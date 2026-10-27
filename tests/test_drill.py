import collections
import random

from sgfmill.common import move_from_vertex

from baduk_lab import drill
from baduk_lab.drill import DrillProblem, compose_session, evaluate, local_region


def _c(vertex):
    return move_from_vertex(vertex, 19)


def _mi(move, score, order, visits=100):
    return {"move": move, "scoreLead": score, "order": order, "visits": visits}


def test_local_region_is_radius_around_last_move():
    last = _c("K10")
    region = local_region({last: "w"}, last, 19, radius=3)
    assert _c("N13") in region and _c("G7") in region
    assert _c("O10") not in region  # 4 columns away
    assert last not in region       # occupied


def test_local_region_follows_liberties_of_touched_group():
    # A long black wall touching the last white move: its liberties a bit
    # beyond the radius still count as answering, up to group_reach.
    last = _c("K10")
    stones = {last: "w"}
    for col in "LMNOP":
        stones[_c(f"{col}11")] = "b"
    stones[_c("K11")] = "b"
    region = local_region(stones, last, 19, radius=2, group_reach=5)
    assert _c("O12") in region      # 4 away: only reachable via the group's liberties
    assert _c("O8") not in region   # 4 away, not next to the group


def test_evaluate_tenuki_position():
    region = {_c("K10"), _c("K11")}
    unrestricted = [_mi("Q16", 3.0, 0), _mi("R16", 2.6, 1, visits=40), _mi("K10", -1.0, 2)]
    probe = [_mi("K10", -1.0, 0)]  # forced local
    v = evaluate(unrestricted, probe, "b", region, 19)
    assert v["gap"] == 4.0
    assert v["best_tenuki"] == "Q16" and v["best_local"] == "K10"
    assert v["accepted"] == ["Q16", "R16"]
    # The score quiz grades against the score of the move actually played,
    # not just the best one, so every accepted move carries its own.
    assert v["accepted_scores"] == [3.0, 2.6]


def test_evaluate_answer_position_for_white():
    # White to move; Black-perspective scores, so White prefers lower.
    region = {_c("K10"), _c("K11")}
    unrestricted = [_mi("K11", -2.0, 0), _mi("K10", -1.5, 1, visits=30)]
    probe = [_mi("Q16", 1.0, 0)]  # forced tenuki
    v = evaluate(unrestricted, probe, "w", region, 19)
    assert v["gap"] == -3.0
    assert v["best_local"] == "K11"
    assert set(v["accepted"]) == {"K11", "K10"}
    # White's perspective: Black-perspective -2.0 is +2.0 for White.
    assert dict(zip(v["accepted"], v["accepted_scores"])) == {"K11": 2.0, "K10": 1.5}


def test_evaluate_never_accepts_a_move_on_the_wrong_side():
    region = {_c("K10")}
    unrestricted = [_mi("Q16", 3.0, 0), _mi("K10", 2.9, 1)]  # local move close in score
    probe = [_mi("K10", 0.5, 0)]
    v = evaluate(unrestricted, probe, "b", region, 19)
    assert v["accepted"] == ["Q16"]
    assert v["accepted_scores"] == [3.0]


def _p(i, kind, seed="s", game=None, gap=3.0):
    return DrillProblem(problem_id=f"p{i}", game=game or f"{seed}/g001", seed=seed,
                        move_number=60 + i,
                        mover="b", kind=kind, gap=gap, points_lost=abs(gap), score_lead=0.0,
                        last_move="K10", best_local="K11", best_local_score=0.0,
                        best_tenuki="Q16", best_tenuki_score=3.0, accepted=["Q16"],
                        accepted_scores=[3.0], region=["K11"], path="x")


def test_compose_session_mix_and_no_long_runs():
    due = [_p(i, "tenuki") for i in range(30)] + [_p(100 + i, "answer") for i in range(30)]
    for seed in range(20):
        session = compose_session(due, 20, tenuki_share=0.6, rng=random.Random(seed))
        kinds = [p.kind for p in session]
        assert kinds.count("tenuki") == 12 and kinds.count("answer") == 8
        assert all(len(set(kinds[i:i + 4])) > 1 for i in range(len(kinds) - 3))


