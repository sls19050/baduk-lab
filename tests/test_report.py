from pathlib import Path

from sgfmill.common import move_from_vertex

from baduk_lab import metrics, report
from baduk_lab.engine import GameAnalysis
from baduk_lab.loader import GameRecord
from baduk_lab.strength import GameStrengthEstimate, SideEstimate
from factories import PLAYER, build_analysis


def test_render_report_writes_markdown_with_all_sections(tmp_path):
    analysis = build_analysis(160, "b", losses={1: 4.0, 101: 20.0, 151: 12.0})
    phase_loss = metrics.phase_loss_distribution([analysis], PLAYER)
    magnitude = metrics.magnitude_profile([analysis], PLAYER)
    ahead_behind = metrics.ahead_behind_split([analysis], PLAYER)
    problems = metrics.problem_positions([analysis], PLAYER)

    report_path = report.render_report(
        tmp_path, player=PLAYER, analyses=[analysis], phase_loss=phase_loss,
        magnitude=magnitude, ahead_behind=ahead_behind, problems=problems,
        model="kata1-b18c384nbt", visits=500,
    )

    assert report_path == tmp_path / "report.md"
    text = report_path.read_text()
    assert f"# baduk-lab report: {PLAYER}" in text
    assert "Games analyzed: 1" in text
    assert "2026-01-01 to 2026-01-01" in text
    assert "## Where your points leak" in text
    assert "## Mistake magnitude profile" in text
    assert "## Ahead/behind behavior" in text
    assert "## Problem set" in text
    for problem in problems:
        assert report._problem_relpath(problem) in text


def test_problem_relpath_is_stable_and_phase_grouped():
    opening = metrics.ProblemPosition(
        game="g.sgf", move_number=10, points_lost=5.0, played="Q16", best="D4")
    endgame = metrics.ProblemPosition(
        game="g.sgf", move_number=180, points_lost=5.0, played="Q16", best="D4")

    assert report._problem_relpath(opening) == "opening/g_m010.sgf"
    assert report._problem_relpath(endgame) == "endgame/g_m180.sgf"
    # stable regardless of the problem's position in a sorted list -- no
    # running index baked into the filename.
    assert report._problem_relpath(opening) == "opening/g_m010.sgf"


def test_export_problem_sgfs_hides_the_played_move(tmp_path):
    analysis = build_analysis(5, "b", losses={1: 2.0, 3: 10.0, 5: 6.0})
    problems = metrics.problem_positions([analysis], PLAYER)

    report.export_problem_sgfs(problems, tmp_path, analyses=[analysis])

    files = sorted(tmp_path.rglob("*.sgf"))
    assert len(files) == len(problems) == 2

    from sgfmill import sgf as sgf_lib
    problem = problems[0]
    path = tmp_path / report._problem_relpath(problem)
    assert path in files
    game = sgf_lib.Sgf_game.from_bytes(path.read_bytes())
    node = game.get_root()
    for _ in range(problem.move_number - 1):
        node = node[0]

    # the position right before the mistake branches into exactly two hidden
    # continuations (played, best) -- neither is played on the visible node itself.
    assert len(node) == 2
    played_node, best_node = node[0], node[1]
    assert played_node.get_move()[1] == move_from_vertex(problem.played, 19)
    assert best_node.get_move()[1] == move_from_vertex(problem.best, 19)


def test_export_problem_sgfs_skips_problems_from_unknown_games(tmp_path):
    analysis = build_analysis(3, "b", losses={1: 5.0}, name="known.sgf")
    fake_problem = metrics.ProblemPosition(
        game="missing.sgf", move_number=1, points_lost=5.0, played="Q16", best="D4")

    report.export_problem_sgfs([fake_problem], tmp_path, analyses=[analysis])

    assert list(tmp_path.rglob("*.sgf")) == []


def test_export_and_load_problem_index_round_trips(tmp_path):
    analysis = build_analysis(5, "b", losses={1: 2.0, 3: 10.0, 5: 6.0})
    problems = metrics.problem_positions([analysis], PLAYER)

    report.export_problem_index(problems, tmp_path)
    loaded = report.load_problem_index(tmp_path)

    assert {e.problem_id for e in loaded} == {p.problem_id for p in problems}
    by_id = {e.problem_id: e for e in loaded}
    for problem in problems:
        entry = by_id[problem.problem_id]
        assert entry.game == problem.game
        assert entry.move_number == problem.move_number
        assert entry.points_lost == problem.points_lost
        assert entry.path == report._problem_relpath(problem)
        assert entry.played == problem.played
        assert entry.best == problem.best


