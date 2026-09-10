"""Recover the yards/TD/reception exchange rate from 2025 results, per position."""
import csv
from collections import defaultdict

import numpy as np

rows = list(csv.DictReader(open("history_2025.csv", encoding="utf-8")))
for r in rows:
    for k in ("pass_yds", "pass_td", "rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "total"):
        r[k] = int(r[k])
    r["avg"] = float(r["avg"])
    r["games"] = round(r["total"] / r["avg"])

by_pos = defaultdict(list)
for r in rows:
    by_pos[r["pos"]].append(r)

print("Per-game regression: points/game ~ scrimmage yds/game + TDs/game + receptions/game")
print("(a reception coefficient near zero confirms catches are worth nothing)\n")
print(f"{'pos':4} {'n':>3} {'yds/pt':>8} {'pts per TD':>11} {'pts per rec':>12} {'base/gm':>8} {'R^2':>6} {'TD worth (yds)':>15}")
for p in ("RB", "WR", "TE"):
    grp = [r for r in by_pos[p] if r["games"] >= 8]
    g = np.array([r["games"] for r in grp], float)
    X = np.column_stack([
        (np.array([r["rush_yds"] + r["rec_yds"] for r in grp], float)) / g,
        (np.array([r["rush_td"] + r["rec_td"] for r in grp], float)) / g,
        (np.array([r["rec"] for r in grp], float)) / g,
    ])
    y = np.array([r["avg"] for r in grp], float)
    coef, *_ = np.linalg.lstsq(np.column_stack([X, np.ones(len(y))]), y, rcond=None)
    pred = np.column_stack([X, np.ones(len(y))]) @ coef
    r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    yds_per_pt = 1 / coef[0] if coef[0] else float("nan")
    print(f"{p:4} {len(grp):>3} {yds_per_pt:>8.1f} {coef[1]:>11.2f} {coef[2]:>12.3f} {coef[3]:>8.2f} {r2:>6.3f} "
          f"{coef[1] * yds_per_pt:>15.0f}")

grp = [r for r in by_pos["QB"] if r["games"] >= 8]
g = np.array([r["games"] for r in grp], float)
X = np.column_stack([
    np.array([r["pass_yds"] + r["rush_yds"] for r in grp], float) / g,
    np.array([r["pass_td"] for r in grp], float) / g,
    np.array([r["rush_td"] for r in grp], float) / g,
])
y = np.array([r["avg"] for r in grp], float)
coef, *_ = np.linalg.lstsq(np.column_stack([X, np.ones(len(y))]), y, rcond=None)
pred = np.column_stack([X, np.ones(len(y))]) @ coef
r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
print(f"\nQB   {len(grp):>3} {1/coef[0]:>8.1f} yds/pt   pass TD {coef[1]:.2f} pts   rush TD {coef[2]:.2f} pts   R^2 {r2:.3f}")
print(f"     a QB passing TD is worth {coef[1]/coef[0]:.0f} yards of offense")

print("\nShare of a player's points that come from touchdowns (per-position TD rate applied):")
td_val = {"RB": 1.2, "WR": 1.4, "TE": 2.2}
for p in ("RB", "WR", "TE"):
    grp = sorted([r for r in by_pos[p] if r["games"] >= 12], key=lambda r: -r["total"])
    print(f"\n  {p}: most and least TD-dependent (>=12 games)")
    scored = [((r["rush_td"] + r["rec_td"]) * td_val[p] / r["total"], r) for r in grp if r["total"]]
    scored.sort(key=lambda x: -x[0])
    for share, r in scored[:3] + scored[-3:]:
        yds = r["rush_yds"] + r["rec_yds"]
        print(f"    {r['player']:24} {yds:>5} yd {r['rush_td']+r['rec_td']:>2} TD -> {r['total']:>3} pts "
              f"({share*100:>4.0f}% from TDs)")
