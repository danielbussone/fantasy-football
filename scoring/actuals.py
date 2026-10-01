"""Score a week box score in GBFL.

CBS's own `Total` column (`Total_3` for DST) is this league's real score,
computed under this league's custom scoring settings on CBS's site — use it
as `pts` when present. Yards/PA/XP/sacks are still parsed and scored exactly
for the explain breakdown; only the TD/FG portion falls back to the sim's
distance mix EV when no CBS total is available (e.g. hand-built test lines).
"""
from __future__ import annotations

from typing import Any

from projections.weekly import (
    FG_DIST,
    PASS_TD_DIST,
    REC_TD_DIST,
    RUSH_TD_DIST,
    _yard_bucket_note,
)
from scoring.rules import (
    Game,
    def_td_points,
    extra_point_points,
    fg_points,
    pa_points,
    passing_td_points,
    receiving_td_points,
    rushing_td_points,
    score_game,
    yard_points,
)

# Same distances simulate_detail uses for DST TDs.
DEF_TD_DIST = [20.0, 35.0, 55.0, 80.0]


SKIP_BOX_KEYS = {
    "player",
    "team",
    "pos",
    "cbs_id",
    "Opp",
    "OVP",
    "Bye",
    "Rost",
    "Start",
    "Expert",
    "owner",
    "slot",
    "key",
    "status",
    "Avg",
    "Avg_2",
    "Avg_3",
}


def row_has_box_stats(row: dict) -> bool:
    """True if a CBS stats row has any real box-score number (not just a name/opp)."""
    for k, v in (row or {}).items():
        if k in SKIP_BOX_KEYS:
            continue
        if v in (None, "", "-", "N/R", "—"):
            continue
        try:
            if abs(float(str(v).replace(",", ""))) > 0:
                return True
        except ValueError:
            continue
    return False


def line_has_box(line: dict | None) -> bool:
    """False for DNP / not-yet-played (MNF) / empty CBS week tables."""
    src = line or {}
    pos = (src.get("pos") or "").upper()
    if pos == "K":
        return int(src.get("fg") or 0) + int(src.get("xp") or 0) > 0
    if pos == "DST":
        pa = src.get("pa")
        try:
            pa_n = None if pa in (None, "") else float(pa)
        except (TypeError, ValueError):
            pa_n = None
        stuff = float(src.get("sacks") or 0) + float(src.get("ints") or 0) + float(src.get("fr") or 0) + int(src.get("def_td") or 0)
        return (pa_n is not None and pa_n > 0) or stuff > 0
    return (
        float(src.get("pass_yds") or 0)
        + float(src.get("rush_yds") or 0)
        + float(src.get("rec_yds") or 0)
        + int(src.get("pass_td") or 0)
        + int(src.get("rush_td") or 0)
        + int(src.get("rec_td") or 0)
        + int(src.get("tar") or 0)
        + int(src.get("rec") or 0)
    ) > 0


def mix_ev(dist: list[float], fn) -> float:
    if not dist:
        return 0.0
    return sum(fn(d) for d in dist) / len(dist)


def _num(row: dict, *keys: str) -> float | None:
    for k in keys:
        v = row.get(k)
        if v in (None, "", "-", "N/R", "—"):
            continue
        try:
            return float(str(v).replace(",", ""))
        except ValueError:
            continue
    return None


def _count(row: dict, *keys: str) -> int:
    v = _num(row, *keys)
    if v is None:
        return 0
    return max(0, int(round(v)))


