"""Turn the 2025 scoring picture into advice for BUSSONE's remaining picks."""
import csv
import re
from collections import defaultdict

ALIAS = {"kenneth gainwell": "kenny gainwell"}


def norm(name):
    n = re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", name.lower().strip())
    return ALIAS.get(n.replace(".", ""), n.replace(".", ""))


hist = {}
for h in csv.DictReader(open("history_2025.csv", encoding="utf-8")):
    h["total"], h["avg"] = int(h["total"]), float(h["avg"])
    h["games"] = round(h["total"] / h["avg"])
    hist[norm(h["player"])] = h

board = list(csv.DictReader(open("combined.csv", encoding="utf-8")))
for b in board:
    b["rank"] = int(b["rank"])

by_pos = defaultdict(list)
for h in hist.values():
    by_pos[h["pos"]].append(h)
for p in by_pos:
    by_pos[p].sort(key=lambda x: -x["total"])
posrank = {norm(h["player"]): by_pos[h["pos"]].index(h) + 1 for h in hist.values()}

drafted_pos = defaultdict(int)
for b in board:
    if b["owner"]:
        drafted_pos[b["pos"]] += 1
picks_made = sum(drafted_pos.values())

print("=" * 78)
print(f"DRAFT STATE  ({picks_made} picks in; BUSSONE on the clock at {picks_made + 1})")
print("=" * 78)
print("  Gone so far: " + ", ".join(f"{p} {drafted_pos[p]}" for p in ("QB", "RB", "WR", "TE")))
print(f"  QBs are leaving the board at {drafted_pos['QB'] / picks_made * 10:.1f} per round of 10 picks.")
print(f"  TEs are leaving at {drafted_pos['TE'] / picks_made * 10:.1f} per round.")

print()
print("=" * 78)
print("INJURY-NORMALIZED TIERS  (2025 points per game)")
print("=" * 78)
ranks = [1, 3, 5, 8, 10, 12, 15, 20]
print(f"  {'pos':4} " + " ".join(f"{('#'+str(r)):>5}" for r in ranks))
for p in ("QB", "RB", "WR", "TE"):
    grp = sorted([h for h in by_pos[p] if h["games"] >= 8], key=lambda x: -x["avg"])
    cells = [f"{grp[r-1]['avg']:>5.2f}" if len(grp) >= r else "    -" for r in ranks]
    print(f"  {p:4} " + " ".join(cells))

print()
print("=" * 78)
print("COST OF WAITING  (best available at each position, by BUSSONE's next picks)")
print("=" * 78)
avail = [b for b in board if not b["owner"]]
rate = {p: drafted_pos[p] / picks_made for p in ("QB", "RB", "WR", "TE")}
for p in ("QB", "RB", "WR", "TE"):
    pool = [b for b in avail if b["pos"] == p]
    print(f"\n  {p} -- expect ~{rate[p]*10:.1f} taken per round")
    print(f"    {'your pick':>9} {'likely best available':24} {'board':>5} {'2025':>6} {'pos rk':>7}")
    for pick in (picks_made + 1, picks_made + 11, picks_made + 21, picks_made + 31, picks_made + 41):
        gone = int(rate[p] * (pick - picks_made - 1))
        if gone >= len(pool):
            break
        b = pool[gone]
        h = hist.get(norm(b["player"]))
        pts = f"{h['total']:>6}" if h else "     -"
        pr = f"{h['pos']}{posrank[norm(b['player'])]}" if h else "rookie"
        print(f"    {pick:>9} {b['player']:24} {b['rank']:>5} {pts} {pr:>7}")

print()
print("=" * 78)
print("QB ARBITRAGE  (available QBs, sorted by what they actually scored in 2025)")
print("=" * 78)
qbs = []
for b in avail:
    if b["pos"] == "QB" and norm(b["player"]) in hist:
        qbs.append((hist[norm(b["player"])], b))
qbs.sort(key=lambda x: -x[0]["total"])
print(f"  {'player':22} {'board':>5} {'2025 pts':>8} {'pos rk':>6} {'g':>3} {'pts/g':>6}")
for h, b in qbs[:14]:
    print(f"  {h['player']:22} {b['rank']:>5} {h['total']:>8} {'QB'+str(posrank[norm(h['player'])]):>6} "
          f"{h['games']:>3} {h['avg']:>6.2f}")

print()
print("=" * 78)
print("BUSSONE ROSTER vs THE FIELD")
print("=" * 78)
rosters = defaultdict(lambda: defaultdict(int))
for b in board:
    if b["owner"]:
        rosters[b["owner"]][b["pos"]] += 1
print(f"  {'team':12} {'QB':>3} {'RB':>3} {'WR':>3} {'TE':>3}   2025 pts on roster")
for t in sorted(rosters, key=lambda t: -sum(hist[norm(b['player'])]["total"]
                                            for b in board if b["owner"] == t and norm(b["player"]) in hist)):
    pts = sum(hist[norm(b["player"])]["total"] for b in board if b["owner"] == t and norm(b["player"]) in hist)
    r = rosters[t]
    star = " <-- you" if t == "BUSSONE" else ""
    print(f"  {t:12} {r['QB']:>3} {r['RB']:>3} {r['WR']:>3} {r['TE']:>3}   {pts:>3}{star}")
