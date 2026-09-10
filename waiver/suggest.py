"""Add/drop: past, present, future, keeper, plus reimportable board prior."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from cbs_client import MY_TEAM, norm
from lineup.start_sit import can_fill_active

ROOT = Path(__file__).resolve().parents[1]
CAPS = {"QB": 2, "RB": 5, "WR": 6, "TE": 2, "K": 2, "DST": 2}
STARTER_MIN = {"QB": 1, "RB": 1, "WR": 1, "TE": 1, "K": 1, "DST": 1}


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


def _reason(add: dict, drop: dict, board_weight: float, weekly_weight: float) -> str:
    bits = [
        f"Blended week value {add['blended']:.2f} vs {drop['blended']:.2f} (board weight {board_weight:.0%})"
    ]
    if weekly_weight > 0:
        bits.append(f"FP weekly {weekly_weight:.0%}")
    return bits[0] + (f"; {bits[1]}." if len(bits) > 1 else ".")


def _board_value(board: dict, name: str) -> tuple[float | None, str | None]:
    b = board.get(norm(name))
    if not b:
        return None, None
    score = float(b.get("score") or 0)
    # invert: rank 1 is best. Use 200 - combined score as value.
    return round(200 - score, 1), b.get("rank")


def evaluate_player(
    rec: dict,
    *,
    board: dict,
    hist: dict,
    kickers: dict,
    board_weight: float,
    depth: dict | None = None,
    weekly_weight: float = 0.0,
) -> dict[str, Any]:
    """board_weight 0 = this week only, 1 = board only.

    present is already the injury + FP-shifted P50 from assemble.
    """
    name = rec["player"]
    pos = (rec.get("pos") or "").upper()
    proj = rec.get("proj") or {}
    present = float(proj.get("p50") or 0)
    p10 = float(proj.get("p10") or 0)
    # ROS proxy: remaining ~16 weeks * p50, discounted if backup
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
    if rank_d >= 3:
        future = present * 6
    elif rank_d == 2:
        future = present * 10
    else:
        future = present * 16
    kpts = kickers.get(norm(name), {})
    past = _past_pts(hist, name)
    if past is None and kpts:
        past = kpts.get(2025, {}).get("total") or kpts.get(2024, {}).get("total")
    bval, brank = _board_value(board, name)
    # Keeper: board for prospects, future for proven
    age = rec.get("age")
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
        "blended": round(blended, 3),
        "depth_rank": rank_d,
        "role_note": role_note,
        "owner": rec.get("owner") or "",
        "rankings_as_of": rec.get("rankings_as_of") or "",
        "breakout": rec.get("breakout"),
    }


def suggest(
    roster: list[dict],
    fa: list[dict],
    *,
    board_weight: float = 0.35,
    board: dict | None = None,
    depth: dict | None = None,
    rankings_as_of: str = "",
    weekly_weight: float = 0.20,
) -> dict[str, Any]:
    board = board if board is not None else load_board()
    hist = load_history()
    kickers = load_kickers()
    mine = [r for r in roster if (r.get("owner") or "") == MY_TEAM]
    if not mine:
        mine = list(roster)
    counts = {}
    for p in mine:
        counts[(p.get("pos") or "").upper()] = counts.get((p.get("pos") or "").upper(), 0) + 1

    scored_mine = [
        evaluate_player(
            {**p, "rankings_as_of": rankings_as_of},
            board=board,
            hist=hist,
            kickers=kickers,
            board_weight=board_weight,
            depth=depth,
            weekly_weight=weekly_weight,
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
            weekly_weight=weekly_weight,
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

    drops = sorted([s for s in scored_mine if droppable(s)], key=lambda x: (x["blended"], x["future"], x["keeper"]))
    adds = sorted(scored_fa, key=lambda x: -x["blended"])

    recs = []
    used_fa = set()
    used_drop = set()
    for add in adds[:25]:
        pos = add["pos"]
        if counts.get(pos, 0) >= CAPS.get(pos, 99):
            # need a same-pos drop
            same = [d for d in drops if d["pos"] == pos and d["player"] not in used_drop]
            if not same:
                continue
            drop = same[0]
        else:
            drop = drops[0] if drops else None
            if drop and drop["pos"] != pos and counts.get(pos, 0) >= CAPS.get(pos, 99):
                continue
        if not drop:
            continue
        if add["blended"] <= drop["blended"] + 0.05:
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
                "reason": cap_note
                or _reason(add, drop, board_weight, weekly_weight),
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
        "caps": CAPS,
        "active_max": {"QB": 1, "RB": 4, "WR": 4, "TE": 2, "K": 1, "DST": 1},
        "recommendations": recs,
        "roster_scored": scored_mine,
        "fa_top": adds[:40],
    }
