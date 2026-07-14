"""Command-line interface.

Target usage:
    baduk-lab analyze ./my-games/ --player donghalee --out report/ \
        --katago /path/to/katago --model /path/to/model.bin.gz --visits 500
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import metrics, report
from .engine import GameAnalysis, KataGoClient
from .loader import load_folder

logger = logging.getLogger(__name__)

# If installed, KaTrain bundles its own KataGo binary/model/config, so most
# users never need to pass --katago/--model/--config explicitly.
_KATRAIN_MAC_RESOURCES = Path("/Applications/KaTrain.app/Contents/Resources/katrain")


def _find_katrain_katago() -> tuple[Path, Path, Path] | None:
    if not _KATRAIN_MAC_RESOURCES.is_dir():
        return None
    binary = _KATRAIN_MAC_RESOURCES / "KataGo" / "katago-osx"
    config = _KATRAIN_MAC_RESOURCES / "KataGo" / "analysis_config.cfg"
    models = sorted((_KATRAIN_MAC_RESOURCES / "models").glob("*.bin.gz"))
    if not (binary.exists() and config.exists() and models):
        return None
    return binary, models[-1], config


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
    if args.command == "analyze":
        _run_analyze(args)


def _run_analyze(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    katago, model, config = args.katago, args.model, args.config
    if not (katago and model and config):
        found = _find_katrain_katago()
        if found is None:
            sys.exit("Could not find a local KataGo install. "
                     "Pass --katago/--model/--config explicitly.")
        katago = katago or found[0]
        model = model or found[1]
        config = config or found[2]

    folder = Path(args.folder)
    records = load_folder(folder)
    if not records:
        sys.exit(f"No SGF files found in {folder}")

    out_dir = Path(args.out)
    cache_dir = out_dir / "raw"

    analyses: list[GameAnalysis] = []
    with KataGoClient(Path(katago), Path(model), Path(config), visits=args.visits) as client:
        for record in records:
            if record.color_of(args.player) is None:
                logger.warning("Skipping %s: %r not found as a player",
                              record.path.name, args.player)
                continue
            logger.info("Analyzing %s...", record.path.name)
            analyses.append(client.analyze_game(record, cache_dir=cache_dir))

    if not analyses:
        sys.exit(f"No games in {folder} feature {args.player!r} as a player")

    phase_loss = metrics.phase_loss_distribution(analyses, args.player)
    magnitude = metrics.magnitude_profile(analyses, args.player)
    ahead_behind = metrics.ahead_behind_split(analyses, args.player)
    problems = metrics.problem_positions(analyses, args.player)

    report_path = report.render_report(
        out_dir, player=args.player, analyses=analyses, phase_loss=phase_loss,
        magnitude=magnitude, ahead_behind=ahead_behind, problems=problems,
        model=str(model), visits=args.visits,
    )
    report.export_problem_sgfs(problems, out_dir / "problems", analyses=analyses)

    logger.info("Report written to %s", report_path)


if __name__ == "__main__":
    main()
