# Middle-game "tenuki or answer?" drill — design

Status: **§2 (self-play generator), §3 (probing) and §4 (quiz) are
implemented** (`selfplay.py`, `drill.py`, `drill_html.py`, `baduk-lab
drill ...`). §1's own-games side, §5 (habit metric) and §7 are not yet.

## The problem this targets

The habit: in the middle game, play near the opponent's last move by reflex,
without asking whether the local situation actually needs an answer.
Following the opponent around hands them sente every time. They pick where
the game happens, and you're always one move behind on the biggest point.

The existing mistake deck (`baduk-lab review`) already catches some of this,
but it can't train this habit for three reasons:

1. **It doesn't know *why* a move was wrong.** A 6-point loss from a
   misread ladder and a 6-point loss from answering a move you could have
   ignored look the same in the deck. You can't drill a habit you can't
   pick out.
2. **It only asks "find the best move".** The skill you're missing is an
   earlier question: *"Do I need to answer this at all?"* If you can't
   answer that question, finding the exact best point doesn't help.
3. **It would teach the wrong lesson if you only saw tenuki answers.** If
   every quiz answer is "play elsewhere", you just learn to tenuki by
   reflex, which is the same habit pointed the other way and loses games
   to the opponent's follow-up. A good drill has to mix in positions where
   answering locally *is* correct, so the only way to score well is to
   actually judge each position.

So the drill is built around one judgement, **local vs. tenuki**, and it
measures your real games to show whether the habit is going away.

## Overview

```
seed openings ──► self-play generator ──┐
  (seeds/*.sgf)    (KataGo, ±10 pts kept)│
                                        ├──► candidate finder ──► probe queries ──► drill deck
your games ──► analyze (existing) ──────┤                         (KataGo, cached)      │
                                        │                                               ▼
                                        └──► "follow rate" metric ──► report.md   baduk-lab drill review
```

Five parts:

1. **Locality classifier.** Labels any move as *local* or *tenuki*
   relative to the opponent's last move. It drives the probe and the
   answer key; the quiz reports the label but never asks for it.
2. **Self-play generator** (the main source). Plays a few seed openings
   forward into many different, close middle games (§2).
3. **Candidate finder + probe.** Finds middle-game positions where the
   local/tenuki choice really matters, and measures the gap with one extra,
   targeted KataGo query per position.
4. **Quiz.** A two-step question (pick the point, then estimate the
   score), with a tolerant answer key and a balanced mix of answers.
5. **Habit metric.** A "follow rate" in `report.md`, so you can see whether
   your real games are changing, not just your quiz score.

## 1. Locality classifier

A move `m` is **local** to the opponent's last move `L` when either of these
holds:

- **Distance:** Chebyshev distance `max(|dx|, |dy|) <= 3` from `L`, or
- **Contact with the stones `L` touched:** `m` is on, or right next to, a
  liberty of a group that `L` touched (any group, either color, next to
  `L`), as long as that group is no more than 5 lines away.

The distance rule handles most cases. The group rule catches answers that
are far from `L` in a straight line but still a reply to it: extending a
group `L` just pressed on, or adding a liberty to a group `L` put in
atari. `board.py` already has `_group_and_liberties`, so this is a small
addition.

Everything else is **tenuki**. Passes and the first move after a pass are
skipped.

The radius (3) and the group cutoff (5) are tunable constants in
`metrics.py`, next to `OPENING_END` and similar. Expect to adjust them
after looking at real output. The rule only needs to agree with a strong
human's label in most cases, not every one.

## 2. Self-play generator: seed openings → close middle games

Your own games give a limited number of positions, and many of them are
already lopsided by move 60. The generator gives an unlimited supply: you
provide a few opening SGFs, and KataGo plays each one forward many times
in different ways. Only positions that stay close are kept.

### Seeds

