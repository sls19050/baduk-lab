# A more interactive UI: LizzieYzy Next

[KaTrain](KATRAIN_UI_SETUP.md) is review/training-oriented (load a game,
step through it, read takeaways). Lizzie-family UIs are built for
*live, continuous* analysis instead — the engine keeps thinking in the
background as you place stones or hover over the board, and you watch the
winrate/score graph move in real time. That's the "more interactive"
feel.

## Which Lizzie

The original [featurecat/lizzie](https://github.com/featurecat/lizzie) is
effectively unmaintained. Use
**[LizzieYzy Next](https://github.com/wimi321/lizzieyzy-next)** instead —
it's the actively maintained fork (releases as recently as July 2026,
bundling KataGo v1.16.5 — the same version this repo's
[KATAGO_SETUP.md](KATAGO_SETUP.md) has you install) with a "bring your own
engine" build so it can reuse a KataGo install you already have instead of
bundling a second copy.

## Install

From [Releases](https://github.com/wimi321/lizzieyzy-next/releases), grab
the **`windows64.without.engine.portable.zip`** (Windows) — no installer,
just unzip anywhere and run `LizzieYzy Next.exe` from inside the extracted
folder. macOS/Linux builds on that page currently only ship as
`with-katago` bundles; if you want to point those at your own KataGo
instead of the bundled one too, the setting is in the same place described
below.

It's a self-contained Java app (bundles its own runtime under
`runtime/`), so no separate Java install is needed.

**Note:** if you launch the `.exe` from a shortcut or a different working
directory, it can fail to start with no error and no window. Run it
directly from inside its own extracted folder (double-click in Explorer
is fine; if launching from a script, set the working directory to the
folder containing the `.exe`).

## Connect it to your KataGo build

On first launch, LizzieYzy Next opens an **Engine Management** window and
asks you to paste in a command — it's a single command-line field, not
separate executable/model/config boxes. Paste this in (adjust the base
path to wherever you installed KataGo per [KATAGO_SETUP.md](KATAGO_SETUP.md);
if it also asks for a name/label, anything works, e.g. `KataGo (local)`):

```
"C:\path\to\katago\katago.exe" gtp -model "C:\path\to\katago\models\<net>.bin.gz" -config "C:\path\to\katago\default_gtp.cfg"
```

Keep the quotes exactly as shown — they matter if your path has spaces in
it (e.g. a username with a space, or a folder like "Local Dev").

**Important:** use `default_gtp.cfg`, not `analysis_example.cfg`, in that
command. Live/interactive play in LizzieYzy Next talks to KataGo over the
**GTP** protocol (with `kata-analyze` extensions) rather than the JSON
analysis-engine protocol KaTrain and baduk-lab use — those two protocols
expect different config keys (`numSearchThreads` for GTP vs
`numAnalysisThreads` / `numSearchThreadsPerAnalysisThread` for analysis),
and the wrong one fails to start with a `Could not find key '...'` error.
See the config-file table in [KATAGO_SETUP.md](KATAGO_SETUP.md#3-get-a-config-file)
if you need a refresher on which file is which.

## "analysis.cfg has been missing and has been auto generated" — expected, not an error

LizzieYzy Next actually runs **two separate KataGo processes**: the `gtp`
one you just configured (for live play/hover analysis), plus a second one
in `analysis` mode that powers its "fast whole-game analysis" feature —
the same JSON analysis-engine protocol baduk-lab/KaTrain use. That second
process looks for a config file named exactly `analysis.cfg` right next to
`katago.exe`. If you only have `analysis_example.cfg` there (the name it
ships under), LizzieYzy Next will auto-generate a working `analysis.cfg`
with sensible defaults the first time it needs one. This is a one-time,
self-healing step — not a sign anything is broken, and it won't happen
again once that file exists. You can safely leave the auto-generated file
as-is.

## First analysis will be slow once

Same as every other UI pointed at this KataGo install: the first time a
given GPU + model + config combination runs, KataGo re-tunes OpenCL
kernels (a few minutes on older GPUs), then caches it. Not a hang.

## Confirm it's using the right engine

While LizzieYzy Next is running, check from outside the app — expect to
see **two** `katago.exe` processes (one `gtp`, one `analysis`), both
pointed at your paths:

```powershell
Get-CimInstance Win32_Process -Filter "Name = 'katago.exe'" |
  Select-Object ProcessId, CommandLine | Format-List
```
