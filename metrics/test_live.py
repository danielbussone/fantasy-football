import pytest

from metrics import live
from metrics.grades import Model

TEAM_GAMES = {"team_targets": 30.0, "team_air": 240.0, "team_carries": 30.0, "team_i10": 2.0, "team_rush_yds": 120.0}


def _g(pid, pos, week, *, targets=0.0, carries=0.0, gbfl=0.0, team="AAA"):
    return {"player_id": pid, "player": pid.replace("_", " ").title(), "pos": pos, "team": team, "week": week, "gbfl": gbfl,
            "targets": float(targets), "rec": float(targets) * 0.6, "rec_yds": float(targets) * 7, "air_yds": float(targets) * 8,
            "rec20": 0.0, "carries": float(carries), "rush_yds": float(carries) * 4, "pass_yds": 0.0, "attempts": 0.0, "sacks": 0.0,
            "pass_air": 0.0, "epa": 0.0, "cpoe": None, "snap_pct": 0.7, "rz_tgt": 0.0, "ez_tgt": 0.0, "deep_tgt": 0.0,
            "i10_car": 0.0, "run15": 0.0, "run26": 0.0, "deep_att": 0.0, "scrambles": 0.0, "implied": 24.0,
            "scrim_yds": float(targets) * 7 + float(carries) * 4, "inj_listed": False, "inj_listed_next": False, **TEAM_GAMES}


def _model(feats, coefs):
    return Model(feats, [0.0] * len(feats), [1.0] * len(feats), coefs).to_dict()


MISS = {"Out": {"miss_rate": 0.55}, "Doubtful": {"miss_rate": 0.42}, "Questionable": {"miss_rate": 0.23},
        "Listed": {"miss_rate": 0.15}, "Healthy": {"miss_rate": 0.20}}
WEIGHTS = {
    "positions": {"WR": {"models": {"par": _model(["ppg", "wopr"], [0.0, 0.4, 1.0])}},
                  "RB": {"models": {"par": _model(["ppg", "opp_share"], [0.0, 0.4, 1.0])}},
                  "TE": {"models": {"par": _model(["ppg", "wopr"], [0.0, 0.4, 1.0])}}},
    "miss_table": {"train": MISS},
    "rb_pedigree_bump": {"low_share": 1.0, "high_share": 0.5, "share_cut": 0.25},
}
PLAYERS = [
    {"gsis_id": "young_back", "rookie_season": "2026", "draft_round": "1", "draft_pick": "10"},
    {"gsis_id": "vet_back", "rookie_season": "2020", "draft_round": "1", "draft_pick": "10"},
    {"gsis_id": "lead_back", "rookie_season": "2020", "draft_round": "5", "draft_pick": "150"},
    {"gsis_id": "backup_back", "rookie_season": "2022", "draft_round": "7", "draft_pick": "230"},
]
SCHEDULE = [{"season": "2026", "game_type": "REG", "week": str(w), "home_team": "AAA", "away_team": "BBB",
             "total_line": "NA", "spread_line": "NA"} for w in range(1, 19)]


@pytest.fixture
def season(monkeypatch):
    games = []
    for w in (1, 2, 3):
        games += [_g("wr_top", "WR", w, targets=10, gbfl=3), _g("wr_mid", "WR", w, targets=5, gbfl=1), _g("wr_low", "WR", w, targets=1),
                  _g("young_back", "RB", w, carries=3, targets=1), _g("vet_back", "RB", w, carries=3, targets=1),
                  _g("lead_back", "RB", w, carries=18, targets=2, gbfl=2), _g("backup_back", "RB", w, carries=8, targets=1, gbfl=1)]
    injuries = [{"game_type": "REG", "gsis_id": "lead_back", "week": "4", "report_status": "Out",
                 "report_primary_injury": "Knee", "practice_primary_injury": ""}]
    state = {"injuries": injuries, "games": games}
    monkeypatch.setattr(live, "load_season_games", lambda s: games)
    monkeypatch.setattr(live, "load", lambda kind, season=None: {"games": SCHEDULE, "players": PLAYERS}.get(kind, []))
    monkeypatch.setattr(live, "_optional", lambda load, kind, s: state["injuries"])
    monkeypatch.setattr(live, "load_weights", lambda: WEIGHTS)
    monkeypatch.setattr(live, "read_meta", lambda: {"as_of": "t"})
    monkeypatch.setattr("metrics.rows.replacement_rank", lambda pos: 2)  # a 7-player league: the top 2 are rostered
    live.clear()
    yield state
    live.clear()


