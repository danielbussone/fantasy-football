import report.snapshot as snapshot
import report.tracking as tracking
from report.snapshot import metrics_block


def _payload(**kw):
    base = {
        "roster": [{"player": "Mine WR", "pos": "WR", "grade": {"par_ppg": 1.0, "par": 3.0, "role": 60, "flags": [], "exp_games": 11}},
                   {"player": "Seahawks", "pos": "DST", "team": "SEA", "stream": {"opp": "LAC", "opp_total": 17.0, "score": 3.0}}],
        "waivers": {"fa_top": [{"player": "Backup RB", "pos": "RB", "grade": {"par_ppg": 0.5, "par": 4.0, "role": 40, "flags": ["next_up"], "exp_games": 11}},
                               {"player": "Soft DST", "pos": "DST", "team": "NYG", "stream": {"opp": "CLE", "opp_total": 15.0, "score": 5.0}},
                               {"player": "Hard DST", "pos": "DST", "team": "KC", "stream": {"opp": "BUF", "opp_total": 28.0, "score": -8.0}}]},
        "grades": {"available": True, "decision_week": 3, "next_up": [
            {"player": "Backup RB", "pos": "RB", "par": 4.0, "pred_ppg": 0.5, "role": 40, "flags": ["next_up"], "exp_games": 11}], "buy_low": [
            {"player": "Young WR", "pos": "WR", "par": 2.0, "pred_ppg": 0.8, "role": 50, "flags": ["buy_low"], "exp_games": 11}]},
    }
    base.update(kw)
    return base


def test_metrics_block_records_predictions_flags_and_dst():
    m = metrics_block(_payload())
    assert m["grades"]["backup rb"]["flags"] == ["next_up"] and m["grades"]["young wr"]["par_ppg"] == 0.8
    assert m["next_up"] == ["Backup RB"] and m["buy_low"] == ["Young WR"]
    assert {d["player"]: d["mine"] for d in m["dst"]} == {"Seahawks": True, "Soft DST": False, "Hard DST": False}


def test_metrics_block_is_none_without_grades():
    assert metrics_block(_payload(grades={"available": False})) is None


def test_tracking_scores_flags_par_error_and_the_dst_stream_pick(monkeypatch):
    snap = {"week": 4, "metrics": metrics_block(_payload())}
    monkeypatch.setattr(tracking, "load_snapshot", lambda w: snap if w == 4 else None)
    actuals = {"backup rb": {"pts": 3.0}, "mine wr": {"pts": 0.0}, "young wr": {"pts": 1.0},
               "soft dst": {"pts": 6.0}, "hard dst": {"pts": 1.0}, "seahawks": {"pts": 4.0}}
    monkeypatch.setattr(tracking, "load_week_actuals", lambda w: actuals)
    t = tracking.tracking(5)
    assert t["weeks"] == [4]
    assert t["next_up"]["n"] == 1 and t["next_up"]["beat"] == 2.5  # 3.0 actual vs 0.5 predicted
    assert abs(t["buy_low"]["beat"] - 0.2) < 1e-9 and t["buy_low"]["hit_rate"] == 1.0
    assert abs(t["par"]["WR"]["mean_err"] - (-0.4)) < 1e-9 and t["par"]["WR"]["n"] == 2  # (0 − 1.0) and (1.0 − 0.8), averaged
    assert t["dst"]["rows"][0]["pick"] == "Soft DST" and t["dst"]["pick_pts"] == 6.0 and t["dst"]["avg_free_pts"] == 3.5


def test_tracking_skips_weeks_without_box_scores(monkeypatch):
    monkeypatch.setattr(tracking, "load_snapshot", lambda w: {"week": w, "metrics": metrics_block(_payload())})
    monkeypatch.setattr(tracking, "load_week_actuals", lambda w: {})
    assert tracking.tracking(6)["weeks"] == []
