"""Synthetic GameAnalysis builders shared by the metrics and report tests."""

from pathlib import Path

from baduk_lab.engine import GameAnalysis, PositionAnalysis
from baduk_lab.loader import GameRecord, Move

PLAYER = "hero"


def build_record(total_moves: int, focus_color: str, name: str = "game.sgf") -> GameRecord:
    moves = [
        Move(number=m, color=("b" if m % 2 == 1 else "w"), coord=(3, 3))
        for m in range(1, total_moves + 1)
    ]
    black = PLAYER if focus_color == "b" else "rival"
    white = PLAYER if focus_color == "w" else "rival"
    return GameRecord(path=Path(name), board_size=19, komi=6.5,
                       player_black=black, player_white=white, result="B+R",
                       date="2026-01-01", moves=moves)


def build_analysis(total_moves: int, focus_color: str, losses: dict[int, float],
                   winrates: dict[int, float] | None = None,
                   name: str = "game.sgf") -> GameAnalysis:
    """Build a synthetic GameAnalysis where `losses[m]` is the desired
    points_lost() for move m (all other moves default to 0), and `winrates[m]`
    is the desired winrate *from that move's own mover's perspective* (all
    other positions default to 0.5).

    PositionAnalysis.score_lead/winrate are fixed to Black's perspective
    (see engine.py), so both are converted here from the mover-relative
    values callers actually want to specify.
    """
    winrates = winrates or {}
    record = build_record(total_moves, focus_color, name)

    # Invert GameAnalysis.points_lost's formula to recover Black-perspective
    # score_lead from the desired mover-relative points_lost per move.
    score_leads = [0.0] * (total_moves + 2)  # 1-indexed positions 1..total_moves+1
    for m in range(1, total_moves + 1):
        mover = "b" if m % 2 == 1 else "w"
        loss = losses.get(m, 0.0)
        score_leads[m + 1] = score_leads[m] + (loss if mover == "w" else -loss)

    positions = [
        PositionAnalysis(
            move_number=pos,
            to_play="b" if pos % 2 == 1 else "w",
            winrate=(winrates.get(pos, 0.5) if pos % 2 == 1
                    else 1.0 - winrates.get(pos, 0.5)),
            score_lead=score_leads[pos],
            best_moves=[{"move": "Q16", "scoreLead": 0.0}],
        )
        for pos in range(1, total_moves + 2)
    ]
    return GameAnalysis(record=record, positions=positions)
