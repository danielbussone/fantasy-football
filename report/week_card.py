"""Week report card: grades vs lock, start/sit hindsight, prior-move tags. Does not write the sim."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from cbs_client import MY_TEAM, norm
from scoring.actuals import line_has_box, row_to_actuals, score_actual_line

ROOT = Path(__file__).resolve().parents[1]

FORMAT_NOTE = (
    "Actual points are CBS's own league-scoring total (exact TD/FG distance, 2-pt conversions "
    "included); yards/PA/sacks/XP rows below it are this app's own breakdown of that same score. "
    "Looking ahead is locked Exp (mean) vs now after Refresh — the report does not write the prior."
)
BENCH_SLOTS = frozenset({"", "bench", "injured", "ir", "reserve", "out", "o", "n/a", "n/r"})


def week_stats_path(week: int) -> Path:
    return ROOT / f"cbs_stats_week{int(week)}.csv"


def cbs_started(slot: str | None) -> bool:
    return (slot or "").strip().lower() not in BENCH_SLOTS


def _fmt(n) -> str:
    if n is None:
        return "—"
    try:
        x = float(n)
    except (TypeError, ValueError):
        return str(n)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _delta(n: float) -> str:
    return f"+{_fmt(n)}" if n > 0 else _fmt(n)


def band_hit(actual: float, proj: dict) -> str:
    p25 = float(proj.get("p25") or 0)
    p75 = float(proj.get("p75") or 0)
    if actual < p25:
        return "bust"
    if actual > p75:
        return "boom"
    return "typical"


def locked_roster_keys(snap: dict) -> set[str]:
    lu = snap.get("lineup_p50") or {}
    names = []
    for p in list(lu.get("starters") or []) + list(lu.get("bench") or []):
        if p.get("player"):
            names.append(norm(p["player"]))
    if names:
        return set(names)
    return set(snap.get("players") or {})


def _actuals_from_csv(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    for r in csv.DictReader(path.open(encoding="utf-8")):
        name = r.get("player") or ""
        if not name:
            continue
        line = row_to_actuals(r)
        if not line_has_box(line):
            continue
        scored = score_actual_line(line.get("pos") or r.get("pos") or "", line)
        out[norm(name)] = {
            "player": name,
            "pos": line.get("pos") or r.get("pos") or "",
            "pts": scored["pts"],
            "why": scored["why"],
            "explain": scored["explain"],
        }
    return out


def load_week_actuals(week: int) -> dict[str, dict]:
    out = _actuals_from_csv(week_stats_path(week))
    if out:
        return out
    # CBS `week1` tables are names with empty stats; 3g is the one played game in week 1.
    if int(week) == 1:
        return _actuals_from_csv(ROOT / "cbs_stats_3g.csv")
    return {}


def _desig(inj: dict | None) -> str:
    if not inj:
        return ""
    if inj.get("out"):
        d = inj.get("designation") or "Out"
        return d
    return inj.get("designation") or ""


def _short_desig(d: str) -> str:
    d = (d or "").strip()
    if not d:
        return "healthy"
    low = d.lower()
    if low in {"out", "ir", "injured", "pup"}:
        return "Out" if low != "ir" else "IR"
    if "question" in low:
        return "Q"
    if "doubt" in low:
        return "D"
    if "probab" in low:
        return "P"
    return d


def _vol_note(lu: dict, nu: dict, flipped: bool) -> str:
    parts = []
    for key, label in (("targets", "targets"), ("carries", "carries"), ("pass_att", "pass att")):
        a, b = lu.get(key), nu.get(key)
        if a == b:
            continue
        if a is None and b is None:
            continue
        parts.append(f"{label} {_fmt(a)} → {_fmt(b)}")
    tail = " (3g now in the mix)" if flipped else ""
    if parts:
        return ", ".join(parts) + tail
    if flipped:
        return "3g now in the mix"
    return "3g usage moved"


def outlook_row(
    locked: dict,
    now: dict,
    *,
    week_now: int,
    week_lock: int,
    mix_now,
    mix_lock,
) -> dict[str, Any]:
    drivers: list[str] = []
    notes: list[str] = []
    lu = (locked.get("proj") or {}).get("usage") or {}
    nu = (now.get("proj") or {}).get("usage") or {}
    g3_flip = bool(lu.get("has_3g")) != bool(nu.get("has_3g"))
    g3_vol = lu.get("g3_targets") != nu.get("g3_targets") or lu.get("g3_carries") != nu.get("g3_carries")
    usage_vol = lu.get("targets") != nu.get("targets") or lu.get("carries") != nu.get("carries") or lu.get("pass_att") != nu.get("pass_att")
    if g3_flip or g3_vol or (usage_vol and (lu.get("has_3g") or nu.get("has_3g"))):
        drivers.append("3g")
        notes.append(_vol_note(lu, nu, flipped=bool(nu.get("has_3g") and not lu.get("has_3g"))))

    ld, nd = _desig(locked.get("injury")), _desig(now.get("injury"))
    if (ld or "").lower() != (nd or "").lower():
        drivers.append("Injury")
        extra = ""
        now_out = bool((now.get("injury") or {}).get("out")) or "out" in (nd or "").lower() or (nd or "").lower() == "ir"
        if now_out:
            extra = "; snaps 0 next week"
        notes.append(f"{_short_desig(ld)} → {_short_desig(nd)}{extra}")

    lr, nr = locked.get("depth_rank"), now.get("depth_rank")
    lrole, nrole = locked.get("role_note") or "", now.get("role_note") or ""
    if lr != nr or lrole != nrole:
        drivers.append("Depth")
        left = lrole or (f"rank {lr}" if lr not in (None, "") else "—")
        right = nrole or (f"rank {nr}" if nr not in (None, "") else "—")
        notes.append(f"{left} → {right}")

    espn_notes = []
    if (locked.get("espn_line") or "") != (now.get("espn_line") or ""):
        espn_notes.append("ESPN week stat line changed")
    if mix_now != mix_lock and mix_now is not None and mix_lock is not None:
        espn_notes.append(f"mix {mix_lock} → {mix_now}")
    if int(week_now) != int(week_lock):
        espn_notes.append("new week ESPN line (not 3g)")
    if espn_notes:
        drivers.append("ESPN")
        notes.extend(espn_notes)

    # "Expected" (mean), not P50: variance is free in this format, so the
    # week-over-week delta that matters is the average moving, not the median.
    locked_exp = float((locked.get("proj") or {}).get("mean") or 0)
    now_exp = float((now.get("proj") or {}).get("mean") or 0)
    return {
        "player": now.get("player") or locked.get("player"),
        "pos": now.get("pos") or locked.get("pos"),
        "locked_exp": round(locked_exp, 2),
        "now_exp": round(now_exp, 2),
        "delta": round(now_exp - locked_exp, 2),
        "drivers": drivers,
        "note": "; ".join(n for n in notes if n),
    }


def grade_rows(snap: dict, actuals: dict[str, dict]) -> list[dict]:
    rec_set = {norm(p.get("player") or "") for p in (snap.get("lineup_p50") or {}).get("starters") or []}
    roster = locked_roster_keys(snap)
    grades = []
    for key, p in (snap.get("players") or {}).items():
        if roster and key not in roster:
            continue
        hit = actuals.get(key)
        if hit is None:
            continue
        proj = p.get("proj") or {}
        actual = float(hit.get("pts") or 0)
        # Graded against the mean (expected points), not P50: this format
        # has no head-to-head to protect a median in, only a season total to
        # maximize. band_hit still uses P25/P75 — that's about how typical
        # the actual game was relative to the distribution's shape, a
        # different question from which point estimate to grade against.
        exp = float(proj.get("mean") or 0)
        grades.append(
            {
                "player": p.get("player"),
                "pos": p.get("pos"),
                "slot": p.get("slot") or "",
                "rec": key in rec_set,
                "actual": round(actual, 2),
                "exp": round(exp, 2),
                "band": band_hit(actual, proj),
                "delta": round(actual - exp, 2),
                "why": hit.get("why") or "",
            }
        )
    grades.sort(key=lambda g: -abs(g["delta"]))
    return grades


def highlights(grades: list[dict], n: int = 4) -> tuple[list[dict], list[dict]]:
    def pack(g):
        return {
            "player": g["player"],
            "pos": g["pos"],
            "actual": g["actual"],
            "exp": g["exp"],
            "why": g.get("why") or "",
        }

    right = [pack(g) for g in grades if g["delta"] > 0][:n]
    wrong = [pack(g) for g in grades if g["delta"] < 0][:n]
    return right, wrong


def sit_misses(snap: dict, actuals: dict[str, dict]) -> list[dict]:
    roster = locked_roster_keys(snap)
    players = [p for p in (snap.get("players") or {}).values() if not roster or norm(p.get("player") or "") in roster]
    rec_set = {norm(p.get("player") or "") for p in (snap.get("lineup_p50") or {}).get("starters") or []}
    by_pos: dict[str, list] = {}
    for p in players:
        pos = p.get("pos") or ""
        if pos:
            by_pos.setdefault(pos, []).append(p)
    misses = []
    seen = set()
    for pos, group in by_pos.items():
        started = [p for p in group if cbs_started(p.get("slot"))]
        sat = [p for p in group if not cbs_started(p.get("slot"))]
        for st in started:
            sk = norm(st.get("player") or "")
            if sk not in actuals:
                continue
            st_pts = float(actuals[sk]["pts"])
            better = []
            for b in sat:
                bk = norm(b.get("player") or "")
                if bk not in actuals:
                    continue
                bp = float(actuals[bk]["pts"])
                if bp > st_pts + 0.05:
                    better.append((b, bp))
            if not better:
                continue
            best, bp = max(better, key=lambda x: x[1])
            bits = []
            rec_st = sk in rec_set
            rec_b = norm(best.get("player") or "") in rec_set
            if rec_st and rec_b:
                bits.append("Rec had both in play.")
            elif rec_st:
                bits.append("Rec had the starter in; CBS slot matched.")
            elif rec_b:
                bits.append("Rec sat the starter.")
            else:
                bits.append("Neither was the rec start.")
            pair = (st.get("player"), best.get("player"))
            seen.add(tuple(sorted(pair)))
            misses.append(
                {
                    "started": st.get("player"),
                    "sat": best.get("player"),
                    "started_actual": round(st_pts, 2),
                    "sat_actual": round(bp, 2),
                    "text": (
                        f"Started {st.get('player')} ({_fmt(st_pts)}) over {best.get('player')} ({_fmt(bp)}). "
                        + " ".join(bits)
                        + f" {_delta(bp - st_pts)} left on the bench."
                    ),
                }
            )
    for w in (snap.get("lineup_p50") or {}).get("why") or []:
        if w.get("kind") != "close":
            continue
        label = w.get("player") or ""
        if " vs " in label:
            a, b = label.split(" vs ", 1)
            key = tuple(sorted((a.strip(), b.strip())))
            if key in seen:
                continue
            sa = actuals.get(norm(a))
            sb = actuals.get(norm(b))
            if not sa or not sb:
                continue
            misses.append(
                {
                    "started": a.strip(),
                    "sat": b.strip(),
                    "started_actual": round(float(sa.get("pts") or 0), 2),
                    "sat_actual": round(float(sb.get("pts") or 0), 2),
                    "text": f"{w.get('text') or 'Close call at lock.'}",
                }
            )
        else:
            misses.append(
                {
                    "started": label,
                    "sat": "",
                    "started_actual": 0,
                    "sat_actual": 0,
                    "text": w.get("text") or "",
                }
            )
    return misses


def looking_ahead(snap: dict, now: dict) -> tuple[list[dict], str]:
    now_by = {norm(p.get("player") or ""): p for p in list(now.get("roster") or []) + list(now.get("fa_sample") or [])}
    roster_keys = {norm(p.get("player") or "") for p in now.get("roster") or []}
    week_now = int(now.get("week") or snap.get("week") or 1)
    week_lock = int(snap.get("week") or week_now)
    mix_now = now.get("espn_mix")
    mix_lock = snap.get("mix")
    mix_now_l = now.get("espn_mix_label") or mix_now
    mix_lock_l = snap.get("mix_label") or mix_lock
    rows = []
    for key, locked in (snap.get("players") or {}).items():
        cur = now_by.get(key)
        if not cur:
            continue
        row = outlook_row(
            locked,
            cur,
            week_now=week_now,
            week_lock=week_lock,
            mix_now=mix_now_l,
            mix_lock=mix_lock_l,
        )
        if key not in roster_keys and not row["drivers"]:
            continue
        rows.append(row)
    rows.sort(key=lambda r: (-len(r["drivers"]), -abs(r["delta"])))
    empty = ""
    has_3g = bool((now.get("data_flags") or {}).get("has_3g_usage"))
    if not any(r["drivers"] for r in rows) and not has_3g:
        empty = "Refresh CBS so 3g / injuries / depth can move the prior."
    return rows, empty


def action_items(now: dict, grades: list[dict]) -> list[dict]:
    waivers = now.get("waivers") or {}
    recs = [dict(r) for r in waivers.get("recommendations") or []]
    busts = {g["player"]: g for g in grades if g.get("band") == "bust"}
    used_drop = {r["drop"]["player"] for r in recs if r.get("drop")}
    used_add = {r["add"]["player"] for r in recs if r.get("add")}
    for r in recs:
        drop = r.get("drop") or {}
        g = busts.get(drop.get("player"))
        if g:
            r["reason"] = (
                f"{r.get('reason') or ''} Bust this week ({_fmt(g['actual'])} vs Exp {_fmt(g['exp'])})."
            ).strip()
    scored = list(waivers.get("roster_scored") or [])
    fa_top = list(waivers.get("fa_top") or [])
    if scored:
        mid = sorted(float(s.get("blended") or 0) for s in scored)
        weak_cut = mid[len(mid) // 2] if mid else 0
    else:
        weak_cut = 0
    for s in scored:
        name = s.get("player")
        g = busts.get(name)
        if not g or name in used_drop:
            continue
        if float(s.get("blended") or 0) > weak_cut:
            continue
        pos = s.get("pos")
        adds = [a for a in fa_top if a.get("pos") == pos and a.get("player") not in used_add]
        if not adds:
            continue
        add = adds[0]
        if float(add.get("blended") or 0) <= float(s.get("blended") or 0) + 0.05:
            continue
        recs.append(
            {
                "add": add,
                "drop": s,
                "reason": (
                    f"Bust this week ({_fmt(g['actual'])} vs Exp {_fmt(g['exp'])}) "
                    f"and weak blended ({_fmt(s.get('blended'))})."
                ),
            }
        )
        used_drop.add(name)
        used_add.add(add["player"])
    return recs[:8]


def locked_lineup_rows(snap: dict) -> list[dict]:
    roster = locked_roster_keys(snap)
    out = []
    for p in (snap.get("players") or {}).values():
        if roster and norm(p.get("player") or "") not in roster:
            continue
        inj = p.get("injury") or {}
        out.append(
            {
                "player": p.get("player"),
                "pos": p.get("pos"),
                "slot": p.get("slot") or "Bench",
                "rec": False,
                "designation": _desig(inj) or "healthy",
            }
        )
    rec_set = {norm(p.get("player") or "") for p in (snap.get("lineup_p50") or {}).get("starters") or []}
    for row in out:
        row["rec"] = norm(row.get("player") or "") in rec_set
    order = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "K": 4, "DST": 5}
    out.sort(key=lambda r: (order.get(r.get("pos") or "", 9), 0 if cbs_started(r.get("slot")) else 1, r.get("player") or ""))
    return out


def _base_card(week: int, **extra) -> dict[str, Any]:
    card = {
        "mock": False,
        "week": int(week),
        "team": MY_TEAM,
        "mix_label": "",
        "banner": "",
        "format_note": FORMAT_NOTE,
        "status": "ready",
        "went_right": [],
        "went_wrong": [],
        "grades": [],
        "sit_misses": [],
        "outlook": [],
        "outlook_note": "",
        "actions": [],
        "locked_lineup": [],
        "pending": [],
        "tracking": None,
        "grades_note": "Actual GBFL vs locked Exp (mean). Bust < P25 · typical P25–P75 · boom > P75.",
    }
    card.update(extra)
    return card


def _tracking(week: int, mock: bool) -> dict | None:
    """Season scorecard for the usage metrics; never lets a tracking problem break the report."""
    if mock:
        return None
    try:
        from report.tracking import tracking

        return tracking(week)
    except Exception:
        return None


def build_report(
    week: int = 1,
    *,
    board_weight: float = 0.35,
    espn_mix: float = 0.5,
    mock: bool = False,
    allow_injured: bool = False,
    snap: dict | None = None,
    now: dict | None = None,
    actuals: dict | None = None,
) -> dict[str, Any]:
    from report.snapshot import load_snapshot

    week = int(week)
    if snap is None:
        snap = load_snapshot(week, mock=mock)
    mix_label = (snap or {}).get("mix_label") or ""
    track = _tracking(week, mock)
    if not snap:
        return _base_card(
            week,
            mix_label=mix_label,
            mock=bool(mock),
            tracking=track,
            status="no_lock",
            banner=f"Lock week {week} before kickoff (or after, knowing it is stale).",
        )
    if now is None:
        from app.assemble import week_for_report

        now = week_for_report(
            week,
            board_weight=board_weight,
            mock=mock,
            espn_mix=espn_mix,
            allow_injured=allow_injured,
        )
    if actuals is None:
        actuals = load_week_actuals(week)

    mix_label = snap.get("mix_label") or (now or {}).get("espn_mix_label") or mix_label

    outlook, outlook_note = looking_ahead(snap, now or {})
    actions = action_items(now or {}, [])
    locked_lineup = locked_lineup_rows(snap)
    if not actuals:
        return _base_card(
            week,
            mix_label=snap.get("mix_label") or mix_label,
            mock=bool(mock),
            tracking=track,
            status="no_actuals",
            banner="Snapshot only — Refresh CBS to pull week-N box scores.",
            outlook=outlook,
            outlook_note=outlook_note,
            actions=actions,
            locked_lineup=locked_lineup,
        )

    grades = grade_rows(snap, actuals)
    right, wrong = highlights(grades)
    misses = sit_misses(snap, actuals)
    actions = action_items(now or {}, grades)
    roster = locked_roster_keys(snap)
    pending = []
    for key in roster:
        if key in actuals:
            continue
        p = (snap.get("players") or {}).get(key)
        if p and p.get("player"):
            pending.append(p["player"])
    banner = "Approximate GBFL — yards/PA/XP/sacks exact; TD/FG distances averaged, not play-by-play."
    if pending:
        shown = ", ".join(pending[:8])
        extra = "…" if len(pending) > 8 else ""
        banner += f" No box yet (MNF / DNP): {shown}{extra}."
    return _base_card(
        week,
        mix_label=snap.get("mix_label") or mix_label,
        mock=bool(mock),
        tracking=track,
        status="ready",
        banner=banner,
        went_right=right,
        went_wrong=wrong,
        grades=grades,
        sit_misses=misses,
        outlook=outlook,
        outlook_note=outlook_note,
        actions=actions,
        locked_lineup=locked_lineup,
        pending=pending,
    )
