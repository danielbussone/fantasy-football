from metrics.features import build_games, window_features


def _weekly(pid, pos, week, **kw):
    base = {"player_id": pid, "player_display_name": pid, "position": pos, "week": str(week),
            "season_type": "REG", "team": "AAA", "targets": "0", "receptions": "0",
            "receiving_yards": "0", "receiving_air_yards": "0", "receiving_20": "0",
            "carries": "0", "rushing_yards": "0", "passing_yards": "0",
            "passing_2pt_conversions": "0", "rushing_2pt_conversions": "0", "receiving_2pt_conversions": "0"}
    base.update({k: str(v) for k, v in kw.items()})
    return base


def _pbp(**kw):
    base = {"week": "1", "posteam": "AAA", "play_type": "pass", "yardline_100": "50", "air_yards": "5",
            "yards_gained": "0", "sack": "0", "two_point_attempt": "0", "touchdown": "0",
            "receiver_player_id": "", "rusher_player_id": ""}
    base.update({k: str(v) for k, v in kw.items()})
    return base


def _games():
    weekly = [
        _weekly("WR1", "WR", 1, targets=10, receptions=6, receiving_yards=80, receiving_air_yards=120),
        _weekly("RB1", "RB", 1, carries=20, rushing_yards=100, targets=2, receptions=2, receiving_yards=10),
    ]
    team_week = [{"team": "AAA", "week": "1", "season_type": "REG", "targets": "40",
                  "receiving_air_yards": "300", "carries": "25"}]
    pbp = [
        _pbp(receiver_player_id="WR1", yardline_100="15", air_yards="15"),  # red zone + end zone target
        _pbp(receiver_player_id="WR1", air_yards="25"),                     # deep target
        _pbp(play_type="run", rusher_player_id="RB1", yardline_100="8", yards_gained="3"),
        _pbp(play_type="run", rusher_player_id="RB1", yards_gained="30"),
    ]
    snaps = [
        {"game_type": "REG", "pfr_player_id": "p_wr", "week": "1", "offense_pct": "0.9", "offense_snaps": "60", "team": "AAA", "position": "WR", "player": "WR1"},
        {"game_type": "REG", "pfr_player_id": "p_te", "week": "1", "offense_pct": "0.2", "offense_snaps": "12", "team": "AAA", "position": "TE", "player": "Blocker"},
    ]
    players = [
        {"gsis_id": "WR1", "pfr_id": "p_wr", "position": "WR", "display_name": "WR1"},
        {"gsis_id": "TE1", "pfr_id": "p_te", "position": "TE", "display_name": "Blocker"},
        {"gsis_id": "RB1", "pfr_id": "", "position": "RB", "display_name": "RB1"},
    ]
    return build_games(2025, weekly=weekly, team_week=team_week, pbp=pbp, snaps=snaps, players=players)


def test_build_games_joins_team_pbp_and_snaps():
    g = {r["player_id"]: r for r in _games()}
    wr = g["WR1"]
    assert wr["snap_pct"] == 0.9
    assert (wr["team_targets"], wr["rz_tgt"], wr["ez_tgt"], wr["deep_tgt"]) == (40.0, 1.0, 1.0, 1.0)
    assert wr["gbfl"] == 1.0  # 80 yards: 70–89 bucket
    rb = g["RB1"]
    assert (rb["i10_car"], rb["team_i10"], rb["run15"], rb["run26"]) == (1.0, 1.0, 1.0, 1.0)
    assert rb["snap_pct"] is None  # no pfr id -> no snap join


def test_snap_only_game_counts_as_a_zero_game():
    te = {r["player_id"]: r for r in _games()}["TE1"]
    assert te["pos"] == "TE" and te["gbfl"] == 0.0 and te["targets"] == 0.0 and te["snap_pct"] == 0.2


