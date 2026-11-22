"""Harvest your own hand-written SGF comments into quiz problems.

`analyze` finds mistakes the way KataGo defines them: any move losing more
than `metrics.PROBLEM_THRESHOLD` points. That misses a whole class of your
own errors -- in a close game, a strategic misjudgment can swing the
winrate 12% while costing well under a point, so the threshold never sees
it. But when you review a game in LizzieYzy Next and type "1 space jump at
N8 is very heavy and does not create any potential", you have already
diagnosed it yourself, in your own words. That is the best drill material
in the repo and it was being thrown away.

This module reads LizzieYzy Next's own analyzed-game SGFs (the files it
writes to `user-data/AnalyzedGames/`) and turns every node you commented
on into a problem, using the KataGo analysis LizzieYzy already baked into
the same file -- so harvesting notes never starts the engine.

Three things have to be read out of those files:

1. **Your text, separated from LizzieYzy's.** LizzieYzy writes its own
   winrate/lead block into `C[]` and appends whatever you type after it.
   `user_note` strips the generated lines and keeps the rest.

2. **Which move the note is about.** You comment from wherever the board
   happened to be sitting, which is sometimes the mistake itself ("1 space
   jump at N8 is very heavy" -- written on the node that played N8) and
   sometimes the position just before it ("black must ... atari at R7",
   written on White's move, about Black's reply). Both resolve the same
   way: the mistake is the nearest move of *your* color at this node or the
   next one. Across every annotated game tested, that rule picked the move
   the note is actually discussing.

3. **The answer, and how bad the move was.** Two sources, in this order:

   - **The variation you played out.** Branching off in LizzieYzy to try
     something records your line as a sibling of the real game. When a note
     names one of those moves ("white must cut at the 2nd line M18 first"
     beside a branch playing M18), that is you stating the answer, and
     nothing beats it.
   - **KataGo, otherwise.** LizzieYzy stores a full search in `LZ[]` on
     each node (`LZOP[]` on the root), evaluating the position *after* that
     node's move -- i.e. the position the next move is chosen from. So the
     analysis of the position facing mistake move M lives on node M-1, and
     its highest-visit candidate stands in. Comparing it with node M's
     search also gives the points and winrate the move actually cost.

   Whichever loses out still counts as a right answer, since a position
   usually has more than one good move.

Perspective conventions in `LZ[]`, confirmed against the human-readable
`C[]` block LizzieYzy writes beside it:

- The header's winrate belongs to the player who *just moved* (so the
  player to move next is at `100 - winrate`).
- The header's scoreMean is from the perspective of the player *to move*.
- Each candidate's own winrate/scoreMean are relative to the player to
  move, as in KataGo's own analysis output.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sgfmill import sgf
from sgfmill.common import format_vertex

from .loader import GameRecord, Move

logger = logging.getLogger(__name__)

# Lines LizzieYzy generates into C[] itself. Anything else in a comment is
# yours. Matching the generated lines (rather than keeping "everything after
# the komi: line") means a LizzieYzy version that reorders or drops one of
# them still leaves your text intact instead of swallowing it.
_GENERATED_LINE_RES = [
    re.compile(r"^(Black|White) win rate:"),
    re.compile(r"^lead:\s"),
    re.compile(r"^\(komi\S*\s*/.*visits\)$"),
    re.compile(r"^komi:\s"),
    re.compile(r"^Engine Rules:"),
    re.compile(r"^(Black|White) AI accuracy:"),
    re.compile(r"^(Black|White) mismatch\("),
]

# One candidate inside an LZ[]/LZOP[] payload. Entries are separated by
# " info ", each starting "move <vertex> visits <n> ...". Every field after
# the move itself is optional so a shorter LizzieYzy payload still parses.
_CANDIDATE_RE = re.compile(
    r"move\s+(?P<move>[A-T]\d{1,2}|pass)"
    r"(?:\s+visits\s+(?P<visits>\d+))?"
    r"(?:\s+winrate\s+(?P<winrate>-?\d+))?"
    r"(?:\s+prior\s+(?P<prior>-?\d+))?"
    r"(?:\s+scoreMean\s+(?P<score>-?[\d.]+))?"
)


# LizzieYzy records the human side of a game against its own built-in AI
# as PB[You]/PW[You], with no handle to match. Inside an annotated-games
# folder that is unambiguously you, so it's always matched alongside your
# configured aliases -- otherwise every such game is silently skipped.
SELF_ALIAS = "You"

# Go board columns skip I, so a column's letter is not its index's letter.
COLUMN_LETTERS = "ABCDEFGHJKLMNOPQRST"

# A board point named in prose: a column letter followed by a row number,
# as you'd write it ("hane at L13", "the 2nd line M18"). Case-insensitive
# because notes are typed quickly; bounded by word breaks so "Top 10" and
# "3rd line" don't register.
_VERTEX_RE = re.compile(r"\b([A-Ta-t])(\d{1,2})\b")


@dataclass
class PositionEval:
    """One node's baked-in KataGo search: the evaluation of the position
    *after* that node's move, i.e. what the next player is choosing from."""
    winrate_to_play: float | None   # 0-1, for the player about to move
    score_to_play: float | None     # points, for the player about to move
    best_move: str | None           # highest-visit candidate, e.g. "R7"


