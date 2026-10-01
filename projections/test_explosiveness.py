import csv

from projections.explosiveness import (
    _game_td_bonus,
    explosiveness_skew,
    format_edges,
    player_td_bonus_table,
    position_avg_bonus_per_td,
    ypc_based_skew,
)

FIELDS = ["player", "team", "pos", "Opp", "Yds", "TD", "Yds_2", "TD_2", "Tar", "Rec", "Total"]


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_game_td_bonus_is_total_minus_yards_minus_base():
    # WR: 46 rec yds (0 bucket points, <70) + one 46-yd-ish TD worth 4
    # (base 1 + 46-60 bonus 3) -> Total should be exactly 4, bonus = 3.
    line = {"pos": "WR", "rush_yds": 0.0, "rec_yds": 46.0, "rec_td": 1, "rush_td": 0, "pass_td": 0, "cbs_total": 4.0}
    bonus, tds = _game_td_bonus(line)
    assert tds == 1
    assert bonus == 3.0


def test_game_td_bonus_no_tds_is_zero():
    line = {"pos": "WR", "rush_yds": 0.0, "rec_yds": 80.0, "rec_td": 0, "rush_td": 0, "pass_td": 0, "cbs_total": 1.0}
    bonus, tds = _game_td_bonus(line)
    assert tds == 0 and bonus == 0.0


def test_player_td_bonus_table_pools_across_weeks(tmp_path):
    w1 = tmp_path / "cbs_stats_week1.csv"
    w2 = tmp_path / "cbs_stats_week2.csv"
    _write(w1, [{"player": "Deep Threat", "pos": "WR", "Yds": "46", "TD": "1", "Total": "4"}])
    _write(w2, [{"player": "Deep Threat", "pos": "WR", "Yds": "5", "TD": "1", "Total": "1"}])
    table = player_td_bonus_table([w1, w2])
    entry = table["deep threat"]
    assert entry["tds"] == 2
    assert entry["bonus"] == 3.0  # one 46-yd TD (+3), one <16-yd TD (+0)


def test_position_avg_bonus_per_td():
    table = {
        "a": {"pos": "WR", "tds": 2, "bonus": 6.0},
        "b": {"pos": "WR", "tds": 1, "bonus": 0.0},
        "c": {"pos": "RB", "tds": 1, "bonus": 4.0},
    }
    avgs = position_avg_bonus_per_td(table)
    assert avgs["WR"] == 2.0  # (6+0)/(2+1)
    assert avgs["RB"] == 4.0


def test_ypc_based_skew_positive_for_big_play_profile():
    assert ypc_based_skew("WR", {"ypc": 20}) > 0
    assert ypc_based_skew("WR", {"ypc": 6}) < 0
    assert ypc_based_skew("WR", {}) == 0.0
    assert ypc_based_skew("RB", {"rush_ypc": 6.0}) > 0


def test_explosiveness_skew_falls_back_to_ypc_prior_with_no_tds():
    prior = {"ypc": 18}
    skew = explosiveness_skew("Nobody Yet", "WR", prior, {}, {})
    assert skew == ypc_based_skew("WR", prior)


def test_explosiveness_skew_uses_real_sample_when_available():
    table = {"deep threat": {"pos": "WR", "tds": 12, "bonus": 36.0}}  # avg bonus 3/td, way above average
    pos_avgs = {"WR": 1.0}
    skew = explosiveness_skew("Deep Threat", "WR", {"ypc": 11}, table, pos_avgs)
    assert skew > 0
    # A big real sample (well past SHRINK_TDS=6) should dominate the neutral
    # ypc-based prior (ypc=11 -> prior_skew 0).
    assert skew > 0.15


def test_format_edges_flags_big_gaps_only():
    # A wide pool so app_rank (bounded by pool size) can land far from a
    # small or large FantasyPros rank number in either direction.
    players = [
        {"player": "Sim Loves Him", "pos": "WR", "weekly_list": "FLX", "weekly_rank": 40, "proj": {"mean": 20}},
        {"player": "FP Loves Him", "pos": "WR", "weekly_list": "FLX", "weekly_rank": 1, "proj": {"mean": 1}},
        {"player": "Agree", "pos": "WR", "weekly_list": "FLX", "weekly_rank": 2, "proj": {"mean": 15}},
    ] + [{"player": f"Filler{i}", "pos": "WR", "weekly_list": "FLX", "weekly_rank": 10 + i, "proj": {"mean": 10 - i * 0.1}} for i in range(8)]
    edges = format_edges(players, min_gap=5)
    names = {e["player"] for e in edges}
    assert "Sim Loves Him" in names
    assert "FP Loves Him" in names
    assert "Agree" not in names
    sim_edge = next(e for e in edges if e["player"] == "Sim Loves Him")
    assert sim_edge["gap"] > 0
    fp_edge = next(e for e in edges if e["player"] == "FP Loves Him")
    assert fp_edge["gap"] < 0
