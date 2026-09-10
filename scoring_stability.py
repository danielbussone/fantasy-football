"""Do the scoring coefficients reproduce across 2023, 2024, 2025?"""
import csv
from collections import defaultdict

import numpy as np

SEASONS = (2023, 2024, 2025)


def load(season):
    rows = list(csv.DictReader(open(f"history_{season}.csv", encoding="utf-8")))
    for r in rows:
        for k in ("pass_yds", "pass_td", "rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "total"):
            r[k] = int(r[k])
        r["avg"] = float(r["avg"])
        r["games"] = round(r["total"] / r["avg"])
        r["scrim"] = r["rush_yds"] + r["rec_yds"]
        r["tds"] = r["rush_td"] + r["rec_td"]
    return rows


def fit(rows, cols, ycol="avg"):
    g = np.array([r["games"] for r in rows], float)
    X = np.column_stack([np.array([r[c] for r in rows], float) / g for c in cols] + [np.ones(len(rows))])
    y = np.array([r[ycol] for r in rows], float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return coef, r2


data = {s: load(s) for s in SEASONS}

print("=" * 84)
print("SCORING COEFFICIENTS BY SEASON  (fit on points/game vs stats/game, >=8 games)")
print("=" * 84)
print("Rule as written: RB/WR earn 1 pt per 20 scrimmage yds starting at 70; TE 1 per 20 starting at 40.")
print("TE receiving TDs use the short-distance rushing bands, so they should be worth much more.\n")
print(f"{'pos':4} {'season':>7} {'n':>3} {'yds/pt':>7} {'pts/TD':>7} {'pts/rec':>8} {'R^2':>6} {'TD in yds':>10}")
summary = defaultdict(list)
for p in ("RB", "WR", "TE"):
    for s in SEASONS:
        grp = [r for r in data[s] if r["pos"] == p and r["games"] >= 8]
        coef, r2 = fit(grp, ["scrim", "tds", "rec"])
        ypp = 1 / coef[0]
        summary[p].append((ypp, coef[1], coef[2]))
        print(f"{p:4} {s:>7} {len(grp):>3} {ypp:>7.1f} {coef[1]:>7.2f} {coef[2]:>8.3f} {r2:>6.3f} {coef[1]*ypp:>10.0f}")
    print()

for s in SEASONS:
    grp = [r for r in data[s] if r["pos"] == "QB" and r["games"] >= 8]
    for r in grp:
        r["qb_yds"] = r["pass_yds"] + r["rush_yds"]
    coef, r2 = fit(grp, ["qb_yds", "pass_td", "rush_td"])
    print(f"QB   {s:>7} {len(grp):>3} {1/coef[0]:>7.1f} pass TD {coef[1]:>5.2f}  rush TD {coef[2]:>5.2f}  R^2 {r2:.3f}")

print()
print("Three-year means:")
for p in ("RB", "WR", "TE"):
    y = np.mean([x[0] for x in summary[p]])
    t = np.mean([x[1] for x in summary[p]])
    rc = np.mean([x[2] for x in summary[p]])
    print(f"  {p}: {y:.1f} yds per point, {t:.2f} pts per TD, {rc:+.3f} pts per reception")
te_td = np.mean([x[1] for x in summary["TE"]])
wr_td = np.mean([x[1] for x in summary["WR"]])
print(f"\n  A tight end touchdown is worth {te_td/wr_td:.1f}x a receiver touchdown (3-year mean).")

print()
print("=" * 84)
print("SAME-USAGE CHECK: does a TE outscore a WR on identical production?")
print("=" * 84)
print("Model each season's fitted curve, then price one 900-yard / 6-TD season at each position.\n")
print(f"{'season':>7} {'as WR':>7} {'as TE':>7} {'TE edge':>8}")
for i, s in enumerate(SEASONS):
    wy, wt, _ = summary["WR"][i]
    ty, tt, _ = summary["TE"][i]
    as_wr = 900 / wy + 6 * wt
    as_te = 900 / ty + 6 * tt
    print(f"{s:>7} {as_wr:>7.1f} {as_te:>7.1f} {as_te - as_wr:>+8.1f}")
