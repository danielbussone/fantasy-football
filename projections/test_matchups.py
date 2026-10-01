import csv

from projections.matchups import (
    apply_matchup,
    league_averages,
    matchup_ratio,
    pass_rush_skew,
    points_allowed_table,
    sack_rates,
)

FIELDS = ["player", "team", "pos", "Opp", "Yds", "TD", "Yds_2", "TD_2", "Tar", "Rec", "SACK", "Total", "Total_2", "Total_3"]


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_points_allowed_table_sums_by_opponent_and_position(tmp_path):
    # Two WRs torch DAL's defense in week 1; a DAL WR (playing someone
    # else, PHI) doesn't count against DAL itself.
    w1 = tmp_path / "cbs_stats_week1.csv"
    _write(
        w1,
        [
            {"player": "WR1", "pos": "WR", "Opp": "@DAL", "Yds": "100", "TD": "1", "Total": "7"},
            {"player": "WR2", "pos": "WR", "Opp": "DAL", "Yds": "50", "TD": "0", "Total": "1"},
            {"player": "DAL-WR", "team": "DAL", "pos": "WR", "Opp": "@PHI", "Yds": "20", "TD": "0", "Total": "0"},
            {"player": "BenchQB", "pos": "QB", "Opp": "BYE", "Yds": "0", "TD": "0", "Total": "0"},
        ],
    )
    table = points_allowed_table([w1])
    assert table["DAL"]["WR"] == 8
    assert table["DAL"]["games"] == 1
    assert "PHI" not in table or table.get("PHI", {}).get("WR", 0) == 0


def test_league_averages_pooled_by_games_not_mean_of_means(tmp_path):
    w1 = tmp_path / "cbs_stats_week1.csv"
    _write(
        w1,
        [
            {"player": "A", "pos": "WR", "Opp": "AAA", "Yds": "100", "TD": "0", "Total": "3"},
            {"player": "B", "pos": "WR", "Opp": "BBB", "Yds": "50", "TD": "0", "Total": "1"},
        ],
    )
    table = points_allowed_table([w1])
    avgs = league_averages(table)
    assert avgs["WR"] == 2.0  # (3 + 1) / (1 game + 1 game)


def test_matchup_ratio_shrinks_toward_average_with_few_games(tmp_path):
    w1 = tmp_path / "cbs_stats_week1.csv"
    # WEAK allows a lot to WR (10/game); the league average is much lower.
    _write(
        w1,
        [
            {"player": "A", "pos": "WR", "Opp": "WEAK", "Yds": "150", "TD": "1", "Total": "10"},
            {"player": "B", "pos": "WR", "Opp": "AVG1", "Yds": "50", "TD": "0", "Total": "2"},
            {"player": "C", "pos": "WR", "Opp": "AVG2", "Yds": "50", "TD": "0", "Total": "2"},
        ],
    )
    table = points_allowed_table([w1])
    avgs = league_averages(table)
    ratio = matchup_ratio("WEAK", "WR", table, avgs)
    # Raw ratio would be 10/4.67 ~ 2.14x, but 1 game shrinks hard toward 1.0
    # and the result is still clamped to the 0.85-1.15 band.
    assert 1.0 < ratio <= 1.15


def test_matchup_ratio_unknown_team_is_noop():
    assert matchup_ratio("ZZZ", "WR", {}, {"WR": 3.0}) == 1.0


def test_apply_matchup_scales_rates_by_ratio(tmp_path):
    w1 = tmp_path / "cbs_stats_week1.csv"
    rows = [{"player": f"P{i}", "pos": "WR", "Opp": "WEAK", "Yds": "150", "TD": "1", "Total": "10"} for i in range(6)]
    rows += [{"player": f"Q{i}", "pos": "WR", "Opp": f"AVG{i}", "Yds": "50", "TD": "0", "Total": "2"} for i in range(6)]
    _write(w1, rows)
    table = points_allowed_table([w1])
    avgs = league_averages(table)
    prior = {"pos": "WR", "scrim_ypg": 60.0, "rec_td_rate": 0.3}
    out = apply_matchup(dict(prior), "WEAK", "WR", table, avgs)
    assert out["rec_td_rate"] > prior["rec_td_rate"]
    assert out["scrim_ypg"] > prior["scrim_ypg"]
    assert out["matchup_ratio"] > 1.0


def test_apply_matchup_noop_without_data():
    prior = {"pos": "WR", "scrim_ypg": 60.0}
    out = apply_matchup(dict(prior), "ZZZ", "WR", {}, {})
    assert out == prior


def test_sack_rates_blends_history_and_season(tmp_path):
    dst_hist = tmp_path / "dst_history.csv"
    with dst_hist.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["season", "team", "sack"])
        w.writerow(["2025", "PIT", "51"])  # 3.0/game prior
        w.writerow(["2025", "CLE", "34"])  # 2.0/game prior
    w1 = tmp_path / "cbs_stats_week1.csv"
    _write(w1, [{"player": "Steelers", "team": "PIT", "pos": "DST", "SACK": "6", "Total": "1"}])
    rates = sack_rates(dst_history_path=dst_hist, week_files=[w1])
    # PIT's one real game (6 sacks) pulls its rate up from the history-only
    # prior (3.0/game), but doesn't fully overwrite it with 1 game of data.
    assert rates["PIT"] > 3.0
    assert rates["PIT"] < 6.0
    # CLE has no season box score yet — falls back to the history prior.
    assert rates["CLE"] == 2.0


def test_pass_rush_skew_negative_for_strong_pass_rush():
    rates = {"STRONG": 4.0, "AVG": 2.0, "WEAK": 1.0}
    strong = pass_rush_skew("STRONG", rates)
    weak = pass_rush_skew("WEAK", rates)
    assert strong < 0  # shift TD draws shorter against a strong pass rush
    assert weak > 0
    assert pass_rush_skew("ZZZ", rates) == 0.0
