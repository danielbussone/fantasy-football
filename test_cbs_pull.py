import cbs_pull


class _FakeClient:
    def __init__(self, html: str = "", raise_error: Exception | None = None):
        self.html = html
        self.raise_error = raise_error

    def stats_report(self, pool, positions, period="2025", kind="stats", **kw):
        if self.raise_error:
            raise self.raise_error
        return self.html


def test_detect_current_week_from_client():
    html = '<span title="Questionable for Week 5 at Dallas">' * 3
    assert cbs_pull.detect_current_week(_FakeClient(html)) == 5


def test_detect_current_week_returns_none_on_network_failure():
    assert cbs_pull.detect_current_week(_FakeClient(raise_error=ConnectionError("down"))) is None


def test_detect_current_week_returns_none_when_no_tooltips():
    assert cbs_pull.detect_current_week(_FakeClient("<table></table>")) is None


def test_current_week_json_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cbs_pull, "CURRENT_WEEK_JSON", tmp_path / "current_week.json")
    assert cbs_pull.read_current_week() == {"week": None, "source": "", "as_of": ""}
    written = cbs_pull.write_current_week(4, "cbs-tp", when="2026-09-23T00:00:00Z")
    assert written == {"week": 4, "source": "cbs-tp", "as_of": "2026-09-23T00:00:00Z"}
    assert cbs_pull.read_current_week() == written


def test_cbs_pull_meta_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cbs_pull, "CBS_PULL_META", tmp_path / "cbs_pull_meta.json")
    assert cbs_pull.read_cbs_pull_meta() == {"week": None, "as_of": ""}
    written = cbs_pull.write_cbs_pull_meta(4, when="2026-09-23T00:00:00Z")
    assert written == {"week": 4, "as_of": "2026-09-23T00:00:00Z"}
    assert cbs_pull.read_cbs_pull_meta() == written


def test_standings_json_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cbs_pull, "STANDINGS_JSON", tmp_path / "standings.json")
    assert cbs_pull.read_standings() == {"as_of": "", "teams": []}
    rows = [{"rank": 1, "team": "BUSSONE", "offensive": 67.5, "defensive": 11.5, "total": 79.0}]
    written = cbs_pull.write_standings(rows, when="2026-09-23T00:00:00Z")
    assert written == {"as_of": "2026-09-23T00:00:00Z", "teams": rows}
    assert cbs_pull.read_standings() == written


def test_waiver_priority_is_reverse_standings_order():
    """Total-points league, no head-to-head: the leader claims last."""
    standings = {
        "teams": [
            {"rank": 1, "team": "BUSSONE", "total": 79.0},
            {"rank": 2, "team": "THROBBER", "total": 59.0},
            {"rank": 3, "team": "ANN", "total": 46.5},
        ]
    }
    priority = cbs_pull.waiver_priority_map(standings)
    assert priority == {"BUSSONE": 3, "THROBBER": 2, "ANN": 1}


def test_waiver_priority_empty_standings_is_empty_map():
    assert cbs_pull.waiver_priority_map({"teams": []}) == {}
