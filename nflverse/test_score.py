import csv

from nflverse import score
from nflverse.score import check_against_cbs, score_player_week, td_events


def _play(**kw):
    base = {"week": "1", "touchdown": "0", "two_point_attempt": "0", "pass_touchdown": "0",
            "rush_touchdown": "0", "return_touchdown": "0", "play_type": "pass", "yards_gained": "0",
            "td_player_id": "", "passer_player_id": "", "receiver_player_id": "", "rusher_player_id": "",
            "return_yards": ""}
    base.update(kw)
    return base


def _week_row(**kw):
    base = {"player_id": "WR1", "player_display_name": "Wide Out", "position": "WR", "week": "1",
            "season_type": "REG", "passing_yards": "0", "rushing_yards": "0", "receiving_yards": "0",
            "passing_2pt_conversions": "0", "rushing_2pt_conversions": "0", "receiving_2pt_conversions": "0"}
    base.update(kw)
    return base


def test_pass_td_credits_passer_and_scorer_at_play_distance():
    ev = td_events([_play(touchdown="1", pass_touchdown="1", yards_gained="46",
                          passer_player_id="QB1", receiver_player_id="WR1", td_player_id="WR1")])
    assert ev[("QB1", 1)]["pass"] == [46.0]
    assert ev[("WR1", 1)]["rec"] == [46.0]


def test_two_point_plays_and_defensive_returns_are_not_player_tds():
    ev = td_events([
        _play(touchdown="1", pass_touchdown="1", two_point_attempt="1", yards_gained="2", td_player_id="WR1"),
        _play(touchdown="1", return_touchdown="1", play_type="pass", yards_gained="40", td_player_id="CB1"),
    ])
    assert ("WR1", 1) not in ev
    assert ("CB1", 1) not in ev


def test_kickoff_return_td_uses_return_yards():
    ev = td_events([_play(touchdown="1", return_touchdown="1", play_type="kickoff",
                          td_player_id="WR1", return_yards="98")])
    assert ev[("WR1", 1)]["ret"] == [98.0]


def test_wr_46_yard_receiving_td_is_4_points():
    # 30 yards is under the 70-yard bucket; base 1 + 46–60 bonus 3.
    row = _week_row(receiving_yards="30")
    assert score_player_week(row, {"pass": [], "rush": [], "rec": [46.0], "ret": []}) == 4.0


def test_te_receiving_td_uses_rushing_bands_and_lower_bucket():
    ev = {"pass": [], "rush": [], "rec": [30.0], "ret": []}
    # TE: 45 yards clears the 40-yard bucket (1); 30-yd TD is rushing band 26–40 (+3) = 4. Total 5.
    assert score_player_week(_week_row(position="TE", receiving_yards="45"), ev) == 5.0
    # Same line as a WR: under the 70 bucket (0); 30-yd TD is passing band 16–30 (+1) = 2.
    assert score_player_week(_week_row(receiving_yards="45"), ev) == 2.0


def test_two_point_conversion_counts_one():
    assert score_player_week(_week_row(receiving_2pt_conversions="1"), None) == 1.0


def test_check_against_cbs_matches_by_normalized_name(tmp_path, monkeypatch):
    monkeypatch.setattr(score, "ROOT", tmp_path)
    fields = ["player", "team", "pos", "Yds", "TD", "Yds_2", "TD_2", "Tar", "Rec", "Total"]
    with (tmp_path / "cbs_stats_week1.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow({"player": "Wide Out Jr.", "team": "X", "pos": "WR", "Yds": "112", "TD": "0",
                    "Yds_2": "0", "TD_2": "0", "Tar": "8", "Rec": "7", "Total": "3"})
        w.writerow({"player": "Nobody Here", "team": "X", "pos": "WR", "Yds": "10", "TD": "0",
                    "Yds_2": "0", "TD_2": "0", "Tar": "1", "Rec": "1", "Total": "0"})
    res = check_against_cbs([_week_row(receiving_yards="112")], [], [1])
    assert res["n"] == 1 and res["exact"] == 1 and res["rate"] == 1.0
    assert [u["player"] for u in res["unmatched"]] == ["Nobody Here"]


def test_kicker_scoring_uses_made_fg_distances_and_xps():
    from nflverse.score import kicker_games, score_kicker

    pbp = [
        _play(play_type="field_goal", kicker_player_id="K1", posteam="AAA", kick_distance="52", field_goal_result="made"),
        _play(play_type="field_goal", kicker_player_id="K1", posteam="AAA", kick_distance="38", field_goal_result="made"),
        _play(play_type="field_goal", kicker_player_id="K1", posteam="AAA", kick_distance="55", field_goal_result="missed"),
        _play(play_type="extra_point", kicker_player_id="K1", posteam="AAA", extra_point_result="good"),
        _play(play_type="extra_point", kicker_player_id="K1", posteam="AAA", extra_point_result="failed"),
    ]
    k = kicker_games(pbp)[("K1", 1)]
    assert (k["fg_att"], k["fg_att_50"], k["xp"], k["xp_att"]) == (3, 2, 1, 2)
    assert score_kicker(k) == 3.0 + 1.0 + 0.5  # 52-yd FG = 3, 38-yd = 1, one XP = 0.5


def test_dst_scoring_with_return_td_and_points_against():
    from nflverse.score import dst_games, score_dst

    pbp = [
        _play(sack="1", defteam="DEF", posteam="OFF"), _play(sack="1", defteam="DEF", posteam="OFF"),
        _play(touchdown="1", return_touchdown="1", td_team="DEF", return_yards="55", interception="1"),
    ]
    team_week = [{"team": "DEF", "week": "1", "season_type": "REG", "def_sacks": "1", "def_interceptions": "1",
                  "fumble_recovery_opp": "1", "def_safeties": "0"}]
    sched = [{"season": "2025", "game_type": "REG", "week": "1", "home_team": "DEF", "away_team": "OFF",
              "home_score": "24", "away_score": "13"}]
    g = dst_games(pbp, team_week, sched, 2025)[("DEF", 1)]
    assert g["sacks"] == 2  # from play-by-play, not the weekly stat
    assert g["pa"] == 13 and g["def_td_yards"] == [55.0]
    # 2 sacks + 1 INT + 1 FR = 2.0; PA 13 = 3; 55-yd return TD = 5 -> 10
    assert score_dst(g) == 10.0


def test_truncated_download_is_never_cached(tmp_path, monkeypatch):
    import gzip
    import io

    import pytest

    from nflverse import pull

    import os

    good = gzip.compress(b"a,b\n" + os.urandom(2000).hex().encode())  # random, so it doesn't compress to a few bytes

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    dest = tmp_path / "f.csv.gz"
    monkeypatch.setattr(pull, "urlopen", lambda *a, **k: Resp(good[: len(good) // 2]))  # cut off mid-stream
    with pytest.raises(EOFError):
        pull._download("http://example/f.csv.gz", dest)
    assert not dest.exists()
    monkeypatch.setattr(pull, "urlopen", lambda *a, **k: Resp(good))
    pull._download("http://example/f.csv.gz", dest)
    assert dest.exists()
