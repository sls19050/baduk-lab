"""Review-scheduling state for `baduk-lab review`.

A simple 3-box scheme, not full spaced repetition (SM-2 etc.) -- this is a
personal drilling tool for one user, not a spaced-repetition product. A
correct answer bumps the box (review again in 1/4/14 days); a wrong answer
always resets to box 1 (due again next session).

State is a plain dict keyed by problem_id, persisted as JSON:

    {"<problem_id>": {"box": int, "next_due": "YYYY-MM-DD",
                       "first_seen": "YYYY-MM-DD", "times_seen": int}, ...}

Deliberately decoupled from metrics.ProblemPosition: the functions here only
need objects with `.problem_id`/`.points_lost`, which both
metrics.ProblemPosition and report.ProblemIndexEntry provide -- so the same
scheduling logic works whether problems came straight from a fresh
`analyze` run or were reloaded from problems/index.json for `review`.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol


class _Problem(Protocol):
    problem_id: str
    points_lost: float


_INTERVALS = {1: 1, 2: 4, 3: 14}  # box -> days until next due, on a correct answer
MAX_BOX = 3


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def sync_new_problems(state: dict, problems: list[_Problem], today: date) -> dict:
    """Add any problem not already tracked, due immediately. Existing
    entries (and their review progress) are left untouched -- this is what
    makes re-running `analyze` incremental instead of resetting the deck."""
    today_str = today.isoformat()
    for problem in problems:
        if problem.problem_id in state:
            continue
        state[problem.problem_id] = {
            "box": 1,
            "next_due": today_str,
            "first_seen": today_str,
            "times_seen": 0,
        }
    return state


def due_problems(state: dict, problems: list[_Problem], today: date) -> list[_Problem]:
    """Problems whose next_due has arrived, worst points-lost first. A
    problem with no state entry yet is treated as due (call
    sync_new_problems first to avoid this in normal use)."""
    today_str = today.isoformat()
    due = [p for p in problems
           if state.get(p.problem_id, {}).get("next_due", today_str) <= today_str]
    return sorted(due, key=lambda p: p.points_lost, reverse=True)


def record_result(state: dict, problem_id: str, correct: bool, today: date) -> None:
    entry = state.setdefault(problem_id, {
        "box": 1, "next_due": today.isoformat(),
        "first_seen": today.isoformat(), "times_seen": 0,
    })
    entry["times_seen"] += 1
    if correct:
        entry["box"] = min(MAX_BOX, entry["box"] + 1)
        entry["next_due"] = (today + timedelta(days=_INTERVALS[entry["box"]])).isoformat()
    else:
        entry["box"] = 1
        entry["next_due"] = today.isoformat()
