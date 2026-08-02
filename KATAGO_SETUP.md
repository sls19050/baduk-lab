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
| **CUDA** | Fastest on NVIDIA GPUs, but you must match the release's CUDA/cuDNN version to what's installed on your machine. Windows/Linux only. See [CUDA and TensorRT setup](#cuda-and-tensorrt-setup-nvidia-gpus) below. |
| **Eigen** | CPU-only, no GPU required. Much slower — fine for testing, painful for analyzing many games. |

- **macOS:** download the macOS build (OpenCL) and unzip it.
- **Windows:** download the OpenCL `.zip` unless you specifically want CUDA
  and know your installed CUDA/cuDNN versions match a listed build. Unzip
  it anywhere (e.g. `C:\KataGo\`).

### CUDA and TensorRT setup (NVIDIA GPUs)

Skip this if you're using the OpenCL build — it needs no separate runtime.
CUDA and TensorRT are both faster than OpenCL on NVIDIA cards, but need
extra components installed and version-matched *before* KataGo will even
start — a mismatch fails immediately with a DLL-load error, not a slow run.

**CUDA:**

1. Install/update your NVIDIA display driver first (GeForce Experience, or
   the standalone driver from [nvidia.com/drivers](https://www.nvidia.com/drivers)).
   Confirm it's active — `nvidia-smi` in a terminal should print your GPU
   and driver version.
2. Check the **exact CUDA and cuDNN versions** the KataGo CUDA release you
   downloaded expects — stated on that release's page on the
   [KataGo releases page](https://github.com/lightvector/KataGo/releases),
   not necessarily the newest CUDA available. Installing a newer CUDA than
   the release supports is the most common cause of the DLL-load failure.
3. Install the matching [CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit-archive)
   version.
4. Install the matching [cuDNN](https://developer.nvidia.com/cudnn) version
   (requires a free NVIDIA Developer account). Copy its DLLs into the CUDA
   Toolkit's `bin` folder, or directly next to `katago.exe` — either
   location works as long as they end up next to the binary or on `PATH`.
5. Run the same verification as the OpenCL build (step 5 below). The first
   run autotunes cuBLAS/cuDNN kernels the same way OpenCL autotunes — a
   few minutes once, cached afterward.

**TensorRT** (optional, NVIDIA RTX 20/30/40/50 series only, faster still
than CUDA): needs the TensorRT SDK installed and matched to your CUDA
version on top of the above — more setup for more speed. If you're running
LizzieYzy Next, its **KataGo Auto Setup** wizard (see
[LIZZIE_UI_SETUP.md](LIZZIE_UI_SETUP.md#katago-auto-setup-and-humansl))
detects your GPU and can install/manage TensorRT for you under "NVIDIA GPU
speed" — the easier path if you mainly use LizzieYzy Next. For
baduk-lab/KaTrain (manual installs), follow KataGo's own TensorRT notes on
the release page instead; it's not required — OpenCL/CUDA is plenty for
baduk-lab's batch analysis use case.

### Windows: getting the CUDA/cuDNN DLLs without the NVIDIA installer

The official path above (install the CUDA Toolkit, install cuDNN, copy
DLLs) works, but both installers are large, need admin/UAC elevation, and
cuDNN's direct download is gated behind an NVIDIA Developer account login.
There's a lighter-weight route for just the **runtime DLLs** KataGo
actually needs (no compiler, no dev headers, no login): NVIDIA publishes
them as ordinary pip wheels, and a wheel is just a zip — you don't even
need to `pip install` anything, just download and unzip.

1. Find the KataGo Windows CUDA build you want on the
   [releases page](https://github.com/lightvector/KataGo/releases) — the
   filename tells you the exact versions to match, e.g.
   `katago-v1.17.1-cuda12.8-cudnn9.8.0-windows-x64.zip` means CUDA 12.8 and
   cuDNN 9.8.0.
2. Download the matching wheels from PyPI (substitute the versions from
   step 1): `nvidia-cuda-runtime-cu12`, `nvidia-cublas-cu12`,
   `nvidia-cudnn-cu12`, and `nvidia-cuda-nvrtc-cu12` (NVRTC isn't in the
   KataGo filename but the CUDA/TensorRT backend needs it at runtime
   anyway — a `nvrtc64_120_0.dll: cannot open shared object file` error at
   startup means this one's missing). Check available versions at
   `https://pypi.org/project/<package-name>/#history`, then grab the
   Windows wheel — either `pip download <package>==<version>` into a scratch
   folder, or fetch the `.whl` URL directly from that version's page (it's
   the file ending `-win_amd64.whl`).
3. Each `.whl` is a zip with the DLLs under `nvidia/<component>/bin/`.
   Extract just those and copy them next to `katago.exe`.

**TensorRT is the exception** — unlike CUDA/cuBLAS/cuDNN/NVRTC, the actual
TensorRT libraries are *not* published as real Windows wheels on PyPI (the
`tensorrt-cu12`/`tensorrt-cu13` packages exist, but the sub-package holding
the actual `.dll`s — `tensorrt-cu12-libs` — only ships a stub source
distribution for Windows, no prebuilt wheel). For TensorRT specifically you
do need the manual, login-gated download:

1. Go to [developer.nvidia.com/tensorrt/download](https://developer.nvidia.com/tensorrt/download),
   log in, and accept the license.
2. Click through to **"TensorRT 10"** (KataGo's TensorRT builds target the
   10.x line — don't grab 11 unless you've confirmed a matching KataGo
   release exists).
3. Pick the **GA version matching the CUDA version** of the KataGo TensorRT
   build you want — e.g. `katago-v1.17.1-trt10.9.0-cuda12.8-windows-x64.zip`
   pairs with **TensorRT 10.9 GA**. Reuse whichever CUDA version you
   already have the runtime DLLs for (previous section) rather than
   chasing the newest TensorRT — a newer TensorRT usually means a newer
   CUDA pairing too, which means redownloading the CUDA runtime wheels
   as well, for a marginal gain.
4. Download the **Windows, ZIP** package (not the tar/deb variants).
5. Extract it; the DLLs you need are under `lib/` (`nvinfer_10.dll`,
   `nvinfer_plugin_10.dll`, `nvonnxparser_10.dll`, and a few more) — copy
   all of `lib/*.dll` next to `katago.exe`.

### A missing-DLL gotcha on recent Windows KataGo builds

KataGo builds compiled with newer MSVC tooling can fail to start with
`STATUS_DLL_NOT_FOUND` (PowerShell: silent exit code `-1073741515`; a
POSIX-style shell will instead name the actual missing file, e.g.
`error while loading shared libraries: api-ms-win-crt-utility-l1-1-0.dll`)
even on an up-to-date Windows install, because the Universal CRT "API set"
forwarder DLLs aren't resolving even though `ucrtbase.dll` itself is
present. Fix: copy the actual files from
`C:\Windows\System32\downlevel\api-ms-win-crt-*.dll` to next to
`katago.exe` (they exist on disk, they're just not resolving via the
normal apiset lookup for some reason). This sidesteps needing to install/
repair the Visual C++ Redistributable.

### Recommended layout: one folder per backend

If you're setting up more than one backend (e.g. keeping OpenCL as a
fallback while trying CUDA/TensorRT), don't overwrite in place — put each
build in its own sibling folder (`katago/`, `katago-cuda/`, `katago-trt/`)
so you can always fall back and A/B benchmark. Only the binary and its
backend-specific DLLs differ between them; copy the same `models/`,
`analysis.cfg`, and `default_gtp.cfg` into each folder so every build is
self-contained (needed for tools like LizzieYzy Next's Auto Setup, which
expects `analysis.cfg` to sit right next to whichever `katago.exe` you
point it at — see
[LIZZIE_UI_SETUP.md](LIZZIE_UI_SETUP.md#katago-auto-setup-and-humansl)).
baduk-lab's own CLI auto-detects this layout and prefers `katago-trt/` >
`katago-cuda/` > `katago/` automatically (see [README.md](README.md#usage)).

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
