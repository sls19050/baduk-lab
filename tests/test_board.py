from baduk_lab.board import board_before

# Surround a lone white stone at (2,2) on a 5x5 board with black on all
# four sides; the last surrounding move should capture it.
_SURROUND = [
    (1, "w", (2, 2)),
    (2, "b", (1, 2)),
    (3, "b", (3, 2)),
    (4, "b", (2, 1)),
    (5, "b", (2, 3)),  # captures (2,2)
]


def test_stone_with_a_liberty_survives():
    board = board_before(_SURROUND, board_size=5, move_number=5)

    assert board[(2, 2)] == "w"
    assert board[(1, 2)] == "b"
    assert board[(3, 2)] == "b"
    assert board[(2, 1)] == "b"


def test_stone_is_captured_once_last_liberty_filled():
    board = board_before(_SURROUND, board_size=5, move_number=6)

    assert (2, 2) not in board
    assert board[(2, 3)] == "b"


def test_move_number_cutoff_excludes_moves_at_or_after_it():
    board = board_before(_SURROUND, board_size=5, move_number=1)

    assert board == {}


def test_pass_moves_are_skipped_without_error():
    moves = [(1, "b", (0, 0)), (2, "w", None), (3, "b", (1, 1))]

    board = board_before(moves, board_size=5, move_number=4)

    assert board == {(0, 0): "b", (1, 1): "b"}


def test_capturing_a_multi_stone_group():
    # black group at (0,0)-(0,1), white surrounds both from the only
    # remaining liberties.
    moves = [
        (1, "b", (0, 0)),
        (2, "b", (0, 1)),
        (3, "w", (1, 0)),
        (4, "w", (1, 1)),
        (5, "w", (0, 2)),
    ]

    board = board_before(moves, board_size=5, move_number=6)

    assert (0, 0) not in board
    assert (0, 1) not in board
    assert board[(1, 0)] == "w"
    assert board[(1, 1)] == "w"
    assert board[(0, 2)] == "w"
