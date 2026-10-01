from datetime import datetime, timedelta, timezone

from app.assemble import _age_hours, _freshness, build_freshness, build_week, clear_proj_cache, rescore_waivers, store_week_projections
from waiver.test_suggest import _board, _full_bussone, _p


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_age_hours():
    assert _age_hours("") is None
    assert _age_hours("not a date") is None
    assert abs(_age_hours(_iso(timedelta(hours=5))) - 5) < 0.05


def test_freshness_statuses():
    fresh = _freshness("X", _iso(timedelta(hours=1)), fresh_hours=24)
    assert fresh["status"] == "fresh"
    assert fresh["hint"] == ""

    stale = _freshness("X", _iso(timedelta(hours=48)), fresh_hours=24, hint="do the thing")
    assert stale["status"] == "stale"
    assert stale["hint"] == "do the thing"

    missing_no_data = _freshness("X", "", fresh_hours=24, hint="do the thing")
    assert missing_no_data["status"] == "missing"

    missing_wrong_week = _freshness("X", _iso(timedelta(minutes=1)), fresh_hours=24, week_match=False, hint="do the thing")
    assert missing_wrong_week["status"] == "missing"


def test_build_freshness_shape(monkeypatch):
    import cbs_pull

    monkeypatch.setattr(cbs_pull, "read_cbs_pull_meta", lambda: {"week": 2, "as_of": _iso(timedelta(hours=1))})
    monkeypatch.setattr(cbs_pull, "read_current_week", lambda: {"week": 2, "source": "cbs-tp", "as_of": _iso(timedelta(hours=1))})
    import app.assemble as assemble_mod

    monkeypatch.setattr(assemble_mod, "read_cbs_pull_meta", cbs_pull.read_cbs_pull_meta)
    monkeypatch.setattr(assemble_mod, "read_current_week", cbs_pull.read_current_week)

    out = build_freshness(
        week=2,
        injuries={"as_of": _iso(timedelta(hours=1))},
        espn_meta={"week": 2, "as_of": _iso(timedelta(hours=1)), "by_week": {"2": {"as_of": _iso(timedelta(hours=1))}}},
        fp_meta={"week": 1, "as_of": _iso(timedelta(days=3))},
        espn_week_match=True,
        fp_week_match=False,
        vegas_data={"as_of": _iso(timedelta(hours=1))},
        nflverse_meta={"as_of": _iso(timedelta(hours=1)), "latest_week": 1},
    )
    assert set(out) == {"cbs", "injuries", "espn", "weekly_fp", "current_week", "vegas", "nflverse"}
    assert out["cbs"]["status"] == "fresh"
    assert out["espn"]["status"] == "fresh"
    assert out["weekly_fp"]["status"] == "missing"  # wrong week on file
    assert out["current_week"]["week"] == 2
    assert out["vegas"]["status"] == "fresh"


def test_build_freshness_vegas_missing_when_never_pulled():
    out = build_freshness(
        week=3,
        injuries={},
        espn_meta={},
        fp_meta={},
        espn_week_match=False,
        fp_week_match=False,
        vegas_data=None,
    )
    assert out["vegas"]["status"] == "missing"


def test_build_week_projection_is_deterministic():
    """Same week, same inputs, must give the same projection every time.

    Guards against reintroducing an index-based Monte Carlo seed: it used to
    be each player's position in the roster/FA list, so adding or dropping
    one player reshuffled every other player's draws even though nothing
    about them changed.
    """
    clear_proj_cache()
    a = build_week(week=1, mock=True)
    clear_proj_cache()
    b = build_week(week=1, mock=True)
    a_by_name = {p["player"]: p["proj"] for p in a["roster"]}
    b_by_name = {p["player"]: p["proj"] for p in b["roster"]}
    assert a_by_name == b_by_name
    assert a_by_name


