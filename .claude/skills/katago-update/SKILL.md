---
name: katago-update
description: Check whether the installed KataGo engine and neural net are behind what's published, and install the strongest net when they are. Use this whenever the user asks about KataGo versions or updates, a new or stronger net, their weekly update check, what Elo their net is, whether they're on the latest KataGo, or says something like "anything new for katago" / "is my net current" / "check for updates". Also use before blaming the engine for weak or odd analysis, since an old or unrated net is a likely cause.
---

# Checking KataGo for updates

The user runs KataGo from `katago/` in this repo, driven by LizzieYzy Next
and by `baduk-lab` itself. They want the strongest available setup and they
check roughly weekly, so the job is usually "tell me if there's anything
worth taking", and only sometimes "install it".

Two things move independently and you check both:

- **The engine** (`katago.exe`) -- new releases bring speed and backend
  changes. Rare, a few per year.
- **The net** (`katago/models/*.bin.gz`) -- new ones are uploaded every week
  or two, and most are *not* upgrades. This is where the judgement lives.

## Run the check

```bash
cd "C:/Users/sls19/OneDrive/Documents/local-dev/baduk-lab"
.venv/Scripts/python.exe .claude/skills/katago-update/scripts/check_updates.py
```

It reads the installed engine and nets, fetches the GitHub releases and the
katagotraining ratings table, and prints a verdict for each. It changes
nothing, so it is always safe to run.

`baduk-lab` is not on PATH and the venv is not active in your shell -- call
`.venv/Scripts/python.exe` directly and don't bother with `Activate.ps1`,
which won't survive to your next call. Plain `python` also works here; the
script is stdlib-only.

Relay the verdict in a sentence or two. The user asked a yes/no question and
mostly wants the answer, not the table.

## Reading the net verdict

The ratings page names two different nets at the top and taking the wrong one
makes the setup weaker:

- **"Latest network"** is just the newest upload. It is often rated on few
  games, and frequently weaker than nets from weeks earlier.
- **"Strongest confidently-rated network"** is the one to install.

The script already prefers the strongest and prints the latest only for
context, so trust its verdict over a net's name or date. In particular the
step count in the filename (`s12382M`) is **not** a proxy for strength:
`s12752M` rates 14480 while the lower-step `s12382M` rates 14642. Sorting by
steps, or by upload date, or by mtime all pick a weaker net. This is the same
reason `_NET_ELO` in `src/baduk_lab/cli.py` exists -- a rating lives on the
server and cannot be read out of the `.bin.gz`.

A `hold` verdict is a real answer, not a failure. Elo intervals on that page
are two sigma, so nets within ~15 Elo of each other are not meaningfully
apart, and swapping costs a 260MB download, a config edit, and a new set of
unfamiliar blind spots. Tell the user it's noise and to check again next week.

Worth saying out loud when it applies: a net that currently rates below the
installed one may overtake it as its rating settles on more games. That makes
"nothing to do today" different from "nothing is coming", and the user plans
their week around the difference.

## Installing a net

Only after the script says UPGRADE AVAILABLE. Download and verify first:

```bash
.venv/Scripts/python.exe .claude/skills/katago-update/scripts/check_updates.py \
  --download <net-name>
```

It lands in `katago/incoming/` -- deliberately not `models/`, so a half-
finished download is never mistaken for an installed net. The download is
~260MB and takes a few minutes, so run it in the background.

The script checks the byte count against `Content-Length`, decompresses the
whole file, and confirms the net's name embedded in its own header. All three
matter because a corrupt net often *loads* and then just plays badly, which
is miserable to debug later from the symptom.

Then, in this order:

**1. Move it in and prove it runs on the GPU** -- before touching any config,
while the old net is still in place as a fallback:

```bash
mv katago/incoming/<net>.bin.gz katago/models/
cd katago && ./katago.exe benchmark -model models/<net>.bin.gz \
  -config default_gtp.cfg -v 400 -t 24
```

Read the header lines: the model name, `useFP16 = true`, and on their RTX
5070 a tensor-core flash attention kernel. Expect roughly **950 visits/s** --
if it's far below that, something regressed and is worth investigating before
you go further. The benchmark also re-tests thread and batch settings and
reports whether the current ones still win, which is free tuning advice.

**2. Record the Elo** in `_NET_ELO` in `src/baduk_lab/cli.py`. Without this
the net sorts as unrated and `_pick_best_net` keeps choosing the old one, so
skipping this step silently undoes the upgrade. Keep the dict in descending
Elo order, and verify the pick while both nets are still present:

```bash
.venv/Scripts/python.exe -c "
from pathlib import Path
import sys; sys.path.insert(0,'src')
from baduk_lab.cli import _pick_best_net
m=sorted(Path('katago/models').glob('*.bin.gz'))
print('picked:', _pick_best_net(m).name)
"
```

**3. Repoint LizzieYzy**, which stores the full model path once per engine
slot in
`lizzieyzy-next/LizzieYzy Next/user-data/config.txt` -- 18 copies at the time
of writing, so count the occurrences before and after rather than assuming.
Check first that LizzieYzy isn't running (`tasklist | grep -i lizzie`); it
rewrites this file on exit and would undo the edit.

**4. Then remove the old net** -- last, once the new one has proven itself.
The user is generally happy to have old kata1 nets deleted, but ask if they
haven't said so, since re-downloading is 260MB.

Leave `b18c384nbt-humanv0.bin.gz` alone. It lives under
`user-data/human-sl-models/`, it is the human-SL net rather than a stale
kata1 net, and the `gtp_human_*.cfg` profiles stop working without it.

Finally, run the tests (`.venv/Scripts/python.exe -m pytest -q`) and **leave
the repo uncommitted** unless the user asks. There is usually unrelated
work-in-progress in the tree, and sweeping it into a "update net" commit is
not yours to do. Show them the `cli.py` diff instead.

## Engine upgrades

Rarer, and the version number is the easy part -- the real question is *which
build*, because there is one per CUDA/cuDNN combination and the fast choice
has changed between releases. Read the new release's notes before downloading
and follow what they recommend rather than pattern-matching the old install.

As of v1.18.2 the state of play is:

- CUDA + cuDNN beats TensorRT on the transformer (`tf3`) nets on recent GPUs,
  which reverses older advice.
- cuDNN must be **>= 9.8**; the 8.9.7 builds are drastically slower on
  transformers and exist only for continuity.
- The user is on `cuda12.8-cudnn9.8.0-windows-x64`, which is the right build
  for their RTX 5070. A `cuda13.2` build also exists if a future release makes
  it the faster one.

Upgrading means replacing the executable and its DLLs in `katago/` while
keeping `models/`, the `*.cfg` files and the log folders. The `.cfg` files
carry the user's tuning, so never overwrite them with the ones from the zip --
diff instead, and only mention a new option if a release note calls for it.

## Gotchas

- **Python and MSYS paths.** The Bash tool gives paths like `/c/Users/...`,
  which `python -c` cannot open. Pass Windows paths (`r'C:\Users\...'`) to
  Python, or let the script resolve its own defaults.
- **Everything lives in OneDrive.** A 260MB net starts syncing as soon as it
  lands in `models/`, which is why the download goes to `incoming/` and gets
  verified before it moves.
- **Ratings drift between runs.** The same net reads 14642.6 one hour and
  14642.4 the next as rating games accumulate. Don't treat a small change as
  a finding, and re-read the page rather than quoting a number from memory.
- **Rate limits.** The unauthenticated GitHub API allows 60 requests an hour,
  which is ample for a weekly check but will bite if you loop on it.