- A folder of SGFs (default `seeds/`, configurable in `config.toml` as
  `[drill] seeds_folder`). Each file's main line, read with the existing
  `loader.load_sgf`, is one seed. It can stop anywhere: move 20 (a fuseki
  you want to understand) or move 60 (a position you know well).
- **Variations in a seed file become separate seeds.** If one SGF has a
  joseki tree with three branches, you get three seeds. This makes it
  easy to cover a whole opening family in one file.
- Komi comes from the seed's `KM[]`, defaulting to 6.5 (matching the
  Japanese-rules default in `engine.py`). Only 19×19 with no handicap for
  now: the loader doesn't read `AB[]`/`AW[]` setup stones, so a
  handicap seed is skipped with a warning.
- Seeds are used as given. A seed that's already lopsided gets pulled
  back by the steering below. (A pre-check that warns about lopsided
  seeds is not implemented.)

### How a game is generated

Use the analysis engine (the existing `KataGoClient` process, not
`katago selfplay`). `katago selfplay` is built for producing training
data: it needs training configs, writes `.npz` files, and gives no
per-move control. Driving the analysis engine one move at a time is
slower per game, but it lets us choose every move:

```
position = seed
while move_number < 150:
    analysis = query(position, visits=GEN_VISITS)          # e.g. 100 visits
    pool = candidates within LOSS_BUDGET of the best        # e.g. 1.5 pts
    move = sample(pool, weights = prior ** (1 / TEMPERATURE))
    apply balancing rule (below) to pool/budget first
    play move; record (move, winrate, scoreLead, best move) for the position
```

Many games (default 16) are advanced in lockstep: each round sends one
query per game in a single batch, so the GPU evaluates them together
instead of one small search at a time.

- **Variety** comes from sampling among the near-best candidates, weighted
  by KataGo's policy prior, instead of always playing the top move.
  Candidates with under 3% of the search's visits are ignored, since
  their scores are too noisy to compare. Every game gets its own RNG
  seed, stored in the SGF. That makes our sampling repeatable, but not
  the game as a whole, because KataGo's own search isn't deterministic
  (`nnRandomize`). Games from one seed split into different shapes within
  a few moves.
- **Stop at move 150.** The drill only uses moves 51–150, so there's no
  point playing the endgame. That alone saves more than half the cost per
  game.
- **Optional human-style moves.** With the HumanSL model available, sample
  from the human policy at a set rank (`humanSLProfile = "rank_3d"`)
  instead of KataGo's own prior. This gives positions that look like
  amateur games, with the overconcentrated shapes and slack local moves
  that create real "do I answer?" decisions. Pure KataGo self-play tends
  to give very efficient positions with fewer obvious temptations. Same
  TensorRT caveat as §7.

### Keeping it close: score within ±10 points

The criterion is the **score lead**, not winrate. Winrate saturates
quickly between strong players: a 3-point lead can already be 70%, so a
winrate window throws away positions that are still very much
playable. Score lead is also what the drill measures (the gap is in
points), so the two agree.

Filtering alone still isn't enough: unsteered self-play drifts apart, so
the generator **steers** while playing and **filters** afterward.

**Steering (while playing).** After each query, look at the score lead
for the side to move:

| Situation | Leading side samples from | Trailing side samples from |
|---|---|---|
| Within ±4 points | normal pool (≤ 1.5 pts loss) | normal pool (≤ 1.5 pts loss) |
| More than 4 points apart | wider pool (≤ 3 pts) | best moves only (≤ 0.5 pts) |
| More than 10 points apart for 10 moves in a row | — | game stops there |

The leading side plays slightly looser moves, and the trailing side plays
precisely. The game drifts back toward even without anyone playing a
deliberately bad move, since the leading side's moves are still among
KataGo's reasonable candidates. A game that stays far apart is stopped
early and saved anyway: its earlier positions can still be used.
Stopped games are counted in the generation summary.

Measured on the first 6 games (one per seed): 590 of 600 middle-game
positions were within ±10 points, and one game that reached +9.6 was
pulled back to about −5.

