# A GUI for testing your KataGo install: KaTrain

baduk-lab itself is a headless CLI — no board to click on. To actually *see*
KataGo analyze positions (and sanity-check a KataGo install before pointing
baduk-lab at it), you want a GUI on top of the same engine.

## Recommendation: KaTrain

[KaTrain](https://github.com/sanderland/katrain) over the alternatives:

| Option | Why / why not |
|---|---|
| **KaTrain** (recommended) | Built specifically around KataGo — live winrate/score graph, move-quality coloring, review mode. Easiest to configure to use a specific external KataGo build (one settings screen). Actively maintained. |
| Sabaki | More flexible (any GTP engine, not just KataGo) but more manual setup, and its analysis UI is thinner. Good if you want a general-purpose SGF editor. |
| Lizzie | Historically popular but the original is unmaintained with long-standing bugs; only use a maintained fork (e.g. LizzieYzy) if you specifically want its overlay style. |

Given baduk-lab is already KataGo-specific, KaTrain is the natural pairing.

## Install

- **macOS:** download the `.dmg` from the
  [KaTrain releases page](https://github.com/sanderland/katrain/releases)
  and drag it to Applications, or `pip install katrain` if you prefer a
  Python install.
- **Windows:** download `KaTrain.exe` from the same
  [releases page](https://github.com/sanderland/katrain/releases). It's a
  standalone build (~220MB, PyInstaller bundle) — no installer, just run it
  directly from wherever you save it.

The standalone build ships with its own bundled KataGo binary + neural net
under the hood, so it works immediately with no configuration. That's fine
if you just want a GUI. If you *specifically* want it exercising the same
KataGo build you set up via [KATAGO_SETUP.md](KATAGO_SETUP.md) — e.g. to
confirm that exact install works before pointing baduk-lab at it, or just
to avoid a second ~100MB+ copy of the neural net sitting on disk — point it
there explicitly (next section).

## Point KaTrain at a specific KataGo build

1. Launch KaTrain, press **F8** to open General settings.
2. Under the engine section, set:
   - **KataGo executable** → full path to your `katago`/`katago.exe`
   - **Model** → full path to your `.bin.gz` net
   - **Config** → full path to your analysis config (e.g. `analysis_example.cfg`)
3. Close the settings dialog. KaTrain restarts its engine process with the
   new paths.

Example values (Windows, matching the layout from KATAGO_SETUP.md):

```
KataGo executable: C:\path\to\katago\katago.exe
Model:             C:\path\to\katago\models\<net>.bin.gz
Config:            C:\path\to\katago\analysis_example.cfg
```

On macOS the same three fields take POSIX paths, e.g.
`/Users/you/katago/katago`.

These are stored in KaTrain's own config file
(`~/.katrain/config.json` on macOS/Linux,
`%USERPROFILE%\.katrain\config.json` on Windows) under the `"engine"` key,
if you'd rather edit it directly than use the F8 dialog — close KaTrain
first, since it rewrites this file on exit.

## Confirm it's actually using your build

Set `"debug_level": 1` under `"general"` in `config.json` (or the
equivalent in-app debug setting) and relaunch. KaTrain logs the exact
command line it uses to start the engine, so you can confirm it's your
binary/model/config and not a fallback. Set it back to `0` afterwards —
it's noisy.

You can also check from outside KaTrain while it's running: on Windows,

```powershell
Get-CimInstance Win32_Process -Filter "Name = 'katago.exe'" |
  Select-Object ExecutablePath, CommandLine
```

should show your paths in the command line.

## Why analysis looks shallow when you open a game

KaTrain doesn't run full analysis on every move by default when loading a
game — it runs a fast, low-visit pass just to color-code move quality and
populate the graph quickly, then only goes deeper if asked. The relevant
settings, in the same `"engine"` block of `config.json` as above:

```
fast_visits: 25    ← used for the automatic pass when you open/load a game
max_visits:  500    ← used for "deeper analysis" on a specific move (press 'A')
max_time:    8.0    ← hard cap in seconds per position, regardless of visits
```

25 visits (the default) is genuinely shallow. Two options, not mutually
exclusive:

1. Raise `fast_visits` (F8 → Engine settings) so the automatic whole-game
   pass is deeper from the start.
2. Use KaTrain's **"Analyze all moves"** menu option after loading a game
   to explicitly re-analyze the whole game at a visit count you choose,
   rather than relying on the quick pass.

**Don't just max it out.** Setting `fast_visits` to `500` (matching
`max_visits`) means *every* move in the game gets a full search the moment
you load it — on a slower/older GPU this makes loading a game painfully
slow, since `max_time = 8.0` lets each move take up to 8 full seconds. On
a GTX 1060 3GB with the `b18c384nbt` net from KATAGO_SETUP.md, 500 was
noticeably too slow in practice. Pick a middle value (100-150 is a
reasonable starting point) and adjust based on how it actually feels on
your hardware — there's no universally correct number, it's a function of
your specific GPU + net + `max_time`.

## Set KaTrain as the default app for .sgf files

- **Windows:** right-click any `.sgf` file → **Open with** → **Choose
  another app** → pick `KaTrain.exe` (Browse to it if it's not listed) →
  check **Always use this app to open .sgf files**. Double-clicking a
  `.sgf` from then on launches KaTrain directly.
- **macOS:** right-click (or Cmd-click) a `.sgf` file in Finder → **Get
  Info** → under **Open with**, choose KaTrain → click **Change All...**
  to apply it to every `.sgf` file, not just this one.

If you have multiple KaTrain installs (e.g. an old bundled `.zip` version
alongside a newer standalone build), double-check you picked the one you
actually want — Windows/macOS won't distinguish them by name alone, only
by the path you browse to.

## First launch will be slow once

The first time KaTrain (or any KataGo binary) analyzes a position with a
given GPU + model + OpenCL combination, it re-tunes kernels for your
hardware — this can take a few minutes on older GPUs. It's cached
afterwards (under `KataGoData/opencltuning/` next to the binary, or inside
KaTrain's own data dir if using its bundled engine), so subsequent
launches are fast. This is normal, not a hang.
