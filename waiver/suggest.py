"""Add/drop: past, present, future, keeper, plus reimportable board prior."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from cbs_client import MY_TEAM, norm
from cbs_pull import read_standings, waiver_priority_map
from lineup.start_sit import ACTIVE_MAX, OUT_TAGS, ROSTER_CAPS, can_fill_active, injury_tag

ROOT = Path(__file__).resolve().parents[1]
# Re-exported for callers/tests that import CAPS from here.
CAPS = ROSTER_CAPS
IR_SLOTS = frozenset({"injured", "ir"})


def load_board(path: Path | None = None) -> dict[str, dict]:
    p = path or ROOT / "combined.csv"
    if not p.exists():
        return {}
    return {norm(r["player"]): r for r in csv.DictReader(p.open(encoding="utf-8"))}


def load_history() -> dict[str, dict[int, dict]]:
    out: dict[str, dict[int, dict]] = {}
    for season in (2023, 2024, 2025):
        fp = ROOT / f"history_{season}.csv"
        if not fp.exists():
            continue
        for r in csv.DictReader(fp.open(encoding="utf-8")):
            rec = dict(r)
            rec["total"] = float(r["total"])
            rec["scrim"] = int(r["rush_yds"]) + int(r["rec_yds"])
            out.setdefault(norm(r["player"]), {})[season] = rec
    return out


def load_kickers() -> dict[str, dict[int, dict]]:
    out: dict[str, dict[int, dict]] = {}
    for season in (2023, 2024, 2025):
        fp = ROOT / f"kicker_{season}.csv"
        if not fp.exists():
            continue
        for r in csv.DictReader(fp.open(encoding="utf-8")):
            rec = dict(r)
            rec["total"] = float(r["total"])
            out.setdefault(norm(r["player"]), {})[season] = rec
    return out


def _past_pts(hist: dict, name: str) -> float | None:
    h = hist.get(norm(name), {})
    if 2025 in h:
        return h[2025]["total"]
    if 2024 in h:
        return h[2024]["total"]
    return None


MIN_PAR_GAIN = 1.0     # season points of PAR an add must beat the drop by
MIN_STREAM_GAIN = 1.0  # implied-total points a DST/K stream add must beat the drop by


def _par(x: dict) -> float | None:
    g = x.get("grade")
    return g["par"] if g and g.get("par") is not None else None


def _stream_score(x: dict) -> float | None:
    """DST: league-average − next opponent's implied total. K: own implied total. Higher is better."""
    for key in ("stream", "kick"):
        v = x.get(key)
        if v and v.get("score") is not None:
            return float(v["score"])
    return None


def _local(x: dict) -> float:
    """Position-local value, higher is better: PAR for graded WR/TE/RB, the stream score for
    DST/K when the Vegas board is in, else the blended week value."""
    v = _par(x)
    if v is not None:
        return v
    v = _stream_score(x)
    return v if v is not None else x["blended"]


def _has_signal(x: dict) -> bool:
    return x.get("weekly_rank") is not None or bool(x.get("espn_line"))


def _rank_key(x: dict) -> tuple:
    """Sort key for the FA board within a position (the board caps per position).

    Kickers rank behind any current-week signal (a FantasyPros weekly rank or
    an ESPN week projection) first: a K with neither usually isn't active on
    an NFL roster this week even if an earlier-season total still looks
    decent — their blended score alone can't tell a current starter from
    someone who lost the job weeks ago.
    """
    if (x.get("pos") or "").upper() == "K":
        return (0 if _has_signal(x) else 1, -_local(x))
    return (0, -_local(x))


def _better(add: dict, drop: dict) -> bool:
    pa, pd_ = _par(add), _par(drop)
    if pa is not None and pd_ is not None:
        return pa > pd_ + MIN_PAR_GAIN
    sa, sd = _stream_score(add), _stream_score(drop)
    if sa is not None and sd is not None:
        return sa > sd + MIN_STREAM_GAIN
    return add["blended"] > drop["blended"] + 0.05


