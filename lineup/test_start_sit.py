from lineup.start_sit import (
    DEFAULT_OBJECTIVE,
    _metric,
    apply_injury_proj,
    can_fill_active,
    optimize,
    rank_tuple,
    skill_counts_legal,
    sort_bench,
    tiebreak_keys,
)


def _p(name, pos, p50, p10=None, p90=None, **kw):
    p10 = p50 - 1 if p10 is None else p10
    p25 = p50 - 0.5
    p75 = p50 + 1
    p90 = p50 + 4 if p90 is None else p90
    rec = {
        "player": name,
        "pos": pos,
        "proj": {"p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90, "mean": p50},
    }
    rec.update(kw)
    return rec


def _roster(**extra):
    rows = [
        _p("QB-A", "QB", 5),
        _p("QB-B", "QB", 3),
        _p("RB-A", "RB", 6),
        _p("RB-B", "RB", 5),
        _p("RB-C", "RB", 4),
        _p("RB-D", "RB", 3.2),
        _p("WR-A", "WR", 7),
        _p("WR-B", "WR", 6),
        _p("WR-C", "WR", 5),
        _p("WR-D", "WR", 4.1),
        _p("TE-A", "TE", 4.4),
        _p("TE-B", "TE", 4.0),
        _p("K-A", "K", 3),
        _p("DST-A", "DST", 2),
    ]
    by = {p["player"]: p for p in rows}
    by.update(extra)
    return list(by.values())


def _pos_counts(starters):
    c = {"RB": 0, "WR": 0, "TE": 0, "QB": 0, "K": 0, "DST": 0}
    for p in starters:
        c[(p.get("pos") or "").upper()] = c.get((p.get("pos") or "").upper(), 0) + 1
    return c


def test_legal_lineup_slots():
    out = optimize(_roster(), "p50")
    slots = [p["lineup_slot"] for p in out["starters"]]
    assert slots.count("QB") == 1
    assert slots.count("RB") == 1
    assert slots.count("WR") == 1
    assert slots.count("TE") == 1
    assert slots.count("FLEX") == 4
    assert slots.count("K") == 1
    assert slots.count("DST") == 1
    assert len(out["starters"]) == 10
    counts = _pos_counts(out["starters"])
    assert skill_counts_legal(counts["RB"], counts["WR"], counts["TE"])


def test_cannot_start_five_rbs():
    roster = [
        _p("QB-A", "QB", 5),
        _p("RB-A", "RB", 20),
        _p("RB-B", "RB", 19),
        _p("RB-C", "RB", 18),
        _p("RB-D", "RB", 17),
        _p("RB-E", "RB", 16),
        _p("WR-A", "WR", 2),
        _p("WR-B", "WR", 1.5),
        _p("TE-A", "TE", 1),
        _p("TE-B", "TE", 0.5),
        _p("K-A", "K", 3),
        _p("DST-A", "DST", 2),
    ]
    out = optimize(roster, "p50")
    counts = _pos_counts(out["starters"])
    assert counts["RB"] <= 4
    assert counts["RB"] + counts["WR"] + counts["TE"] == 7
    names = {p["player"] for p in out["starters"]}
    assert "RB-E" not in names


def test_four_rb_two_wr_one_te_legal():
    assert skill_counts_legal(4, 2, 1)
    roster = [
        _p("QB-A", "QB", 5),
        _p("RB-A", "RB", 10),
        _p("RB-B", "RB", 9),
        _p("RB-C", "RB", 8),
        _p("RB-D", "RB", 7),
        _p("WR-A", "WR", 3),
        _p("WR-B", "WR", 2),
        _p("TE-A", "TE", 4),
        _p("K-A", "K", 3),
        _p("DST-A", "DST", 2),
    ]
    out = optimize(roster, "p50")
    counts = _pos_counts(out["starters"])
    assert counts["RB"] == 4
    assert counts["WR"] == 2
    assert counts["TE"] == 1


def test_three_te_illegal():
    assert not skill_counts_legal(2, 2, 3)
    roster = [
        _p("QB-A", "QB", 5),
        _p("RB-A", "RB", 3),
        _p("RB-B", "RB", 2),
        _p("WR-A", "WR", 3),
        _p("WR-B", "WR", 2),
        _p("WR-C", "WR", 1.2),
        _p("WR-D", "WR", 1.1),
        _p("TE-A", "TE", 20),
        _p("TE-B", "TE", 19),
        _p("TE-C", "TE", 18),
        _p("K-A", "K", 3),
        _p("DST-A", "DST", 2),
    ]
    out = optimize(roster, "p50")
    counts = _pos_counts(out["starters"])
    assert counts["TE"] <= 2
    names = {p["player"] for p in out["starters"]}
    assert "TE-C" not in names


def test_injured_cannot_start_unless_override():
    hurt = _p(
        "QB-HOT",
        "QB",
        20,
        slot="Injured",
        injury={"designation": "Out", "out": True, "note": "IR", "source": "CBS"},
    )
    roster = _roster(**{"QB-A": hurt})
    blocked = optimize(roster, "p50", allow_injured=False)
    qb = next(p for p in blocked["starters"] if p["lineup_slot"] == "QB")
    assert qb["player"] == "QB-B"
    allowed = optimize(roster, "p50", allow_injured=True)
    qb2 = next(p for p in allowed["starters"] if p["lineup_slot"] == "QB")
    # Override only unlocks the slot; OUT still scores 0/0/0/0/0 so healthy QB-B starts.
    assert qb2["player"] == "QB-B"
    hot = next(p for p in allowed["starters"] + allowed["bench"] if p["player"] == "QB-HOT")
    assert hot["proj"]["p10"] == hot["proj"]["p50"] == hot["proj"]["p90"] == 0


def test_percentile_objectives_change_set():
    boom = _p("WR-BOOM", "WR", 8, p10=0.5, p90=20)
    floor = _p("WR-FLOOR", "WR", 6.5, p10=5, p90=8)
    roster = _roster(**{"WR-A": boom, "WR-B": floor})
    p50 = {p["player"] for p in optimize(roster, "p50")["starters"]}
    p10 = {p["player"] for p in optimize(roster, "p10")["starters"]}
    p90 = {p["player"] for p in optimize(roster, "p90")["starters"]}
    assert "WR-BOOM" in p50
    assert "WR-FLOOR" in p10
    assert "WR-BOOM" in p90
    assert optimize(roster, "p25")["objective_label"] == "safe bets"


def test_close_call_note_present():
    out = optimize(_roster(), "p50")
    close = [w for w in out["why"] if w.get("kind") == "close" or " vs " in w["player"]]
    assert close


def test_qb_close_call_always_shown_even_when_not_close():
    """Only one active QB slot, roster caps at 2 QBs: which one starts is a
    real weekly decision regardless of how far apart their projections are —
    unlike the flex/TE close calls, this must show up every week."""
    roster = _roster(**{"QB-A": _p("QB-A", "QB", 20), "QB-B": _p("QB-B", "QB", 2)})
    out = optimize(roster, "mean")
    qb_calls = [w for w in out["why"] if w.get("kind") == "close" and "QB-A" in w["player"] and "QB-B" in w["player"]]
    assert qb_calls
    assert "QB" in qb_calls[0]["text"]


def test_no_qb_close_call_with_only_one_healthy_qb():
    roster = _roster(**{"QB-B": {**_p("QB-B", "QB", 2), "injury": {"designation": "Out", "out": True}}})
    out = optimize(roster, "mean")
    qb_calls = [w for w in out["why"] if w.get("kind") == "close" and " vs " in w["player"] and w["player"].split(" vs ")[0].startswith("QB")]
    assert not qb_calls


def test_floor_tie_prefers_next_percentile_not_roster_order():
    """Corum 0/0/0/2/4 must not beat Walker 0/0/1/3/5 on P10/P25."""

    def rb(name, p10, p25, p50, p75, p90):
        return {
            "player": name,
            "pos": "RB",
            "proj": {"p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90, "mean": p50},
        }

    # Corum listed before Walker so roster order would start the boom/bust back.
    roster = [
        _p("QB-A", "QB", 5, p10=4),
        rb("Lead Back", 2, 3, 6, 8, 10),
        rb("Blake Corum", 0, 0, 0, 2, 4),
        rb("Kenneth Walker", 0, 0, 1, 3, 5),
        _p("WR-A", "WR", 7, p10=4),
        _p("WR-B", "WR", 6, p10=3),
        _p("WR-C", "WR", 5, p10=3),
        _p("WR-D", "WR", 4, p10=2),
        _p("TE-A", "TE", 4, p10=2),
        _p("K-A", "K", 3, p10=2),
        _p("DST-A", "DST", 2, p10=1),
    ]
    for obj in ("p10", "p25"):
        names = [p["player"] for p in optimize(roster, obj)["starters"] if p["pos"] == "RB"]
        assert "Kenneth Walker" in names, obj
        assert "Blake Corum" not in names, obj
        why = " ".join(w["text"] for w in optimize(roster, obj)["why"] if w.get("kind") == "tiebreak")
        assert "P50" in why


def test_default_objective_is_mean():
    """Cumulative total-points league, no head-to-head: variance is free, so
    every default ranking should target the average, not a percentile."""
    assert DEFAULT_OBJECTIVE == "mean"
    assert optimize(_roster())["objective"] == "mean"


def test_mean_tiebreak_walks_upside_first():
    assert tiebreak_keys("mean") == ("mean", "p75", "p90", "p50", "p25", "p10")


def test_metric_reads_mean_not_p50():
    p = {"proj": {"p10": 0, "p25": 1, "p50": 2, "p75": 3, "p90": 4, "mean": 2.6}}
    assert _metric(p, "mean") == 2.6
    assert _metric(p, "p50") == 2


def test_mean_objective_starts_higher_average_over_higher_median():
    """A high-floor/low-ceiling RB can have the better P50 while a spikier
    one has the better average — mean must start the higher-average player
    for the contested 2nd RB slot, not the higher-P50 one (which would just
    be P50 again under a new name). Same 3-RB/4-WR/1-TE shape as the floor
    tiebreak test above, which forces exactly 2 of the 3 RBs to start.
    """

    def rb(name, p10, p25, p50, p75, p90, mean):
        return {"player": name, "pos": "RB", "proj": {"p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90, "mean": mean}}

    roster = [
        _p("QB-A", "QB", 5, p10=4),
        rb("Lead Back", 2, 3, 6, 8, 10, 6.5),
        rb("Steady Eddie", 3, 4, 5, 6, 7, 5.0),
        rb("Boom Bust", 0, 0, 4, 9, 14, 6.2),
        _p("WR-A", "WR", 9, p10=4),
        _p("WR-B", "WR", 8, p10=3),
        _p("WR-C", "WR", 7, p10=3),
        # Worth more than any 3rd RB under either objective, so the mix
        # search always keeps exactly 2 RBs — the only question is which 2.
        _p("WR-D", "WR", 6.8, p10=2),
        _p("TE-A", "TE", 4, p10=2),
        _p("K-A", "K", 3, p10=2),
        _p("DST-A", "DST", 2, p10=1),
    ]
    mean_starters = [p["player"] for p in optimize(roster, "mean")["starters"] if p["pos"] == "RB"]
    p50_starters = [p["player"] for p in optimize(roster, "p50")["starters"] if p["pos"] == "RB"]
    assert "Boom Bust" in mean_starters and "Steady Eddie" not in mean_starters
    assert "Steady Eddie" in p50_starters and "Boom Bust" not in p50_starters


def test_can_fill_active_rejects_short_skill():
    assert can_fill_active({"QB": 1, "RB": 5, "WR": 6, "TE": 2, "K": 1, "DST": 1})
    assert not can_fill_active({"QB": 1, "RB": 1, "WR": 1, "TE": 1, "K": 1, "DST": 1})
    assert not can_fill_active({"QB": 1, "RB": 5, "WR": 1, "TE": 1, "K": 1, "DST": 1})


def test_bench_order_pos_score_alpha():
    bench = [
        _p("Z-DST", "DST", 3),
        _p("B-WR", "WR", 2),
        _p("A-WR", "WR", 2),
        _p("High-WR", "WR", 5),
        _p("K-A", "K", 1),
        _p("TE-A", "TE", 4),
        _p("RB-A", "RB", 1),
        _p("QB-B", "QB", 3),
    ]
    names = [p["player"] for p in sort_bench(bench, "p50")]
    assert names == ["QB-B", "RB-A", "High-WR", "A-WR", "B-WR", "TE-A", "K-A", "Z-DST"]
    out = optimize(_roster(), "p50")
    pos_rank = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "K": 4, "DST": 5}
    ranks = [pos_rank[p["pos"]] for p in out["bench"]]
    assert ranks == sorted(ranks)


def test_out_projection_is_zero():
    hurt = _p("X", "RB", 6, p10=2, p90=12, injury={"designation": "Out", "out": True})
    adj = apply_injury_proj(hurt)["proj"]
    assert adj["p10"] == adj["p25"] == adj["p50"] == adj["p75"] == adj["p90"] == 0
    assert adj["injury_adj"] == "out"


def test_questionable_does_not_scale_scored_points():
    """Q/D volume is applied in the Monte Carlo, not as 0.75 × already-scored P50."""
    q = apply_injury_proj(_p("Q", "WR", 8, p10=4, p90=16, injury={"designation": "Questionable"}))
    assert q["proj"]["p50"] == 8
    assert q["proj"]["p10"] == 4
    assert q["proj"]["p90"] == 16
    assert q["proj"]["injury_adj"] == "questionable"
    h = _p("H", "WR", 3)
    q2 = _p("Q2", "WR", 3, injury={"designation": "Questionable"})
    h["proj"]["_inj_adj"] = True
    q2["proj"]["_inj_adj"] = True
    assert rank_tuple(h, "p50") > rank_tuple(q2, "p50")
