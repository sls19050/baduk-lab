from datetime import date

from baduk_lab.quiz_html import render_quiz_html
from baduk_lab.report import ProblemIndexEntry

TODAY = date(2026, 1, 1)


def _entry(problem_id, game, move_number, played="D4", best="Q16"):
    return ProblemIndexEntry(
        problem_id=problem_id, game=game, move_number=move_number,
        phase="middle", points_lost=6.0, path=f"middle/{game}_m{move_number}.sgf",
        played=played, best=best,
    )


def _games_for(game_name, total_moves):
    moves = [["b" if m % 2 == 1 else "w", [3, 3]] for m in range(1, total_moves + 1)]
    return {game_name: {"board_size": 19, "moves": moves}}


def test_renders_every_due_problem_id(tmp_path):
    due = [_entry("g1::m10", "g1.sgf", 10), _entry("g1::m40", "g1.sgf", 40)]
    games = _games_for("g1.sgf", 60)

    out = render_quiz_html(due, games, tmp_path / "quiz.html", TODAY)

    text = out.read_text(encoding="utf-8")
    assert "g1::m10" in text
    assert "g1::m40" in text


def test_empty_due_list_does_not_crash(tmp_path):
    out = render_quiz_html([], {}, tmp_path / "quiz.html", TODAY)

    assert out.exists()
    assert "<html" in out.read_text(encoding="utf-8").lower()


def test_problem_missing_from_games_is_skipped_not_crashed(tmp_path):
    due = [_entry("known::m10", "known.sgf", 10), _entry("missing::m5", "missing.sgf", 5)]
    games = _games_for("known.sgf", 20)

    out = render_quiz_html(due, games, tmp_path / "quiz.html", TODAY)

    text = out.read_text(encoding="utf-8")
    assert "known::m10" in text
    assert "missing::m5" not in text
