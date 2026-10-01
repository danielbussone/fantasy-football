from cbs_client import norm
from cbs_pull import week_stat_periods
from scoring.actuals import line_has_box, mix_ev, row_to_actuals, score_actual_line
from scoring.rules import receiving_td_points, rb_wr_yard_points
from projections.weekly import REC_TD_DIST
from report.week_card import band_hit, build_report, grade_rows, outlook_row, sit_misses
from report.snapshot import snapshot_from_payload


def test_yards_exact_td_mix_ev():
    rec_ev = mix_ev(REC_TD_DIST, lambda d: receiving_td_points(d, "WR"))
    hit = score_actual_line("WR", rec_yds=142, rec_td=1)
    assert rb_wr_yard_points(142) == 4
    assert hit["pts"] == round(4 + rec_ev, 2)
    assert "mix EV" in hit["why"]
    assert "142 rec yds" in hit["why"]
    two = score_actual_line("WR", rec_yds=0, rec_td=2)
    assert two["pts"] == round(2 * rec_ev, 2)


def test_dst_pa_and_sacks_exact():
    hit = score_actual_line("DST", pa=13, sacks=4, ints=0, fr=0)
    assert hit["pts"] == 5.0  # PA 10–14 = 3, 4 sacks * 0.5
    assert "PA 13" in hit["why"]


def test_row_to_actuals_wr_yds_are_receiving():
    line = row_to_actuals({"player": "Ja'Marr Chase", "pos": "WR", "Yds": "142", "TD": "1", "Yds_2": "4"})
    assert line["rec_yds"] == 142
    assert line["rush_yds"] == 4
    assert line["rec_td"] == 1


def test_band_hit():
    proj = {"p25": 1, "p50": 2, "p75": 4}
    assert band_hit(0, proj) == "bust"
    assert band_hit(2, proj) == "typical"
    assert band_hit(5, proj) == "boom"


def _snap_players(**rows):
    players = {}
    starters = []
    bench = []
    for name, rec in rows.items():
        pos = rec["pos"]
        slot = rec.get("slot", "")
        p50 = rec.get("p50", 2)
        mean = rec.get("mean", p50)
        key = norm(name)
        players[key] = {
            "player": name,
            "pos": pos,
            "slot": slot,
            "proj": {"p10": 0, "p25": rec.get("p25", 1), "p50": p50, "p75": rec.get("p75", 4), "p90": 8, "mean": mean, "usage": rec.get("usage") or {}},
            "espn_line": rec.get("espn_line") or "",
            "injury": rec.get("injury"),
            "depth_rank": rec.get("depth_rank", 1),
            "role_note": rec.get("role_note") or f"{pos}{rec.get('depth_rank', 1)}",
        }
        if rec.get("rec"):
            starters.append({"player": name, "pos": pos, "slot": slot})
        else:
            bench.append({"player": name, "pos": pos, "slot": slot})
    return {
        "week": 1,
        "mix": 0.5,
        "mix_label": "50/50",
        "players": players,
        "lineup_p50": {
            "starters": starters,
            "bench": bench,
            "why": [{"player": "Kenneth Walker III vs Blake Corum", "text": "Close skill call.", "kind": "close"}],
        },
    }


def test_lineup_miss_sat_who_outscored():
    snap = _snap_players(
        **{
            "Kenneth Walker III": {"pos": "RB", "slot": "RB", "p50": 2, "rec": True},
            "Blake Corum": {"pos": "RB", "slot": "", "p50": 1, "rec": False},
        }
    )
    actuals = {
        "kenneth walker": {"pts": 1, "why": "short day"},
        "blake corum": {"pts": 4, "why": "boom"},
    }
    misses = sit_misses(snap, actuals)
    text = " ".join(m["text"] for m in misses)
    assert "Walker" in text and "Corum" in text
    assert any(m["sat"] == "Blake Corum" and m["started"] == "Kenneth Walker III" for m in misses)


