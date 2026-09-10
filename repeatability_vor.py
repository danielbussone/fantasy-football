"""Which positions are predictable year to year, and what is each worth over replacement?

Lineup: 1 QB, 1 RB, 1 WR, 1 TE, 4 FLEX (RB/WR/TE), 1 K, 1 DST. 10 teams.
Replacement: QB10, DST10, K10, and the 70th-best RB/WR/TE for the flex pool.
"""
import csv
import re
from collections import defaultdict

import numpy as np

SEASONS = (2023, 2024, 2025)
ALIAS = {"kenneth gainwell": "kenny gainwell"}


def norm(n):
    return ALIAS.get(re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", n.lower().strip()).replace(".", ""),
                     re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", n.lower().strip()).replace(".", ""))


def load(season):
    rows = list(csv.DictReader(open(f"history_{season}.csv", encoding="utf-8")))
    for r in rows:
        r["total"] = int(r["total"])
        r["key"] = norm(r["player"])
    return rows


data = {s: load(s) for s in SEASONS}
idx = {s: {r["key"]: r for r in data[s]} for s in SEASONS}
bypos = {s: defaultdict(list) for s in SEASONS}
for s in SEASONS:
    for r in data[s]:
        bypos[s][r["pos"]].append(r)
    for p in bypos[s]:
        bypos[s][p].sort(key=lambda x: -x["total"])

dst = defaultdict(list)
for r in csv.DictReader(open("dst_history.csv", encoding="utf-8")):
    r["total"] = float(r["total"])
    dst[int(r["season"])].append(r)
for s in dst:
    dst[s].sort(key=lambda x: -x["total"])

print("=" * 80)
print("1. YEAR-OVER-YEAR STICKINESS BY POSITION")
print("=" * 80)
print("  Correlation of a player's points in year N with year N+1, for players who")
print("  appear in the top 100 in BOTH years. This is survivorship-biased upward --")
print("  players who fell out of the top 100 are excluded, so true stickiness is lower.\n")
print(f"  {'pos':4} {'pair':>13} {'n':>4} {'r':>7}")
agg = defaultdict(list)
for p in ("QB", "RB", "WR", "TE"):
    for a, b in ((2023, 2024), (2024, 2025)):
        both = [k for k in idx[a] if k in idx[b] and idx[a][k]["pos"] == p and idx[b][k]["pos"] == p]
        if len(both) < 5:
            continue
        xs = [idx[a][k]["total"] for k in both]
        ys = [idx[b][k]["total"] for k in both]
        r = float(np.corrcoef(xs, ys)[0, 1])
        agg[p].append(r)
        print(f"  {p:4} {f'{a}->{b}':>13} {len(both):>4} {r:>+7.2f}")
    print()
teams = sorted(set(d["team"] for d in dst[2023]))
tbl = {s: {d["team"]: d["total"] for d in dst[s]} for s in SEASONS}
dr = []
for a, b in ((2023, 2024), (2024, 2025)):
    r = float(np.corrcoef([tbl[a][t] for t in teams], [tbl[b][t] for t in teams])[0, 1])
    dr.append(r)
    print(f"  {'DST':4} {f'{a}->{b}':>13} {len(teams):>4} {r:>+7.2f}")

print("\n  Mean stickiness: " + ", ".join(f"{p} {np.mean(agg[p]):+.2f}" for p in ("QB", "RB", "WR", "TE"))
      + f", DST {np.mean(dr):+.2f}")

print()
print("=" * 80)
print("2. FLEX REPLACEMENT LEVEL  (70th-best RB/WR/TE -- below the data floor)")
print("=" * 80)
flex_repl = {}
for s in SEASONS:
    pool = sorted(bypos[s]["RB"] + bypos[s]["WR"] + bypos[s]["TE"], key=lambda x: -x["total"])
    n = len(pool)
    tail = [(i + 1, pool[i]["total"]) for i in range(29, n)]
    lr = np.polyfit(np.log([t[0] for t in tail]), np.log([t[1] for t in tail]), 1)
    est = float(np.exp(np.polyval(lr, np.log(70))))
    flex_repl[s] = est
    print(f"  {s}: data reaches flex rank {n} at {pool[-1]['total']} pts. "
          f"Power-law tail fit -> rank 70 ESTIMATED at {est:.0f} pts")
print("\n  These three numbers are extrapolations, not measurements. Everything below")
print("  that uses 'flex VOR' inherits that uncertainty; treat the ordering as solid")
print("  and the magnitudes as approximate.")

print()
print("=" * 80)
print("3. VALUE OVER REPLACEMENT, ALL POSITIONS, CORRECT REPLACEMENT RANKS")
print("=" * 80)
print(f"  {'season':>7} {'slot':>6} {'#1':>6} {'#3':>6} {'#5':>6} {'#10':>6}  replacement")
for s in SEASONS:
    print(f"  {s}")
    q = [r["total"] for r in bypos[s]["QB"]]
    print(f"  {'':>7} {'QB':>6} {q[0]-q[9]:>6} {q[2]-q[9]:>6} {q[4]-q[9]:>6} {0:>6}  QB10 = {q[9]} (exact)")
    d = [x["total"] for x in dst[s]]
    print(f"  {'':>7} {'DST':>6} {d[0]-d[9]:>6.0f} {d[2]-d[9]:>6.0f} {d[4]-d[9]:>6.0f} {0:>6}  "
          f"DST10 = {d[9]:.0f} (exact)")
    fr = flex_repl[s]
    for p in ("RB", "WR", "TE"):
        v = [r["total"] for r in bypos[s][p]]
        cells = [f"{v[i]-fr:>6.0f}" if len(v) > i else "     -" for i in (0, 2, 4, 9)]
        print(f"  {'':>7} {p:>6} " + " ".join(cells) + f"  flex repl = {fr:.0f} (estimated)")
    print()

print("=" * 80)
print("4. THREE-YEAR AVERAGE VOR BY SLOT")
print("=" * 80)
print(f"  {'slot':>6} {'#1':>7} {'#3':>7} {'#5':>7} {'#10':>7}   stickiness")
rows = []
q1 = [bypos[s]["QB"][0]["total"] - bypos[s]["QB"][9]["total"] for s in SEASONS]
q3 = [bypos[s]["QB"][2]["total"] - bypos[s]["QB"][9]["total"] for s in SEASONS]
q5 = [bypos[s]["QB"][4]["total"] - bypos[s]["QB"][9]["total"] for s in SEASONS]
print(f"  {'QB':>6} {np.mean(q1):>7.0f} {np.mean(q3):>7.0f} {np.mean(q5):>7.0f} {0:>7}   {np.mean(agg['QB']):+.2f}")
d1 = [dst[s][0]["total"] - dst[s][9]["total"] for s in SEASONS]
d3 = [dst[s][2]["total"] - dst[s][9]["total"] for s in SEASONS]
d5 = [dst[s][4]["total"] - dst[s][9]["total"] for s in SEASONS]
print(f"  {'DST':>6} {np.mean(d1):>7.0f} {np.mean(d3):>7.0f} {np.mean(d5):>7.0f} {0:>7}   {np.mean(dr):+.2f}")
for p in ("RB", "WR", "TE"):
    cells = []
    for i in (0, 2, 4, 9):
        vals = [bypos[s][p][i]["total"] - flex_repl[s] for s in SEASONS if len(bypos[s][p]) > i]
        cells.append(f"{np.mean(vals):>7.0f}" if vals else "      -")
    print(f"  {p:>6} " + " ".join(cells) + f"   {np.mean(agg[p]):+.2f}")
print("\n  VOR says what a slot is worth. Stickiness says how much of that you can")
print("  actually target in a draft. A position needs both to deserve an early pick.")
