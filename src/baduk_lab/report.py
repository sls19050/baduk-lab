"""Render metrics into report.md and export the problem-set SGFs.

Report structure:
- Header: games analyzed, player, date range, engine/model/visits used.
- Section per metric, each with one plain-language takeaway line
  ("Most of your losses happen in the middle game, and they are many small
  leaks rather than single blunders").
- Problem set: table of extracted positions linking to problems/*.sgf.
  Each problem SGF contains the position before your mistake, with your
  actual move and KataGo's preferred move stored as comments/variations
  so the answer is one click away but not spoiled.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from sgfmill import sgf as sgf_lib
from sgfmill.common import move_from_vertex

from . import metrics
from .engine import GameAnalysis


def render_report(out_dir: Path, *, player: str, analyses: list[GameAnalysis],
                  phase_loss: metrics.PhaseLoss, magnitude: metrics.MagnitudeProfile,
                  ahead_behind: metrics.AheadBehindSplit,
                  problems: list[metrics.ProblemPosition],
                  model: str, visits: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dates = sorted(a.record.date for a in analyses if a.record.date)
    date_range = f"{dates[0]} to {dates[-1]}" if dates else "unknown"

    lines = [
        f"# baduk-lab report: {player}",
        "",
        f"- Games analyzed: {len(analyses)}",
        f"- Date range: {date_range}",
        f"- Engine: KataGo, model `{model}`, {visits} visits/position",
        "",
        "## Where your points leak",
        "",
        f"- Opening (moves 1-{metrics.OPENING_END}): {phase_loss.opening:.2f} pts/move "
        f"({phase_loss.opening_total:.1f} pts total)",
        f"- Middle game (moves {metrics.OPENING_END + 1}-{metrics.MIDDLE_END}): "
        f"{phase_loss.middle:.2f} pts/move ({phase_loss.middle_total:.1f} pts total)",
        f"- Endgame (moves {metrics.MIDDLE_END + 1}+): {phase_loss.endgame:.2f} pts/move "
        f"({phase_loss.endgame_total:.1f} pts total)",
        "",
        _phase_takeaway(phase_loss),
        "",
        "## Mistake magnitude profile",
        "",
    ]
    for label, _, _ in metrics.MAGNITUDE_BUCKETS:
        lines.append(f"- {label} points: {magnitude.buckets.get(label, 0)} moves")
    lines += [
        f"- Blunders (8+ points) per game: {magnitude.blunders_per_game:.2f}",
        f"- Leak rate (1-3 point moves): {magnitude.leak_rate:.1%}",
        "",
        _magnitude_takeaway(magnitude),
        "",
        "## Ahead/behind behavior",
        "",
        f"- Mean points lost per move when ahead (winrate >= {metrics.AHEAD:.0%}): "
        f"{ahead_behind.mean_loss_when_ahead:.2f}",
        f"- Mean points lost per move when close: {ahead_behind.mean_loss_when_close:.2f}",
        f"- Mean points lost per move when behind (winrate <= {metrics.BEHIND:.0%}): "
        f"{ahead_behind.mean_loss_when_behind:.2f}",
        "",
        _ahead_behind_takeaway(ahead_behind),
        "",
        "## Problem set",
        "",
        f"{len(problems)} positions extracted to `problems/` "
        f"(losing {metrics.PROBLEM_THRESHOLD}+ points). Run `baduk-lab review` to "
        "drill them; re-running `analyze` later only adds new mistakes, it "
        "doesn't reset your review progress.",
        "",
        "| # | Phase | Game | Move | Points lost | File |",
        "|---|-------|------|------|-------------|------|",
    ]
    for i, p in enumerate(problems, start=1):
        relpath = _problem_relpath(p)
        lines.append(f"| {i} | {metrics.phase_of(p.move_number)} | {p.game} | "
                     f"{p.move_number} | {p.points_lost:.1f} | "
                     f"[{relpath}](problems/{relpath}) |")

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _phase_takeaway(phase_loss: metrics.PhaseLoss) -> str:
    totals = {"opening": phase_loss.opening_total, "middle": phase_loss.middle_total,
              "endgame": phase_loss.endgame_total}
    worst_phase = max(totals, key=totals.get)
    return f"**Takeaway:** most of your total points are lost in the {worst_phase}."


def _magnitude_takeaway(magnitude: metrics.MagnitudeProfile) -> str:
    if magnitude.blunders_per_game >= 1:
        return ("**Takeaway:** you're averaging a full blunder (8+ points) per game — "
                "double-checking reads before big moves matters more right now than "
                "fine endgame technique.")
    return ("**Takeaway:** you rarely blunder outright; most of your loss is a steady "
            "drip of small leaks, which points to technique refinement over reading errors.")


def _ahead_behind_takeaway(ahead_behind: metrics.AheadBehindSplit) -> str:
    if ahead_behind.mean_loss_when_ahead > ahead_behind.mean_loss_when_behind:
        return ("**Takeaway:** your move quality drops more when you're ahead than when "
                "you're behind — you may be coasting.")
    if ahead_behind.mean_loss_when_behind > ahead_behind.mean_loss_when_ahead:
        return ("**Takeaway:** your move quality drops more when you're behind than when "
                "you're ahead — you may be flailing.")
    return "**Takeaway:** your move quality is roughly stable whether ahead or behind."


def _problem_relpath(problem: metrics.ProblemPosition) -> str:
    """Stable, phase-grouped relative path under problems/ -- derived from
    the source game + move number (not sort position), so re-running
    `analyze` with new games mixed in doesn't rename/duplicate files you've
    already reviewed."""
    phase = metrics.phase_of(problem.move_number)
    stem = Path(problem.game).stem
    return f"{phase}/{stem}_m{problem.move_number:03d}.sgf"


def export_problem_sgfs(problems: list[metrics.ProblemPosition], out_dir: Path,
                        analyses: list[GameAnalysis]) -> None:
    """Export each problem position as its own SGF, grouped into
    opening/middle/endgame subfolders. The main line stops right before the
    mistake (so your move is hidden); what you played and KataGo's preferred
    move are stored as two sibling variations, one click away but not
    spoiled on open."""
    out_dir.mkdir(parents=True, exist_ok=True)
    by_game = {a.record.path.name: a for a in analyses}

    for problem in problems:
        analysis = by_game.get(problem.game)
        if analysis is None:
            continue
        record = analysis.record
        prefix = record.moves[: problem.move_number - 1]
        mover = "b" if problem.move_number % 2 == 1 else "w"

        game = sgf_lib.Sgf_game(size=record.board_size)
        root = game.get_root()
        root.set("KM", record.komi)
        root.set("PB", record.player_black)
        root.set("PW", record.player_white)
        root.set("C",
            f"From {problem.game}, move {problem.move_number}. "
            f"{'Black' if mover == 'b' else 'White'} to play. "
            f"{problem.points_lost:.1f} points were lost here.")

        node = root
        for move in prefix:
            node = node.new_child()
            node.set_move(move.color, move.coord)

        played = node.new_child()
        played.set_move(mover, move_from_vertex(problem.played, record.board_size))
        played.set("C", f"What was actually played ({problem.points_lost:.1f} points lost).")

        best = node.new_child()
        best.set_move(mover, move_from_vertex(problem.best, record.board_size))
        best.set("C", "KataGo's preferred move.")

        path = out_dir / _problem_relpath(problem)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(game.serialise())


@dataclass
class ProblemIndexEntry:
    """Machine-readable mirror of one ProblemPosition, as written to
    problems/index.json. `quiz.py`'s review-scheduling functions accept
    either this or a metrics.ProblemPosition -- both expose the
    `problem_id`/`points_lost` attributes they need. `played`/`best` (SGF
    vertex strings, e.g. "Q16") are what quiz_html.py needs to grade a
    click and mark the board without re-running KataGo."""
    problem_id: str
    game: str
    move_number: int
    phase: str
    points_lost: float
    path: str
    played: str
    best: str


def export_problem_index(problems: list[metrics.ProblemPosition], out_dir: Path) -> Path:
    """Write problems/index.json: the full current problem set, keyed by
    stable problem_id. This is what `baduk-lab review` reads -- it never
    needs to re-run KataGo or re-derive problems itself."""
    entries = [
        ProblemIndexEntry(
            problem_id=p.problem_id, game=p.game, move_number=p.move_number,
            phase=metrics.phase_of(p.move_number), points_lost=p.points_lost,
            path=_problem_relpath(p), played=p.played, best=p.best,
        )
        for p in problems
    ]
    path = out_dir / "index.json"
    path.write_text(json.dumps([asdict(e) for e in entries], indent=2), encoding="utf-8")
    return path


def load_problem_index(out_dir: Path) -> list[ProblemIndexEntry]:
    """Read back problems/index.json written by export_problem_index."""
    data = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    return [ProblemIndexEntry(**entry) for entry in data]


def export_game_records(analyses: list[GameAnalysis], out_dir: Path) -> Path:
    """Write problems/games.json: {game_filename: {board_size, moves:
    [[color, row, col_or_null], ...]}} for every analyzed game. This is
    what quiz_html.py uses to reconstruct any problem's pre-mistake board
    (via board.board_before) without re-parsing the original SGF/.gib
    source folder, which `review` has no reason to touch."""
    games = {
        analysis.record.path.name: {
            "board_size": analysis.record.board_size,
            "moves": [[m.color, list(m.coord) if m.coord else None]
                     for m in analysis.record.moves],
        }
        for analysis in analyses
    }
    path = out_dir / "games.json"
    path.write_text(json.dumps(games), encoding="utf-8")
    return path