def test_prior_move_tags():
    locked = {
        "player": "Ja'Marr Chase",
        "pos": "WR",
        "proj": {"p50": 3, "mean": 3, "usage": {"has_3g": False, "targets": 11, "carries": 0, "g3_targets": None}},
        "injury": {"designation": "Questionable", "out": False},
        "depth_rank": 2,
        "role_note": "CIN WR2",
        "espn_line": "10 tar",
    }
    now = {
        "player": "Ja'Marr Chase",
        "pos": "WR",
        "proj": {"p50": 4, "mean": 4, "usage": {"has_3g": True, "targets": 8, "carries": 0, "g3_targets": 8}},
        "injury": {"designation": "Out", "out": True},
        "depth_rank": 1,
        "role_note": "CIN WR1",
        "espn_line": "12 tar",
    }
    row = outlook_row(locked, now, week_now=2, week_lock=1, mix_now="50/50", mix_lock="50/50")
    assert row["drivers"] == ["3g", "Injury", "Depth", "ESPN"]
    assert "targets 11 → 8" in row["note"]
    assert "3g now in the mix" in row["note"]
    assert "Q → Out" in row["note"]
    assert "CIN WR2 → CIN WR1" in row["note"]
    assert "not 3g" in row["note"]
    assert row["delta"] == 1


def test_no_lock_and_no_actuals_states(monkeypatch):
    monkeypatch.setattr("report.snapshot.load_snapshot", lambda week, mock=False: None)
    card = build_report(1, snap=None, now={"week": 1, "roster": [], "waivers": {}, "espn_mix_label": "50/50"}, actuals={})
    assert card["status"] == "no_lock"
    snap = snapshot_from_payload(
        {
            "week": 1,
            "team": "BUSSONE",
            "espn_mix": 0.5,
            "espn_mix_label": "50/50",
            "roster": [{"player": "Ja'Marr Chase", "pos": "WR", "slot": "WR", "proj": {"p10": 1, "p25": 2, "p50": 3, "p75": 5, "p90": 8, "usage": {}}}],
            "fa_sample": [],
            "lineup_p50": {"starters": [{"player": "Ja'Marr Chase", "pos": "WR"}], "bench": [], "why": []},
        }
    )
    card = build_report(1, snap=snap, now={"week": 1, "roster": [], "fa_sample": [], "waivers": {}, "espn_mix_label": "50/50", "data_flags": {}}, actuals={})
    assert card["status"] == "no_actuals"
    assert card["locked_lineup"]


def test_ready_report_grades():
    snap = _snap_players(
        **{
            "Ja'Marr Chase": {"pos": "WR", "slot": "WR", "p50": 3, "p25": 1, "p75": 5, "rec": True},
            "CeeDee Lamb": {"pos": "WR", "slot": "WR", "p50": 2, "p25": 1, "p75": 4, "rec": True},
            "Kenneth Walker III": {"pos": "RB", "slot": "RB", "p50": 2, "rec": True},
        }
    )
    actuals = {
        "ja'marr chase": {"pts": 7, "why": "142 rec yds → 130–149 bucket = 4; 1 rec TD at mix EV."},
        "ceedee lamb": {"pts": 0, "why": "54 rec yds → <70 = 0; no TD."},
    }
    now = {
        "week": 1,
        "espn_mix": 0.5,
        "espn_mix_label": "50/50",
        "roster": [
            {"player": "Ja'Marr Chase", "pos": "WR", "proj": {"p50": 3, "usage": {}}, "espn_line": "", "injury": None, "depth_rank": 1, "role_note": "CIN WR1"},
            {"player": "CeeDee Lamb", "pos": "WR", "proj": {"p50": 2, "usage": {}}, "espn_line": "", "injury": None, "depth_rank": 1, "role_note": "DAL WR1"},
        ],
        "fa_sample": [],
        "waivers": {"recommendations": [], "roster_scored": [], "fa_top": []},
        "data_flags": {"has_3g_usage": False},
    }
    card = build_report(1, snap=snap, now=now, actuals=actuals)
    assert card["status"] == "ready"
    by = {g["player"]: g for g in card["grades"]}
    assert by["Ja'Marr Chase"]["band"] == "boom"
    assert by["CeeDee Lamb"]["band"] == "bust"
    assert "Kenneth Walker III" not in by
    assert "Kenneth Walker III" in (card.get("pending") or [])
    assert card["went_right"][0]["player"] == "Ja'Marr Chase"
    assert card["went_wrong"][0]["player"] == "CeeDee Lamb"
    assert "outlook_note" in card


