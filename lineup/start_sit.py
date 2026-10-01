"""Enumerate legal GBFL lineups under CBS active min/max."""
from __future__ import annotations

from typing import Any

# 10 starters: 1 QB + 1 K + 1 DST + 7 skill. Skill is NOT unconstrained 4-FLEX.
ACTIVE_MIN = {"QB": 1, "RB": 1, "WR": 1, "TE": 1, "K": 1, "DST": 1}
ACTIVE_MAX = {"QB": 1, "RB": 4, "WR": 4, "TE": 2, "K": 1, "DST": 1}
ROSTER_CAPS = {"QB": 2, "RB": 5, "WR": 6, "TE": 2, "K": 2, "DST": 2}
SKILL_STARTERS = 7
FLEX_POS = {"RB", "WR", "TE"}
OBJECTIVES = ("p10", "p25", "p50", "p75", "p90")
# "mean" (expected points) is a separate, non-percentile objective — kept out
# of OBJECTIVES because tiebreak_keys()'s p10..p90 walk assumes OBJECTIVES is
# a strictly ordered percentile sequence. DEFAULT_OBJECTIVE is "mean": this
# is a cumulative-total-points league with no head-to-head, so variance is
# free and every ranking should maximize the average, not a percentile.
DEFAULT_OBJECTIVE = "mean"
ALL_OBJECTIVES = OBJECTIVES + (DEFAULT_OBJECTIVE,)
OBJECTIVE_LABELS = {
    "p10": "floor",
    "p25": "safe bets",
    "p50": "median",
    "p75": "high upside",
    "p90": "ceiling",
    "mean": "expected points",
}

LEGAL_SKILL_MIXES = [
    (n_rb, n_wr, n_te)
    for n_te in (1, 2)
    for n_rb in range(1, 5)
    for n_wr in range(1, 5)
    if n_rb + n_wr + n_te == SKILL_STARTERS
]


# Per-draw snap/volume factors at P10–P90 (not point multipliers).
# Floor is cut harder than the ceiling so Q/D weeks stay wide; scoring stays GBFL.
INJURY_WEIGHTS = {
    "out": (0.0, 0.0, 0.0, 0.0, 0.0),
    "ir": (0.0, 0.0, 0.0, 0.0, 0.0),
    "injured": (0.0, 0.0, 0.0, 0.0, 0.0),
    "pup": (0.0, 0.0, 0.0, 0.0, 0.0),
    "doubtful": (0.0, 0.15, 0.35, 0.55, 0.70),
    "questionable": (0.45, 0.60, 0.75, 0.90, 1.05),
    "probable": (0.85, 0.90, 0.95, 1.0, 1.0),
}
INJURY_SNAP_PCTS = (0.10, 0.25, 0.50, 0.75, 0.90)
OUT_TAGS = frozenset({"out", "ir", "injured", "pup"})
HEALTH_SCORE = {
    "": 3,
    "probable": 2,
    "questionable": 1,
    "doubtful": 0,
    "out": -1,
    "ir": -1,
    "injured": -1,
    "pup": -1,
}


def injury_tag(player: dict) -> str:
    inj = player.get("injury") or {}
    des = (inj.get("designation") or "").lower()
    slot = (player.get("slot") or "").lower()
    if inj.get("out") or slot in {"injured", "ir", "o", "out"} or des in {"out", "ir", "pup"}:
        if des == "ir" or slot == "ir":
            return "ir"
        return "out"
    if "doubt" in des:
        return "doubtful"
    if "question" in des:
        return "questionable"
    if "probab" in des:
        return "probable"
    return ""


def health_score(player: dict) -> int:
    return HEALTH_SCORE.get(injury_tag(player), 3)


def injury_snap_factor(tag: str, rng) -> float:
    """Snap/volume share for one simulated game. Inverse-CDF over INJURY_WEIGHTS."""
    if not tag or tag not in INJURY_WEIGHTS:
        return 1.0
    w = INJURY_WEIGHTS[tag]
    if tag in OUT_TAGS:
        return 0.0
    u = float(rng.random())
    xs = INJURY_SNAP_PCTS
    if u <= xs[0]:
        return float(w[0])
    if u >= xs[-1]:
        return float(w[-1])
    for i in range(1, len(xs)):
        if u <= xs[i]:
            t = (u - xs[i - 1]) / (xs[i] - xs[i - 1])
            return float(w[i - 1] + t * (w[i] - w[i - 1]))
    return float(w[-1])