def _gain(add: dict, drop: dict, weeks_left: int) -> float:
    """How much better the add is than the drop, in season points, so adds at different
    positions sort together."""
    pa, pd_ = _par(add), _par(drop)
    if pa is not None and pd_ is not None:
        return pa - pd_
    sa, sd = _stream_score(add), _stream_score(drop)
    if sa is not None and sd is not None:
        return sa - sd
    return (add["blended"] - drop["blended"]) * weeks_left


def _fa_board(scored_fa: list[dict], per_pos: int = 25) -> list[dict]:
    """Keep the best of each position so a WR filter is not empty when kickers lead blended."""
    ranked = sorted(scored_fa, key=_rank_key)
    taken: dict[str, int] = {}
    out: list[dict] = []
    for s in ranked:
        pos = (s.get("pos") or "").upper() or "?"
        if taken.get(pos, 0) >= per_pos:
            continue
        taken[pos] = taken.get(pos, 0) + 1
        out.append(s)
    return out


def _reason(add: dict, drop: dict, board_weight: float) -> str:
    return (
        f"Blended week value {add['blended']:.2f} vs {drop['blended']:.2f} "
        f"(board weight {board_weight:.0%})."
    )


def _board_value(board: dict, name: str) -> tuple[float | None, str | None]:
    b = board.get(norm(name))
    if not b:
        return None, None
    score = float(b.get("score") or 0)
    # invert: rank 1 is best. Use 200 - combined score as value.
    return round(200 - score, 1), b.get("rank")


SEASON_LAST_WEEK = 18
# Depth-factor keeps the starter-vs-bench spread the old flat 16:10:6
# multiplier had at week 1 (16:10:6 == 1.0 : 0.625 : 0.375 of 16), but scaled
# by the true weeks left instead of a constant that never shrank as the
# season went on (week 17 used to still multiply by 16 with one week left).
DEPTH_FUTURE_FACTOR = {1: 1.0, 2: 0.625}
DEPTH_FUTURE_FACTOR_BACKUP = 0.375


def weeks_remaining(week: int, last_week: int = SEASON_LAST_WEEK) -> int:
    return max(0, last_week - int(week) + 1)


def is_ir_slot(p: dict) -> bool:
    return (p.get("slot") or "").lower() in IR_SLOTS


def waiver_status(rec: dict) -> str:
    """"waivers" (contested, priority order applies), "free_agent" (add any
    time, no claim needed), or "" for a rostered player (not FA at all).
    cbs_fa.csv's own `status` column is the source — blank there means
    free agent, "waivers" means it's still in the post-drop lock.
    """
    if rec.get("owner"):
        return ""
    return "waivers" if (rec.get("status") or "").lower() == "waivers" else "free_agent"


def ir_candidates(mine: list[dict]) -> list[dict]:
    """Rostered players who are Out/IR by designation but not already in a
    CBS IR slot. Moving them is free — IR doesn't count against position
    caps — and opens a roster spot without a drop.
    """
    out = []
    for p in mine:
        if is_ir_slot(p):
            continue
        tag = injury_tag(p)
        if tag not in OUT_TAGS:
            continue
        out.append(
            {
                "player": p.get("player"),
                "pos": (p.get("pos") or "").upper(),
                "designation": (p.get("injury") or {}).get("designation") or tag,
                "note": "Not in an IR slot yet — moving him there doesn't count against position caps and opens a roster spot without a drop.",
            }
        )
    return out


