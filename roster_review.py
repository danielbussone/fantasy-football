"""Evaluate BUSSONE's final 19-man roster under this league's scoring.

Starters: 1 QB, 1 RB, 1 WR, 1 TE, 4 FLEX (RB/WR/TE), 1 K, 1 DST. 10 teams.
Replacement: QB10 and DST10 exact; flex replacement extrapolated (below data floor).
"""
import csv
import re
from collections import defaultdict

import numpy as np

SEASONS = (2023, 2024, 2025)
FLEX_REPL = {2023: 17, 2024: 16, 2025: 24}

ROSTER = [
    ("Trevor Lawrence", "QB"), ("Jordan Love", "QB"),
    ("Kenneth Walker III", "RB"), ("Jeremiyah Love", "RB"), ("TreVeyon Henderson", "RB"),
    ("Blake Corum", "RB"), ("Woody Marks", "RB"),
    ("Ja'Marr Chase", "WR"), ("CeeDee Lamb", "WR"), ("Malik Nabers", "WR"),
    ("Luther Burden III", "WR"), ("Ladd McConkey", "WR"), ("Makai Lemon", "WR"),
    ("Tyler Warren", "TE"), ("Dalton Kincaid", "TE"),
]
DEFENSES = ["Seahawks", "Ravens"]


def norm(n):
    return re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", n.lower().strip()).replace(".", "")


