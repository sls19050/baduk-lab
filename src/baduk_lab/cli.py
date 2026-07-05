"""Command-line interface.

Target usage:
    baduk-lab analyze ./my-games/ --player donghalee --out report/ \
        --katago /path/to/katago --model /path/to/model.bin.gz --visits 500
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="baduk-lab")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze a folder of SGF files")
    analyze.add_argument("folder", help="Folder containing .sgf files")
    analyze.add_argument("--player", required=True,
                         help="Your server handle (matched against PB/PW)")
    analyze.add_argument("--out", default="report", help="Output directory")
    analyze.add_argument("--katago", help="Path to katago binary")
    analyze.add_argument("--model", help="Path to neural net model")
    analyze.add_argument("--config", help="Path to analysis config")
    analyze.add_argument("--visits", type=int, default=500)

    args = parser.parse_args()
    raise SystemExit("Not implemented yet: loader -> engine -> metrics -> report")


if __name__ == "__main__":
    main()
