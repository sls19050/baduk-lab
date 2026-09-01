# baduk-lab

A "swing lab" for serious amateur Go players.

Professional golfers go to training facilities that measure their swing and tell
them which muscles to train. Go players have a superhuman measurement device
(KataGo) but no diagnosis or prescription layer on top of it. This project fills
that gap.

You give it a folder of your recent serious games (SGF files from KGS/OGS,
or Tygem's own `.gib` game records straight out of `Gibo/`). It
batch-analyzes them with KataGo's JSON analysis engine and produces a
single report that tells you **where your points are leaking and what to
train next**, plus a growing quiz deck of your own mistakes you can drill
with `baduk-lab review`.

## Quick start (already-set-up machine)

Once KataGo, `config.toml` (your player aliases + games folder), and the
venv are set up (see below if any of that isn't done yet), every new
terminal window still starts *without* the venv active — you must activate
it first, every time, or `baduk-lab` won't be found:

```powershell
cd path\to\baduk-lab   # wherever you cloned this repo
.venv\Scripts\Activate.ps1
```

Your prompt should now start with `(baduk-lab)` — that's the sign it
worked. If it doesn't, see **Troubleshooting** below before continuing.
Then, day-to-day:

```powershell
baduk-lab analyze                 # re-scans your Gibo folder, only pays for new games
baduk-lab review --out report --html --phase middle --limit 15
```

The `analyze` run writes `report/report.md` (the diagnosis) and updates
your problem deck; `review --html` opens a browser quiz over whatever's
due.

### Troubleshooting: `baduk-lab` / `.venv\Scripts\Activate.ps1` not recognized

- **`baduk-lab : The term 'baduk-lab' is not recognized...`** — the venv
  isn't active in *this* terminal window (activation only applies to the
  window you ran it in, not others, and not future windows). Run the
  `Activate.ps1` command above again. If your prompt already shows
  `(baduk-lab)` and it's still not found, the install may be broken — from
  the repo root, activate the venv then run `pip install -e .` again.
- **`Activate.ps1 cannot be loaded because running scripts is disabled on
  this system`** — PowerShell's execution policy is blocking it (a default
  Windows security setting, unrelated to this project). Fix once, for your
  user only:
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```
  then retry `.venv\Scripts\Activate.ps1`.
- **Don't want to activate every time?** Skip activation and call the
  tools by their full path instead:
  ```powershell
  .venv\Scripts\baduk-lab.exe analyze
  .venv\Scripts\baduk-lab.exe review --out report --html
  ```

First-time setup (a fresh machine, or if any of the above is missing) is
the rest of this README, roughly in this order:

1. [KATAGO_SETUP.md](KATAGO_SETUP.md) — GPU driver + KataGo binary/model/config.
2. [KATRAIN_UI_SETUP.md](KATRAIN_UI_SETUP.md) and/or
   [LIZZIE_UI_SETUP.md](LIZZIE_UI_SETUP.md) — optional GUIs to sanity-check
   the KataGo install and view positions.
3. [Setup](#setup) below — clone, venv, `pip install -e .`.
4. Copy [`config.example.toml`](config.example.toml) to `config.toml` and
   fill in your player handle(s) and games folder — see
   ["Skipping the flags: config.toml"](#skipping-the-flags-configtoml).
5. `baduk-lab analyze` then `baduk-lab review --html` as above.

## What it produces

Given ~8+ games, one markdown report containing:

1. **Loss distribution by game phase.** Opening (moves 1-50), middle game
   (50-150), endgame (150+). Where do you actually lose points?
2. **Mistake magnitude profile.** One 15-point blunder per game vs. thirty
   1-point leaks per game are different players needing different training.
3. **Ahead/behind behavior.** Does your move quality collapse when you are
   winning (coasting) or losing (flailing)?
4. **A personalized, drillable problem set.** Every position where you lost
   more than a threshold (default 4 points), exported as SGF files with your
   move hidden, ready to drill in KaTrain or any SGF editor. Your own
   mistakes are the best tsumego collection you will ever own. `baduk-lab
   review` turns this into an actual quiz session -- it tracks what you've
   already drilled and resurfaces missed ones sooner, so re-running
   `analyze` as new games come in adds to the deck instead of resetting it.

Planned, not in MVP:

- Time-usage diagnosis (pacing profile, byo-yomi degradation, time-quality
  correlation) using KGS `BL[]`/`WL[]` tags.
- Mistake taxonomy (direction of play vs. reading vs. timing), built on
  move-distance and fight-locality heuristics.
- Cycle-over-cycle trend tracking, so growth is visible instead of guessed at.

## What it deliberately does not do

- **No server integration / auth.** You download your own SGFs manually.
  Serious players can manage a folder.
- **No GUI.** This is a CLI that emits markdown + SGF files. Use KaTrain to
  view the extracted positions ([setup guide](KATRAIN_UI_SETUP.md)), or
  LizzieYzy Next for live/continuous analysis
  ([setup guide](LIZZIE_UI_SETUP.md)).
- **No fine-grained claims from small samples.** With 8 games, phase-level and
  magnitude-level statistics are real; "you are weak at attachments in the
  lower left" is tea-leaf reading. The report only makes claims the sample
  size supports.

## Setting up a new machine from scratch

Order matters here (e.g. after a hardware upgrade): GPU driver/CUDA before
KataGo, KataGo before either GUI, both before this repo's own install.

1. **GPU driver + KataGo binary/model/config** —
   [KATAGO_SETUP.md](KATAGO_SETUP.md). If you have an NVIDIA card and want
   the faster CUDA/TensorRT backends instead of OpenCL, that doc covers the
   extra driver-version-matching steps.
2. **A GUI to sanity-check the install** (optional but recommended before
   trusting baduk-lab's output) —
   [KATRAIN_UI_SETUP.md](KATRAIN_UI_SETUP.md) for review-oriented use, or
   [LIZZIE_UI_SETUP.md](LIZZIE_UI_SETUP.md) for live/continuous analysis
   and HumanSL.
3. **baduk-lab itself** — the Setup section below.

## Requirements

- Python 3.11+
- A working KataGo binary and neural network. If you have KaTrain installed,
  you already have both; point the config at KaTrain's copy. See
  [KATAGO_SETUP.md](KATAGO_SETUP.md) for a full walkthrough (macOS and
  Windows) if you need to install one.

## Setup

```bash
git clone https://github.com/sls19050/baduk-lab.git
cd baduk-lab
python -m venv .venv
```

Activate the virtual environment:

- macOS/Linux: `source .venv/bin/activate`
- Windows (PowerShell): `.venv\Scripts\Activate.ps1`
- Windows (cmd.exe): `.venv\Scripts\activate.bat`

Then install:

```bash
pip install -e .
```

## Usage

```bash
baduk-lab analyze ./my-games/ --player "your-name-in-sgf" --out report/
```

`--player` is matched case-insensitively as a substring against the SGF's
`PB`/`PW` tags (or `GAMEBLACKNICK`/`GAMEWHITENICK` for Tygem `.gib` files),
so your server handle is enough. Pass a comma-separated list
(`--player "handle1,handle2"`) if you've played under more than one
account/handle -- any of them counts as you.

### Skipping the flags: `config.toml`

Copy [`config.example.toml`](config.example.toml) to `config.toml` (it's
gitignored -- it holds your personal handle and folder path) and fill in
your aliases and default games folder, e.g.:

```toml
[player]
aliases = ["your-handle", "your-other-handle"]

