"""Load SGF and Tygem .gib files into a simple internal game record.

Responsibilities:
- Parse SGF with sgfmill, and Tygem's proprietary .gib format by hand.
- Identify which color the player of interest held (possibly across
  several server-handle aliases for the same person).
- Extract the main-line move sequence.
- Extract per-move clock tags (BL/WL, OB/OW) when present (KGS provides them;
  .gib files don't carry per-move clocks in the fields this parser reads).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sgfmill import sgf

logger = logging.getLogger(__name__)

# Folder name `tidy.tidy_folder()` quarantines exact-duplicate games into.
# Defined here (not in tidy.py) so load_folder can skip it without a
# circular import -- tidy.py imports this back for its own use.
QUARANTINE_DIRNAME = "duplicates"


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

    def color_of(self, player_name: str | Sequence[str]) -> str | None:
        """Return 'b' or 'w' for the player of interest, None if not found.

        `player_name` may be a single handle or a list of aliases for the
        same person (e.g. two accounts on the same server) -- any match
        wins.
        """
        names = [player_name] if isinstance(player_name, str) else list(player_name)
        black = self.player_black.lower()
        white = self.player_white.lower()
        for name in names:
            name = name.lower()
            if name in black:
                return "b"
            if name in white:
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



# --- Tygem .gib format -------------------------------------------------
#
# Reverse-engineered format (no official spec): header lines look like
# `\[KEY=VALUE\]` (the backslashes are literal), and moves are lines like
# `STO 0 <move_index> <color:1=b,2=w> <x> <y>` where x/y are raw SGF-style
# coordinates (x=column left-to-right, y=row top-to-bottom), confirmed
# against github.com/yenw/computer-go-dataset's GibParser.cpp, which builds
# `;B[x_letter y_letter]` directly with no inversion. sgfmill's (row, col)
# tuples are row-from-bottom (row 0 = bottom edge), so converting into the
# Move.coord convention this module already uses is:
#
#   row = board_size - 1 - y
#   col = x
#
# "N Handicap" games on Tygem just mean komi=0 (no pre-placed handicap
# stones) -- moves still alternate normally from black move 1, and each STO
# line already carries its own explicit color, so no special handicap-stone
# placement logic is needed here.

_GIB_HEADER_RE = re.compile(r"\\\[([A-Z]+)=(.*?)\\\]")
_GIB_STO_RE = re.compile(r"^STO\s+\d+\s+\d+\s+([12])\s+(\d+)\s+(\d+)\s*$")


def _decode_gib_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _parse_gib_headers(text: str) -> dict[str, str]:
    return dict(_GIB_HEADER_RE.findall(text))


def _parse_gib_board_size(gameinfomain: str) -> int:
    for part in gameinfomain.split(","):
        if part.startswith("LINE:"):
            try:
                return int(part.split(":", 1)[1])
            except ValueError:
                break
    return 19


def _parse_gib_komi(raw: str) -> float:
    try:
        return int(raw) / 10
    except ValueError:
        return 0.0


def _parse_gib_date(raw: str) -> str:
    # e.g. "2026- 8-16- 6-38-28" -> "2026-08-16" (stray spaces before
    # single-digit fields are part of the source format).
    parts = [p.strip() for p in raw.split("-")]
    if len(parts) < 3:
        return ""
    try:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return ""


def _map_gib_result(raw: str) -> str:
    """Best-effort GAMERESULT free text -> SGF-style RE. Purely cosmetic
    (no metric depends on it); falls back to the raw string unrecognized."""
    lower = raw.strip().lower()
    if lower == "draw":
        return "0"
    m = re.match(r"^(black|white)\s+wins?\s+by\s+(resignation|time|disconnection)$", lower)
    if m:
        color = "B" if m.group(1) == "black" else "W"
        code = {"resignation": "R", "time": "T", "disconnection": "Forfeit"}[m.group(2)]
        return f"{color}+{code}"
    m = re.match(r"^(black|white)\s+(\d+(?:\.\d+)?)\s*(?:points?)?\s*win$", lower)
    if m:
        color = "B" if m.group(1) == "black" else "W"
        return f"{color}+{m.group(2)}"
    return raw


def parse_gib(text: str, path: Path) -> GameRecord:
    """Parse the text content of one .gib file into a GameRecord."""
    headers = _parse_gib_headers(text)
    board_size = _parse_gib_board_size(headers.get("GAMEINFOMAIN", ""))

    moves: list[Move] = []
    for line in text.splitlines():
        match = _GIB_STO_RE.match(line.strip())
        if not match:
            continue
        color_code, x_str, y_str = match.groups()
        x, y = int(x_str), int(y_str)
        moves.append(Move(
            number=len(moves) + 1,
            color="b" if color_code == "1" else "w",
            coord=(board_size - 1 - y, x),
        ))

    return GameRecord(
        path=path,
        board_size=board_size,
        komi=_parse_gib_komi(headers.get("GAMEGONGJE", "0")),
        player_black=headers.get("GAMEBLACKNICK", ""),
        player_white=headers.get("GAMEWHITENICK", ""),
        result=_map_gib_result(headers.get("GAMERESULT", "")),
        date=_parse_gib_date(headers.get("GAMEDATE", "")),
        moves=moves,
    )


def load_gib(path: Path) -> GameRecord:
    """Parse one .gib file into a GameRecord."""
    return parse_gib(_decode_gib_bytes(path.read_bytes()), path)


def load_folder(folder: Path) -> list[GameRecord]:
    """Load every .sgf/.gib file in a folder (recursively -- Tygem's own
    Gibo/YYYY-MM/ layout needs this), skipping unparseable files with a
    warning. Skips any `duplicates/` folder `tidy.tidy_folder()` may have
    quarantined games into, so a tidied folder isn't double-counted."""
    paths = sorted(list(folder.rglob("*.sgf")) + list(folder.rglob("*.gib")))
    paths = [p for p in paths if QUARANTINE_DIRNAME not in p.relative_to(folder).parts[:-1]]
    records = []
    for path in paths:
        try:
            if path.suffix.lower() == ".gib":
                records.append(load_gib(path))
            else:
                records.append(load_sgf(path))
        except Exception as exc:
            logger.warning("Skipping %s: %s", path.name, exc)
    return records
