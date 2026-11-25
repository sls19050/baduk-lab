#!/usr/bin/env python3
"""Compare the installed KataGo engine and net against what's published upstream.

Read-only by default: it touches the network and the local katago/ folder, and
changes nothing. `--download` fetches and verifies a net into a directory you
name, which is still inert -- installing it means moving the file and editing
config, and those steps need judgement, so they stay in SKILL.md.

Stdlib only, so it runs under any python on the box, venv or not.
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

GITHUB_RELEASES = "https://api.github.com/repos/lightvector/KataGo/releases"
NETWORKS_PAGE = "https://katagotraining.org/networks/kata1/"
MODEL_URL = "https://media.katagotraining.org/uploaded/networks/models/kata1/{name}.bin.gz"

# A rating needs games behind it to mean anything. katagotraining shows a fresh
# upload rated on zero games, where the interval can be +-200 Elo -- adopting
# one of those is a coin flip dressed up as an upgrade.
MIN_RATING_GAMES = 1500

# Published intervals are two sigma, so sigma is half the quoted number. Two
# nets whose ratings differ by less than the combined sigma are not meaningfully
# apart, and swapping between them is churn: a 260MB download, a config edit and
# a fresh set of blind spots, bought for noise.
MIN_WORTHWHILE_ELO = 15.0


def fetch(url: str, timeout: int = 60) -> bytes:
    # No identifying headers: this is a public endpoint and it has no business
    # knowing whose machine is asking.
    req = urllib.request.Request(url, headers={"User-Agent": "katago-update-check"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# --------------------------------------------------------------------------- #
# Installed side
# --------------------------------------------------------------------------- #

def installed_engine(katago_dir: Path) -> dict:
    exe = katago_dir / "katago.exe"
    if not exe.exists():
        exe = katago_dir / "katago"
    if not exe.exists():
        return {"error": f"no katago executable in {katago_dir}"}
    try:
        out = subprocess.run([str(exe), "version"], capture_output=True, text=True,
                             timeout=120, cwd=str(katago_dir)).stdout
    except Exception as e:                                    # noqa: BLE001
        return {"error": f"could not run {exe}: {e}"}
    got = {"raw": out.strip()}
    for key, pat in (("version", r"KataGo (v[\d.]+)"),
                     ("backend", r"Using (\w+) backend"),
                     ("cuda", r"Compiled with CUDA version ([\d.]+)")):
        m = re.search(pat, out)
        if m:
            got[key] = m.group(1)
    return got


def installed_nets(models_dir: Path) -> list[str]:
    """Net names as katagotraining lists them, i.e. the filename less .bin.gz."""
    if not models_dir.is_dir():
        return []
    return sorted(p.name[: -len(".bin.gz")] for p in models_dir.glob("*.bin.gz"))


# --------------------------------------------------------------------------- #
# Upstream side
# --------------------------------------------------------------------------- #

def latest_release() -> dict:
    rels = json.loads(fetch(GITHUB_RELEASES))
    stable = [r for r in rels if not r.get("prerelease")]
    if not stable:
        return {"error": "no stable release found"}
    r = stable[0]
    return {"tag": r["tag_name"], "name": r["name"],
            "published": r["published_at"][:10],
            "assets": [a["name"] for a in r.get("assets", [])]}


def _text(raw: bytes) -> str:
    """HTML to one whitespace-normalised line.

    Collapsing newlines matters: the ratings sit in <td>s that each span several
    source lines, so any row-oriented regex run before this quietly matches
    nothing and the whole table looks empty.
    """
    t = raw.decode("utf-8", "replace")
    t = re.sub(r"<(script|style).*?</\1>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def published_nets() -> dict:
    """Ratings table plus the two names the page calls out at the top."""
    t = _text(fetch(NETWORKS_PAGE))

    rows = {}
    # name | YYYY-MM-DD HH:MM:SS UTC | <elo> <sep> <interval> - (<n> games)
    # The separator is a plusmn that survives encoding badly, so match any
    # non-space run rather than the character itself.
    for m in re.finditer(
        r"(kata1-[\w.\-]+?)\s*\|?\s*"
        r"(\d{4}-\d{2}-\d{2}) [\d:]+ UTC\s*\|?\s*"
        r"([\d.]+)\s*\S+\s*([\d.]+)\s*-\s*\(([\d,]+) games\)", t
    ):
        name, date, elo, interval, games = m.groups()
        rows[name] = {"name": name, "uploaded": date, "elo": float(elo),
                      "interval": float(interval),
                      "games": int(games.replace(",", ""))}

    def called_out(label: str) -> str | None:
        m = re.search(label + r":?\s*(kata1-[\w.\-]+)", t)
        return m.group(1) if m else None

    return {"rows": rows,
            "latest": called_out("Latest network"),
            "strongest": called_out("Strongest confidently-rated network")}


def best_net(pub: dict) -> dict | None:
    """The strongest net that has enough games to be believed.

    Prefer the page's own 'strongest confidently-rated' label, since that is the
    site operator's judgement and it is what we actually want. Fall back to our
    own filter only if the label is missing or unrated, e.g. after a redesign.
    """
    rows = pub["rows"]
    if pub["strongest"] and pub["strongest"] in rows:
        return rows[pub["strongest"]]
    rated = [r for r in rows.values() if r["games"] >= MIN_RATING_GAMES]
    return max(rated, key=lambda r: r["elo"]) if rated else None


# --------------------------------------------------------------------------- #
# Download + verify
# --------------------------------------------------------------------------- #

def download_net(name: str, dest_dir: Path) -> int:
    """Fetch a net and prove it arrived intact. Returns a process exit code.

    Three independent checks, because a truncated or corrupt 260MB net fails in
    confusing ways much later -- KataGo may load it and play badly rather than
    error out. Checking here is far cheaper than debugging that.
    """
    url = MODEL_URL.format(name=name)
    target = dest_dir / f"{name}.bin.gz"

    req = urllib.request.Request(url, headers={"User-Agent": "katago-update-check"})
    try:
        r = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        # Nearly always a typo'd or archived net name rather than an outage, and
        # a traceback buries that.
        print(f"FAIL fetch: {url}\n            HTTP {e.code} {e.reason}")
        # The bucket answers 403 rather than 404 for an object that isn't there,
        # so don't read 'Forbidden' as a permissions problem.
        if e.code in (403, 404):
            print("            no net by that name on the kata1 run -- check "
                  "the spelling against\n            the ratings page, or look "
                  "under https://katagoarchive.org/ for older runs")
        return 1
    except Exception as e:                                    # noqa: BLE001
        print(f"FAIL fetch: {url}\n            {e}")
        return 1

    with r:
        expected = int(r.headers.get("Content-Length") or 0)
        print(f"downloading {name} ({expected / 1e6:.0f} MB) -> {target}")
        # Created only now that the net is known to exist, so a typo doesn't
        # leave an empty folder behind.
        dest_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        with open(target, "wb") as f:
            while chunk := r.read(1 << 22):
                f.write(chunk)
                written += len(chunk)

    ok = True
    if expected and written != expected:
        print(f"FAIL size: got {written}, Content-Length said {expected}")
        ok = False
    else:
        print(f"ok   size: {written} bytes matches Content-Length")

    try:
        with gzip.open(target, "rb") as f:
            header = f.read(120)
            n = len(header)
            while chunk := f.read(1 << 22):
                n += len(chunk)
        print(f"ok   gzip: decompresses cleanly, {n} bytes")
    except Exception as e:                                    # noqa: BLE001
        print(f"FAIL gzip: {e}")
        return 1

    # KataGo writes the net's own name as the first line of the model file, so
    # this catches a mirror or redirect having served the wrong net entirely.
    embedded = header.split(b"\n", 1)[0].decode("ascii", "replace").strip()
    if embedded == name:
        print(f"ok   name: file identifies itself as {embedded}")
    else:
        print(f"FAIL name: file says {embedded!r}, expected {name!r}")
        ok = False

    print(f"\n{'verified' if ok else 'NOT verified'}: {target}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def report(katago_dir: Path) -> int:
    eng = installed_engine(katago_dir)
    nets = installed_nets(katago_dir / "models")
    rel = latest_release()
    pub = published_nets()
    best = best_net(pub)

    print("== engine ==")
    if "error" in eng:
        print(f"  installed : {eng['error']}")
    else:
        extra = " ".join(f"{k} {eng[k]}" for k in ("backend", "cuda") if k in eng)
        print(f"  installed : {eng.get('version', '?')}  ({extra})")
    if "error" in rel:
        print(f"  latest    : {rel['error']}")
    else:
        print(f"  latest    : {rel['tag']}  ({rel['published']})  {rel['name']}")
        if eng.get("version") == rel["tag"]:
            print("  verdict   : up to date")
        elif eng.get("version"):
            print(f"  verdict   : UPGRADE AVAILABLE {eng['version']} -> {rel['tag']}"
                  "\n              read that release's notes before downloading; "
                  "the recommended\n              backend has changed before, "
                  "and the notes say which build to take")

    print("\n== net ==")
    if not nets:
        print(f"  installed : none found in {katago_dir / 'models'}")
    for n in nets:
        row = pub["rows"].get(n)
        if row:
            print(f"  installed : {n}"
                  f"\n              {row['elo']} +/-{row['interval']} "
                  f"({row['games']} games, uploaded {row['uploaded']})")
        else:
            print(f"  installed : {n}\n              not on the ratings page "
                  "(archived, or a special-purpose net)")

    print(f"  latest    : {pub['latest'] or '?'}   (newest upload, not "
          "necessarily strongest)")
    if not best:
        print("  strongest : could not read the ratings table -- open "
              f"{NETWORKS_PAGE} by hand")
        return 1

    print(f"  strongest : {best['name']}"
          f"\n              {best['elo']} +/-{best['interval']} "
          f"({best['games']} games, uploaded {best['uploaded']})")

    if best["name"] in nets:
        print("  verdict   : up to date -- the strongest rated net is already "
              "installed")
        return 0

    have = [pub["rows"][n]["elo"] for n in nets if n in pub["rows"]]
    if not have:
        print("  verdict   : UPGRADE AVAILABLE (installed net is unrated, so "
              "the gain is unknown)")
        return 0

    gain = best["elo"] - max(have)
    if gain < MIN_WORTHWHILE_ELO:
        print(f"  verdict   : hold -- only +{gain:.1f} Elo over what's "
              f"installed, inside the noise\n              (<{MIN_WORTHWHILE_ELO:.0f} "
              "Elo); not worth a 260MB swap. Check again next week.")
    else:
        print(f"  verdict   : UPGRADE AVAILABLE -- +{gain:.1f} Elo"
              f"\n              katago-update/scripts/check_updates.py "
              f"--download {best['name']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--katago-dir", type=Path,
                    default=Path(__file__).resolve().parents[4] / "katago",
                    help="folder holding katago.exe and models/ "
                         "(default: the repo's katago/)")
    ap.add_argument("--download", metavar="NET_NAME",
                    help="fetch and verify this net instead of reporting")
    ap.add_argument("--dest", type=Path,
                    help="where --download puts the file (default: a 'incoming' "
                         "folder beside models/, so it is not picked up as "
                         "installed until you move it)")
    args = ap.parse_args()

    if args.download:
        dest = args.dest or (args.katago_dir / "incoming")
        return download_net(args.download, dest)
    return report(args.katago_dir)


if __name__ == "__main__":
    sys.exit(main())
