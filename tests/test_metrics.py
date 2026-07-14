"""Metrics are pure functions, so they get real tests from day one."""

import pytest

from baduk_lab import metrics
from factories import PLAYER, build_analysis


def test_phase_loss_distribution_buckets_by_move_number():
    # focus_color='b' -> player's moves are the odd move numbers.
    # opening: 1..49 odd (25 moves), middle: 51..149 odd (50 moves), endgame: 151..159 odd (5 moves).
    analysis = build_analysis(160, "b", losses={1: 4.0, 101: 20.0, 151: 9.0})

    result = metrics.phase_loss_distribution([analysis], PLAYER)

    assert result.opening_total == pytest.approx(4.0)
    assert result.middle_total == pytest.approx(20.0)
    assert result.endgame_total == pytest.approx(9.0)
    assert result.opening == pytest.approx(4.0 / 25)
    assert result.middle == pytest.approx(20.0 / 50)
    assert result.endgame == pytest.approx(9.0 / 5)


def test_magnitude_profile_buckets_and_rates():
    analysis = build_analysis(9, "b", losses={1: 0.5, 3: 2.0, 5: 5.0, 7: 10.0, 9: 0.0})

    result = metrics.magnitude_profile([analysis], PLAYER)

    assert result.buckets == {"0-1": 2, "1-3": 1, "3-8": 1, "8+": 1}
    assert result.blunders_per_game == pytest.approx(1.0)
    assert result.leak_rate == pytest.approx(1 / 5)


def test_magnitude_profile_averages_blunders_across_games():
    blundery = build_analysis(1, "b", losses={1: 10.0}, name="a.sgf")
    clean = build_analysis(1, "b", losses={1: 0.0}, name="b.sgf")

    result = metrics.magnitude_profile([blundery, clean], PLAYER)

    assert result.blunders_per_game == pytest.approx(0.5)


def test_ahead_behind_split_uses_winrate_before_the_move():
    analysis = build_analysis(3, "b", losses={1: 1.0, 3: 5.0}, winrates={1: 0.8, 3: 0.2})

    result = metrics.ahead_behind_split([analysis], PLAYER)

    assert result.mean_loss_when_ahead == pytest.approx(1.0)
    assert result.mean_loss_when_behind == pytest.approx(5.0)
    assert result.mean_loss_when_close == pytest.approx(0.0)


def test_problem_positions_filters_and_sorts_by_points_lost():
    analysis = build_analysis(5, "b", losses={1: 2.0, 3: 10.0, 5: 6.0})

    problems = metrics.problem_positions([analysis], PLAYER)

    assert [p.move_number for p in problems] == [3, 5]
    assert [p.points_lost for p in problems] == pytest.approx([10.0, 6.0])
    assert all(p.best == "Q16" for p in problems)
    assert all(p.game == "game.sgf" for p in problems)


def test_problem_positions_respects_custom_threshold():
    analysis = build_analysis(3, "b", losses={1: 2.0, 3: 3.0})

    problems = metrics.problem_positions([analysis], PLAYER, threshold=2.5)

    assert [p.move_number for p in problems] == [3]


def test_unknown_player_is_skipped_not_errored():
    analysis = build_analysis(3, "b", losses={1: 5.0})

    result = metrics.phase_loss_distribution([analysis], "someone_not_in_this_game")

    assert result.opening_total == 0.0
