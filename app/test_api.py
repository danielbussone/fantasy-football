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