[source]
default_folder = "C:\\Program Files (x86)\\TygemGlobal2.0\\Gibo"
```

With that in place, `baduk-lab analyze` (no arguments) scans your default
folder for both accounts. `--player`/the folder argument still override the
config file when passed explicitly. The folder is scanned recursively, so
Tygem's own `Gibo/YYYY-MM/` layout works without pointing at each month.

`--katago`/`--model`/`--config` are auto-detected in two cases, checked in
this order:

1. **This repo has its own local KataGo install** — a `katago/` folder (plus
   optionally faster `katago-cuda/`/`katago-trt/` sibling folders) sitting
   next to this repo's root, set up per [KATAGO_SETUP.md](KATAGO_SETUP.md).
   If more than one of `katago-trt/`, `katago-cuda/`, `katago/` exists,
   the fastest one present is used automatically — no flag needed either
   way.
2. **KaTrain is installed at its default macOS location**
   (`/Applications/KaTrain.app`).

Anywhere else (Windows/Linux without a local `katago/` folder in this repo,
or a KaTrain install in a custom directory), pass all three explicitly. If
you have KaTrain installed, press `F8` in it to open general settings and
check the engine command (or set `debug_level=1`) to see the exact paths it
launches KataGo with, then reuse them:

```powershell
baduk-lab analyze .\my-games\ --player "your-name-in-sgf" --out report\ `
  --katago "C:\Path\To\KaTrain\KataGo\katago.exe" `
  --model "C:\Path\To\KaTrain\KataGo\model.bin.gz" `
  --config "C:\Path\To\KaTrain\KataGo\analysis_config.cfg"
```

Outputs:

