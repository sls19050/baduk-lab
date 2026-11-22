"""The misplaced-comment check.

Each test builds one game where a single note lands somewhere, and asserts
which verdict it earns. The rule that matters most is the suppression one:
a note naming the move the card is graded against is about that move, and
a worse move nearby must not cast doubt on it.
"""

from pathlib import Path

from baduk_lab import note_check

PLAYER = "you"


def _lz(winrate_just_moved: float, score_to_play: float, candidates: str) -> str:
    return (f"komi65 {winrate_just_moved} 10k {score_to_play} 12.0 0.0 "
            f"rootVisits=10000 wrn=0.04\n{candidates}")


def _cand(move: str, *, visits: int = 900, score: float = 1.0,
          order: int = 0) -> str:
    return f"move {move} visits {visits} winrate 5000 scoreMean {score} order {order}"


def _engine_comment(extra: str) -> str:
    return ("Black win rate: 46.9% (-0.3%)\n"
            "lead: -0.3 (-0.0) stdev: 12.9\n"
            "(komi65 / 9.3k visits)\n"
            f"komi: 6.5\n{extra}")


def _node(color: str, coord: str, *, lz: str, comment: str | None = None) -> str:
    out = f";{color}[{coord}]LZ[{lz}]"
    if comment is not None:
        out += f"C[{_engine_comment(comment)}]"
    return out


def _write(tmp_path: Path, nodes: list[str], name: str = "game.sgf") -> Path:
    root = f"(;CA[UTF-8]SZ[19]KM[6.5]PB[{PLAYER}]PW[rival]DT[2026-11-22]"
    path = tmp_path / name
    path.write_text(root + "".join(nodes) + ")", encoding="utf-8")
    return path


def _rules(path: Path) -> list[str]:
    _, issues = note_check.check_file(path, PLAYER)
    return [issue.skipped or issue.rule for issue in issues]


# --- the suppression rule -------------------------------------------------

def test_a_note_naming_the_cards_answer_is_never_flagged(tmp_path):
    """Black's move 3 cost nothing and move 5 cost 10 points, but the note
    on 3 names K4 -- which is the answer the card is graded against -- so
    it is provably about move 3 and the cheap-move rules must stay quiet."""
    path = _write(tmp_path, [
        _node("B", "aa", lz=_lz(50.0, 1.0, _cand("K4"))),
        _node("W", "bb", lz=_lz(50.0, 1.0, _cand("K4"))),
        # Black 3: KataGo wanted K4, note says K4 -> corroborated.
        _node("B", "cc", lz=_lz(50.0, 1.0, _cand("Q10")),
              comment="should play the extension at K4"),
        _node("W", "dd", lz=_lz(50.0, 1.0, _cand("Q10"))),
        # Black 5 drops 10 points: a second mistake, not evidence about 3.
        _node("B", "ee", lz=_lz(50.0, 9.0, _cand("Q10"))),
    ])

    assert _rules(path) == []


def test_a_note_naming_a_line_you_played_out_is_not_flagged(tmp_path):
    """A variation you tried while reviewing is saved as a later sibling of
    the real game and counts as a right answer, so a note naming it is
    corroborated even though KataGo picked something else."""
    # The real game stays child 0; D16 is the line you played out yourself.
    root = f"(;CA[UTF-8]SZ[19]KM[6.5]PB[{PLAYER}]PW[rival]DT[2026-11-22]"
    path = tmp_path / "explored.sgf"
    path.write_text(
        root
        + _node("B", "aa", lz=_lz(50.0, 1.0, _cand("K4")))
        + _node("W", "bb", lz=_lz(50.0, 1.0, _cand("Q10")))
        + "("
        + _node("B", "cc", lz=_lz(50.0, 1.0, _cand("Q10")),
                comment="the attachment at D16 was better")
        + ")(" + _node("B", "dd", lz=_lz(50.0, 1.0, _cand("Q10"))) + "))",
        encoding="utf-8")

    assert _rules(path) == []


# --- the misplacement rules ----------------------------------------------