def apply_injury_proj(player: dict) -> dict:
    """OUT/IR → 0/0/0/0/0. Q/D/P volume is applied inside the Monte Carlo, not to points."""
    p = dict(player)
    proj = dict(p.get("proj") or {})
    if proj.get("_inj_adj"):
        return p
    raw = {k: proj.get(k) for k in (*OBJECTIVES, "mean")}
    tag = injury_tag(p)
    if tag in OUT_TAGS:
        for key in (*OBJECTIVES, "mean"):
            if proj.get(key) is not None:
                proj[key] = 0.0
        proj["injury_adj"] = tag or "out"
    elif tag:
        proj["injury_adj"] = tag
    proj["raw"] = raw
    proj["_inj_adj"] = True
    p["proj"] = proj
    return p


def _pct(player: dict, key: str) -> float:
    return float((player.get("proj") or {}).get(key) or 0)


def _metric(player: dict, objective: str) -> float:
    key = objective if objective in OBJECTIVES or objective == "mean" else DEFAULT_OBJECTIVE
    return _pct(player, key)


def tiebreak_keys(objective: str) -> tuple[str, ...]:
    """When the optimized value ties, walk the rest of the curve.

    Floor / safe (P10, P25): same floor → who scores *next* (P50, then P75, P90).
    That prefers Walker 0/0/1/3/5 over Corum 0/0/0/2/4 — not roster order.
    Median: P50, then floor, then upside.
    Upside / ceiling: same top tick → next-highest rungs.
    Mean (the default): same average → prefer the one with more upside next,
    since variance is free in this format — then fall back through the rest
    of the band.
    """
    if objective == "mean":
        return ("mean", "p75", "p90", "p50", "p25", "p10")
    if objective not in OBJECTIVES:
        objective = "p50"
    i = OBJECTIVES.index(objective)
    if objective in ("p10", "p25"):
        return OBJECTIVES[i:] + OBJECTIVES[:i]
    if objective in ("p75", "p90"):
        return tuple(reversed(OBJECTIVES[: i + 1])) + OBJECTIVES[i + 1 :]
    return ("p50", "p25", "p10", "p75", "p90")


def rank_tuple(player: dict, objective: str) -> tuple[float, ...]:
    # Last key: healthy beats Q/D when the injury-adjusted curve is tied.
    return tuple(_pct(player, k) for k in tiebreak_keys(objective)) + (float(health_score(player)),)


def lineup_rank_tuple(lineup: list[dict], objective: str) -> tuple[float, ...]:
    scores = tuple(sum(_pct(p, k) for p in lineup) for k in tiebreak_keys(objective))
    return scores + (float(sum(health_score(p) for p in lineup)),)


def can_fill_active(counts: dict) -> bool:
    """True if remaining roster can still fill a legal 10-man active lineup."""
    if counts.get("QB", 0) < 1 or counts.get("K", 0) < 1 or counts.get("DST", 0) < 1:
        return False
    rb, wr, te = counts.get("RB", 0), counts.get("WR", 0), counts.get("TE", 0)
    for n_rb, n_wr, n_te in LEGAL_SKILL_MIXES:
        if rb >= n_rb and wr >= n_wr and te >= n_te:
            return True
    return False


def skill_counts_legal(n_rb: int, n_wr: int, n_te: int) -> bool:
    return (n_rb, n_wr, n_te) in LEGAL_SKILL_MIXES


POS_ORDER = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "K": 4, "DST": 5}


def sort_bench(bench: list[dict], objective: str) -> list[dict]:
    """QB > RB > WR > TE > K > DST, then optimized score desc, then name."""
    return sorted(
        bench,
        key=lambda p: (
            POS_ORDER.get((p.get("pos") or "").upper(), 9),
            -_metric(p, objective),
            (p.get("player") or "").lower(),
        ),
    )


def _is_unavailable(player: dict) -> bool:
    slot = (player.get("slot") or "").lower()
    inj = player.get("injury") or {}
    note = (inj.get("designation") or "").lower()
    if inj.get("out"):
        return True
    if slot in {"injured", "ir", "o", "out"}:
        return True
    if note in {"out", "ir", "doubtful"} or "doubt" in note:
        return True
    if note == "out" or note.startswith("out"):
        return True
    return False


def _eligible(roster: list[dict], injured_out: bool = True) -> list[dict]:
    out = []
    for p in roster:
        if injured_out and _is_unavailable(p):
            p = dict(p)
            p["_out"] = True
        out.append(p)
    return out