**Filtering (at harvest).** A position is only eligible when the **side
to move** is within **±10 points** (`--score-window 10`). The window is
checked loosely (±12) on generation-visit numbers, then strictly on the
full-visit re-analysis.

### Harvesting positions

`drill build` handles each generated game in three passes, several games
at a time so each pass's queries batch together:

1. **Screen.** Every eligible middle-game position gets one low-visit
   (100) probe that forces the side the generation search didn't pick
   (§3). Together with the generation search's best move, that gives a
   rough gap for every position.
2. **Verify.** A shortlist goes through a full-visit (500) unrestricted
   query plus a full-visit probe. A position is kept only if the score is
   still within ±10 and |gap| ≥ 2.
3. **Pick.** At most 3 positions per game, at least 15 moves apart.

**Tenuki positions are scarce in self-play.** KataGo rarely plays a
move its opponent can ignore. Its best move is a tenuki about 38% of the
time, but usually the local answer is almost as good. On the first 3
games, about 15 positions per kind cleared a 2-point gap at screening,
and far fewer tenuki ones survived verification. So:

- The shortlist reserves up to 6 tenuki candidates per game (vs 3
  answer-locally ones), since verification is cheap compared with
  generating games.
- The final pick reserves 2 of the 3 per-game slots for tenuki
  positions. If one kind is short, the other fills the slot.
- Ranking caps |gap| at 8. Past that, a position is usually a
  save-the-group fight, which is an easy "answer" rather than the
  whole-board judgement being trained, so smaller gaps win ties.
- Beyond that, the remedy is more games. Tenuki positions per game is
  the number to watch.

Problem IDs: `selfplay::<seed-slug>::g<NNN>::m<n>`, stable across
re-runs. Generating more games for a seed adds new `g<NNN>` numbers
without touching existing ones. (Removing near-duplicate positions
across games is not implemented yet; spacing within a game is.)

### Output on disk

```
selfplay/
  <seed-stem>/
    g001.sgf          # full generated game; root comment records seed, RNG
                      # seed, visits, loss budget, temperature, human profile
    g001.gen.json     # per-move winrate/scoreLead at generation visits
```

The SGFs are normal game records. You can open one in KaTrain or
LizzieYzy to see how the drill position was reached, and the quiz's
LizzieYzy button works without changes.

### Cost (measured)

On this machine (RTX 5070, TensorRT, b40 model), with 6 games running in
parallel:

- generation: about 2 minutes for 6 games of 150 moves at 100
  visits/move, plus about 30 s of engine startup;
- build: about 30 s per game (screening dominates: roughly 85 probes ×
  100 visits per game).

So 180 games (30 per seed) is a run of about 2–2½ hours, best left
running in the background. Both steps are incremental and cached, so
adding games later only pays for the new ones.

## 3. Finding and probing candidate positions

### Candidate filter (cheap, uses the existing cache only)

From each analyzed game, take positions where:

- it's the middle game (`phase_of(move) == "middle"`, i.e. moves 51–150);
- for your own games, the side to move is **you** (positions where the
  opponent is to move are a later extension, see §7); for self-play
  games, either side;
- the game is still undecided, otherwise every move is "fine" and
  nothing is learned: the mover's score lead is within ±10 points for
  self-play (§2), or the mover's winrate is between 0.15 and 0.85 for
  your own games;
- the opponent's previous move wasn't a pass, and there's no ko fight
  going on. The rough check: none of the last 4 moves captured exactly
  one stone. Every ko capture does, and losing a few non-ko positions
  is acceptable.

That's about 70–90 positions per self-play game. For each one, the
cached `best_moves` (top 16 candidates) is split into local and tenuki
candidates using §1.

### Probe query (one extra KataGo call per candidate, cached)

The cached top-16 list isn't enough to measure the gap reliably. If every
local move is bad, none of them may appear in the list. If one does
appear, it may have very few visits, so its score is noisy. So for each
candidate, send **one** extra analysis query that forces the side KataGo
didn't pick:

- If KataGo's best move is **tenuki**, ask for the best **local** move:
  `"allowMoves": [{"player": <mover>, "moves": <local region>, "untilDepth": 1}]`
- If KataGo's best move is **local**, ask for the best **tenuki** move:
  `"avoidMoves": [{"player": <mover>, "moves": <local region>, "untilDepth": 1}]`

The unrestricted best move is already in the cache, so between that and
the probe you have both sides' best scores:

```
gap = score(best tenuki) − score(best local)        # in the mover's points
```

Positive gap = tenuki was better, negative = answering was required.

The probe also returns per-candidate **visits** (the existing cache doesn't
store them). Those are used for the tolerant answer key in §4.

Cost and caching: see §2, "Harvesting positions" (screening at 100
visits, then full-visit verification of a shortlist). Results are
cached per game in `report/drill/cache/<seed>/gNNN.json`, keyed on the
gen.json content, the model and every drill setting, so changing
`--radius` or `--min-gap` re-probes and re-runs only probe new games.

### Selection: what makes a good drill position

Keep a position if `|gap| >= 2.0` points (tunable `--min-gap`), and sort it
into one of three types:

| Type | Condition | What it teaches |
|---|---|---|
| **Tenuki** | gap ≥ +2 | "This doesn't need an answer. Take the big point." |
| **Answer** | gap ≤ −2 | "This one really does need an answer. Don't overcorrect." |
| **Followed** *(Tenuki that you got wrong)* | gap ≥ +2 **and** your real move was local | Your habit in action. The most valuable type. |

"Followed" is a subset of Tenuki. It gets its own tag because it's direct
evidence of the habit and gets priority in sessions. The opposite case
("answer needed, but you tenuki'd") is tagged **Ignored**, so you can see
whether you're overcorrecting.

When several places are about equally good, the tolerant answer key
(§4) accepts all of them, so the "where" step stays fair without
dropping the position.

### Deck sources

The pipeline doesn't care where the SGFs came from:

- **Self-play from your seeds** (§2). The main source of volume, with
  every position close (within ±10 points). Tagged Tenuki/Answer only, since you
  didn't play these games.
- **Your own games.** Fewer positions, but these are the ones you actually
  misjudged, which makes them the most relevant. They're the only source
  of Followed/Ignored tags.
- **Any other SGF folder** via `--from`: pro games, strong-amateur games
  from your server, or your opponents' games. This gives more volume once
  your own deck runs low. "Followed"/"Ignored" tags only apply where the
  player of interest is in the game. Otherwise positions are tagged just
  Tenuki/Answer, from the perspective of whoever is to move.

## 4. The quiz

### Question flow (per position)

The board shows the position before your move, with the **opponent's last
move clearly marked**. That mark is the whole point: it's the thing
tempting you, so it should be visible.

**Step 1: "Where do you play?"** Click an intersection. Graded against a
**tolerant answer key**: any move with at least 10% of the root's visits
and a score within `max(1.0, 0.15 × |gap|)` points of the best counts as
correct, so playing a solid second-best point in the right area isn't
marked wrong. (The existing quiz only accepts the exact top move, which is
too strict for whole-board judgement.)

The local/tenuki judgement is **not** asked as a separate question. It's
still the thing being trained, but the answer key already enforces it: a
local move when tenuki was right simply isn't in the key. Asking it
out loud made the quiz slower without adding a constraint, and it let you
pass step 1 by guessing one of two buttons. The feedback still names the
side you played, so the habit stays visible.

**Step 2: "What's the score now?"** Asked **only when the move was
right** — a wrong move goes straight to the feedback. Type the score lead
from the mover's side; within `SCORE_TOLERANCE` (3.0) points counts as
correct.

