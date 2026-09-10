"""Season-grain bounds: naive mean-game + TD base/max vs reported FPTS."""
from __future__ import annotations

import csv
from pathlib import Path

from scoring.rules import qb_yard_points, rb_wr_yard_points, te_yard_points

ROOT = Path(__file__).resolve().parents[1]
TD_MIN, TD_MAX = 1.0, 5.0


def _yds_fn(pos: str):
    if pos == "QB":
        return qb_yard_points
    if pos == "TE":
        return te_yard_points
    return rb_wr_yard_points


def test_history_totals_near_naive_plus_td_distance():
    """Reported FPTS should sit above naive (mean-game + 1/TD) for most full seasons.

    Weekly yardage path and TD distance are unobserved, so we do not require an
    exact match. We require the leftover is not wildly negative (which would
    mean the written rules overstate scoring).
    """
    misses = []
    n = 0
    for season in (2023, 2024, 2025):
        path = ROOT / f"history_{season}.csv"
        if not path.exists():
            continue
        for r in csv.DictReader(path.open(encoding="utf-8")):
            total = float(r["total"])
            avg = float(r["avg"] or 0)
            games = round(total / avg) if avg else 0
            if games < 8:
                continue
            pos = r["pos"]
            pass_yds = int(r["pass_yds"])
            rush_yds = int(r["rush_yds"])
            rec_yds = int(r["rec_yds"])
            tds = int(r["pass_td"]) + int(r["rush_td"]) + int(r["rec_td"])
            if pos == "QB":
                yds = pass_yds + rush_yds
                tds = int(r["pass_td"]) + int(r["rush_td"])
            else:
                yds = rush_yds + rec_yds
            ypg = yds / games
            naive = games * _yds_fn(pos)(ypg) + TD_MIN * tds
            n += 1
            # Allow a little rounding; a large negative leftover would mean
            # our buckets are too generous vs the league's reported totals.
            if total + 8 < naive:
                misses.append((season, r["player"], naive, total))
    assert n > 50
    assert len(misses) <= max(3, n // 20), misses[:8]


def test_kicker_totals_match_xp_plus_fg_bounds():
    """XP = 0.5; each FG is 1–3.5. Totals must sit in [xp*0.5 + 1*FG, xp*0.5 + 3.5*FG]."""
    for season in (2023, 2024, 2025):
        path = ROOT / f"kicker_{season}.csv"
        if not path.exists():
            continue
        for r in csv.DictReader(path.open(encoding="utf-8")):
            fg = int(r["fg"])
            xp = int(r["xp"])
            total = float(r["total"])
            lo = xp * 0.5 + fg * 1.0
            hi = xp * 0.5 + fg * 3.5
            assert lo - 0.01 <= total <= hi + 0.01, (r["player"], season, total, lo, hi)
