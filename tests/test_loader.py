from pathlib import Path

from baduk_lab.loader import load_folder, load_sgf

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


def test_load_folder_skips_unparseable_files(tmp_path):
    good = tmp_path / "good.sgf"
    good.write_text((FIXTURES / "sample.sgf").read_text())
    bad = tmp_path / "bad.sgf"
    bad.write_text("not an sgf file")

    records = load_folder(tmp_path)

    assert len(records) == 1
    assert records[0].path == good
