"""Tests for harvesting your own SGF comments into quiz problems.

The fixtures here are hand-built LizzieYzy-shaped SGFs rather than real
exports: a real one is ~200KB of KataGo search per game, and every
property this module reads (C[], LZ[], PB/PW) is small and stated
explicitly below, so a synthetic file documents the format better than a
truncated real one would.
"""

from pathlib import Path

import pytest

from baduk_lab import annotations

PLAYER = "hero"

# One LZ[] payload: a header line (winrate of whoever just moved, a visit
# count, then scoreMean from the perspective of whoever is to move), then
# " info "-separated candidates.
def _lz(winrate_just_moved: float, score_to_play: float, candidates: str) -> str:
    return (f"komi65 {winrate_just_moved} 10k {score_to_play} 12.0 0.0 "
            f"rootVisits=10000 wrn=0.04\n{candidates}")


def _engine_comment(extra: str = "") -> str:
    """The block LizzieYzy writes into C[] itself, optionally with your
    own text appended the way LizzieYzy appends it."""
    block = ("Black win rate: 46.9% (-0.3%)\n"
             "lead: -0.3 (-0.0) stdev: 12.9\n"
             "(komi65 / 9.3k visits)\n"
             "komi: 6.5 WRN:0.04")
    return f"{block}\n{extra}" if extra else block


def _write_sgf(tmp_path: Path, nodes: list[str], *, black: str = PLAYER,
               white: str = "rival", name: str = "game.sgf") -> Path:
    root = f"(;CA[UTF-8]SZ[19]KM[6.5]PB[{black}]PW[{white}]DT[2026-11-21]"
    path = tmp_path / name
    path.write_text(root + "".join(nodes) + ")", encoding="utf-8")
    return path


def _move_node(color: str, sgf_coord: str, *, lz: str | None = None,
               comment: str | None = None) -> str:
    out = f";{color}[{sgf_coord}]"
    if lz is not None:
        out += f"LZ[{lz}]"
    if comment is not None:
        out += f"C[{comment}]"
    return out


# --- separating your text from LizzieYzy's ----------------------------

def test_user_note_drops_generated_lines_and_keeps_yours():
    assert annotations.user_note(_engine_comment("N8 is heavy.")) == "N8 is heavy."


def test_user_note_is_empty_when_you_wrote_nothing():
    assert annotations.user_note(_engine_comment()) == ""


def test_vertices_in_reads_a_point_typed_against_the_previous_word():
    """Notes are typed fast. "atP13" is a coordinate with a missed space,
    and dropping it silently makes the card quiz a different move than the
    note recommends."""
    assert annotations.vertices_in("extend to 5th atP13 line", 19) == ["P13"]


def test_vertices_in_still_ignores_prose_and_generated_numbers():
    assert annotations.vertices_in("Top 10 moves, 3rd line", 19) == []
    assert annotations.vertices_in("komi65 is the komi", 19) == []
    # Off the board, so a header's "KM65" can't read as a point.
    assert annotations.vertices_in("KM65 SZ19", 19) == []


def test_user_note_is_empty_for_a_flash_analyze_stamp():
    """LizzieYzy's one-click pass stamps "(Flash_Analyze / 2 visits)" onto
    nearly every node. It is its footer, not a note of yours, so a node
    carrying only that must not become a problem."""
    assert annotations.user_note("(Flash_Analyze / 2 visits)") == ""
    assert annotations.user_note(
        "(Flash_Analyze / 2 visits)\nN8 is heavy.") == "N8 is heavy."


def test_user_note_keeps_a_blank_line_inside_your_own_text():
    note = annotations.user_note(_engine_comment("First point.\n\nSecond point."))

    assert note == "First point.\n\nSecond point."


def test_user_note_drops_the_roots_accuracy_summary():
    root_comment = ("Engine Rules:Japanese\n\nWhite win rate: 52.9% \n"
                    "lead: 0.3  stdev: 12.9\n(komi65 / 9.3k visits)\n"
                    "komi: 6.5 WRN:0.04\nBlack AI accuracy:71.1\n"
                    "Black mismatch(Top 10): 7(-3.1%), 17(+2.8%)\n"
                    "White AI accuracy:83.7\nWhite mismatch(Top 10): 16(-4.4%)")

    assert annotations.user_note(root_comment) == ""


