"""Clean up a folder of manually-saved SGF/.gib files.

Games saved by hand from a client UI (KGS's, LizzieYzy's game-record
export, etc.) tend to pile up under whatever name the client defaulted
to -- often just the opponent's handle, sometimes duplicated once as a
plain export and again as a client's own "analyzed" export of the same
game. `tidy_folder` renames every game to a name derived from its own
SGF metadata (date/players/result) and quarantines exact-duplicate
games into a `duplicates/` subfolder rather than deleting them, so
running it repeatedly on a folder you keep adding games to is safe.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .loader import QUARANTINE_DIRNAME, GameRecord, load_gib, load_sgf

logger = logging.getLogger(__name__)

_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE_RE = re.compile(r"\s+")


def _sanitize_component(text: str, fallback: str) -> str:
    text = _WHITESPACE_RE.sub("", text.strip())
    text = _INVALID_FILENAME_CHARS_RE.sub("", text)
    return text or fallback


def suggest_filename(record: GameRecord) -> str:
    """A `{date}_{black}-vs-{white}_{result}{ext}` name built from the
    game's own metadata, e.g. "2026-09-07_ikirushia-vs-HKA_B+Resign.sgf".
    Falls back to placeholder components for any tag the source file
    left blank, rather than failing."""
    date = _sanitize_component(record.date, "unknown-date")
    black = _sanitize_component(record.player_black, "unknown")
    white = _sanitize_component(record.player_white, "unknown")
    result = _sanitize_component(record.result, "no-result")
    ext = record.path.suffix.lower()
    return f"{date}_{black}-vs-{white}_{result}{ext}"


def game_fingerprint(record: GameRecord) -> tuple:
    """Identity of the actual game played, independent of file naming,
    added chat/analysis comments, or post-game review variations
    (GameRecord.moves is already just the main line). Deliberately
    exact -- matching every move is the only way to be confident enough
    to auto-quarantine a file, so near-duplicates are left alone rather
    than risk quarantining two genuinely different games."""
    move_seq = tuple((m.color, m.coord) for m in record.moves)
    return (
        record.board_size,
        round(record.komi, 2),
        record.player_black.strip().lower(),
        record.player_white.strip().lower(),
        record.date,
        record.result.strip().lower(),
        move_seq,
    )


def _is_engine_export(record: GameRecord) -> bool:
    """Heuristic for LizzieYzy/KaTrain-style "analyzed game" exports:
    same game as the original save, but bloated with baked-in engine
    commentary that `baduk-lab analyze` will just regenerate anyway."""
    return "analyz" in record.path.stem.lower()


def choose_keeper(group: list[GameRecord]) -> GameRecord:
    """Which file in a group of exact-duplicate games to keep: prefer a
    plain save over an engine-analyzed export, then the smaller file,
    then whichever path sorts first (for determinism)."""
    return min(group, key=lambda r: (_is_engine_export(r), r.path.stat().st_size, str(r.path)))


def _unique_path(path: Path, taken: set[Path]) -> Path:
    if path not in taken and not path.exists():
        return path
    stem, suffix, n = path.stem, path.suffix, 2
    while True:
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if candidate not in taken and not candidate.exists():
            return candidate
        n += 1


@dataclass
class TidyResult:
    renamed: list[tuple[Path, Path]] = field(default_factory=list)
    quarantined: list[tuple[Path, Path]] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def _load_record(path: Path) -> GameRecord:
    return load_gib(path) if path.suffix.lower() == ".gib" else load_sgf(path)


def tidy_folder(folder: Path, dry_run: bool = False) -> TidyResult:
    """Rename every game in `folder` (recursively) to `suggest_filename`,
    and move all but one copy of each exact-duplicate game into a
    `duplicates/` subfolder next to it. Never deletes anything. Files
    already inside a `duplicates/` folder are left alone, so re-running
    this on a folder you keep adding new games to is safe -- it never
    reprocesses what a previous run already quarantined."""
    result = TidyResult()

    records: list[GameRecord] = []
    paths = sorted(list(folder.rglob("*.sgf")) + list(folder.rglob("*.gib")))
    for path in paths:
        if path.parent.name == QUARANTINE_DIRNAME:
            continue
        try:
            records.append(_load_record(path))
        except Exception as exc:
            result.skipped.append((path, str(exc)))

    groups: dict[tuple, list[GameRecord]] = {}
    for record in records:
        groups.setdefault(game_fingerprint(record), []).append(record)

    quarantine_targets: set[Path] = set()
    keepers: list[GameRecord] = []
    for group in groups.values():
        if len(group) == 1:
            keepers.append(group[0])
            continue
        keeper = choose_keeper(group)
        keepers.append(keeper)
        for record in group:
            if record is keeper:
                continue
            quarantine_dir = record.path.parent / QUARANTINE_DIRNAME
            dest = _unique_path(quarantine_dir / record.path.name, quarantine_targets)
            quarantine_targets.add(dest)
            result.quarantined.append((record.path, dest))
            if not dry_run:
                quarantine_dir.mkdir(exist_ok=True)
                record.path.rename(dest)

    rename_targets: set[Path] = set()
    for record in keepers:
        new_path = record.path.parent / suggest_filename(record)
        if new_path == record.path:
            continue
        new_path = _unique_path(new_path, rename_targets | {record.path})
        rename_targets.add(new_path)
        result.renamed.append((record.path, new_path))
        if not dry_run:
            record.path.rename(new_path)

    return result
