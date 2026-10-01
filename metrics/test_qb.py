from metrics.qb import qb_row, prior_production


def _qb_game(week, gbfl, *, attempts=30.0, epa=3.0):
    return {"week": week, "gbfl": gbfl, "attempts": attempts, "sacks": 2.0, "scrambles": 0.0, "carries": 3.0, "targets": 0.0,
            "rec": 0.0, "rec_yds": 0.0, "air_yds": 0.0, "rush_yds": 10.0, "pass_yds": 220.0, "epa": epa, "cpoe": None,
            "pass_air": 0.0, "deep_att": 0.0, "implied": 22.0, "snap_pct": 1.0}


def _season(n, gbfl):
    return [_qb_game(w, gbfl) for w in range(1, n + 1)]


def test_backups_and_one_game_samples_are_not_ranked():
    assert qb_row(_season(1, 10), {1: [], 2: []}, 9.0) is None
    backup = [_qb_game(w, 1.0, attempts=5.0) for w in (1, 2, 3)]  # 5 attempts a game is garbage time, not a starter
    assert qb_row(backup, {1: [], 2: []}, 9.0) is None


def test_prior_seasons_need_five_games_and_two_back_counts_half():
    assert prior_production({1: _season(4, 20), 2: []}) is None
    pr = prior_production({1: _season(10, 12.0), 2: _season(10, 6.0)})
    assert pr["prior_n"] == 15.0
    assert abs(pr["prior_ppg"] - (12.0 * 10 + 6.0 * 5) / 15) < 1e-9


def test_rookie_gets_the_league_prior_and_a_flag():
    row = qb_row(_season(3, 8.0), {1: [], 2: []}, 9.5)
    assert row["has_prior"] == 0.0 and row["prior_ppg"] is None and row["prior_ppg_i"] == 9.5


def test_weight_shifts_from_last_year_to_this_year_as_games_pile_up():
    prior = {1: _season(17, 10.0), 2: []}
    early, late = qb_row(_season(3, 14.0), prior, 9.0), qb_row(_season(12, 14.0), prior, 9.0)
    assert early["ppg_x_g"] < late["ppg_x_g"] and early["prior_x_g"] > late["prior_x_g"]
    assert abs(early["ppg_x_g"] - 14.0 * 3 / 17) < 1e-9 and abs(early["prior_x_g"] - 10.0 * 14 / 17) < 1e-9


def test_epa_per_play_uses_dropbacks_and_designed_runs():
    row = qb_row(_season(5, 9.0), {1: [], 2: []}, 9.0)
    assert abs(row["epa"] - 15.0 / (5 * (30 + 2 + 3))) < 1e-9
