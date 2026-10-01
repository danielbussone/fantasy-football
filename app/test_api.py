from fastapi.testclient import TestClient

from app.main import app

FAKE = {
    "mock": False,
    "week": 1,
    "team": "BUSSONE",
    "rankings_as_of": "2026-09-09",
    "injury_as_of": "",
    "format_note": "46-yard receiving TD is 4.",
    "roster": [{"player": "Ja'Marr Chase", "pos": "WR", "proj": {"p10": 1, "p50": 3, "p90": 8}}],
    "lineup_p50": {"starters": [], "bench": [], "total": 0, "why": []},
    "lineup_p10": {"starters": [], "bench": [], "total": 0, "why": []},
    "lineups": {
        "p10": {"starters": [], "bench": [], "total": 0, "why": []},
        "p50": {"starters": [], "bench": [], "total": 0, "why": []},
    },
    "waivers": {"recommendations": [], "fa_top": [], "caps": {}, "rankings_as_of": "2026-09-09"},
    "fa_sample": [],
}


def test_week_and_split_routes(monkeypatch):
    monkeypatch.setattr("app.main.build_week", lambda **k: {**FAKE, "week": k.get("week", 1)})
    monkeypatch.setattr("app.main.rescore_waivers", lambda **k: FAKE["waivers"])
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"] is True
    w = c.get("/api/week?week=2").json()
    assert w["week"] == 2
    assert c.get("/api/roster").json()["roster"]
    assert "lineup" in c.get("/api/lineup").json()
    assert "waivers" in c.get("/api/waivers").json()
    assert "projections" in c.get("/api/projections?week=1").json()
    assert c.get("/roster").status_code == 200
    assert c.get("/lineup").status_code == 200
    assert c.get("/waivers").status_code == 200
    assert c.get("/projections?week=1").status_code == 200


def test_week_forwards_espn_mix(monkeypatch):
    seen = {}

    def fake(**k):
        seen.update(k)
        return {**FAKE, "espn_mix": k.get("espn_mix")}

    monkeypatch.setattr("app.main.build_week", fake)
    c = TestClient(app)
    c.get("/api/week?espn_mix=0")
    assert seen["espn_mix"] == 0


def test_report_and_lock_routes(monkeypatch, tmp_path):
    fake_week = {
        "week": 1,
        "team": "BUSSONE",
        "espn_mix": 0.5,
        "espn_mix_label": "50/50",
        "roster": [{"player": "Ja'Marr Chase", "pos": "WR", "slot": "WR", "proj": {"p10": 1, "p25": 2, "p50": 3, "p75": 5, "p90": 8, "usage": {}}}],
        "fa_sample": [],
        "lineup_p50": {"starters": [{"player": "Ja'Marr Chase", "pos": "WR"}], "bench": [], "why": []},
        "lineups": {},
        "waivers": {"recommendations": [], "roster_scored": [], "fa_top": []},
        "data_flags": {},
    }
    monkeypatch.setattr("app.main.week_for_report", lambda week=1, **k: fake_week)
    monkeypatch.setattr("app.assemble.week_for_report", lambda week=1, **k: fake_week)
    monkeypatch.setattr("app.main.build_week", lambda **k: fake_week)
    from report import snapshot as snapmod

    monkeypatch.setattr(snapmod, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(snapmod, "snapshot_path", lambda week: tmp_path / f"week{week}_pre.json")
    monkeypatch.setattr("report.week_card.load_week_actuals", lambda week: {})
    c = TestClient(app)
    locked = c.post("/api/lock?week=1").json()
    assert locked["ok"] is True
    assert locked["n"] >= 1
    assert (tmp_path / "week1_pre.json").exists()
    body = c.get("/api/report?week=1").json()
    assert body["status"] == "no_actuals"
    assert body["locked_lineup"]


def test_current_week_route(monkeypatch):
    monkeypatch.setattr("app.main.read_current_week", lambda: {"week": 3, "source": "cbs-tp", "as_of": "2026-09-23T00:00:00Z"})
    c = TestClient(app)
    body = c.get("/api/current-week").json()
    assert body == {"week": 3, "source": "cbs-tp", "as_of": "2026-09-23T00:00:00Z"}


def test_refresh_forwards_requested_week(monkeypatch):
    """Regression: /api/refresh used to always call build_week() with no
    args (week 1) no matter what ?week= was, and to pull the CBS week via a
    global sys.argv swap instead of passing args to cbs_pull.main directly.
    """
    seen_pull_argv = {}
    seen_build_week = {}

    def fake_pull_main(argv=None):
        seen_pull_argv["argv"] = argv
        return 0

    def fake_build_week(**k):
        seen_build_week.update(k)
        return {**FAKE, "week": k.get("week", 1)}

    nflverse_calls = []
    monkeypatch.setattr("cbs_pull.main", fake_pull_main)
    monkeypatch.setattr("nflverse.pull.refresh", lambda *a, **k: nflverse_calls.append(1) or {"ok": True})
    monkeypatch.setattr("app.main.build_week", fake_build_week)
    c = TestClient(app)
    body = c.post("/api/refresh?week=2").json()
    assert body["ok"] is True
    assert body["week"]["week"] == 2
    assert seen_build_week.get("week") == 2
    assert seen_pull_argv["argv"] == ["--week", "2"]
    assert nflverse_calls == [1]  # Refresh also pulls nflverse so grades don't lag the CBS data


def test_weekly_upload_filename_cannot_escape_import_tmp(tmp_path, monkeypatch):
    """A crafted filename like "../../x.csv" must not write outside
    .import_tmp: Path(filename).name strips any directory components."""
    import io

    monkeypatch.setattr("app.main.ROOT", tmp_path)
    monkeypatch.setattr("app.main.import_weekly", lambda paths, fallback_week=1: {"week": fallback_week, "lists": []})
    c = TestClient(app)
    evil_name = "../../evil.csv"
    r = c.post(
        "/api/rankings/import?week=1",
        files={"weekly": (evil_name, io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
    )
    assert r.status_code == 200
    written = list((tmp_path / ".import_tmp").iterdir())
    assert all(".." not in p.name for p in written)
    assert (tmp_path / ".import_tmp" / "evil.csv").exists()
    assert not (tmp_path.parent / "evil.csv").exists()


def test_waivers_route_uses_rescore_not_build_week(monkeypatch):
    seen = {}

    def fake_rescore(**k):
        seen.update(k)
        return {**FAKE["waivers"], "board_weight": k.get("board_weight")}

    monkeypatch.setattr("app.main.rescore_waivers", fake_rescore)
    monkeypatch.setattr(
        "app.main.build_week",
        lambda **k: (_ for _ in ()).throw(AssertionError("build_week should not run")),
    )
    c = TestClient(app)
    body = c.get("/api/waivers?board_weight=0.8&espn_mix=1").json()
    assert body["waivers"]["board_weight"] == 0.8
    assert seen["board_weight"] == 0.8
    assert seen["espn_mix"] == 1