def evaluate_player(
    rec: dict,
    *,
    board: dict,
    hist: dict,
    kickers: dict,
    board_weight: float,
    depth: dict | None = None,
    week: int = 1,
) -> dict[str, Any]:
    """board_weight 0 = this week only, 1 = board only.

    present is the injury-adjusted mean (expected points) from assemble —
    not the median: this is a cumulative total-points league with no
    head-to-head, so variance is free and every valuation should target the
    average, never a percentile.
    """
    name = rec["player"]
    pos = (rec.get("pos") or "").upper()
    proj = rec.get("proj") or {}
    present = float(proj.get("mean") or 0)
    p10 = float(proj.get("p10") or 0)
    # ROS proxy: weeks left in the season * present, discounted if backup.
    depth = depth or {}
    role = {}
    if "name" in depth or "id" in depth:
        role = (depth.get("id") or {}).get(str(rec.get("cbs_id") or "")) or (
            depth.get("name") or {}
        ).get(norm(name), {})
    else:
        role = depth.get(norm(name), {})
    try:
        rank_d = int(role.get("depth_rank") or rec.get("depth_rank") or 0) or 1
    except (TypeError, ValueError):
        rank_d = 1
    role_note = role.get("role_note") or rec.get("role_note") or ""
    weeks_left = weeks_remaining(week)
    if rank_d >= 3:
        depth_factor = DEPTH_FUTURE_FACTOR_BACKUP
    else:
        depth_factor = DEPTH_FUTURE_FACTOR.get(rank_d, DEPTH_FUTURE_FACTOR[1])
    future = present * weeks_left * depth_factor
    kpts = kickers.get(norm(name), {})
    past = _past_pts(hist, name)
    if past is None and kpts:
        past = kpts.get(2025, {}).get("total") or kpts.get(2024, {}).get("total")
    bval, brank = _board_value(board, name)
    # Keeper: board for prospects, future for proven.
    # CBS rows carry no age; it lives on the combined.csv board row.
    age = rec.get("age")
    if age in (None, ""):
        age = (board.get(norm(name)) or {}).get("age")
    try:
        age_n = int(age) if age not in (None, "") else 27
    except ValueError:
        age_n = 27
    keeper = 0.0
    if bval is not None and age_n <= 24:
        keeper = bval * 0.5
    elif bval is not None:
        keeper = bval * 0.2
    if pos in {"K", "DST"} and present >= 4:
        keeper = max(keeper, present * 4)

    # Blend present with board for the ranking used in add/drop
    if bval is None:
        blended = present
    else:
        # scale board to weekly-ish 0-8
        board_week = max(0.0, bval / 40)
        blended = (1 - board_weight) * present + board_weight * board_week

    return {
        "player": name,
        "pos": pos,
        "team": rec.get("team") or "",
        "past": None if past is None else round(float(past), 1),
        "present": round(present, 2),
        "p10": round(p10, 2),
        "future": round(future, 1),
        "keeper": round(keeper, 1),
        "board_rank": brank,
        "board_value": bval,
        "weekly_rank": rec.get("weekly_rank"),
        "weekly_value": rec.get("weekly_value"),
        "weekly_list": rec.get("weekly_list"),
        "weekly_matchup": rec.get("weekly_matchup") or "",
        "has_espn": bool(rec.get("has_espn")),
        "espn_pts": rec.get("espn_pts") or "",
        "espn_tip": rec.get("espn_tip") or "",
        "espn_line": rec.get("espn_line") or "",
        "espn_gbfl": rec.get("espn_gbfl"),
        "blended": round(blended, 3),
        "depth_rank": rank_d,
        "role_note": role_note,
        "owner": rec.get("owner") or "",
        "waiver_status": waiver_status(rec),
        "rankings_as_of": rec.get("rankings_as_of") or "",
        "grade": rec.get("grade"),
        "stream": rec.get("stream"),
        "kick": rec.get("kick"),
    }


