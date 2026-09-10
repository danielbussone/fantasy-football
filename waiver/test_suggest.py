from waiver.suggest import CAPS, suggest


def _p(name, pos, p50, owner="BUSSONE", board_rank=None, **kw):
    rec = {
        "player": name,
        "pos": pos,
        "owner": owner,
        "proj": {"p10": max(0, p50 - 1), "p50": p50, "p90": p50 + 3},
        "depth_rank": 1,
    }
    rec.update(kw)
    return rec, board_rank


def _board(pairs):
    out = {}
    for name, rank, score in pairs:
        out[name.lower()] = {"player": name, "rank": str(rank), "score": str(score)}
    return out


def _full_bussone():
    """2 QB / 5 RB / 6 WR / 2 TE / 2 K / 2 DST — at WR cap."""
    names = [
        ("Q1", "QB", 5),
        ("Q2", "QB", 4),
        ("R1", "RB", 6),
        ("R2", "RB", 5),
        ("R3", "RB", 4),
        ("R4", "RB", 3),
        ("R5", "RB", 2),
        ("W1", "WR", 7),
        ("W2", "WR", 6),
        ("W3", "WR", 5),
        ("W4", "WR", 4),
        ("W5", "WR", 3),
        ("W6", "WR", 1.2),
        ("T1", "TE", 4),
        ("T2", "TE", 3),
        ("K1", "K", 3),
        ("K2", "K", 2),
        ("D1", "DST", 2),
        ("D2", "DST", 1),
    ]
    return [_p(n, p, s)[0] for n, p, s in names]


def test_cannot_add_seventh_wr_without_wr_drop():
    roster = _full_bussone()
    fa = [_p("FA-WR", "WR", 9, owner="")[0], _p("FA-RB", "RB", 8, owner="")[0]]
    out = suggest(roster, fa, board_weight=0.0, board={}, rankings_as_of="2026-09-09")
    wr_adds = [r for r in out["recommendations"] if r["add"]["pos"] == "WR"]
    assert wr_adds
    for r in wr_adds:
        assert r["drop"]["pos"] == "WR"
        assert "7th WR" in r["reason"] or "must drop a WR" in r["reason"]
    assert all(p["rankings_as_of"] == "2026-09-09" for p in out["fa_top"])
    assert out["caps"]["WR"] == 6 == CAPS["WR"]


def test_weekly_weight_zero_present_is_p50():
    roster = _full_bussone()
    fa = [_p("FA-RB", "RB", 4.5, owner="", weekly_rank=12, weekly_value=6, weekly_list="FLX")[0]]
    out = suggest(roster, fa, board_weight=0.0, board={}, weekly_weight=0.0)
    row = next(x for x in out["fa_top"] if x["player"] == "FA-RB")
    assert row["present"] == 4.5
    assert row["weekly_rank"] == 12
    assert out["weekly_weight"] == 0.0


def test_board_weight_moves_present_blend():
    roster = _full_bussone()
    fa = [_p("Prospect", "RB", 1.0, owner="")[0]]
    board = _board([("Prospect", 12, 20)])
    low = suggest(roster, fa, board_weight=0.0, board=board)
    high = suggest(roster, fa, board_weight=1.0, board=board)
    a0 = next(x for x in low["fa_top"] if x["player"] == "Prospect")
    a1 = next(x for x in high["fa_top"] if x["player"] == "Prospect")
    assert a1["blended"] > a0["blended"]


def test_drop_keeps_legal_lineup():
    roster = _full_bussone()
    fa = [_p("Stream-K", "K", 10, owner="")[0]]
    out = suggest(roster, fa, board_weight=0.0, board={})
    counts = {"QB": 2, "RB": 5, "WR": 6, "TE": 2, "K": 2, "DST": 2}
    for r in out["recommendations"]:
        counts[r["drop"]["pos"]] -= 1
        counts[r["add"]["pos"]] += 1
        rb, wr, te = counts["RB"], counts["WR"], counts["TE"]
        assert counts["QB"] >= 1 and counts["K"] >= 1 and counts["DST"] >= 1
        assert rb >= 1 and wr >= 1 and te >= 1
        from lineup.start_sit import can_fill_active

        assert can_fill_active(counts)
