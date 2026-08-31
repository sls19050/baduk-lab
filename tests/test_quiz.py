from dataclasses import dataclass
from datetime import date

from baduk_lab import quiz


@dataclass
class _P:
    problem_id: str
    points_lost: float


DAY1 = date(2026, 1, 1)


def test_sync_new_problems_adds_unseen_due_today_and_leaves_existing_alone():
    state = {"a::m1": {"box": 3, "next_due": "2026-06-01",
                       "first_seen": "2026-01-01", "times_seen": 5}}
    problems = [_P("a::m1", 5.0), _P("b::m2", 8.0)]

    quiz.sync_new_problems(state, problems, DAY1)

    # existing entry untouched (this is what makes re-runs incremental)
    assert state["a::m1"]["box"] == 3
    assert state["a::m1"]["next_due"] == "2026-06-01"
    # new entry added, due immediately
    assert state["b::m2"] == {"box": 1, "next_due": "2026-01-01",
                              "first_seen": "2026-01-01", "times_seen": 0}


def test_due_problems_filters_by_next_due_and_sorts_worst_first():
    state = {
        "a::m1": {"box": 1, "next_due": "2026-01-01"},
        "b::m2": {"box": 1, "next_due": "2026-06-01"},  # not due yet
        "c::m3": {"box": 1, "next_due": "2025-12-01"},
    }
    problems = [_P("a::m1", 5.0), _P("b::m2", 99.0), _P("c::m3", 20.0)]

    due = quiz.due_problems(state, problems, DAY1)

    assert [p.problem_id for p in due] == ["c::m3", "a::m1"]


def test_record_result_correct_advances_box_and_pushes_due_date():
    state = {}
    quiz.record_result(state, "a::m1", correct=True, today=DAY1)

    assert state["a::m1"]["box"] == 2
    assert state["a::m1"]["next_due"] == "2026-01-05"  # +4 days for box 2
    assert state["a::m1"]["times_seen"] == 1


def test_record_result_wrong_resets_box_and_is_due_immediately():
    state = {"a::m1": {"box": 3, "next_due": "2026-06-01",
                       "first_seen": "2026-01-01", "times_seen": 2}}

    quiz.record_result(state, "a::m1", correct=False, today=DAY1)

    assert state["a::m1"]["box"] == 1
    assert state["a::m1"]["next_due"] == "2026-01-01"
    assert state["a::m1"]["times_seen"] == 3


def test_record_result_box_caps_at_max():
    state = {"a::m1": {"box": quiz.MAX_BOX, "next_due": "2026-01-01",
                       "first_seen": "2026-01-01", "times_seen": 0}}

    quiz.record_result(state, "a::m1", correct=True, today=DAY1)

    assert state["a::m1"]["box"] == quiz.MAX_BOX


def test_state_round_trips_through_save_and_load(tmp_path):
    path = tmp_path / "quiz_state.json"
    state = {"a::m1": {"box": 2, "next_due": "2026-01-05",
                       "first_seen": "2026-01-01", "times_seen": 1}}

    quiz.save_state(path, state)

    assert quiz.load_state(path) == state


def test_load_state_missing_file_returns_empty_dict(tmp_path):
    assert quiz.load_state(tmp_path / "does_not_exist.json") == {}