# --- resolving a note to the move it is about -------------------------

def test_note_on_your_own_move_is_about_that_move(tmp_path):
    """"1 space jump at N8 is very heavy" -- written on the node that
    played N8, about the move itself."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, "move D4 visits 900 scoreMean 2.0")),
        _move_node("B", "cc", lz=_lz(40.0, 1.0, "move R7 visits 900 scoreMean 1.0"),
                   comment=_engine_comment("That jump was heavy.")),
    ])

    mistakes = annotations.mistakes_from_sgf(path, PLAYER)

    assert [m.move_number for m in mistakes] == [3]
    assert mistakes[0].played == "C17"  # "cc" -> col 2, row 2 from the top
    assert mistakes[0].note == "That jump was heavy."


def test_note_on_your_opponents_move_is_about_your_reply(tmp_path):
    """"black must ... atari at R7" -- written on White's move, about
    Black's answer to it."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, "move R7 visits 900 scoreMean 2.0"),
                   comment=_engine_comment("Black must atari at R7.")),
        _move_node("B", "cc", lz=_lz(40.0, 1.0, "move D4 visits 900 scoreMean 1.0")),
    ])

    mistakes = annotations.mistakes_from_sgf(path, PLAYER)

    assert [m.move_number for m in mistakes] == [3]
    assert mistakes[0].best == "R7"


def test_notes_on_both_sides_of_one_move_are_not_quizzed_twice(tmp_path):
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, "move R7 visits 900 scoreMean 2.0"),
                   comment=_engine_comment("Black must atari at R7.")),
        _move_node("B", "cc", lz=_lz(40.0, 1.0, "move D4 visits 900 scoreMean 1.0"),
                   comment=_engine_comment("...and that atari was the wrong one.")),
    ])

    mistakes = annotations.mistakes_from_sgf(path, PLAYER)

    assert [m.move_number for m in mistakes] == [3]


def test_your_color_decides_which_move_a_note_is_about(tmp_path):
    """The same file read as White resolves the same note to move 2, not 3."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0"),
                   comment=_engine_comment("White should answer here.")),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, "move R7 visits 900 scoreMean 2.0")),
    ], black="rival", white=PLAYER)

    mistakes = annotations.mistakes_from_sgf(path, PLAYER)

    assert [m.move_number for m in mistakes] == [2]
    assert mistakes[0].color == "w"


def test_uncommented_nodes_produce_no_problems(tmp_path):
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0"),
                   comment=_engine_comment()),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, "move R7 visits 900 scoreMean 2.0")),
    ])

    assert annotations.mistakes_from_sgf(path, PLAYER) == []


def test_game_you_did_not_play_in_is_skipped(tmp_path):
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0"),
                   comment=_engine_comment("Interesting.")),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, "move R7 visits 900 scoreMean 2.0")),
    ], black="someone", white="someone-else")

    assert annotations.mistakes_from_sgf(path, PLAYER) == []


def test_lizzieyzy_tags_you_as_You_in_games_against_its_own_ai(tmp_path):
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, "move R7 visits 900 scoreMean 2.0"),
                   comment=_engine_comment("Too slow.")),
    ], black="HumanSL AI (6 dan)", white="You")

    mistakes = annotations.mistakes_from_sgf(path, PLAYER)

    assert [m.color for m in mistakes] == ["w"]


def test_an_opponent_handle_containing_you_is_not_mistaken_for_You(tmp_path):
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, "move R7 visits 900 scoreMean 2.0"),
                   comment=_engine_comment("Too slow.")),
    ], black="younggun", white="rival")

    assert annotations.mistakes_from_sgf(path, PLAYER) == []


def test_note_about_a_move_past_the_end_of_the_game_is_skipped(tmp_path):
    """A note on the final move, when that move was your opponent's, has
    no reply of yours to be about."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, "move R7 visits 900 scoreMean 2.0"),
                   comment=_engine_comment("Black had to answer.")),
    ])

    assert annotations.mistakes_from_sgf(path, PLAYER) == []