def row_to_actuals(row: dict) -> dict[str, Any]:
    """Map one CBS week-N stats row (parse_stats_players / CSV) into a box-score dict.

    `cbs_total` (CBS's own `Total` column, `Total_3` for DST) is this
    league's real scoreboard, computed by CBS under this league's custom
    scoring settings — it already includes 2-pt conversions and exact TD/FG
    distance that this repo's own column-by-column parsing can't see.
    `score_actual_line` prefers it as the final `pts` when present.
    """
    pos = (row.get("pos") or "WR").upper()
    player = row.get("player") or ""
    base: dict[str, Any] = {"player": player, "pos": pos, "team": row.get("team") or ""}
    if pos == "QB":
        return {
            **base,
            "pass_yds": _num(row, "Pass Yds", "Passing Yds", "Yds") or 0.0,
            "rush_yds": _num(row, "Rush Yds", "Rushing Yds", "Yds_2") or 0.0,
            "rec_yds": 0.0,
            "pass_td": _count(row, "Pass TD", "PaTD", "TD"),
            "rush_td": _count(row, "Rush TD", "RuTD", "TD_2"),
            "rec_td": 0,
            "int": _count(row, "Int", "INT"),
            "cbs_total": _num(row, "Total"),
        }
    if pos == "K":
        fg = _count(row, "FG", "FGM")
        if fg == 0:
            fg = sum(_count(row, k) for k in ("FG_2", "FG_3", "FG_4", "FG_5", "FG_6"))
        return {**base, "fg": fg, "xp": _count(row, "XP", "XPM"), "cbs_total": _num(row, "Total")}
    if pos == "DST":
        return {
            **base,
            "sacks": _num(row, "SACK", "Sack", "Sacks") or 0.0,
            "ints": _num(row, "INT", "Int") or 0.0,
            "fr": _num(row, "Fum", "FR", "Fumble Rec") or 0.0,
            "safeties": _count(row, "STY", "Sfty", "Safety"),
            # CBS's own PA column is Total_2 for this position pool; the
            # named fallbacks are for other/older row shapes.
            "pa": _num(row, "Total_2", "Pts Ag", "PA", "Pts Allowed", "Pts Agst", "Pts"),
            "def_td": _count(row, "DTD", "Def TD", "TD"),
            "cbs_total": _num(row, "Total_3", "Total"),
        }
    if pos == "RB":
        rush_yds = _num(row, "Rush Yds", "Rushing Yds", "Yds") or 0.0
        rec_yds = _num(row, "Rec Yds", "Receiving Yds", "Yds_2") or 0.0
        rush_td = _count(row, "Rush TD", "RuTD", "TD")
        rec_td = _count(row, "Rec TD", "ReTD", "TD_2")
    else:
        rec_yds = _num(row, "Rec Yds", "Receiving Yds", "Yds") or 0.0
        rush_yds = _num(row, "Rush Yds", "Rushing Yds", "Yds_2") or 0.0
        rec_td = _count(row, "Rec TD", "ReTD", "TD")
        rush_td = _count(row, "Rush TD", "RuTD", "TD_2")
    return {
        **base,
        "pass_yds": 0.0,
        "rush_yds": rush_yds,
        "rec_yds": rec_yds,
        "pass_td": 0,
        "rush_td": rush_td,
        "rec_td": rec_td,
        "rec": _count(row, "Rec", "Receptions"),
        "tar": _count(row, "Tar", "Targets"),
        "cbs_total": _num(row, "Total"),
    }


