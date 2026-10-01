import backtest_pedigree as bp


def _r(pid, resid, week=5, **kw):
    base = {"player_id": pid, "resid": resid, "pred": 1.0, "y_ppg": 1.0 + resid, "week": week,
            "now_share": 0.1, "y_share": 0.2, "start_2h": False}
    base.update(kw)
    return base


def test_summarize_counts_week9_starters_and_share_growth():
    grp = [_r("a", 1.0, week=9, start_2h=True), _r("b", 0.0, week=9), _r("c", -1.0)]
    s = bp.summarize(grp)
    assert s["n"] == 3 and s["players"] == 3 and s["miss"] == 0.0
    assert (s["wk9"], s["wk9_starters"]) == (2, 1)
    assert abs(s["share_now"] - 0.1) < 1e-12 and abs(s["share_next"] - 0.2) < 1e-12


def test_summarize_empty():
    assert bp.summarize([]) == {"n": 0}


def test_prior_top_keeps_only_last_seasons_top_n(monkeypatch):
    monkeypatch.setattr(bp, "PRIOR_TOP", {"WR": 1, "RB": 1, "TE": 1})
    games = [{"player_id": p, "pos": "WR", "week": w, "gbfl": pts} for p, pts in (("good", 3.0), ("meh", 1.0)) for w in range(1, 8)]
    assert bp.prior_top(games) == {"good"}
