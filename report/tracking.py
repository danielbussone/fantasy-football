"""Season-long scorecard for the usage metrics, built from the weekly lock snapshots.

Each lock records what the grades predicted (per-game points, flags, DST matchups);
once a week's box scores are in, this scores those predictions. Nothing here feeds
back into the sim or the grades. It exists so the two signals built on thin
samples (RB next man up, buy-low) get confirmed or dropped on 2026 data.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from cbs_client import norm
from report.snapshot import load_snapshot
from report.week_card import load_week_actuals


def _weeks_with_metrics(through: int) -> list[int]:
    out = []
    for w in range(1, int(through) + 1):
        snap = load_snapshot(w)
        if snap and snap.get("metrics"):
            out.append(w)
    return out


def _stat(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    return {"n": len(rows), "pred": fmean(r["pred"] for r in rows), "actual": fmean(r["actual"] for r in rows),
            "beat": fmean(r["actual"] - r["pred"] for r in rows),
            "hit_rate": sum(1 for r in rows if r["actual"] > r["pred"]) / len(rows)}


def tracking(through_week: int) -> dict:
    """Scorecard over every locked week up to `through_week` that has both a metrics block and box scores."""
    flag_rows: list[dict] = []
    par_err: dict[str, list[float]] = defaultdict(list)
    dst_weeks: list[dict] = []
    used: list[int] = []
    for w in _weeks_with_metrics(through_week):
        snap = load_snapshot(w)
        actuals = load_week_actuals(w)
        if not actuals:
            continue
        m = snap["metrics"]
        used.append(w)
        for key, g in m["grades"].items():
            a = actuals.get(key)
            if not a or g.get("par_ppg") is None:
                continue
            par_err[g["pos"]].append(float(a["pts"]) - float(g["par_ppg"]))
            for flag in g.get("flags") or []:
                flag_rows.append({"week": w, "flag": flag, "player": g["player"], "pos": g["pos"],
                                  "pred": float(g["par_ppg"]), "actual": float(a["pts"])})
        free = [d for d in m.get("dst") or [] if not d["mine"] and norm(d["player"]) in actuals]
        if len(free) >= 2:
            pick = max(free, key=lambda d: d["score"])
            dst_weeks.append({"week": w, "pick": pick["player"], "opp": pick["opp"], "opp_total": pick["opp_total"],
                              "pick_pts": float(actuals[norm(pick["player"])]["pts"]),
                              "avg_free_pts": fmean(float(actuals[norm(d["player"])]["pts"]) for d in free), "n_free": len(free)})
    return {
        "weeks": used,
        "next_up": _stat([r for r in flag_rows if r["flag"] == "next_up"]),
        "buy_low": _stat([r for r in flag_rows if r["flag"] == "buy_low"]),
        "flag_rows": sorted(flag_rows, key=lambda r: (-r["week"], r["flag"], r["player"]))[:20],
        "par": {pos: {"n": len(e), "mean_err": fmean(e), "mae": fmean(abs(x) for x in e)} for pos, e in sorted(par_err.items())},
        "dst": {
            "weeks": len(dst_weeks),
            "pick_pts": fmean(d["pick_pts"] for d in dst_weeks) if dst_weeks else None,
            "avg_free_pts": fmean(d["avg_free_pts"] for d in dst_weeks) if dst_weeks else None,
            "rows": sorted(dst_weeks, key=lambda d: -d["week"]),
        },
    }