def test_rescore_waivers_uses_cache_not_build_week(monkeypatch):
    clear_proj_cache()
    mine = _full_bussone()
    fa = [_p("Prospect", "RB", 1.0, owner="")[0]]
    board = _board([("Prospect", 12, 20)])
    store_week_projections(1, False, 0.5, mine, fa, board, {}, "2026-09-09")
    monkeypatch.setattr(
        "app.assemble.build_week",
        lambda **k: (_ for _ in ()).throw(AssertionError("build_week should not run")),
    )
    low = rescore_waivers(week=1, board_weight=0.0, mock=False, espn_mix=0.5)
    high = rescore_waivers(week=1, board_weight=1.0, mock=False, espn_mix=0.5)
    a0 = next(x for x in low["fa_top"] if x["player"] == "Prospect")
    a1 = next(x for x in high["fa_top"] if x["player"] == "Prospect")
    assert a1["blended"] > a0["blended"]
    assert low["board_weight"] == 0.0
    assert high["board_weight"] == 1.0


def test_nflverse_freshness_needs_the_last_completed_week():
    kw = dict(week=4, injuries={}, espn_meta={}, fp_meta={}, espn_week_match=False, fp_week_match=False)
    fresh = build_freshness(**kw, nflverse_meta={"as_of": _iso(timedelta(hours=2)), "latest_week": 3})
    assert fresh["nflverse"]["status"] == "fresh" and fresh["nflverse"]["latest_week"] == 3
    behind = build_freshness(**kw, nflverse_meta={"as_of": _iso(timedelta(hours=2)), "latest_week": 2})
    assert behind["nflverse"]["status"] == "missing" and "through week 2" in behind["nflverse"]["hint"]
    stale = build_freshness(**kw, nflverse_meta={"as_of": _iso(timedelta(days=3)), "latest_week": 3})
    assert stale["nflverse"]["status"] == "stale"
    never = build_freshness(**kw, nflverse_meta={})
    assert never["nflverse"]["status"] == "missing"


def test_attach_metrics_without_nflverse_still_streams_dst_and_kickers():
    from app.assemble import attach_metrics, grades_payload

    recs = [{"player": "WR One", "pos": "WR", "team": "BAL"}, {"player": "Ravens", "pos": "DST", "team": "BAL"},
            {"player": "Some Kicker", "pos": "K", "team": "BAL"}]
    vegas = {"teams": {"BAL": {"total": 24.0, "opp": "TEN"}, "TEN": {"total": 17.0, "opp": "BAL"}}}
    streams = attach_metrics(recs, {"available": False, "reason": "nflverse data not cached"}, vegas)
    assert recs[0]["grade"] is None  # no grade without nflverse, never a made-up one
    assert recs[1]["stream"]["opp"] == "TEN" and recs[1]["stream"]["opp_total"] == 17.0
    assert recs[2]["kick"]["implied"] == 24.0
    g = grades_payload({"available": False, "reason": "nflverse data not cached"}, 4, [], [], recs, [], streams)
    assert g["available"] is False and g["reason"] == "nflverse data not cached"
    assert g["buy_low"] == [] and g["next_up"] == [] and g["wr_watch"]["players"] == []
    assert [d["player"] for d in g["dst"]["mine"]] == ["Ravens"]


def test_a_backup_qb_gets_no_grade_even_if_he_filled_in_recently(monkeypatch):
    from app import assemble

    graded = {"role": 50}
    monkeypatch.setattr(assemble.live_metrics, "grade_for", lambda data, rec: graded)
    recs = [{"player": "Fill In", "pos": "QB", "team": "SEA", "depth_rank": 2},
            {"player": "Starter", "pos": "QB", "team": "SEA", "depth_rank": 1},
            {"player": "No Depth Info", "pos": "QB", "team": "SEA"}]
    assemble.attach_metrics(recs, {"available": True}, None)
    assert [r["grade"] for r in recs] == [None, graded, graded]
