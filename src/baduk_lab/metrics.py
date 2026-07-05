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

from dataclasses import dataclass

from .engine import GameAnalysis

# Move-number boundaries for phases. Crude but robust; revisit later.
OPENING_END = 50
MIDDLE_END = 150

# A move losing at least this many points becomes a drill problem.
PROBLEM_THRESHOLD = 4.0

# Winrate bands for ahead/behind analysis (mover's perspective).
AHEAD = 0.65
BEHIND = 0.35


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


def phase_loss_distribution(analyses: list[GameAnalysis], player: str) -> PhaseLoss:
    raise NotImplementedError


def magnitude_profile(analyses: list[GameAnalysis], player: str) -> MagnitudeProfile:
    raise NotImplementedError


def ahead_behind_split(analyses: list[GameAnalysis], player: str) -> AheadBehindSplit:
    raise NotImplementedError


def problem_positions(analyses: list[GameAnalysis], player: str,
                      threshold: float = PROBLEM_THRESHOLD) -> list[ProblemPosition]:
    raise NotImplementedError
