"""Minimal Go board simulation: replay a move list into board state.

Nothing else in this codebase computes actual board position with captures
applied -- report.py's SGF export just records the move sequence as SGF
properties and lets a real SGF viewer (KaTrain, Sabaki) apply the rules on
load. The HTML quiz (quiz_html.py) renders its own board client-side from
data baked into the page at generation time, so that data has to already
be capture-correct.

Takes plain (number, color, coord) tuples rather than loader.Move objects,
so this module has no dependency on loader.py -- callers adapt either a
GameRecord.moves list (at `analyze` time) or a JSON-loaded move list (at
`review` time, from problems/games.json) into the same shape.
"""

from __future__ import annotations

from collections.abc import Iterable

Coord = tuple[int, int]
MoveTuple = tuple[int, str, "Coord | None"]


def _neighbors(pos: Coord, size: int) -> Iterable[Coord]:
    r, c = pos
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < size and 0 <= nc < size:
            yield (nr, nc)


def _group_and_liberties(board: dict[Coord, str], start: Coord, color: str,
                         size: int) -> tuple[set[Coord], set[Coord]]:
    seen: set[Coord] = set()
    stack = [start]
    liberties: set[Coord] = set()
    while stack:
        pos = stack.pop()
        if pos in seen:
            continue
        seen.add(pos)
        for n in _neighbors(pos, size):
            occupant = board.get(n)
            if occupant is None:
                liberties.add(n)
            elif occupant == color and n not in seen:
                stack.append(n)
    return seen, liberties


def board_before(moves: Iterable[MoveTuple], board_size: int,
                 move_number: int) -> dict[Coord, str]:
    """Board state right before `move_number` is played (i.e. after
    replaying every move numbered < move_number, captures applied).

    Suicide/self-capture isn't handled -- moves replayed here always come
    from real completed games, where the server already enforced legality.
    """
    board: dict[Coord, str] = {}
    for number, color, coord in moves:
        if number >= move_number:
            break
        if coord is None:  # pass
            continue
        board[coord] = color
        opponent = "w" if color == "b" else "b"
        for n in _neighbors(coord, board_size):
            if board.get(n) == opponent:
                group, liberties = _group_and_liberties(board, n, opponent, board_size)
                if not liberties:
                    for pos in group:
                        del board[pos]
    return board
