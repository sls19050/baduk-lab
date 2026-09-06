from baduk_lab import strength_chart
from baduk_lab.strength import SideEstimate


def _side(rank_value: float) -> SideEstimate:
    return SideEstimate(
        sample_count=20, score_sample_count=20, confidence="medium",
        rank_value=rank_value, quality_score=None, strength_band="3-4d",
        rank_label=f"{rank_value:.1f} dan", first_choice_rate=0.5,
        good_move_rate=0.8, mistake_rate=0.0, weighted_point_loss=1.0,
        average_point_loss=0.5, match_rate=0.6,
    )


def test_render_strength_chart_embeds_one_point_per_row(tmp_path):
    rows = [
        ("2026-01-01", "a.sgf", "Black", _side(4.0)),
        ("2026-01-05", "b.sgf", "White", _side(6.0)),
        ("2026-01-10", "c.sgf", "Black", _side(8.0)),
    ]

    path = strength_chart.render_strength_chart(rows, tmp_path / "chart.html")
    text = path.read_text(encoding="utf-8")

    assert text.count('class="point"') == 3
    assert "a.sgf" in text and "b.sgf" in text and "c.sgf" in text
    assert '"rankValue": 4.0' in text or '"rankValue":4.0' in text.replace(" ", "")
    assert "No dated games" not in text or 'id="noData" hidden' in text


def test_render_strength_chart_handles_empty_rows(tmp_path):
    path = strength_chart.render_strength_chart([], tmp_path / "chart.html")
    text = path.read_text(encoding="utf-8")

    assert '<p id="noData" >' in text  # not hidden -> message is visible
    assert 'id="chart-wrap" hidden>' in text
    assert "No dated, high-confidence games" in text
    assert 'class="point"' not in text


def test_band_boundaries_only_drawn_within_visible_range(tmp_path):
    # All rank values near 5.0 -> y-domain shouldn't stretch to include the
    # "12d AI" (11.5) or "Beginner" boundaries.
    rows = [
        ("2026-01-01", "a.sgf", "Black", _side(4.8)),
        ("2026-01-02", "b.sgf", "Black", _side(5.2)),
    ]

    path = strength_chart.render_strength_chart(rows, tmp_path / "chart.html")
    text = path.read_text(encoding="utf-8")

    assert ">12d AI<" not in text
    assert ">3-4d<" in text or ">5-6d<" in text
