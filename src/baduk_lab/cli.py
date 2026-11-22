"""Command-line interface.

Target usage:
    baduk-lab tidy ./my-games/
    baduk-lab analyze ./my-games/ --player donghalee --out report/ \
        --katago /path/to/katago --model /path/to/model.bin.gz --visits 500
    baduk-lab review --out report/

`folder`/`--player` fall back to config.toml (see config.example.toml) if
omitted, so a single-user setup with that file filled in can just run
`baduk-lab analyze` with no arguments.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import logging
import subprocess
import sys
import threading
import webbrowser
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import (annotations, config, drill, drill_html, metrics, quiz, quiz_html, report,
               selfplay, strength, strength_chart, tidy)
from .engine import GameAnalysis, KataGoClient
from .loader import GameRecord, load_folder

logger = logging.getLogger(__name__)

# If installed, KaTrain bundles its own KataGo binary/model/config, so most
# users never need to pass --katago/--model/--config explicitly.
_KATRAIN_MAC_RESOURCES = Path("/Applications/KaTrain.app/Contents/Resources/katrain")

# This repo's own local KataGo install (see KATAGO_SETUP.md): one CUDA build in
# katago/, holding the engine, its GPU backend DLLs, the configs and models/.
# Kept as a list so a second backend build can be dropped in alongside later.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_KATAGO_BUILDS = ["katago"]

# Published Elo ratings from https://katagotraining.org/networks/kata1/, used to
# pick the strongest net when models/ holds more than one. A rating lives on the
# training server and is not stored in the .bin.gz, so it cannot be read off the
# file -- it has to be recorded here and refreshed when a net is added.
#
# Deliberately not a step-count or mtime sort: the step number is not a proxy for
# strength. s11003M-d5973M-7gres (14606) outrates the later s12002M-d6304M
# (14596), and the four nets uploaded after s12002M all rate below it -- so both
# "highest steps" and "newest" pick a weaker net here.
#
# Only confidently-rated nets belong here. A fresh upload is rated on zero games
# (the latest can carry +-200 Elo), so an unlisted net sorts last instead of
# being adopted on a provisional number.
_NET_ELO = {
    "kata1-tf3-b11c768-s11003M-d5973M-7gres": 14606.2,
    "kata1-tf3-b11c768-s12002M-d6304M": 14596.8,
    "kata1-tf3-b11c768-s12252M-d6398M": 14565.0,
    "kata1-tf3-b11c768-s12501M-d6467M": 14548.4,
    "kata1-tf3-b11c768-s11001M-d5973M": 14531.6,
    "kata1-tf3-b11c768-s12000M-d6278M": 14530.2,
    "kata1-tf3-b11c768-s11500M-d6163M": 14526.1,
    "kata1-zhizi-b40c768nbt-s11272M-d5935M": 14523.2,
    "kata1-tf3-b11c768-s11750M-d6216M": 14518.5,
    "kata1-zhizi-b40c768nbt-s11472M-d5982M": 14515.9,
    "kata1-tf3-b11c768-s11341M-d6089M": 14503.6,
    "kata1-zhizi-b40c768nbt-fdx6d": 14481.6,
    "kata1-zhizi-b40c768nbt-fdx6c": 14453.6,
    "kata1-tf3-b10c512-s3203M-d5937M": 14169.6,
    "kata1-zhizi-b28c512nbt-muonfd2": 14159.0,
    "kata1-tf2-b10c384-s2941M-d5872M": 13710.3,
}


def _net_name(model: Path) -> str:
    """Net name as katagotraining.org lists it, i.e. the filename less .bin.gz."""
    name = model.name
    for suffix in (".bin.gz", ".txt.gz"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _pick_best_net(models: list[Path]) -> Path:
    """Pick the net with the highest published Elo, rated nets ahead of unrated."""
    # Rated nets beat unrated ones; name breaks ties so the choice is stable.
    best = max(models, key=lambda m: (_net_name(m) in _NET_ELO,
                                      _NET_ELO.get(_net_name(m), 0.0),
                                      m.name))
    if _net_name(best) not in _NET_ELO:
        logger.warning(
            "No published Elo on record for any net in %s; falling back to %s. "
            "Add its rating to _NET_ELO in cli.py to pick by strength.",
            best.parent, best.name)
    return best


def _find_katrain_katago() -> tuple[Path, Path, Path] | None:
    if not _KATRAIN_MAC_RESOURCES.is_dir():
        return None
    binary = _KATRAIN_MAC_RESOURCES / "KataGo" / "katago-osx"
    config = _KATRAIN_MAC_RESOURCES / "KataGo" / "analysis_config.cfg"
    models = sorted((_KATRAIN_MAC_RESOURCES / "models").glob("*.bin.gz"))
    if not (binary.exists() and config.exists() and models):
        return None
    return binary, _pick_best_net(models), config


def _find_local_katago() -> tuple[Path, Path, Path] | None:
    config = _REPO_ROOT / "katago" / "analysis.cfg"
    models = sorted((_REPO_ROOT / "katago" / "models").glob("*.bin.gz"))
    if not (config.exists() and models):
        return None
    for build_dir in _LOCAL_KATAGO_BUILDS:
        binary = _REPO_ROOT / build_dir / "katago.exe"
        if binary.exists():
            return binary, _pick_best_net(models), config
    return None


def main() -> None:
    parser = argparse.ArgumentParser(prog="baduk-lab")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze a folder of SGF/.gib files")
    analyze.add_argument("folder", nargs="?",
                         help="Folder containing .sgf/.gib files (recursed into). "
                              "Defaults to config.toml's [source] default_folder.")
    analyze.add_argument("--player",
                         help="Your server handle(s), comma-separated for multiple "
                              "aliases (matched against PB/PW or the .gib equivalent). "
                              "Defaults to config.toml's [player] aliases.")
    analyze.add_argument("--out", default="report", help="Output directory")
    analyze.add_argument("--katago", help="Path to katago binary")
    analyze.add_argument("--model", help="Path to neural net model")
    analyze.add_argument("--config", help="Path to analysis config")
    analyze.add_argument("--visits", type=int, default=500)

    tidy_cmd = sub.add_parser(
        "tidy", help="Rename SGF/.gib files from their own metadata and "
                     "quarantine duplicate games in a folder")
    tidy_cmd.add_argument("folder", help="Folder to tidy (recursed into)")
    tidy_cmd.add_argument("--dry-run", action="store_true",
                          help="Show planned renames/duplicate moves without "
                               "touching any files")

    notes = sub.add_parser(
        "notes", help="Harvest the mistakes you commented on yourself in "
                      "reviewed SGFs into the quiz deck (no KataGo needed)")
    notes.add_argument("folder", nargs="?",
                       help="Folder of SGFs you've reviewed and commented on "
                            "(recursed into). Defaults to config.toml's "
                            "[annotations] folder.")
    notes.add_argument("--player",
                       help="Your server handle(s), comma-separated. Defaults to "
                            "config.toml's [player] aliases.")
    notes.add_argument("--out", default="report", help="Output directory")

    review = sub.add_parser("review", help="Run a quiz session over your problem set")
    review.add_argument("--out", default="report",
                        help="Report directory from a prior `analyze` run")
    review.add_argument("--limit", type=int, default=15,
                        help="Max problems to review in this session")
    review.add_argument("--phase", choices=["opening", "middle", "endgame"],
                        help="Only review problems from this phase")
    review.add_argument("--source", choices=["all", "katago", "note"], default="all",
                        help="Which deck to review: KataGo's points-lost finds "
                             "(katago), the mistakes you commented on yourself "
                             "(note), or both (default). Your own notes are "
                             "offered first when both are due, since you picked "
                             "them out by hand.")
    review.add_argument("--ignore-due", action="store_true",
                        help="Drill every problem in the deck, not just what "
                             "spaced repetition says is due today -- for going "
                             "back over a game you just reviewed, or when "
                             "nothing is due and you want to practise anyway. "
                             "Answers still count: a right one pushes the "
                             "problem to a later box as usual.")
    review.add_argument("--html", action="store_true",
                        help="Generate quiz.html and open it in your browser via a "
                             "local server, instead of the terminal y/n loop -- "
                             "click-to-guess, instant grading, no switching to "
                             "KaTrain per problem. Served over http://127.0.0.1 "
                             "(not opened as a plain file) so the page can save "
                             "your answers back to quiz_state.json; Ctrl+C to stop.")

    drill_cmd = sub.add_parser(
        "drill", help="Middle-game 'answer or tenuki?' drill from self-play "
                      "of seed openings (see MIDGAME_DRILL_DESIGN.md)")
    drill_sub = drill_cmd.add_subparsers(dest="drill_command", required=True)

    gen = drill_sub.add_parser("generate", help="Self-play seed openings into middle games")
    gen.add_argument("--seeds", default="seeds", help="Folder of seed opening SGFs")
    gen.add_argument("--selfplay", default="selfplay", help="Where generated games go")
    gen.add_argument("--games-per-seed", type=int, default=20,
                     help="Top each seed up to this many games (incremental)")
    gen.add_argument("--gen-visits", type=int, default=selfplay.GenSettings.gen_visits)
    gen.add_argument("--stop-at", type=int, default=selfplay.GenSettings.stop_at)
    gen.add_argument("--loss-budget", type=float, default=selfplay.GenSettings.loss_budget)
    gen.add_argument("--temperature", type=float, default=selfplay.GenSettings.temperature)
    gen.add_argument("--parallel", type=int, default=16,
                     help="Games advanced together (one batched query per round)")
    _add_katago_args(gen)

    build = drill_sub.add_parser("build", help="Probe generated games into a drill deck")
    build.add_argument("--selfplay", default="selfplay", help="Folder of generated games")
    build.add_argument("--out", default="report/drill", help="Drill deck directory")
    build.add_argument("--visits", type=int, default=drill.DrillSettings.visits)
    build.add_argument("--screen-visits", type=int, default=drill.DrillSettings.screen_visits)
    build.add_argument("--min-gap", type=float, default=drill.DrillSettings.min_gap)
    build.add_argument("--score-window", type=float, default=drill.DrillSettings.score_window,
                       help="Max |score lead| for the side to move, in points")
    build.add_argument("--radius", type=int, default=drill.DrillSettings.radius)
    build.add_argument("--max-games", type=int,
                       help="Probe at most this many not-yet-cached games, then stop "
                            "(0 just rewrites the deck from the cache). "
                            "Rerun to continue where it left off -- each run restarts "
                            "the engine, so a long build can be done in batches without "
                            "its memory use piling up.")
    build.add_argument("--group", type=int, default=8,
                       help="Games probed together per engine phase (lower uses less memory)")
    _add_katago_args(build)

    drill_review = drill_sub.add_parser("review", help="Drill session in the browser")
    drill_review.add_argument("--out", default="report/drill", help="Drill deck directory")
    drill_review.add_argument("--limit", type=int, default=20)
    drill_review.add_argument("--tenuki-share", type=float, default=0.6,
                              help="Share of tenuki-answer positions per session")
    drill_review.add_argument("--score-tolerance", type=float, default=drill.SCORE_TOLERANCE,
                              help="A score estimate within this many points counts as "
                                   "right (re-renders the page; no rebuild needed)")

    args = parser.parse_args()
    if args.command == "analyze":
        _run_analyze(args)
    elif args.command == "tidy":
        _run_tidy(args)
    elif args.command == "notes":
        _run_notes(args)
    elif args.command == "review":
        _run_review(args)
    elif args.command == "drill":
        {"generate": _run_drill_generate, "build": _run_drill_build,
         "review": _run_drill_review}[args.drill_command](args)


def _add_katago_args(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument("--katago", help="Path to katago binary")
    cmd.add_argument("--model", help="Path to neural net model")
    cmd.add_argument("--config", help="Path to analysis config")


def _resolve_katago(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    katago, model, engine_config = args.katago, args.model, args.config
    if not (katago and model and engine_config):
        found = _find_local_katago() or _find_katrain_katago()
        if found is None:
            sys.exit("Could not find a local KataGo install. "
                     "Pass --katago/--model/--config explicitly.")
        katago = katago or found[0]
        model = model or found[1]
        engine_config = engine_config or found[2]
    return Path(katago), Path(model), Path(engine_config)


def _run_analyze(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    katago, model, engine_config = _resolve_katago(args)

    player_aliases = ([p.strip() for p in args.player.split(",") if p.strip()]
                      if args.player else config.player_aliases())
    if not player_aliases:
        sys.exit("No --player given, and no [player] aliases in config.toml. "
                 "Pass --player, or copy config.example.toml to config.toml.")

    folder = Path(args.folder) if args.folder else config.default_folder()
    if folder is None:
        sys.exit("No folder given, and no [source] default_folder in config.toml.")

    records = load_folder(folder)
    if not records:
        sys.exit(f"No SGF/.gib files found in {folder}")

    out_dir = Path(args.out)
    cache_dir = out_dir / "raw"

    analyses: list[GameAnalysis] = []
    with KataGoClient(Path(katago), Path(model), Path(engine_config),
                      visits=args.visits) as client:
        for record in records:
            if record.color_of(player_aliases) is None:
                logger.warning("Skipping %s: none of %r found as a player",
                              record.path.name, player_aliases)
                continue
            logger.info("Analyzing %s...", record.path.name)
            analyses.append(client.analyze_game(record, cache_dir=cache_dir))

    if not analyses:
        sys.exit(f"No games in {folder} feature any of {player_aliases!r} as a player")

    phase_loss = metrics.phase_loss_distribution(analyses, player_aliases)
    magnitude = metrics.magnitude_profile(analyses, player_aliases)
    ahead_behind = metrics.ahead_behind_split(analyses, player_aliases)
    problems = metrics.problem_positions(analyses, player_aliases)

    logger.info("Estimating strength...")
    strengths = {a.record.path.name: strength.estimate_game(a) for a in analyses}

    report_path = report.render_report(
        out_dir, player=" / ".join(player_aliases), analyses=analyses,
        phase_loss=phase_loss, magnitude=magnitude, ahead_behind=ahead_behind,
        problems=problems, model=str(model), visits=args.visits,
        player_aliases=player_aliases, strengths=strengths,
    )
    problems_dir = out_dir / "problems"
    report.export_problem_sgfs(problems, problems_dir, analyses=analyses)
    report.export_problem_index(problems, problems_dir)
    report.export_game_records(analyses, problems_dir)

    timeline = report.strength_timeline(analyses, strengths, player_aliases)
    chart_path = strength_chart.render_strength_chart(timeline, out_dir / "strength_chart.html")

    state_path = out_dir / "quiz_state.json"
    state = quiz.load_state(state_path)
    quiz.sync_new_problems(state, problems, date.today())
    quiz.save_state(state_path, state)

    logger.info("Report written to %s", report_path)
    logger.info("Strength chart written to %s", chart_path)
    logger.info("%d problems tracked for review (run `baduk-lab review --out %s`)",
               len(problems), out_dir)


def _run_notes(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    player_aliases = ([p.strip() for p in args.player.split(",") if p.strip()]
                      if args.player else config.player_aliases())
    if not player_aliases:
        sys.exit("No --player given, and no [player] aliases in config.toml. "
                 "Pass --player, or copy config.example.toml to config.toml.")

    folder = Path(args.folder) if args.folder else config.annotations_folder()
    if folder is None:
        sys.exit("No folder given, and no [annotations] folder in config.toml. "
                 "Point it at where your reviewer saves commented games (for "
                 "LizzieYzy Next: its user-data/AnalyzedGames).")
    if not folder.is_dir():
        sys.exit(f"Not a folder: {folder}")

    mistakes = annotations.harvest_folder(folder, player_aliases)
    if not mistakes:
        sys.exit(f"No commented mistakes found in {folder}. Comments are read from "
                 "each SGF's own C[] nodes, minus the lines your reviewer "
                 "generates into them.")

    # Only the games a note actually landed in need their moves exported;
    # the quiz redraws each board from these, not from the source folder.
    records = {}
    for name in {m.game for m in mistakes}:
        path = next(p for p in folder.rglob("*.sgf") if p.name == name)
        board_size, moves = annotations.moves_of(path)
        records[name] = GameRecord(path=path, board_size=board_size, komi=0.0,
                                   player_black="", player_white="", result="",
                                   moves=moves)

    out_dir = Path(args.out)
    problems_dir = out_dir / "problems"
    report.export_note_sgfs(mistakes, problems_dir, records)
    index_path = report.export_note_index(mistakes, problems_dir)
    report.export_note_game_records(records, problems_dir)

    state_path = out_dir / "quiz_state.json"
    state = quiz.load_state(state_path)
    quiz.sync_new_problems(state, mistakes, date.today())
    dropped = quiz.drop_missing(state, mistakes, prefix="note::")
    quiz.save_state(state_path, state)

    logger.info("%d commented mistake(s) across %d game(s) -> %s",
                len(mistakes), len(records), index_path)
    for key in dropped:
        logger.info("Dropped %s -- no note on that move any more.", key)
    logger.info("Run `baduk-lab review --source note --html --out %s` to drill them.",
                out_dir)


def _run_tidy(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    folder = Path(args.folder)
    if not folder.is_dir():
        sys.exit(f"Not a folder: {folder}")

    result = tidy.tidy_folder(folder, dry_run=args.dry_run)

    rename_verb = "Would rename" if args.dry_run else "Renamed"
    for old, new in result.renamed:
        logger.info("%s: %s -> %s", rename_verb, old.name, new.name)

    move_verb = "Would quarantine" if args.dry_run else "Quarantined"
    for old, new in result.quarantined:
        logger.info("%s duplicate: %s -> %s", move_verb, old.relative_to(folder), new.relative_to(folder))

    for path, reason in result.skipped:
        logger.warning("Skipping %s: %s", path.name, reason)

    suffix = " (dry run, nothing changed)" if args.dry_run else ""
    logger.info("%d renamed, %d duplicate(s) quarantined, %d skipped%s",
               len(result.renamed), len(result.quarantined), len(result.skipped), suffix)


def _resolve_problem_sgf_path(problems_dir: Path, rel_path: str | None) -> Path | None:
    """Validate a client-supplied relative SGF path against problems_dir,
    rejecting anything that escapes it (e.g. "../../..") or doesn't exist.
    Pure/testable; kept separate from the HTTP handler that calls it."""
    if not rel_path:
        return None
    problems_dir = problems_dir.resolve()
    candidate = (problems_dir / rel_path).resolve()
    try:
        candidate.relative_to(problems_dir)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _kill_process_tree(pid: int) -> None:
    """Best-effort: kill `pid` and every process it spawned, recursively.

    LizzieYzy Next.exe isn't a single process -- subprocess.Popen's PID is
    a lightweight launcher that immediately re-execs a second "LizzieYzy
    Next.exe" (the actual window + JVM), which in turn spawns its own
    katago.exe engine processes as further children. Verified empirically
    (Get-CimInstance Win32_Process parent/child chase): terminating just
    the Popen PID leaves the real window and its engines running orphaned.
    `taskkill /T` walks and kills the whole tree in one call; there's no
    single-call equivalent worth using os.kill for here. Failures (e.g. the
    user already closed the window themselves) are silently ignored --
    "no old instance running" is the goal state either way.
    """
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True)
    else:
        try:
            subprocess.Popen(["pkill", "-TERM", "-P", str(pid)]).wait(timeout=5)
        except Exception:
            pass


class _QuizRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serves out_dir like SimpleHTTPRequestHandler, plus two extra routes:
    GET /open-lizzie?path=<sgf relpath under problems_dir> launches
    lizzieyzy_exe with that file, for quiz.html's "Deep analysis" button.
    Only one instance is kept alive at a time -- each request kills
    whatever this session's last /open-lizzie call launched (if it's still
    running) before starting the new one, so a whole quiz session only
    ever has one LizzieYzy window (and one KataGo engine) open, instead of
    piling one up per click.

    POST /quiz-state grades one problem straight into quiz_state.json using
    the same quiz.record_result/save_state this process already uses for
    the terminal review flow, instead of quiz.html reimplementing the box
    scheduling in JS against a browser-picked file handle -- the server
    already knows state_path (it's just out_dir/quiz_state.json), so there
    is nothing for the page to pick. state_lock serializes writes since
    ThreadingHTTPServer can run request handlers concurrently.

    All class attributes are set once in _serve_and_open before the server
    starts -- this process only ever runs one review session at a time."""
    problems_dir: Path | None = None
    lizzieyzy_exe: Path | None = None
    lizzieyzy_proc: subprocess.Popen | None = None
    state_path: Path | None = None
    state_lock = threading.Lock()

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/open-lizzie":
            self._handle_open_lizzie()
            return
        super().do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path == "/quiz-state":
            self._handle_save_state()
            return
        self.send_error(404)

    def _handle_save_state(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            problem_id = str(body["problemId"])
            correct = bool(body["correct"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            self._json(400, {"ok": False, "error": f"Bad request: {exc}"})
            return

        with self.state_lock:
            state = quiz.load_state(self.state_path)
            quiz.record_result(state, problem_id, correct, date.today())
            quiz.save_state(self.state_path, state)
        self._json(200, {"ok": True})

    def _handle_open_lizzie(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        rel_path = query.get("path", [None])[0]
        sgf_path = _resolve_problem_sgf_path(self.problems_dir, rel_path)

        if self.lizzieyzy_exe is None:
            self._json(400, {"ok": False,
                             "error": "No [lizzieyzy] exe configured in config.toml."})
            return
        if not self.lizzieyzy_exe.is_file():
            self._json(400, {"ok": False,
                             "error": f"lizzieyzy_exe not found: {self.lizzieyzy_exe}"})
            return
        if sgf_path is None:
            self._json(400, {"ok": False, "error": f"Unknown problem path: {rel_path!r}"})
            return

        if _QuizRequestHandler.lizzieyzy_proc is not None:
            _kill_process_tree(_QuizRequestHandler.lizzieyzy_proc.pid)
            _QuizRequestHandler.lizzieyzy_proc = None

        try:
            _QuizRequestHandler.lizzieyzy_proc = subprocess.Popen(
                [str(self.lizzieyzy_exe), str(sgf_path)], cwd=str(self.lizzieyzy_exe.parent))
        except OSError as exc:
            self._json(500, {"ok": False, "error": str(exc)})
            return
        self._json(200, {"ok": True})

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve_and_open(out_dir: Path, problems_dir: Path, filename: str, state_path: Path) -> None:
    """Serve out_dir on 127.0.0.1 and open filename in the default browser.

    quiz.html grades each answer via a fetch() POST to /quiz-state on this
    same server -- a relative fetch only resolves against a real origin, so
    double-clicking quiz.html as a file:// page would break that (and the
    /open-lizzie route below) regardless. The server only needs to be up
    for page loads and those fetches, but it's kept alive with
    serve_forever() so a page reload later in the session still works;
    Ctrl+C stops it.
    """
    _QuizRequestHandler.problems_dir = problems_dir
    _QuizRequestHandler.lizzieyzy_exe = config.lizzieyzy_exe()
    _QuizRequestHandler.lizzieyzy_proc = None
    _QuizRequestHandler.state_path = state_path
    handler = functools.partial(_QuizRequestHandler, directory=str(out_dir))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/{filename}"
    print(f"Serving {out_dir} at {url}")
    webbrowser.open(url)
    print("Press Ctrl+C here once you're done reviewing.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if _QuizRequestHandler.lizzieyzy_proc is not None:
            print("Closing LizzieYzy...")
            _kill_process_tree(_QuizRequestHandler.lizzieyzy_proc.pid)


def _select_problems(problems, state: dict, today: date, *,
                     ignore_due: bool):
    """The problems this session will ask, best-first.

    Normally that is whatever spaced repetition says is due. --ignore-due
    takes the whole deck instead, keeping due_problems' own worst-first
    order (by points lost) so a practice run still leads with the costly
    mistakes rather than with whatever sorts first by name."""
    selected = (sorted(problems, key=lambda p: p.points_lost, reverse=True)
                if ignore_due else quiz.due_problems(state, problems, today))
    return _order_session(selected)


def _order_session(due: list[report.ProblemIndexEntry]) -> list[report.ProblemIndexEntry]:
    """Put your own commented mistakes first, keeping each deck in the
    worst-first order `quiz.due_problems` already gave them.

    That ordering is by points lost, which under-rates a note badly: a
    strategic misjudgment in a close game can swing the winrate 20% while
    costing well under a point, so sorting the merged list by points would
    bury every note under KataGo's blunders and `--limit` would cut them.
    You picked the notes out by hand, so they lead."""
    return sorted(due, key=lambda p: p.source != "note")


def _run_review(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    out_dir = Path(args.out)
    problems_dir = out_dir / "problems"

    problems = []
    if args.source in ("all", "katago") and (problems_dir / "index.json").exists():
        problems += report.load_problem_index(problems_dir)
    if args.source in ("all", "note"):
        problems += report.load_note_index(problems_dir)
    if not problems:
        sys.exit(f"No problems found in {problems_dir}. Run `baduk-lab analyze` "
                 "(KataGo's own finds) or `baduk-lab notes` (the mistakes you "
                 "commented on yourself) first.")

    if args.phase:
        problems = [p for p in problems if p.phase == args.phase]

    state_path = out_dir / "quiz_state.json"
    state = quiz.load_state(state_path)
    today = date.today()
    quiz.sync_new_problems(state, problems, today)

    due = _select_problems(problems, state, today,
                           ignore_due=args.ignore_due)[: args.limit]
    quiz.save_state(state_path, state)

    if args.html:
        if not due:
            print("Nothing due for review right now. Nice. "
                  "(`--ignore-due` drills the whole deck anyway.)")
            return
        games = report.load_game_records(problems_dir)
        if not games:
            sys.exit(f"No games.json/{report.NOTES_GAMES_FILENAME} found in "
                     f"{problems_dir}. Re-run `baduk-lab analyze` or "
                     "`baduk-lab notes` to regenerate it.")
        quiz_html.render_quiz_html(due, games, out_dir / "quiz.html", today)
        print(f"{len(due)} problem(s) ready.")
        _serve_and_open(out_dir, problems_dir, "quiz.html", state_path)
        return

    if not due:
        print("Nothing due for review right now. Nice. "
              "(`--ignore-due` drills the whole deck anyway.)")
        return

    print(f"{len(due)} problem(s) due for review.\n")
    reviewed = correct = 0
    for problem in due:
        print(f"[{problem.phase}] {problem.game} move {problem.move_number} "
             f"({problem.points_lost:.1f} pts lost)")
        print(f"  Open: {problems_dir / problem.path}")
        answer = input("  Found the better move? [y/n/s(kip)/q(uit)]: ").strip().lower()
        if answer == "q":
            break
        # Only after you've answered -- your own note usually names the move,
        # so printing it with the prompt would hand you the answer.
        if problem.note:
            print(f"  Your note: {problem.note}")
        if answer != "y" and answer != "n":
            continue
        reviewed += 1
        is_correct = answer == "y"
        correct += int(is_correct)
        quiz.record_result(state, problem.problem_id, is_correct, today)
        quiz.save_state(state_path, state)

    remaining = len(quiz.due_problems(state, problems, today))
    print(f"\nReviewed {reviewed}, correct {correct}. {remaining} still due today.")


# Many small searches in flight instead of the config's few wide ones: the
# drill's queries are cheap (100-500 visits) and numerous, so batch width
# across positions is what keeps the GPU busy.
_DRILL_ENGINE_OVERRIDES = {"numAnalysisThreads": 16, "numSearchThreadsPerAnalysisThread": 4}


def _run_drill_generate(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    seeds = selfplay.load_seeds(Path(args.seeds))
    if not seeds:
        sys.exit(f"No seed SGFs found in {args.seeds}")
    settings = selfplay.GenSettings(gen_visits=args.gen_visits, stop_at=args.stop_at,
                                    loss_budget=args.loss_budget,
                                    temperature=args.temperature)
    katago, model, engine_config = _resolve_katago(args)
    overrides = dict(_DRILL_ENGINE_OVERRIDES, numAnalysisThreads=args.parallel)
    with KataGoClient(katago, model, engine_config, visits=args.gen_visits,
                      config_overrides=overrides) as client:
        result = selfplay.generate(client, seeds, args.games_per_seed,
                                   Path(args.selfplay), settings, parallel=args.parallel)
    print(f"Generated {result['generated']} game(s) "
          f"({result['abandoned']} stopped early) into {args.selfplay}/. "
          f"Next: baduk-lab drill build")


def _run_drill_build(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    selfplay_dir = Path(args.selfplay)
    if not any(selfplay_dir.rglob("g*.gen.json")):
        sys.exit(f"No generated games in {selfplay_dir}. Run `baduk-lab drill generate` first.")
    settings = drill.DrillSettings(visits=args.visits, screen_visits=args.screen_visits,
                                   min_gap=args.min_gap, score_window=args.score_window,
                                   radius=args.radius)
    out_dir = Path(args.out)
    katago, model, engine_config = _resolve_katago(args)
    with KataGoClient(katago, model, engine_config, visits=args.visits,
                      config_overrides=_DRILL_ENGINE_OVERRIDES) as client:
        problems = drill.build(client, selfplay_dir, out_dir, settings, model=str(model),
                               group=args.group, max_games=args.max_games)

    state_path = out_dir / "drill_state.json"
    state = quiz.load_state(state_path)
    quiz.sync_new_problems(state, problems, date.today())
    quiz.save_state(state_path, state)
    n_tenuki = sum(p.kind == "tenuki" for p in problems)
    remaining = sum(1 for _ in selfplay_dir.rglob("g*.gen.json")) - len(
        list((out_dir / "cache").rglob("*.json")))
    print(f"{len(problems)} drill position(s): {n_tenuki} tenuki, "
          f"{len(problems) - n_tenuki} answer-locally."
          + (f" {remaining} game(s) still unprobed -- rerun `baduk-lab drill build` "
             f"to add more." if remaining > 0 else "")
          + " Next: baduk-lab drill review")


def _run_drill_review(args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    problems_dir = out_dir / "problems"
    if not (problems_dir / "index.json").exists():
        sys.exit(f"No {problems_dir / 'index.json'} found. Run `baduk-lab drill build` first.")
    problems = drill.load_index(problems_dir)
    state_path = out_dir / "drill_state.json"
    state = quiz.load_state(state_path)
    today = date.today()
    quiz.sync_new_problems(state, problems, today)
    quiz.save_state(state_path, state)

    due = quiz.due_problems(state, problems, today)
    session = drill.compose_session(due, args.limit, tenuki_share=args.tenuki_share)
    if not session:
        print("Nothing due for review right now. Nice.")
        return
    games = json.loads((problems_dir / "games.json").read_text(encoding="utf-8"))
    drill_html.render_drill_html(session, games, out_dir / "drill.html", today,
                                 score_tolerance=args.score_tolerance)
    print(f"{len(session)} position(s) ready.")
    _serve_and_open(out_dir, problems_dir, "drill.html", state_path)


if __name__ == "__main__":
    main()