```
report/
  report.md              # the diagnosis
  problems/
    opening/*.sgf        # your personalized problem set, one SGF per
    middle/*.sgf          # mistake, grouped by game phase
    endgame/*.sgf
    index.json            # machine-readable problem list, read by `review`
    games.json            # every analyzed game's move list, read by `review --html`
  quiz_state.json         # review progress -- see "Reviewing your problem set"
  quiz.html                # generated by `review --html`, gitignored/transient
  raw/                    # cached KataGo analysis JSON per game (re-runs are free)
```

Problem filenames and IDs are derived from the source game + move number,
not sort order, so re-running `analyze` as new games come in never
renumbers or duplicates a problem you've already started reviewing -- it
only adds new ones.

## Reviewing your problem set

Two front ends, same underlying due-problem list and `quiz_state.json`
scheduling -- pick whichever fits the moment.

### Browser quiz (recommended for actually working through the deck)

```bash
baduk-lab review --out report/ --html
```

Renders `quiz.html` -- a real board for each due position, right there in
the page. Click the point you think is best, it grades instantly against
KataGo's answer, marks both your guess and the actual played/best moves,
and you hit Next (or Enter/→) to move on. No alt-tabbing to KaTrain per
problem, no manual y/n typing.

This starts a small local server (`http://127.0.0.1:<port>`) and opens
your default browser to it automatically, rather than just writing the
file for you to double-click. That's not optional flourish: every graded
answer is saved automatically -- the page POSTs it to `/quiz-state` on
that same local server, which already knows where `quiz_state.json` lives
(it's the one that just wrote it) and updates it using the same box
scheduling as the terminal flow, no file picker or manual "connect" step
needed. That POST is a same-origin fetch, which is why this needs the
local server instead of a plain `file://` page (same reason `/open-lizzie`
below does). Works in any browser; if the request ever fails (server not
reachable) the status line next to the score says so instead of silently
losing progress. Ctrl+C in the terminal once you're done to stop the
server.

**"Deep analysis in LizzieYzy"** button, on each problem: launches
whatever's configured under `[lizzieyzy] exe` in `config.toml` (see
[config.example.toml](config.example.toml)) with that problem's SGF as an
argument -- confirmed working with LizzieYzy Next, which opens straight
into the position with live analysis running, no manual file-opening.
Point it at a `lizzieyzy-next-fast/`-style build if you have one; this is
for the "let me actually dig into this position" cases, not routine
browsing.

Only one LizzieYzy instance (and one KataGo engine) is ever alive across a
whole quiz session: each click closes whatever the previous click opened
before launching the new one. This isn't a simple "close the launched
process" -- `LizzieYzy Next.exe` immediately re-execs itself into the real
windowed process, which spawns its own `katago.exe` engines as further
children, so the server tracks the launched PID and kills its entire
process tree (`taskkill /T` on Windows) before opening the next file, and
again when you Ctrl+C out of the review session. Verified this empirically
by chasing the actual parent/child process chain rather than assuming.

Browsers have no API for launching a local program directly, so the
button instead calls back into the same local server this page is already
served from (`GET /open-lizzie?path=...`), which does the launching (and
the previous-instance cleanup) on the page's behalf -- another reason this
needs the local server rather than a plain `file://` page, on top of the
File System Access requirement above. Leave `[lizzieyzy]` unset in
`config.toml` and the button still shows -- it just errors when clicked,
telling you to configure it.

### Terminal quiz

```bash
baduk-lab review --out report/
```

