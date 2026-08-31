from pathlib import Path

from sgfmill.common import format_vertex

from baduk_lab.loader import load_folder, load_gib, load_sgf

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_sgf_parses_header_and_moves():
    record = load_sgf(FIXTURES / "sample.sgf")

    assert record.board_size == 19
    assert record.komi == 6.5
    assert record.player_black == "black_player"
    assert record.player_white == "white_player"
    assert record.result == "B+Resign"
    assert len(record.moves) == 5


def test_moves_are_numbered_and_alternate_color():
    record = load_sgf(FIXTURES / "sample.sgf")

    assert [m.number for m in record.moves] == [1, 2, 3, 4, 5]
    assert [m.color for m in record.moves] == ["b", "w", "b", "w", "b"]


def test_pass_move_has_no_coord():
    record = load_sgf(FIXTURES / "sample.sgf")

    assert record.moves[-1].coord is None


def test_clock_and_byo_yomi_tags_are_parsed():
    record = load_sgf(FIXTURES / "sample.sgf")

    first_move = record.moves[0]
    assert first_move.clock_after == 300
    assert first_move.byo_yomi_periods is None

    last_move = record.moves[-1]
    assert last_move.clock_after == 280
    assert last_move.byo_yomi_periods == 2


def test_color_of_matches_black_and_white_by_name():
    record = load_sgf(FIXTURES / "sample.sgf")

    assert record.color_of("black_player") == "b"
    assert record.color_of("white_player") == "w"
    assert record.color_of("nobody") is None


def test_color_of_matches_any_alias():
    record = load_sgf(FIXTURES / "sample.sgf")

    assert record.color_of(["nobody", "black_player"]) == "b"
    assert record.color_of(["nobody", "still nobody"]) is None


def test_load_folder_skips_unparseable_files(tmp_path):
    good = tmp_path / "good.sgf"
    good.write_text((FIXTURES / "sample.sgf").read_text())
    bad = tmp_path / "bad.sgf"
    bad.write_text("not an sgf file")

    records = load_folder(tmp_path)

    assert len(records) == 1
    assert records[0].path == good


def test_load_folder_recurses_and_loads_sgf_and_gib(tmp_path):
    (tmp_path / "2026-08").mkdir()
    sgf_copy = tmp_path / "2026-08" / "game.sgf"
    sgf_copy.write_text((FIXTURES / "sample.sgf").read_text())
    gib_copy = tmp_path / "2026-08" / "game.gib"
    gib_copy.write_bytes((FIXTURES / "sample.gib").read_bytes())

    records = load_folder(tmp_path)

    assert {r.path for r in records} == {sgf_copy, gib_copy}


def test_load_gib_parses_header():
    record = load_gib(FIXTURES / "sample.gib")

    assert record.board_size == 19
    assert record.komi == 6.5
    assert record.player_black == "black_player"
    assert record.player_white == "white_player"
    assert record.result == "B+R"
    assert record.date == "2026-08-16"
    assert len(record.moves) == 5


def test_gib_moves_are_numbered_and_alternate_color():
    record = load_gib(FIXTURES / "sample.gib")

    assert [m.number for m in record.moves] == [1, 2, 3, 4, 5]
    assert [m.color for m in record.moves] == ["b", "w", "b", "w", "b"]


def test_gib_coordinates_match_sgfmill_convention():
    # Fixture's first STO line is "STO 0 2 1 16 3" -> color=1(black), x=16, y=3.
    # Tygem's x/y are raw SGF-style (x=col left-to-right, y=row top-to-bottom,
    # no inversion -- verified against GibParser.cpp), so on a 19x19 board
    # this is sgfmill vertex (row=18-3=15, col=16) -> "R16".
    record = load_gib(FIXTURES / "sample.gib")

    assert record.moves[0].coord == (15, 16)
    assert format_vertex(record.moves[0].coord) == "R16"


def test_gib_color_of_matches_nick_not_display_name():
    record = load_gib(FIXTURES / "sample.gib")

    # GAMEBLACKNAME is "black_player (8D)" -- color_of should match the
    # clean GAMEBLACKNICK, not require the rank suffix.
    assert record.color_of("black_player") == "b"
    assert record.color_of("white_player") == "w"