def test_role_percentile_and_par_follow_usage(season):
    d = live.compute(4)
    assert d["available"] and d["decision_week"] == 3
    wr = {n: live.lookup(d, n, "WR") for n in ("Wr Top", "Wr Mid", "Wr Low")}
    assert (wr["Wr Top"]["role"], wr["Wr Mid"]["role"], wr["Wr Low"]["role"]) == (100, 50, 0)
    # The pool is short of 60 WRs, so replacement is the worst WR: his PAR is zero and the others sit above it.
    assert wr["Wr Low"]["par"] == 0 and wr["Wr Mid"]["par"] > 0 and wr["Wr Top"]["par"] > wr["Wr Mid"]["par"]


def test_expected_games_use_the_status_table(season):
    d = live.compute(4)
    healthy = live.lookup(d, "Wr Top", "WR")
    assert healthy["team_games_left"] == 15  # weeks 4-18
    assert abs(healthy["exp_games"] - 15 * 0.8) < 0.06  # the healthy miss rate over the whole stretch
    rec = {"player": "Wr Top", "pos": "WR", "team": "AAA", "injury": {"designation": "Questionable"}}
    q = live.grade_for(d, rec)
    assert q["status"] == "Questionable" and q["exp_games"] < healthy["exp_games"]


def test_ir_slot_is_out_for_at_least_four_games(season):
    d = live.compute(4)
    ir = live.grade_for(d, {"player": "Wr Top", "pos": "WR", "team": "AAA", "slot": "IR"})
    assert ir["status"] == "Out" and ir["exp_games"] <= d["players"]["wr_top"]["team_games_left"] - 4


def test_pedigree_bump_only_for_young_high_pick_backs(season):
    d = live.compute(4)
    young, vet = live.lookup(d, "Young Back", "RB"), live.lookup(d, "Vet Back", "RB")
    assert young["bump"] == 1.0 and vet["bump"] == 0.0  # low opportunity share, so the larger bump
    assert abs((young["pred_ppg"] - vet["pred_ppg"]) - 1.0) < 1e-9
    assert young["par"] > vet["par"]


def test_next_man_up_flag_when_the_lead_back_is_out(season):
    d = live.compute(4)
    assert live.lookup(d, "Backup Back", "RB")["flags"] == ["next_up"]
    assert "next_up" not in live.lookup(d, "Young Back", "RB")["flags"]  # smaller share, not the next man up


def test_buy_low_needs_a_young_high_pick_in_the_waiver_tier(season):
    d = live.compute(4)
    assert d["buy_low_active"]
    assert "buy_low" in live.lookup(d, "Young Back", "RB")["flags"]
    assert "buy_low" not in live.lookup(d, "Vet Back", "RB")["flags"]


def test_players_nflverse_does_not_know_get_no_grade(season):
    d = live.compute(4)
    assert live.grade_for(d, {"player": "Nobody Special", "pos": "WR", "team": "AAA"}) is None
    assert live.wants_in_pool(d, {"player": "Wr Mid", "pos": "WR", "team": "AAA"})
    assert not live.wants_in_pool(d, {"player": "Nobody Special", "pos": "WR", "team": "AAA"})


def test_unavailable_without_weights_or_enough_weeks(monkeypatch, season):
    monkeypatch.setattr(live, "load_weights", lambda: {})
    live.clear()
    assert live.compute(4)["available"] is False
    monkeypatch.setattr(live, "load_weights", lambda: WEIGHTS)
    live.clear()
    assert live.compute(2)["available"] is False  # only one completed week
    assert live.grade_for(live.compute(2), {"player": "Wr Top", "pos": "WR"}) is None


def test_status_from_designation():
    s = live.status_from_designation
    assert (s("Out"), s("IR"), s("Doubtful"), s("Questionable"), s("Probable"), s("")) == ("Out", "Out", "Doubtful", "Questionable", None, None)


def test_dst_and_kicker_streams_rank_by_vegas():
    vegas = {"teams": {"AAA": {"total": 28.0, "opp": "BBB", "indoor": True}, "BBB": {"total": 17.0, "opp": "AAA", "indoor": True},
                       "CCC": {"total": 22.0, "opp": "DDD", "indoor": False}, "DDD": {"total": 21.0, "opp": "CCC", "indoor": False}}}
    dst = live.dst_stream(vegas)
    assert dst["AAA"]["opp_total"] == 17.0 and dst["AAA"]["rank"] == 1  # AAA's defense faces the 17-point offense
    assert dst["BBB"]["rank"] == 4 and dst["AAA"]["score"] > dst["CCC"]["score"] > dst["BBB"]["score"]
    kick = live.kicker_stream(vegas)
    assert kick["AAA"]["rank"] == 1 and kick["BBB"]["rank"] == 4 and kick["AAA"]["dome"]
    assert live.dst_stream({}) == {} and live.kicker_stream({}) == {}


