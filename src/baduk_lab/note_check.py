"""Find comments that are probably attached to the wrong move.

You comment while reviewing, from wherever the board happens to be, and
the note doesn't always land on the move it is about: it drifts a move or
two past the mistake, or stays on the last position you were looking at
long after the move it describes. `annotations` resolves every comment to
*a* move regardless, so a drifted note quietly becomes a problem whose
answer has nothing to do with what you wrote.

This module reads the same resolution the harvest reached and judges how
well each note fits the move it landed on. It changes nothing -- it tells
you which comments to go back and move.

The one signal worth more than all the others is whether the note *names*
the move the problem would be graded against. When it does, the note is
provably about that position and no other evidence can outweigh that; a
costlier mistake sitting a few moves away is then just a second mistake
you didn't comment on, not a sign the note is misplaced. Judging a note
without that check flags about half of them and is worth nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sgfmill.common import format_vertex

from . import annotations, board

logger = logging.getLogger(__name__)

# How far from a note to look for the mistake it might really be about.
# Wide enough for "a move or two late", not so wide that any note in a
# messy fight finds something.
NEARBY_RADIUS = 8

# A move this cheap didn't cost you anything worth writing a note about.
_TRIVIAL_POINTS = 0.3
# ...and this is the ceiling for "the note's own move is a real mistake",
# below which a note naming something else looks misplaced rather than
# merely unspecific.
_MILD_POINTS = 1.0
_MILD_WINRATE = 0.05
# A nearby move has to be this much worse to be the better explanation.
_NEARBY_POINTS = 2.0

RULES = {
    "misplaced": (
        "high",
        "names a point that is nothing in this position, costs almost "
        "nothing, and sits beside a much worse move of yours",
        "Most likely your note belongs to that other move. Move the "
        "comment there in LizzieYzy and re-run the harvest.",
    ),
    "drifted": (
        "medium",
        "names no point, costs almost nothing, and a much worse move of "
        "yours is a few moves away",
        "Probably the comment drifted past the move it describes. Check "
        "the nearby move and move the comment onto it.",
    ),
    "answer_disagrees": (
        "medium",
        "recommends a point the quiz won't accept as the answer",
        "The card would mark the move your own note recommends as wrong. "
        "Either the comment is on the wrong move, or play your line out "
        "in LizzieYzy so it is saved as a variation and becomes the "
        "answer.",
    ),
    "no_wrong_answer": (
        "low",
        "sits on a move KataGo already rates best, so the card's answer "
        "is the move you played",
        "Usually a note about something you got right. Fine to keep, but "
        "it drills nothing -- there is no mistake to find.",
    ),
    "names_only_occupied": (
        "low",
        "names only points that are already occupied",
        "Often a retrospective note about a stone played earlier. Nothing "
        "can retarget that automatically -- move it yourself if it was "
        "meant for that earlier move.",
    ),
}


@dataclass
class NoteIssue:
    """One comment worth a second look, and why."""
    game: str
    move_number: int
    rule: str
    note: str
    played: str = ""
    answers: list[str] | None = None      # what the card would accept
    named: list[str] | None = None        # points your note names
    points_lost: float = 0.0
    nearby_move: int | None = None        # a worse move of yours close by
    nearby_points: float = 0.0
    skipped: str | None = None            # set for a note that was dropped

    @property
    def confidence(self) -> str:
        # A dropped note is a fact, not a guess: it is simply not drilled.
        return "high" if self.skipped else RULES[self.rule][0]

    @property
    def what(self) -> str:
        if self.skipped:
            return annotations.SKIP_REASONS[self.skipped]
        return RULES[self.rule][1]

    @property
    def advice(self) -> str:
        if self.skipped == "past_end":
            return ("The move it points at was never played. Move the "
                    "comment back onto the move you meant.")
        if self.skipped == "shadowed":
            return ("Two comments landed on the same move, so this one is "
                    "not drilled. Move it onto the move it is about.")
        if self.skipped:
            return "Not drilled -- re-check which move the comment sits on."
        return RULES[self.rule][2]


def _vertex_owner(occupied: dict, vertex: str) -> str | None:
    column = annotations.COLUMN_LETTERS.find(vertex[0])
    row = int(vertex[1:]) - 1
    return occupied.get((row, column))


def _worst_own_move_near(resolution: annotations.NoteResolution,
                         move_number: int) -> tuple[int | None, float]:
    """(move, points lost) for your own costliest move within
    NEARBY_RADIUS of `move_number`, ignoring the move itself."""
    sequence = resolution.sequence
    worst_move, worst_cost = None, 0.0
    for candidate in range(move_number - NEARBY_RADIUS, move_number + NEARBY_RADIUS + 1):
        if candidate == move_number or not 1 <= candidate < len(sequence):
            continue
        color, _ = sequence[candidate].get_move()
        if color != resolution.your_color:
            continue
        before = annotations._node_eval(sequence[candidate - 1])
        after = annotations._node_eval(sequence[candidate])
        if before is None or after is None:
            continue
        cost = annotations._points_lost(before, after)
        if cost > worst_cost:
            worst_move, worst_cost = candidate, cost
    return worst_move, worst_cost


def _classify(resolved: annotations.ResolvedNote,
              resolution: annotations.NoteResolution) -> NoteIssue | None:
    """The one thing most worth saying about this note, or None if it fits
    the move it landed on."""
    mistake = resolved.mistake
    assert mistake is not None
    answers = [mistake.best, *mistake.alternatives]
    named = mistake.note_vertices

    # Provably about this move: your note names the move it would be
    # graded against. Nothing below can outrank that.
    if any(vertex in answers for vertex in named):
        return None

    nearby_move, nearby_points = _worst_own_move_near(resolution, mistake.move_number)
    issue = NoteIssue(
        game=mistake.game, move_number=mistake.move_number, rule="",
        note=mistake.note, played=mistake.played, answers=answers, named=named,
        points_lost=mistake.points_lost, nearby_move=nearby_move,
        nearby_points=nearby_points,
    )

    names_a_move = bool(named) and mistake.played not in named
    mild = mistake.points_lost < _MILD_POINTS and mistake.winrate_drop < _MILD_WINRATE
    much_worse_nearby = nearby_points >= max(
        _NEARBY_POINTS, 4 * max(mistake.points_lost, 0.25))

    if names_a_move and mild and much_worse_nearby:
        issue.rule = "misplaced"
    elif names_a_move:
        issue.rule = "answer_disagrees"
    elif not named and mistake.points_lost < _TRIVIAL_POINTS \
            and nearby_points >= 3.0 \
            and nearby_points >= 10 * max(mistake.points_lost, 0.05):
        issue.rule = "drifted"
    elif mistake.played == mistake.best:
        issue.rule = "no_wrong_answer"
    elif named and all(_vertex_owner(
            board.board_before(
                [(m.number, m.color, m.coord) for m in resolution.moves],
                resolution.record.board_size, mistake.move_number),
            vertex) is not None for vertex in named):
        issue.rule = "names_only_occupied"
    else:
        return None
    return issue


def check_file(path: Path, player: str | Sequence[str]) -> tuple[int, list[NoteIssue]]:
    """(comments examined, issues) for one reviewed SGF."""
    resolution = annotations.resolve_notes(path, player)
    if resolution is None:
        return 0, []

    issues = []
    for resolved in resolution.notes:
        if resolved.mistake is None:
            issues.append(NoteIssue(
                game=resolution.record.path.name, move_number=resolved.move_number,
                rule="", note=resolved.note, skipped=resolved.skipped))
            continue
        issue = _classify(resolved, resolution)
        if issue is not None:
            issues.append(issue)
    return len(resolution.notes), issues


def check_folder(folder: Path,
                 player: str | Sequence[str]) -> tuple[int, list[NoteIssue]]:
    """(comments examined, issues) across a folder of reviewed SGFs,
    worst first. An unreadable file is skipped with a warning rather than
    failing the whole check, matching `harvest_folder`."""
    examined, issues = 0, []
    for path in sorted(folder.rglob("*.sgf")):
        try:
            count, found = check_file(path, player)
        except Exception as exc:                      # noqa: BLE001
            logger.warning("Skipping %s: %s", path.name, exc)
            continue
        examined += count
        issues.extend(found)

    rank = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: (rank[i.confidence], -i.nearby_points,
                               i.game, i.move_number))
    return examined, issues


def format_report(examined: int, issues: list[NoteIssue]) -> str:
    """The check as text, grouped by game."""
    if not issues:
        return (f"Checked {examined} comment(s) -- none look misplaced.")

    lines = [f"Checked {examined} comment(s); {len(issues)} worth a look.", ""]
    by_game: dict[str, list[NoteIssue]] = {}
    for issue in issues:
        by_game.setdefault(issue.game, []).append(issue)

    for game, found in by_game.items():
        lines.append(game)
        for issue in sorted(found, key=lambda i: i.move_number):
            lines.append(f"  move {issue.move_number} [{issue.confidence}] {issue.what}")
            lines.append(f"    your note: {issue.note.splitlines()[0][:100]}")
            if issue.skipped is None:
                detail = (f"    played {issue.played}; "
                          f"card accepts {', '.join(issue.answers) or '-'}; "
                          f"note names {', '.join(issue.named) or '-'}; "
                          f"cost {issue.points_lost:.1f} pts")
                if issue.nearby_move is not None and issue.nearby_points >= 1.0:
                    detail += (f"; move {issue.nearby_move} nearby cost "
                               f"{issue.nearby_points:.1f}")
                lines.append(detail)
            lines.append(f"    -> {issue.advice}")
        lines.append("")
    return "\n".join(lines).rstrip()
