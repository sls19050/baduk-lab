"""Command-line interface.

Target usage:
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

from . import config, metrics, quiz, quiz_html, report, strength, strength_chart
from .engine import GameAnalysis, KataGoClient
from .loader import load_folder

logger = logging.getLogger(__name__)

# If installed, KaTrain bundles its own KataGo binary/model/config, so most
# users never need to pass --katago/--model/--config explicitly.
_KATRAIN_MAC_RESOURCES = Path("/Applications/KaTrain.app/Contents/Resources/katrain")

# This repo's own local KataGo installs (see KATAGO_SETUP.md), fastest backend
# first. All three share one model/config directory (katago/); only the
# binary + its GPU backend DLLs differ between katago-trt/katago-cuda/katago.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_KATAGO_BUILDS = ["katago-trt", "katago-cuda", "katago"]


def _find_katrain_katago() -> tuple[Path, Path, Path] | None:
    if not _KATRAIN_MAC_RESOURCES.is_dir():
        return None
    binary = _KATRAIN_MAC_RESOURCES / "KataGo" / "katago-osx"
    config = _KATRAIN_MAC_RESOURCES / "KataGo" / "analysis_config.cfg"
    models = sorted((_KATRAIN_MAC_RESOURCES / "models").glob("*.bin.gz"))
    if not (binary.exists() and config.exists() and models):
        return None
    return binary, models[-1], config


def _find_local_katago() -> tuple[Path, Path, Path] | None:
    config = _REPO_ROOT / "katago" / "analysis.cfg"
    models = sorted((_REPO_ROOT / "katago" / "models").glob("*.bin.gz"))
    if not (config.exists() and models):
        return None
    for build_dir in _LOCAL_KATAGO_BUILDS:
        binary = _REPO_ROOT / build_dir / "katago.exe"
        if binary.exists():
            return binary, models[-1], config
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

    review = sub.add_parser("review", help="Run a quiz session over your problem set")
    review.add_argument("--out", default="report",
                        help="Report directory from a prior `analyze` run")
    review.add_argument("--limit", type=int, default=15,
                        help="Max problems to review in this session")
    review.add_argument("--phase", choices=["opening", "middle", "endgame"],
                        help="Only review problems from this phase")
    review.add_argument("--html", action="store_true",
                        help="Generate quiz.html and open it in your browser via a "
                             "local server, instead of the terminal y/n loop -- "
                             "click-to-guess, instant grading, no switching to "
                             "KaTrain per problem. Served over http://127.0.0.1 "
                             "(not opened as a plain file) so the page can save "
                             "your answers back to quiz_state.json; Ctrl+C to stop.")

    args = parser.parse_args()
    if args.command == "analyze":
        _run_analyze(args)
    elif args.command == "review":
        _run_review(args)


def _run_analyze(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    katago, model, engine_config = args.katago, args.model, args.config
    if not (katago and model and engine_config):
        found = _find_local_katago() or _find_katrain_katago()
        if found is None:
            sys.exit("Could not find a local KataGo install. "
                     "Pass --katago/--model/--config explicitly.")
        katago = katago or found[0]
        model = model or found[1]
        engine_config = engine_config or found[2]

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


def _run_review(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    out_dir = Path(args.out)
    problems_dir = out_dir / "problems"
    if not (problems_dir / "index.json").exists():
        sys.exit(f"No {problems_dir / 'index.json'} found. Run `baduk-lab analyze` first.")

    problems = report.load_problem_index(problems_dir)
    if args.phase:
        problems = [p for p in problems if p.phase == args.phase]

    state_path = out_dir / "quiz_state.json"
    state = quiz.load_state(state_path)
    today = date.today()
    quiz.sync_new_problems(state, problems, today)

    due = quiz.due_problems(state, problems, today)[: args.limit]
    quiz.save_state(state_path, state)

    if args.html:
        if not due:
            print("Nothing due for review right now. Nice.")
            return
        games_path = problems_dir / "games.json"
        if not games_path.exists():
            sys.exit(f"No {games_path} found. Run `baduk-lab analyze` again to "
                     "regenerate it (added after your last analyze run).")
        games = json.loads(games_path.read_text(encoding="utf-8"))
        quiz_html.render_quiz_html(due, games, out_dir / "quiz.html", today)
        print(f"{len(due)} problem(s) ready.")
        _serve_and_open(out_dir, problems_dir, "quiz.html", state_path)
        return

    if not due:
        print("Nothing due for review right now. Nice.")
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
        if answer != "y" and answer != "n":
            continue
        reviewed += 1
        is_correct = answer == "y"
        correct += int(is_correct)
        quiz.record_result(state, problem.problem_id, is_correct, today)
        quiz.save_state(state_path, state)

    remaining = len(quiz.due_problems(state, problems, today))
    print(f"\nReviewed {reviewed}, correct {correct}. {remaining} still due today.")


if __name__ == "__main__":
    main()
