"""Positional tiers across three seasons, and the joint RB/WR/TE flex pool.

Lineup: 1 QB, 1 RB, 1 WR, 1 TE, 4 FLEX (RB/WR/TE), 1 K, 1 DST. 10 teams.
So league-wide weekly demand is 10 QB, 10 DST, 10 K, and 70 flex-eligible
starters (>=10 RB, >=10 WR, >=10 TE, remaining 40 to whoever scores most).
"""
import csv
from collections import defaultdict

SEASONS = (2023, 2024, 2025)


def load(season):
    rows = list(csv.DictReader(open(f"history_{season}.csv", encoding="utf-8")))
    for r in rows:
        r["total"] = int(r["total"])
        r["avg"] = float(r["avg"])
        r["games"] = round(r["total"] / r["avg"])
        r["season"] = season
    return rows


data = {s: load(s) for s in SEASONS}
bypos = {s: defaultdict(list) for s in SEASONS}
for s in SEASONS:
    for r in data[s]:
        bypos[s][r["pos"]].append(r)
    for p in bypos[s]:
        bypos[s][p].sort(key=lambda x: -x["total"])

print("=" * 80)
print("1. HOW FAR DOES THE DATA REACH?  (each list is the top ~100 scorers only)")
print("=" * 80)
print(f"  {'season':>7} {'QB':>4} {'RB':>4} {'WR':>4} {'TE':>4} {'RB+WR+TE':>9} {'need 70?':>9}")
for s in SEASONS:
    n = {p: len(bypos[s][p]) for p in ("QB", "RB", "WR", "TE")}
    flex_n = n["RB"] + n["WR"] + n["TE"]
    print(f"  {s:>7} {n['QB']:>4} {n['RB']:>4} {n['WR']:>4} {n['TE']:>4} {flex_n:>9} "
          f"{'SHORT by ' + str(70 - flex_n) if flex_n < 70 else 'ok':>9}")
print("\n  Consequence: QB10 and DST10 replacement levels are exact. The flex replacement")
print("  (70th best RB/WR/TE) sits at or just below the floor, so it can only be bounded.")

print()
print("=" * 80)
print("2. POSITIONAL TIERS BY SEASON  (season points at each positional rank)")
print("=" * 80)
ranks = [1, 2, 3, 5, 7, 8, 10, 12, 15, 20]
for p in ("QB", "RB", "WR", "TE"):
    print(f"\n  {p}")
    print(f"    {'season':>7} " + " ".join(f"{('#'+str(r)):>5}" for r in ranks))
    for s in SEASONS:
        cells = [f"{bypos[s][p][r-1]['total']:>5}" if len(bypos[s][p]) >= r else "    -" for r in ranks]
        print(f"    {s:>7} " + " ".join(cells))

print()
print("=" * 80)
print("3. IS THE RB7/RB8 CLIFF STRUCTURAL?")
print("=" * 80)
for p in ("QB", "RB", "WR", "TE"):
    print(f"\n  {p}: largest one-rank drop inside the top 12, by season")
    for s in SEASONS:
        grp = bypos[s][p][:12]
        if len(grp) < 3:
            continue
        drops = [(grp[i]["total"] - grp[i + 1]["total"], i + 1) for i in range(len(grp) - 1)]
        d, i = max(drops)
        pct = d / grp[i - 1]["total"] * 100
        print(f"    {s}: {d:>3} pts between {p}{i} and {p}{i+1}  ({pct:.0f}% of {p}{i}'s total)")

print()
print("=" * 80)
print("4. THE FLEX POOL: composition of the 70 weekly RB/WR/TE starters")
print("=" * 80)
for s in SEASONS:
    pool = sorted(bypos[s]["RB"] + bypos[s]["WR"] + bypos[s]["TE"], key=lambda x: -x["total"])
    print(f"\n  {s} -- {len(pool)} flex-eligible players in the data")
    for cut in (20, 40, 70):
        seg = pool[:cut]
        mix = defaultdict(int)
        for r in seg:
            mix[r["pos"]] += 1
        floor = seg[-1]["total"] if len(seg) == cut else None
        tag = f"cut at {floor} pts" if floor else f"only {len(seg)} available, floor {seg[-1]['total']} pts"
        print(f"    top {cut:>2}: " + ", ".join(f"{p} {mix[p]:>2}" for p in ("RB", "WR", "TE")) + f"   ({tag})")

print()
print("=" * 80)
print("5. THE TWO-TIGHT-END TEST")
print("=" * 80)
print("  If every team starts one TE, the league uses TE1-TE10 and fills the other 60")
print("  flex-eligible slots with RBs and WRs. Starting a second TE means dropping the")
print("  worst RB/WR starter (combined RB/WR rank ~60) for TE11-TE20.\n")
for s in SEASONS:
    rbwr = sorted(bypos[s]["RB"] + bypos[s]["WR"], key=lambda x: -x["total"])
    tes = bypos[s]["TE"]
    print(f"  {s}")
    print(f"    RB/WR available in data: {len(rbwr)}. Marginal RB/WR starter (#60) "
          f"{'= ' + str(rbwr[59]['total']) + ' pts' if len(rbwr) >= 60 else 'is below the floor'}")
    if len(rbwr) < 60:
        print(f"      -> the worst RB/WR in the data is #{len(rbwr)} at {rbwr[-1]['total']} pts, "
              f"so RB/WR #60 scored NO MORE than {rbwr[-1]['total']}")
    lo = rbwr[59]["total"] if len(rbwr) >= 60 else rbwr[-1]["total"]
    beat = [t for t in tes[10:] if t["total"] > lo]
    print(f"    TEs ranked 11+ in the data: " +
          (", ".join(f"TE{tes.index(t)+1} {t['player']} {t['total']}" for t in tes[10:]) or "none in data"))
    print(f"    of those, {len(beat)} out-score the marginal RB/WR flex starter "
          f"(threshold {lo} pts)\n")

print("  Direct rank-for-rank: what does the Nth TE score vs the Nth-best RB/WR?")
print(f"  {'season':>7} " + " ".join(f"{('TE'+str(r)):>6}" for r in (2, 5, 8, 10, 12)) +
      "   |" + " ".join(f"{('RBWR'+str(r)):>8}" for r in (30, 40, 50, 60)))
for s in SEASONS:
    tes = bypos[s]["TE"]
    rbwr = sorted(bypos[s]["RB"] + bypos[s]["WR"], key=lambda x: -x["total"])
    a = " ".join(f"{tes[r-1]['total']:>6}" if len(tes) >= r else "     -" for r in (2, 5, 8, 10, 12))
    b = " ".join(f"{rbwr[r-1]['total']:>8}" if len(rbwr) >= r else "    <flr" for r in (30, 40, 50, 60))
    print(f"  {s:>7} {a}   |{b}")