def test_trackers_split_free_and_rostered_and_gate_the_wr_watch_list(season):
    d = live.compute(4)
    roster = [{"player": "Young Back", "pos": "RB", "owner": "BOLDING"}]
    fa = [{"player": "Wr Mid", "pos": "WR", "status": ""}, {"player": "Backup Back", "pos": "RB", "status": "waivers"}]
    t = live.trackers(d, 4, roster, fa)
    young = next(c for c in t["buy_low"] if c["player"] == "Young Back")
    assert young["owner"] == "BOLDING" and not young["available"]
    nxt = t["next_up"][0]
    assert nxt["player"] == "Backup Back" and nxt["waiver_status"] == "waivers" and nxt["available"]
    assert t["wr_watch"]["active"] is False and t["wr_watch"]["players"]
    assert live.trackers(d, 8, roster, fa)["wr_watch"]["active"] is True
    assert live.trackers({"available": False}, 4, [], [])["buy_low"] == []


def test_a_player_the_app_knows_is_out_makes_his_backup_next_up_without_an_nflverse_report(season):
    season["injuries"] = []  # nflverse's report says nothing: IR players aren't on it
    plain = live.compute(4)
    assert live.lookup(plain, "Backup Back", "RB")["flags"] == []
    d = live.compute(4, out_names=frozenset({"lead back"}))  # the app's ESPN notes / CBS IR slot
    assert live.lookup(d, "Backup Back", "RB")["flags"] == ["next_up"]
    assert live.lookup(d, "Lead Back", "RB")["status"] == "Out"


def test_someone_out_for_weeks_is_not_a_fresh_vacancy(season):
    season["injuries"] = []
    # A back who last played in week 1 is long gone: his work is already spread around.
    season["games"][:] = [g for g in season["games"] if not (g["player_id"] == "lead_back" and g["week"] > 1)]
    d = live.compute(4, out_names=frozenset({"lead back"}))
    assert live.lookup(d, "Backup Back", "RB")["flags"] == []


def _qb(pid, week, gbfl, epa):
    g = _g(pid, "QB", week, gbfl=gbfl, carries=3)
    g.update({"attempts": 30.0, "sacks": 2.0, "epa": epa, "targets": 0.0, "rec": 0.0, "rec_yds": 0.0, "air_yds": 0.0})
    return g


def test_qbs_are_ranked_by_projected_points_not_usage(season, monkeypatch):
    qb_model = _model(["ppg", "prior_ppg_i", "has_prior", "ppg_x_g", "prior_x_g", "epa_i"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    monkeypatch.setitem(WEIGHTS, "qb_ros", {"model": qb_model, "mean_prior": 9.0})
    for w in (1, 2, 3):
        season["games"] += [_qb("hot_qb", w, 12.0, 8.0), _qb("mid_qb", w, 10.0, 3.0), _qb("cold_qb", w, 14.0, -2.0)]
    monkeypatch.setattr(live, "_qb_games", lambda s: {})
    live.clear()
    d = live.compute(4)
    qbs = {n: live.lookup(d, n, "QB") for n in ("Hot Qb", "Mid Qb", "Cold Qb")}
    assert qbs["Hot Qb"]["usage_stat"] == "epa"
    # the toy model weights only EPA, so the QB with the most points so far still ranks last
    assert [qbs[n]["rank"] for n in ("Hot Qb", "Mid Qb", "Cold Qb")] == [1, 2, 3]
    assert qbs["Hot Qb"]["of"] == 3 and qbs["Hot Qb"]["role"] == 100 and qbs["Cold Qb"]["role"] == 0
    assert qbs["Hot Qb"]["par"] > 0 and qbs["Cold Qb"]["par"] == 0  # replacement is the 3rd QB with two rostered
    assert live.grade_for(d, {"player": "Hot Qb", "pos": "QB", "team": "AAA"})["rank"] == 1


def test_no_qb_model_means_no_qb_grades(season):
    for w in (1, 2, 3):
        season["games"].append(_qb("solo_qb", w, 10.0, 1.0))
    live.clear()
    assert live.lookup(live.compute(4), "Solo Qb", "QB") is None
