from metrics.availability import expected_games, miss_table, status_key, team_weeks
from metrics.features import injury_exit_weeks, injury_index


def _inj(gsis, week, status="", practice="", report_injury=""):
    return {"game_type": "REG", "gsis_id": gsis, "week": str(week), "report_status": status,
            "report_primary_injury": report_injury, "practice_primary_injury": practice}


def test_injury_index_ignores_rest_days_and_postseason():
    idx = injury_index([
        _inj("A", 3, "Out", "Hamstring", "Hamstring"),
        _inj("B", 3, "", "Not injury related - resting player"),
        _inj("C", 3, "", "Ankle"),
        {**_inj("D", 19, "Out", "Knee"), "game_type": "WC"},
    ])
    assert idx[("A", 3)] == {"status": "Out", "injured": True}
    assert idx[("B", 3)]["injured"] is False
    assert idx[("C", 3)] == {"status": "", "injured": True}
    assert ("D", 19) not in idx


def test_status_key():
    assert status_key(None) == "Healthy"
    assert status_key({"status": "Questionable", "injured": True}) == "Questionable"
    assert status_key({"status": "", "injured": True}) == "Listed"
    assert status_key({"status": "", "injured": False}) == "Healthy"


def _g(week, snap, listed=False, listed_next=False):
    return {"week": week, "snap_pct": snap, "inj_listed": listed, "inj_listed_next": listed_next}


def test_injury_exit_needs_low_snaps_and_an_injury_listing():
    past = [_g(1, 0.9), _g(2, 0.85), _g(3, 0.3, listed_next=True), _g(4, 0.3), _g(5, 0.88)]
    # Week 3: under half his median and on the next report -> exit. Week 4: low but never listed -> real role.
    assert injury_exit_weeks(past) == {3}


def test_injury_exit_uses_only_the_games_passed_in():
    assert injury_exit_weeks([_g(1, 0.9), _g(2, 0.2, listed=True)]) == set()  # under 3 games: no baseline yet


def test_team_weeks_skip_byes_and_other_seasons():
    sched = [
        {"season": "2025", "game_type": "REG", "week": "1", "home_team": "AAA", "away_team": "BBB"},
        {"season": "2025", "game_type": "REG", "week": "3", "home_team": "BBB", "away_team": "AAA"},
        {"season": "2024", "game_type": "REG", "week": "2", "home_team": "AAA", "away_team": "BBB"},
        {"season": "2025", "game_type": "WC", "week": "19", "home_team": "AAA", "away_team": "BBB"},
    ]
    assert team_weeks(sched, 2025) == {"AAA": {1, 3}, "BBB": {1, 3}}


def test_miss_table_and_expected_games():
    obs = [
        {"status": "Out", "team_games": 6, "played": 3, "played_next": False},
        {"status": "Healthy", "team_games": 6, "played": 6, "played_next": True},
        {"status": "Healthy", "team_games": 6, "played": 3, "played_next": True},
    ]
    t = miss_table(obs)
    assert t["Out"] == {"n": 1, "play_next": 0.0, "miss_rate": 0.5}
    assert t["Healthy"]["miss_rate"] == 0.25
    assert t["Doubtful"]["n"] == 0 and t["Doubtful"]["miss_rate"] is None
    # 10 team games left: next 6 at the Out rate (3 of 6), the last 4 at the healthy rate (3 of 4).
    assert expected_games("Out", 10, t) == 6.0
    # A status with no data falls back to the healthy rate.
    assert expected_games("Doubtful", 4, t) == 3.0
