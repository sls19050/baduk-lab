import json
from pathlib import Path

from sgfmill import sgf as sgf_lib
from sgfmill.common import move_from_vertex

from baduk_lab import metrics, report
from baduk_lab.annotations import AnnotatedMistake
from baduk_lab.engine import GameAnalysis
from baduk_lab.loader import GameRecord, Move
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


# --- the notes deck (annotations.py's half of the problem set) ---------

def _mistake(game="g.sgf", move_number=23, note="atari at R7", points_lost=0.8,
             winrate_drop=0.12):
    return AnnotatedMistake(
        game=game, move_number=move_number, color="b", note=note,
        played="S4", best="R7", points_lost=points_lost, winrate_drop=winrate_drop)


def _note_record(name="g.sgf", total_moves=30):
    return GameRecord(
        path=Path(name), board_size=19, komi=6.5, player_black=PLAYER,
        player_white="rival", result="", moves=[
            Move(number=m, color=("b" if m % 2 == 1 else "w"), coord=(3, 3))
            for m in range(1, total_moves + 1)
        ])


def test_export_and_load_note_index_round_trips_your_own_words(tmp_path):
    mistake = _mistake(note="1 space jump at N8 is very heavy.")

    report.export_note_index([mistake], tmp_path)
    loaded = report.load_note_index(tmp_path)

    assert len(loaded) == 1
    assert loaded[0].problem_id == mistake.problem_id
    assert loaded[0].note == "1 space jump at N8 is very heavy."
    assert loaded[0].source == "note"
    assert loaded[0].winrate_drop == 0.12


def test_load_note_index_is_empty_when_notes_never_ran(tmp_path):
    assert report.load_note_index(tmp_path) == []


def test_note_entries_cannot_collide_with_analyze_entries(tmp_path):
    """Both decks can hold the same game at the same move -- they're found
    different ways -- and each has to keep its own review history."""
    analysis = build_analysis(30, "b", losses={23: 10.0}, name="g.sgf")
    problems = metrics.problem_positions([analysis], PLAYER)

    report.export_problem_index(problems, tmp_path)
    report.export_note_index([_mistake(game="g.sgf", move_number=23)], tmp_path)

    ids = ({e.problem_id for e in report.load_problem_index(tmp_path)} |
           {e.problem_id for e in report.load_note_index(tmp_path)})
    assert len(ids) == 2


def test_export_note_sgfs_hides_your_move_and_attaches_your_note(tmp_path):
    report.export_note_sgfs([_mistake()], tmp_path, {"g.sgf": _note_record()})

    path = tmp_path / "notes" / "g_m023.sgf"
    game = sgf_lib.Sgf_game.from_bytes(path.read_bytes())
    assert "atari at R7" in game.get_root().get("C")

    # The recorded line stops before move 23 (root + moves 1..22), and
    # both answers hang off it as siblings.
    branch_point = game.get_main_sequence()[22]
    assert len(branch_point) == 2
    assert {node.get_move()[1] for node in branch_point} == {
        move_from_vertex("S4", 19), move_from_vertex("R7", 19)}


def test_export_note_sgfs_skips_a_game_it_has_no_moves_for(tmp_path):
    report.export_note_sgfs([_mistake(game="missing.sgf")], tmp_path, {})

    assert not (tmp_path / "notes").exists() or \
        list((tmp_path / "notes").iterdir()) == []


def test_export_note_sgfs_removes_the_file_of_a_note_you_moved(tmp_path):
    """Re-reviewing a game and putting the comment on a different move must
    not leave the old move's problem behind in problems/notes/."""
    records = {"g.sgf": _note_record()}
    report.export_note_sgfs([_mistake(move_number=23)], tmp_path, records)
    assert (tmp_path / "notes" / "g_m023.sgf").exists()

    report.export_note_sgfs([_mistake(move_number=19)], tmp_path, records)

    assert (tmp_path / "notes" / "g_m019.sgf").exists()
    assert not (tmp_path / "notes" / "g_m023.sgf").exists()


def test_export_note_sgfs_leaves_other_games_alone(tmp_path):
    records = {"g.sgf": _note_record(), "h.sgf": _note_record("h.sgf")}
    report.export_note_sgfs(
        [_mistake(game="g.sgf"), _mistake(game="h.sgf")], tmp_path, records)

    # a harvest that still finds both notes keeps both files
    report.export_note_sgfs(
        [_mistake(game="g.sgf"), _mistake(game="h.sgf")], tmp_path, records)

    assert {p.name for p in (tmp_path / "notes").glob("*.sgf")} == {
        "g_m023.sgf", "h_m023.sgf"}


def test_load_game_records_merges_both_decks(tmp_path):
    report.export_game_records([build_analysis(2, "b", losses={}, name="a.sgf")], tmp_path)
    report.export_note_game_records({"n.sgf": _note_record("n.sgf", 2)}, tmp_path)

    assert set(report.load_game_records(tmp_path)) == {"a.sgf", "n.sgf"}


def test_load_game_records_survives_either_deck_missing(tmp_path):
    assert report.load_game_records(tmp_path) == {}

    report.export_note_game_records({"n.sgf": _note_record("n.sgf", 2)}, tmp_path)
    assert set(report.load_game_records(tmp_path)) == {"n.sgf"}


def test_an_index_written_before_the_notes_deck_existed_still_loads(tmp_path):
    """source/note/winrate_drop were added to ProblemIndexEntry later; an
    index.json from an earlier `analyze` run has none of them."""
    (tmp_path / "index.json").write_text(json.dumps([{
        "problem_id": "g::m10", "game": "g.sgf", "move_number": 10,
        "phase": "opening", "points_lost": 9.0, "path": "opening/g_m010.sgf",
        "played": "D4", "best": "Q16",
    }]), encoding="utf-8")

    entry = report.load_problem_index(tmp_path)[0]

    assert entry.source == "katago"
    assert entry.note == ""
    assert entry.winrate_drop == 0.0
