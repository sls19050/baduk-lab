"""Your own corrections to a card's answer and note: `report/card_edits.json`.

A card's answer comes from whatever KataGo search was stored when it was
harvested, and that changes when you move to a stronger network -- a new
net may prefer a different move, or rate the move you played as fine. A
note can also need rewording once you understand the position better.
The quiz page's "Edit card" button lets you fix both on the spot.

Edits live in their own file, keyed by problem_id, and nothing else ever
writes it: `notes` rewrites notes_index.json wholesale on every harvest and
`analyze` rewrites index.json, so an edit stored in either would vanish on
the next run. Applying them at load time instead means an edit wins over
every later harvest until you reset it from the quiz page.

Each entry replaces the card's whole answer set and note, and keeps what
the card said when you edited it (`was`), so you can see what you changed:

    {"<problem_id>": {"best": "R3", "alternatives": ["Q3"], "note": "...",
                       "edited": "YYYY-MM-DD",
                       "was": {"best": ..., "alternatives": [...], "note": ...}}}
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

from .report import ProblemIndexEntry

FILENAME = "card_edits.json"

# A GTP-style point: column letter (no I), then a 1-25 row. Board size isn't
# known here; render_quiz_html drops anything off the board anyway.
_VERTEX_RE = re.compile(r"^[A-HJ-Z](?:[1-9]|1[0-9]|2[0-5])$")


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, edits: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(edits, indent=2, ensure_ascii=False), encoding="utf-8")


def apply(problems: list[ProblemIndexEntry], edits: dict) -> list[ProblemIndexEntry]:
    """The problems with your edits in place of their harvested answer and
    note. Cards without an edit come back unchanged."""
    out = []
    for p in problems:
        edit = edits.get(p.problem_id)
        if edit is None:
            out.append(p)
            continue
        out.append(replace(p, best=edit["best"],
                           alternatives=list(edit["alternatives"]),
                           note=edit["note"]))
    return out


def validate(best, alternatives, note) -> tuple[str, list[str], str]:
    """Clean one edit from the quiz page, or raise ValueError. `best` may be
    empty only if nothing is accepted at all -- a card with no answer can't
    be graded, so that's refused rather than saved."""
    if not isinstance(best, str) or not _VERTEX_RE.match(best):
        raise ValueError(f"main answer must be a point like 'R3', got {best!r}")
    if not isinstance(alternatives, list) or not all(
            isinstance(v, str) and _VERTEX_RE.match(v) for v in alternatives):
        raise ValueError(f"alternatives must be a list of points, got {alternatives!r}")
    if not isinstance(note, str):
        raise ValueError("note must be text")
    # Keep order, drop duplicates and the main answer itself.
    seen = {best}
    cleaned = []
    for v in alternatives:
        if v not in seen:
            seen.add(v)
            cleaned.append(v)
    return best, cleaned, note.strip()


def set_edit(edits: dict, problem: ProblemIndexEntry | None, problem_id: str,
             best: str, alternatives: list[str], note: str, today: date) -> None:
    """Record an edit. `problem` is the card as harvested (before any edit),
    used for `was` the first time a card is edited; re-editing keeps the
    original `was`, since that is the harvested version you'd reset to."""
    best, alternatives, note = validate(best, alternatives, note)
    previous = edits.get(problem_id, {})
    was = previous.get("was")
    if was is None and problem is not None:
        was = {"best": problem.best, "alternatives": list(problem.alternatives),
               "note": problem.note}
    edits[problem_id] = {"best": best, "alternatives": alternatives, "note": note,
                         "edited": today.isoformat(), "was": was}


def reset(edits: dict, problem_id: str) -> None:
    edits.pop(problem_id, None)
