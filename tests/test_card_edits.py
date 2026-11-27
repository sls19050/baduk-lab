"""Editing a card's answer and note from the quiz page."""

import functools
import http.server
import json
import re
import threading
import urllib.request
from datetime import date

import pytest

from baduk_lab import card_edits
from baduk_lab.cli import _QuizRequestHandler
from baduk_lab.quiz_html import render_quiz_html
from baduk_lab.report import ProblemIndexEntry

TODAY = date(2026, 11, 26)


def _entry(pid="g::m10", best="Q16", alternatives=(), note="harvested note"):
    return ProblemIndexEntry(
        problem_id=pid, game="g.sgf", move_number=10, phase="opening",
        points_lost=3.0, path="notes/g_m010.sgf", played="D4", best=best,
        source="note", note=note, alternatives=list(alternatives))


# --- the edits file ----------------------------------------------------

def test_an_edit_replaces_the_harvested_answer_and_note():
    edits = {}
    card_edits.set_edit(edits, _entry(), "g::m10", "R3", ["Q3", "R3"], "  new note ", TODAY)

    [edited] = card_edits.apply([_entry()], edits)

    assert (edited.best, edited.alternatives, edited.note) == ("R3", ["Q3"], "new note")


def test_cards_without_an_edit_are_untouched():
    other = _entry(pid="g::m20")
    assert card_edits.apply([other], {"g::m10": {}}) == [other]


def test_re_editing_keeps_what_the_harvest_originally_said():
    edits = {}
    card_edits.set_edit(edits, _entry(), "g::m10", "R3", [], "first", TODAY)
    # The second edit sees the already-edited card; `was` must still be
    # the harvested version, since that's what Reset goes back to.
    edited = card_edits.apply([_entry()], edits)[0]
    card_edits.set_edit(edits, edited, "g::m10", "R4", [], "second", TODAY)

    assert edits["g::m10"]["was"] == {"best": "Q16", "alternatives": [],
                                      "note": "harvested note"}


def test_an_edit_survives_a_re_harvest(tmp_path):
    """The point of a separate file: harvesting rewrites the deck, not this."""
    path = tmp_path / card_edits.FILENAME
    edits = {}
    card_edits.set_edit(edits, _entry(), "g::m10", "R3", [], "mine", TODAY)
    card_edits.save(path, edits)

    rehavested = _entry(best="C9", note="harvested note")  # new network, new pick
    [card] = card_edits.apply([rehavested], card_edits.load(path))

    assert (card.best, card.note) == ("R3", "mine")


def test_reset_removes_the_edit():
    edits = {}
    card_edits.set_edit(edits, _entry(), "g::m10", "R3", [], "", TODAY)
    card_edits.reset(edits, "g::m10")
    assert edits == {}


@pytest.mark.parametrize("best, alternatives, note", [
    ("", [], "x"),          # no main answer
    ("I5", [], "x"),        # Go has no I column
    ("R3", ["zz"], "x"),
    ("R3", "Q3", "x"),      # not a list
    ("R3", [], None),
])
def test_bad_edits_are_refused(best, alternatives, note):
    with pytest.raises(ValueError):
        card_edits.validate(best, alternatives, note)


def test_missing_edits_file_means_no_edits(tmp_path):
    assert card_edits.load(tmp_path / "nope.json") == {}


# --- the quiz page -----------------------------------------------------

def _games():
    moves = [["b" if m % 2 == 1 else "w", [m % 19, m // 19]] for m in range(1, 30)]
    return {"g.sgf": {"board_size": 19, "moves": moves}}


def _page_data(path):
    text = path.read_text(encoding="utf-8")
    return json.loads(re.search(r"const DATA = (.*);\n", text).group(1).replace("<\\/", "</"))


def test_page_marks_edited_cards_and_keeps_the_harvested_version(tmp_path):
    original = _entry()
    edits = {}
    card_edits.set_edit(edits, original, "g::m10", "R3", ["Q3"], "now hane at K10", TODAY)
    [edited] = card_edits.apply([original], edits)

    out = render_quiz_html([edited], _games(), tmp_path / "quiz.html", TODAY,
                           originals={"g::m10": original})
    [card] = _page_data(out)

    assert card["edited"] is True
    assert card["best"] == [2, 16]                 # R3
    assert card["orig"]["best"] == [15, 15]        # Q16
    assert card["orig"]["note"] == "harvested note"
    assert card["noteVertices"] == [[9, 9]]        # K10, read from the edited note


def test_unedited_card_is_not_marked_edited(tmp_path):
    out = render_quiz_html([_entry()], _games(), tmp_path / "quiz.html", TODAY,
                           originals={"g::m10": _entry()})
    assert _page_data(out)[0]["edited"] is False


# --- the server route --------------------------------------------------

@pytest.fixture
def server(tmp_path):
    _QuizRequestHandler.edits_path = tmp_path / card_edits.FILENAME
    _QuizRequestHandler.harvested = {"g::m10": _entry()}
    handler = functools.partial(_QuizRequestHandler, directory=str(tmp_path))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path / card_edits.FILENAME
    httpd.shutdown()
    httpd.server_close()
    _QuizRequestHandler.edits_path = None
    _QuizRequestHandler.harvested = {}


def _post(url, body):
    req = urllib.request.Request(url + "/card-edit", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_saving_and_resetting_through_the_server(server):
    url, path = server
    status, body = _post(url, {"problemId": "g::m10", "best": "R3", "alternatives": [],
                               "note": "hane at K10", "boardSize": 19})
    assert status == 200 and body["noteVertices"] == [[9, 9]]
    assert card_edits.load(path)["g::m10"]["best"] == "R3"

    status, _ = _post(url, {"problemId": "g::m10", "reset": True})
    assert status == 200 and card_edits.load(path) == {}


def test_the_server_refuses_unknown_cards_and_bad_points(server):
    url, path = server
    assert _post(url, {"problemId": "nope", "best": "R3", "alternatives": [],
                       "note": ""})[0] == 400
    assert _post(url, {"problemId": "g::m10", "best": "Z99", "alternatives": [],
                       "note": ""})[0] == 400
    assert not path.exists()
