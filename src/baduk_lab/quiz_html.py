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

from . import annotations, board
from .report import ProblemIndexEntry


def _coords(vertices: list[str], board_size: int) -> list[list[int]]:
    """SGF vertex strings to [row, col] pairs, dropping passes."""
    out = []
    for vertex in vertices:
        coord = move_from_vertex(vertex, board_size)
        if coord is not None:
            out.append(list(coord))
    return out


def _vertex(coord_vertex: str, board_size: int) -> list[int] | None:
    coord = move_from_vertex(coord_vertex, board_size) if coord_vertex else None
    return list(coord) if coord else None


def render_quiz_html(due: list[ProblemIndexEntry], games: dict, out_path: Path,
                     today: date, originals: dict | None = None) -> Path:
    """`originals` maps problem_id to the card as harvested, before any of
    your card_edits -- the page needs it to show which cards you edited and
    to reset one without reloading. Without it no card counts as edited."""
    originals = originals or {}
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
        orig = originals.get(p.problem_id, p)
        edited = (orig.best, list(orig.alternatives), orig.note) != \
            (p.best, list(p.alternatives), p.note)
        # An edited note may name different points than the harvested one.
        note_vertices = (annotations.vertices_in(p.note, board_size)
                         if edited and p.note != orig.note else p.note_vertices)
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
            "noteVertices": _coords(note_vertices, board_size),
            "opponent": p.opponent,
            "edited": edited,
            "orig": {
                "best": _vertex(orig.best, board_size),
                "alternatives": _coords(orig.alternatives, board_size),
                "note": orig.note,
                "noteVertices": _coords(orig.note_vertices, board_size),
            },
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
  .tag.edited { background: #f3e6c8; color: #7a5a14; }
  .edit-panel {
    margin-top: 12px; padding: 12px; border: 1px dashed #b89a5c; border-radius: 6px;
    background: #fdf9f0;
  }
  .edit-panel .hint { font-size: 13px; color: #6b6156; margin-bottom: 8px; }
  .edit-panel textarea {
    width: 100%; box-sizing: border-box; min-height: 90px; font: inherit;
    padding: 8px; border: 1px solid #c9beac; border-radius: 6px; resize: vertical;
  }
  .edit-panel .answers { font-size: 13px; margin: 8px 0; font-variant-numeric: tabular-nums; }
  .edit-status { font-size: 12px; min-height: 16px; margin-top: 6px; color: #6b6156; }
  .edit-status.bad { color: #a53f3f; }
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
      <button id="editBtn" hidden>Edit card</button>
      <button id="nextBtn" class="primary" disabled>Next &rarr;</button>
    </div>
    <div class="edit-panel" id="editPanel" hidden>
      <div class="hint">Click an empty point to change it:
        not accepted &rarr; <b>=</b> also right &rarr; <b>B</b> main answer &rarr; not accepted.
        Saving updates the card now and in every later session, and survives re-harvests;
        the grade you already got for this card stays as it was.</div>
      <div class="answers" id="editAnswers"></div>
      <textarea id="editNote" placeholder="Your note for this card"></textarea>
      <div class="actions">
        <button id="editSaveBtn" class="primary">Save</button>
        <button id="editCancelBtn">Cancel</button>
        <button id="editResetBtn">Reset to harvested</button>
      </div>
      <div class="edit-status" id="editStatus"></div>
    </div>
    <div id="lizzieStatus" class="lizzie-status"></div>
    <div class="legend">
      <span class="swatch-best">B</span>the answer
      <span class="swatch-alt">=</span>also counts as right
      <span class="swatch-played">P</span>what was actually played
      <span class="swatch-note">N</span>other points your note names
    </div>
  </div>
</div>

<div id="done" hidden>
  <h2>Session complete</h2>
  <p id="doneSummary"></p>
  <div class="actions" style="justify-content:center;">
    <button id="nextSetBtn" class="primary">Next set &rarr;</button>
    <button id="practiceSetBtn">Practice set (any card)</button>
    <button id="restartBtn">Restart this set</button>
  </div>
  <p id="newSetStatus" class="edit-status"></p>
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
let lastGuess = null;   // the point clicked for this card, kept to redraw marks after an edit
let draft = null;       // {best, alternatives} while the card editor is open

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
const editBtn = document.getElementById('editBtn');
const editPanel = document.getElementById('editPanel');
const editAnswers = document.getElementById('editAnswers');
const editNote = document.getElementById('editNote');
const editStatus = document.getElementById('editStatus');

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

// The grid, stones, and (when onClick is given) a click target on every
// empty point. Marks go on top afterwards.
function drawBoard(p, onClick) {
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

  if (!onClick) return;
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      if (occupied.has(r + ',' + c)) continue;
      const [x, y] = toXY(r, c, size);
      const hit = svgEl('circle', {cx: x, cy: y, r: CELL * 0.48, fill: 'transparent', style: 'cursor:pointer'});
      hit.addEventListener('click', () => onClick(r, c));
      svg.appendChild(hit);
    }
  }
}

// Click targets go last in drawBoard, so marks drawn after them would sit
// on top and swallow the click; in edit mode they're re-added above marks.
function raiseClickTargets() {
  svg.querySelectorAll('circle[fill="transparent"]').forEach(el => svg.appendChild(el));
}

function renderMeta(p) {
  // A hand-picked note can cost almost no points while swinging the
  // winrate hard, so lead with whichever number actually measures it.
  const cost = p.source === 'note' && p.winrateDrop >= 0.01
    ? `${(p.winrateDrop * 100).toFixed(0)}% winrate lost`
    : `${p.pointsLost.toFixed(1)} pts lost`;
  metaEl.innerHTML = '';
  const tag = document.createElement('span');
  tag.className = p.source === 'note' ? 'tag note' : 'tag';
  tag.textContent = p.source !== 'note' ? 'katago'
    : p.opponent ? "your note · opponent's move" : 'your note';
  metaEl.appendChild(tag);
  if (p.edited) {
    const ed = document.createElement('span');
    ed.className = 'tag edited';
    ed.textContent = 'edited';
    metaEl.appendChild(ed);
  }
  metaEl.appendChild(document.createTextNode(
    `${p.game} · move ${p.moveNumber} · ${p.phase} · ${cost} · ` +
    `${p.mover === 'b' ? 'Black' : 'White'} to play`));
}

function renderProblem() {
  const p = DATA[idx];
  answered = false;
  lastGuess = null;
  closeEditor();
  drawBoard(p, onGuess);
  renderMeta(p);

  statusEl.textContent = 'Click a point on the board to guess.';
  statusEl.className = 'status';
  noteBox.hidden = true;
  noteText.textContent = '';
  overrideBtn.hidden = true;
  editBtn.hidden = true;
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

// A position usually has more than one good move, and these are the
// ones this problem actually knows about: the other lines you played
// out, KataGo's pick when your note named a different move, and any you
// accepted yourself with "Edit card".
function isCorrect(p, guess) {
  return same(guess, p.best) || (p.alternatives || []).some(alt => same(guess, alt));
}

function drawMarks(p, guess) {
  const best = p.best;
  const played = p.played;
  const alternatives = p.alternatives || [];
  const playedAccepted = alternatives.some(a => same(a, played));

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
    // The move actually played can itself be accepted (a newer network
    // may rate it fine), so say so rather than hide the '=' under the P.
    markPoint(played[0], played[1], p.boardSize, playedAccepted ? 'P=' : 'P', 'mark-played');
  }
  if (guess && !same(guess, best)) {
    markPoint(guess[0], guess[1], p.boardSize, '?', 'mark-guess');
  }
}

// Your own diagnosis, in your own words -- the reason this position is
// in the deck at all, and worth more than the marked point.
function showNote(p) {
  noteText.textContent = p.note || '';
  noteBox.hidden = !p.note;
}

function reveal(p, guess) {
  const best = p.best;
  const correct = isCorrect(p, guess);

  drawBoard(p, null);
  drawMarks(p, guess);
  showNote(p);
  editBtn.hidden = false;

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
  lastGuess = [row, col];
  const correct = reveal(p, lastGuess);
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

// --- editing a card: its accepted answers and its note --------------------

function vertexOf(pt) {
  return COLUMN_LETTERS[pt[1]] + (pt[0] + 1);
}

function closeEditor() {
  draft = null;
  editPanel.hidden = true;
  editStatus.textContent = '';
  editStatus.className = 'edit-status';
}

function renderDraft() {
  const p = DATA[idx];
  drawBoard(p, onEditClick);
  if (draft.best) markPoint(draft.best[0], draft.best[1], p.boardSize, 'B', 'mark-best');
  for (const a of draft.alternatives) markPoint(a[0], a[1], p.boardSize, '=', 'mark-alt');
  // Where the move was actually played, for reference -- not an answer
  // unless you mark it as one.
  const played = p.played;
  if (played && !same(played, draft.best) && !draft.alternatives.some(a => same(a, played))) {
    markPoint(played[0], played[1], p.boardSize, 'P', 'mark-played');
  }
  raiseClickTargets();
  editAnswers.textContent =
    `Main answer: ${draft.best ? vertexOf(draft.best) : '(none)'} · also right: ` +
    (draft.alternatives.length ? draft.alternatives.map(vertexOf).join(', ') : '(none)');
}

// not accepted -> '=' -> 'B' -> not accepted. Promoting a point to 'B'
// demotes the old main answer to '=' rather than dropping it.
function onEditClick(row, col) {
  const pt = [row, col];
  if (same(pt, draft.best)) {
    draft.best = null;
  } else if (draft.alternatives.some(a => same(a, pt))) {
    draft.alternatives = draft.alternatives.filter(a => !same(a, pt));
    if (draft.best) draft.alternatives.push(draft.best);
    draft.best = pt;
  } else {
    draft.alternatives.push(pt);
  }
  editStatus.textContent = '';
  editStatus.className = 'edit-status';
  renderDraft();
}

function redrawRevealed() {
  const p = DATA[idx];
  drawBoard(p, null);
  drawMarks(p, lastGuess);
  showNote(p);
  renderMeta(p);
}

function editFailed(message) {
  editStatus.textContent = message;
  editStatus.className = 'edit-status bad';
}

async function postEdit(body) {
  try {
    const res = await fetch('/card-edit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    return await res.json();
  } catch (err) {
    return {ok: false, error: 'Could not reach the local server: ' + err.message};
  }
}

editBtn.addEventListener('click', () => {
  const p = DATA[idx];
  draft = {best: p.best, alternatives: (p.alternatives || []).slice()};
  editNote.value = p.note || '';
  editPanel.hidden = false;
  renderDraft();
});

document.getElementById('editCancelBtn').addEventListener('click', () => {
  closeEditor();
  redrawRevealed();
});

document.getElementById('editSaveBtn').addEventListener('click', async () => {
  const p = DATA[idx];
  if (!draft.best) {
    editFailed(draft.alternatives.length
      ? 'Pick a main answer: click one of the = points again to make it B.'
      : 'A card needs at least one answer: click a point.');
    return;
  }
  const note = editNote.value.trim();
  const body = await postEdit({
    problemId: p.id, best: vertexOf(draft.best),
    alternatives: draft.alternatives.map(vertexOf), note, boardSize: p.boardSize,
  });
  if (!body.ok) { editFailed('Not saved: ' + body.error); return; }
  p.best = draft.best;
  p.alternatives = draft.alternatives;
  p.note = note;
  if (body.noteVertices) p.noteVertices = body.noteVertices;
  p.edited = true;
  closeEditor();
  redrawRevealed();
  lizzieStatusEl.textContent = 'Card saved to card_edits.json ✓';
});

document.getElementById('editResetBtn').addEventListener('click', async () => {
  const p = DATA[idx];
  const body = await postEdit({problemId: p.id, reset: true});
  if (!body.ok) { editFailed('Not reset: ' + body.error); return; }
  p.best = p.orig.best;
  p.alternatives = p.orig.alternatives.slice();
  p.note = p.orig.note;
  p.noteVertices = p.orig.noteVertices;
  p.edited = false;
  closeEditor();
  redrawRevealed();
  lizzieStatusEl.textContent = 'Card reset to its harvested answer and note ✓';
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
  // Typing a note must not skip to the next card on Space or Enter.
  if (e.target.tagName === 'TEXTAREA' || draft) return;
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

// A new set is picked by the server -- it re-reads your games, so comments
// added since this page loaded show up -- and written over quiz.html; the
// page then reloads into it. "Next set" is what spaced repetition says is
// due; "Practice set" is any card, worst first, skipping ones already shown
// this sitting.
async function newSet(ignoreDue) {
  const statusEl = document.getElementById('newSetStatus');
  const buttons = ['nextSetBtn', 'practiceSetBtn'].map(id => document.getElementById(id));
  buttons.forEach(b => b.disabled = true);
  statusEl.classList.remove('bad');
  statusEl.textContent = 'Picking the next set…';
  try {
    const res = await fetch('/new-set', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ignoreDue}),
    });
    const body = await res.json();
    if (!body.ok) throw new Error(body.error);
    if (body.count === 0) {
      statusEl.textContent = ignoreDue
        ? 'No cards left to practise.'
        : 'Nothing else is due right now. Try a practice set.';
      buttons.forEach(b => b.disabled = false);
      return;
    }
    location.replace('/quiz.html?set=' + Date.now());
  } catch (err) {
    statusEl.classList.add('bad');
    statusEl.textContent = 'Could not start a new set: ' + err.message;
    buttons.forEach(b => b.disabled = false);
  }
}
document.getElementById('nextSetBtn').addEventListener('click', () => newSet(false));
document.getElementById('practiceSetBtn').addEventListener('click', () => newSet(true));

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
  document.getElementById('nextSetBtn').hidden = true;
} else {
  renderProblem();
}
</script>
</body>
</html>
"""
