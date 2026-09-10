"""Pick 41 under the confirmed lineup: 1QB/1RB/1WR/1TE/4FLEX/1K/1DST, 10 teams."""
import csv
import re
from collections import defaultdict

import numpy as np

SEASONS = (2023, 2024, 2025)
ALIAS = {"kenneth gainwell": "kenny gainwell"}


def norm(n):
    s = re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", n.lower().strip()).replace(".", "")
    return ALIAS.get(s, s)


hist = defaultdict(dict)
for s in SEASONS:
    for r in csv.DictReader(open(f"history_{s}.csv", encoding="utf-8")):
        r["total"] = int(r["total"])
        hist[s][norm(r["player"])] = r

bypos = {s: defaultdict(list) for s in SEASONS}
for s in SEASONS:
    for r in hist[s].values():
        bypos[s][r["pos"]].append(r)
    for p in bypos[s]:
        bypos[s][p].sort(key=lambda x: -x["total"])
posrank = {s: {norm(r["player"]): bypos[s][r["pos"]].index(r) + 1 for r in hist[s].values()} for s in SEASONS}

board = list(csv.DictReader(open("combined.csv", encoding="utf-8")))
for b in board:
    b["rank"] = int(b["rank"])

VOR = {"RB": 77, "WR": 57, "QB": 30, "TE": 33, "DST": 31}
STICK = {"RB": 0.36, "WR": 0.12, "QB": 0.23, "TE": 0.23, "DST": 0.21}

print("=" * 76)
print("1. VALUE YOU CAN ACTUALLY TARGET IN A DRAFT")
print("=" * 76)
print("  Shrinking each position's top-end VOR by how repeatable that position is.")
print("  This is a rough heuristic, not a formal expectation -- but the ordering is")
print("  robust to any reasonable weighting.\n")
print(f"  {'pos':5} {'#1 VOR':>7} {'stickiness':>11} {'targetable':>11}")
for p in sorted(VOR, key=lambda p: -VOR[p] * STICK[p]):
    print(f"  {p:5} {VOR[p]:>7} {STICK[p]:>+11.2f} {VOR[p]*STICK[p]:>11.0f}")

print()
print("=" * 76)
print("2. BUSSONE's LINEUP HOLES")
print("=" * 76)
mine = [b for b in board if b["owner"] == "BUSSONE"]
have = defaultdict(int)
for b in mine:
    have[b["pos"]] += 1
print("  Rostered: " + ", ".join(f"{b['player']} ({b['pos']})" for b in mine))
print(f"  Counts: " + ", ".join(f"{p} {have[p]}" for p in ("QB", "RB", "WR", "TE")) + ", K 0, DST 0")
print("\n  Starting slots: 1 QB, 1 RB, 1 WR, 1 TE, 4 FLEX, 1 K, 1 DST")
print("  Filled: RB (Walker), WR (Chase), 2 of 4 FLEX (Lamb, Nabers)")
print("  Empty:  QB, TE, K, DST, and 2 FLEX  -> six starters still needed")
print("  Caps:   max 2 QB / 5 RB / 6 WR / 2 TE / 2 K / 2 DST = 19 roster spots")
print(f"  Room:   {19 - len(mine)} picks remaining if the draft runs the full 19 rounds")

print()
print("=" * 76)
print("3. BEST AVAILABLE, WITH THREE-YEAR RECORDS")
print("=" * 76)
avail = [b for b in board if not b["owner"]]
for p in ("RB", "TE", "QB", "WR"):
    print(f"\n  {p}")
    print(f"    {'board':>5} {'player':22} {'2023':>6} {'2024':>6} {'2025':>6}   3yr finishes")
    for b in [x for x in avail if x["pos"] == p][:6]:
        k = norm(b["player"])
        pts, fins = [], []
        for s in SEASONS:
            if k in hist[s]:
                pts.append(f"{hist[s][k]['total']:>6}")
                fins.append(f"{p}{posrank[s][k]}")
            else:
                pts.append("     -")
        tag = ", ".join(fins) if fins else "no top-100 season (rookie or below floor)"
        print(f"    {b['rank']:>5} {b['player']:22} " + " ".join(pts) + f"   {tag}")

print()
print("=" * 76)
print("4. COST OF WAITING, BY POSITION")
print("=" * 76)
drafted_pos = defaultdict(int)
for b in board:
    if b["owner"]:
        drafted_pos[b["pos"]] += 1
made = sum(drafted_pos.values())
print(f"  {made} picks in. Gone: " + ", ".join(f"{p} {drafted_pos[p]}" for p in ("QB", "RB", "WR", "TE")))
print("  Zero kickers and zero defenses taken -- consistent with 1 K and 1 DST starting.\n")
print(f"  {'pos':4} {'per round':>10}  best available at your pick 41 / 61 / 81 / 101")
for p in ("RB", "WR", "TE", "QB"):
    pool = [b for b in avail if b["pos"] == p]
    rate = drafted_pos[p] / made
    names = []
    for pick in (41, 61, 81, 101):
        gone = int(rate * (pick - 41))
        names.append(pool[gone]["player"] if gone < len(pool) else "-")
    print(f"  {p:4} {rate*10:>10.1f}  " + " / ".join(names))

print()
print("=" * 76)
print("5. THE TWO-TIGHT-END QUESTION, SETTLED")
print("=" * 76)
print("  A second TE competes for a FLEX slot against your next-best RB/WR.")
print("  Three-year average points above flex replacement:\n")
flex_repl = {2023: 17, 2024: 16, 2025: 24}
for p in ("TE", "RB", "WR"):
    row = []
    for i in (2, 4, 9):
        vals = [bypos[s][p][i]["total"] - flex_repl[s] for s in SEASONS if len(bypos[s][p]) > i]
        row.append(f"{p}{i+1} {np.mean(vals):>+5.0f}")
    print(f"    {p}: " + "   ".join(row))
print("\n  Your TE2 will realistically be somewhere around TE10 league-wide, worth about")
print("  +4 over a replacement flex body. A 10th-best RB is worth about +23. So a")
print("  second tight end is mildly positive, not a strategy. Roster two because you")
print("  need one starter and the backup is free -- do not pay up for the pair.")