def score_actual_line(pos: str, line: dict[str, Any] | None = None, **stats) -> dict[str, Any]:
    """GBFL points from a box score. TD/FG distances are mix EV, not play-by-play."""
    pos = (pos or "").upper()
    src = dict(line or {})
    src.update(stats)
    rows: list[dict[str, Any]] = []
    bits: list[str] = []
    pts = 0.0

    def add(cat: str, input_s: str, val: float, note: str = "", why: str | None = None):
        nonlocal pts
        val = round(float(val), 4)
        pts += val
        rows.append({"cat": cat, "input": input_s, "pts": round(val, 2), "note": note})
        if why:
            bits.append(why)

    if pos == "QB":
        py = float(src.get("pass_yds") or 0)
        ry = float(src.get("rush_yds") or 0)
        y = py + ry
        yp = yard_points(pos, y)
        note = _yard_bucket_note(pos, y)
        add("Pass+rush yards", f"{y:.0f}", yp, note, f"{py:.0f} pass + {ry:.0f} ru → {note} = {yp:g}")
        ptd = int(src.get("pass_td") or 0)
        rtd = int(src.get("rush_td") or 0)
        p_ev = mix_ev(PASS_TD_DIST, passing_td_points)
        r_ev = mix_ev(RUSH_TD_DIST, rushing_td_points)
        if ptd:
            add("Pass TDs", str(ptd), ptd * p_ev, "distance mix EV", f"{ptd} pass TD at mix EV")
        if rtd:
            add("Rush TDs", str(rtd), rtd * r_ev, "distance mix EV", f"{rtd} rush TD at mix EV")
        g = Game(pos="QB", pass_yds=py, rush_yds=ry)
        assert abs(score_game(g) - yp) < 1e-9
    elif pos in {"RB", "WR", "TE"}:
        ry = float(src.get("rush_yds") or 0)
        recy = float(src.get("rec_yds") or 0)
        y = ry + recy
        yp = yard_points(pos, y)
        note = _yard_bucket_note(pos, y)
        label = f"{recy:.0f} rec yds" if recy >= ry else f"{y:.0f} scrim"
        add("Scrimmage yards", f"{y:.0f}", yp, note, f"{label} → {note} = {yp:g}")
        rec_td = int(src.get("rec_td") or 0)
        rush_td = int(src.get("rush_td") or 0)
        rec_ev = mix_ev(REC_TD_DIST, lambda d: receiving_td_points(d, pos))
        ru_ev = mix_ev(RUSH_TD_DIST, rushing_td_points)
        if rec_td:
            add("Rec TDs", str(rec_td), rec_td * rec_ev, "distance mix EV", f"{rec_td} rec TD at mix EV")
        if rush_td:
            add("Rush TDs", str(rush_td), rush_td * ru_ev, "distance mix EV", f"{rush_td} rush TD at mix EV")
        g = Game(pos=pos, rush_yds=ry, rec_yds=recy)
        assert abs(score_game(g) - yp) < 1e-9
    elif pos == "K":
        fg_n = int(src.get("fg") or 0)
        xp = int(src.get("xp") or 0)
        fg_ev = mix_ev(FG_DIST, fg_points)
        if fg_n:
            add("FG", str(fg_n), fg_n * fg_ev, "distance mix EV", f"{fg_n} FG at mix EV")
        else:
            bits.append("0 FG")
        xp_pts = extra_point_points(xp)
        add("XP", str(xp), xp_pts, "0.5 each", f"{xp} XP at 0.5")
        g = Game(pos="K", xp=xp)
        assert abs(score_game(g) - xp_pts) < 1e-9
    elif pos == "DST":
        pa_raw = src.get("pa")
        pa = 0
        pa_pts = 0.0
        if pa_raw not in (None, ""):
            pa = int(round(float(pa_raw)))
            pa_pts = pa_points(pa)
            add("PA", str(pa), pa_pts, "PA table", f"PA {pa} → {pa_pts:g}")
        sacks = float(src.get("sacks") or 0)
        ints = float(src.get("ints") or 0)
        fr = float(src.get("fr") or src.get("fumbles_recovered") or 0)
        turn_pts = 0.5 * (sacks + ints + fr)
        add("Sacks/INT/FR", f"{sacks:g}/{ints:g}/{fr:g}", turn_pts, "0.5 each")
        if sacks:
            bits.append(f"{sacks:g} sacks at 0.5")
        if ints:
            bits.append(f"{ints:g} INT at 0.5")
        if fr:
            bits.append(f"{fr:g} FR at 0.5")
        sty = int(src.get("safeties") or 0)
        if sty:
            add("Safeties", str(sty), 3.0 * sty, "3 each", f"{sty} safety")
        n_td = int(src.get("def_td") or 0)
        if n_td:
            td_ev = mix_ev(DEF_TD_DIST, def_td_points)
            add("Def TDs", str(n_td), n_td * td_ev, "distance mix EV", f"{n_td} def TD at mix EV")
        g = Game(
            pos="DST",
            sacks=sacks,
            ints=ints,
            fumbles_recovered=fr,
            safeties=sty,
            points_against=pa if pa_raw not in (None, "") else 22,
        )
        assert abs(score_game(g) - (pa_pts + turn_pts + 3.0 * sty)) < 1e-6
    else:
        return {"pts": 0.0, "explain": {"rows": [], "lines": [], "approx_pts": 0.0}, "why": "", "stats": src}

    cbs_total = src.get("cbs_total")
    if cbs_total not in (None, ""):
        # Swap the mix-EV TD/FG guesses for CBS's own exact total. It also
        # picks up 2-pt conversions and other events this parser doesn't
        # track column-by-column.
        mix_rows = [r for r in rows if r["note"] == "distance mix EV"]
        mix_pts = sum(r["pts"] for r in mix_rows)
        certain_pts = pts - mix_pts
        exact = round(float(cbs_total) - certain_pts, 2)
        rows = [r for r in rows if r["note"] != "distance mix EV"]
        bits = [b for b in bits if "at mix EV" not in b]
        if mix_rows or abs(exact) > 1e-6:
            label = " + ".join(r["cat"] for r in mix_rows) if mix_rows else "TD/FG"
            rows.append({"cat": f"{label} (CBS exact)", "input": "", "pts": exact, "note": "CBS league scoring"})
            bits.append(f"{label} at CBS exact ({exact:g})" if mix_rows else f"CBS-only adjustment {exact:g}")
        pts = certain_pts + exact

    tot = round(pts, 2)
    why = "; ".join(bits) if bits else f"{tot:g} GBFL"
    return {
        "pts": tot,
        "explain": {"rows": rows, "lines": [why], "approx_pts": tot},
        "why": why,
        "stats": src,
    }
