"""Thin client for KataGo's JSON analysis engine.

Runs `katago analysis -config ... -model ...` as a subprocess, sends one query
per game over stdin, reads newline-delimited JSON responses from stdout.

Design decisions:
- One query per game with `analyzeTurns` covering every move. KataGo batches
  internally; this is far faster than one query per position.
- Results are cached to raw/<sgf-stem>.json keyed by (sgf content hash,
  model, visits, schema). Re-running the report never re-runs the engine.
- We record, per position: winrate, scoreLead, and the top N candidate moves
  with their scoreLead, winrate, scoreMean, prior (policy), and order, so
  metrics.py can compute points lost and move-distance, and strength.py can
  compute move-quality features, without further engine calls.

winrate/scoreLead are fixed to Black's perspective for every position,
regardless of whose turn it is -- confirmed empirically (KataGo's own docs
describe rootInfo in mover-relative terms, but the actual analysis engine
output does not flip sign with the player to move; a lopsided fixed board
queried with initialPlayer=B and initialPlayer=W gives the same-sign
scoreLead both times). GameAnalysis.points_lost() does the mover-relative
conversion itself.

Rules are not yet read from the SGF (loader.py does not extract RU[] tags),
so we assume Japanese rules, which matches KGS's default and every game
we've tested against; this is a known simplification.

See https://github.com/lightvector/KataGo/blob/master/docs/Analysis_Engine.md
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sgfmill.common import format_vertex

from .loader import GameRecord

DEFAULT_RULES = "japanese"


@dataclass
class PositionAnalysis:
    move_number: int         # analysis of the position *before* this move
    to_play: str             # "b" or "w"
    winrate: float           # Black's win probability, fixed perspective
    score_lead: float        # Black's score lead in points, fixed perspective
    best_moves: list[dict]   # top candidates: {"move", "scoreLead", "scoreMean",
                              # "winrate", "prior", "order"}. Unlike the fields
                              # above, each candidate's own scoreMean/winrate are
                              # relative to whoever is to move at this position
                              # (KataGo's per-moveInfo convention), so comparing
                              # two candidates here needs no color-flip.


@dataclass
class GameAnalysis:
    record: GameRecord
    positions: list[PositionAnalysis]

    def __post_init__(self) -> None:
        self._by_move_number = {p.move_number: p for p in self.positions}

    def position_at(self, move_number: int) -> PositionAnalysis | None:
        """The analysis of the position immediately before this move number."""
        return self._by_move_number.get(move_number)

    def points_lost(self, move_number: int) -> float | None:
        """How many points the move cost its own player, in the mover's
        favor. The core quantity everything else builds on."""
        before = self._by_move_number.get(move_number)
        after = self._by_move_number.get(move_number + 1)
        if before is None or after is None:
            return None
        # score_lead is fixed to Black's perspective at every position, so
        # the raw change in it is Black's gain/loss from the move. Flip the
        # sign when White was the mover, since a rise in Black's score lead
        # is a loss for White.
        mover = self.record.moves[move_number - 1].color
        delta_for_black = after.score_lead - before.score_lead
        return delta_for_black if mover == "w" else -delta_for_black


class KataGoClient:
    def __init__(self, katago_binary: Path, model: Path, config: Path,
                 visits: int = 500, top_moves: int = 16):
        self.katago_binary = Path(katago_binary)
        self.model = Path(model)
        self.config = Path(config)
        self.visits = visits
        self.top_moves = top_moves
        self._process: subprocess.Popen | None = None

    def __enter__(self) -> "KataGoClient":
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    def _ensure_started(self) -> None:
        # Deferred so that a run where every game is already cached never
        # pays the cost of loading the neural net at all.
        if self._process is None:
            self._process = subprocess.Popen(
                [str(self.katago_binary), "analysis",
                 "-config", str(self.config), "-model", str(self.model)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", bufsize=1,
            )

    def close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.stdin.close()
            self._process.wait(timeout=10)

    def analyze_game(self, record: GameRecord, cache_dir: Path) -> GameAnalysis:
        """Analyze every position of a game, using the cache when possible."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{record.path.stem}.json"
        key = self._cache_key(record)

        cached = self._read_cache(cache_path, key)
        if cached is not None:
            return GameAnalysis(record=record, positions=cached)

        positions = self._query(record)
        self._write_cache(cache_path, key, positions)
        return GameAnalysis(record=record, positions=positions)

    def _cache_key(self, record: GameRecord) -> dict:
        return {
            "sgf_sha256": hashlib.sha256(record.path.read_bytes()).hexdigest(),
            "model": str(self.model),
            "visits": self.visits,
            # Bump when PositionAnalysis.best_moves gains/loses fields, so
            # caches written before the change are transparently invalidated
            # instead of silently missing the new keys.
            "schema": 2,
        }

    def _read_cache(self, cache_path: Path, key: dict) -> list[PositionAnalysis] | None:
        if not cache_path.exists():
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if payload.get("key") != key:
            return None
        return [PositionAnalysis(**p) for p in payload["positions"]]

    def _write_cache(self, cache_path: Path, key: dict,
                     positions: list[PositionAnalysis]) -> None:
        payload = {
            "key": key,
            "positions": [dataclasses.asdict(p) for p in positions],
        }
        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _query(self, record: GameRecord) -> list[PositionAnalysis]:
        self._ensure_started()
        query_id = record.path.stem
        num_turns = len(record.moves) + 1
        query = {
            "id": query_id,
            "moves": [[m.color.upper(), format_vertex(m.coord)] for m in record.moves],
            "rules": DEFAULT_RULES,
            "komi": record.komi,
            "boardXSize": record.board_size,
            "boardYSize": record.board_size,
            "analyzeTurns": list(range(num_turns)),
            "maxVisits": self.visits,
            "includePolicy": False,
        }
        self._process.stdin.write(json.dumps(query) + "\n")
        self._process.stdin.flush()

        by_turn: dict[int, PositionAnalysis] = {}
        while len(by_turn) < num_turns:
            line = self._process.stdout.readline()
            if not line:
                stderr = self._process.stderr.read()
                raise RuntimeError(
                    f"KataGo process ended unexpectedly while analyzing "
                    f"{query_id}: {stderr}"
                )
            response = json.loads(line)
            if response.get("id") != query_id or response.get("isDuringSearch"):
                continue

            turn = response["turnNumber"]
            root = response["rootInfo"]
            by_turn[turn] = PositionAnalysis(
                move_number=turn + 1,
                to_play=root["currentPlayer"].lower(),
                winrate=root["winrate"],
                score_lead=root["scoreLead"],
                best_moves=[
                    {
                        "move": mi["move"],
                        "scoreLead": mi.get("scoreLead"),
                        "scoreMean": mi.get("scoreMean"),
                        "winrate": mi.get("winrate"),
                        "prior": mi.get("prior"),
                        "order": mi.get("order"),
                    }
                    for mi in response.get("moveInfos", [])[:self.top_moves]
                ],
            )

        return [by_turn[t] for t in range(num_turns)]
