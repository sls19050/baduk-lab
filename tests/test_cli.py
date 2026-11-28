import functools

import pytest

from datetime import date

from baduk_lab.cli import (_order_session, _resolve_problem_sgf_path,
                           _select_problems)
from baduk_lab.report import ProblemIndexEntry


def test_resolves_a_real_file_inside_problems_dir(tmp_path):
    (tmp_path / "middle").mkdir()
    sgf = tmp_path / "middle" / "game_m10.sgf"
    sgf.write_text("(;GM[1])")

    resolved = _resolve_problem_sgf_path(tmp_path, "middle/game_m10.sgf")

    assert resolved == sgf.resolve()


def test_rejects_path_traversal_outside_problems_dir(tmp_path):
    outside = tmp_path.parent / "secret.sgf"
    outside.write_text("(;GM[1])")

    resolved = _resolve_problem_sgf_path(tmp_path, "../secret.sgf")

    assert resolved is None


def test_rejects_nonexistent_file(tmp_path):
    resolved = _resolve_problem_sgf_path(tmp_path, "middle/does_not_exist.sgf")

    assert resolved is None


def test_rejects_empty_or_missing_path(tmp_path):
    assert _resolve_problem_sgf_path(tmp_path, None) is None
    assert _resolve_problem_sgf_path(tmp_path, "") is None


def _entry(problem_id, source, points_lost):
    return ProblemIndexEntry(
        problem_id=problem_id, game="g.sgf", move_number=10, phase="middle",
        points_lost=points_lost, path="p.sgf", played="D4", best="Q16",
        source=source)


def test_your_own_notes_lead_the_session(tmp_path):
    """A note can cost under a point and still matter most, so it must not
    be sorted below KataGo's big-points finds."""
    due = [_entry("k1", "katago", 20.0), _entry("n1", "note", 0.8),
           _entry("k2", "katago", 9.0), _entry("n2", "note", 0.2)]

    ordered = _order_session(due)

    assert [p.problem_id for p in ordered] == ["n1", "n2", "k1", "k2"]


def test_each_decks_own_worst_first_order_is_preserved(tmp_path):
    due = [_entry("k1", "katago", 20.0), _entry("k2", "katago", 9.0)]

    assert [p.problem_id for p in _order_session(due)] == ["k1", "k2"]


def test_ordering_a_single_deck_changes_nothing(tmp_path):
    due = [_entry("n1", "note", 0.8), _entry("n2", "note", 0.2)]

    assert [p.problem_id for p in _order_session(due)] == ["n1", "n2"]


TODAY = date(2026, 11, 21)


def test_select_problems_normally_asks_only_what_is_due():
    deck = [_entry("note::a::m1", "note", 1.0), _entry("note::b::m2", "note", 9.0)]
    state = {"note::a::m1": {"next_due": "2026-11-21"},
             "note::b::m2": {"next_due": "2026-12-05"}}

    picked = _select_problems(deck, state, TODAY, ignore_due=False)

    assert [p.problem_id for p in picked] == ["note::a::m1"]


def test_select_problems_ignore_due_takes_the_whole_deck_worst_first():
    """For practising a game you just reviewed, or when nothing is due."""
    deck = [_entry("note::a::m1", "note", 1.0), _entry("note::b::m2", "note", 9.0)]
    state = {"note::a::m1": {"next_due": "2026-12-05"},
             "note::b::m2": {"next_due": "2026-12-05"}}

    picked = _select_problems(deck, state, TODAY, ignore_due=True)

    assert [p.problem_id for p in picked] == ["note::b::m2", "note::a::m1"]


def test_select_problems_ignore_due_still_puts_your_own_notes_first():
    deck = [_entry("katago::a::m1", "katago", 50.0),
            _entry("note::b::m2", "note", 0.5)]

    picked = _select_problems(deck, {}, TODAY, ignore_due=True)

    assert [p.source for p in picked] == ["note", "katago"]


# --- "Next set" / "Practice set" from the quiz page --------------------

import argparse

from baduk_lab import cli


@pytest.fixture
def new_set_env(tmp_path, monkeypatch):
    """A five-card deck, two of them due; rendering is recorded rather
    than written, and re-harvesting is a no-op."""
    deck = [_entry(f"note::g::m{i}", "note", float(i)) for i in range(1, 6)]
    state = {p.problem_id: {"next_due": "2026-12-05"} for p in deck}
    state["note::g::m1"]["next_due"] = state["note::g::m2"]["next_due"] = "2026-11-01"
    rendered = []
    monkeypatch.setattr(cli, "_reharvest_notes", lambda out_dir: None)
    monkeypatch.setattr(cli, "_load_session",
                        lambda out_dir, source, phase, today: (deck, {}, state))
    monkeypatch.setattr(cli.report, "load_game_records", lambda d: {})
    monkeypatch.setattr(cli.quiz_html, "render_quiz_html",
                        lambda due, games, out, today, originals:
                        rendered.append([p.problem_id for p in due]))
    args = argparse.Namespace(source="note", phase=None, limit=2)
    return args, tmp_path, rendered


def test_next_set_asks_what_is_due_and_not_already_shown(new_set_env):
    args, out_dir, rendered = new_set_env
    new_set = cli._new_set_maker(args, out_dir, served={"note::g::m2"})

    assert new_set(False) == 1
    assert rendered == [["note::g::m1"]]


def test_next_set_with_nothing_due_leaves_the_page_alone(new_set_env):
    args, out_dir, rendered = new_set_env
    new_set = cli._new_set_maker(args, out_dir, served={"note::g::m1", "note::g::m2"})

    assert new_set(False) == 0
    assert rendered == []


def test_practice_sets_move_on_through_the_deck_then_start_over(new_set_env):
    """Worst first, but never the set you just did -- otherwise every
    practice set would be the same top cards."""
    args, out_dir, rendered = new_set_env
    new_set = cli._new_set_maker(args, out_dir, served=set())

    for _ in range(4):
        new_set(True)

    assert rendered == [["note::g::m5", "note::g::m4"], ["note::g::m3", "note::g::m2"],
                        ["note::g::m1"], ["note::g::m5", "note::g::m4"]]


def test_the_server_route_runs_the_new_set(tmp_path):
    import http.server, json, threading, urllib.request
    calls = []
    cli._QuizRequestHandler.new_set = lambda ignore_due: calls.append(ignore_due) or 7
    handler = functools.partial(cli._QuizRequestHandler, directory=str(tmp_path))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/new-set",
            data=json.dumps({"ignoreDue": True}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as res:
            body = json.loads(res.read())
    finally:
        httpd.shutdown()
        httpd.server_close()
        cli._QuizRequestHandler.new_set = None

    assert body == {"ok": True, "count": 7}
    assert calls == [True]