def test_week_period_is_n_not_weekn():
    assert week_stat_periods(1)[0] == "1"
    assert "week1" in week_stat_periods(1)
    assert "tp" not in week_stat_periods(1)
    assert "tp" not in week_stat_periods(2)


def test_cbs_opp_at_vs():
    from cbs_pull import format_cbs_opp

    assert format_cbs_opp("@NYJ") == "at NYJ"
    assert format_cbs_opp("SF") == "vs. SF"


def test_empty_box_is_pending_not_zero():
    assert not line_has_box({"pos": "QB", "pass_yds": 0, "rush_yds": 0, "pass_td": 0, "rush_td": 0})
    assert line_has_box({"pos": "QB", "pass_yds": 245, "rush_yds": 3, "pass_td": 4, "rush_td": 0})
    assert line_has_box({"pos": "WR", "rec_yds": 54, "rush_yds": 0, "rec_td": 0, "rush_td": 0})
    assert not line_has_box({"pos": "DST", "pa": None, "sacks": 0})
    assert not line_has_box({"pos": "DST", "pa": 0, "sacks": 0})
    assert line_has_box({"pos": "DST", "pa": 22, "sacks": 0})
    hit = score_actual_line("DST", sacks=3)
    assert "PA 22" not in hit["why"]
    assert hit["pts"] == 1.5


def test_old_snapshot_without_mean_key_still_grades():
    """A snapshot locked before this change has no "mean" in its per-player
    proj — grading must not crash, just show 0 for that old record's
    expected value (it re-locks correctly the next time)."""
    snap = {
        "week": 1,
        "mix": 0.5,
        "mix_label": "50/50",
        "players": {
            "old player": {
                "player": "Old Player",
                "pos": "WR",
                "slot": "WR",
                "proj": {"p10": 0, "p25": 1, "p50": 3, "p75": 5, "p90": 8},  # no "mean"
            }
        },
        "lineup_p50": {"starters": [{"player": "Old Player", "pos": "WR", "slot": "WR"}], "bench": [], "why": []},
    }
    grades = grade_rows(snap, {"old player": {"pts": 4, "why": "ok"}})
    assert grades[0]["exp"] == 0
    assert grades[0]["actual"] == 4


def test_snapshot_from_payload_defaults_to_mean_objective():
    payload = {
        "week": 1,
        "lineups": {
            "p50": {"starters": [{"player": "P50 Pick", "pos": "WR"}], "bench": [], "why": []},
            "mean": {"starters": [{"player": "Mean Pick", "pos": "WR"}], "bench": [], "why": []},
        },
        "lineup_p50": {"starters": [{"player": "P50 Pick", "pos": "WR"}], "bench": [], "why": []},
        "roster": [],
        "fa_sample": [],
    }
    snap = snapshot_from_payload(payload)
    assert snap["objective"] == "mean"
    assert [p["player"] for p in snap["lineup_p50"]["starters"]] == ["Mean Pick"]


def test_grades_skip_fa_sample():
    snap = _snap_players(**{"Trevor Lawrence": {"pos": "QB", "slot": "QB", "p50": 7, "p25": 3, "p75": 9, "rec": True}})
    snap["players"][norm("Anders Carlson")] = {
        "player": "Anders Carlson",
        "pos": "K",
        "slot": "",
        "proj": {"p25": 2, "p50": 4, "p75": 6},
    }
    grades = grade_rows(
        snap,
        {
            "trevor lawrence": {"pts": 11, "why": "boom"},
            "anders carlson": {"pts": 0, "why": "empty"},
        },
    )
    names = {g["player"] for g in grades}
    assert names == {"Trevor Lawrence"}

