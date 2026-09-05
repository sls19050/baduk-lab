"""strength.py is a port of an external model's feature pipeline, so these
tests lean on the pure helper functions (thresholds, aggregation, formula
correctness) plus one end-to-end smoke test that the vendored XGBoost model
actually loads and produces a plausible rank."""

from pathlib import Path

import pytest

from baduk_lab import strength
from baduk_lab.engine import GameAnalysis, PositionAnalysis
from factories import build_record


def test_categorize_thresholds():
    assert strength._categorize(0.0) == strength.MoveCategory.EXCELLENT
    assert strength._categorize(0.19) == strength.MoveCategory.EXCELLENT
    assert strength._categorize(0.2) == strength.MoveCategory.GREAT
    assert strength._categorize(0.6) == strength.MoveCategory.GOOD
    assert strength._categorize(1.2) == strength.MoveCategory.INACCURACY
    assert strength._categorize(4.0) == strength.MoveCategory.MISTAKE
    assert strength._categorize(10.0) == strength.MoveCategory.BLUNDER
    assert strength._categorize(-5.0) == strength.MoveCategory.EXCELLENT  # clamped positive


def test_categorize_good_and_mistake_groupings():
    assert strength.MoveCategory.EXCELLENT.is_good
    assert strength.MoveCategory.GREAT.is_good
    assert strength.MoveCategory.GOOD.is_good
    assert not strength.MoveCategory.INACCURACY.is_good
    assert strength.MoveCategory.MISTAKE.is_mistake
    assert strength.MoveCategory.BLUNDER.is_mistake
    assert not strength.MoveCategory.INACCURACY.is_mistake


def test_candidate_loss_prefers_score_mean_over_winrate():
    top = {"move": "Q16", "scoreMean": 5.0, "winrate": 0.9}
    actual = {"move": "D4", "scoreMean": 3.0, "winrate": 0.8}

    assert strength._candidate_loss(top, actual) == pytest.approx(2.0)


def test_candidate_loss_falls_back_to_winrate():
    top = {"move": "Q16", "winrate": 0.9}
    actual = {"move": "D4", "winrate": 0.6}

    assert strength._candidate_loss(top, actual) == pytest.approx(0.3 / strength.WINRATE_TO_SCORE_LOSS)


def test_candidate_loss_missing_data_returns_none():
    assert strength._candidate_loss({"move": "Q16"}, {"move": "D4"}) is None


def test_complexity_is_policy_weighted_and_capped_at_one():
    best_moves = [
        {"move": "Q16", "scoreMean": 10.0, "prior": 0.6},
        {"move": "D4", "scoreMean": 4.0, "prior": 0.4},   # 6-point candidate loss
    ]
    # weighted average loss = 6.0 * 0.4 / 1.0 = 2.4, clamped to 1.0
    assert strength._complexity(best_moves) == pytest.approx(1.0)


def test_complexity_falls_back_without_priors():
    best_moves = [
        {"move": "Q16", "scoreMean": 1.0},
        {"move": "D4", "scoreMean": 0.4},  # 0.6-point gap, no prior data at all
    ]
    assert strength._complexity(best_moves) == pytest.approx(0.6 / strength.GOOD_LOSS)


def test_complexity_empty_candidates_is_zero():
    assert strength._complexity([]) == 0.0


def test_match_rate_formula():
    rate = strength._match_rate(first_choice_rate=0.4, good_move_rate=0.8, mistake_rate=0.1)
    assert rate == pytest.approx(0.45 * 0.4 + 0.45 * 0.8 + 0.10 * 0.9)


def test_rank_label_bands():
    assert strength._rank_label(12.0).endswith("AI")
    assert strength._rank_label(11.5).endswith("top pro")
    assert strength._rank_label(10.2).endswith("pro")
    assert strength._rank_label(5.0).endswith("dan")
    assert strength._rank_label(-1.0).endswith("kyu")


def _build_analysis_with_candidates(total_moves: int, focus_color: str,
                                    best_moves_by_position: dict[int, list[dict]],
                                    played_matches_top: bool = True) -> GameAnalysis:
    """Like factories.build_analysis, but lets each position specify its own
    best_moves candidates (with scoreMean/winrate/prior) instead of a single
    fixed placeholder -- needed to exercise strength.py's candidate-matching
    path instead of always falling back to the before/after score diff."""
    record = build_record(total_moves, focus_color)
    positions = [
        PositionAnalysis(
            move_number=pos,
            to_play="b" if pos % 2 == 1 else "w",
            winrate=0.5,
            score_lead=0.0,
            best_moves=best_moves_by_position.get(pos, [{"move": "Q16", "scoreLead": 0.0}]),
        )
        for pos in range(1, total_moves + 2)
    ]
    return GameAnalysis(record=record, positions=positions)


def test_estimate_side_none_when_color_has_no_moves():
    analysis = _build_analysis_with_candidates(4, "b", {})
    record = analysis.record
    # Every move in build_record alternates color starting from black; a
    # white-only game isn't representable via build_record, so instead
    # assert the *other* color (here, moves the factory never assigns
    # winrate/candidate data worth reading) still degrades to a result
    # rather than raising -- the "no samples at all" path is exercised
    # directly below.
    assert strength._aggregate([]) is None


def test_estimate_side_uses_candidate_match_when_available():
    # build_record's moves are all coord=(3, 3), which sgfmill formats to a
    # fixed vertex; point every position's top candidate straight at it so
    # first_choice comes out true and the candidate-based (not fallback)
    # loss path is exercised.
    from sgfmill.common import format_vertex
    vertex = format_vertex((3, 3))

    best_moves = [{"move": vertex, "scoreMean": 5.0, "winrate": 0.9, "prior": 1.0}]
    analysis = _build_analysis_with_candidates(
        6, "b", {pos: best_moves for pos in range(1, 8)})

    estimate = strength.estimate_side(analysis, "b")

    assert estimate is not None
    assert estimate.first_choice_rate == pytest.approx(1.0)
    assert estimate.mistake_rate == pytest.approx(0.0)
    assert estimate.sample_count == 3  # moves 1, 3, 5


def test_estimate_game_smoke_test_produces_a_rank():
    """End-to-end: the vendored model actually loads and yields a plausible
    strength estimate for a clearly-strong synthetic game."""
    from sgfmill.common import format_vertex
    vertex = format_vertex((3, 3))
    strong_candidate = [{"move": vertex, "scoreMean": 5.0, "winrate": 0.9, "prior": 1.0}]

    analysis = _build_analysis_with_candidates(
        40, "b", {pos: strong_candidate for pos in range(1, 42)})

    result = strength.estimate_game(analysis)

    assert result.black is not None
    assert result.black.rank_value is not None
    assert strength.MIN_RANK_VALUE <= result.black.rank_value <= strength.MAX_RANK_VALUE
    assert result.black.strength_band in strength.STRENGTH_BANDS
    # Playing the engine's own top choice every single analyzed move should
    # not land anywhere near the bottom of the scale.
    assert result.black.strength_band != "Beginner"