def _fake_side(rank_value: float, confidence: str = "high") -> SideEstimate:
    return SideEstimate(
        sample_count=20, score_sample_count=20, confidence=confidence,
        rank_value=rank_value, quality_score=None, strength_band="3-4d",
        rank_label=f"{rank_value:.1f} dan", first_choice_rate=0.5,
        good_move_rate=0.8, mistake_rate=0.0, weighted_point_loss=1.0,
        average_point_loss=0.5, match_rate=0.6,
    )


def _fake_game(name: str, date: str, focus_color: str = "b") -> GameAnalysis:
    black = PLAYER if focus_color == "b" else "rival"
    white = PLAYER if focus_color == "w" else "rival"
    record = GameRecord(path=Path(name), board_size=19, komi=6.5, player_black=black,
                        player_white=white, result="B+R", date=date, moves=[])
    return GameAnalysis(record=record, positions=[])


def test_strength_section_sorts_by_date_and_computes_rolling_average():
    analyses = [
        _fake_game("second.sgf", "2026-02-01"),
        _fake_game("first.sgf", "2026-01-01"),
        _fake_game("third.sgf", "2026-03-01"),
    ]
    strengths = {
        "first.sgf": GameStrengthEstimate(black=_fake_side(4.0), white=None),
        "second.sgf": GameStrengthEstimate(black=_fake_side(6.0), white=None),
        "third.sgf": GameStrengthEstimate(black=_fake_side(8.0), white=None),
    }

    lines = report._strength_section(analyses, strengths, [PLAYER])
    text = "\n".join(lines)

    # chronological, not input order
    assert text.index("first.sgf") < text.index("second.sgf") < text.index("third.sgf")
    # rolling average over {4.0}, {4.0,6.0}, {4.0,6.0,8.0}
    assert "| 2026-01-01 | first.sgf | Black | 3-4d | 4.0 | 4.0 |" in lines
    assert "| 2026-02-01 | second.sgf | Black | 3-4d | 6.0 | 5.0 |" in lines
    assert "| 2026-03-01 | third.sgf | Black | 3-4d | 8.0 | 6.0 |" in lines


def test_strength_section_omits_undated_and_unresolved_games():
    undated = _fake_game("undated.sgf", "")
    no_rank = _fake_game("no_rank.sgf", "2026-01-01")
    dated = _fake_game("dated.sgf", "2026-01-02")
    analyses = [undated, no_rank, dated]
    strengths = {
        "undated.sgf": GameStrengthEstimate(black=_fake_side(5.0), white=None),
        "no_rank.sgf": GameStrengthEstimate(
            black=SideEstimate(sample_count=1, score_sample_count=1, confidence="low",
                               rank_value=None, quality_score=None, strength_band="Beginner",
                               rank_label=None, first_choice_rate=0.0, good_move_rate=0.0,
                               mistake_rate=0.0, weighted_point_loss=0.0, average_point_loss=0.0,
                               match_rate=0.0),
            white=None,
        ),
        "dated.sgf": GameStrengthEstimate(black=_fake_side(5.0), white=None),
    }

    lines = report._strength_section(analyses, strengths, [PLAYER])
    text = "\n".join(lines)

    assert "undated.sgf" not in text
    assert "no_rank.sgf" not in text
    assert "dated.sgf" in text


def test_strength_section_omits_low_and_medium_confidence_games():
    low = _fake_game("low.sgf", "2026-01-01")
    medium = _fake_game("medium.sgf", "2026-01-02")
    high = _fake_game("high.sgf", "2026-01-03")
    analyses = [low, medium, high]
    strengths = {
        "low.sgf": GameStrengthEstimate(black=_fake_side(5.0, confidence="low"), white=None),
        "medium.sgf": GameStrengthEstimate(black=_fake_side(5.0, confidence="medium"), white=None),
        "high.sgf": GameStrengthEstimate(black=_fake_side(5.0, confidence="high"), white=None),
    }

    lines = report._strength_section(analyses, strengths, [PLAYER])
    text = "\n".join(lines)

    assert "low.sgf" not in text
    assert "medium.sgf" not in text
    assert "high.sgf" in text


def test_strength_section_empty_when_no_strengths():
    assert report._strength_section([_fake_game("a.sgf", "2026-01-01")], {}, [PLAYER]) == []


def test_export_game_records_writes_one_entry_per_game(tmp_path):
    a = build_analysis(3, "b", losses={1: 5.0}, name="a.sgf")
    b = build_analysis(2, "w", losses={2: 5.0}, name="b.sgf")

    path = report.export_game_records([a, b], tmp_path)

    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"a.sgf", "b.sgf"}
    assert data["a.sgf"]["board_size"] == 19
    assert data["a.sgf"]["moves"] == [["b", [3, 3]], ["w", [3, 3]], ["b", [3, 3]]]
    assert data["b.sgf"]["moves"] == [["b", [3, 3]], ["w", [3, 3]]]
