---
name: quiz
description: Harvest newly reviewed games and start the baduk-lab quiz. Use when the user wants to drill their mistakes, start/restart the quiz, asks what's due, or says they just reviewed and commented on games in LizzieYzy. Also covers checking what a note resolved to and why.
---

# Starting the quiz

The user reviews games in LizzieYzy Next, commenting on moves they
misplayed, and saves them to the `AnalyzedGames` folder. `baduk-lab notes`
turns each of those comments into a quiz problem; `baduk-lab review` drills
whatever is due. There are two decks — `note` (their own comments) and
`katago` (what the engine flagged during `analyze`).

## The venv is not active in your shell

`baduk-lab` is not on PATH. Always invoke the executables directly:

```bash
cd "C:/Users/sls19/OneDrive/Documents/local-dev/baduk-lab"
.venv/Scripts/baduk-lab.exe ...
.venv/Scripts/python.exe ...
```

Do not run `Activate.ps1` — activation does not survive to your next call.

## Default: harvest, then serve

```bash
.venv/Scripts/baduk-lab.exe notes
.venv/Scripts/baduk-lab.exe review --source note --html --limit 20
```

(`quiz.ps1` in the repo root does exactly this for the user when they are
not talking to you -- keep the two in step if you change either.)

Always run `notes` first, even if the user did not mention new games — it
is cheap (no GPU, no engine; the KataGo search is already stored in each
saved SGF) and it is the only thing that picks up a game they reviewed
since the last run. It is incremental: box and due dates survive, and a
comment they moved to a different move takes its old state entry and
problem file with it.

`review --html` **blocks** (it serves the page until Ctrl+C), so run it in
the background. It prints the port it chose — read the task output for a
line like `127.0.0.1 - - [...] "GET /quiz.html"` or the startup URL, then
give the user `http://127.0.0.1:<port>/quiz.html`.

Serving matters: the page POSTs answers back to `report/quiz_state.json`,
so opening `quiz.html` as a `file://` path silently loses their progress.

Leave `--source note` off if they want both decks. Their own notes are
offered first either way.

## Nothing due, or going over a game again

Spaced repetition hides a problem once it is answered, so a run right
after a session says "Nothing due for review right now." Pass
`--ignore-due` to drill the whole deck anyway (worst-first, answers still
counted). Say which one you ran -- "everything" and "what's due" are
different sessions and the user should know which they got.

## Already running?

Check before starting a second server; two of them on different ports is
pure confusion:

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:<port>/quiz.html
```

If one is alive and the deck has changed under it, stop it and start a
fresh one rather than hand-rendering `report/quiz.html` into it -- the
running server only serves that file off disk, so a hand-render works,
but then the page's problems and the server's idea of the session differ.

## Opening the browser

The Chrome extension is often disconnected. Try `tabs_context_mcp` once;
if it fails, just give the user the URL to click rather than retrying.

## Explaining what a note resolved to

When the user doubts a problem ("this comment doesn't match the quiz"),
inspect the harvest directly rather than guessing:

```bash
.venv/Scripts/python.exe -c "
from baduk_lab import annotations
from pathlib import Path
ms = annotations.mistakes_from_sgf(Path('<sgf>'), ['828if8wz'])
for m in sorted(ms, key=lambda m: m.move_number):
    print(m.move_number, m.color, m.played, '->', m.best,
          '| alts', m.alternatives, '| names', m.note_vertices)
"
```

Three rules decide the answer, and all three have bitten before:

- **Which move a comment is about.** A comment sits on the node the user
  was looking at, which is often the move *before* the reply they are
  criticising. Resolved from the node's colour against theirs.
- **Where the answer comes from.** A line they played out while reviewing
  is saved by LizzieYzy as a *sibling* of the real game (the real game
  stays child 0). Those siblings are moves they chose themselves, so one
  their note names wins over KataGo's top move; extra ones become
  `alternatives`, which also grade as correct.
- **Note-named points are marked, never graded.** A note names the move
  they played about as often as the one they should have, so those points
  get an `N` on the board and nothing more.

A note can also be genuinely retrospective — naming a point played fifty
moves earlier. Nothing can retarget that automatically; say so plainly
instead of inventing a match.

## Adding games

Nothing to do but re-run `notes`. The folder is in `config.toml` under
`[annotations] folder`; it is scanned recursively, so subfolders are fine.