def test_note_with_no_stored_analysis_before_it_is_skipped(tmp_path):
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb"),  # LizzieYzy left no search here
        _move_node("B", "cc", lz=_lz(40.0, 1.0, "move R7 visits 900 scoreMean 1.0"),
                   comment=_engine_comment("Wrong direction.")),
    ])

    assert annotations.mistakes_from_sgf(path, PLAYER) == []


# --- reading the answer and the cost out of LZ[] ----------------------

def test_best_move_follows_katagos_order_not_the_visit_count(tmp_path):
    """`order 0` is the engine's own pick. It selects on a confidence
    bound, so the move it searched most is not always the one it
    recommends -- and when they disagree, order 0 is the one holding the
    better score."""
    candidates = ("move R5 visits 756 winrate 4825 scoreMean -0.13 order 0 "
                  "info move O7 visits 2588 winrate 4802 scoreMean -0.18 order 1")
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, candidates)),
        _move_node("B", "cc", lz=_lz(40.0, 1.0, "move D4 visits 900 scoreMean 1.0"),
                   comment=_engine_comment("Wrong point.")),
    ])

    assert annotations.mistakes_from_sgf(path, PLAYER)[0].best == "R5"


def test_best_move_falls_back_to_visits_without_a_usable_order(tmp_path):
    """A payload with no `order`, or one that isn't a clean ranking (some
    LizzieYzy versions write a counter that accumulates across search
    passes), is ranked by visits instead."""
    no_order = ("move R5 visits 756 winrate 4825 scoreMean -0.13 "
                "info move O7 visits 2588 winrate 4802 scoreMean -0.18")
    repeated = ("move R5 visits 756 winrate 4825 scoreMean -0.13 order 0 "
                "info move O7 visits 2588 winrate 4802 scoreMean -0.18 order 0")
    for candidates in (no_order, repeated):
        path = _write_sgf(tmp_path, [
            _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
            _move_node("W", "bb", lz=_lz(50.0, 2.0, candidates)),
            _move_node("B", "cc", lz=_lz(40.0, 1.0, "move D4 visits 900 scoreMean 1.0"),
                       comment=_engine_comment("Wrong point.")),
        ], name=f"{hash(candidates)}.sgf")

        assert annotations.mistakes_from_sgf(path, PLAYER)[0].best == "O7"


def test_points_lost_flips_the_opponents_perspective_back(tmp_path):
    """scoreMean is always from the perspective of whoever is to move, so
    the evaluation after your move belongs to your opponent."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        # Before your move 3: you lead by 0.97.
        _move_node("W", "bb", lz=_lz(50.0, 0.974227, "move R7 visits 900 scoreMean 0.97")),
        # After it: your opponent is at -0.132, so you lead by only 0.132.
        _move_node("B", "cc", lz=_lz(40.0, -0.132047, "move D4 visits 900 scoreMean -0.13"),
                   comment=_engine_comment("Lost ground.")),
    ])

    assert annotations.mistakes_from_sgf(path, PLAYER)[0].points_lost == \
        pytest.approx(0.842, abs=0.001)


def test_winrate_drop_catches_what_points_lost_misses(tmp_path):
    """The case this whole module exists for: barely a point, but a 12%
    winrate swing, so `analyze`'s 4-point threshold never sees it."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        # 36.4% belongs to White, who just moved -- so you are at 63.6%.
        _move_node("W", "bb", lz=_lz(36.4, 0.974227, "move R7 visits 900 scoreMean 0.97")),
        # 51.7% belongs to you, who just moved.
        _move_node("B", "cc", lz=_lz(51.7, -0.132047, "move D4 visits 900 scoreMean -0.13"),
                   comment=_engine_comment("Lost ground.")),
    ])

    mistake = annotations.mistakes_from_sgf(path, PLAYER)[0]

    assert mistake.winrate_drop == pytest.approx(0.119, abs=0.001)
    assert mistake.points_lost < 1.0


