"""Where do defenses sit in this format, and are their finishes repeatable?"""
import csv
from collections import defaultdict

import numpy as np

SEASONS = (2023, 2024, 2025)


def load_skill(season):
    rows = list(csv.DictReader(open(f"history_{season}.csv", encoding="utf-8")))
    for r in rows:
        r["total"] = int(r["total"])
    return rows


dst = defaultdict(list)
for r in csv.DictReader(open("dst_history.csv", encoding="utf-8")):
    r["total"] = float(r["total"])
    for k in ("sack", "fum", "int", "dwn", "td", "sty", "yds_ag", "pts_ag"):
        r[k] = int(r[k])
    dst[int(r["season"])].append(r)
for s in dst:
    dst[s].sort(key=lambda x: -x["total"])

skill = {s: load_skill(s) for s in SEASONS}

print("=" * 78)
print("1. DEFENSES vs SKILL PLAYERS  (where a DST would rank among all scorers)")
print("=" * 78)
for s in SEASONS:
    everyone = sorted(skill[s], key=lambda x: -x["total"])
    def overall_rank(pts):
        return sum(1 for r in everyone if r["total"] > pts) + 1
    print(f"\n  {s}")
    print(f"    {'DST rank':>9} {'team':12} {'pts':>6} {'would rank':>11} among top-100 skill players")
    for i in (0, 4, 9, 11, 19, 31):
        d = dst[s][i]
        print(f"    {'DST'+str(i+1):>9} {d['team']:12} {d['total']:>6.1f} {overall_rank(d['total']):>11}")

print()
print("=" * 78)
print("2. HOW BIG IS THE DST EDGE?  (replacement = DST10, since 10 teams start one)")
print("=" * 78)
print(f"  {'season':>7} {'DST1':>6} {'DST5':>6} {'DST10':>6} {'DST12':>6} {'DST20':>6} {'DST32':>6} "
      f"{'DST1 VOR':>9} {'DST5 VOR':>9}")
for s in SEASONS:
    d = [x["total"] for x in dst[s]]
    print(f"  {s:>7} {d[0]:>6.1f} {d[4]:>6.1f} {d[9]:>6.1f} {d[11]:>6.1f} {d[19]:>6.1f} {d[31]:>6.1f} "
          f"{d[0]-d[9]:>9.1f} {d[4]-d[9]:>9.1f}")

print("\n  Same table for the skill positions, replacement at the correct rank:")
print("  (QB replacement = QB10. Flex replacement is bounded, not exact -- see note.)")
print(f"  {'season':>7} {'QB1':>5} {'QB10':>5} {'QB1 VOR':>8}   {'RB1':>5} {'WR1':>5} {'TE1':>5}")
for s in SEASONS:
    q = sorted([r["total"] for r in skill[s] if r["pos"] == "QB"], reverse=True)
    rb = max(r["total"] for r in skill[s] if r["pos"] == "RB")
    wr = max(r["total"] for r in skill[s] if r["pos"] == "WR")
    te = max(r["total"] for r in skill[s] if r["pos"] == "TE")
    print(f"  {s:>7} {q[0]:>5} {q[9]:>5} {q[0]-q[9]:>8}   {rb:>5} {wr:>5} {te:>5}")

print()
print("=" * 78)
print("3. ARE DST FINISHES REPEATABLE?  (join by team across seasons)")
print("=" * 78)
tbl = {s: {d["team"]: d for d in dst[s]} for s in SEASONS}
rank = {s: {d["team"]: i + 1 for i, d in enumerate(dst[s])} for s in SEASONS}
teams = sorted(set(tbl[2023]) & set(tbl[2024]) & set(tbl[2025]))
print(f"  {len(teams)} teams present in all three seasons\n")


def corr(xs, ys):
    return float(np.corrcoef(xs, ys)[0, 1])


def spearman(xs, ys):
    def rk(v):
        order = np.argsort(np.argsort(-np.array(v)))
        return order.astype(float)
    return corr(rk(xs), rk(ys))


for a, b in ((2023, 2024), (2024, 2025), (2023, 2025)):
    xs = [tbl[a][t]["total"] for t in teams]
    ys = [tbl[b][t]["total"] for t in teams]
    print(f"  {a} -> {b}:  points r = {corr(xs, ys):+.2f}   rank r = {spearman(xs, ys):+.2f}   "
          f"r^2 = {corr(xs, ys)**2:.2f}")

print("\n  Year-over-year movement of each season's top 5 defenses:")
for a, b in ((2023, 2024), (2024, 2025)):
    print(f"    {a} top 5 -> {b} finish: " +
          ", ".join(f"{d['team']} DST{rank[a][d['team']]}->DST{rank[b][d['team']]}" for d in dst[a][:5]))

print("\n  How often does a top-5 defense stay top-10 the next year?")
for a, b in ((2023, 2024), (2024, 2025)):
    top5 = [d["team"] for d in dst[a][:5]]
    kept = sum(1 for t in top5 if rank[b][t] <= 10)
    print(f"    {a}->{b}: {kept} of 5")

print()
print("=" * 78)
print("4. WHAT DRIVES DST SCORING?  (pooled 3-season fit)")
print("=" * 78)
rows = [r for s in SEASONS for r in dst[s]]
cols = ["sack", "fum", "int", "dwn", "td", "sty", "pts_ag"]
X = np.column_stack([np.array([r[c] for r in rows], float) for c in cols] + [np.ones(len(rows))])
y = np.array([r["total"] for r in rows])
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
r2 = 1 - ((y - X @ coef) ** 2).sum() / ((y - y.mean()) ** 2).sum()
for c, v in zip(cols, coef):
    print(f"  {c:>8}: {v:+.3f} pts each")
print(f"  R^2 {r2:.3f}")
print("\n  Defensive touchdowns and points allowed carry most of the signal; both are")
print("  among the least repeatable things a defense does.")
tds = [(s, [d["td"] for d in dst[s]]) for s in SEASONS]
xs = [tbl[2024][t]["td"] for t in teams]
ys = [tbl[2025][t]["td"] for t in teams]
print(f"  Defensive TDs, 2024 -> 2025 correlation: r = {corr(xs, ys):+.2f}")
xs = [tbl[2024][t]["pts_ag"] for t in teams]
ys = [tbl[2025][t]["pts_ag"] for t in teams]
print(f"  Points allowed, 2024 -> 2025 correlation: r = {corr(xs, ys):+.2f}")
xs = [tbl[2024][t]["sack"] for t in teams]
ys = [tbl[2025][t]["sack"] for t in teams]
print(f"  Sacks,          2024 -> 2025 correlation: r = {corr(xs, ys):+.2f}")