def optimize(roster: list[dict], objective: str = DEFAULT_OBJECTIVE, allow_injured: bool = False) -> dict[str, Any]:
    """Max SUM of the chosen percentile (or the mean) across a legal active lineup."""
    objective = objective if objective in ALL_OBJECTIVES else DEFAULT_OBJECTIVE
    roster = [apply_injury_proj(p) for p in roster]
    tagged = _eligible(roster, injured_out=not allow_injured)
    players = [p for p in tagged if not p.get("_out")]
    by = {pos: [p for p in players if (p.get("pos") or "").upper() == pos] for pos in ("QB", "RB", "WR", "TE", "K", "DST")}

    def top(xs, n):
        return sorted(xs, key=lambda p: rank_tuple(p, objective), reverse=True)[:n]

    qbs, rbs, wrs, tes, ks, dsts = top(by["QB"], 2), top(by["RB"], 5), top(by["WR"], 6), top(by["TE"], 2), top(by["K"], 2), top(by["DST"], 2)

    best = None
    best_rank: tuple[float, ...] | None = None
    best_mix = None
    qb = qbs[0] if qbs else None
    k = ks[0] if ks else None
    dst = dsts[0] if dsts else None

    for n_rb, n_wr, n_te in LEGAL_SKILL_MIXES:
        if len(rbs) < n_rb or len(wrs) < n_wr or len(tes) < n_te:
            continue
        if not qb or not k or not dst:
            continue
        lineup = [qb, k, dst] + rbs[:n_rb] + wrs[:n_wr] + tes[:n_te]
        rank = lineup_rank_tuple(lineup, objective)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best = lineup
            best_mix = (n_rb, n_wr, n_te)

    if not best:
        best = sorted(players, key=lambda p: rank_tuple(p, objective), reverse=True)[:10]
        best_rank = lineup_rank_tuple(best, objective)
        best_mix = None

    best_score = best_rank[0] if best_rank else 0.0

    starter_ids = {p.get("player") for p in best}
    bench = sort_bench([p for p in tagged if p.get("player") not in starter_ids], objective)
    slots = _assign_slots(best)
    why = _whys(slots, bench, objective)
    label = OBJECTIVE_LABELS.get(objective, objective)
    return {
        "objective": objective,
        "objective_label": label,
        "allow_injured": allow_injured,
        "total": round(best_score, 2),
        "mix": {"RB": best_mix[0], "WR": best_mix[1], "TE": best_mix[2]} if best_mix else None,
        "starters": slots,
        "bench": bench,
        "why": why,
        "active_caps": ACTIVE_MAX,
        "active_min": ACTIVE_MIN,
    }


def _assign_slots(lineup: list[dict]) -> list[dict]:
    used = set()
    out = []

    def take(pos: str):
        for p in lineup:
            if p.get("player") in used:
                continue
            if (p.get("pos") or "").upper() == pos:
                used.add(p.get("player"))
                q = dict(p)
                q["lineup_slot"] = pos
                out.append(q)
                return

    for pos in ("QB", "RB", "WR", "TE", "K", "DST"):
        take(pos)
    for p in lineup:
        if p.get("player") in used:
            continue
        q = dict(p)
        q["lineup_slot"] = "FLEX"
        out.append(q)
        used.add(p.get("player"))
    order = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "FLEX": 4, "K": 5, "DST": 6}
    out.sort(key=lambda p: (order.get(p["lineup_slot"], 9), -float((p.get("proj") or {}).get("p50") or 0)))
    return out


