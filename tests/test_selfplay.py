import json
import random

from sgfmill.common import format_vertex

from baduk_lab import selfplay
from baduk_lab.selfplay import GenSettings, choose_move, load_seeds, loss_budget


def _mi(move, score, order, visits=50, prior=0.1):
    return {"move": move, "scoreLead": score, "order": order, "visits": visits, "prior": prior}


def test_load_seeds_one_per_variation(tmp_path):
    (tmp_path / "mainline.sgf").write_text("(;SZ[19]KM[6.5];B[pd];W[dp])")
    (tmp_path / "tree.sgf").write_text("(;SZ[19]KM[7.5];B[pd](;W[dd])(;W[dp];B[pp]))")
    (tmp_path / "handicap.sgf").write_text("(;SZ[19]AB[pd][dp];W[dd])")
    seeds = {s.slug: s for s in load_seeds(tmp_path)}

    assert set(seeds) == {"mainline", "tree--var1", "tree--var2"}
    assert len(seeds["mainline"].moves) == 2
    assert len(seeds["tree--var1"].moves) == 2
    assert len(seeds["tree--var2"].moves) == 3
    assert seeds["tree--var1"].komi == 7.5


def test_loss_budget_steers_leader_loose_and_trailer_tight():
    s = GenSettings()
    assert loss_budget(0.0, s) == s.loss_budget
    assert loss_budget(s.steer_start + 1, s) == s.leader_budget
    assert loss_budget(-(s.steer_start + 1), s) == s.trailer_budget


def test_choose_move_respects_budget_for_white():
    # White to move; scores are Black's perspective, so lower is better for White.
    infos = [_mi("D4", -2.0, 0), _mi("Q16", -1.0, 1), _mi("K10", 3.0, 2)]
    rng = random.Random(0)
    picks = {choose_move(infos, "w", 0.0, GenSettings(), rng) for _ in range(200)}
    assert picks == {"D4", "Q16"}  # K10 loses 5 points for White


def test_choose_move_trailer_only_plays_best():
    infos = [_mi("D4", 1.0, 0), _mi("Q16", 0.0, 1)]  # Black to move, Q16 loses 1
    rng = random.Random(0)
    picks = {choose_move(infos, "b", -6.0, GenSettings(), rng) for _ in range(100)}
    assert picks == {"D4"}


def test_choose_move_skips_barely_searched_candidates():
    infos = [_mi("D4", 1.0, 0, visits=97), _mi("Q16", 1.0, 1, visits=1, prior=0.9)]
    rng = random.Random(0)
    assert {choose_move(infos, "b", 0.0, GenSettings(), rng) for _ in range(50)} == {"D4"}


class _ScriptedClient:
    """Fake engine: every position reports Black ahead by `lead`, with a
    few legal-looking candidates spread over the board."""

    def __init__(self, lead):
        self.lead = lead
        self.queries = 0

    def run_queries(self, queries):
        out = {}
        for q in queries:
            self.queries += 1
            played = {v for _, v in q["moves"]}
            free = [format_vertex((r, c)) for r in range(19) for c in range(19)
                    if format_vertex((r, c)) not in played][:3]
            out[q["id"]] = {
                "turnNumber": q["analyzeTurns"][0],
                "rootInfo": {"scoreLead": self.lead, "winrate": 0.5},
                "moveInfos": [_mi(v, self.lead, i) for i, v in enumerate(free)],
            }
        return out


def _seed():
    return selfplay.Seed(slug="s", komi=6.5, board_size=19, moves=[("b", (15, 15))])


def test_generate_writes_games_and_is_incremental(tmp_path):
    settings = GenSettings(stop_at=20)
    client = _ScriptedClient(lead=0.0)
    result = selfplay.generate(client, [_seed()], 2, tmp_path, settings, parallel=4)
    assert result == {"generated": 2, "abandoned": 0}

    gen = json.loads((tmp_path / "s" / "g001.gen.json").read_text())
    assert len(gen["moves"]) == 20
    assert [p["move_number"] for p in gen["positions"]] == list(range(2, 21))
    assert (tmp_path / "s" / "g002.sgf").exists()

    again = selfplay.generate(client, [_seed()], 3, tmp_path, settings)
    assert again["generated"] == 1  # only the missing game


def test_generate_abandons_games_that_stay_lopsided(tmp_path):
    settings = GenSettings(stop_at=100, abandon_after=5)
    result = selfplay.generate(_ScriptedClient(lead=25.0), [_seed()], 1, tmp_path, settings)
    assert result["abandoned"] == 1
    gen = json.loads((tmp_path / "s" / "g001.gen.json").read_text())
    assert len(gen["moves"]) == 1 + 5