def test_a_move_that_gained_ground_is_clamped_to_zero(tmp_path):
    """Independent per-position searches can disagree slightly; a note on
    a move the engine scores as an improvement is still worth drilling,
    just not as a negative loss."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb", lz=_lz(40.0, 0.5, "move R7 visits 900 scoreMean 0.5")),
        _move_node("B", "cc", lz=_lz(70.0, -2.0, "move D4 visits 900 scoreMean -2.0"),
                   comment=_engine_comment("Still not what I wanted.")),
    ])

    mistake = annotations.mistakes_from_sgf(path, PLAYER)[0]

    assert mistake.points_lost == 0.0
    assert mistake.winrate_drop == 0.0


# --- ids and folder harvesting ----------------------------------------

def test_problem_id_is_stable_and_namespaced_away_from_the_analyze_deck():
    mistake = annotations.AnnotatedMistake(
        game="my-game.sgf", move_number=23, color="b", note="n",
        played="S4", best="R7", points_lost=0.8, winrate_drop=0.12)

    assert mistake.problem_id == "note::my-game::m23"


def test_harvest_folder_sorts_worst_winrate_drop_first(tmp_path):
    def game(name, winrate_after):
        _write_sgf(tmp_path, [
            _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
            _move_node("W", "bb", lz=_lz(30.0, 1.0, "move R7 visits 900 scoreMean 1.0")),
            _move_node("B", "cc", lz=_lz(winrate_after, 1.0, "move D4 visits 900 scoreMean 1.0"),
                       comment=_engine_comment("note")),
        ], name=name)

    game("small.sgf", 65.0)  # 70% -> 65%, a 5-point drop
    game("big.sgf", 40.0)    # 70% -> 40%, a 30-point drop

    mistakes = annotations.harvest_folder(tmp_path, PLAYER)

    assert [m.game for m in mistakes] == ["big.sgf", "small.sgf"]


def test_harvest_folder_skips_an_unparseable_file_without_failing(tmp_path):
    (tmp_path / "broken.sgf").write_text("this is not an SGF", encoding="utf-8")
    _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb", lz=_lz(50.0, 1.0, "move R7 visits 900 scoreMean 1.0")),
        _move_node("B", "cc", lz=_lz(40.0, 1.0, "move D4 visits 900 scoreMean 1.0"),
                   comment=_engine_comment("note")),
    ], name="good.sgf")

    assert [m.game for m in annotations.harvest_folder(tmp_path, PLAYER)] == ["good.sgf"]


def test_moves_of_reads_the_main_line_for_the_quizs_board(tmp_path):
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa"), _move_node("W", "bb"), _move_node("B", "cc"),
    ])

    board_size, moves = annotations.moves_of(path)

    assert board_size == 19
    assert [(m.number, m.color) for m in moves] == [(1, "b"), (2, "w"), (3, "b")]


# --- the variation you played out, which beats KataGo's pick -----------
#
# Branching off in LizzieYzy to try a move records your line as a sibling
# of the real game, with the game kept as the first child. These build
# that shape: `_branch` is the parent, whose first child is what you
# really played and whose later children are what you explored.

def _branch(color: str, sgf_coord: str, lz: str, comment: str,
            real: str, explored: list[str], tail_lz: str) -> str:
    """One commented branch point, followed by the real game move and
    each explored variation as siblings."""
    other = "W" if color == "B" else "B"
    lines = "".join(f"({_move_node(other, v, lz=tail_lz)})" for v in explored)
    return (f";{color}[{sgf_coord}]LZ[{lz}]C[{comment}]"
            f"({_move_node(other, real, lz=tail_lz)})" + lines)


def test_a_move_you_explored_and_named_in_your_note_is_the_answer(tmp_path):
    """The whole point: you played D16 out yourself and wrote "cut at the
    2nd line D16 first". That is the answer, not KataGo's top move."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _branch("W", "bb", _lz(50.0, 2.0, "move R7 visits 9000 scoreMean 2.0"),
                _engine_comment("white must cut at the 2nd line D16 first."),
                real="cc", explored=["dd"],
                tail_lz=_lz(40.0, 1.0, "move D4 visits 900 scoreMean 1.0")),
    ])

    mistake = annotations.mistakes_from_sgf(path, PLAYER)[0]

    assert mistake.played == "C17"   # the real game's move 3
    assert mistake.best == "D16"     # "dd", the line you played out
    assert "R7" in mistake.alternatives  # KataGo's pick still counts


