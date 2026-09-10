from projections.espn import blend_espn, parse_kona, player_row, stats_to_prior
from projections.weekly import blend_espn as blend_from_weekly


def test_hurts_week1_stat_map():
    stats = {"3": 229.105, "4": 1.661, "24": 27.461, "25": 0.636}
    prior = stats_to_prior("QB", stats)
    assert abs(prior["qb_ypg"] - 229.105) < 0.01
    assert abs(prior["rush_ypg"] - 27.461) < 0.01
    assert abs(prior["pass_td_rate"] - 1.661) < 0.01
    assert abs(prior["rush_td_rate"] - 0.636) < 0.01
    assert "espn_pts" not in prior


def test_wr_rec_yards_are_stat_42():
    stats = {"24": 1.22, "42": 88.8, "43": 0.65, "25": 0.01}
    prior = stats_to_prior("WR", stats)
    assert abs(prior["scrim_ypg"] - 90.02) < 0.02
    assert prior["rec_share"] > 0.9
    assert abs(prior["rec_td_rate"] - 0.65) < 0.01


def test_dst_pa_uses_points_not_yards():
    prior = stats_to_prior("DST", {"95": 0.73, "96": 0.47, "120": 18.8, "127": 308.5, "93": 0.01})
    assert abs(prior["pa_mean"] - 18.8) < 0.01
    assert prior["pa_mean"] < 40


def test_blend_espn_moves_and_missing_is_noop():
    base = {"player": "X", "pos": "QB", "qb_ypg": 200, "rush_ypg": 10, "source": "history"}
    espn = {"qb_ypg": 240, "rush_ypg": 30}
    mixed = blend_espn(base, espn, weight=0.5)
    assert mixed["qb_ypg"] == 220
    assert mixed["has_espn"]
    assert "+espn" in mixed["source"]
    same = blend_espn(base, None, weight=0.5)
    assert same["qb_ypg"] == 200
    assert blend_from_weekly(base, espn, 0.5)["qb_ypg"] == 220


def test_player_row_keeps_applied_total_as_tooltip_only():
    entry = {
        "id": 4040715,
        "player": {
            "id": 4040715,
            "fullName": "Jalen Hurts",
            "defaultPositionId": 1,
            "proTeamId": 21,
            "stats": [
                {
                    "statSourceId": 1,
                    "scoringPeriodId": 1,
                    "appliedTotal": 21.065,
                    "stats": {"3": 229.1, "4": 1.66, "24": 27.5, "25": 0.64},
                }
            ],
        },
    }
    row = player_row(entry, 1)
    assert row["player"] == "Jalen Hurts"
    assert row["pos"] == "QB" and row["team"] == "PHI"
    assert row["espn_pts"].startswith("21")
    assert float(row["qb_ypg"]) > 200
    parsed = parse_kona({"players": [entry]}, 1)
    assert parsed[0]["espn_id"] == 4040715
    # appliedTotal is not a prior key
    assert "present" not in row
