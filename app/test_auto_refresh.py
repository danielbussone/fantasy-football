import projections.vegas as vegas_mod
from app.auto_refresh import run_auto_refresh_once


def _no_network_vegas(monkeypatch, week: int = 1, n: int = 5):
    """Vegas has no cookie gate — every test must stub it or it'd hit the
    real network. Returns the fake's call record."""
    calls = {"week": None}

    def fake_refresh_vegas(w, season=vegas_mod.SEASON):
        calls["week"] = w
        return {"week": w, "as_of": "2026-09-23T00:00:00Z", "league_avg": 22.0, "teams": {f"T{i}": {} for i in range(n)}}

    monkeypatch.setattr(vegas_mod, "refresh_vegas", fake_refresh_vegas)
    return calls


def test_no_cookies_is_a_clean_noop(tmp_path, monkeypatch):
    """No cbs_cookies.txt / espn_cookies.txt: both legs report why, and the
    pass returns cleanly — no exception, no crash."""
    import app.auto_refresh as ar

    monkeypatch.setattr(ar, "ROOT", tmp_path)
    _no_network_vegas(monkeypatch)
    out = run_auto_refresh_once()
    assert out["cbs"] == {"ok": False, "error": "no cbs_cookies.txt"}
    assert out["espn"] == {"ok": False, "error": "no espn_cookies.txt"}
    assert out["vegas"]["ok"] is True


def test_successful_pass_refreshes_both_and_clears_cache(tmp_path, monkeypatch):
    import app.assemble as assemble_mod
    import app.auto_refresh as ar
    import cbs_pull
    import projections.espn as espn_mod

    monkeypatch.setattr(ar, "ROOT", tmp_path)
    (tmp_path / "cbs_cookies.txt").write_text("x", encoding="utf-8")
    (tmp_path / "espn_cookies.txt").write_text("x", encoding="utf-8")

    calls = {"cbs_argv": None, "espn_week": None, "cache_cleared": False}

    def fake_pull_main(argv=None):
        calls["cbs_argv"] = argv
        return 0

    def fake_read_current_week():
        return {"week": 5, "source": "cbs-tp", "as_of": "2026-09-23T00:00:00Z"}

    def fake_refresh_espn(week, limit=1000):
        calls["espn_week"] = week
        return {"ok": True, "week": week, "n": 10}

    def fake_clear_cache():
        calls["cache_cleared"] = True

    monkeypatch.setattr(cbs_pull, "main", fake_pull_main)
    monkeypatch.setattr(cbs_pull, "read_current_week", fake_read_current_week)
    monkeypatch.setattr(espn_mod, "refresh_espn_from_saved_cookies", fake_refresh_espn)
    monkeypatch.setattr(assemble_mod, "clear_proj_cache", fake_clear_cache)
    vegas_calls = _no_network_vegas(monkeypatch)

    out = run_auto_refresh_once()

    assert out["cbs"] == {"ok": True}
    assert calls["cbs_argv"] == []  # no --week: cbs_pull auto-detects it
    assert out["espn"] == {"ok": True, "week": 5, "n": 10}
    assert calls["espn_week"] == 5
    assert calls["cache_cleared"] is True
    assert out["vegas"]["ok"] is True
    assert vegas_calls["week"] == 5  # same week read_current_week reported


def test_cbs_pull_exception_does_not_propagate(tmp_path, monkeypatch):
    import app.auto_refresh as ar
    import cbs_pull

    monkeypatch.setattr(ar, "ROOT", tmp_path)
    (tmp_path / "cbs_cookies.txt").write_text("x", encoding="utf-8")

    def boom(argv=None):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(cbs_pull, "main", boom)
    _no_network_vegas(monkeypatch)
    out = run_auto_refresh_once()
    assert out["cbs"]["ok"] is False
    assert "network exploded" in out["cbs"]["error"]


def test_espn_failure_does_not_touch_cbs_result(tmp_path, monkeypatch):
    import app.auto_refresh as ar
    import cbs_pull
    import projections.espn as espn_mod

    monkeypatch.setattr(ar, "ROOT", tmp_path)
    (tmp_path / "espn_cookies.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(cbs_pull, "read_current_week", lambda: {"week": 2})
    monkeypatch.setattr(
        espn_mod,
        "refresh_espn_from_saved_cookies",
        lambda week, limit=1000: {"ok": False, "week": week, "error": "ESPN returned 0 players — cookie may be expired"},
    )
    _no_network_vegas(monkeypatch)
    out = run_auto_refresh_once()
    assert out["cbs"] == {"ok": False, "error": "no cbs_cookies.txt"}
    assert out["espn"]["ok"] is False
    assert "expired" in out["espn"]["error"]


def test_vegas_exception_does_not_propagate_or_touch_other_legs(tmp_path, monkeypatch):
    import app.auto_refresh as ar

    monkeypatch.setattr(ar, "ROOT", tmp_path)

    def boom(week, season=vegas_mod.SEASON):
        raise RuntimeError("odds api down")

    monkeypatch.setattr(vegas_mod, "refresh_vegas", boom)
    out = run_auto_refresh_once()
    assert out["vegas"]["ok"] is False
    assert "odds api down" in out["vegas"]["error"]
    assert out["cbs"] == {"ok": False, "error": "no cbs_cookies.txt"}
    assert out["espn"] == {"ok": False, "error": "no espn_cookies.txt"}
