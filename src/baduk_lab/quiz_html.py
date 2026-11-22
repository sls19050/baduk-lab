"""Render a self-contained HTML quiz page: `baduk-lab review --html`.

Replaces the one-SGF-at-a-time terminal loop for the actual "go look at a
position and guess" step. Takes exactly the `due` list `_run_review`
already computes (worst points-lost first, --limit/--phase applied), bakes
each problem's pre-mistake board (via board.board_before) plus the played/
best vertices into one embedded JSON blob, and ships a hand-rolled inline
SVG board renderer -- no external libraries, no CDN, works offline.

Problems from both decks render the same way. A `notes` problem (one you
commented on yourself) additionally shows your own note on reveal, is
labelled by winrate lost rather than points when those disagree, and
offers a "count it anyway" override -- grading compares the click to
KataGo's single top move, but a note usually describes a plan, and the
move you had in mind may be just as good.

Grading is client-side and immediate: click an empty intersection, it's
compared to the recorded "best" vertex. Each graded answer is then POSTed
to /quiz-state on the local server this page is served from, which calls
the same quiz.record_result/save_state used by the terminal review flow --
no file picker, no client-side reimplementation of the box scheduling.
Falls back to a visible "not saved" banner if that request fails (server
not reachable, e.g. the page was saved and reopened directly instead of
via `baduk-lab review --html`).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sgfmill.common import move_from_vertex

from . import board
from .report import ProblemIndexEntry


def _coords(vertices: list[str], board_size: int) -> list[list[int]]:
    """SGF vertex strings to [row, col] pairs, dropping passes."""
    out = []
    for vertex in vertices:
        coord = move_from_vertex(vertex, board_size)
        if coord is not None:
            out.append(list(coord))
    return out


def render_quiz_html(due: list[ProblemIndexEntry], games: dict, out_path: Path,
                     today: date) -> Path:
    problems = []
    for p in due:
        game_info = games.get(p.game)
        if game_info is None:
            continue  # games.json out of sync with index.json; skip rather than crash
        board_size = game_info["board_size"]
        moves = [(i + 1, color, (tuple(coord) if coord else None))
                for i, (color, coord) in enumerate(game_info["moves"])]
        stones = board.board_before(moves, board_size, p.move_number)
        played_coord = move_from_vertex(p.played, board_size)
        best_coord = move_from_vertex(p.best, board_size)
        problems.append({
            "id": p.problem_id,
            "game": p.game,
            "moveNumber": p.move_number,
            "phase": p.phase,
            "pointsLost": round(p.points_lost, 1),
            "boardSize": board_size,
            "mover": "b" if p.move_number % 2 == 1 else "w",
            "stones": [[r, c, color] for (r, c), color in stones.items()],
            "played": list(played_coord) if played_coord else None,
            "best": list(best_coord) if best_coord else None,
            "path": p.path,
            "source": p.source,
            "note": p.note,
            "winrateDrop": round(p.winrate_drop, 3),
            "alternatives": _coords(p.alternatives, board_size),
            "noteVertices": _coords(p.note_vertices, board_size),
        })

    payload = json.dumps(problems).replace("</", "<\\/")
    html = (_TEMPLATE
           .replace("__QUIZ_DATA__", payload)
           .replace("__GENERATED__", today.isoformat())
           .replace("__COUNT__", str(len(problems))))
    out_path.write_text(html, encoding="utf-8")
    return out_path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>baduk-lab quiz</title>
<style>
  :root { color-scheme: light; }
  body {
    margin: 0; padding: 24px 16px 60px; background: #f3efe8; color: #1f1b16;
    font: 15px/1.5 -apple-system, "Segoe UI", sans-serif;
    display: flex; flex-direction: column; align-items: center;
  }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: #6b6156; font-size: 13px; margin-bottom: 16px; }
  .bar {
    width: 100%; max-width: 620px; display: flex; justify-content: space-between;
    align-items: center; margin-bottom: 12px; gap: 12px; flex-wrap: wrap;
  }
  .score { font-variant-numeric: tabular-nums; font-weight: 600; }
  button {
    font: inherit; padding: 6px 14px; border-radius: 6px; border: 1px solid #c9beac;
    background: #fff; cursor: pointer;
  }
  button:hover { background: #f8f3ea; }
  button:disabled { opacity: 0.4; cursor: default; }
  button.primary { background: #2f6b3a; color: #fff; border-color: #2f6b3a; }
  button.primary:hover { background: #275a31; }
  #saveStatus { font-size: 12px; color: #6b6156; }
  #board-wrap { background: #dcb35c; border-radius: 8px; padding: 8px;
               box-shadow: 0 1px 4px rgba(0,0,0,0.2); }
  svg { display: block; touch-action: manipulation; }
  .info {
    width: 100%; max-width: 620px; margin-top: 14px; background: #fff;
    border: 1px solid #e3dbcb; border-radius: 8px; padding: 14px 16px;
  }
  .info .meta { color: #6b6156; font-size: 13px; margin-bottom: 6px; }
  .status { font-weight: 600; min-height: 22px; }
  .status.correct { color: #2f6b3a; }
  .status.wrong { color: #a53f3f; }
  .actions { margin-top: 10px; display: flex; gap: 8px; }
  .lizzie-status { font-size: 12px; color: #6b6156; margin-top: 6px; min-height: 16px; }
  .tag {
    display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: 0.04em;
    text-transform: uppercase; padding: 1px 6px; border-radius: 4px; margin-right: 6px;
    background: #e8e0d0; color: #6b6156;
  }
  .tag.note { background: #dfe7f3; color: #2c4a76; }
  .note-box {
    margin-top: 10px; padding: 10px 12px; border-left: 3px solid #2c4a76;
    background: #f2f6fc; border-radius: 0 6px 6px 0; white-space: pre-wrap;
  }
  .note-box .label {
    font-size: 11px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
    color: #2c4a76; display: block; margin-bottom: 4px;
  }
  #done { max-width: 620px; text-align: center; }
  #done h2 { margin-bottom: 4px; }
  .legend { font-size: 12px; color: #6b6156; margin-top: 10px; }
  .legend span { padding: 1px 6px; border-radius: 4px; margin-right: 4px; }
  .swatch-best { background: #cdead4; color: #1f4d2a; }
  .swatch-played { background: #f6d9c9; color: #7a3f1f; }
  .swatch-alt { background: #e4f0e7; color: #2f6b3a; }
  .swatch-note { background: #dfe7f3; color: #2c4a76; }
</style>
</head>
<body>
<h1>baduk-lab quiz</h1>
<div class="sub" id="headerSub">__COUNT__ problem(s) &middot; generated __GENERATED__</div>

<div class="bar">
  <div class="score" id="score">0 / 0</div>
  <div style="display:flex; align-items:center; gap:8px;">
    <span id="saveStatus">Progress saves automatically</span>
  </div>
</div>

<div id="quiz">
  <div id="board-wrap"><svg id="board" width="0" height="0"></svg></div>
  <div class="info">
    <div class="meta" id="meta">-</div>
    <div class="status" id="status">Click a point on the board to guess.</div>
    <div class="note-box" id="noteBox" hidden><span class="label">Your note</span><span id="noteText"></span></div>
    <div class="actions">
      <button id="lizzieBtn">Deep analysis in LizzieYzy</button>
      <button id="skipBtn">Skip (show answer)</button>
      <button id="overrideBtn" hidden>My move was fine &mdash; count it</button>
      <button id="nextBtn" class="primary" disabled>Next &rarr;</button>
    </div>
    <div id="lizzieStatus" class="lizzie-status"></div>
    <div class="legend">
      <span class="swatch-best">B</span>the answer
      <span class="swatch-alt">=</span>also counts as right
      <span class="swatch-played">P</span>what you actually played
      <span class="swatch-note">N</span>other points your note names
    </div>
  </div>
</div>

<div id="done" hidden>
  <h2>Session complete</h2>
  <p id="doneSummary"></p>
  <button id="restartBtn">Restart this set</button>
</div>

<script>
const DATA = __QUIZ_DATA__;
// MARGIN has to clear the coordinate labels drawn outside the grid, since
// the SVG is sized to exactly MARGIN*2 + the grid and anything past that
// is clipped.
const CELL = 30, MARGIN = 30;
// Go skips I, so a column's letter is not its index's letter.
const COLUMN_LETTERS = 'ABCDEFGHJKLMNOPQRST';

let idx = 0, correctCount = 0, answeredCount = 0, answered = false;

const svg = document.getElementById('board');
const metaEl = document.getElementById('meta');
const statusEl = document.getElementById('status');
const scoreEl = document.getElementById('score');
const nextBtn = document.getElementById('nextBtn');
const skipBtn = document.getElementById('skipBtn');
const overrideBtn = document.getElementById('overrideBtn');
const noteBox = document.getElementById('noteBox');
const noteText = document.getElementById('noteText');
const saveStatusEl = document.getElementById('saveStatus');
const lizzieBtn = document.getElementById('lizzieBtn');
const lizzieStatusEl = document.getElementById('lizzieStatus');

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function toXY(row, col, size) {
  return [MARGIN + col * CELL, MARGIN + (size - 1 - row) * CELL];
}

function label(x, y, text, anchor) {
  const el = svgEl('text', {
    x, y, 'text-anchor': anchor, 'font-size': 11, fill: '#6b5836',
    'font-family': 'inherit',
  });
  el.textContent = text;
  svg.appendChild(el);
}

// Both edges, not just one: your own notes name points all over the board
// ("hane at L13", "extend to R6"), and counting in from the far side of a
// 19x19 grid is exactly the friction this is here to remove.
function drawCoordinates(size) {
  const far = MARGIN + (size - 1) * CELL;
  for (let col = 0; col < size; col++) {
    const [x] = toXY(0, col, size);
    label(x, MARGIN - 14, COLUMN_LETTERS[col], 'middle');
    label(x, far + 20, COLUMN_LETTERS[col], 'middle');
  }
  for (let row = 0; row < size; row++) {
    const [, y] = toXY(row, 0, size);
    // Row 0 is the bottom edge, which is line 1.
    label(MARGIN - 12, y + 4, String(row + 1), 'end');
    label(far + 12, y + 4, String(row + 1), 'start');
  }
}

function starPoints(size) {
  if (size === 19) return [3,9,15].flatMap(r => [3,9,15].map(c => [r,c]));
  if (size === 13) return [3,9].flatMap(r => [3,9].map(c => [r,c])).concat([[6,6]]);
  if (size === 9) return [[2,2],[2,6],[6,2],[6,6],[4,4]];
  return [];
}

function renderProblem() {
  const p = DATA[idx];
  answered = false;
  const size = p.boardSize;
  const dim = MARGIN * 2 + (size - 1) * CELL;
  svg.setAttribute('width', dim);
  svg.setAttribute('height', dim);
  svg.innerHTML = '';

  for (let i = 0; i < size; i++) {
    const [x0, y0] = toXY(i, 0, size), [x1] = toXY(i, size - 1, size);
    svg.appendChild(svgEl('line', {x1: x0, y1: y0, x2: x1, y2: y0, stroke: '#3a2c14', 'stroke-width': 1}));
    const [xa, ya] = toXY(0, i, size), [, yb] = toXY(size - 1, i, size);
    svg.appendChild(svgEl('line', {x1: xa, y1: ya, x2: xa, y2: yb, stroke: '#3a2c14', 'stroke-width': 1}));
  }
  drawCoordinates(size);
  for (const [r, c] of starPoints(size)) {
    const [x, y] = toXY(r, c, size);
    svg.appendChild(svgEl('circle', {cx: x, cy: y, r: 2.5, fill: '#3a2c14'}));
  }

  const occupied = new Set(p.stones.map(s => s[0] + ',' + s[1]));
  for (const [r, c, color] of p.stones) {
    const [x, y] = toXY(r, c, size);
    svg.appendChild(svgEl('circle', {
      cx: x, cy: y, r: CELL * 0.46,
      fill: color === 'b' ? '#111' : '#f7f3ea',
      stroke: color === 'b' ? '#000' : '#4a4033',
      'stroke-width': color === 'b' ? 0 : 1.2,
    }));
  }

  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      if (occupied.has(r + ',' + c)) continue;
      const [x, y] = toXY(r, c, size);
      const hit = svgEl('circle', {cx: x, cy: y, r: CELL * 0.48, fill: 'transparent', style: 'cursor:pointer'});
      hit.addEventListener('click', () => onGuess(r, c));
      svg.appendChild(hit);
    }
  }

  // A hand-picked note can cost almost no points while swinging the
  // winrate hard, so lead with whichever number actually measures it.
  const cost = p.source === 'note' && p.winrateDrop >= 0.01
    ? `${(p.winrateDrop * 100).toFixed(0)}% winrate lost`
    : `${p.pointsLost.toFixed(1)} pts lost`;
  metaEl.innerHTML = '';
  const tag = document.createElement('span');
  tag.className = p.source === 'note' ? 'tag note' : 'tag';
  tag.textContent = p.source === 'note' ? 'your note' : 'katago';
  metaEl.appendChild(tag);
  metaEl.appendChild(document.createTextNode(
    `${p.game} · move ${p.moveNumber} · ${p.phase} · ${cost} · ` +
    `${p.mover === 'b' ? 'Black' : 'White'} to play`));

  statusEl.textContent = 'Click a point on the board to guess.';
  statusEl.className = 'status';
  noteBox.hidden = true;
  noteText.textContent = '';
  overrideBtn.hidden = true;
  lizzieStatusEl.textContent = '';
  nextBtn.disabled = true;
  document.getElementById('headerSub').textContent =
    `Problem ${idx + 1} of ${DATA.length} · generated __GENERATED__`;
}

const MARK_TEXT_FILL = {
  'mark-best': '#1f4d2a', 'mark-alt': '#2f6b3a',
  'mark-played': '#7a3f1f', 'mark-note': '#2c4a76',
};

function markPoint(row, col, size, label, cls) {
  const [x, y] = toXY(row, col, size);
  const g = svgEl('g', {});
  g.appendChild(svgEl('circle', {cx: x, cy: y, r: CELL * 0.3, class: cls}));
  const text = svgEl('text', {
    x, y: y + 4, 'text-anchor': 'middle', 'font-size': 12, 'font-weight': 700,
    fill: MARK_TEXT_FILL[cls] || '#1c3a63',
  });
  text.textContent = label;
  g.appendChild(text);
  svg.appendChild(g);
}

function same(a, b) {
  return !!a && !!b && a[0] === b[0] && a[1] === b[1];
}

function reveal(p, guess) {
  const best = p.best;
  const played = p.played;
  const alternatives = p.alternatives || [];
  // A position usually has more than one good move, and these are the
  // ones this problem actually knows about: the other lines you played
  // out, plus KataGo's pick when your note named a different move.
  const correct = same(guess, best) || alternatives.some(alt => same(guess, alt));

  if (best) markPoint(best[0], best[1], p.boardSize, 'B', 'mark-best');
  for (const alt of alternatives) {
    if (!same(alt, played)) markPoint(alt[0], alt[1], p.boardSize, '=', 'mark-alt');
  }
  // Points your note talks about but nothing here recommends -- "the moyo
  // at F7" means nothing until you can see where F7 is.
  for (const v of (p.noteVertices || [])) {
    if (same(v, best) || same(v, played) || alternatives.some(a => same(a, v))) continue;
    markPoint(v[0], v[1], p.boardSize, 'N', 'mark-note');
  }
  if (played && !same(played, best)) {
    markPoint(played[0], played[1], p.boardSize, 'P', 'mark-played');
  }
  if (guess && !same(guess, best)) {
    markPoint(guess[0], guess[1], p.boardSize, '?', 'mark-guess');
  }

  document.querySelectorAll('#board circle[fill="transparent"]').forEach(el => el.remove());

  // Your own diagnosis, in your own words -- the reason this position is
  // in the deck at all, and worth more than the marked point.
  if (p.note) {
    noteText.textContent = p.note;
    noteBox.hidden = false;
  }

  if (!guess) {
    statusEl.textContent = best ? "Answer shown — not scored." : 'KataGo suggests passing here.';
    statusEl.className = 'status';
  } else if (correct) {
    statusEl.textContent = `Correct! (${p.pointsLost.toFixed(1)} pts were lost by not playing this)`;
    statusEl.className = 'status correct';
  } else {
    statusEl.textContent = `Not quite — the better move is marked B (${p.pointsLost.toFixed(1)} pts lost).`;
    statusEl.className = 'status wrong';
    // Graded against KataGo's single top move, but your note may well have
    // named a different move that is just as good (it often names a plan,
    // not a point). You're the judge; this just fixes the scheduling.
    overrideBtn.hidden = false;
  }
  nextBtn.disabled = false;
  nextBtn.focus();
  return correct;
}

async function onGuess(row, col) {
  if (answered) return;
  answered = true;
  const p = DATA[idx];
  const correct = reveal(p, [row, col]);
  answeredCount++;
  if (correct) correctCount++;
  scoreEl.textContent = `${correctCount} / ${answeredCount}`;
  await saveResult(p.id, correct);
}

skipBtn.addEventListener('click', () => {
  if (answered) return;
  answered = true;
  reveal(DATA[idx], null);
});

overrideBtn.addEventListener('click', async () => {
  overrideBtn.hidden = true;
  correctCount++;
  scoreEl.textContent = `${correctCount} / ${answeredCount}`;
  statusEl.textContent = 'Counted as correct.';
  statusEl.className = 'status correct';
  await saveResult(DATA[idx].id, true);
});

lizzieBtn.addEventListener('click', async () => {
  const p = DATA[idx];
  lizzieStatusEl.textContent = 'Opening in LizzieYzy (closing any previous instance first)…';
  try {
    const res = await fetch('/open-lizzie?path=' + encodeURIComponent(p.path));
    const body = await res.json();
    lizzieStatusEl.textContent = body.ok
      ? 'Opened in LizzieYzy.'
      : 'Could not open: ' + body.error;
  } catch (err) {
    lizzieStatusEl.textContent = 'Could not reach the local server: ' + err.message;
  }
});

function next() {
  if (!answered) return;
  idx++;
  if (idx >= DATA.length) {
    document.getElementById('quiz').hidden = true;
    document.getElementById('done').hidden = false;
    document.getElementById('doneSummary').textContent =
      `You answered ${correctCount} of ${answeredCount} correctly` +
      (answeredCount < DATA.length ? ` (${DATA.length - answeredCount} skipped).` : '.');
    return;
  }
  renderProblem();
}
nextBtn.addEventListener('click', next);
document.addEventListener('keydown', (e) => {
  if ((e.key === 'Enter' || e.key === 'ArrowRight' || e.key === ' ') && !nextBtn.disabled) {
    e.preventDefault();
    next();
  }
});

document.getElementById('restartBtn').addEventListener('click', () => {
  idx = 0; correctCount = 0; answeredCount = 0;
  scoreEl.textContent = '0 / 0';
  document.getElementById('done').hidden = true;
  document.getElementById('quiz').hidden = false;
  renderProblem();
});

async function saveResult(problemId, correct) {
  try {
    const res = await fetch('/quiz-state', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({problemId, correct}),
    });
    const body = await res.json();
    saveStatusEl.textContent = body.ok
      ? 'Saved to quiz_state.json ✓'
      : 'Save failed: ' + body.error;
  } catch (err) {
    saveStatusEl.textContent = 'Could not reach the local server: ' + err.message;
  }
}

const style = document.createElement('style');
style.textContent = '.mark-best{fill:#cdead4;stroke:#2f6b3a;stroke-width:1.5}' +
  '.mark-played{fill:#f6d9c9;stroke:#a5602f;stroke-width:1.5}' +
  '.mark-alt{fill:#e4f0e7;stroke:#2f6b3a;stroke-width:1.5;stroke-dasharray:3 2}' +
  '.mark-note{fill:#dfe7f3;stroke:#2c4a76;stroke-width:1.5;stroke-dasharray:3 2}' +
  '.mark-guess{fill:none;stroke:#1c3a63;stroke-width:2}';
document.head.appendChild(style);

if (DATA.length === 0) {
  document.getElementById('quiz').hidden = true;
  document.getElementById('done').hidden = false;
  document.getElementById('doneSummary').textContent = 'Nothing due right now. Nice.';
  document.getElementById('restartBtn').hidden = true;
} else {
  renderProblem();
}
</script>
</body>
</html>
"""