def suggest(
    roster: list[dict],
    fa: list[dict],
    *,
    board_weight: float = 0.35,
    board: dict | None = None,
    depth: dict | None = None,
    rankings_as_of: str = "",
    weekly_weight: float = 0.0,
    week: int = 1,
) -> dict[str, Any]:
    board = board if board is not None else load_board()
    hist = load_history()
    kickers = load_kickers()
    mine = [r for r in roster if (r.get("owner") or "") == MY_TEAM]
    if not mine:
        mine = list(roster)
    # IR doesn't count against the 19-man position caps (§3), so a player
    # sitting in a CBS IR slot shouldn't occupy one of those counted spots.
    counts = {}
    for p in mine:
        if is_ir_slot(p):
            continue
        counts[(p.get("pos") or "").upper()] = counts.get((p.get("pos") or "").upper(), 0) + 1

    scored_mine = [
        evaluate_player(
            {**p, "rankings_as_of": rankings_as_of},
            board=board,
            hist=hist,
            kickers=kickers,
            board_weight=board_weight,
            depth=depth,
            week=week,
        )
        for p in mine
    ]
    scored_fa = [
        evaluate_player(
            {**p, "rankings_as_of": rankings_as_of},
            board=board,
            hist=hist,
            kickers=kickers,
            board_weight=board_weight,
            depth=depth,
            week=week,
        )
        for p in fa
    ]

    def remaining_legal(after: dict) -> bool:
        return can_fill_active(after)

    def droppable(s):
        pos = s["pos"]
        trial = dict(counts)
        trial[pos] = trial.get(pos, 0) - 1
        return remaining_legal(trial)

    # A next man up is worth more than PAR shows this week (the flag isn't priced into it), so he's
    # never the suggested drop; the user can still cut him by hand.
    protected = lambda x: "next_up" in ((x.get("grade") or {}).get("flags") or [])
    drops = sorted([s for s in scored_mine if droppable(s) and not protected(s)],
                   key=lambda x: (x["blended"], x["future"], x["keeper"]))
    # Kickers: free-agent adds only, never a claim (§4/§7) — a K-for-K swap
    # makes the Thursday drop-pool lock irrelevant, so it's never worth
    # spending Tuesday priority on one.
    eligible_fa = [s for s in scored_fa if not (s["pos"] == "K" and s.get("waiver_status") == "waivers")]
    # Order adds by how much each beats the worst droppable player at his position, in season
    # points, so a PAR gain at WR and a stream gain at DST compete on one scale.
    worst = {pos: min((d for d in drops if d["pos"] == pos), key=_local, default=None) for pos in {d["pos"] for d in drops}}
    weeks_left = weeks_remaining(week)

    def _pregain(a: dict) -> float:
        w = worst.get(a["pos"]) or (drops[0] if drops else None)
        if w is None:
            return float("-inf")
        penalty = 1e6 if a["pos"] == "K" and not _has_signal(a) else 0.0
        return _gain(a, w, weeks_left) - penalty

    adds = sorted(eligible_fa, key=lambda a: -_pregain(a))

    priority_map = waiver_priority_map()
    my_priority = priority_map.get(MY_TEAM)
    total_teams = len(priority_map) or None

    def _claim_note(add: dict) -> str:
        if add.get("waiver_status") == "waivers":
            if my_priority and total_teams:
                return f" On waivers — you're priority {my_priority}/{total_teams}; assume you lose a contested claim."
            return " On waivers — assume you lose a contested claim if it's contested."
        if add.get("waiver_status") == "free_agent":
            return " Free agent — add any time, no claim needed."
        return ""

    recs = []
    used_fa = set()
    used_drop = set()
    for add in adds[:40]:
        pos = add["pos"]
        if counts.get(pos, 0) >= CAPS.get(pos, 99):
            # need a same-pos drop
            same = sorted((d for d in drops if d["pos"] == pos and d["player"] not in used_drop), key=_local)
            if not same:
                continue
            drop = same[0]
        else:
            drop = drops[0] if drops else None
            if drop and drop["pos"] != pos and counts.get(pos, 0) >= CAPS.get(pos, 99):
                continue
        if not drop:
            continue
        if not _better(add, drop):
            continue
        if add["player"] in used_fa or drop["player"] in used_drop:
            continue
        cap_note = ""
        if counts.get(pos, 0) >= CAPS.get(pos, 99):
            cap_note = f"Roster is at {CAPS[pos]} {pos}; must drop a {pos}. Cannot add a 7th WR." if pos == "WR" else f"Roster is at {CAPS[pos]} {pos}; must drop a {pos}."
        recs.append(
            {
                "add": add,
                "drop": drop,
                "reason": (cap_note or _reason(add, drop, board_weight)) + _claim_note(add),
            }
        )
        used_fa.add(add["player"])
        used_drop.add(drop["player"])
        if len(recs) >= 5:
            break

    return {
        "rankings_as_of": rankings_as_of,
        "board_weight": board_weight,
        "weekly_weight": weekly_weight,
        "waiver_priority": my_priority,
        "waiver_teams": total_teams,
        "ir_candidates": ir_candidates(mine),
        "caps": CAPS,
        "active_max": ACTIVE_MAX,
        "recommendations": recs,
        "roster_scored": scored_mine,
        "fa_top": _fa_board(scored_fa),
    }