@dataclass
class AnnotatedMistake:
    """One comment you wrote, resolved to the move it is about."""
    game: str              # source SGF filename
    move_number: int       # the move your note is about (1-indexed)
    color: str             # "b" or "w" -- your color in this game
    note: str              # your own comment text, generated lines stripped
    played: str            # the move you actually made, e.g. "S4"
    best: str              # the answer to quiz against -- see _choose_best
    points_lost: float     # score cost of `played` vs the position before it
    winrate_drop: float    # winrate cost, 0-1 (what `points_lost` can miss)
    # Other moves that also count as right: the rest of the variations you
    # played out, plus KataGo's own pick when it isn't already `best`.
    alternatives: list[str] = field(default_factory=list)
    # Every point your note names, so the quiz can mark them on the board.
    # A note sometimes discusses a point that is nobody's candidate here
    # ("the moyo at F7"), which is unreadable without seeing where it is.
    note_vertices: list[str] = field(default_factory=list)

    @property
    def problem_id(self) -> str:
        """Stable across re-harvests, and namespaced so it can never
        collide with an `analyze` problem id for the same game/move --
        the two decks are graded the same way but come from different
        sources and should keep separate review histories."""
        return f"note::{Path(self.game).stem}::m{self.move_number}"


def user_note(comment: str) -> str:
    """Your own text from one C[] value, with LizzieYzy's generated
    winrate/lead/accuracy lines removed. Empty if you wrote nothing."""
    kept = [line for line in comment.splitlines()
            if not any(r.match(line.strip()) for r in _GENERATED_LINE_RES)]
    return "\n".join(kept).strip()


def _self_alias_color(record: GameRecord) -> str | None:
    """Your color in a game LizzieYzy tagged `You`. Matched exactly rather
    than as a substring (which is how real handles are matched), so a real
    opponent handle that merely contains "you" can't be mistaken for it."""
    if record.player_black.strip().lower() == SELF_ALIAS.lower():
        return "b"
    if record.player_white.strip().lower() == SELF_ALIAS.lower():
        return "w"
    return None


def vertices_in(text: str, board_size: int) -> list[str]:
    """Every board point named in a note, in the order written, deduped.
    Anything off the board (a stray "the 2 stones at M99") is dropped."""
    out = []
    for letter, number in _VERTEX_RE.findall(text):
        column = COLUMN_LETTERS.find(letter.upper())
        row = int(number)
        if column < 0 or column >= board_size or not 1 <= row <= board_size:
            continue
        vertex = f"{COLUMN_LETTERS[column]}{row}"
        if vertex not in out:
            out.append(vertex)
    return out