Walks you through whatever's due today: game, move, phase, points lost, and
the path to the SGF (open it in KaTrain -- see
[KATRAIN_UI_SETUP.md](KATRAIN_UI_SETUP.md#set-katrain-as-the-default-app-for-sgf-files)
for setting it as your default `.sgf` app so double-clicking the path
launches straight into the position). Answer whether you found the better
move yourself; it records the result the same way the browser quiz does.

### Both share

Three-tier scheduling: get a problem right and it comes back in a few days
then a couple of weeks; get it wrong and it's due again next session.
`--limit` caps a session's size (default 15, `--html` too) and
`--phase opening|middle|endgame` narrows to one phase if you want to drill
just one weakness. Progress lives in `quiz_state.json` next to the report,
so `analyze` → `review` (either front end) is meant to be a repeating loop
as your Tygem folder grows, not a one-shot report.

## Architecture

```
sgf/gib files -> loader.py -> engine.py (KataGo JSON analysis) -> metrics.py -> report.py -> quiz.py / quiz_html.py
                                          |                                          |
                                          v                                          v
                                    raw/ cache (JSON, keyed by            board.py (pure board-state
                                    SGF hash + model + visits)             replay, for quiz_html.py)
```

- `loader.py` — SGF parsing (sgfmill) and hand-rolled Tygem `.gib` parsing
  (no library exists for it; format reverse-engineered from real files and
  cross-checked against a known open-source parser). Both produce the same
  `GameRecord` per file: board size, komi, player names, result, and a flat
  `Move` list (color, coord, move number, KGS clock tags if present -- `.gib`
  doesn't carry per-move clocks in the fields read here). `color_of()`
  matches a player handle (or a list of aliases, for someone who's played
  under more than one account) against `PB`/`PW` (or the `.gib` equivalent)
  to pick which color to diagnose. `load_folder()` recurses, so Tygem's own
  `Gibo/YYYY-MM/` layout works unmodified.
- `config.py` — optional `config.toml` reader (player aliases, default games
  folder, and the LizzieYzy executable for the browser quiz's "Deep
  analysis" button) so a single-user setup doesn't need to repeat
  `--player`/the folder on every run; see
  [config.example.toml](config.example.toml).
- `engine.py` — `KataGoClient` runs `katago analysis` as a persistent
  subprocess and queries it once per game (all moves via `analyzeTurns`,
  not one query per position) over newline-delimited JSON on stdin/stdout.
  Produces one `PositionAnalysis` per position (winrate, scoreLead, top
  candidate moves), fixed to Black's perspective; `GameAnalysis.points_lost()`
  converts to the mover's perspective. Results are cached to
  `raw/<sgf-stem>.json` keyed by (SGF content hash, model, visits), so a
  folder of mostly-already-analyzed games only pays for the new ones.
- `metrics.py` — pure functions from a list of `GameAnalysis` to diagnosis
  numbers. No I/O; this is what the test suite covers. `_player_moves()`
  flattens all games into one list of the player's moves with points lost,
  phase, and perspective-corrected winrate; four functions build on it:
  `phase_loss_distribution`, `magnitude_profile`, `ahead_behind_split`,
  `problem_positions`.
- `report.py` — renders the four metric objects into `report.md` (one
  plain-language takeaway per section), `export_problem_sgfs()`, which
  writes one SGF per problem position grouped into phase subfolders — the
  game up to the mistake, plus sibling variations for what was played vs.
  KataGo's preferred move, so the answer isn't spoiled on open —
  `export_problem_index()`, a machine-readable `problems/index.json`
  mirror (including the played/best vertices) that `quiz.py`/`review`
  read without re-touching KataGo, and `export_game_records()`, a
  `problems/games.json` dump of every analyzed game's full move list, so
  `review --html` can reconstruct any problem's board without re-parsing
  the original source folder.
- `quiz.py` — review-scheduling state shared by both `review` front ends: a
  simple 3-box scheme (not full spaced repetition) keyed by each problem's
  stable `problem_id`, persisted as `quiz_state.json`. `sync_new_problems()`
  is what makes `analyze` incremental — new mistakes get added to the deck,
  existing review progress is left alone.
- `board.py` — pure Go board simulation (stone placement + capture
  removal) from a plain move-tuple list. Nothing else in the codebase
  computes actual board state; SGF export just leans on a real SGF viewer
  (KaTrain) to apply the rules on load. `quiz_html.py` needs a real
  position to render client-side, so this exists to compute one.
- `quiz_html.py` — renders `quiz.html`: a self-contained page (inline SVG
  board, no external libraries) for whatever `review --html` decides is
  due. Grading is instant and client-side (click vs. the recorded best
  vertex); if granted write access via the File System Access API it
  reimplements `quiz.py`'s exact box logic in JS to update the shared
  `quiz_state.json` live. Its "Deep analysis" button calls back into the
  local server `cli.py` starts for this page (`GET /open-lizzie?path=...`,
  handled by `_QuizRequestHandler` in `cli.py`) to launch `[lizzieyzy] exe`
  with that problem's SGF as an argument -- browsers have no API to launch
  a local program directly, so the server does it on the page's behalf,
  and keeps only one instance alive at a time by killing the previously
  launched process's entire tree (`_kill_process_tree()`, `taskkill /T` on
  Windows) before starting the next one.

## Status

Working end to end: `baduk-lab analyze` parses a folder of SGF/`.gib` files
(recursively, across configured player aliases), runs KataGo analysis
(cached per game), computes all four MVP metrics, and writes `report.md`
plus a phase-grouped problem-set SGF per flagged mistake. `baduk-lab review`
(terminal, or `--html` for a real click-to-guess quiz page) turns that
problem set into a repeatable quiz session with review-progress tracking
across runs.

## License

MIT
