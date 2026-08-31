from sgfmill.common import move_from_vertex

from baduk_lab import metrics, report
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
