"""Self-play generator for the middle-game drill: `baduk-lab drill generate`.

Plays each seed opening forward many times with KataGo's analysis engine,
one move at a time, sampling among near-best candidates so every game
diverges. Games are steered to stay close (see `loss_budget`), because the
drill only wants positions where the score is still within ~10 points --
see MIDGAME_DRILL_DESIGN.md §2.

Why the analysis engine and not `katago selfplay`: selfplay is built for
training data (npz output, training configs) and gives no per-move control,
which the steering rule needs.

Many games are advanced in lockstep (one query per game per round, sent
together through KataGoClient.run_queries) so the GPU sees a batch instead
of one small search at a time.

Output per game, under <out>/<seed-slug>/:
    gNNN.sgf       the generated game (a normal record; open it anywhere)
    gNNN.gen.json  per-position engine summary at generation visits, which
                   drill.py screens instead of re-analyzing whole games
"""

from __future__ import annotations

import json
import logging
import random
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sgfmill import sgf
from sgfmill.common import format_vertex, move_from_vertex

from .engine import DEFAULT_RULES

logger = logging.getLogger(__name__)

Coord = tuple[int, int]


@dataclass
class Seed:
    slug: str                 # filesystem-safe id: file stem, plus --varK for variations
    komi: float
    board_size: int
    moves: list[tuple[str, Coord | None]]  # (color, coord), coord None = pass


@dataclass
class GenSettings:
    gen_visits: int = 100
    stop_at: int = 150          # last move number generated; drill only uses 51-150
    loss_budget: float = 1.5    # normal: sample among moves within this of the best
    leader_budget: float = 3.0  # side ahead by > steer_start samples more loosely
    trailer_budget: float = 0.5 # side behind plays (near-)best moves only
    steer_start: float = 4.0    # |score lead| above which steering kicks in
    abandon_lead: float = 10.0  # stop the game once |lead| stays above this...
    abandon_after: int = 10     # ...for this many consecutive moves
    temperature: float = 1.0    # weights = prior ** (1 / temperature)
    min_visit_share: float = 0.03  # ignore candidates searched less than this share


def load_seeds(folder: Path) -> list[Seed]:
    """Every root-to-leaf line in every SGF under `folder` becomes one
    seed, so a file holding a joseki tree yields one seed per branch."""
    seeds: list[Seed] = []
    for path in sorted(folder.rglob("*.sgf")):
        game = sgf.Sgf_game.from_bytes(path.read_bytes())
        root = game.get_root()
        if game.get_size() != 19 or root.has_property("AB") or root.has_property("AW"):
            logger.warning("Skipping seed %s: only 19x19 seeds without setup "
                           "stones (handicap) are supported", path.name)
            continue
        komi = game.get_komi() if root.has_property("KM") else 6.5
        lines = _leaf_lines(root)
        for index, nodes in enumerate(lines, start=1):
            moves = [node.get_move() for node in nodes]
            moves = [(c, coord) for c, coord in moves if c is not None]
            slug = path.stem if len(lines) == 1 else f"{path.stem}--var{index}"
            seeds.append(Seed(slug=slug, komi=komi, board_size=19, moves=moves))
    return seeds


def _leaf_lines(root) -> list[list]:
    lines = []
    stack = [(root, [])]
    while stack:
        node, path = stack.pop()
        children = list(node)
        if not children:
            lines.append(path)
        # Reversed so variations come out in file order (first child first).
        for child in reversed(children):
            stack.append((child, path + [child]))
    return lines


def mover_score(score_lead_black: float, mover: str) -> float:
    """Convert a Black-perspective score (all KataGo values with this
    repo's config) into the mover's own perspective."""
    return score_lead_black if mover == "b" else -score_lead_black


def loss_budget(lead_for_mover: float, settings: GenSettings) -> float:
    """The steering rule: the side ahead plays a bit looser, the side
    behind plays precisely, so games drift back toward even without anyone
    playing an outright bad move."""
    if abs(lead_for_mover) <= settings.steer_start:
        return settings.loss_budget
    return settings.leader_budget if lead_for_mover > 0 else settings.trailer_budget


def choose_move(move_infos: list[dict], mover: str, lead_for_mover: float,
                settings: GenSettings, rng: random.Random) -> str:
    """Sample one move (GTP vertex string) from the candidates within the
    current loss budget, weighted by policy prior."""
    if not move_infos:
        return "pass"
    best = min(move_infos, key=lambda mi: mi.get("order", 0))
    best_score = mover_score(best["scoreLead"], mover)
    total_visits = sum(mi.get("visits", 0) for mi in move_infos) or 1
    budget = loss_budget(lead_for_mover, settings)

    pool = [
        mi for mi in move_infos
        if mi["move"].lower() != "pass"
        and mi.get("visits", 0) / total_visits >= settings.min_visit_share
        and best_score - mover_score(mi["scoreLead"], mover) <= budget
    ]
    if not pool:
        return best["move"]
    weights = [max(mi.get("prior", 0.0), 1e-6) ** (1.0 / settings.temperature) for mi in pool]
    return rng.choices(pool, weights=weights, k=1)[0]["move"]