def _explored_moves(parent) -> list[str]:
    """The moves you played out yourself from this position.

    When you branch off in LizzieYzy to try something, it records your line
    as a sibling of the real game, with the game itself kept as the first
    child. So every child but the first is a move you reached for while
    reviewing -- which is a far better answer to a note than KataGo's top
    move, because it is the move you concluded you should have played."""
    out = []
    for child in list(parent)[1:]:
        _, coord = child.get_move()
        if coord is not None:
            out.append(format_vertex(coord))
    return out


def _choose_best(explored: list[str], note_vertices: list[str],
                 engine_best: str) -> tuple[str, list[str]]:
    """(the answer to quiz against, the others that also count as right).

    A variation you played out *and* named in your note is as close to a
    stated answer as these files get, so it wins. Failing that the engine's
    pick stays the answer -- an explored line is not always a recommendation
    (sometimes you were just checking what happens), so it only earns the
    top spot when the note backs it up."""
    named = [v for v in note_vertices if v in explored]
    best = named[0] if named else engine_best
    alternatives = [v for v in [*explored, engine_best] if v != best]
    return best, list(dict.fromkeys(alternatives))


def _parse_eval(payload: str) -> PositionEval:
    """Read one LZ[]/LZOP[] value. Any field that isn't there comes back
    None rather than raising -- a half-written search is still worth the
    parts of it that parsed."""
    header, _, candidates = payload.partition("\n")
    fields = header.split()

    winrate_just_moved = _as_float(fields[1]) if len(fields) > 1 else None
    winrate_to_play = None if winrate_just_moved is None else 1.0 - winrate_just_moved / 100.0

    best_move, best_visits = None, -1
    for match in _CANDIDATE_RE.finditer(candidates):
        visits = int(match.group("visits") or 0)
        if visits > best_visits:
            best_move, best_visits = match.group("move"), visits

    return PositionEval(
        winrate_to_play=winrate_to_play,
        score_to_play=_as_float(fields[3]) if len(fields) > 3 else None,
        best_move=best_move,
    )


def _as_float(raw: str) -> float | None:
    try:
        return float(raw)
    except ValueError:
        return None


def _node_eval(node) -> PositionEval | None:
    for prop in ("LZ", "LZOP"):
        if node.has_property(prop):
            return _parse_eval(node.get_raw(prop).decode("utf-8", errors="replace"))
    return None


def _mistake_move_number(node_index: int, node_color: str | None, your_color: str) -> int:
    """Which move the note on node `node_index` is about. `node_index` is
    also that node's move number (node 0 is the root), so a note on your
    own move is about that move, and a note on your opponent's move is
    about your reply to it."""
    return node_index if node_color == your_color else node_index + 1


def mistakes_from_sgf(path: Path, player: str | Sequence[str]) -> list[AnnotatedMistake]:
    """Every commented node in one LizzieYzy-analyzed SGF, resolved to the
    move it is about. Returns [] if you didn't play in this game, or if
    nothing in it is commented."""
    game = sgf.Sgf_game.from_bytes(path.read_bytes())
    root = game.get_root()
    sequence = game.get_main_sequence()
    board_size = game.get_size()

    record = GameRecord(
        path=path, board_size=board_size, komi=game.get_komi(),
        player_black=root.get("PB") if root.has_property("PB") else "",
        player_white=root.get("PW") if root.has_property("PW") else "",
        result=root.get("RE") if root.has_property("RE") else "",
        date=root.get("DT") if root.has_property("DT") else "",
    )
    your_color = record.color_of(player) or _self_alias_color(record)
    if your_color is None:
        # Expected, not an error: an annotated-games folder usually also
        # holds games you only watched or studied.
        logger.debug("Skipping %s: none of %r found as a player", path.name, player)
        return []

    out = []
    # The root carries LizzieYzy's whole-game accuracy summary, never a
    # note of yours about a move, so commented nodes start at index 1.
    for index, node in enumerate(sequence):
        if index == 0 or not node.has_property("C"):
            continue
        note = user_note(node.get("C"))
        if not note:
            continue

        move_number = _mistake_move_number(index, node.get_move()[0], your_color)
        mistake = _build_mistake(record, sequence, move_number, your_color, note)
        if mistake is not None:
            out.append(mistake)

    # A note on your move N and another on your opponent's move N-1 both
    # resolve to N; keep the first and drop the duplicate rather than
    # quizzing the same position twice in one session.
    seen, deduped = set(), []
    for mistake in out:
        if mistake.move_number in seen:
            continue
        seen.add(mistake.move_number)
        deduped.append(mistake)
    return deduped


