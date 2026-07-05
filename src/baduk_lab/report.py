"""Render metrics into report.md and export the problem-set SGFs.

Report structure:
- Header: games analyzed, player, date range, engine/model/visits used.
- Section per metric, each with one plain-language takeaway line
  ("Most of your losses happen in the middle game, and they are many small
  leaks rather than single blunders").
- Problem set: table of extracted positions linking to problems/*.sgf.
  Each problem SGF contains the position before your mistake, with your
  actual move and KataGo's preferred move stored as comments/variations
  so the answer is one click away but not spoiled.
"""

from __future__ import annotations

from pathlib import Path

from . import metrics


def render_report(out_dir: Path, **computed_metrics) -> Path:
    raise NotImplementedError


def export_problem_sgfs(problems: list[metrics.ProblemPosition],
                        out_dir: Path) -> None:
    raise NotImplementedError
