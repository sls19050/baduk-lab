"""Render the drill page: `baduk-lab drill review`.

Same approach as quiz_html.py (self-contained page, inline SVG board,
grading POSTed to the local server's /quiz-state), but each position asks
two things in order:

1. "Where do you play?" -- a click, graded against the problem's tolerant
   answer key (`accepted`), not just KataGo's single top move. The
   local/tenuki judgement isn't asked as a separate question: a local move
   when tenuki was right is simply not in the answer key. The feedback
   still names which side you played, since that's the habit being
   trained.
2. "What's the score now?" -- asked only when the move was right, and
   graded within `SCORE_TOLERANCE` points. The position's score lead is
   deliberately kept off the board until the answer is shown, otherwise
   this would just be reading it back: the best move's score is within a
   fraction of a point of the score before it.

The opponent's last move is marked on purpose: it's the temptation the
drill is about. Only the move drives scheduling: a right move with a wrong
score estimate still graduates the problem to the next box, because
knowing where to play before you can count the result is a normal stage of
progress -- otherwise one bad count would keep re-serving the same deck
every session. The score estimate is tracked in the session stats only.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sgfmill.common import move_from_vertex

from . import board
from .drill import SCORE_TOLERANCE, DrillProblem


def render_drill_html(session: list[DrillProblem], games: dict, out_path: Path,
                      today: date, score_tolerance: float = SCORE_TOLERANCE) -> Path:
    problems = []
    for p in session:
        game = games.get(p.game)
        if game is None:
            continue
        size = game["board_size"]
        moves = [(i + 1, c, tuple(coord) if coord else None)
                 for i, (c, coord) in enumerate(game["moves"])]
        stones = board.board_before(moves, size, p.move_number)

        def rc(vertex: str) -> list[int]:
            return list(move_from_vertex(vertex, size))

        problems.append({
            "id": p.problem_id,
            "seed": p.seed,
            "moveNumber": p.move_number,
            "mover": p.mover,
            "kind": p.kind,
            "gap": p.gap,
            "scoreLead": p.score_lead,
            "boardSize": size,
            "stones": [[r, c, color] for (r, c), color in stones.items()],
            "last": rc(p.last_move),
            "bestLocal": rc(p.best_local),
            "bestLocalScore": p.best_local_score,
            "bestTenuki": rc(p.best_tenuki),
            "bestTenukiScore": p.best_tenuki_score,
            "accepted": [rc(v) for v in p.accepted],
            "acceptedScores": p.accepted_scores,
            "region": [rc(v) for v in p.region],
            "path": p.path,
        })

    payload = json.dumps(problems).replace("</", "<\\/")
    html = (_TEMPLATE
            .replace("__DRILL_DATA__", payload)
            .replace("__SCORE_TOL__", f"{score_tolerance:g}")
            .replace("__GENERATED__", today.isoformat())
            .replace("__COUNT__", str(len(problems))))
    out_path.write_text(html, encoding="utf-8")
    return out_path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tenuki drill</title>
<style>
  :root { color-scheme: light; }
  [hidden] { display: none !important; }  /* .choices' display:flex would override it */
  body {
    margin: 0; padding: 24px 16px 60px; background: #f3efe8; color: #1f1b16;
    font: 15px/1.5 -apple-system, "Segoe UI", sans-serif;
    display: flex; flex-direction: column; align-items: center;
  }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: #6b6156; font-size: 13px; margin-bottom: 16px; }
  .score { font-variant-numeric: tabular-nums; font-weight: 600; }
  .bar {
    width: 100%; max-width: 620px; display: flex; justify-content: space-between;
    align-items: center; margin-bottom: 12px; gap: 12px; flex-wrap: wrap;
  }
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
               box-shadow: 0 1px 4px rgba(0,0,0,0.2); max-width: 100%; }
  svg { display: block; touch-action: manipulation; max-width: 100%; height: auto; }
  .info {
    width: 100%; max-width: 620px; margin-top: 14px; background: #fff;
    border: 1px solid #e3dbcb; border-radius: 8px; padding: 14px 16px; box-sizing: border-box;
  }
  .info .meta { color: #6b6156; font-size: 13px; margin-bottom: 6px; }
  .prompt { font-weight: 600; font-size: 16px; min-height: 24px; }
  .choices { display: flex; gap: 10px; margin: 10px 0 4px; flex-wrap: wrap;
             align-items: center; }
  #scoreInput {
    font: inherit; font-variant-numeric: tabular-nums; width: 100px; padding: 7px 10px;
    border-radius: 6px; border: 1px solid #c9beac; text-align: right;
  }
  .hint { font-size: 12px; color: #6b6156; }
  .result { margin-top: 8px; }
  .result .line { margin: 2px 0; }
  .ok { color: #2f6b3a; font-weight: 600; }
  .bad { color: #a53f3f; font-weight: 600; }
  .actions { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
  .lizzie-status { font-size: 12px; color: #6b6156; margin-top: 6px; min-height: 16px; }
  .legend { font-size: 12px; color: #6b6156; margin-top: 10px; }
  .legend span { padding: 1px 6px; border-radius: 4px; margin-right: 4px; }
  .sw-t { background: #cdead4; color: #1f4d2a; }
  .sw-l { background: #d6e2f5; color: #1c3a63; }
  .sw-last { background: #f3d0d0; color: #7a1f1f; }
  #done { max-width: 620px; text-align: center; }
  .keys { font-size: 12px; color: #6b6156; }
</style>
</head>
<body>
<h1>Tenuki drill</h1>
<div class="sub" id="headerSub">__COUNT__ position(s) &middot; generated __GENERATED__</div>

<div class="bar">
  <div class="score" id="score">Move 0/0 &middot; Score 0/0</div>
  <span id="saveStatus">Progress saves automatically</span>
</div>

<div id="quiz">
  <div id="board-wrap"><svg id="board"></svg></div>
  <div class="info">
    <div class="meta" id="meta">-</div>
    <div class="prompt" id="prompt"></div>
    <div class="choices" id="choices" hidden>
      <input id="scoreInput" inputmode="decimal" autocomplete="off" placeholder="+0.0">
      <button id="scoreBtn" class="primary">Submit <span class="keys">(Enter)</span></button>
      <span class="hint" id="scoreHint"></span>
    </div>
    <div class="result" id="result"></div>
    <div class="actions">
      <button id="lizzieBtn">Deep analysis in LizzieYzy</button>
      <button id="skipBtn">Skip (show answer)</button>
      <button id="nextBtn" class="primary" disabled>Next &rarr;</button>
    </div>
    <div id="lizzieStatus" class="lizzie-status"></div>
    <div class="legend">
      <span class="sw-last">&#9679;</span>opponent's last move
      <span class="sw-t">T</span>best tenuki
      <span class="sw-l">L</span>best local answer
      &middot; small dots: other moves also accepted
    </div>
  </div>
</div>

<div id="done" hidden>
  <h2>Session complete</h2>
  <p id="doneSummary"></p>
  <button id="restartBtn">Restart this set</button>
</div>

<script>
const DATA = __DRILL_DATA__;
const SCORE_TOL = __SCORE_TOL__;
const CELL = 30, MARGIN = 26;

// stage: 'where' -> 'score' (only when the move was right) -> 'shown'
let idx = 0, stage = 'where';
let moveGuess = null, moveOk = false, scoreGuess = null, scoreOk = false;
let moveRight = 0, moveTotal = 0, scoreRight = 0, scoreTotal = 0, bothRight = 0;

const svg = document.getElementById('board');
const $ = id => document.getElementById(id);

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}
function toXY(row, col, size) { return [MARGIN + col * CELL, MARGIN + (size - 1 - row) * CELL]; }
function starPoints(size) {
  if (size === 19) return [3,9,15].flatMap(r => [3,9,15].map(c => [r,c]));
  return [];
}
const same = (a, b) => !!a && !!b && a[0] === b[0] && a[1] === b[1];
const side = c => c === 'b' ? 'Black' : 'White';
const other = c => c === 'b' ? 'White' : 'Black';
const fmt = x => (x >= 0 ? '+' : '') + x.toFixed(1);

function renderBoard(p) {
  const size = p.boardSize, dim = MARGIN * 2 + (size - 1) * CELL;
  svg.setAttribute('viewBox', `0 0 ${dim} ${dim}`);
  svg.setAttribute('width', dim);
  svg.innerHTML = '';
  for (let i = 0; i < size; i++) {
    const [x0, y0] = toXY(i, 0, size), [x1] = toXY(i, size - 1, size);
    svg.appendChild(svgEl('line', {x1: x0, y1: y0, x2: x1, y2: y0, stroke: '#3a2c14', 'stroke-width': 1}));
    const [xa, ya] = toXY(0, i, size), [, yb] = toXY(size - 1, i, size);
    svg.appendChild(svgEl('line', {x1: xa, y1: ya, x2: xa, y2: yb, stroke: '#3a2c14', 'stroke-width': 1}));
  }
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
      stroke: color === 'b' ? '#000' : '#4a4033', 'stroke-width': color === 'b' ? 0 : 1.2,
    }));
    if (same([r, c], p.last)) {
      svg.appendChild(svgEl('circle', {cx: x, cy: y, r: CELL * 0.2, fill: 'none',
        stroke: '#d23c3c', 'stroke-width': 3}));
    }
  }
  for (let r = 0; r < size; r++) for (let c = 0; c < size; c++) {
    if (occupied.has(r + ',' + c)) continue;
    const [x, y] = toXY(r, c, size);
    const hit = svgEl('circle', {cx: x, cy: y, r: CELL * 0.48, fill: 'transparent',
                                 class: 'hit', style: 'cursor:pointer'});
    hit.addEventListener('click', () => onClickPoint(r, c));
    svg.appendChild(hit);
  }
}

function mark(pt, size, label, fill, stroke, textColor) {
  const [x, y] = toXY(pt[0], pt[1], size);
  svg.appendChild(svgEl('circle', {cx: x, cy: y, r: CELL * 0.32, fill, stroke, 'stroke-width': 1.5}));
  const t = svgEl('text', {x, y: y + 4, 'text-anchor': 'middle', 'font-size': 12,
                           'font-weight': 700, fill: textColor});
  t.textContent = label;
  svg.appendChild(t);
}
function dot(pt, size) {
  const [x, y] = toXY(pt[0], pt[1], size);
  svg.appendChild(svgEl('circle', {cx: x, cy: y, r: 4, fill: '#2f6b3a', opacity: 0.7}));
}
function playStone(pt, size, color) {
  const [x, y] = toXY(pt[0], pt[1], size);
  svg.appendChild(svgEl('circle', {
    cx: x, cy: y, r: CELL * 0.46,
    fill: color === 'b' ? '#111' : '#f7f3ea',
    stroke: '#2f6b3a', 'stroke-width': 2.5,
  }));
}

function renderProblem() {
  const p = DATA[idx];
  stage = 'where';
  moveGuess = null; moveOk = false; scoreGuess = null; scoreOk = false;
  renderBoard(p);
  // The score before the move is deliberately not shown: the best move
  // barely changes it, so showing it would answer the score question.
  $('meta').textContent =
    `${p.seed} · move ${p.moveNumber} · ${side(p.mover)} to play`;
  $('prompt').textContent =
    `Your opponent just played the marked stone. Where do you play?`;
  $('choices').hidden = true;
  $('scoreInput').value = '';
  $('scoreHint').textContent = '';
  $('result').innerHTML = '';
  $('lizzieStatus').textContent = '';
  $('nextBtn').disabled = true;
  $('skipBtn').disabled = false;
  $('headerSub').textContent = `Position ${idx + 1} of ${DATA.length} · generated __GENERATED__`;
}

function updateScoreboard() {
  $('score').textContent =
    `Move ${moveRight}/${moveTotal} · Score ${scoreRight}/${scoreTotal}`;
}

function onClickPoint(r, c) {
  if (stage !== 'where') return;
  const p = DATA[idx];
  moveGuess = [r, c];
  moveOk = p.accepted.some(a => same(a, moveGuess));
  moveTotal++; moveRight += moveOk;
  updateScoreboard();
  document.querySelectorAll('#board .hit').forEach(el => el.remove());
  if (!moveOk) { reveal(); return; }

  // Right move: play it on the board and ask what the score is now.
  stage = 'score';
  playStone(moveGuess, p.boardSize, p.mover);
  $('prompt').textContent =
    `Right move. What's the score after it, from ${side(p.mover)}'s side?`;
  $('scoreHint').textContent =
    `points (negative if ${other(p.mover)} is ahead) · within ${SCORE_TOL} counts` +
    ` · practice only, doesn't affect scheduling`;
  $('choices').hidden = false;
  $('scoreInput').focus();
}

function submitScore() {
  if (stage !== 'score') return;
  const p = DATA[idx];
  const raw = $('scoreInput').value.trim().replace(/^\+/, '');
  const val = parseFloat(raw);
  if (raw === '' || !isFinite(val)) {
    $('scoreHint').textContent = 'Enter a number, e.g. -2.5';
    return;
  }
  scoreGuess = val;
  scoreOk = Math.abs(val - acceptedScoreOf(p, moveGuess)) <= SCORE_TOL;
  scoreTotal++; scoreRight += scoreOk; bothRight += scoreOk;
  updateScoreboard();
  reveal();
}

function acceptedScoreOf(p, pt) {
  const i = p.accepted.findIndex(a => same(a, pt));
  // Fall back to the winning side's best score if the key has no score
  // for this move (a deck built before acceptedScores existed).
  if (i >= 0 && p.acceptedScores && p.acceptedScores.length > i) return p.acceptedScores[i];
  return p.kind === 'tenuki' ? p.bestTenukiScore : p.bestLocalScore;
}

function reveal() {
  const p = DATA[idx];
  stage = 'shown';
  document.querySelectorAll('#board .hit').forEach(el => el.remove());
  for (const a of p.accepted) dot(a, p.boardSize);
  mark(p.bestTenuki, p.boardSize, 'T', '#cdead4', '#2f6b3a', '#1f4d2a');
  mark(p.bestLocal, p.boardSize, 'L', '#d6e2f5', '#1c3a63', '#1c3a63');
  if (moveGuess && !same(moveGuess, p.bestTenuki) && !same(moveGuess, p.bestLocal)) {
    const [x, y] = toXY(moveGuess[0], moveGuess[1], p.boardSize);
    svg.appendChild(svgEl('circle', {cx: x, cy: y, r: CELL * 0.3, fill: 'none',
                                     stroke: '#7a3f1f', 'stroke-width': 2.5}));
  }

  const gap = Math.abs(p.gap).toFixed(1);
  const verdict = p.kind === 'tenuki'
    ? `<b>Tenuki was right.</b> Answering locally (L, ${fmt(p.bestLocalScore)}) costs ${gap} points compared with the best tenuki (T, ${fmt(p.bestTenukiScore)}).`
    : `<b>This one needed an answer.</b> Tenuki (T, ${fmt(p.bestTenukiScore)}) costs ${gap} points compared with answering at L (${fmt(p.bestLocalScore)}).`;
  const lines = [
    `<div class="line">${verdict}</div>`,
    `<div class="line">Score before your move: ${side(p.mover)} ${fmt(p.scoreLead)}.</div>`,
  ];

  if (moveGuess === null) {
    lines.unshift('<div class="line">Answer shown &mdash; not scored.</div>');
  } else {
    // The local/tenuki judgement isn't asked any more, but it's still the
    // habit being drilled, so the feedback names the side you picked.
    const playedLocal = p.region.some(a => same(a, moveGuess));
    const sideWord = playedLocal ? 'answered locally' : 'played elsewhere';
    lines.unshift(
      `<div class="line">Move: <span class="${moveOk ? 'ok' : 'bad'}">${moveOk ? '✓ accepted' : '✗ not one of the accepted moves'}</span>` +
      ` &mdash; you ${sideWord}` +
      (moveOk && p.accepted.length > 1 ? ` (${p.accepted.length} moves accepted)` : '') +
      `</div>`);
    if (scoreGuess !== null) {
      const truth = acceptedScoreOf(p, moveGuess);
      lines.splice(1, 0,
        `<div class="line">Score: <span class="${scoreOk ? 'ok' : 'bad'}">` +
        `${scoreOk ? '✓' : '✗'} you said ${fmt(scoreGuess)}, it's ${fmt(truth)}</span>` +
        ` (off by ${Math.abs(scoreGuess - truth).toFixed(1)})</div>`);
    } else if (moveOk) {
      lines.splice(1, 0, '<div class="line">Score: <span class="bad">not estimated</span></div>');
    }
    // Scheduling follows the move only -- the score estimate is practice,
    // not a gate, or a wrong count would reset the box and the same
    // positions would come back every session.
    saveResult(p.id, moveOk);
  }
  $('result').innerHTML = lines.join('');
  $('prompt').textContent = '';
  $('choices').hidden = true;
  $('skipBtn').disabled = true;
  $('nextBtn').disabled = false;
  $('nextBtn').focus();
}

$('scoreBtn').addEventListener('click', submitScore);
$('scoreInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); submitScore(); }
});
$('skipBtn').addEventListener('click', () => { if (stage !== 'shown') reveal(); });

function next() {
  if (stage !== 'shown') return;
  idx++;
  if (idx >= DATA.length) {
    $('quiz').hidden = true;
    $('done').hidden = false;
    $('doneSummary').textContent =
      `Move right ${moveRight}/${moveTotal}, score within ${SCORE_TOL} pts ` +
      `${scoreRight}/${scoreTotal}, both right ${bothRight}/${moveTotal}.`;
    return;
  }
  renderProblem();
}
$('nextBtn').addEventListener('click', next);
document.addEventListener('keydown', (e) => {
  if ((e.key === 'Enter' || e.key === 'ArrowRight' || e.key === ' ') && stage === 'shown') {
    e.preventDefault(); next();
  }
});

$('restartBtn').addEventListener('click', () => {
  idx = 0; moveRight = moveTotal = scoreRight = scoreTotal = bothRight = 0;
  updateScoreboard();
  $('done').hidden = true; $('quiz').hidden = false;
  renderProblem();
});

$('lizzieBtn').addEventListener('click', async () => {
  const p = DATA[idx];
  $('lizzieStatus').textContent = 'Opening in LizzieYzy (closing any previous instance first)…';
  try {
    const res = await fetch('/open-lizzie?path=' + encodeURIComponent(p.path));
    const body = await res.json();
    $('lizzieStatus').textContent = body.ok ? 'Opened in LizzieYzy.' : 'Could not open: ' + body.error;
  } catch (err) {
    $('lizzieStatus').textContent = 'Could not reach the local server: ' + err.message;
  }
});

async function saveResult(problemId, correct) {
  try {
    const res = await fetch('/quiz-state', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({problemId, correct}),
    });
    const body = await res.json();
    $('saveStatus').textContent = body.ok ? 'Saved ✓' : 'Save failed: ' + body.error;
  } catch (err) {
    $('saveStatus').textContent = 'Not saved — could not reach the local server: ' + err.message;
  }
}

if (DATA.length === 0) {
  $('quiz').hidden = true; $('done').hidden = false;
  $('doneSummary').textContent = 'Nothing due right now. Nice.';
  $('restartBtn').hidden = true;
} else {
  renderProblem();
}
</script>
</body>
</html>
"""
