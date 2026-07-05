# baduk-lab

A "swing lab" for serious amateur Go players.

Professional golfers go to training facilities that measure their swing and tell
them which muscles to train. Go players have a superhuman measurement device
(KataGo) but no diagnosis or prescription layer on top of it. This project fills
that gap.

You give it a folder of your recent serious games (SGF files, downloaded
manually from KGS / Tygem / OGS). It batch-analyzes them with KataGo's JSON
analysis engine and produces a single report that tells you **where your points
are leaking and what to train next**.

## What it produces

Given ~8+ games, one markdown report containing:

1. **Loss distribution by game phase.** Opening (moves 1-50), middle game
   (50-150), endgame (150+). Where do you actually lose points?
2. **Mistake magnitude profile.** One 15-point blunder per game vs. thirty
   1-point leaks per game are different players needing different training.
3. **Ahead/behind behavior.** Does your move quality collapse when you are
   winning (coasting) or losing (flailing)?
4. **A personalized problem set.** Every position where you lost more than a
   threshold (default 4 points), exported as SGF files with your move hidden,
   ready to drill in KaTrain or any SGF editor. Your own mistakes are the best
   tsumego collection you will ever own.

Planned, not in MVP:

- Time-usage diagnosis (pacing profile, byo-yomi degradation, time-quality
  correlation) using KGS `BL[]`/`WL[]` tags.
- Mistake taxonomy (direction of play vs. reading vs. timing), built on
  move-distance and fight-locality heuristics.
- Cycle-over-cycle trend tracking, so growth is visible instead of guessed at.

## What it deliberately does not do

- **No server integration / auth.** You download your own SGFs manually.
  Serious players can manage a folder.
- **No GUI.** This is a CLI that emits markdown + SGF files. Use KaTrain to
  view the extracted positions.
- **No fine-grained claims from small samples.** With 8 games, phase-level and
  magnitude-level statistics are real; "you are weak at attachments in the
  lower left" is tea-leaf reading. The report only makes claims the sample
  size supports.

## Requirements

- Python 3.11+
- A working KataGo binary and neural network. If you have KaTrain installed,
  you already have both; point the config at KaTrain's copy.

## Usage (target interface, not fully implemented yet)

```bash
pip install -e .
baduk-lab analyze ./my-games/ --player "donghalee" --out report/
```

Outputs:

```
report/
  report.md          # the diagnosis
  problems/          # your personalized problem set, one SGF per mistake
  raw/               # cached KataGo analysis JSON per game (re-runs are free)
```

## Architecture

```
sgf files -> loader.py -> engine.py (KataGo JSON analysis) -> metrics.py -> report.py
                                          |
                                          v
                                    raw/ cache (JSON)
```

- `loader.py` — SGF parsing (sgfmill), player-of-interest detection, move list
  extraction, time tags.
- `engine.py` — thin client for KataGo's JSON analysis engine over stdin/stdout.
  Caches results per game so KataGo only runs once per SGF.
- `metrics.py` — pure functions from per-move analysis to diagnosis numbers.
  No I/O. This is where the interesting logic lives and what tests cover.
- `report.py` — renders metrics into markdown; extracts problem SGFs.

## Status

Skeleton. Interfaces are sketched, nothing runs end to end yet.

## License

MIT
