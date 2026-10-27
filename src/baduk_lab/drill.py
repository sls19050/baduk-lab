"""Middle-game "answer or tenuki?" drill deck: `baduk-lab drill build`.

Turns self-play games (selfplay.py) into quiz positions where the choice
between answering the opponent's last move locally and playing elsewhere
is worth at least `min_gap` points, with the score still within
`score_window` points. See MIDGAME_DRILL_DESIGN.md §1 and §3.

Per generated game (several games at a time, so each phase's queries
batch together on the GPU):
1. Screen: every middle-game position that passes the cheap filters
   (score window at generation visits, no recent single-stone capture,
   last move not a pass) gets one low-visit probe query that forces the
   side (local/tenuki) the generation search didn't pick. That gives a
   rough gap for every position at a fraction of full-analysis cost.
2. Verify: the most promising few are re-run at full visits -- one
   unrestricted query plus one probe -- and kept only if the full-visit
   score is in the window and the gap still clears `min_gap`.
3. Pick at most `max_per_game`, `min_spacing` moves apart, so one game
   doesn't flood the deck with near-identical positions.

Results are cached per game under <out>/cache/, keyed on the gen.json
content and every setting that changes the outcome, so re-running only
pays for games added since the last build.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from sgfmill import sgf as sgf_lib
from sgfmill.common import format_vertex, move_from_vertex

from . import board, metrics
from .engine import DEFAULT_RULES
from .selfplay import mover_score

logger = logging.getLogger(__name__)

Coord = tuple[int, int]

KO_LOOKBACK = 4             # skip positions with a single-stone capture in the last N moves
ACCEPT_VISIT_SHARE = 0.10   # an alternative answer needs this share of root visits...
ACCEPT_MIN_TOLERANCE = 1.0  # ...and to be within max(this, ACCEPT_GAP_SHARE * |gap|) points
ACCEPT_GAP_SHARE = 0.15
GAP_CAP = 8.0               # gaps beyond this rank no higher when picking positions
SCORE_TOLERANCE = 3.0       # a score estimate within this many points counts as right
_SCHEMA = 2


@dataclass
class DrillSettings:
    visits: int = 500           # verification visits (same default as `analyze`)
    screen_visits: int = 100
    radius: int = 3             # "local" = within this Chebyshev distance of the last move...
    group_reach: int = 5        # ...or next to a liberty of a group it touched, this close
    score_window: float = 10.0  # |score lead| for the side to move must be within this
    min_gap: float = 2.0
    max_per_game: int = 3
    tenuki_per_game: int = 2    # of max_per_game; tenuki positions are rarer in
                                # self-play, so they get reserved slots
    min_spacing: int = 15


@dataclass
class DrillProblem:
    problem_id: str
    game: str                 # "<seed-slug>/gNNN", key into games.json
    seed: str
    move_number: int
    mover: str                # "b"/"w"
    kind: str                 # "tenuki" or "answer"
    gap: float                # best tenuki minus best local, mover's points
    points_lost: float        # |gap|, so quiz.due_problems sorts biggest first
    score_lead: float         # mover's lead before the move, full visits
    last_move: str
    best_local: str
    best_local_score: float   # mover's perspective
    best_tenuki: str
    best_tenuki_score: float
    accepted: list[str]       # every vertex graded correct in the "where?" step
    accepted_scores: list[float]  # mover's score after each accepted move, same order
    region: list[str]         # the local region (§1), so the quiz can label a
                              # click "local" or "tenuki" without re-deriving it
    path: str                 # problem SGF, relative to problems/


# --- locality -----------------------------------------------------------

def _chebyshev(a: Coord, b: Coord) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def local_region(stones: dict[Coord, str], last: Coord, size: int,
                 radius: int = 3, group_reach: int = 5) -> set[Coord]:
    """Empty points counted as answering `last` (the opponent's previous
    move, already on `stones`): everything within `radius`, plus points on
    or next to a liberty of any group `last` touched (its own, or one it's
    adjacent to), as long as they're within `group_reach` of it. The
    second rule catches replies like extending a group the move pressed on
    or saving a stone it put in atari."""
    region = {
        (r, c)
        for r in range(max(0, last[0] - radius), min(size, last[0] + radius + 1))
        for c in range(max(0, last[1] - radius), min(size, last[1] + radius + 1))
        if (r, c) not in stones
    }
    seen: set[Coord] = set()
    for start in [last] + board.neighbors(last, size):
        if start not in stones or start in seen:
            continue
        group, liberties = board.group_and_liberties(stones, start, size)
        seen |= group
        for lib in liberties:
            if _chebyshev(lib, last) > group_reach:
                continue
            region.add(lib)
            for n in board.neighbors(lib, size):
                if n not in stones and _chebyshev(n, last) <= group_reach:
                    region.add(n)
    return region


# --- evaluating one position ---------------------------------------------

def _best(move_infos: list[dict]) -> dict | None:
    return min(move_infos, key=lambda mi: mi.get("order", 0)) if move_infos else None


def _coord(vertex: str, size: int) -> Coord | None:
    return None if vertex.lower() == "pass" else move_from_vertex(vertex, size)


def evaluate(unrestricted: list[dict], probe: list[dict], mover: str,
             region: set[Coord], size: int) -> dict | None:
    """Combine an unrestricted search with a probe that forced the other
    side into the position's verdict. Both arguments are KataGo moveInfos
    lists (Black-perspective scores). Returns None when either search came
    back empty or chose to pass."""
    u_best, p_best = _best(unrestricted), _best(probe)
    if u_best is None or p_best is None:
        return None
    u_coord, p_coord = _coord(u_best["move"], size), _coord(p_best["move"], size)
    if u_coord is None or p_coord is None:
        return None

    if u_coord in region:
        local_infos, tenuki_infos = unrestricted, probe
    else:
        local_infos, tenuki_infos = probe, unrestricted
    local_best, tenuki_best = _best(local_infos), _best(tenuki_infos)
    local_score = mover_score(local_best["scoreLead"], mover)
    tenuki_score = mover_score(tenuki_best["scoreLead"], mover)
    gap = tenuki_score - local_score

    # Tolerant answer key, from whichever search covered the winning side.
    win_infos, win_is_local = (tenuki_infos, False) if gap > 0 else (local_infos, True)
    win_best = tenuki_best if gap > 0 else local_best
    win_score = mover_score(win_best["scoreLead"], mover)
    tolerance = max(ACCEPT_MIN_TOLERANCE, ACCEPT_GAP_SHARE * abs(gap))
    total_visits = sum(mi.get("visits", 0) for mi in win_infos) or 1
    accepted = [win_best["move"]]
    accepted_scores = [win_score]
    for mi in win_infos:
        coord = _coord(mi["move"], size)
        if coord is None or mi["move"] in accepted:
            continue
        if (coord in region) != win_is_local:
            continue
        mi_score = mover_score(mi["scoreLead"], mover)
        if (mi.get("visits", 0) / total_visits >= ACCEPT_VISIT_SHARE
                and win_score - mi_score <= tolerance):
            accepted.append(mi["move"])
            accepted_scores.append(mi_score)

    return {
        "gap": gap,
        "best_local": local_best["move"], "best_local_score": local_score,
        "best_tenuki": tenuki_best["move"], "best_tenuki_score": tenuki_score,
        "accepted": accepted, "accepted_scores": accepted_scores,
    }


# --- queries ------------------------------------------------------------

def _query(qid: str, gen: dict, move_number: int, visits: int,
           restrict: tuple[str, str, set[Coord]] | None = None) -> dict:
    """Query for the position before `move_number`. `restrict` is
    ("allowMoves"|"avoidMoves", mover, region) for a probe."""
    q = {
        "id": qid,
        "moves": [[c.upper(), format_vertex(tuple(coord) if coord else None)]
                  for c, coord in gen["moves"][: move_number - 1]],
        "rules": DEFAULT_RULES,
        "komi": gen["komi"],
        "boardXSize": gen["board_size"],
        "boardYSize": gen["board_size"],
        "analyzeTurns": [move_number - 1],
        "maxVisits": visits,
        "includePolicy": False,
    }
    if restrict:
        key, mover, region = restrict
        q[key] = [{"player": mover.upper(),
                   "moves": sorted(format_vertex(p) for p in region),
                   "untilDepth": 1}]
    return q


def _run_batched(client, queries: list[dict], batch: int = 64) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(queries), batch):
        out.update(client.run_queries(queries[i:i + batch]))
    return out


# --- per-game pipeline ---------------------------------------------------

@dataclass
class _Candidate:
    move_number: int
    mover: str
    last: Coord
    region: set[Coord]
    gen_best: str
    gen_best_score: float     # mover's perspective, generation visits


def candidates(gen: dict, settings: DrillSettings) -> list[_Candidate]:
    """Cheap filters only -- no engine calls."""
    size = gen["board_size"]
    tuples = [(i + 1, c, tuple(coord) if coord else None)
              for i, (c, coord) in enumerate(gen["moves"])]
    captures = board.single_stone_captures(tuples, size)
    out = []
    for pos in gen["positions"]:
        n = pos["move_number"]
        if not (metrics.OPENING_END < n <= metrics.MIDDLE_END) or n < 2:
            continue
        last = tuples[n - 2][2]
        if last is None:
            continue
        if any(m in captures for m in range(n - KO_LOOKBACK, n)):
            continue
        mover = pos["to_play"]
        # Slightly wider than the final window: generation visits are noisy,
        # and the full-visit verify step applies the real window.
        if abs(mover_score(pos["score_lead"], mover)) > settings.score_window + 2:
            continue
        stones = board.board_before(tuples, size, n)
        region = local_region(stones, last, size, settings.radius, settings.group_reach)
        if not region or len(region) + len(stones) >= size * size:
            continue
        out.append(_Candidate(n, mover, last, region, pos["best"],
                              mover_score(pos["best_score_lead"], mover)))
    return out


def _rank_key(gap: float) -> tuple[float, float]:
    """Bigger gap first, but only up to GAP_CAP: past that, a position is
    usually a must-save-the-group fight (an easy "answer") rather than the
    whole-board judgement the drill is for, so smaller gaps win ties."""
    g = abs(gap)
    return (min(g, GAP_CAP), -g)


def _pick_spaced(items: list, key_gap, key_move, quotas: dict[str, int], limit: int,
                 spacing: int) -> list:
    """Greedy pick by _rank_key, at least `spacing` moves apart. A first
    pass honours per-kind `quotas` ("tenuki"/"answer"); a second fills any
    leftover room with whichever kind is still available."""
    ranked = sorted(items, key=lambda x: _rank_key(key_gap(x)), reverse=True)
    chosen: list = []
    counts = {"tenuki": 0, "answer": 0}
    for use_quotas in (True, False):
        for item in ranked:
            if len(chosen) >= limit:
                return chosen
            kind = "tenuki" if key_gap(item) > 0 else "answer"
            if item in chosen or (use_quotas and counts[kind] >= quotas[kind]):
                continue
            if all(abs(key_move(item) - key_move(c)) >= spacing for c in chosen):
                chosen.append(item)
                counts[kind] += 1
    return chosen


def _side_restrict(c: _Candidate, best_vertex: str, size: int) -> tuple[str, str, set[Coord]]:
    """Probe restriction forcing the side `best_vertex` is NOT on."""
    best_is_local = _coord(best_vertex, size) in c.region
    return ("avoidMoves" if best_is_local else "allowMoves", c.mover, c.region)


def process_games(client, gens: list[dict], settings: DrillSettings) -> list[list[DrillProblem]]:
    """Run the screen -> verify -> pick pipeline for several games at once,
    batching each phase's queries across all of them (verification alone
    is only a handful of queries per game, too few to fill the GPU).
    Returns one problem list per input game, in order."""
    # Query ids are "<game index>|<phase><move number>".
    cands = [candidates(gen, settings) for gen in gens]

    # 1. Screen: one low-visit probe per candidate, forcing the side the
    # generation search didn't choose.
    screen_q = [
        _query(f"{gi}|s{c.move_number}", gen, c.move_number, settings.screen_visits,
               _side_restrict(c, c.gen_best, gen["board_size"]))
        for gi, gen in enumerate(gens) for c in cands[gi]
        if _coord(c.gen_best, gen["board_size"]) is not None
    ]
    screen = _run_batched(client, screen_q)

    shortlists = []
    for gi, gen in enumerate(gens):
        size = gen["board_size"]
        screened = []
        for c in cands[gi]:
            r = screen.get(f"{gi}|s{c.move_number}")
            probe_best = _best(r.get("moveInfos", [])) if r else None
            if probe_best is None:
                continue
            probe_score = mover_score(probe_best["scoreLead"], c.mover)
            gen_is_local = _coord(c.gen_best, size) in c.region
            gap = (probe_score - c.gen_best_score) if gen_is_local else (c.gen_best_score - probe_score)
            if abs(gap) >= 0.75 * settings.min_gap:
                screened.append((c, gap))
        shortlists.append(_pick_spaced(
            screened, lambda x: x[1], lambda x: x[0].move_number,
            # Tenuki candidates are scarce and most don't survive full-visit
            # verification, so send more of them through; verifying is cheap
            # next to generating more games.
            {"tenuki": 2 * settings.max_per_game, "answer": settings.max_per_game},
            3 * settings.max_per_game, settings.min_spacing // 3))

    # 2. Verify at full visits: unrestricted first (it decides which side
    # the probe has to force), then the probe.
    full = _run_batched(client, [
        _query(f"{gi}|u{c.move_number}", gens[gi], c.move_number, settings.visits)
        for gi, shortlist in enumerate(shortlists) for c, _ in shortlist
    ])
    probe_q = []
    for gi, shortlist in enumerate(shortlists):
        size = gens[gi]["board_size"]
        for c, _ in shortlist:
            u_best = _best(full[f"{gi}|u{c.move_number}"].get("moveInfos", []))
            if u_best is not None and _coord(u_best["move"], size) is not None:
                probe_q.append(_query(f"{gi}|p{c.move_number}", gens[gi], c.move_number,
                                      settings.visits, _side_restrict(c, u_best["move"], size)))
    probes = _run_batched(client, probe_q)

    # 3. Final pick per game.
    results = []
    for gi, gen in enumerate(gens):
        verified = []
        for c, _ in shortlists[gi]:
            u = full[f"{gi}|u{c.move_number}"]
            pr = probes.get(f"{gi}|p{c.move_number}")
            if pr is None:
                continue
            lead = mover_score(u["rootInfo"]["scoreLead"], c.mover)
            if abs(lead) > settings.score_window:
                continue
            verdict = evaluate(u.get("moveInfos", []), pr.get("moveInfos", []),
                               c.mover, c.region, gen["board_size"])
            if verdict is None or abs(verdict["gap"]) < settings.min_gap:
                continue
            verified.append((c, lead, verdict))
        final = _pick_spaced(verified, lambda x: x[2]["gap"], lambda x: x[0].move_number,
                             {"tenuki": settings.tenuki_per_game,
                              "answer": settings.max_per_game - settings.tenuki_per_game},
                             settings.max_per_game, settings.min_spacing)
        results.append([_problem(gen, c, lead, v)
                        for c, lead, v in sorted(final, key=lambda x: x[0].move_number)])
    return results


def _problem(gen: dict, c: _Candidate, lead: float, v: dict) -> DrillProblem:
    slug, stem = gen["game"].split("/")
    return DrillProblem(
        problem_id=f"selfplay::{slug}::{stem}::m{c.move_number}",
        game=gen["game"], seed=gen["seed"], move_number=c.move_number,
        mover=c.mover, kind="tenuki" if v["gap"] > 0 else "answer",
        gap=round(v["gap"], 2), points_lost=round(abs(v["gap"]), 2),
        score_lead=round(lead, 2), last_move=format_vertex(c.last),
        best_local=v["best_local"], best_local_score=round(v["best_local_score"], 2),
        best_tenuki=v["best_tenuki"], best_tenuki_score=round(v["best_tenuki_score"], 2),
        accepted=v["accepted"],
        accepted_scores=[round(x, 2) for x in v["accepted_scores"]],
        region=sorted(format_vertex(p) for p in c.region),
        path=f"{slug}/{stem}_m{c.move_number:03d}.sgf",
    )


# --- build: all games -> deck on disk -------------------------------------

def _round_robin_by_seed(gen_paths: list[Path]) -> list[Path]:
    """Interleave the games one seed folder at a time: g001 of every seed,
    then g002 of every seed, and so on. Plain alphabetical order would
    probe one seed to exhaustion before touching the next, so a build done
    in `max_games` batches (or stopped early) would leave a deck of
    nothing but the first opening."""
    by_seed: dict[str, list[Path]] = {}
    for path in gen_paths:
        by_seed.setdefault(str(path.parent), []).append(path)
    out: list[Path] = []
    for i in range(max((len(v) for v in by_seed.values()), default=0)):
        out += [by_seed[k][i] for k in sorted(by_seed) if i < len(by_seed[k])]
    return out


def _cache_key(gen_path: Path, model: str, settings: DrillSettings) -> dict:
    return {
        "gen_sha256": hashlib.sha256(gen_path.read_bytes()).hexdigest(),
        "model": model,
        "settings": asdict(settings),
        "schema": _SCHEMA,
    }


def build(client, selfplay_dir: Path, out_dir: Path, settings: DrillSettings,
          model: str, group: int = 8, max_games: int | None = None) -> list[DrillProblem]:
    """Process every gen.json under selfplay_dir (cached per game) and
    write the deck: problems/index.json, problems/games.json and one SGF
    per problem.

    `max_games` probes at most that many *uncached* games and leaves the
    rest for a later run, so a big selfplay folder can be worked through a
    batch at a time (each run restarts the engine, which is what keeps peak
    memory down). Already-cached games are always included in the deck, so
    the deck grows with every batch instead of being replaced."""
    problems_dir = out_dir / "problems"
    cache_dir = out_dir / "cache"
    gen_paths = _round_robin_by_seed(sorted(selfplay_dir.rglob("g*.gen.json")))
    all_problems: list[DrillProblem] = []
    games: dict[str, dict] = {}

    # Cached games are reused as-is; the rest are probed in groups of
    # `group` so each engine phase batches across several games.
    by_game: dict[str, list[DrillProblem]] = {}
    gens: dict[str, dict] = {}
    todo: list[tuple[Path, dict, dict]] = []
    for gen_path in gen_paths:
        gen = json.loads(gen_path.read_text(encoding="utf-8"))
        gens[gen["game"]] = gen
        key = _cache_key(gen_path, model, settings)
        cache_path = cache_dir / f"{gen['game']}.json"
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if payload.get("key") == key:
                by_game[gen["game"]] = [DrillProblem(**p) for p in payload["problems"]]
                continue
        todo.append((gen_path, gen, key))

    cached = len(gen_paths) - len(todo)
    if max_games is not None and len(todo) > max_games:
        logger.info("%d game(s) to probe, this batch takes %d; rerun to continue",
                    len(todo), max_games)
        todo = todo[:max_games]
    if todo:
        logger.info("%d game(s) cached, %d to probe", cached, len(todo))
    for i in range(0, len(todo), group):
        chunk = todo[i:i + group]
        logger.info("Probing games %d-%d of %d...", i + 1, i + len(chunk), len(todo))
        for (_, gen, key), problems in zip(chunk, process_games(client, [g for _, g, _ in chunk],
                                                                settings)):
            by_game[gen["game"]] = problems
            cache_path = cache_dir / f"{gen['game']}.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"key": key, "problems": [asdict(p) for p in problems]}),
                                  encoding="utf-8")

    for game_key in sorted(by_game):
        if by_game[game_key]:
            all_problems += by_game[game_key]
            gen = gens[game_key]
            games[game_key] = {"board_size": gen["board_size"], "komi": gen["komi"],
                               "moves": gen["moves"]}

    problems_dir.mkdir(parents=True, exist_ok=True)
    for p in all_problems:
        _write_problem_sgf(p, games[p.game], problems_dir / p.path)
    (problems_dir / "index.json").write_text(
        json.dumps([asdict(p) for p in all_problems], indent=2), encoding="utf-8")
    (problems_dir / "games.json").write_text(json.dumps(games), encoding="utf-8")
    return all_problems


def load_index(problems_dir: Path) -> list[DrillProblem]:
    data = json.loads((problems_dir / "index.json").read_text(encoding="utf-8"))
    return [DrillProblem(**p) for p in data]


def _side(color: str) -> str:
    return "Black" if color == "b" else "White"


def _write_problem_sgf(p: DrillProblem, game: dict, path: Path) -> None:
    """Main line stops before the move to find; the best tenuki and best
    local answer are sibling variations, the correct one first."""
    size = game["board_size"]
    record = sgf_lib.Sgf_game(size=size)
    root = record.get_root()
    root.set("KM", game["komi"])
    root.set("C", (f"Self-play from seed {p.seed}, move {p.move_number}. "
                   f"{_side(p.mover)} to play, {p.score_lead:+.1f} points. "
                   f"Opponent just played {p.last_move}: answer it, or tenuki?"))
    node = root
    for c, coord in game["moves"][: p.move_number - 1]:
        node = node.new_child()
        node.set_move(c, tuple(coord) if coord else None)

    tenuki_note = f"Best tenuki ({p.best_tenuki_score:+.1f})."
    local_note = f"Best local answer ({p.best_local_score:+.1f})."
    lines = [(p.best_tenuki, tenuki_note), (p.best_local, local_note)]
    if p.kind == "answer":
        lines.reverse()
    for vertex, note in lines:
        child = node.new_child()
        child.set_move(p.mover, move_from_vertex(vertex, size))
        child.set("C", note)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(record.serialise())


# --- sessions ------------------------------------------------------------

def _spread(items: list, key) -> list:
    """Round-robin the items by `key`, preserving the order within each
    group and taking the groups in order of first appearance."""
    groups: dict = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    out: list = []
    for i in range(max((len(g) for g in groups.values()), default=0)):
        out += [g[i] for g in groups.values() if i < len(g)]
    return out


def _spread_by_source(problems: list[DrillProblem]) -> list[DrillProblem]:
    """Reorder a biggest-gap-first list so it alternates between seed
    openings, and between games within a seed, while each seed's own
    problems stay in gap order.

    Taking the top N of a purely gap-ranked list skews a session towards
    whichever opening happens to throw the biggest gaps (and towards the
    seed with the most problems built), so you would drill one joseki over
    and over. Spreading first means the N picked are spread over all the
    openings that are due, and it still prefers each opening's worst
    positions."""
    by_seed: dict[str, list[DrillProblem]] = {}
    for problem in problems:
        by_seed.setdefault(problem.seed, []).append(problem)
    regrouped: list[DrillProblem] = []
    for seed_problems in by_seed.values():
        regrouped += _spread(seed_problems, lambda p: p.game)
    return _spread(regrouped, lambda p: p.seed)


def compose_session(due: list[DrillProblem], limit: int, tenuki_share: float = 0.6,
                    rng: random.Random | None = None, max_run: int = 3) -> list[DrillProblem]:
    """Pick `limit` problems from `due` (already biggest-first) with about
    `tenuki_share` of them tenuki, the rest answer-locally, spread over the
    seed openings that are due, then order them so the answer is never the
    same more than `max_run` times in a row -- a deck that's all "tenuki"
    would just train the opposite reflex."""
    rng = rng or random.Random()
    tenuki = _spread_by_source([p for p in due if p.kind == "tenuki"])
    answer = _spread_by_source([p for p in due if p.kind == "answer"])
    n_tenuki = min(len(tenuki), round(limit * tenuki_share))
    n_answer = min(len(answer), limit - n_tenuki)
    if n_tenuki:
        # Keep the ratio even when tenuki positions run short: a session
        # padded out with answer-locally positions would mostly train the
        # very follow-the-opponent reflex this drill is meant to break.
        n_answer = min(n_answer, max(1, round(n_tenuki * (1 - tenuki_share) / tenuki_share)))
    n_tenuki = min(len(tenuki), limit - n_answer)  # top up if answers ran short
    pools = {"tenuki": tenuki[:n_tenuki], "answer": answer[:n_answer]}
    for pool in pools.values():
        rng.shuffle(pool)

    session: list[DrillProblem] = []
    last, run = None, 0
    while pools["tenuki"] or pools["answer"]:
        kinds = [k for k, v in pools.items() if v]
        # Random order weighted by what's left, then take the first pick
        # that keeps the rest arrangeable without a run over max_run. If
        # none can (one kind simply outnumbers the other too much), the
        # long run is unavoidable and the random pick stands.
        order = []
        while kinds:
            k = rng.choices(kinds, weights=[len(pools[x]) for x in kinds], k=1)[0]
            order.append(k)
            kinds.remove(k)
        choice = order[0]
        for k in order:
            new_run = run + 1 if k == last else 1
            if new_run > max_run:
                continue
            left = {x: len(pools[x]) - (x == k) for x in pools}
            other = "answer" if k == "tenuki" else "tenuki"
            if (left[k] <= (max_run - new_run) + max_run * left[other]
                    and left[other] <= max_run * (left[k] + 1)):
                choice = k
                break
        run = run + 1 if choice == last else 1
        last = choice
        session.append(pools[choice].pop())
    return session
