# Setting up KataGo for baduk-lab

baduk-lab doesn't bundle KataGo — you point it at a KataGo binary, a neural
net model, and an analysis config file via `--katago`/`--model`/`--config`.
This doc covers getting those three files on macOS and Windows.

If you already have [KaTrain](https://github.com/sanderland/katrain)
installed, you likely already have all three (see "Reuse an existing
KaTrain install" below). Otherwise, install KataGo directly.

## Option A: Reuse an existing KaTrain install

KaTrain bundles a KataGo binary, config, and one or more neural nets so it
works out of the box. If you already have KaTrain, you don't need a
separate install.

- **macOS:** KaTrain's default install is `/Applications/KaTrain.app`, with
  KataGo at `Contents/Resources/katrain/KataGo/`. baduk-lab auto-detects
  this path — you don't need to pass `--katago`/`--model`/`--config` at all.
- **Windows:** the KaTrain installer lets you pick any install directory,
  so there's no fixed path baduk-lab can guess. Find yours: open KaTrain,
  press `F8` for general settings, and look for the KataGo executable path
  (or set `debug_level = 1` in `katrain.cfg` and check the startup log for
  the exact command it runs). The files are typically together in a
  `KataGo/` subfolder of wherever KaTrain was installed/extracted:
  `katago.exe`, `analysis_config.cfg` (or `katrain.cfg`), and a `models/`
  folder containing `*.bin.gz` or `*.txt.gz` net files.

**Check the version before relying on it.** Older KaTrain bundles (roughly
before mid-2020) shipped KataGo versions whose `analysis` subcommand had a
different CLI than baduk-lab expects — notably an old required
`-analysis-threads` flag that later versions dropped in favor of a
`numAnalysisThreads` config setting. Run:

```
katago.exe version
```

If this reports anything older than roughly v1.6, don't wire it into
baduk-lab — install fresh instead (Option B). A quick compatibility check:

```
katago.exe analysis -config <config> -model <model>
```

should start and wait for JSON input on stdin without printing a
`PARSE ERROR` about missing arguments. If it does print a parse error,
the bundled binary predates the CLI baduk-lab uses.

## Option B: Fresh KataGo install

### 1. Download the binary

Get the latest release from the
[KataGo releases page](https://github.com/lightvector/KataGo/releases).
Pick the build that matches your hardware:

| Backend | When to use it |
|---|---|
| **OpenCL** | Works on almost any semi-modern GPU (NVIDIA, AMD, Intel) without matching driver versions exactly. Good default, especially on older or lower-VRAM GPUs. This is what most Mac installs use, since macOS has no CUDA. |
| **CUDA** | Fastest on NVIDIA GPUs, but you must match the release's CUDA/cuDNN version to what's installed on your machine. Windows/Linux only. |
| **Eigen** | CPU-only, no GPU required. Much slower — fine for testing, painful for analyzing many games. |

- **macOS:** download the macOS build (OpenCL) and unzip it.
- **Windows:** download the OpenCL `.zip` unless you specifically want CUDA
  and know your installed CUDA/cuDNN versions match a listed build. Unzip
  it anywhere (e.g. `C:\KataGo\`).

### 2. Download a neural net

Get a model from [katagotraining.org/networks](https://katagotraining.org/networks/kata1/).
Larger nets (more blocks/channels) are stronger but slower and need more
VRAM. For a GPU with 3-4GB VRAM, stick to a smaller/mid net; 8GB+ can
handle larger ones comfortably. The file is a single `.bin.gz` (or, for
very old versions, `.txt.gz`) — save it next to the binary.

### 3. Get a config file

The release archive ships **two different config files** — grab the right
one for what you're doing, they are not interchangeable:

| File | Used by | Key setting |
|---|---|---|
| `analysis_example.cfg` | baduk-lab, KaTrain — anything using KataGo's JSON analysis engine (`katago analysis`) | `numAnalysisThreads` / `numSearchThreadsPerAnalysisThread` |
| `default_gtp.cfg` | Lizzie-family UIs ([LIZZIE_UI_SETUP.md](LIZZIE_UI_SETUP.md)) — anything using GTP (`katago gtp`) | `numSearchThreads` |

Passing the wrong one to the wrong subcommand fails immediately with
`Could not find key '...' in config file` — that's the tell if you mix
them up. Copy whichever you need as-is to start; the defaults are
reasonable and each documents its own settings inline.

### 4. First run: verify + tune

**Skip the `benchmark` subcommand** — despite being what KataGo's own
`README.txt` suggests first, it requires `numSearchThreads`, which only
`default_gtp.cfg` has; running it against `analysis_example.cfg` fails
with `Could not find key 'numSearchThreads' in config file`. You don't
need it anyway: OpenCL tuning for a given GPU + model combination happens
automatically the first time you run *any* subcommand against that pair,
including the actual `analysis` verification below — so that single step
both tunes and confirms the install works.

### 5. Verify the analysis engine specifically

baduk-lab uses `katago analysis`, not `katago gtp` or `benchmark`. Confirm
it starts cleanly:

```bash
katago.exe analysis -config <analysis_example.cfg> -model <model>.bin.gz
```

The first run against a new GPU + model pair spends a few minutes
autotuning OpenCL kernels — you'll see `Tuning xGemmDirect...` /
`Tuning xGemm...` progress lines scroll by. That's normal, not a hang, and
is cached afterward (under `KataGoData/opencltuning/` next to the binary)
so it's fast every time after. Once tuning finishes it should hang waiting
for input on stdin (correct — it's an interactive JSON protocol). Ctrl+C
to exit. If you instead see a `PARSE ERROR` immediately, your KataGo
build/CLI is mismatched (see the version-check note in Option A). If your
GPU drivers are missing or too old, tuning fails outright — OpenCL/CUDA
runtime must be installed separately from KataGo itself, it isn't bundled.

## Wiring it into baduk-lab

```bash
baduk-lab analyze ./my-games/ --player "your-name-in-sgf" --out report/ \
  --katago /path/to/katago \
  --model /path/to/model.bin.gz \
  --config /path/to/analysis_config.cfg
```

On macOS, if KaTrain is installed at its default location, these three
flags can be omitted — see [README.md](README.md#usage).
