"""Per-game strength estimate: a Python port of LizzieYzy Next's
PlayerStrengthEstimator / XGBoostStrengthModel / XGBoost20TunResidualCalibrator
(https://github.com/wimi321/lizzieyzy-next, GPLv3 -- see
models/strength/NOTICE.md for why that matters for this file specifically).

This is a from-scratch reimplementation of their formulas and thresholds
against baduk-lab's own data model, not a translation of their Java files.
The underlying trained model (models/strength/xgboost20tun_booster.json) and
its small residual calibrator are used unmodified -- there's no retraining
here, just feeding them the same 20 features they were trained on.

Pipeline, per side (color) of one game:

1. Turn each move into a Sample: how many points it cost (preferring a
   same-search comparison against the position's own top candidate when the
   played move is among the analyzed candidates, falling back to the
   before/after score-lead diff otherwise), whether it was engine's #1
   choice, its rank among analyzed candidates, a move-quality category
   (EXCELLENT..BLUNDER), and a policy-weighted "complexity" of the position
   it was played in.
2. Aggregate samples into ~20 named features (rates, loss percentiles,
   phase splits, difficulty-interaction terms) -- see _feature_vector.
3. Run those through the vendored XGBoost booster to get a raw rank value,
   nudge it with the small residual calibrator, then run a second,
   rule-based guardrail layer (metric caps, elite-evidence floors,
   tail-loss caps) to get a discrete strength band -- this second layer is
   deliberately conservative and is usually the more trustworthy number for
   sub-dan players, since the training data (Fox 1-9 dan, pro games, KataGo
   self-play) never covered kyu-level play; the raw model score bottoms out
   around 1-2 kyu regardless of how weak the actual play is.

For review reference only -- not a rating, and the confidence label matters:
short games (few dozen moves) should be read as noise, not signal.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from .engine import GameAnalysis, PositionAnalysis

_MODELS_DIR = Path(__file__).resolve().parent / "models" / "strength"
_BOOSTER_PATH = _MODELS_DIR / "xgboost20tun_booster.json"
_CALIBRATOR_PATH = _MODELS_DIR / "xgboost20tun_residual_calibrator.json"

# --- Move-quality thresholds (score-equivalent points lost) ----------------
EXCELLENT_LOSS = 0.2
GREAT_LOSS = 0.6
GOOD_LOSS = 1.2
INACCURACY_LOSS = 4.0
MISTAKE_LOSS = 10.0

WINRATE_TO_SCORE_LOSS = 6.0     # winrate points (0-1 scale) -> board points
MIN_DIFFICULTY_WEIGHT = 0.05
NOT_IN_CANDIDATES = 999         # sentinel rank for "played move wasn't analyzed"
AI_RANK_CAP = 10

# Move-number boundaries the upstream model was trained against -- distinct
# from metrics.py's OPENING_END/MIDDLE_END, which are baduk-lab's own choice
# for its unrelated phase-loss report.
OPENING_END = 60
MIDDLE_END = 160

MIN_REPORT_SAMPLES = 6
MIN_RANK_VALUE = -1.0
MAX_RANK_VALUE = 12.0

# How many trailing games report.py's markdown table and strength_chart.py's
# graph both average over -- shared here so the two can't drift apart.
ROLLING_WINDOW = 10

STRENGTH_BANDS = [
    "Beginner", "11-15k", "6-10k", "3-5k", "1-2k", "1-2d", "3-4d", "5-6d",
    "7d", "8d", "9d", "10d pro", "11d top pro", "12d AI",
]

STRONG_KYU_LEVEL = 4
LOW_DAN_LEVEL = 6
MID_DAN_LEVEL = 7
HIGH_DAN_LEVEL = 9
LOW_DIFFICULTY_EVIDENCE = 25.0
LOW_DIFFICULTY_TOP_FIRST_CHOICE_RATE = 0.35
LOW_DIFFICULTY_TOP_GOOD_MOVE_RATE = 0.74
TOP_PRO_FIRST_CHOICE_RATE = 0.50
TOP_PRO_GOOD_MOVE_RATE = 0.86
TOP_PRO_MISTAKE_RATE = 0.05
TOP_PRO_WEIGHTED_LOSS = 3.20
PRO_FIRST_CHOICE_RATE = 0.45
PRO_GOOD_MOVE_RATE = 0.86
PRO_MISTAKE_RATE = 0.06
PRO_WEIGHTED_LOSS = 3.00

# (threshold, level) pairs, checked in order; "at least" tables list highest
# threshold first, "at most" tables list lowest threshold first.
FIRST_CHOICE_CAPS = [
    (0.62, 13), (0.50, 12), (0.46, 11), (0.42, 10), (0.38, 9), (0.34, 8),
    (0.30, 7), (0.24, 7), (0.18, 6), (0.12, 5), (0.06, 4),
]
GOOD_MOVE_CAPS = [
    (0.96, 13), (0.88, 12), (0.82, 11), (0.78, 10), (0.74, 9), (0.68, 8),
    (0.62, 7), (0.56, 6), (0.50, 5), (0.42, 4), (0.32, 3), (0.22, 2),
]
MATCH_RATE_CAPS = [
    (0.80, 13), (0.70, 12), (0.62, 11), (0.58, 10), (0.54, 9), (0.49, 8),
    (0.43, 7), (0.37, 6), (0.30, 5), (0.22, 4), (0.14, 3),
]
MISTAKE_RATE_CAPS = [
    (0.005, 13), (0.050, 12), (0.060, 11), (0.070, 10), (0.100, 9),
    (0.140, 8), (0.180, 7), (0.240, 6), (0.310, 5), (0.400, 4),
    (0.520, 3), (0.660, 2),
]
MEDIAN_LOSS_CAPS = [
    (0.05, 13), (0.25, 12), (0.50, 11), (0.80, 10), (1.10, 9), (1.50, 8),
    (2.00, 7), (2.60, 6), (3.40, 5), (4.60, 4), (6.50, 3), (9.00, 2),
]

# Order the vendored booster's feature_names were trained on -- selected
# from the 29 named features below by index (see FULL29_NAMES).
FULL29_NAMES = [
    "first_choice_rate", "top3_rate", "top5_rate", "average_ai_rank_fit",
    "excellent_rate", "good_move_rate", "non_inaccuracy_rate", "match_rate",
    "non_mistake_rate", "non_blunder_rate", "weighted_loss_fit",
    "average_loss_fit", "median_loss_fit", "p75_loss_fit", "p90_loss_fit",
    "p95_loss_fit", "max_loss_fit", "loss_stability_fit", "difficulty_fit",
    "opening_loss_fit", "middlegame_loss_fit", "endgame_loss_fit",
    "opening_good_move_rate", "middlegame_good_move_rate",
    "endgame_good_move_rate", "first_choice_x_difficulty",
    "good_move_x_difficulty", "match_x_difficulty", "top5_x_difficulty",
]
XGBOOST20TUN_INDICES = [13, 5, 2, 19, 10, 20, 26, 3, 14, 11, 28, 8, 18, 7, 12, 23, 27, 22, 25, 0]


class MoveCategory(Enum):
    EXCELLENT = "excellent"
    GREAT = "great"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"

    @property
    def is_good(self) -> bool:
        return self in (MoveCategory.EXCELLENT, MoveCategory.GREAT, MoveCategory.GOOD)

    @property
    def is_mistake(self) -> bool:
        return self in (MoveCategory.MISTAKE, MoveCategory.BLUNDER)


@dataclass
class Sample:
    move_number: int
    loss: float              # score-equivalent points lost, clamped >= 0
    first_choice: bool
    ai_rank: int              # rank among analyzed candidates, or NOT_IN_CANDIDATES
    category: MoveCategory
    complexity: float         # 0..1, policy-weighted sharpness of the position
    adjusted_weight: float    # 0.05..1, how much this move counts toward "weighted loss"


@dataclass
class SideEstimate:
    sample_count: int
    score_sample_count: int
    confidence: str                # "low" | "medium" | "high"
    rank_value: float | None       # raw+calibrated model output, None if no model/xgboost
    quality_score: float | None    # rank_value rescaled to 0-100, None alongside rank_value
    strength_band: str             # coarse, guardrail-driven label (always available)
    rank_label: str | None         # "5.3 dan" / "2.1 kyu" / "10.4 pro" style, None if no rank_value
    first_choice_rate: float
    good_move_rate: float
    mistake_rate: float
    weighted_point_loss: float
    average_point_loss: float
    match_rate: float


@dataclass
class GameStrengthEstimate:
    black: SideEstimate | None
    white: SideEstimate | None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)


def _positive(value: float) -> float:
    return max(0.0, value)


def _median(values: list[float]) -> float:
    values = sorted(values)
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    position = fraction * (len(values) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return values[int(lower)]
    weight = position - lower
    return values[int(lower)] * (1.0 - weight) + values[int(upper)] * weight


def _population_stddev(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _candidate(best_moves: list[dict], vertex: str) -> tuple[int, dict] | None:
    for index, move in enumerate(best_moves):
        if move.get("move", "").upper() == vertex.upper():
            return index, move
    return None


def _candidate_loss(top: dict, actual: dict) -> float | None:
    """Points `actual` costs relative to `top`, from whoever's to move --
    both candidates come from the same search, so no color-flip is needed."""
    top_score, actual_score = top.get("scoreMean"), actual.get("scoreMean")
    if top_score is not None and actual_score is not None:
        return top_score - actual_score
    top_wr, actual_wr = top.get("winrate"), actual.get("winrate")
    if top_wr is not None and actual_wr is not None:
        return (top_wr - actual_wr) / WINRATE_TO_SCORE_LOSS
    return None


def _complexity(best_moves: list[dict]) -> float:
    """Policy-weighted average loss among a position's analyzed candidates,
    capped at 1.0 -- near 0 in calm positions where every reasonable move is
    about as good, closer to 1 when only one move avoids a real cost."""
    if not best_moves:
        return 0.0
    top = best_moves[0]
    weighted_loss_sum = prior_sum = 0.0
    for move in best_moves:
        prior = max(0.0, move.get("prior") or 0.0)
        if prior <= 0.0:
            continue
        loss = _candidate_loss(top, move)
        if loss is None:
            continue
        weighted_loss_sum += _positive(loss) * prior
        prior_sum += prior
    if prior_sum > 0.0:
        return _clamp(weighted_loss_sum / prior_sum, 0.0, 1.0)
    if len(best_moves) >= 2:
        loss = _candidate_loss(top, best_moves[1])
        if loss is not None:
            return _clamp(_positive(loss) / GOOD_LOSS, 0.0, 1.0)
    return 0.0


def _categorize(loss: float) -> MoveCategory:
    loss = _positive(loss)
    if loss < EXCELLENT_LOSS:
        return MoveCategory.EXCELLENT
    if loss < GREAT_LOSS:
        return MoveCategory.GREAT
    if loss < GOOD_LOSS:
        return MoveCategory.GOOD
    if loss < INACCURACY_LOSS:
        return MoveCategory.INACCURACY
    if loss < MISTAKE_LOSS:
        return MoveCategory.MISTAKE
    return MoveCategory.BLUNDER


def _sample(analysis: GameAnalysis, move_number: int, played_vertex: str) -> Sample | None:
    previous = analysis.position_at(move_number)
    if previous is None or not previous.best_moves:
        return None
    best_moves = previous.best_moves
    top = best_moves[0]
    found = _candidate(best_moves, played_vertex)

    loss = None
    ai_rank = NOT_IN_CANDIDATES
    if found is not None:
        ai_rank, actual = found
        loss = _candidate_loss(top, actual)
    if loss is None:
        fallback = analysis.points_lost(move_number)
        if fallback is None:
            return None
        loss = fallback
    loss = _positive(loss)

    complexity = _complexity(best_moves)
    adjusted_weight = _clamp(max(complexity, loss / INACCURACY_LOSS), MIN_DIFFICULTY_WEIGHT, 1.0)
    first_choice = played_vertex.upper() == top.get("move", "").upper()
    return Sample(
        move_number=move_number,
        loss=loss,
        first_choice=first_choice,
        ai_rank=ai_rank,
        category=_categorize(loss),
        complexity=complexity,
        adjusted_weight=adjusted_weight,
    )


def _samples_for_color(analysis: GameAnalysis, color: str) -> list[Sample]:
    from sgfmill.common import format_vertex

    samples = []
    for move in analysis.record.moves:
        if move.color != color:
            continue
        if move.coord is None:  # passes carry no candidate list to compare against
            continue
        sample = _sample(analysis, move.number, format_vertex(move.coord))
        if sample is not None:
            samples.append(sample)
    return samples


def _capped_ai_rank(sample: Sample) -> float:
    if sample.ai_rank >= NOT_IN_CANDIDATES:
        return float(AI_RANK_CAP)
    return min(sample.ai_rank + 1.0, AI_RANK_CAP)


def _match_rate(first_choice_rate: float, good_move_rate: float, mistake_rate: float) -> float:
    return _clamp01(0.45 * first_choice_rate + 0.45 * good_move_rate + 0.10 * (1.0 - mistake_rate))


def _phase_weighted_loss(samples: list[Sample], fallback: float) -> float:
    if not samples:
        return fallback
    weighted = sum(s.loss * s.adjusted_weight for s in samples)
    weight = sum(s.adjusted_weight for s in samples)
    return weighted / weight if weight > 0.0 else fallback


def _phase_good_move_rate(samples: list[Sample], fallback: float) -> float:
    if not samples:
        return fallback
    return sum(1 for s in samples if s.category.is_good) / len(samples)


@dataclass
class _Aggregate:
    sample_count: int
    score_sample_count: int
    weighted_point_loss: float
    average_point_loss: float
    median_point_loss: float
    p75: float
    p90: float
    p95: float
    max_loss: float
    loss_stddev: float
    difficulty: float
    opening_weighted_loss: float
    middlegame_weighted_loss: float
    endgame_weighted_loss: float
    opening_good_move_rate: float
    middlegame_good_move_rate: float
    endgame_good_move_rate: float
    first_choice_rate: float
    top3_rate: float
    top5_rate: float
    average_ai_rank: float
    excellent_rate: float
    good_move_rate: float
    inaccuracy_rate: float
    mistake_rate: float
    blunder_rate: float
    match_rate: float


def _aggregate(samples: list[Sample]) -> _Aggregate | None:
    if not samples:
        return None
    n = len(samples)
    losses = [s.loss for s in samples]
    opening = [s for s in samples if s.move_number <= OPENING_END]
    middlegame = [s for s in samples if OPENING_END < s.move_number <= MIDDLE_END]
    endgame = [s for s in samples if s.move_number > MIDDLE_END]

    weighted_sum = sum(s.loss * s.adjusted_weight for s in samples)
    weight_sum = sum(s.adjusted_weight for s in samples)
    average_point_loss = sum(losses) / n
    weighted_point_loss = weighted_sum / weight_sum if weight_sum > 0.0 else average_point_loss

    first_choice_rate = sum(1 for s in samples if s.first_choice) / n
    top3_rate = sum(1 for s in samples if s.ai_rank < 3) / n
    top5_rate = sum(1 for s in samples if s.ai_rank < 5) / n
    excellent_rate = sum(1 for s in samples if s.category == MoveCategory.EXCELLENT) / n
    good_move_rate = sum(1 for s in samples if s.category.is_good) / n
    inaccuracy_rate = sum(1 for s in samples if s.category == MoveCategory.INACCURACY) / n
    mistake_rate = sum(1 for s in samples if s.category.is_mistake) / n
    blunder_rate = sum(1 for s in samples if s.category == MoveCategory.BLUNDER) / n
    match_rate = _match_rate(first_choice_rate, good_move_rate, mistake_rate)
    average_ai_rank = sum(_capped_ai_rank(s) for s in samples) / n
    median_point_loss = _median(losses)

    return _Aggregate(
        sample_count=n,
        score_sample_count=n,  # baduk-lab's engine always yields a score-based loss
        weighted_point_loss=weighted_point_loss,
        average_point_loss=average_point_loss,
        median_point_loss=median_point_loss,
        p75=_percentile(losses, 0.75),
        p90=_percentile(losses, 0.90),
        p95=_percentile(losses, 0.95),
        max_loss=max(losses),
        loss_stddev=_population_stddev(losses),
        difficulty=sum(s.complexity for s in samples) * 100.0 / n,
        opening_weighted_loss=_phase_weighted_loss(opening, weighted_point_loss),
        middlegame_weighted_loss=_phase_weighted_loss(middlegame, weighted_point_loss),
        endgame_weighted_loss=_phase_weighted_loss(endgame, weighted_point_loss),
        opening_good_move_rate=_phase_good_move_rate(opening, good_move_rate),
        middlegame_good_move_rate=_phase_good_move_rate(middlegame, good_move_rate),
        endgame_good_move_rate=_phase_good_move_rate(endgame, good_move_rate),
        first_choice_rate=first_choice_rate,
        top3_rate=top3_rate,
        top5_rate=top5_rate,
        average_ai_rank=average_ai_rank,
        excellent_rate=excellent_rate,
        good_move_rate=good_move_rate,
        inaccuracy_rate=inaccuracy_rate,
        mistake_rate=mistake_rate,
        blunder_rate=blunder_rate,
        match_rate=match_rate,
    )


def _loss_fit(loss: float, cap: float) -> float:
    return 1.0 / (1.0 + _clamp(_positive(loss), 0.0, cap))


def _full29_features(agg: _Aggregate) -> list[float]:
    difficulty = _clamp((agg.difficulty - 25.0) / 35.0, 0.0, 1.0)
    first_choice = _clamp01(agg.first_choice_rate)
    top5 = _clamp01(agg.top5_rate)
    good_move = _clamp01(agg.good_move_rate)
    match = _clamp01(agg.match_rate)
    return [
        first_choice,
        _clamp01(agg.top3_rate),
        top5,
        1.0 / (1.0 + _clamp(agg.average_ai_rank, 0.0, 10.0)),
        _clamp01(agg.excellent_rate),
        good_move,
        1.0 - _clamp01(agg.inaccuracy_rate),
        match,
        1.0 - _clamp01(agg.mistake_rate),
        1.0 - _clamp01(agg.blunder_rate),
        _loss_fit(agg.weighted_point_loss, 50.0),
        _loss_fit(agg.average_point_loss, 50.0),
        _loss_fit(agg.median_point_loss, 50.0),
        _loss_fit(agg.p75, 50.0),
        _loss_fit(agg.p90, 80.0),
        _loss_fit(agg.p95, 100.0),
        _loss_fit(agg.max_loss, 120.0),
        _loss_fit(agg.loss_stddev, 50.0),
        difficulty,
        _loss_fit(agg.opening_weighted_loss, 50.0),
        _loss_fit(agg.middlegame_weighted_loss, 50.0),
        _loss_fit(agg.endgame_weighted_loss, 50.0),
        _clamp01(agg.opening_good_move_rate),
        _clamp01(agg.middlegame_good_move_rate),
        _clamp01(agg.endgame_good_move_rate),
        first_choice * difficulty,
        good_move * difficulty,
        match * difficulty,
        top5 * difficulty,
    ]


@lru_cache(maxsize=1)
def _load_booster():
    if not _BOOSTER_PATH.exists():
        return None
    try:
        import xgboost as xgb
    except ImportError:
        return None
    booster = xgb.Booster()
    booster.load_model(str(_BOOSTER_PATH))
    return booster


@lru_cache(maxsize=1)
def _load_calibrator() -> dict | None:
    if not _CALIBRATOR_PATH.exists():
        return None
    return json.loads(_CALIBRATOR_PATH.read_text(encoding="utf-8"))


def _predict_rank_value(full29: list[float]) -> float | None:
    booster = _load_booster()
    if booster is None:
        return None
    import xgboost as xgb

    selected = [full29[i] for i in XGBOOST20TUN_INDICES]
    names = [FULL29_NAMES[i] for i in XGBOOST20TUN_INDICES]
    dmatrix = xgb.DMatrix([selected], feature_names=names)
    base_prediction = float(booster.predict(dmatrix)[0])
    return _apply_calibrator(base_prediction, full29)


def _apply_calibrator(base_prediction: float, full29: list[float]) -> float:
    calibrator = _load_calibrator()
    if not calibrator:
        return _clamp(base_prediction, MIN_RANK_VALUE, MAX_RANK_VALUE)

    spec = calibrator["final_spec"]
    fc = calibrator["final_calibrator"]
    feature_order = fc["feature_order"]
    scaler_mean = fc["scaler_mean"]
    scaler_scale = fc["scaler_scale"]

    raw_correction = fc["intercept"]
    for name, mean, scale, coef in zip(feature_order, scaler_mean, scaler_scale, fc["coefficients"]):
        value = _calibrator_feature_value(name, base_prediction, full29)
        if value is None or not math.isfinite(value):
            return _clamp(base_prediction, MIN_RANK_VALUE, MAX_RANK_VALUE)
        scale = scale if scale != 0.0 else 1.0
        raw_correction += coef * ((value - mean) / scale)

    gate_start, gate_full = spec["gate_start"], spec["gate_full"]
    rank_gate = _clamp01((base_prediction - gate_start) / max(gate_full - gate_start, 1e-9))
    quality_gate = _quality_gate(calibrator.get("quality_gate_thresholds", {}), full29)
    correction = rank_gate * quality_gate * _clamp(
        raw_correction, spec["correction_min"], spec["correction_max"])
    return _clamp(base_prediction + correction, MIN_RANK_VALUE, MAX_RANK_VALUE)


def _calibrator_feature_value(name: str, base_prediction: float, full29: list[float]) -> float | None:
    if name == "base_prediction":
        return base_prediction
    if name.startswith("hinge_above_"):
        try:
            threshold = float(name[len("hinge_above_"):])
        except ValueError:
            return None
        return max(0.0, base_prediction - threshold)
    named = {
        "match_rate": full29[FULL29_NAMES.index("match_rate")],
        "first_choice_rate": full29[FULL29_NAMES.index("first_choice_rate")],
        "top5_rate": full29[FULL29_NAMES.index("top5_rate")],
        "weighted_loss_fit": full29[FULL29_NAMES.index("weighted_loss_fit")],
        "difficulty_fit": full29[FULL29_NAMES.index("difficulty_fit")],
    }
    return named.get(name)


def _gate_value(value: float, threshold: list[float]) -> float:
    if not threshold or len(threshold) < 2:
        return 0.0
    lo, hi = threshold
    return _clamp01((value - lo) / max(hi - lo, 1e-9))


def _quality_gate(thresholds: dict, full29: list[float]) -> float:
    match_rate = full29[FULL29_NAMES.index("match_rate")]
    top5_rate = full29[FULL29_NAMES.index("top5_rate")]
    weighted_loss_fit = full29[FULL29_NAMES.index("weighted_loss_fit")]
    return max(
        _gate_value(match_rate, thresholds.get("match_rate", [])),
        _gate_value(top5_rate, thresholds.get("top5_rate", [])),
        _gate_value(weighted_loss_fit, thresholds.get("weighted_loss_fit", [])),
    )


def _rank_value_to_quality_score(rank_value: float) -> float:
    return _clamp((rank_value + 18.0) * 100.0 / 30.0, 0.0, 100.0)


# Descending (rank_value lower-bound, level) pairs -- level N covers
# [thresholds[i], thresholds[i-1]). Hoisted to module level (not just local
# to _level_from_rank_value) so band_boundaries() can derive chart reference
# lines from the same numbers instead of a second hardcoded copy.
RANK_LEVEL_THRESHOLDS = [
    (11.5, 13), (10.5, 12), (9.5, 11), (8.5, 10), (7.5, 9), (6.5, 8),
    (4.5, 7), (2.5, 6), (0.0, 5), (-2.75, 4), (-6.0, 3), (-10.5, 2), (-15.5, 1),
]


def _level_from_rank_value(rank_value: float) -> int:
    for threshold, level in RANK_LEVEL_THRESHOLDS:
        if rank_value >= threshold:
            return level
    return 0


def band_boundaries() -> list[tuple[float, str]]:
    """(rank_value lower bound, band label) pairs in ascending order, for
    everything except the unbounded bottom band ("Beginner") -- useful as
    reference lines/labels on a rank-value-over-time chart."""
    return [(value, STRENGTH_BANDS[level]) for value, level in reversed(RANK_LEVEL_THRESHOLDS)]


def rolling_average(values: list[float], window: int) -> list[float]:
    """values[i]'s trailing average over the last `window` entries up to
    and including i (fewer than `window` at the start)."""
    out = []
    buffer: list[float] = []
    for value in values:
        buffer.append(value)
        if len(buffer) > window:
            buffer.pop(0)
        out.append(sum(buffer) / len(buffer))
    return out


def _level_at_least(value: float, table: list[tuple[float, int]], fallback: int) -> int:
    for threshold, level in table:
        if value >= threshold:
            return level
    return fallback


def _level_at_most(value: float, table: list[tuple[float, int]], fallback: int) -> int:
    for threshold, level in table:
        if value <= threshold:
            return level
    return fallback


def _base_level(quality_score: float) -> int:
    return _level_from_rank_value(-18.0 + _clamp(quality_score, 0.0, 100.0) * 30.0 / 100.0)


def _elite_evidence_level(weighted_point_loss: float, first_choice_rate: float,
                          good_move_rate: float, mistake_rate: float) -> int:
    if (first_choice_rate >= TOP_PRO_FIRST_CHOICE_RATE and good_move_rate >= TOP_PRO_GOOD_MOVE_RATE
            and mistake_rate <= TOP_PRO_MISTAKE_RATE and weighted_point_loss <= TOP_PRO_WEIGHTED_LOSS):
        return 12
    if (first_choice_rate >= PRO_FIRST_CHOICE_RATE and good_move_rate >= PRO_GOOD_MOVE_RATE
            and mistake_rate <= PRO_MISTAKE_RATE and weighted_point_loss <= PRO_WEIGHTED_LOSS):
        return 11
    return 0


def _evidence_cap_level(weighted_point_loss: float, first_choice_rate: float,
                        good_move_rate: float) -> int:
    cap = 13
    if good_move_rate < 0.50 and first_choice_rate < 0.22:
        cap = min(cap, STRONG_KYU_LEVEL)
    if good_move_rate < 0.62 and first_choice_rate < 0.30:
        cap = min(cap, STRONG_KYU_LEVEL)
    if weighted_point_loss > 7.50 and first_choice_rate < 0.26:
        cap = min(cap, STRONG_KYU_LEVEL)
    if weighted_point_loss >= 2.90 and first_choice_rate < 0.34 and good_move_rate < 0.78:
        cap = min(cap, LOW_DAN_LEVEL)
    return cap


def _metric_cap_level(weighted_point_loss: float, median_point_loss: float,
                      first_choice_rate: float, good_move_rate: float,
                      mistake_rate: float, match_rate: float) -> int:
    cap = 13
    cap = min(cap, _level_at_least(first_choice_rate, FIRST_CHOICE_CAPS, LOW_DAN_LEVEL))
    cap = min(cap, _level_at_least(good_move_rate, GOOD_MOVE_CAPS, 1))
    cap = min(cap, _level_at_least(match_rate, MATCH_RATE_CAPS, 2))
    cap = min(cap, _level_at_most(mistake_rate, MISTAKE_RATE_CAPS, 1))
    cap = min(cap, _level_at_most(median_point_loss, MEDIAN_LOSS_CAPS, 1))
    cap = min(cap, _evidence_cap_level(weighted_point_loss, first_choice_rate, good_move_rate))
    return cap


def _tail_loss_cap(weighted_point_loss: float, average_point_loss: float,
                   median_point_loss: float, p90_point_loss: float, match_rate: float) -> int:
    cap = 13
    if p90_point_loss > 8.0 and average_point_loss > 2.8 and match_rate < 0.55:
        cap = min(cap, MID_DAN_LEVEL)
    if p90_point_loss > 5.5 and median_point_loss > 1.0 and match_rate < 0.50:
        cap = min(cap, LOW_DAN_LEVEL)
    if weighted_point_loss > 4.8 and average_point_loss > 3.0 and match_rate < 0.45:
        cap = min(cap, STRONG_KYU_LEVEL)
    return cap


def _evidence_adjusted_level(level: int, first_choice_rate: float, good_move_rate: float,
                             average_difficulty: float) -> int:
    if (level >= HIGH_DAN_LEVEL and average_difficulty < LOW_DIFFICULTY_EVIDENCE
            and first_choice_rate < LOW_DIFFICULTY_TOP_FIRST_CHOICE_RATE
            and good_move_rate < LOW_DIFFICULTY_TOP_GOOD_MOVE_RATE):
        return min(level, MID_DAN_LEVEL)
    return level


def _low_confidence_adjusted_level(level: int, sample_count: int, weighted_point_loss: float) -> int:
    if sample_count < MIN_REPORT_SAMPLES and level == 0 and weighted_point_loss <= MISTAKE_LOSS:
        return 1
    return level


def _strength_band(agg: _Aggregate, quality_score: float | None) -> str:
    base = _base_level(quality_score) if quality_score is not None else 0
    base = max(base, _elite_evidence_level(
        agg.weighted_point_loss, agg.first_choice_rate, agg.good_move_rate, agg.mistake_rate))
    level = min(base, _metric_cap_level(
        agg.weighted_point_loss, agg.median_point_loss, agg.first_choice_rate,
        agg.good_move_rate, agg.mistake_rate, agg.match_rate))
    level = min(level, _tail_loss_cap(
        agg.weighted_point_loss, agg.average_point_loss, agg.median_point_loss,
        agg.p90, agg.match_rate))
    level = _evidence_adjusted_level(level, agg.first_choice_rate, agg.good_move_rate, agg.difficulty)
    level = _low_confidence_adjusted_level(level, agg.sample_count, agg.weighted_point_loss)
    return STRENGTH_BANDS[level]


def _rank_label(rank_value: float) -> str:
    value = _clamp(rank_value, MIN_RANK_VALUE, MAX_RANK_VALUE)
    if value >= 12.0:
        return f"{value:.1f} AI"
    if value >= 11.0:
        return f"{value:.1f} top pro"
    if value >= 10.0:
        return f"{value:.1f} pro"
    if value >= 1.0:
        return f"{value:.1f} dan"
    kyu_value = max(1.0, 2.0 - value)
    return f"{kyu_value:.1f} kyu"


def _confidence(sample_count: int) -> str:
    if sample_count >= 40:
        return "high"
    if sample_count >= 16:
        return "medium"
    return "low"


def estimate_side(analysis: GameAnalysis, color: str) -> SideEstimate | None:
    """Strength estimate for one color's moves in one game, or None if there
    weren't enough analyzed positions to say anything (e.g. an all-pass or
    unanalyzed game)."""
    samples = _samples_for_color(analysis, color)
    agg = _aggregate(samples)
    if agg is None:
        return None

    full29 = _full29_features(agg)
    rank_value = _predict_rank_value(full29)
    quality_score = _rank_value_to_quality_score(rank_value) if rank_value is not None else None
    rank_label = _rank_label(rank_value) if rank_value is not None else None

    return SideEstimate(
        sample_count=agg.sample_count,
        score_sample_count=agg.score_sample_count,
        confidence=_confidence(agg.sample_count),
        rank_value=rank_value,
        quality_score=quality_score,
        strength_band=_strength_band(agg, quality_score),
        rank_label=rank_label,
        first_choice_rate=agg.first_choice_rate,
        good_move_rate=agg.good_move_rate,
        mistake_rate=agg.mistake_rate,
        weighted_point_loss=agg.weighted_point_loss,
        average_point_loss=agg.average_point_loss,
        match_rate=agg.match_rate,
    )


def estimate_game(analysis: GameAnalysis) -> GameStrengthEstimate:
    """Strength estimate for both colors in one game."""
    return GameStrengthEstimate(
        black=estimate_side(analysis, "b"),
        white=estimate_side(analysis, "w"),
    )
