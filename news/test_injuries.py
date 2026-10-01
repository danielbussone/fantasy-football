from news.injuries import designation_from_text, fetch_espn_injury_report, from_cbs_slots, from_depth_tooltip, match_notes, official_status


def test_cbs_injured_slot_is_out():
    notes = from_cbs_slots(
        [
            {"player": "Malik Nabers", "slot": "Injured"},
            {"player": "Ja'Marr Chase", "slot": "WR"},
        ]
    )
    assert notes["malik nabers"]["out"] is True
    assert notes["malik nabers"]["source"] == "CBS"
    assert "chase" not in notes


def test_espn_match_sets_designation():
    notes = match_notes(
        ["Kenneth Walker III"],
        [{"headline": "Walker ruled Out for Sunday", "description": "", "published": "", "source": "ESPN"}],
    )
    assert notes["kenneth walker"]["designation"] == "Out"
    assert notes["kenneth walker"]["out"] is True


def test_designation_out_not_without():
    assert designation_from_text("Ankle: Out for Week 1 at Seattle") == "Out"
    assert designation_from_text("ruled Out for Sunday") == "Out"
    assert designation_from_text("practice without limitation") is None
    assert designation_from_text("embraced the new offense") is None


def test_official_status_ignores_blurbs():
    assert official_status("Out") == "Out"
    assert official_status("Questionable") == "Questionable"
    assert official_status("Active") is None
    assert official_status("") is None


def test_espn_report_skips_rows_without_status(monkeypatch):
    import news.injuries as inj

    monkeypatch.setattr(
        inj,
        "_get",
        lambda url, timeout=20: (
            '{"injuries":[{"injuries":['
            '{"status":"Out","athlete":{"displayName":"TreVeyon Henderson"},'
            '"shortComment":"Ruled out","details":{}},'
            '{"athlete":{"displayName":"Ja\'Marr Chase"},'
            '"shortComment":"Embraced the new offense","details":{}}'
            "]}]}"
        ),
    )
    notes = fetch_espn_injury_report()
    assert "treveyon henderson" in notes
    assert notes["treveyon henderson"]["designation"] == "Out"
    assert "ja'marr chase" not in notes
    from news.injuries import fetch_espn_player_items

    injuries, blurbs = fetch_espn_player_items()
    assert "ja'marr chase" in blurbs
    assert blurbs["ja'marr chase"]["text"]
    assert "designation" not in blurbs["ja'marr chase"]


def test_depth_tooltip_out():
    n = from_depth_tooltip("Ankle: Out for Week 1 at Seattle. Expected Return - Week 2", "TreVeyon Henderson")
    assert n and n["out"] is True and n["designation"] == "Out"


def test_refresh_does_not_wipe_existing(monkeypatch, tmp_path):
    import news.injuries as inj

    monkeypatch.setattr(inj, "OUT", tmp_path / "injury_notes.json")
    inj.OUT.write_text(
        '{"as_of":"x","notes":{"treveyon henderson":{"player":"TreVeyon Henderson","designation":"Out","out":true}}}',
        encoding="utf-8",
    )
    # refresh() calls the combined fetch_espn_player_items(), not the two
    # split helpers below it — mock that one.
    monkeypatch.setattr(inj, "fetch_espn_player_items", lambda: ({}, {}))
    out = inj.refresh([{"player": "Ja'Marr Chase", "slot": "WR"}])
    assert out["notes"]["treveyon henderson"]["designation"] == "Out"


def test_assemble_merges_cbs_slot_without_news_file():
    from app.assemble import _injury_for

    rec = {"player": "Foo", "slot": "Injured"}
    note = _injury_for(rec, {"notes": {}}, mock=False)
    assert note and note["source"] == "CBS"
    assert _injury_for({"player": "Ja'Marr Chase", "slot": "WR"}, {"notes": {}}, mock=False) is None
    mock_n = _injury_for({"player": "Malik Nabers", "slot": "WR"}, {"notes": {}}, mock=True)
    assert mock_n and mock_n["designation"] == "Questionable"
