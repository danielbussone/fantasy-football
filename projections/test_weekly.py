import random

from projections.weekly import (
    _pick_skewed,
    blend_usage,
    games_for_3g_window,
    percentile_dict,
    prior_for,
    project_player,
    row_to_3g_prior,
    simulate_detail,
)


def test_percentiles_ordered():
    prior = prior_for("Ja'Marr Chase", "WR")
    p = project_player(prior, n=400, seed=7)
    assert p["p10"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p90"]
    assert set(p) >= {"p10", "p25", "p50", "p75", "p90", "mean"}
    assert "sim" in p and "usage" in p and "explain" in p
    assert p["explain"]["lines"]


def test_long_td_example_in_engine():
    from scoring.rules import Game, score_game

    assert score_game(Game(pos="WR", rec_td_yards=[46])) > score_game(
        Game(pos="WR", rec_yds=109, rec_td_yards=[10])
    )


def test_p90_exceeds_p10_for_spiky_wr():
    prior = {
        "player": "Boom WR",
        "pos": "WR",
        "scrim_ypg": 80,
        "rec_share": 0.95,
        "rec_td_rate": 0.7,
        "cv": 0.6,
        "ypc": 16,
    }
    p = project_player(prior, n=800, seed=3)
    assert p["p90"] > p["p10"]
    assert p["p90"] - p["p10"] >= 4


def test_3g_blend_and_backup_downweight():
    g3 = row_to_3g_prior({"player": "X", "pos": "RB", "Yds": "210", "Rec": "6", "Yds_2": "30", "TD": "2", "GP": "3"})
    assert g3["scrim_ypg"] > 70
    base = {"player": "X", "pos": "RB", "scrim_ypg": 40, "rush_td_rate": 0.2, "rec_td_rate": 0.1}
    mixed = blend_usage(base, g3, depth_rank=1)
    assert mixed["scrim_ypg"] > base["scrim_ypg"]
    backup = blend_usage(base, g3, depth_rank=3)
    assert backup["scrim_ypg"] < mixed["scrim_ypg"]
    assert backup.get("role") == "backup"


def test_percentile_dict_order():
    d = percentile_dict([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert d["p10"] <= d["p50"] <= d["p90"]


def test_3g_early_season_divides_by_games_played_not_three():
    love = {"player": "Jordan Love", "pos": "QB", "ATT": "42", "Yds": "387", "Yds_2": "0", "TD": "2"}
    assert games_for_3g_window(1) == 1
    assert games_for_3g_window(2) == 1
    assert games_for_3g_window(3) == 2
    assert games_for_3g_window(4) == 3
    assert games_for_3g_window(None) == 3
    w2 = row_to_3g_prior(love, week=2)
    assert w2["pass_att_pg"] == 42
    assert w2["qb_ypg"] == 387
    mid = row_to_3g_prior(love, week=5)
    assert abs(mid["pass_att_pg"] - 42 / 3) < 1e-9
    two = row_to_3g_prior({**love, "GP": "2"}, week=5)
    assert abs(two["pass_att_pg"] - 21) < 1e-9


def test_3g_rb_wr_td_rates_are_not_always_zero():
    """Regression: CBS reuses Yds/TD for rushing (RB) vs receiving (WR/TE);
    the parser used to only ever look for "Rush TD"/"RuTD" columns, which
    never exist, so every RB/WR/TE last-3-games TD rate silently parsed as 0.
    Rows below are real week-1 CBS shapes (Gibbs, Jefferson).
    """
    gibbs = row_to_3g_prior(
        {"player": "Jahmyr Gibbs", "pos": "RB", "Yds": "156", "TD": "2", "Att": "29", "Yds_2": "30", "TD_2": "0", "Tar": "5", "Rec": "5", "GP": "1"}
    )
    assert gibbs["rush_td_rate"] > 0

    jefferson = row_to_3g_prior(
        {"player": "Justin Jefferson", "pos": "WR", "Yds": "92", "TD": "2", "Att": "0", "Yds_2": "0", "TD_2": "0", "Tar": "9", "Rec": "8", "GP": "1"}
    )
    assert jefferson["rec_td_rate"] > 0
    assert abs(jefferson["ypc"] - 11.5) < 0.01


def test_zero_3g_does_not_count_as_usage():
    from projections.weekly import default_prior

    g3 = row_to_3g_prior({"player": "X", "pos": "RB", "Yds": "0", "Att": "0", "Tar": "0", "Rec": "0"})
    assert not g3.get("has_3g")
    base = default_prior("X", "RB")
    base["source"] = "role-prior"
    out = blend_usage(base, g3, 1)
    assert out["source"] == "role-prior"
    assert not out["has_3g"]
def _wr_prior():
    return {
        "player": "QWR",
        "pos": "WR",
        "scrim_ypg": 90,
        "rec_share": 0.95,
        "rec_td_rate": 0.5,
        "cv": 0.35,
        "ypc": 12,
    }


def test_out_sim_is_zero():
    p = project_player(_wr_prior(), n=200, seed=1, injury="out")
    assert p["p10"] == p["p50"] == p["p90"] == 0
    assert p["injury_adj"] == "out"


def test_pick_skewed_zero_skew_matches_uniform_distribution():
    seq = [10, 20, 30, 40, 50]
    rng = random.Random(1)
    zero_skew = [_pick_skewed(seq, rng, 0.0) for _ in range(2000)]
    rng2 = random.Random(1)
    plain = [seq[rng2.randrange(len(seq))] for _ in range(2000)]
    assert zero_skew == plain


def test_pick_skewed_negative_shifts_shorter_positive_shifts_longer():
    seq = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    rng = random.Random(7)
    short = [_pick_skewed(seq, rng, -0.4) for _ in range(3000)]
    rng2 = random.Random(7)
    long = [_pick_skewed(seq, rng2, 0.4) for _ in range(3000)]
    assert (sum(short) / len(short)) < (sum(long) / len(long))


def test_pass_rush_skew_moves_qb_pass_td_distance():
    """A strong opposing pass rush (negative skew) should pull mean passing
    TD length shorter — a shorter TD is worth fewer points here."""
    from projections.weekly import PASS_TD_DIST
    from scoring.rules import passing_td_points

    rng = random.Random(9)
    neutral_draws = [_pick_skewed(PASS_TD_DIST, rng, 0.0) for _ in range(3000)]
    rng = random.Random(9)
    pressured_draws = [_pick_skewed(PASS_TD_DIST, rng, -0.4) for _ in range(3000)]
    assert (sum(pressured_draws) / len(pressured_draws)) < (sum(neutral_draws) / len(neutral_draws))
    assert passing_td_points(min(PASS_TD_DIST)) < passing_td_points(max(PASS_TD_DIST))


def test_simulate_detail_reads_pass_rush_skew_from_prior():
    """simulate_detail must actually thread prior["pass_rush_skew"] through
    to the pass-TD distance draw, not just accept the key silently."""
    prior = {"pos": "QB", "qb_ypg": 260, "rush_ypg": 10, "pass_td_rate": 5.0, "rush_td_rate": 0.0}
    pressured = {**prior, "pass_rush_skew": -0.4}
    neutral_lengths = []
    pressured_lengths = []
    for seed in range(400):
        pts, _ = simulate_detail(dict(prior), random.Random(seed))
        neutral_lengths.append(pts)
    for seed in range(400):
        pts, _ = simulate_detail(dict(pressured), random.Random(seed))
        pressured_lengths.append(pts)
    # With a high pass TD rate and a big pressure skew, average points must
    # come down (shorter TDs bank fewer distance-bonus points) even though
    # yards/rates are otherwise identical.
    assert sum(pressured_lengths) < sum(neutral_lengths)


def test_player_td_skew_combines_with_pass_rush_skew():
    """Both skews should stack (clamped), each independently able to move
    the receiving-TD distance draw."""
    from projections.weekly import REC_TD_DIST

    rng = random.Random(4)
    neutral = [_pick_skewed(REC_TD_DIST, rng, 0.0) for _ in range(3000)]
    rng = random.Random(4)
    both_negative = [_pick_skewed(REC_TD_DIST, rng, -0.3 + -0.3) for _ in range(3000)]
    assert (sum(both_negative) / len(both_negative)) < (sum(neutral) / len(neutral))


def test_qb_rush_yards_not_double_counted():
    """qb_ypg is pass+rush together; the sim used to sample rush again on top
    and only discount it 10%, so mean simulated yards ran well above qb_ypg.
    """
    prior = {"player": "Test QB", "pos": "QB", "qb_ypg": 260.0, "rush_ypg": 40.0, "pass_td_rate": 1.5, "rush_td_rate": 0.3}
    rng = random.Random(1)
    total = 0.0
    n = 4000
    for _ in range(n):
        _, det = simulate_detail(prior, rng)
        total += det["pass_yds"] + det["rush_yds"]
    mean_yds = total / n
    assert abs(mean_yds - prior["qb_ypg"]) / prior["qb_ypg"] < 0.05


def test_prior_for_has_no_last_name_fallback():
    """A player with no season history used to silently borrow another
    player's stats via a "same last name + position" match (any two
    "... Jr." at the same position, "II" matching "III") — e.g. Omar Cooper
    Jr. got Brian Thomas Jr.'s full season-history prior. Unmatched now
    means role-prior (optionally blended with his own real last-3-games),
    never someone else's season-history row.
    """
    prior = prior_for("Omar Cooper Jr.", "WR")
    assert prior["source"] != "season history"
    assert "3g" in prior["source"] or prior["source"] == "role-prior"


def test_questionable_cuts_volume_then_scores():
    """Injury scales yards/TDs; P50 is a scored game, not 0.75 × healthy P50."""
    prior = _wr_prior()
    healthy = project_player(prior, n=800, seed=9)
    q = project_player(prior, n=800, seed=9, injury="questionable")
    h_yds = (healthy["sim"].get("rec_yds") or 0) + (healthy["sim"].get("rush_yds") or 0)
    q_yds = (q["sim"].get("rec_yds") or 0) + (q["sim"].get("rush_yds") or 0)
    assert q_yds < h_yds
    assert q["p50"] <= healthy["p50"]
    assert q["p10"] <= q["p50"] <= q["p90"]
    assert q["p50"] != round(healthy["p50"] * 0.75, 2)
    assert q.get("injury_adj") == "questionable"

