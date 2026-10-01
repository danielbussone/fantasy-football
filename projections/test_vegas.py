from projections.vegas import apply_vegas, league_average_total, team_totals_from_scoreboard

# Real week-3 shape, captured live during exploration (GB -5.5 / 42.5 total
# home favorite; DET a dome game).
SAMPLE_SCOREBOARD = {
    "week": {"number": 3},
    "events": [
        {
            "date": "2026-09-25T00:15Z",
            "weather": {"temperature": 61},
            "competitions": [
                {
                    "venue": {"indoor": False},
                    "competitors": [
                        {"homeAway": "home", "team": {"abbreviation": "GB"}},
                        {"homeAway": "away", "team": {"abbreviation": "ATL"}},
                    ],
                    "odds": [{"overUnder": 42.5, "spread": -5.5}],
                }
            ],
        },
        {
            "date": "2026-09-27T17:00Z",
            "weather": {"temperature": 70},
            "competitions": [
                {
                    "venue": {"indoor": True},
                    "competitors": [
                        {"homeAway": "home", "team": {"abbreviation": "DET"}},
                        {"homeAway": "away", "team": {"abbreviation": "NYJ"}},
                    ],
                    "odds": [{"overUnder": 47.5, "spread": -6.5}],
                }
            ],
        },
    ],
}


def test_team_totals_split_by_spread_confirmed_against_real_line():
    """GB -5.5 on a 42.5 total, a real week-3 line: GB 24.0 / ATL 18.5."""
    totals = team_totals_from_scoreboard(SAMPLE_SCOREBOARD)
    assert totals["GB"]["total"] == 24.0
    assert totals["ATL"]["total"] == 18.5
    assert totals["GB"]["opp"] == "ATL"
    assert totals["ATL"]["opp"] == "GB"
    assert totals["GB"]["total"] + totals["ATL"]["total"] == 42.5


def test_team_totals_indoor_and_kickoff_carried_through():
    totals = team_totals_from_scoreboard(SAMPLE_SCOREBOARD)
    assert totals["DET"]["indoor"] is True
    assert totals["NYJ"]["indoor"] is True  # same game/venue
    assert totals["NYJ"]["kickoff"] == "2026-09-27T17:00Z"


def test_league_average_is_mean_of_team_totals():
    totals = team_totals_from_scoreboard(SAMPLE_SCOREBOARD)
    avg = league_average_total(totals)
    assert abs(avg - (sum(t["total"] for t in totals.values()) / len(totals))) < 0.01


def test_team_abbreviation_aliases_normalized_to_repo_canonical():
    """The scoreboard endpoint says JAX/WSH; CBS and this repo's own ESPN
    fantasy-API mapping (projections/espn.py PRO_TEAM) say JAC/WAS — a
    player's team lookup must find their Vegas line under either name.
    """
    payload = {
        "events": [
            {
                "date": "2026-09-28T17:00Z",
                "competitions": [
                    {
                        "venue": {"indoor": True},
                        "competitors": [
                            {"homeAway": "home", "team": {"abbreviation": "JAX"}},
                            {"homeAway": "away", "team": {"abbreviation": "NE"}},
                        ],
                        "odds": [{"overUnder": 45.5, "spread": -3.0}],
                    }
                ],
            },
            {
                "date": "2026-09-28T20:20Z",
                "competitions": [
                    {
                        "venue": {"indoor": False},
                        "competitors": [
                            {"homeAway": "home", "team": {"abbreviation": "WSH"}},
                            {"homeAway": "away", "team": {"abbreviation": "PHI"}},
                        ],
                        "odds": [{"overUnder": 44.0, "spread": 2.5}],
                    }
                ],
            },
        ]
    }
    totals = team_totals_from_scoreboard(payload)
    assert "JAC" in totals and "JAX" not in totals
    assert "WAS" in totals and "WSH" not in totals
    assert totals["JAC"]["opp"] == "NE"


def test_missing_odds_still_records_kickoff_and_indoor():
    payload = {
        "events": [
            {
                "date": "2026-09-28T20:20Z",
                "competitions": [
                    {
                        "venue": {"indoor": False},
                        "competitors": [
                            {"homeAway": "home", "team": {"abbreviation": "SEA"}},
                            {"homeAway": "away", "team": {"abbreviation": "ARI"}},
                        ],
                        "odds": [],
                    }
                ],
            }
        ]
    }
    totals = team_totals_from_scoreboard(payload)
    assert totals["SEA"]["total"] is None
    assert totals["SEA"]["kickoff"] == "2026-09-28T20:20Z"


def test_apply_vegas_moves_favorite_up_and_underdog_down():
    vegas_data = {"league_avg": 22.0, "teams": team_totals_from_scoreboard(SAMPLE_SCOREBOARD)}
    prior = {"pos": "WR", "scrim_ypg": 60, "rec_td_rate": 0.3}
    fav = apply_vegas(dict(prior), "GB", "WR", vegas_data)  # 24.0 / 22.0 > 1
    dog = apply_vegas(dict(prior), "ATL", "WR", vegas_data)  # 18.5 / 22.0 < 1
    assert fav["rec_td_rate"] > prior["rec_td_rate"] > dog["rec_td_rate"]
    assert fav["scrim_ypg"] > prior["scrim_ypg"] > dog["scrim_ypg"]


def test_apply_vegas_is_a_noop_without_a_line():
    prior = {"pos": "WR", "scrim_ypg": 60}
    out = apply_vegas(dict(prior), "ZZZ", "WR", {"league_avg": 22.0, "teams": {}})
    assert out == prior


def test_apply_vegas_dst_uses_opponent_total_for_pa():
    vegas_data = {"league_avg": 22.0, "teams": team_totals_from_scoreboard(SAMPLE_SCOREBOARD)}
    prior = {"pos": "DST", "pa_mean": 20.0}
    # Falcons' DST faces GB, a 24.0-point Vegas favorite — PA prior should
    # move up toward that, not stay flat at the season-long average.
    out = apply_vegas(dict(prior), "ATL", "DST", vegas_data)
    assert out["pa_mean"] > prior["pa_mean"]
    assert out["pa_mean"] == round(0.4 * 20.0 + 0.6 * 24.0, 2)


def test_apply_vegas_kicker_scales_with_own_team_total():
    vegas_data = {"league_avg": 22.0, "teams": team_totals_from_scoreboard(SAMPLE_SCOREBOARD)}
    prior = {"pos": "K", "fg_rate": 1.8, "xp_mean": 2.5}
    fav = apply_vegas(dict(prior), "GB", "K", vegas_data)
    dog = apply_vegas(dict(prior), "ATL", "K", vegas_data)
    assert fav["fg_rate"] > prior["fg_rate"] > dog["fg_rate"]


def test_apply_vegas_ratio_is_clamped():
    vegas_data = {"league_avg": 10.0, "teams": {"BLOWOUT": {"total": 40.0, "opp": "X"}}}
    out = apply_vegas({"pos": "WR", "rec_td_rate": 0.2}, "BLOWOUT", "WR", vegas_data)
    assert out["vegas_ratio"] == 1.8  # clamped, not 4.0
