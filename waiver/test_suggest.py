from waiver.suggest import CAPS, evaluate_player, ir_candidates, is_ir_slot, waiver_status, weeks_remaining, suggest


def _p(name, pos, p50, owner="BUSSONE", board_rank=None, **kw):
    rec = {
        "player": name,
        "pos": pos,
        "owner": owner,
        # mean == p50 in these synthetic fixtures (not testing distribution
        # shape here); evaluate_player values present/future off the mean.
        "proj": {"p10": max(0, p50 - 1), "p50": p50, "p90": p50 + 3, "mean": p50},
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


def test_weeks_remaining_clamped_and_counts_current_week():
    assert weeks_remaining(1) == 18
    assert weeks_remaining(17) == 2
    assert weeks_remaining(18) == 1
    assert weeks_remaining(19) == 0  # season's over, never negative


def test_future_scales_by_weeks_remaining_not_a_flat_multiplier():
    """The old `present * 16` never shrank — week 17 still multiplied by 16
    with one week left. Future must track the season's true remaining weeks.
    """
    rec, _ = _p("Starter", "RB", 5)  # depth_rank 1 by default
    week1 = evaluate_player(rec, board={}, hist={}, kickers={}, board_weight=0.0, week=1)
    week17 = evaluate_player(rec, board={}, hist={}, kickers={}, board_weight=0.0, week=17)
    assert week1["future"] == round(5 * 18 * 1.0, 1)
    assert week17["future"] == round(5 * 2 * 1.0, 1)
    assert week17["future"] < week1["future"]


def test_present_is_the_mean_not_the_median():
    rec = {
        "player": "X",
        "pos": "WR",
        "proj": {"p10": 0, "p50": 2, "mean": 5.5, "p90": 10},
        "depth_rank": 1,
    }
    out = evaluate_player(rec, board={}, hist={}, kickers={}, board_weight=0.0, week=1)
    assert out["present"] == 5.5


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


def test_weekly_weight_zero_present_is_unperturbed():
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


def test_waiver_status_tagging():
    rostered, _ = _p("Mine", "WR", 5, owner="BUSSONE")
    fa_open, _ = _p("Open", "WR", 5, owner="")
    fa_waivers, _ = _p("Locked", "WR", 5, owner="", status="waivers")
    assert waiver_status(rostered) == ""
    assert waiver_status(fa_open) == "free_agent"
    assert waiver_status(fa_waivers) == "waivers"


def test_kicker_on_waivers_is_never_recommended():
    """Kickers: free-agent adds only, never a claim (§4/§7) — a K-for-K swap
    makes the Thursday drop-pool lock irrelevant."""
    roster = _full_bussone()
    fa = [_p("Big Leg", "K", 50, owner="", status="waivers")[0]]  # dominates every blended score
    out = suggest(roster, fa, board_weight=0.0, board={})
    assert not any(r["add"]["player"] == "Big Leg" for r in out["recommendations"])


def test_kicker_free_agent_still_recommended():
    roster = _full_bussone()
    fa = [_p("Open Leg", "K", 50, owner="")[0]]
    out = suggest(roster, fa, board_weight=0.0, board={})
    assert any(r["add"]["player"] == "Open Leg" for r in out["recommendations"])


def test_ir_slot_does_not_count_against_position_cap():
    """A 7th WR add should not need a same-position drop when one of the 6
    rostered WRs is already sitting in a CBS IR slot — IR doesn't count
    against the 19-man position caps."""
    roster = _full_bussone()
    for p in roster:
        if p["player"] == "W6":
            p["slot"] = "Injured"
    fa = [_p("FA-WR", "WR", 9, owner="")[0]]
    out = suggest(roster, fa, board_weight=0.0, board={})
    wr_add = next((r for r in out["recommendations"] if r["add"]["player"] == "FA-WR"), None)
    assert wr_add is not None
    assert wr_add["drop"]["pos"] != "WR"
    assert "must drop a WR" not in wr_add["reason"]


def test_is_ir_slot():
    assert is_ir_slot({"slot": "Injured"})
    assert is_ir_slot({"slot": "IR"})
    assert not is_ir_slot({"slot": "WR"})
    assert not is_ir_slot({"slot": ""})


def test_ir_candidates_flags_out_player_not_yet_on_ir():
    mine = [
        {"player": "Hurt Not IR'd", "pos": "RB", "slot": "", "injury": {"designation": "Out", "out": True}},
        {"player": "Already IR'd", "pos": "WR", "slot": "Injured", "injury": {"designation": "Out", "out": True}},
        {"player": "Healthy", "pos": "TE", "slot": "TE", "injury": None},
    ]
    flagged = {c["player"] for c in ir_candidates(mine)}
    assert flagged == {"Hurt Not IR'd"}


def test_waiver_priority_and_claim_note_in_reason(monkeypatch):
    import waiver.suggest as ws

    monkeypatch.setattr(ws, "waiver_priority_map", lambda: {"BUSSONE": 4, "THROBBER": 1})
    roster = _full_bussone()
    fa = [_p("Locked WR", "WR", 9, owner="", status="waivers")[0]]
    out = suggest(roster, fa, board_weight=0.0, board={})
    assert out["waiver_priority"] == 4
    assert out["waiver_teams"] == 2
    rec = next(r for r in out["recommendations"] if r["add"]["player"] == "Locked WR")
    assert "priority 4/2" in rec["reason"]
    assert "contested" in rec["reason"]


def test_fa_board_keeps_skill_when_kickers_lead():
    roster = _full_bussone()
    fa = [_p(f"K{i}", "K", 20, owner="")[0] for i in range(40)]
    fa.append(_p("FA-WR", "WR", 2, owner="")[0])
    out = suggest(roster, fa, board_weight=0.0, board={})
    assert any(p["player"] == "FA-WR" for p in out["fa_top"])
    assert sum(1 for p in out["fa_top"] if p["pos"] == "K") <= 25



def _graded(name, pos, par, p50=1.0, **kw):
    rec, rank = _p(name, pos, p50, **kw)
    rec["grade"] = {"par": par, "role": 50, "flags": []}
    return rec


def test_graded_players_compare_on_par_not_blended():
    roster = [r for r in _full_bussone() if r["pos"] != "WR"] + [
        _graded(f"W{i}", "WR", par, p50=5.0, owner="BUSSONE") for i, par in enumerate([8, 6, 5, 4, 3, -4])]
    # The free agent has the lower blended value but a far better PAR than the worst WR.
    fa = [_graded("Role Guy", "WR", 12, p50=0.5, owner="")]
    out = suggest(roster, fa, board_weight=0.0, board={})
    rec = next(r for r in out["recommendations"] if r["add"]["player"] == "Role Guy")
    assert rec["drop"]["player"] == "W5"  # the PAR −4 WR, not whoever has the lowest blended value


def test_par_gain_must_clear_the_minimum():
    roster = [r for r in _full_bussone() if r["pos"] != "WR"] + [
        _graded(f"W{i}", "WR", par, owner="BUSSONE") for i, par in enumerate([8, 6, 5, 4, 3, 2])]
    fa = [_graded("Marginal", "WR", 2.5, owner="")]  # only 0.5 PAR over the worst WR
    out = suggest(roster, fa, board_weight=0.0, board={})
    assert not any(r["add"]["player"] == "Marginal" for r in out["recommendations"])


def test_dst_stream_prefers_the_softer_matchup():
    roster = _full_bussone()
    for r in roster:
        if r["pos"] == "DST":
            r["stream"] = {"score": -2.0}  # a tough opponent this week
    fa = [dict(_p("Soft Matchup", "DST", 1.0, owner="")[0], stream={"score": 3.0}),
          dict(_p("Hard Matchup", "DST", 1.0, owner="")[0], stream={"score": -4.0})]
    out = suggest(roster, fa, board_weight=0.0, board={})
    adds = [r["add"]["player"] for r in out["recommendations"] if r["add"]["pos"] == "DST"]
    assert adds[0] == "Soft Matchup" and "Hard Matchup" not in adds


def test_kicker_without_current_signal_ranks_last_even_with_a_big_implied_total():
    roster = _full_bussone()
    for r in roster:
        if r["pos"] == "K":
            r["kick"] = {"score": 17.0}
    fa = [dict(_p("Ghost", "K", 1.0, owner="")[0], kick={"score": 30.0}),
          dict(_p("Live", "K", 1.0, owner="")[0], kick={"score": 24.0}, weekly_rank=5)]
    out = suggest(roster, fa, board_weight=0.0, board={})
    ks = [r["add"]["player"] for r in out["recommendations"] if r["add"]["pos"] == "K"]
    assert ks[0] == "Live"


def test_next_man_up_is_never_the_suggested_drop():
    roster = [r for r in _full_bussone() if r["pos"] != "RB"] + [
        _graded(f"R{i}", "RB", par, p50=3.0, owner="BUSSONE") for i, par in enumerate([9, 7, 6, 5])]
    nxt = _graded("Next Up", "RB", 0.9, p50=0.6, owner="BUSSONE")
    nxt["grade"]["flags"] = ["next_up"]  # his lead back just tore an ACL
    roster.append(nxt)
    fa = [_graded("Committee Back", "RB", 13.5, p50=1.0, owner="")]
    out = suggest(roster, fa, board_weight=0.0, board={})
    rec = next(r for r in out["recommendations"] if r["add"]["player"] == "Committee Back")
    assert rec["drop"]["player"] == "R3"  # the lowest-PAR back who is not the next man up