This step is why the board **doesn't show the score lead before the
move**. The best move barely changes the score (measured: a position at
+3.4 goes to +3.38, one at +4.5 to +4.45), so showing the lead up front
would turn the question into reading a number back off the screen. The
true value, before and after, is revealed in the feedback.

Grading uses the score of the **move you actually played**, not the best
one, which is why the deck stores `accepted_scores` alongside `accepted`:
accepted moves can differ by a point or more (one position accepts K15 at
+1.45, H14 at +0.97 and B10 at +1.16).

**Step 3: Feedback.** Shown after step 2 and kept short:

- the type (Tenuki / Answer) and the gap: *"Answering locally cost 4.6
  points here"*;
- KataGo's best local move and best tenuki move, both marked on the board,
  each with its score, so you see *both* options and not only the answer;
- for Followed positions, your actual game move and what it cost;
- the existing "Deep analysis in LizzieYzy" button, unchanged.

The move and the score estimate are recorded as separate results. Getting
the move right and the score wrong is a normal stage of progress (you know
where to play but can't count the result yet), and the stats show it:
the scoreboard reads `Move 7/9 · Score 4/7`. Only the move feeds the spaced-repetition
state: a right move graduates the problem to the next box even if the
count was off, while a wrong move resets it to box 1 and brings it back.
Gating on both would mean one bad count re-serves the whole deck next
session.

### Session composition

The answer key must not be predictable. A session of `--limit N` is built
as:

- about **60% Tenuki** (Followed positions first),
- about **40% Answer** (Ignored positions first),
- **spread over the seed openings that are due**, and over the games within
  a seed,
- shuffled, and never more than 3 of the same type in a row.

The spread matters because the deck is rarely balanced across seeds: one
opening may have far more games probed, or simply throw bigger gaps. Taking
the top N of a purely points-lost ranking then serves a session of almost
nothing but that opening. Spreading first (`_spread_by_source`) gives each
due opening a share of the session while still preferring each opening's
own worst positions. A game can still contribute one Tenuki *and* one
Answer position -- those are different positions, at least `min_spacing`
moves apart, and the type ratio comes first.

If few tenuki positions are due, the session gets **shorter** rather than
being filled with answer-locally positions. A session that's mostly
"answer" would train the very reflex the drill is meant to break.

This ratio is a tunable constant (`--tenuki-share`). The adaptive rule
below is not implemented yet: and should change with your results. If
your step-1 accuracy on Answer positions falls below your accuracy on
Tenuki positions, you're overcorrecting, so the next session shifts toward
50/50. That one adaptive rule is enough. No need for anything more
elaborate.

### Scheduling

Reuse `quiz.py` as is: the 3-box scheme, `sync_new_problems`,
`record_result`. Two small changes:

- A separate deck and state file (`report/drill/index.json`,
  `report/drill_state.json`) with problem IDs like
  `drill::<game-stem>::m<n>`, so the drill and the mistake deck don't
  share or overwrite each other's review history.
- `record_result` is called with `correct = move_correct and
  score_correct`. Box progress needs both steps right; a right move whose
  score you skipped or missed brings the card back. Per-step stats are
  stored next to the box state, which the existing schema allows (it's a
  plain dict per entry).

`due_problems` sorts by `points_lost`. For drill entries, set that field to
`|gap|` so the most expensive positions come first among those due, and
apply the type mix above on top of that.

## 5. Habit metric in `report.md`: did your real games change?

Quiz accuracy shows you can *recognize* when to tenuki. It doesn't show
that you *do it* in real games. The real target is your games, so
`analyze` adds a short section:

```
### Middle-game initiative (moves 51–150)

                         You      KataGo's choice, same positions
Follow rate              78%      54%
Points lost following    9.4/game     —   (local move when tenuki was ≥2 pts better)
Points lost ignoring     1.1/game     —   (tenuki when an answer was ≥2 pts better)
```

- **Follow rate:** share of your middle-game moves that were local (§1).
  The comparison column is how often KataGo's top move was local in the
  same positions. The gap between the two numbers measures the habit
  directly. The goal is to close it, not reach 0%. Plenty of positions
  really do need an answer.
- **Points lost following / ignoring:** total gap, per game, over
  Followed and Ignored positions respectively. When the habit improves,
  the first number falls without the second one rising. If the second
  one rises, you're overcorrecting.

Shown with a rolling 10-game average, like the strength trend, and with the
same caution about small samples: under 8 games, it shows raw counts only
and draws no conclusions.

The follow rate only needs the cached analysis, not the probes. The
"points lost" lines need probes, so they cover games that `drill build`
has processed.

## 6. CLI

```powershell
baduk-lab drill generate --seeds seeds\ --games-per-seed 20   # self-play from seed openings (§2)
baduk-lab drill build --from selfplay\   # harvest + probe generated games
baduk-lab drill build                    # find candidates + probe your own new games (uses default_folder / aliases)
baduk-lab drill build --from pro-games\  # add positions from another folder
baduk-lab drill review --limit 20       # quiz session in the browser
baduk-lab drill --stats                  # (not yet) step-1 / step-2 accuracy by type, follow-rate trend
```

For your own games, `drill build` assumes `analyze` has been run on them
already (it needs the cached analysis) and errors with that hint if it
hasn't. That keeps `analyze` fast and only pays for probe queries when
you ask. For self-play folders, it reads each game's `.gen.json` instead
and re-analyzes only the eligible turns (passing just those turns in
`analyzeTurns`), so whole generated games are never fully analyzed.

`drill generate` is incremental: with 20 games already in
`selfplay/<seed>/`, `--games-per-seed 30` adds 10 more. Flags:
`--gen-visits`, `--loss-budget`, `--temperature`, `--human-profile
rank_3d`, `--stop-at 150`.

`drill build` flags: `--min-gap`, `--radius`, `--visits` (default: same as
`analyze`), `--score-window`.

## 7. Later extensions (not in the first version)

- **Human-style temptation score.** Run the HumanSL model
  (`b18c384nbt-humanv0`, `humanSLProfile = "rank_<your rank>"`) on each
  candidate and record how much of a player-at-your-rank's policy goes to
  local moves. Positions where most of it is local *and* the right answer
  is tenuki are the most tempting ones, so show those first. Your rank can
  come from the existing strength estimate. Needs a non-TensorRT KataGo
  for the human net (see LIZZIE_UI_SETUP.md), so it's optional.
- **Opponent-to-move positions** ("your opponent just ignored your move.
  Should they have?"). This doubles the volume from your own games and
  trains the same judgement from the other side.
- **Region-first answering.** Split the board into a 3×3 grid and ask
  "which area?" before "which point?", for when step 2 is still too hard.
- **Ownership overlay** in feedback (`includeOwnership` on the probe),
  showing *what* the local answer would have protected, so "it was only
  worth 2 points" can be seen on the board.

## Implementation order

1. Locality classifier + follow-rate section in `report.md`. No new
   engine calls. It immediately tells you how big the habit is, and gives
   a baseline before you start drilling.
2. Probe query in `engine.py` (one new method, its own cache), candidate
   finder + selection in a new `drill.py`, `drill build`.
3. Self-play generator (`selfplay.py`, `drill generate`): seed loading
   with variations, sampling + balancing loop, `.gen.json` output, and
   harvesting from the ±10-point window in `drill build`. The balancing
   rule is tested with a fake engine whose score is scripted, so it's
   checked without KataGo. **(Done.)**
4. HTML drill page: a fork of `quiz_html.py` with the move-then-score
   flow and two-move feedback, served through the existing
   `_serve_and_open`.
5. Session mix + adaptive ratio, `drill --stats`, "points lost following"
   lines in the report.

Each step gets unit tests in the style of `tests/test_metrics.py` /
`tests/test_quiz.py`, using `tests/factories.py` to build positions with a
known best move on each side.
