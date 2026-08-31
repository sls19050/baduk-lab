from baduk_lab.cli import _resolve_problem_sgf_path


def test_resolves_a_real_file_inside_problems_dir(tmp_path):
    (tmp_path / "middle").mkdir()
    sgf = tmp_path / "middle" / "game_m10.sgf"
    sgf.write_text("(;GM[1])")

    resolved = _resolve_problem_sgf_path(tmp_path, "middle/game_m10.sgf")

    assert resolved == sgf.resolve()


def test_rejects_path_traversal_outside_problems_dir(tmp_path):
    outside = tmp_path.parent / "secret.sgf"
    outside.write_text("(;GM[1])")

    resolved = _resolve_problem_sgf_path(tmp_path, "../secret.sgf")

    assert resolved is None


def test_rejects_nonexistent_file(tmp_path):
    resolved = _resolve_problem_sgf_path(tmp_path, "middle/does_not_exist.sgf")

    assert resolved is None


def test_rejects_empty_or_missing_path(tmp_path):
    assert _resolve_problem_sgf_path(tmp_path, None) is None
    assert _resolve_problem_sgf_path(tmp_path, "") is None
