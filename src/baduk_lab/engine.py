"""Thin client for KataGo's JSON analysis engine.

Runs `katago analysis -config ... -model ...` as a subprocess, sends one query
per game over stdin, reads newline-delimited JSON responses from stdout.

Design decisions:
- One query per game with `analyzeTurns` covering every move. KataGo batches
  internally; this is far faster than one query per position.
- Results are cached to raw/<sgf-stem>.json keyed by (sgf content hash,
  model, visits). Re-running the report never re-runs the engine.
- We record, per position: winrate, scoreLead, and the top N candidate moves
  with their scoreLead, so metrics.py can compute points lost and
  move-distance without further engine calls.

See https://github.com/lightvector/KataGo/blob/master/docs/Analysis_Engine.md
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .loader import GameRecord


@dataclass
class PositionAnalysis:
    move_number: int         # analysis of the position *before* this move
    to_play: str             # "b" or "w"
    winrate: float           # from to_play's perspective
    score_lead: float        # from to_play's perspective
    best_moves: list[dict]   # top candidates: {"move": "Q16", "scoreLead": ...}


@dataclass
class GameAnalysis:
    record: GameRecord
    positions: list[PositionAnalysis]

    def points_lost(self, move_number: int) -> float | None:
        """Score lead before the move minus score lead after it, from the
        mover's perspective. The core quantity everything else builds on."""
        raise NotImplementedError


class KataGoClient:
    def __init__(self, katago_binary: Path, model: Path, config: Path,
                 visits: int = 500):
        raise NotImplementedError

    def analyze_game(self, record: GameRecord, cache_dir: Path) -> GameAnalysis:
        """Analyze every position of a game, using the cache when possible."""
        raise NotImplementedError
