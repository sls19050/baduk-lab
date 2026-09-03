"""Diagnosis metrics: pure functions from analyses to numbers.

No I/O in this module. Everything here is unit-testable with synthetic data.

MVP metrics (honest at ~8 games):

1. phase_loss_distribution   Where do points leak: opening / middle / endgame?
2. magnitude_profile         One big blunder per game, or death by 1-point cuts?
3. ahead_behind_split        Quality when winning vs. losing (coasting/flailing).
4. problem_positions         Every mistake above a threshold -> drill set.

Deliberately NOT in MVP (sample too small to be honest):
- per-region or per-joseki weakness claims
- opening repertoire analysis
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sgfmill.common import format_vertex

from .engine import GameAnalysis

# Move-number boundaries for phases. Crude but robust; revisit later.
OPENING_END = 50
MIDDLE_END = 150

# A move losing at least this many points becomes a drill problem.
PROBLEM_THRESHOLD = 4.0

# Winrate bands for ahead/behind analysis (mover's perspective).
AHEAD = 0.65
BEHIND = 0.35

# Magnitude buckets: (label, lower bound inclusive, upper bound exclusive).
MAGNITUDE_BUCKETS = [
    ("0-1", 0.0, 1.0),
    ("1-3", 1.0, 3.0),
    ("3-8", 3.0, 8.0),
    ("8+", 8.0, float("inf")),
]
BLUNDER_THRESHOLD = 8.0
LEAK_RANGE = (1.0, 3.0)


@dataclass
class PhaseLoss:
    opening: float   # mean points lost per move in each phase
    middle: float
    endgame: float
    opening_total: float  # and totals per game, for "where the game is lost"
    middle_total: float
    endgame_total: float


@dataclass
class MagnitudeProfile:
    """Histogram of per-move losses, plus summary stats."""
    buckets: dict[str, int]      # e.g. {"0-1": 412, "1-3": 88, "3-8": 21, "8+": 6}
    blunders_per_game: float     # moves losing 8+ points
    leak_rate: float             # share of moves losing 1-3 points


@dataclass
class AheadBehindSplit:
    mean_loss_when_ahead: float
    mean_loss_when_close: float
    mean_loss_when_behind: float


@dataclass
class ProblemPosition:
    game: str          # sgf filename
    move_number: int
    points_lost: float
    played: str        # what you played, e.g. "Q10"
    best: str          # KataGo's preferred move

    @property
    def problem_id(self) -> str:
        """Stable identity derived from the source game + move number, not
        sort position -- safe to persist across re-runs (new games added,
        problems re-sorted) without renumbering or losing review history."""
        return f"{Path(self.game).stem}::m{self.move_number}"


@dataclass
class _PlayerMove:
    game: str
    move_number: int
    phase: str
    points_lost: float          # clamped to >= 0; engine noise can go slightly negative
    winrate_before: float | None
    played: str
    best: str


def phase_of(move_number: int) -> str:
    if move_number <= OPENING_END:
        return "opening"
    if move_number <= MIDDLE_END:
        return "middle"
    return "endgame"


def _player_moves(analyses: list[GameAnalysis], player: str | Sequence[str]) -> list[_PlayerMove]:
    """Every move the player of interest played, across all games, with the
    points lost and context needed by every metric below."""
    out = []
    for analysis in analyses:
        record = analysis.record
        color = record.color_of(player)
        if color is None:
            continue
        for move in record.moves:
            if move.color != color:
                continue
            raw_loss = analysis.points_lost(move.number)
            if raw_loss is None:
                continue
            before = analysis.position_at(move.number)
            best = before.best_moves[0]["move"] if before and before.best_moves else "?"
            # before.winrate is fixed to Black's perspective; flip it to the
            # mover's own perspective so "ahead"/"behind" means the player of
            # interest, not always Black.
            winrate_before = None
            if before is not None:
                winrate_before = before.winrate if color == "b" else 1.0 - before.winrate
            out.append(_PlayerMove(
                game=record.path.name,
                move_number=move.number,
                phase=phase_of(move.number),
                points_lost=max(0.0, raw_loss),
                winrate_before=winrate_before,
                played=format_vertex(move.coord),
                best=best,
            ))
    return out


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def phase_loss_distribution(analyses: list[GameAnalysis], player: str | Sequence[str]) -> PhaseLoss:
    moves = _player_moves(analyses, player)
    totals = {"opening": 0.0, "middle": 0.0, "endgame": 0.0}
    by_phase: dict[str, list[float]] = {"opening": [], "middle": [], "endgame": []}
    for m in moves:
        totals[m.phase] += m.points_lost
        by_phase[m.phase].append(m.points_lost)
    return PhaseLoss(
        opening=_mean(by_phase["opening"]),
        middle=_mean(by_phase["middle"]),
        endgame=_mean(by_phase["endgame"]),
        opening_total=totals["opening"],
        middle_total=totals["middle"],
        endgame_total=totals["endgame"],
    )


def magnitude_profile(analyses: list[GameAnalysis], player: str | Sequence[str]) -> MagnitudeProfile:
    moves = _player_moves(analyses, player)
    n_games = len({m.game for m in moves})
    buckets = {label: 0 for label, _, _ in MAGNITUDE_BUCKETS}
    for m in moves:
        for label, lo, hi in MAGNITUDE_BUCKETS:
            if lo <= m.points_lost < hi:
                buckets[label] += 1
                break
    blunders = sum(1 for m in moves if m.points_lost >= BLUNDER_THRESHOLD)
    leaks = sum(1 for m in moves if LEAK_RANGE[0] <= m.points_lost < LEAK_RANGE[1])
    return MagnitudeProfile(
        buckets=buckets,
        blunders_per_game=blunders / n_games if n_games else 0.0,
        leak_rate=leaks / len(moves) if moves else 0.0,
    )


def ahead_behind_split(analyses: list[GameAnalysis], player: str | Sequence[str]) -> AheadBehindSplit:
    moves = [m for m in _player_moves(analyses, player) if m.winrate_before is not None]
    ahead = [m.points_lost for m in moves if m.winrate_before >= AHEAD]
    behind = [m.points_lost for m in moves if m.winrate_before <= BEHIND]
    close = [m.points_lost for m in moves if BEHIND < m.winrate_before < AHEAD]
    return AheadBehindSplit(
        mean_loss_when_ahead=_mean(ahead),
        mean_loss_when_close=_mean(close),
        mean_loss_when_behind=_mean(behind),
    )


def problem_positions(analyses: list[GameAnalysis], player: str | Sequence[str],
                      threshold: float = PROBLEM_THRESHOLD) -> list[ProblemPosition]:
    moves = _player_moves(analyses, player)
    problems = [
        ProblemPosition(game=m.game, move_number=m.move_number, points_lost=m.points_lost,
                        played=m.played, best=m.best)
        for m in moves
        # Playing KataGo's own top move but still showing a large points_lost
        # is search noise (independent per-turn evaluations, not a true delta
        # against the best move), not a real mistake -- nothing to quiz here.
        if m.points_lost >= threshold and m.played != m.best
    ]
    problems.sort(key=lambda p: p.points_lost, reverse=True)
    return problems