def test_an_explored_move_your_note_does_not_name_stays_an_alternative(tmp_path):
    """You sometimes branch just to see what happens. Without the note
    backing it up, KataGo keeps the top spot."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _branch("W", "bb", _lz(50.0, 2.0, "move R7 visits 9000 scoreMean 2.0"),
                _engine_comment("this whole direction was wrong."),
                real="cc", explored=["dd"],
                tail_lz=_lz(40.0, 1.0, "move D4 visits 900 scoreMean 1.0")),
    ])

    mistake = annotations.mistakes_from_sgf(path, PLAYER)[0]

    assert mistake.best == "R7"
    assert mistake.alternatives == ["D16"]


def test_the_named_variation_wins_when_you_explored_several(tmp_path):
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _branch("W", "bb", _lz(50.0, 2.0, "move R7 visits 9000 scoreMean 2.0"),
                _engine_comment("the 3 space pincer at D16 was the move."),
                real="cc", explored=["ee", "dd"],
                tail_lz=_lz(40.0, 1.0, "move D4 visits 900 scoreMean 1.0")),
    ])

    mistake = annotations.mistakes_from_sgf(path, PLAYER)[0]

    assert mistake.best == "D16"
    assert set(mistake.alternatives) == {"E15", "R7"}


def test_the_move_you_played_is_never_treated_as_explored(tmp_path):
    """The first child is the real game, not a variation -- and a note
    naming the move you played ("the jump at C17 was heavy") must not turn
    that mistake into the answer."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _branch("W", "bb", _lz(50.0, 2.0, "move R7 visits 9000 scoreMean 2.0"),
                _engine_comment("the jump at C17 was heavy."),
                real="cc", explored=["dd"],
                tail_lz=_lz(40.0, 1.0, "move D4 visits 900 scoreMean 1.0")),
    ])

    mistake = annotations.mistakes_from_sgf(path, PLAYER)[0]

    assert mistake.played == "C17"
    assert mistake.best != "C17"
    assert "C17" not in mistake.alternatives


# --- points named in a note -------------------------------------------

def test_vertices_in_reads_the_points_a_note_names():
    assert annotations.vertices_in(
        "must hane M9 on white's 2 stone's head", 19) == ["M9"]


def test_vertices_in_is_case_insensitive_and_keeps_note_order():
    assert annotations.vertices_in("pincers at r9/R8/r10", 19) == ["R9", "R8", "R10"]


def test_vertices_in_ignores_prose_that_merely_looks_like_a_point():
    assert annotations.vertices_in(
        "the 3rd line, mismatch Top 10, within 2 moves", 19) == []


def test_vertices_in_drops_points_off_the_board():
    assert annotations.vertices_in("around M99 and B13", 19) == ["B13"]
    assert annotations.vertices_in("B13 is off a 9x9", 9) == []


def test_note_vertices_are_recorded_for_the_board_to_mark(tmp_path):
    """A note can discuss a point nobody recommends here ("the moyo at
    F7"); the quiz marks it so the note is readable against the board."""
    path = _write_sgf(tmp_path, [
        _move_node("B", "aa", lz=_lz(50.0, 1.0, "move Q16 visits 900 scoreMean 1.0")),
        _move_node("W", "bb", lz=_lz(50.0, 2.0, "move R7 visits 900 scoreMean 2.0"),
                   comment=_engine_comment("the uncertain moyo at F7 was the problem.")),
        _move_node("B", "cc", lz=_lz(40.0, 1.0, "move D4 visits 900 scoreMean 1.0")),
    ])

    assert annotations.mistakes_from_sgf(path, PLAYER)[0].note_vertices == ["F7"]
