"""Optional per-user config: `config.toml` at the repo root.

Nothing here is required -- every value has a CLI-flag equivalent. This
just saves retyping `--player`/the games folder on every run for a
single-user setup. Copy config.example.toml to config.toml and fill it in;
config.toml itself is gitignored since it holds a personal handle/path.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "config.toml"


def _load() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    with _CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def player_aliases() -> list[str]:
    """Every server handle configured as belonging to the same person."""
    return list(_load().get("player", {}).get("aliases", []))


def default_folder() -> Path | None:
    """Folder to scan when none is passed on the command line."""
    folder = _load().get("source", {}).get("default_folder")
    return Path(folder) if folder else None


def lizzieyzy_exe() -> Path | None:
    """LizzieYzy Next executable, used by quiz.html's "deep analysis" button
    (review --html) to open a problem position for live/continuous
    analysis. Point this at whichever install you want triggered -- e.g.
    a lizzieyzy-next-fast/ TensorRT build for quick deep dives."""
    exe = _load().get("lizzieyzy", {}).get("exe")
    return Path(exe) if exe else None
