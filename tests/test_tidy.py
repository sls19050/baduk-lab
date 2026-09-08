from pathlib import Path

from baduk_lab.loader import load_sgf
from baduk_lab.tidy import (
    QUARANTINE_DIRNAME,
    choose_keeper,
    game_fingerprint,
    suggest_filename,
    tidy_folder,
)

SGF_TEMPLATE = "(;GM[1]FF[4]CA[UTF-8]SZ[19]KM[6.5]PB[{black}]PW[{white}]RE[{result}]DT[{date}]{moves})"


def _write_sgf(path: Path, black="ikirushia", white="HKA", result="B+Resign",
               date="2026-09-07", moves=";B[pd];W[dd];B[pp]") -> Path:
    path.write_text(SGF_TEMPLATE.format(black=black, white=white, result=result,
                                        date=date, moves=moves), encoding="utf-8")
    return path


def test_suggest_filename_uses_metadata():
    from baduk_lab.loader import GameRecord
    record = GameRecord(path=Path("junk_name_123.sgf"), board_size=19, komi=6.5,
                        player_black="ikirushia", player_white="HKA",
                        result="B+Resign", date="2026-09-07")

    assert suggest_filename(record) == "2026-09-07_ikirushia-vs-HKA_B+Resign.sgf"


def test_suggest_filename_falls_back_for_missing_fields():
    from baduk_lab.loader import GameRecord
    record = GameRecord(path=Path("x.sgf"), board_size=19, komi=6.5,
                        player_black="", player_white="", result="", date="")

    assert suggest_filename(record) == "unknown-date_unknown-vs-unknown_no-result.sgf"


def test_fingerprint_ignores_filename_and_matches_same_game(tmp_path):
    a = _write_sgf(tmp_path / "ikirushia.sgf")
    b = _write_sgf(tmp_path / "ikirushia_Analyzed_20260907.sgf")

    assert game_fingerprint(load_sgf(a)) == game_fingerprint(load_sgf(b))


def test_fingerprint_differs_for_different_games(tmp_path):
    a = _write_sgf(tmp_path / "a.sgf", moves=";B[pd];W[dd]")
    b = _write_sgf(tmp_path / "b.sgf", moves=";B[pd];W[dp]")

    assert game_fingerprint(load_sgf(a)) != game_fingerprint(load_sgf(b))


def test_choose_keeper_prefers_non_engine_export_even_if_larger(tmp_path):
    plain = _write_sgf(tmp_path / "ikirushia.sgf")
    analyzed = tmp_path / "ikirushia_Analyzed_20260907181601.sgf"
    analyzed.write_text(plain.read_text(encoding="utf-8") + " " * 500, encoding="utf-8")

    keeper = choose_keeper([load_sgf(plain), load_sgf(analyzed)])

    assert keeper.path == plain


def test_tidy_folder_renames_unique_games(tmp_path):
    messy = _write_sgf(tmp_path / "ikirushia.sgf")

    result = tidy_folder(tmp_path)

    assert result.renamed == [(messy, tmp_path / "2026-09-07_ikirushia-vs-HKA_B+Resign.sgf")]
    assert not messy.exists()
    assert (tmp_path / "2026-09-07_ikirushia-vs-HKA_B+Resign.sgf").exists()
    assert result.quarantined == []


def test_tidy_folder_quarantines_duplicate_keeping_plain_copy(tmp_path):
    plain = _write_sgf(tmp_path / "ikirushia.sgf")
    analyzed = _write_sgf(tmp_path / "ikirushia_Analyzed_20260907181601.sgf")

    result = tidy_folder(tmp_path)

    kept = tmp_path / "2026-09-07_ikirushia-vs-HKA_B+Resign.sgf"
    assert kept.exists()
    assert not plain.exists()
    assert not analyzed.exists()
    assert (tmp_path / QUARANTINE_DIRNAME / analyzed.name).exists()
    assert result.quarantined == [(analyzed, tmp_path / QUARANTINE_DIRNAME / analyzed.name)]


def test_tidy_folder_dry_run_touches_nothing(tmp_path):
    plain = _write_sgf(tmp_path / "ikirushia.sgf")
    analyzed = _write_sgf(tmp_path / "ikirushia_Analyzed_20260907181601.sgf")

    result = tidy_folder(tmp_path, dry_run=True)

    assert plain.exists()
    assert analyzed.exists()
    assert not (tmp_path / QUARANTINE_DIRNAME).exists()
    assert len(result.renamed) == 1
    assert len(result.quarantined) == 1


def test_tidy_folder_is_idempotent_across_runs(tmp_path):
    _write_sgf(tmp_path / "ikirushia.sgf")
    _write_sgf(tmp_path / "ikirushia_Analyzed_20260907181601.sgf")

    tidy_folder(tmp_path)
    second = tidy_folder(tmp_path)

    assert second.renamed == []
    assert second.quarantined == []
    assert second.skipped == []


def test_tidy_folder_skips_unparseable_files(tmp_path):
    bad = tmp_path / "corrupt.sgf"
    bad.write_text("not an sgf file", encoding="utf-8")

    result = tidy_folder(tmp_path)

    assert bad.exists()
    assert len(result.skipped) == 1
    assert result.skipped[0][0] == bad


def test_tidy_folder_avoids_overwriting_distinct_games_with_same_suggested_name(tmp_path):
    _write_sgf(tmp_path / "game1.sgf", moves=";B[pd];W[dd]")
    _write_sgf(tmp_path / "game2.sgf", moves=";B[pd];W[dp]")

    result = tidy_folder(tmp_path)

    names = {new.name for _, new in result.renamed}
    assert names == {
        "2026-09-07_ikirushia-vs-HKA_B+Resign.sgf",
        "2026-09-07_ikirushia-vs-HKA_B+Resign (2).sgf",
    }
