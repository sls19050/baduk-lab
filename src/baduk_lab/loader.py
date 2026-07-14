"""Load SGF files into a simple internal game record.

Responsibilities:
- Parse SGF with sgfmill.
- Identify which color the player of interest held.
- Extract the main-line move sequence.
- Extract per-move clock tags (BL/WL, OB/OW) when present (KGS provides them).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sgfmill import sgf

logger = logging.getLogger(__name__)


@dataclass
class Move:
    number: int          # 1-indexed move number
    color: str           # "b" or "w"
    coord: tuple[int, int] | None  # (row, col), None for pass
    clock_after: float | None = None   # BL/WL value: seconds remaining after move
    byo_yomi_periods: int | None = None  # OB/OW value, if in overtime


@dataclass
class GameRecord:
    path: Path
    board_size: int
    komi: float
    player_black: str
    player_white: str
    result: str
    date: str = ""       # DT tag, e.g. "2026-06-02"; empty if absent
    moves: list[Move] = field(default_factory=list)

    def color_of(self, player_name: str) -> str | None:
        """Return 'b' or 'w' for the player of interest, None if not found."""
        name = player_name.lower()
        if name in self.player_black.lower():
            return "b"
        if name in self.player_white.lower():
            return "w"
        return None


def load_sgf(path: Path) -> GameRecord:
    """Parse one SGF file into a GameRecord."""
    game = sgf.Sgf_game.from_bytes(path.read_bytes())
    root = game.get_root()

    moves: list[Move] = []
    for number, node in enumerate(game.get_main_sequence()[1:], start=1):
        color, coord = node.get_move()
        if color is None:
            continue

        clock_prop = "BL" if color == "b" else "WL"
        byo_prop = "OB" if color == "b" else "OW"
        moves.append(Move(
            number=number,
            color=color,
            coord=coord,
            clock_after=node.get(clock_prop) if node.has_property(clock_prop) else None,
            byo_yomi_periods=node.get(byo_prop) if node.has_property(byo_prop) else None,
        ))

    return GameRecord(
        path=path,
        board_size=game.get_size(),
        komi=game.get_komi(),
        player_black=root.get("PB") if root.has_property("PB") else "",
        player_white=root.get("PW") if root.has_property("PW") else "",
        result=root.get("RE") if root.has_property("RE") else "",
        date=root.get("DT") if root.has_property("DT") else "",
        moves=moves,
    )


def load_folder(folder: Path) -> list[GameRecord]:
    """Load every .sgf in a folder, skipping unparseable files with a warning."""
    records = []
    for path in sorted(folder.glob("*.sgf")):
        try:
            records.append(load_sgf(path))
        except Exception as exc:
            logger.warning("Skipping %s: %s", path.name, exc)
    return records
