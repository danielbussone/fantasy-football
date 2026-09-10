from projections.weekly import blend_usage, breakout_marker, percentile_dict, prior_for, project_player, row_to_3g_prior


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


def test_zero_3g_does_not_count_as_usage():
    from projections.weekly import default_prior

    g3 = row_to_3g_prior({"player": "X", "pos": "RB", "Yds": "0", "Att": "0", "Tar": "0", "Rec": "0"})
    assert not g3.get("has_3g")
    base = default_prior("X", "RB")
    base["source"] = "role-prior"
    out = blend_usage(base, g3, 1)
    assert out["source"] == "role-prior"
    assert not out["has_3g"]
    m = breakout_marker(out, depth_rank=1, pos="RB")
    assert m and m["flag"] == "needs-3g"


def test_breakout_needs_3g_not_invented():
    prior = {"pos": "RB", "source": "role-prior", "has_3g": False}
    m = breakout_marker(prior, depth_rank=2, pos="RB")
    assert m and m["flag"] == "needs-3g"
    assert "needs 3g" in m["why"]
    assert breakout_marker({"pos": "WR", "source": "season history", "has_3g": False}, 1, "WR") is None


def test_breakout_when_3g_usage_rises():
    from projections.weekly import breakout_marker

    prior = {
        "pos": "RB",
        "has_3g": True,
        "g3_carries_pg": 12,
        "season_carries_pg": 4,
        "rush_ypc": 5.1,
        "source": "3g+history",
    }
    m = breakout_marker(prior, depth_rank=2, pos="RB")
    assert m and m["flag"] == "breakout"
    assert "12" in m["why"] and "5.1" in m["why"]

