"""Load SGF files into a simple internal game record.

Responsibilities:
- Parse SGF with sgfmill.
- Identify which color the player of interest held.
- Extract the main-line move sequence.
- Extract per-move clock tags (BL/WL, OB/OW) when present (KGS provides them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
    """Parse one SGF file into a GameRecord. TODO: implement with sgfmill."""
    raise NotImplementedError


def load_folder(folder: Path) -> list[GameRecord]:
    """Load every .sgf in a folder, skipping unparseable files with a warning."""
    raise NotImplementedError
