from projections.espn import blend_espn, parse_kona, player_row, stats_to_prior
from projections.weekly import blend_espn as blend_from_weekly


def test_hurts_week1_stat_map():
    stats = {"3": 229.105, "4": 1.661, "24": 27.461, "25": 0.636}
    prior = stats_to_prior("QB", stats)
    # qb_ypg is pass+rush together, matching history/3g priors and the sim.
    assert abs(prior["qb_ypg"] - (229.105 + 27.461)) < 0.01
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


def test_espn_mix_flavors_are_mc_half_espn():
    from projections.espn import mix_label, snap_espn_mix
    from projections.weekly import usage_block

    assert snap_espn_mix(0) == 0.0
    assert snap_espn_mix(0.45) == 0.5
    assert snap_espn_mix(0.9) == 1.0
    assert mix_label(0) == "Monte Carlo" and mix_label(1) == "ESPN"
    base = {"qb_ypg": 200, "targets_pg": 8, "source": "history"}
    espn = {"qb_ypg": 240, "targets": 10}
    mc = blend_espn(base, espn, 0)
    assert mc["qb_ypg"] == 200 and mc.get("targets_pg") == 8
    assert "+espn" not in (mc.get("source") or "")
    half = blend_espn(base, espn, 0.5)
    assert half["qb_ypg"] == 220 and half["targets_pg"] == 9
    full = blend_espn(base, espn, 1)
    assert full["qb_ypg"] == 240 and full["targets_pg"] == 10
    assert full["source"] == "espn week stats"
    assert usage_block({"source": "season history+espn"}).get("source") == "season history+espn"
    assert usage_block({"source": "espn week stats"}).get("source") == "espn week stats"


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
    assert float(row["pass_yds"]) > 200
    parsed = parse_kona({"players": [entry]}, 1)
    assert parsed[0]["espn_id"] == 4040715
    # appliedTotal is not a prior key
    assert "present" not in row


def test_espn_stat_line_is_volume_not_fpts():
    from projections.espn import espn_stat_line, espn_to_sim, hydrate_espn, raw_stats

    raw = raw_stats({"23": 0, "24": 1.22, "25": 0.01, "42": 88.8, "43": 0.65, "53": 7.1, "58": 10.2})
    assert abs(raw["targets"] - 10.2) < 0.01
    assert abs(raw["receptions"] - 7.1) < 0.01
    line = espn_stat_line({**raw, "pos": "WR"}, "WR")
    assert "12.93" not in line
    assert "tar" in line and "rec yds" in line
    old = hydrate_espn({"pos": "WR", "scrim_ypg": 90.02, "rec_share": 0.9864, "rec_td_rate": 0.65})
    assert abs(old["rec_yds"] - 88.8) < 0.2
    sim = espn_to_sim(old)
    assert sim["rec_yds"] > 80


def test_player_row_stores_targets_and_receptions():
    entry = {
        "id": 4362628,
        "player": {
            "id": 4362628,
            "fullName": "Ja'Marr Chase",
            "defaultPositionId": 3,
            "proTeamId": 4,
            "stats": [
                {
                    "statSourceId": 1,
                    "scoringPeriodId": 1,
                    "appliedTotal": 12.932,
                    "stats": {
                        "23": 0.24,
                        "24": 1.22,
                        "25": 0.01,
                        "42": 88.8,
                        "43": 0.65,
                        "53": 7.02,
                        "58": 10.14,
                    },
                }
            ],
        },
    }
    row = player_row(entry, 1)
    assert abs(float(row["targets"]) - 10.14) < 0.01
    assert abs(float(row["receptions"]) - 7.02) < 0.01
    from projections.espn import espn_stat_line

    line = espn_stat_line(row, "WR").replace("\xa0", " ")
    assert "10 tar" in line and "7 rec" in line
    assert "12.932" not in line


def test_refresh_espn_from_saved_cookies_no_cookie(tmp_path, monkeypatch):
    import projections.espn as espn_mod

    monkeypatch.setattr(espn_mod, "ESPN_COOKIES", tmp_path / "espn_cookies.txt")
    out = espn_mod.refresh_espn_from_saved_cookies(2)
    assert out["ok"] is False
    assert "no stored ESPN cookie" in out["error"]


def test_refresh_espn_from_saved_cookies_success(tmp_path, monkeypatch):
    import projections.espn as espn_mod

    cookie_path = tmp_path / "espn_cookies.txt"
    cookie_path.write_text("swid=abc", encoding="utf-8")
    monkeypatch.setattr(espn_mod, "ESPN_COOKIES", cookie_path)
    week_csv = tmp_path / "espn_week2.csv"
    monkeypatch.setattr(espn_mod, "ESPN_WEEK", tmp_path / "espn_week.csv")
    monkeypatch.setattr(espn_mod, "espn_week_csv", lambda week=None: week_csv if week else espn_mod.ESPN_WEEK)
    monkeypatch.setattr(espn_mod, "ESPN_META", tmp_path / "espn_week_meta.json")
    fake_rows = [{"player": "Jalen Hurts", "team": "PHI", "pos": "QB", "week": 2}]
    monkeypatch.setattr(espn_mod, "replay_kona", lambda cookie, week, limit=1000: fake_rows)
    out = espn_mod.refresh_espn_from_saved_cookies(2)
    assert out["ok"] is True
    assert out["n"] == 1
    assert week_csv.exists()


def test_refresh_espn_from_saved_cookies_expired_cookie_keeps_old_data(tmp_path, monkeypatch):
    import projections.espn as espn_mod

    cookie_path = tmp_path / "espn_cookies.txt"
    cookie_path.write_text("swid=abc", encoding="utf-8")
    monkeypatch.setattr(espn_mod, "ESPN_COOKIES", cookie_path)
    monkeypatch.setattr(espn_mod, "replay_kona", lambda cookie, week, limit=1000: [])
    out = espn_mod.refresh_espn_from_saved_cookies(2)
    assert out["ok"] is False
    assert "0 players" in out["error"]


def test_load_espn_ignores_other_week(tmp_path):
    from projections.espn import FIELDS, load_espn

    p = tmp_path / "espn.csv"
    p.write_text(
        ",".join(FIELDS)
        + "\n"
        + ",".join("1" if k == "week" else ("Jordan Love" if k == "player" else "") for k in FIELDS)
        + "\n",
        encoding="utf-8",
    )
    assert load_espn(path=p, week=2) == {}
    hit = load_espn(path=p, week=1)
    assert "jordan love" in hit