def _whys(starters: list[dict], bench: list[dict], objective: str) -> list[dict]:
    notes = []
    label = OBJECTIVE_LABELS.get(objective, "expected points")
    for p in starters:
        pos = (p.get("pos") or "").upper()
        proj = p.get("proj") or {}
        p50, p10, p90 = proj.get("p50", 0), proj.get("p10", 0), proj.get("p90", 0)
        spread = p90 - p10
        slot = p.get("lineup_slot") or pos
        if pos == "TE":
            text = "TE slot (active max 2). Premium pays if he clears 60 yards."
        elif pos == "WR" and spread >= 8:
            text = "P90 lives in 46+ receiving TDs, not catch volume."
        elif pos == "RB":
            text = "Scrimmage-yard buckets; workhorse volume beats TD luck on the median."
        elif pos == "K":
            text = "Long FG (51+) is +2 vs a chip shot in this format."
        elif pos == "DST":
            text = "High floor from PA buckets; TDs are the lottery tail."
        elif pos == "QB":
            text = "Yardage is per-game buckets (200+). Boom weeks clear 250/300."
        else:
            text = "Median week under league scoring."
        if objective == "p10" and spread >= 8:
            text = "Floor start: narrower band than the boom-bust alternative."
        elif objective == "p25":
            text = f"Safe-bet start ({label}): optimizing P25, not the long-TD tail."
        elif objective == "p75" and spread >= 6:
            text = "High-upside start: P75 needs a chunk play or extra yardage bucket."
        elif objective == "p90":
            text = "Ceiling start: P90 is the long-TD / long-FG tail in this scoring."
        elif objective == "mean":
            text = "Expected-points start: no head-to-head, no playoffs — variance is free, so this maximizes the average, not a percentile."
        tag = (p.get("proj") or {}).get("injury_adj") or injury_tag(p)
        if tag == "questionable":
            text = "Questionable: snaps/volume cut in the sim (floor more than ceiling). Points are GBFL scores, not a fraction of a healthy week."
        elif tag == "doubtful":
            text = "Doubtful: steep snap/volume cut. Only in the pool if you override injured."
        elif tag in {"out", "ir", "injured"}:
            text = "Out: scored 0/0/0/0/0 this week."
        notes.append({"player": p.get("player"), "text": text, "kind": "starter", "slot": slot})
    notes.extend(_close_calls(starters, bench, objective))
    notes.extend(_tiebreak_notes(starters, bench, objective))
    return notes


def _tiebreak_notes(starters: list[dict], bench: list[dict], objective: str) -> list[dict]:
    """Explain when the starter won a same-objective tie on a later percentile."""
    notes = []
    keys = tiebreak_keys(objective)
    for p in starters:
        pos = (p.get("pos") or "").upper()
        rivals = [
            b
            for b in bench
            if (b.get("pos") or "").upper() == pos and not b.get("_out")
        ]
        if not rivals:
            continue
        rival = max(rivals, key=lambda b: rank_tuple(b, objective))
        if _metric(p, objective) != _metric(rival, objective):
            continue
        if rank_tuple(p, objective) <= rank_tuple(rival, objective):
            continue
        nxt = next((k for k in keys[1:] if _pct(p, k) != _pct(rival, k)), None)
        if not nxt:
            continue
        notes.append(
            {
                "player": f"{p.get('player')} vs {rival.get('player')}",
                "text": (
                    f"Same {objective.upper()}; {p.get('player')} starts on "
                    f"{nxt.upper()} {_pct(p, nxt):g} vs {_pct(rival, nxt):g} "
                    f"(not roster order)."
                ),
                "kind": "tiebreak",
            }
        )
    return notes


def _close_calls(starters: list[dict], bench: list[dict], objective: str) -> list[dict]:
    notes = []
    # Exactly one active QB slot but the roster caps at 2 QBs, so which one
    # starts is a real decision every single week — always surface it, not
    # only when the projections happen to be close.
    qbs = sorted(
        (p for p in starters + bench if (p.get("pos") or "").upper() == "QB" and not p.get("_out")),
        key=lambda p: rank_tuple(p, objective),
        reverse=True,
    )
    if len(qbs) >= 2:
        a, b = qbs[0], qbs[1]
        notes.append(
            {
                "player": f"{a.get('player')} vs {b.get('player')}",
                "text": "QB call: only one active QB slot. Recheck matchup/Vegas each week, not just this sim.",
                "kind": "close",
            }
        )
    tes = [p for p in starters + bench if (p.get("pos") or "").upper() == "TE"]
    if len(tes) >= 2:
        a, b = tes[0], tes[1]
        notes.append(
            {
                "player": f"{a.get('player')} vs {b.get('player')}",
                "text": "Close TE call: YPC/spike profile vs target volume. Volume does not score here. Active max 2 TE.",
                "kind": "close",
            }
        )
    flex_s = [p for p in starters if (p.get("lineup_slot") or "") == "FLEX" or (p.get("pos") or "").upper() in FLEX_POS]
    flex_b = [p for p in bench if (p.get("pos") or "").upper() in FLEX_POS and not p.get("_out")]
    if flex_s and flex_b:
        worst = min(flex_s, key=lambda p: _metric(p, objective))
        best_b = max(flex_b, key=lambda p: _metric(p, objective))
        gap = abs(_metric(worst, objective) - _metric(best_b, objective))
        if gap <= 1.5 and worst.get("player") != best_b.get("player"):
            notes.append(
                {
                    "player": f"{worst.get('player')} vs {best_b.get('player')}",
                    "text": "Close skill call at this percentile. Active max 4 RB / 4 WR — a 5th RB cannot start.",
                    "kind": "close",
                }
            )
    return notes