def test_compose_session_spreads_over_seeds_not_just_biggest_gaps():
    # One seed hogs the biggest gaps and has far more problems built, which
    # is exactly what a pure points-lost ranking would serve 20 of.
    due = ([_p(i, "tenuki", seed="hog", game=f"hog/g{i:03d}", gap=20.0) for i in range(40)]
           + [_p(100 + i, "answer", seed="hog", game=f"hog/g{i:03d}", gap=-19.0)
              for i in range(40)])
    for n, seed_name in enumerate(["b", "c", "d"], start=1):
        due += [_p(200 + n * 10 + i, "tenuki", seed=seed_name,
                   game=f"{seed_name}/g{i:03d}", gap=4.0) for i in range(5)]
        due += [_p(300 + n * 10 + i, "answer", seed=seed_name,
                   game=f"{seed_name}/g{i:03d}", gap=-4.0) for i in range(5)]
    due.sort(key=lambda p: p.points_lost, reverse=True)  # what due_problems hands over

    session = compose_session(due, 20, rng=random.Random(0))
    by_seed = collections.Counter(p.seed for p in session)
    assert len(by_seed) == 4, by_seed
    # Every seed gets a real share: the hog cannot take more than a third.
    assert max(by_seed.values()) <= 7, by_seed
    assert min(by_seed.values()) >= 4, by_seed
    # No game supplies two problems of the same kind while other games of
    # that seed are still waiting. (A game can still contribute one tenuki
    # and one answer: those are different positions, and the kind quota
    # comes first.)
    for kind in ("tenuki", "answer"):
        games = [p.game for p in session if p.seed == "hog" and p.kind == kind]
        assert len(set(games)) == len(games), games


def test_spread_by_source_keeps_gap_order_within_a_seed():
    ordered = [_p(0, "tenuki", seed="a", game="a/g001", gap=9.0),
               _p(1, "tenuki", seed="a", game="a/g001", gap=5.0),
               _p(2, "tenuki", seed="a", game="a/g002", gap=7.0),
               _p(3, "tenuki", seed="b", game="b/g001", gap=8.0)]
    spread = drill._spread_by_source(ordered)
    assert [p.seed for p in spread] == ["a", "b", "a", "a"]
    a_gaps = [p.gap for p in spread if p.seed == "a"]
    assert a_gaps == [9.0, 7.0, 5.0]  # games alternate, gap order kept


def test_compose_session_tops_up_when_one_kind_runs_short():
    due = [_p(i, "tenuki") for i in range(30)] + [_p(100, "answer")]
    session = compose_session(due, 10, rng=random.Random(0))
    assert len(session) == 10
    assert sum(p.kind == "answer" for p in session) == 1


def test_candidates_apply_cheap_filters():
    # Stones two lines apart, so nothing is ever captured (no ko filter hits).
    moves = [["b" if i % 2 == 0 else "w", [(i // 9) * 2, (i % 9) * 2]] for i in range(80)]
    positions = [{"move_number": n, "to_play": "b" if n % 2 else "w",
                  "score_lead": 0.0 if n != 61 else 30.0, "winrate": 0.5,
                  "best": "T19", "best_score_lead": 0.0, "played": "?"}
                 for n in range(2, 81)]
    gen = {"board_size": 19, "komi": 6.5, "moves": moves, "positions": positions}
    nums = [c.move_number for c in drill.candidates(gen, drill.DrillSettings())]
    assert nums == [n for n in range(51, 81) if n != 61]  # middle game only, score window


def test_pick_spaced_reserves_tenuki_slots_and_caps_huge_gaps():
    # (move_number, gap): big must-answer fights would win a pure |gap| ranking.
    items = [(60, -20.0), (80, -15.0), (100, -12.0), (120, 3.0), (140, 2.5)]
    picked = drill._pick_spaced(items, lambda x: x[1], lambda x: x[0],
                                {"tenuki": 2, "answer": 1}, 3, 15)
    assert sorted(m for m, _ in picked) == [100, 120, 140]  # -12 is the smallest capped gap


def test_pick_spaced_fills_from_other_kind_and_keeps_spacing():
    items = [(60, -5.0), (70, -4.0), (90, -3.0), (110, 2.5)]
    picked = drill._pick_spaced(items, lambda x: x[1], lambda x: x[0],
                                {"tenuki": 2, "answer": 1}, 3, 15)
    assert sorted(m for m, _ in picked) == [60, 90, 110]  # 70 is too close to 60


def test_compose_session_keeps_ratio_when_tenuki_is_scarce():
    due = [_p(i, "tenuki") for i in range(3)] + [_p(100 + i, "answer") for i in range(30)]
    session = compose_session(due, 20, tenuki_share=0.6, rng=random.Random(0))
    assert sum(p.kind == "tenuki" for p in session) == 3
    assert sum(p.kind == "answer" for p in session) == 2  # not padded to 17