hist, bypos, posrank = {}, {}, {}
for s in SEASONS:
    rows = list(csv.DictReader(open(f"history_{s}.csv", encoding="utf-8")))
    for r in rows:
        for k in ("rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "total"):
            r[k] = int(r[k])
        r["avg"] = float(r["avg"])
        r["games"] = round(r["total"] / r["avg"])
        r["scrim"] = r["rush_yds"] + r["rec_yds"]
        r["tds"] = r["rush_td"] + r["rec_td"]
    hist[s] = {norm(r["player"]): r for r in rows}
    bp = defaultdict(list)
    for r in rows:
        bp[r["pos"]].append(r)
    for p in bp:
        bp[p].sort(key=lambda x: -x["total"])
    bypos[s] = bp
    posrank[s] = {norm(r["player"]): bp[r["pos"]].index(r) + 1 for r in rows}

board = {norm(b["player"]): b for b in csv.DictReader(open("combined.csv", encoding="utf-8"))}

dst = defaultdict(list)
for r in csv.DictReader(open("dst_history.csv", encoding="utf-8")):
    r["total"] = float(r["total"])
    dst[int(r["season"])].append(r)
for s in dst:
    dst[s].sort(key=lambda x: -x["total"])
dstrank = {s: {d["team"]: i + 1 for i, d in enumerate(dst[s])} for s in SEASONS}
dsttbl = {s: {d["team"]: d for d in dst[s]} for s in SEASONS}

print("=" * 92)
print("ROSTER, WITH BOARD POSITION AND THREE-YEAR RECORD UNDER THIS SCORING")
print("=" * 92)
print(f"{'player':22} {'pos':4} {'brd':>4} {'dyn':>4} {'red':>4} {'age':>4} "
      f"{'2023':>10} {'2024':>10} {'2025':>10}")
for name, pos in ROSTER:
    b = board.get(norm(name), {})
    cells = []
    for s in SEASONS:
        h = hist[s].get(norm(name))
        cells.append(f"{h['total']:>3} ({pos}{posrank[s][norm(name)]:<2})" if h else f"{'-':>9}")
    print(f"{name:22} {pos:4} {b.get('rank','?'):>4} {b.get('dynasty') or '-':>4} "
          f"{b.get('redraft') or '-':>4} {b.get('age') or '-':>4} " + " ".join(f"{c:>10}" for c in cells))
for d in DEFENSES:
    cells = [f"{dsttbl[s][d]['total']:>4.0f} (DST{dstrank[s][d]:<2})" for s in SEASONS]
    print(f"{d:22} {'DST':4} {'-':>4} {'-':>4} {'-':>4} {'-':>4} " + " ".join(f"{c:>10}" for c in cells))
print("Cairo Santos / Will Reichard  K  -- no kicker data in any of the three seasons")

print()
print("=" * 92)
print("SCORING-FIT PROFILE: yards per catch and share of points from touchdowns")
print("=" * 92)
print("Receptions score zero and a TD is worth ~30 yards, so total yardage is the")
print("only thing that pays. Low yards-per-catch and high TD share are both warnings.\n")
print(f"{'player':22} {'season':>7} {'rec':>4} {'yds':>5} {'y/c':>5} {'TD':>3} {'pts':>4} {'TD share':>9}")
TD_VAL = {"RB": 1.50, "WR": 1.33, "TE": 1.78}
for name, pos in ROSTER:
    if pos == "QB":
        continue
    for s in SEASONS:
        h = hist[s].get(norm(name))
        if not h:
            continue
        ypc = h["rec_yds"] / h["rec"] if h["rec"] else 0
        share = h["tds"] * TD_VAL[pos] / h["total"] if h["total"] else 0
        print(f"{name:22} {s:>7} {h['rec']:>4} {h['scrim']:>5} {ypc:>5.1f} {h['tds']:>3} "
              f"{h['total']:>4} {share*100:>8.0f}%")

print()
print("=" * 92)
print("THE FLEX DECISION: seven of thirteen RB/WR/TE start each week")
print("=" * 92)
print("Slots: 1 RB + 1 WR + 1 TE (mandatory) + 4 FLEX from any of the three.\n")
print("Most recent full-season evidence for each flex-eligible player, per game:")
rows = []
for name, pos in ROSTER:
    if pos == "QB":
        continue
    best = None
    for s in SEASONS:
        h = hist[s].get(norm(name))
        if h:
            best = (s, h)
    if best:
        s, h = best
        rows.append((h["avg"], name, pos, s, h))
    else:
        rows.append((None, name, pos, None, None))
print(f"  {'player':22} {'pos':4} {'latest':>7} {'pts/gm':>7} {'g':>3} {'yds/gm':>7}")
for avg, name, pos, s, h in sorted(rows, key=lambda x: -(x[0] or 0)):
    if h:
        print(f"  {name:22} {pos:4} {s:>7} {avg:>7.2f} {h['games']:>3} {h['scrim']/h['games']:>7.0f}")
    else:
        b = board.get(norm(name), {})
        print(f"  {name:22} {pos:4} {'none':>7} {'-':>7} {'-':>3} {'-':>7}  "
              f"(board {b.get('rank','?')}, dyn {b.get('dynasty','?')}, red {b.get('redraft','?')})")

print()
print("=" * 92)
print("TIGHT END CHECK: do Warren or Kincaid belong in a FLEX slot?")
print("=" * 92)
print("The TE bonus curve starts at 40 yards (vs 70 for a WR) and steps every 20 yards.")
print("So a TE's value depends entirely on which tier his weekly yardage lands in.\n")
print(f"  {'yds/game':>9} {'TE tier pts/gm':>15} {'over 17 games':>14}")
for y in (40, 50, 60, 80, 100):
    tier = min(10, (y - 40) // 20 + 1) if y >= 40 else 0
    print(f"  {y:>9} {tier:>15} {tier*17:>14}")
print()
for name in ("Tyler Warren", "Dalton Kincaid"):
    h = hist[2025].get(norm(name))
    ypg = h["scrim"] / h["games"]
    print(f"  {name}: {h['scrim']} yds in {h['games']} games = {ypg:.0f} yds/game "
          f"-> bottom tier, {h['avg']:.2f} pts/gm actual")
print("\n  Both sit just above the 40-yard threshold, where the TE premium is worth the")
print("  least. The premium pays for TEs clearing 60-80 yards a game; neither does.")

print()
print("=" * 92)
print("VALUE OVER REPLACEMENT OF THE LIKELY STARTING SEVEN (2025 basis)")
print("=" * 92)
fr = FLEX_REPL[2025]
print(f"  Flex replacement 2025 = {fr} pts (ESTIMATED -- rank 70 is below the data floor)\n")
starters = ["Ja'Marr Chase", "Kenneth Walker III", "TreVeyon Henderson", "CeeDee Lamb",
            "Dalton Kincaid", "Malik Nabers", "Jeremiyah Love"]
tot = 0
for name in starters:
    h = hist[2025].get(norm(name))
    if h:
        v = h["total"] - fr
        tot += v
        print(f"  {name:22} {h['total']:>4} pts  VOR {v:>+5.0f}")
    else:
        print(f"  {name:22} {'  n/a':>4}      VOR    ?   no 2025 top-100 season")
print(f"\n  Sum of measurable flex VOR: {tot:+.0f} (four players measured, three unknown)")
q = [r["total"] for r in bypos[2025]["QB"]]
for name in ("Trevor Lawrence", "Jordan Love"):
    h = hist[2025][norm(name)]
    print(f"  {name:22} {h['total']:>4} pts  VOR {h['total']-q[9]:>+5.0f}  (vs QB10 = {q[9]}, exact)")
d = [x["total"] for x in dst[2025]]
for name in DEFENSES:
    t = dsttbl[2025][name]["total"]
    print(f"  {name:22} {t:>4.0f} pts  VOR {t-d[9]:>+5.0f}  (vs DST10 = {d[9]:.0f}, exact)")
