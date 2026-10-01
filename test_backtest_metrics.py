import backtest_metrics as bt


def _game(week, gbfl, targets=6):
    return {"player_id": "P", "player": "P", "pos": "WR", "team": "AAA", "week": week, "gbfl": float(gbfl),
            "targets": float(targets), "rec": 3.0, "rec_yds": 40.0, "air_yds": 50.0, "rec20": 0.0,
            "carries": 0.0, "rush_yds": 0.0, "pass_yds": 0.0, "scrim_yds": 40.0, "snap_pct": 0.8,
            "team_targets": 35.0, "team_air": 300.0, "team_carries": 25.0, "team_i10": 1.0,
            "rz_tgt": 0.0, "ez_tgt": 0.0, "deep_tgt": 0.0, "i10_car": 0.0, "run15": 0.0, "run26": 0.0}


def test_features_only_see_the_past_and_targets_only_the_future():
    # Weeks 1–3 score 0; weeks 4+ score 9. At decision week 3 the features must
    # know nothing about the 9s, and the target must be all 9s.
    games = [_game(w, 0 if w <= 3 else 9) for w in range(1, 11)]
    rows = bt.decision_rows(games, 2025, ["WR"], {"WR": 2.0})
    d3 = next(r for r in rows if r["week"] == 3)
    assert d3["ppg"] == 0.0 and d3["l3_ppg"] == 0.0 and d3["std_boom"] == 0.0
    assert d3["y_ppg"] == 9.0 and d3["y_next"] == 9.0 and d3["y_boom"] == 1.0 and d3["y_bust"] == 0.0


def test_missed_next_week_leaves_next_game_target_empty():
    games = [_game(w, 1) for w in (1, 2, 3, 5, 6)]
    d3 = next(r for r in bt.decision_rows(games, 2025, ["WR"], {"WR": 2.0}) if r["week"] == 3)
    assert d3["y_next"] is None and d3["y_ppg"] == 1.0


def test_injury_exit_is_dropped_from_features_but_not_targets():
    games = [_game(w, 2) for w in range(1, 11)]
    games[2].update({"snap_pct": 0.2, "targets": 0.0, "gbfl": 0.0, "inj_listed_next": True})  # week 3: hurt early
    keep = next(r for r in bt.decision_rows(games, 2025, ["WR"], {"WR": 2.0}) if r["week"] == 4)
    drop = next(r for r in bt.decision_rows(games, 2025, ["WR"], {"WR": 2.0}, exclude_exits=True) if r["week"] == 4)
    assert keep["ppg"] == 1.5 and keep["exits_dropped"] == 0
    assert drop["ppg"] == 2.0 and drop["exits_dropped"] == 1
    assert keep["y_ppg"] == drop["y_ppg"]


def test_availability_rows_count_missed_team_games_as_zero():
    games = [_game(w, 2) for w in (1, 2, 3, 4)]  # plays weeks 1–4, then hurt for the rest
    inj = {("P", 5): {"status": "Out", "injured": True}}
    rows = bt.decision_rows(games, 2025, ["WR"], {"WR": 2.0}, require_future=False, inj=inj,
                            team_weeks={"AAA": set(range(1, 18)) - {6}})  # bye in week 6
    d4 = next(r for r in rows if r["week"] == 4)
    assert d4["status"] == "Out" and d4["team_games6"] == 5 and d4["played6"] == 0
    assert d4["y_total6"] == 0 and d4["y_ppg"] is None and d4["played_next"] is False


def test_players_without_an_offensive_role_are_excluded():
    games = [_game(w, 0, targets=0) for w in range(1, 11)]
    assert bt.decision_rows(games, 2025, ["WR"], {"WR": 2.0}) == []


def _rb(pid, week, carries, targets=0, team="AAA"):
    g = _game(week, 1, targets=targets)
    g.update({"player_id": pid, "player": pid, "pos": "RB", "team": team, "carries": float(carries),
              "team_carries": 30.0, "team_targets": 30.0})
    return g


def test_teammate_vacancy_and_next_man_up():
    # LEAD carries most of the load weeks 1–4, is Out for week 5. B2 is the bigger backup, B3 the smaller.
    games = [_rb("LEAD", w, 18) for w in range(1, 5)] + [_rb("B2", w, 6) for w in range(1, 10)] + [_rb("B3", w, 2) for w in range(1, 10)]
    inj = {("LEAD", 5): {"status": "Out", "injured": True}}
    tw = {"AAA": set(range(1, 18))}
    rows = [r for r in bt.decision_rows(games, 2025, ["RB"], {"RB": 3.0}, inj=inj, team_weeks=tw) if r["week"] == 4]
    bt.add_breakout_context(rows, games, inj, tw)
    bt.mark_next_up(rows)
    by = {r["player_id"]: r for r in rows}
    assert abs(by["B2"]["vac_pos"] - 18 / 60) < 1e-9  # LEAD's opportunity share
    assert by["B2"]["next_up"] and not by["B3"]["next_up"]
    assert "LEAD" not in by  # no games after week 4, so no decision row for him


def test_last3_usage_delta():
    games = [_game(w, 1, targets=4) for w in (1, 2, 3)] + [_game(w, 1, targets=10) for w in (4, 5, 6)] + [_game(w, 1) for w in (7, 8)]
    d6 = next(r for r in bt.decision_rows(games, 2025, ["WR"], {"WR": 2.0}) if r["week"] == 6)
    assert d6["d_share"] > 0 and d6["d_snap"] == 0.0


def test_extra_out_ids_count_as_a_vacancy():
    games = [_rb("LEAD", w, 18) for w in range(1, 5)] + [_rb("B2", w, 6) for w in range(1, 10)]
    tw = {"AAA": set(range(1, 18))}
    rows = [r for r in bt.decision_rows(games, 2025, ["RB"], {"RB": 3.0}, team_weeks=tw) if r["week"] == 4]
    bt.add_breakout_context(rows, games, {}, tw)
    assert rows[0]["vac_pos"] == 0.0  # no injury report and he played week 4: not a vacancy
    bt.add_breakout_context(rows, games, {}, tw, extra_out={"LEAD"})
    assert abs(next(r for r in rows if r["player_id"] == "B2")["vac_pos"] - 18 / 60) < 1e-9
