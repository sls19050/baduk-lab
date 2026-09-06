"""Render a self-contained HTML chart of strength.py's rank_value over time:
`baduk-lab analyze` writes this alongside report.md.

Same philosophy as quiz_html.py: one static file, no external libraries or
CDN, hand-rolled inline SVG -- works offline, opens straight from disk (no
local server needed, unlike quiz.html, since there's nothing to write back).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import strength
from .strength import SideEstimate

WIDTH = 960
HEIGHT = 480
PAD_LEFT = 56
PAD_RIGHT = 90
PAD_TOP = 24
PAD_BOTTOM = 40


def render_strength_chart(rows: list[tuple[str, str, str, SideEstimate]], out_path: Path) -> Path:
    """`rows` is exactly report.strength_timeline()'s output: chronological
    (date, game, you_label, your SideEstimate) tuples, already filtered to
    those with a parseable date, a numeric rank_value, and high confidence."""
    points = []
    for iso_date, game, you_label, estimate in rows:
        points.append({
            "date": iso_date,
            "ordinal": date.fromisoformat(iso_date).toordinal(),
            "game": game,
            "youLabel": you_label,
            "band": estimate.strength_band,
            "rankValue": estimate.rank_value,
        })

    rank_values = [p["rankValue"] for p in points]
    rolling = strength.rolling_average(rank_values, strength.ROLLING_WINDOW)
    for point, avg in zip(points, rolling):
        point["rollingAvg"] = avg

    svg = _render_svg(points) if points else ""
    payload = json.dumps(points).replace("</", "<\\/")
    html = (_TEMPLATE
           .replace("__SVG__", svg)
           .replace("__DATA__", payload)
           .replace("__COUNT__", str(len(points)))
           .replace("__WINDOW__", str(strength.ROLLING_WINDOW))
           .replace("__HIDE_IF_EMPTY__", "" if points else "hidden")
           .replace("__HIDE_IF_DATA__", "hidden" if points else ""))
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _nice_y_domain(points: list[dict]) -> tuple[float, float]:
    values = [p["rankValue"] for p in points] + [p["rollingAvg"] for p in points]
    lo, hi = min(values) - 1.0, max(values) + 1.0
    lo = max(lo, strength.MIN_RANK_VALUE)
    hi = min(hi, strength.MAX_RANK_VALUE)
    if hi - lo < 1.0:  # degenerate (all-identical or single-point) data
        lo, hi = lo - 1.0, hi + 1.0
    return lo, hi


def _render_svg(points: list[dict]) -> str:
    plot_w = WIDTH - PAD_LEFT - PAD_RIGHT
    plot_h = HEIGHT - PAD_TOP - PAD_BOTTOM
    ordinals = [p["ordinal"] for p in points]
    min_ord, max_ord = min(ordinals), max(ordinals)
    ord_span = max(max_ord - min_ord, 1)
    y_lo, y_hi = _nice_y_domain(points)

    def x_of(ordinal: int) -> float:
        return PAD_LEFT + (ordinal - min_ord) / ord_span * plot_w

    def y_of(value: float) -> float:
        return PAD_TOP + (y_hi - value) / (y_hi - y_lo) * plot_h

    parts = []

    # Band reference lines -- only the ones that actually fall in view, so a
    # sub-dan player's chart isn't cluttered with "top pro"/"AI" gridlines.
    for threshold, label in strength.band_boundaries():
        if not (y_lo <= threshold <= y_hi):
            continue
        y = y_of(threshold)
        parts.append(
            f'<line x1="{PAD_LEFT}" y1="{y:.1f}" x2="{WIDTH - PAD_RIGHT}" y2="{y:.1f}" '
            f'class="band-line"/>'
        )
        parts.append(f'<text x="{WIDTH - PAD_RIGHT + 6}" y="{y + 4:.1f}" class="band-label">{label}</text>')

    # X-axis date ticks: up to 8, evenly spaced by index.
    tick_count = min(8, len(points))
    if tick_count > 1:
        step = (len(points) - 1) / (tick_count - 1)
        tick_indices = sorted({round(i * step) for i in range(tick_count)})
    else:
        tick_indices = [0]
    for i in tick_indices:
        x = x_of(points[i]["ordinal"])
        parts.append(f'<line x1="{x:.1f}" y1="{PAD_TOP}" x2="{x:.1f}" y2="{HEIGHT - PAD_BOTTOM}" class="tick-line"/>')
        parts.append(f'<text x="{x:.1f}" y="{HEIGHT - PAD_BOTTOM + 18}" class="tick-label">{points[i]["date"]}</text>')

    # Rolling-average line.
    line_points = " ".join(f"{x_of(p['ordinal']):.1f},{y_of(p['rollingAvg']):.1f}" for p in points)
    parts.append(f'<polyline points="{line_points}" class="avg-line"/>')

    # Per-game scatter points (hover targets; JS below fills in a tooltip).
    for i, p in enumerate(points):
        x, y = x_of(p["ordinal"]), y_of(p["rankValue"])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="point" data-idx="{i}"/>')

    axis = (
        f'<line x1="{PAD_LEFT}" y1="{HEIGHT - PAD_BOTTOM}" x2="{WIDTH - PAD_RIGHT}" '
        f'y2="{HEIGHT - PAD_BOTTOM}" class="axis"/>'
        f'<line x1="{PAD_LEFT}" y1="{PAD_TOP}" x2="{PAD_LEFT}" y2="{HEIGHT - PAD_BOTTOM}" class="axis"/>'
    )
    return axis + "".join(parts)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>baduk-lab strength over time</title>
<style>
  :root { color-scheme: light; }
  body {
    margin: 0; padding: 24px 16px 40px; background: #f3efe8; color: #1f1b16;
    font: 15px/1.5 -apple-system, "Segoe UI", sans-serif;
    display: flex; flex-direction: column; align-items: center;
  }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: #6b6156; font-size: 13px; margin-bottom: 16px; max-width: 960px; text-align: center; }
  #chart-wrap { position: relative; background: #fff; border: 1px solid #e3dbcb;
               border-radius: 8px; padding: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
  svg { display: block; }
  .axis { stroke: #3a2c14; stroke-width: 1; }
  .band-line { stroke: #d8cdb8; stroke-width: 1; stroke-dasharray: 3 3; }
  .band-label { font-size: 11px; fill: #8a7d68; dominant-baseline: middle; }
  .tick-line { stroke: #efe9dd; stroke-width: 1; }
  .tick-label { font-size: 11px; fill: #6b6156; text-anchor: middle; }
  .avg-line { fill: none; stroke: #2f6b3a; stroke-width: 2.5; }
  .point { fill: #b8895a; fill-opacity: 0.6; stroke: #7a5230; stroke-width: 0.5; cursor: pointer; }
  .point:hover, .point.active { fill: #a53f3f; fill-opacity: 1; r: 6; }
  #tooltip {
    position: absolute; pointer-events: none; background: #1f1b16; color: #f3efe8;
    padding: 8px 10px; border-radius: 6px; font-size: 12px; line-height: 1.4;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3); max-width: 260px; visibility: hidden;
  }
  .legend { font-size: 12px; color: #6b6156; margin-top: 10px; display: flex; gap: 18px; }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .swatch { width: 14px; height: 3px; display: inline-block; }
  .swatch-avg { background: #2f6b3a; }
  .swatch-dot { width: 9px; height: 9px; border-radius: 50%; background: #b8895a; }
</style>
</head>
<body>
<h1>Strength estimate over time</h1>
<div class="sub">
  __COUNT__ game(s) with a dated, resolved, high-confidence rank value. Low/medium-confidence
  games (typically ones that ended early, e.g. by resignation, leaving too few analyzed moves)
  are excluded -- their estimate is too noisy to plot. Dots are individual games (still noisy);
  the green line is the rolling average over the last __WINDOW__ games -- read that, not
  single dots. Dashed lines mark strength-band boundaries. Ported from LizzieYzy Next's
  XGBoost20TUN model -- for review reference only, not a rating.
</div>
<div id="chart-wrap" __HIDE_IF_EMPTY__>
  <svg id="chart" width="960" height="480" viewBox="0 0 960 480">__SVG__</svg>
  <div id="tooltip"></div>
</div>
<div class="legend" __HIDE_IF_EMPTY__>
  <span><span class="swatch swatch-dot"></span>per-game rank value</span>
  <span><span class="swatch swatch-avg"></span>rolling average (__WINDOW__ games)</span>
</div>
<p id="noData" __HIDE_IF_DATA__>No dated, high-confidence games yet -- run `baduk-lab analyze` first.</p>

<script>
const DATA = __DATA__;
const tooltip = document.getElementById('tooltip');
const chartWrap = document.getElementById('chart-wrap');

document.querySelectorAll('.point').forEach(el => {
  el.addEventListener('mouseenter', () => {
    document.querySelectorAll('.point.active').forEach(a => a.classList.remove('active'));
    el.classList.add('active');
    const p = DATA[+el.getAttribute('data-idx')];
    tooltip.innerHTML = `<b>${p.game}</b><br>${p.date} &middot; you played ${p.youLabel}<br>` +
      `Band: ${p.band}<br>Rank value: ${p.rankValue.toFixed(1)} ` +
      `(rolling avg: ${p.rollingAvg.toFixed(1)})`;
    const rect = chartWrap.getBoundingClientRect();
    const cx = parseFloat(el.getAttribute('cx')), cy = parseFloat(el.getAttribute('cy'));
    const scaleX = rect.width / 960;
    tooltip.style.left = (cx * scaleX + 12) + 'px';
    tooltip.style.top = Math.max(0, cy * scaleX - 10) + 'px';
    tooltip.style.visibility = 'visible';
  });
  el.addEventListener('mouseleave', () => {
    el.classList.remove('active');
    tooltip.style.visibility = 'hidden';
  });
});
</script>
</body>
</html>
"""