def _build_mistake(record: GameRecord, sequence, move_number: int, your_color: str,
                   note: str) -> AnnotatedMistake | None:
    """Resolve one note into a drillable problem, or None if the file
    doesn't carry enough to quiz it (the note is about a move that was
    never played, or LizzieYzy left no search on the position)."""
    if move_number >= len(sequence):
        logger.warning("%s: note about move %d, but the game ends at %d -- skipping",
                       record.path.name, move_number, len(sequence) - 1)
        return None

    color, coord = sequence[move_number].get_move()
    if color != your_color or coord is None:
        logger.warning("%s: note resolved to move %d, which isn't a move of yours "
                       "-- skipping", record.path.name, move_number)
        return None

    before = _node_eval(sequence[move_number - 1])
    after = _node_eval(sequence[move_number])
    if before is None or before.best_move is None:
        logger.warning("%s: no KataGo analysis stored before move %d -- skipping",
                       record.path.name, move_number)
        return None

    note_vertices = vertices_in(note, record.board_size)
    best, alternatives = _choose_best(
        _explored_moves(sequence[move_number - 1]), note_vertices, before.best_move)

    return AnnotatedMistake(
        game=record.path.name,
        move_number=move_number,
        color=your_color,
        note=note,
        played=format_vertex(coord),
        best=best,
        points_lost=_points_lost(before, after),
        winrate_drop=_winrate_drop(before, after),
        alternatives=alternatives,
        note_vertices=note_vertices,
    )


def _points_lost(before: PositionEval, after: PositionEval) -> float:
    """What the move cost its own player, in points. `before.score_to_play`
    is already from the mover's perspective; `after.score_to_play` belongs
    to the opponent, so it flips."""
    if before.score_to_play is None or after is None or after.score_to_play is None:
        return 0.0
    return max(0.0, before.score_to_play + after.score_to_play)


def _winrate_drop(before: PositionEval, after: PositionEval) -> float:
    """The same cost in winrate (0-1), which is what `points_lost` misses
    in a close game. `before.winrate_to_play` is already the mover's own
    winrate; after the move it is the opponent who is to play, so
    `after.winrate_to_play` has to be flipped back to the mover."""
    if before.winrate_to_play is None or after is None or after.winrate_to_play is None:
        return 0.0
    return max(0.0, before.winrate_to_play - (1.0 - after.winrate_to_play))


def moves_of(path: Path) -> tuple[int, list[Move]]:
    """(board_size, main-line moves) for one analyzed SGF, in the shape
    report.export_game_records/board.board_before want, so the quiz can
    redraw the position without re-reading this file."""
    game = sgf.Sgf_game.from_bytes(path.read_bytes())
    moves = []
    for number, node in enumerate(game.get_main_sequence()[1:], start=1):
        color, coord = node.get_move()
        if color is None:
            continue
        moves.append(Move(number=number, color=color, coord=coord))
    return game.get_size(), moves


def harvest_folder(folder: Path, player: str | Sequence[str]) -> list[AnnotatedMistake]:
    """Every annotated mistake across every SGF in a folder, worst winrate
    drop first. Unparseable files are skipped with a warning rather than
    failing the whole harvest."""
    mistakes: list[AnnotatedMistake] = []
    scanned = 0
    for path in sorted(folder.rglob("*.sgf")):
        scanned += 1
        try:
            mistakes.extend(mistakes_from_sgf(path, player))
        except Exception as exc:
            logger.warning("Skipping %s: %s", path.name, exc)
    logger.info("Scanned %d SGF(s) in %s", scanned, folder)
    mistakes.sort(key=lambda m: m.winrate_drop, reverse=True)
    return mistakes