def test_a_cheap_note_beside_a_costly_move_is_called_misplaced(tmp_path):
    """The note names a point that is nothing here, its own move cost
    nothing, and your move two later threw away 10 points."""
    path = _write(tmp_path, [
        _node("B", "aa", lz=_lz(50.0, 1.0, _cand("K4"))),
        _node("W", "bb", lz=_lz(50.0, 1.0, _cand("K4"))),
        # -1.0 against the 1.0 before it: this move cost nothing.
        _node("B", "cc", lz=_lz(50.0, -1.0, _cand("Q10")),
              comment="the cut at T2 is the key point"),
        _node("W", "dd", lz=_lz(50.0, 1.0, _cand("Q10"))),
        _node("B", "ee", lz=_lz(50.0, 9.0, _cand("Q10"))),
    ])

    issues = note_check.check_file(path, PLAYER)[1]
    assert [i.rule for i in issues] == ["misplaced"]
    assert issues[0].move_number == 3
    assert issues[0].nearby_move == 5
    assert issues[0].confidence == "high"


def test_a_note_recommending_an_unaccepted_point_disagrees(tmp_path):
    """A real mistake, but the move the note recommends is not what the
    card accepts -- so the card would mark your own answer wrong."""
    path = _write(tmp_path, [
        _node("B", "aa", lz=_lz(50.0, 1.0, _cand("K4"))),
        _node("W", "bb", lz=_lz(50.0, 1.0, _cand("K4"))),
        _node("B", "cc", lz=_lz(50.0, 4.0, _cand("Q10")),
              comment="black should defend at T2 instead"),
    ])

    assert _rules(path) == ["answer_disagrees"]


def test_a_note_on_a_move_katago_rates_best_has_no_wrong_answer(tmp_path):
    path = _write(tmp_path, [
        _node("B", "aa", lz=_lz(50.0, 1.0, _cand("K4"))),
        _node("W", "bb", lz=_lz(50.0, 1.0, _cand("C17"))),
        _node("B", "cc", lz=_lz(50.0, 1.0, _cand("Q10")),
              comment="good solid shape, nothing to fix"),
    ])

    issues = note_check.check_file(path, PLAYER)[1]
    assert [i.rule for i in issues] == ["no_wrong_answer"]
    assert issues[0].confidence == "low"


# --- notes that were never drilled at all --------------------------------

def test_a_note_about_a_move_past_the_end_is_reported(tmp_path):
    """The class that started this: a comment on your opponent's last move
    resolves to a reply you never made, and the harvest drops it."""
    path = _write(tmp_path, [
        _node("B", "aa", lz=_lz(50.0, 1.0, _cand("K4"))),
        _node("W", "bb", lz=_lz(50.0, 1.0, _cand("K4")),
              comment="should have taken the corner"),
    ])

    issues = note_check.check_file(path, PLAYER)[1]
    assert [i.skipped for i in issues] == ["past_end"]
    assert issues[0].confidence == "high"
    assert "never played" in issues[0].advice


def test_two_notes_on_one_move_report_the_shadowed_one(tmp_path):
    """A note on your move N and one on your opponent's N-1 both resolve to
    N; only the first is drilled, so the other should not vanish silently."""
    path = _write(tmp_path, [
        _node("B", "aa", lz=_lz(50.0, 1.0, _cand("K4"))),
        _node("W", "bb", lz=_lz(50.0, 1.0, _cand("K4")),
              comment="my reply at D4 was wrong"),
        _node("B", "cc", lz=_lz(50.0, 1.0, _cand("K4")),
              comment="D4 was wrong here"),
    ])

    assert "shadowed" in _rules(path)


# --- the report -----------------------------------------------------------

def test_the_report_says_so_when_nothing_looks_wrong():
    assert "none look misplaced" in note_check.format_report(12, [])


def test_the_report_names_the_game_the_move_and_the_advice(tmp_path):
    path = _write(tmp_path, [
        _node("B", "aa", lz=_lz(50.0, 1.0, _cand("K4"))),
        _node("W", "bb", lz=_lz(50.0, 1.0, _cand("K4"))),
        # -1.0 against the 1.0 before it: this move cost nothing.
        _node("B", "cc", lz=_lz(50.0, -1.0, _cand("Q10")),
              comment="the cut at T2 is the key point"),
        _node("W", "dd", lz=_lz(50.0, 1.0, _cand("Q10"))),
        _node("B", "ee", lz=_lz(50.0, 9.0, _cand("Q10"))),
    ])

    examined, issues = note_check.check_folder(tmp_path, PLAYER)
    report = note_check.format_report(examined, issues)
    assert "game.sgf" in report
    assert "move 3" in report
    assert "T2" in report
    assert "move 5 nearby cost" in report