@dataclass
class _Game:
    seed: Seed
    index: int
    rng_seed: int
    moves: list[tuple[str, Coord | None]]
    stop_at: int = 150
    positions: list[dict] = field(default_factory=list)
    far_streak: int = 0
    abandoned: bool = False

    @property
    def query_id(self) -> str:
        return f"{self.seed.slug}#g{self.index:03d}"

    @property
    def mover(self) -> str:
        if not self.moves:
            return "b"
        return "w" if self.moves[-1][0] == "b" else "b"

    @property
    def done(self) -> bool:
        return self.abandoned or len(self.moves) >= self.stop_at


def _query_for(game: _Game, visits: int) -> dict:
    size = game.seed.board_size
    return {
        "id": game.query_id,
        "moves": [[c.upper(), format_vertex(coord)] for c, coord in game.moves],
        "rules": DEFAULT_RULES,
        "komi": game.seed.komi,
        "boardXSize": size,
        "boardYSize": size,
        "analyzeTurns": [len(game.moves)],
        "maxVisits": visits,
        "includePolicy": False,
    }


def _advance(game: _Game, response: dict, settings: GenSettings) -> None:
    mover = game.mover
    root = response["rootInfo"]
    lead = mover_score(root["scoreLead"], mover)
    move_infos = response.get("moveInfos", [])
    rng = random.Random(game.rng_seed * 1000 + len(game.moves))
    vertex = choose_move(move_infos, mover, lead, settings, rng)
    best = min(move_infos, key=lambda mi: mi.get("order", 0)) if move_infos else None

    game.positions.append({
        "move_number": len(game.moves) + 1,
        "to_play": mover,
        "score_lead": root["scoreLead"],     # Black's perspective, like the analyze cache
        "winrate": root["winrate"],
        "best": best["move"] if best else "pass",
        "best_score_lead": best["scoreLead"] if best else root["scoreLead"],
        "played": vertex,
    })

    coord = move_from_vertex(vertex, game.seed.board_size) if vertex.lower() != "pass" else None
    game.moves.append((mover, coord))
    if coord is None:
        game.abandoned = True  # a pass in the middle game means the game is over; stop
        return

    game.far_streak = game.far_streak + 1 if abs(lead) > settings.abandon_lead else 0
    if game.far_streak >= settings.abandon_after:
        game.abandoned = True


def _write_game(game: _Game, out_dir: Path, settings: GenSettings) -> None:
    seed_dir = out_dir / game.seed.slug
    seed_dir.mkdir(parents=True, exist_ok=True)
    stem = f"g{game.index:03d}"

    record = sgf.Sgf_game(size=game.seed.board_size)
    root = record.get_root()
    root.set("KM", game.seed.komi)
    root.set("PB", "KataGo selfplay")
    root.set("PW", "KataGo selfplay")
    root.set("GN", f"{game.seed.slug} {stem}")
    root.set("C", (
        f"baduk-lab drill self-play from seed {game.seed.slug} "
        f"(first {len(game.seed.moves)} moves). rng_seed={game.rng_seed}, "
        f"{settings.gen_visits} visits/move, loss budget {settings.loss_budget}"
        + (", stopped early (score too far apart or pass)" if game.abandoned else "")
    ))
    node = root
    for color, coord in game.moves:
        node = node.new_child()
        node.set_move(color, coord)
    (seed_dir / f"{stem}.sgf").write_bytes(record.serialise())

    payload = {
        "seed": game.seed.slug,
        "game": f"{game.seed.slug}/{stem}",
        "rng_seed": game.rng_seed,
        "komi": game.seed.komi,
        "board_size": game.seed.board_size,
        "seed_moves": len(game.seed.moves),
        "abandoned": game.abandoned,
        "settings": asdict(settings),
        "moves": [[c, list(coord) if coord else None] for c, coord in game.moves],
        "positions": game.positions,
    }
    (seed_dir / f"{stem}.gen.json").write_text(json.dumps(payload), encoding="utf-8")


def existing_game_count(out_dir: Path, seed: Seed) -> int:
    return len(list((out_dir / seed.slug).glob("g*.gen.json")))


def generate(client, seeds: list[Seed], games_per_seed: int, out_dir: Path,
             settings: GenSettings, parallel: int = 16) -> dict[str, int]:
    """Top up every seed to `games_per_seed` generated games. Returns
    {"generated": n, "abandoned": m}. `client` is a KataGoClient (or
    anything with a compatible run_queries)."""
    jobs: list[tuple[Seed, int]] = []
    for seed in seeds:
        have = existing_game_count(out_dir, seed)
        jobs += [(seed, i) for i in range(have + 1, games_per_seed + 1)]
    total = len(jobs)
    logger.info("%d game(s) to generate across %d seed(s)", total, len(seeds))

    active: list[_Game] = []
    generated = abandoned = 0
    while jobs or active:
        while jobs and len(active) < parallel:
            seed, index = jobs.pop(0)
            game = _Game(seed=seed, index=index,
                         rng_seed=zlib.crc32(f"{seed.slug}:{index}".encode()),
                         moves=list(seed.moves), stop_at=settings.stop_at)
            active.append(game)

        responses = client.run_queries([_query_for(g, settings.gen_visits) for g in active])
        still_active = []
        for game in active:
            _advance(game, responses[game.query_id], settings)
            if game.done:
                _write_game(game, out_dir, settings)
                generated += 1
                abandoned += int(game.abandoned)
                logger.info("[%d/%d] %s g%03d: %d moves%s", generated, total,
                           game.seed.slug, game.index, len(game.moves),
                           " (stopped early)" if game.abandoned else "")
            else:
                still_active.append(game)
        active = still_active
    return {"generated": generated, "abandoned": abandoned}