def test_window_shares_are_ratios_of_sums():
    games = [
        {"gbfl": 2, "targets": 12, "rec": 8, "rec_yds": 100, "air_yds": 120, "rec20": 1, "carries": 0,
         "rush_yds": 0, "team_targets": 36, "team_air": 300, "team_carries": 25, "team_i10": 0,
         "rz_tgt": 1, "ez_tgt": 0, "deep_tgt": 2, "i10_car": 0, "run15": 0, "run26": 0,
         "scrim_yds": 100, "snap_pct": 0.9},
        {"gbfl": 0, "targets": 1, "rec": 0, "rec_yds": 0, "air_yds": 10, "rec20": 0, "carries": 0,
         "rush_yds": 0, "team_targets": 40, "team_air": 300, "team_carries": 25, "team_i10": 0,
         "rz_tgt": 0, "ez_tgt": 0, "deep_tgt": 0, "i10_car": 0, "run15": 0, "run26": 0,
         "scrim_yds": 0, "snap_pct": 0.5},
    ]
    f = window_features(games, "WR")
    assert f["tgt_share"] == 13 / 76  # not the mean of 12/36 and 1/40
    assert f["adot"] == 130 / 13
    assert f["ppg"] == 1.0 and f["bucket_rate"] == 0.5
    assert abs(f["snap_pct"] - 0.7) < 1e-12


def test_efficiency_needs_a_minimum_sample():
    g = {"gbfl": 0, "targets": 2, "rec": 2, "rec_yds": 50, "air_yds": 40, "scrim_yds": 50, "carries": 4, "rush_yds": 40}
    f = window_features([g], "WR")
    assert f["adot"] is None and f["catch_rate"] is None and f["ypc"] is None


def test_bucket_threshold_is_position_specific():
    g = {"gbfl": 1, "scrim_yds": 45}
    assert window_features([g], "TE")["bucket_rate"] == 1.0
    assert window_features([g], "WR")["bucket_rate"] == 0.0


def test_empty_window():
    assert window_features([], "WR") == {"n": 0}


def test_implied_totals_split_the_total_by_the_spread():
    from metrics.features import implied_totals

    sched = [{"season": "2025", "game_type": "REG", "week": "1", "home_team": "HOM", "away_team": "AWY",
              "total_line": "44", "spread_line": "6"},
             {"season": "2025", "game_type": "REG", "week": "2", "home_team": "HOM", "away_team": "AWY",
              "total_line": "NA", "spread_line": "3"}]
    imp = implied_totals(sched, 2025)
    assert imp[("HOM", 1)] == 25.0 and imp[("AWY", 1)] == 19.0  # home favored by 6
    assert ("HOM", 2) not in imp


def test_qb_window_counts_dropbacks_and_designed_runs():
    g = {"gbfl": 3, "attempts": 30, "sacks": 2, "scrambles": 3, "carries": 7, "rush_yds": 40, "team_rush_yds": 100,
         "pass_air": 240, "deep_att": 3, "epa": 6.0, "cpoe": 2.0, "implied": 24.0, "pass_yds": 250, "scrim_yds": 40}
    f = window_features([g], "QB")
    assert f["db_pg"] == 35 and f["rush_att_pg"] == 4 and f["opp_pg"] == 39
    assert f["adot_pass"] == 8.0 and f["deep_att_rate"] == 0.1 and f["qb_rush_share"] == 0.4
    assert abs(f["epa_db"] - 6.0 / 39) < 1e-12 and f["cpoe"] == 2.0 and f["implied"] == 24.0
    assert f["bucket_rate"] == 1.0  # 250 pass + 40 rush clears 200


def test_pedigree_years_and_young_high_pick():
    from metrics.features import pedigree, pedigree_index

    idx = pedigree_index([
        {"gsis_id": "A", "rookie_season": "2024", "draft_round": "2", "draft_pick": "40"},
        {"gsis_id": "B", "rookie_season": "2022", "draft_round": "1", "draft_pick": "10"},
        {"gsis_id": "C", "rookie_season": "2025", "draft_round": "NA", "draft_pick": ""},
    ])
    assert pedigree(idx, "A", 2025) == {"years": 2, "round": 2, "pick": 40, "young_high_pick": True}
    assert pedigree(idx, "B", 2025)["young_high_pick"] is False  # 4th season
    assert pedigree(idx, "C", 2025) == {"years": 1, "round": 8, "pick": 300, "young_high_pick": False}  # undrafted
    assert pedigree(idx, "missing", 2025)["years"] is None
