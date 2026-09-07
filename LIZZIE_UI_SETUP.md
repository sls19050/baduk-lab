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

Concrete worked example, using the fastest build from a `katago-trt/` +
`katago/` layout set up per
[KATAGO_SETUP.md](KATAGO_SETUP.md#recommended-layout-one-folder-per-backend)
(swap in your own base path and net filename):

```
"C:\Users\sls19\OneDrive\Documents\local-dev\baduk-lab\katago-trt\katago.exe" gtp -model "C:\Users\sls19\OneDrive\Documents\local-dev\baduk-lab\katago\models\kata1-zhizi-b40c768nbt-s11272M-d5935M.bin" -config "C:\Users\sls19\OneDrive\Documents\local-dev\baduk-lab\katago\default_gtp.cfg"
```

Using the plain `.bin` net (if you have both `.bin` and `.bin.gz` sitting
in `models/`) skips a gzip-decompress on every engine launch — free
startup time, no downside.

**Important:** use `default_gtp.cfg`, not `analysis_example.cfg`, in that
command. Live/interactive play in LizzieYzy Next talks to KataGo over the
**GTP** protocol (with `kata-analyze` extensions) rather than the JSON
analysis-engine protocol KaTrain and baduk-lab use — those two protocols
expect different config keys (`numSearchThreads` for GTP vs
`numAnalysisThreads` / `numSearchThreadsPerAnalysisThread` for analysis),
and the wrong one fails to start with a `Could not find key '...'` error.
See the config-file table in [KATAGO_SETUP.md](KATAGO_SETUP.md#3-get-a-config-file)
if you need a refresher on which file is which.

## KataGo Auto Setup and HumanSL

The manual command above only wires up the **GTP** engine used for
live/hover analysis. HumanSL (playing against or reviewing with a
human-style-rated model) and the background whole-game analysis feature
run on a *separate* engine profile that LizzieYzy Next manages itself via
a **KataGo Auto Setup** wizard — pasting the manual GTP command does not
configure this second profile, so it's easy to get regular play working
and still hit a HumanSL failure.

**Symptom if you skip this:** starting a HumanSL game fails with something
like:

```
Failed to start HumanSL engine: Cannot run program "katago" in directory
"...\human-sl-models": CreateProcess error=2. The system cannot find the
file specified.
```

That's LizzieYzy Next falling back to assuming a bundled `katago` binary
that doesn't exist in the engine-less build — not a sign anything you
already configured is broken.

**Fix:** open the **"KataGo auto setup"** menu item (also reachable via a
**"Setup"** button near the engine controls). On the **Overview** tab:

1. Click **"Choose existing KataGo"** → **"Choose the KataGo executable"**
   and browse to your `katago.exe` (same file as the manual command above).
2. Confirm it auto-detects the GTP config, analysis config, and weight
   sitting next to it. If not, use **"Choose gtp.cfg"** / **"Choose a
   KataGo weight"** to point at them directly.
3. Check the HumanSL model status on this tab (or the **Weights** tab) —
   if missing, it offers a direct download; the official model is
   `b18c384nbt-humanv0.bin.gz`.
4. Once the overview shows **"Ready to auto-configure now"** with no
   missing-engine/config/weight warnings, click **"Apply setup"**.

This writes its own engine profile and does not touch or override the
manual GTP command from the previous section — both coexist.

The same wizard's **"NVIDIA GPU speed"** tab can detect your card and
install **TensorRT** for faster analysis on RTX 20/30/40/50 series — see
[KATAGO_SETUP.md](KATAGO_SETUP.md#cuda-and-tensorrt-setup-nvidia-gpus) if
you want the manual/non-LizzieYzy equivalent for baduk-lab or KaTrain.

## TensorRT and HumanSL don't mix in one install

If you've set up a faster `katago-trt/` build per
[KATAGO_SETUP.md](KATAGO_SETUP.md#recommended-layout-one-folder-per-backend)
and pointed the KataGo Auto Setup wizard at it, you may hit a wall trying
to also use HumanSL: TensorRT can build an engine for a normal-sized
KataGo net fine, but chokes on the small HumanSL net specifically
(`b18c384nbt-humanv0.bin.gz` at time of writing).

**Symptom:** HumanSL games (or the "fast whole-game analysis" feature,
which shares the same engine profile) fail or hang, with no error dialog.
Checking the actual katago logs (`analysis_logs/` — the location depends
on LizzieYzy Next's working directory when it launched the process; search
the whole repo tree if it's not next to `katago.exe`) shows the pattern:
the main net's TensorRT engine builds fine, then it starts
`TensorRT backend: building network via ONNX emitter` for the HumanSL net
and the log just stops — no error, the process silently dies partway
through. This is reproducible every time, not a one-off timing issue.

**There's no per-feature engine switch** — HumanSL and whole-game-analysis
both read the same `katago-auto-setup-engine-path` /
`katago-auto-setup-analysis-config-path` settings, so you can't have
"TensorRT for whole-game-analysis, OpenCL for HumanSL" within one install.

**Fix: run a second, fully independent portable install.** LizzieYzy
Next's portable build has no installer and no shared system state — it's
just an unzip — so two copies coexist cleanly with zero conflict:

1. Extract the same release zip into a new sibling folder (e.g.
   `lizzieyzy-next-fast/` next to your existing `lizzieyzy-next/`).
2. **Before ever launching it**, copy your existing install's
   `user-data\config.txt` into the new folder's `user-data\` — this
   carries over your UI preferences, komi profiles, etc. as a starting
   point instead of starting from scratch.
3. While it's still never been launched (see the next section for why
   this timing matters), hand-edit these fields in the copy to point
   everywhere at your fast backend:
   - `katago-auto-setup-engine-path`
   - `katago-auto-setup-analysis-config-path`
   - `katago-auto-setup-gtp-config-path`
   - `analysis-engine-command`
   - `estimate-command`
   - each `"command"` field under `leelaz.engine-settings-list`
4. Leave HumanSL unconfigured in this new install entirely — that's the
   point of keeping it separate.

Now you have one install for HumanSL (on OpenCL/CUDA, whichever build
handles that net) and one dedicated to fast TensorRT analysis, and they
never fight over shared config.

## A manual Human SL 9d engine for Genmove mode (to get a timed clock)

The built-in **"Human-style game"** mode (the one the KataGo Auto Setup
wizard configures above) has no time-setting UI for the player at all —
fine for casual play, useless if you want to practice under a clock.
**"New game (Genmove mode)"**, by contrast, does have time settings *and*
lets you manually pick any engine from `leelaz.engine-settings-list` (the
same list the manual GTP command earlier in this doc adds to). So instead
of the built-in HumanSL feature, add a second, ordinary GTP engine entry
that plays human-style, and use it from Genmove mode.

The KataGo release archive already ships a ready-made config for exactly
this — `gtp_human9d_search_example.cfg` (next to `default_gtp.cfg` /
`analysis_example.cfg`). Unlike the raw HumanSL net alone (which does
*not* actually play at 9d strength despite the profile name — see the
comments in `gtp_human5k_example.cfg`), this one layers KataGo's own
search on top of the human-SL policy (`humanSLProfile = preaz_9d` +
`maxVisits = 400`) to actually reach roughly 9d/superhuman strength while
still biasing toward human-style moves. Copy it to a stable filename
first (the `_example` file may get overwritten if you ever re-extract a
KataGo release into the same folder):

```powershell
Copy-Item katago\gtp_human9d_search_example.cfg katago\gtp_human_9d.cfg
```

Then add an engine command that passes **both** a normal KataGo model
(`-model`, for the search) and the HumanSL net (`-human-model`, downloaded
by the Auto Setup wizard into `user-data\human-sl-models\` — reuse that
same file rather than downloading it again):

```
"C:\path\to\katago\katago.exe" gtp -model "C:\path\to\katago\models\<net>.bin" -human-model "C:\path\to\LizzieYzy Next\user-data\human-sl-models\b18c384nbt-humanv0.bin.gz" -config "C:\path\to\katago\gtp_human_9d.cfg"
```

**Use the plain OpenCL/CUDA `katago.exe`, not a `katago-trt/` build** —
same reason as the section above: TensorRT chokes silently on the small
HumanSL net. This matters even though you're adding a one-off manual
engine rather than going through the Auto Setup wizard — the failure is
about the net, not which code path launches it.

Two things that aren't bugs if you hit them:

- **The engine has to be started before you start the game**, not
  after — picking it from the dropdown and then clicking into a game in
  progress does nothing; nothing gets logged to `gtp_logs\` and it just
  silently keeps using whatever engine was already running. Select it,
  start the engine, *then* start the new game.
- **This engine ignores whatever time setting you give it** — `maxVisits
  = 400` is a fixed visit count per move (plus a random ~2-10s pacing
  delay from `delayMoveScale`/`delayMoveMax`), not a time budget, so
  Genmove mode's clock only really constrains *your* moves. That's
  usually what you want anyway (practicing under time pressure yourself
  against a fixed-strength opponent) — just don't expect the engine to
  visibly speed up or slow down if you change the time control.

To adjust strength/style, edit `katago\gtp_human_9d.cfg` directly:
`humanSLProfile` picks the imitated rank (e.g. `preaz_7d`, `rank_5d`), and
`humanSLChosenMovePiklLambda` trades strength for humanness (smaller =
weaker/more human-like, larger = stronger/more KataGo-like).

## The #1 way to make config edits vanish: editing `config.txt` while the app is open

`user-data\config.txt` is not just a settings file you edit and forget —
LizzieYzy Next periodically **rewrites the whole file from its own
in-memory state** while running (and definitely on exit). If you hand-edit
`config.txt` while the app is open, your edit is live for a little while
and then silently overwritten back to whatever the running app still has
in memory the next time it saves. There's no error, no warning — it just
looks like your fix "didn't take," which sends you back to debugging a
problem that's already fixed on disk but not in the running process.

**Rule: fully close LizzieYzy Next before hand-editing `config.txt`, and
don't relaunch until you're done.** Confirm it's actually closed first
(the `.exe` name is the same across every install, portable or not):

```powershell
Get-Process | Where-Object { $_.ProcessName -like "*Lizzie*" }
```

Empty output means it's safe to edit.

**A related trap:** `analysis-engine-command` looks like the obvious field
to edit if you want to change which `katago.exe` the analysis/HumanSL
engine uses — but it isn't actually the source of truth. LizzieYzy Next
regenerates it from `katago-auto-setup-engine-path` +
`katago-auto-setup-analysis-config-path`, so editing only
`analysis-engine-command` has no effect on the next launch; it gets
overwritten to match those other two fields regardless. Edit the
`katago-auto-setup-*` fields, not `analysis-engine-command` directly.

Whenever config.txt edits seem to not be sticking, the fastest way to cut
through the confusion is to stop trusting the file or the UI and check
what's *actually* running — see "Confirm it's using the right engine"
below. That command doesn't care what any config file claims.

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

This works the same way regardless of which install launched the process,
and reflects reality even when a config file or the UI is stale — see the
`config.txt`-clobbering trap above for why that distinction matters.

## Replacing the byoyomi countdown sounds

The countdown beeps (and the stone-placement / dead-stone-marking sounds)
aren't loose files and there's no in-app setting or external
override/theme folder for them — they're baked directly inside the app's
jar, at `app\lizzie-yzy<version>-shaded.jar` → `assets/sound/0.wav`
through `9.wav` (plus `Stone.wav`, `deadStone.wav`, `deadStoneMore.wav`).
Changing them means editing the jar itself. A jar is just a zip, so this
is more approachable than it sounds — but a few things matter:

**Format/timing constraint:** the stock beeps are mono, 22050 Hz, 16-bit
PCM, and only ~0.23 seconds each. The countdown ticks roughly once a
second, so a replacement sound needs to stay under ~1 second or it'll
still be playing when the next tick fires. This matters if you want
something more distinctive than a beep (e.g. spoken numbers, which cut
through noise-cancelling headsets much better than tones) — normal-speed
speech runs 1.3+ seconds per digit, too long.

**Generating replacements for free, offline:** Windows' built-in SAPI
text-to-speech, via PowerShell, needs no internet and no licensing
concerns:

```powershell
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice("Microsoft Zira Desktop")  # or "Microsoft David Desktop"
$synth.Rate = 4  # 0 = normal; each step speeds it up. Needed to get spoken
                 # digits under ~1 second — Rate 4 landed every 0-9 clip
                 # under 0.95s on this machine, Rate 3 left a couple over 1s.
for ($i = 0; $i -le 9; $i++) {
    $synth.SetOutputToWaveFile("C:\path\to\output\$i.wav")
    $synth.Speak("$i")
    $synth.SetOutputToNull()
}
```

`Get-InstalledVoices` on a stock Windows install typically only offers
`Microsoft David Desktop` (male) and `Microsoft Zira Desktop` (female) —
generate both and listen before committing, voice/pacing preference is
subjective. Conveniently, SAPI's default WAV output already matches the
original beeps' format (mono/22050 Hz/16-bit), so no conversion needed.

**Splicing the new files into the jar:** git-bash doesn't ship a `zip`
binary that can update entries in-place, but .NET's
`System.IO.Compression.ZipArchive` (available from any PowerShell) can, in
`Update` mode:

```powershell
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$jarPath = "C:\path\to\LizzieYzy Next\app\lizzie-yzy<version>-shaded.jar"
Copy-Item $jarPath "$jarPath.original-beeps-backup"  # back up first, always

$zip = [System.IO.Compression.ZipFile]::Open($jarPath, [System.IO.Compression.ZipArchiveMode]::Update)
try {
    for ($i = 0; $i -le 9; $i++) {
        $entryName = "assets/sound/$i.wav"
        $existing = $zip.GetEntry($entryName)
        if ($existing) { $existing.Delete() }
        $newEntry = $zip.CreateEntry($entryName)
        $bytes = [System.IO.File]::ReadAllBytes("C:\path\to\output\$i.wav")
        $stream = $newEntry.Open()
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Close()
    }
} finally {
    $zip.Dispose()
}
```

Confirm LizzieYzy Next is fully closed first (same reason as the
`config.txt` warning above — Windows will also just flat-out lock the jar
file if a running JVM has it open, so this fails loudly rather than
silently if you forget).

**A false alarm to expect afterward:** running `unzip -t` on the modified
jar reports `bad CRC` errors on every zero-byte *directory* entry (e.g.
`assets/sound/`, `META-INF/`) — this is a known cosmetic quirk of how
.NET's `ZipArchive` rewrites the central directory in `Update` mode, not
real corruption. Confirm by checking that only directory entries (paths
ending in `/`) show the warning and every actual file entry reports `OK`;
Java's own jar/zip reader doesn't validate CRCs on directory entries
anyway, so the app runs fine regardless. Launch the app afterward to
confirm rather than trusting the theory, though — that's the real test.

Keep the `.original-beeps-backup` copy — reverting to stock beeps is just
copying it back over the modified jar.
