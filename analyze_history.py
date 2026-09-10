"""What the 2025 season says about this league's tiered-bucket scoring."""
import csv
import re
from collections import defaultdict

ALIAS = {"kenneth gainwell": "kenny gainwell"}


def norm(name):
    n = name.lower().strip()
    n = re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", n)
    n = n.replace(".", "")
    return ALIAS.get(n, n)


hist = list(csv.DictReader(open("history_2025.csv", encoding="utf-8")))
for h in hist:
    for k in ("pass_yds", "pass_td", "rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "total"):
        h[k] = int(h[k])
    h["avg"] = float(h["avg"])
    h["games"] = round(h["total"] / h["avg"]) if h["avg"] else 0
    h["scrim_yds"] = h["rush_yds"] + h["rec_yds"]
    h["tds"] = h["pass_td"] + h["rush_td"] + h["rec_td"]

board = {norm(r["player"]): r for r in csv.DictReader(open("combined.csv", encoding="utf-8"))}

by_pos = defaultdict(list)
for h in hist:
    by_pos[h["pos"]].append(h)
for p in by_pos:
    by_pos[p].sort(key=lambda x: -x["total"])

print("=" * 74)
print("1. WHO ACTUALLY SCORED  (top 100 finishers, 2025)")
print("=" * 74)
counts = {p: len(v) for p, v in by_pos.items()}
print("Positions represented in the top 100:", ", ".join(f"{p} {counts[p]}" for p in ("QB", "RB", "WR", "TE")))
for cut in (10, 25, 50):
    top = sorted(hist, key=lambda x: -x["total"])[:cut]
    mix = defaultdict(int)
    for t in top:
        mix[t["pos"]] += 1
    print(f"  top {cut:>3}: " + ", ".join(f"{p} {mix[p]}" for p in ("QB", "RB", "WR", "TE") if mix[p]))

print()
print("=" * 74)
print("2. TIER CURVES  (season points at each positional rank)")
print("=" * 74)
ranks = [1, 2, 3, 5, 8, 10, 12, 15, 20, 25]
print(f"{'pos':4} " + " ".join(f"{('#'+str(r)):>5}" for r in ranks))
for p in ("QB", "RB", "WR", "TE"):
    row = []
    for r in ranks:
        v = by_pos[p][r - 1]["total"] if len(by_pos[p]) >= r else None
        row.append(f"{v:>5}" if v else "    -")
    print(f"{p:4} " + " ".join(row))

print()
print("Biggest single-rank drop-offs inside each position's top 15:")
for p in ("QB", "RB", "WR", "TE"):
    grp = by_pos[p][:15]
    drops = [(grp[i]["total"] - grp[i + 1]["total"], i + 1, grp[i], grp[i + 1]) for i in range(len(grp) - 1)]
    d, i, a, b = max(drops)
    print(f"  {p}: {d:>2} pts between {p}{i} {a['player']} ({a['total']}) and {p}{i+1} {b['player']} ({b['total']})")

print()
print("=" * 74)
print("3. VALUE OVER REPLACEMENT  (10 teams; replacement = last starter)")
print("=" * 74)
for label, need in (("1QB / 2RB / 3WR / 1TE", {"QB": 1, "RB": 2, "WR": 3, "TE": 1}),
                    ("superflex (2QB)      ", {"QB": 2, "RB": 2, "WR": 3, "TE": 1})):
    print(f"\n  Lineup {label}")
    print(f"  {'pos':4} {'repl':>5} {'#1 VOR':>7} {'#3 VOR':>7} {'#5 VOR':>7}")
    for p in ("QB", "RB", "WR", "TE"):
        idx = need[p] * 10 - 1
        if idx >= len(by_pos[p]):
            print(f"  {p:4} {'n/a':>5}  (top 100 does not reach replacement level)")
            continue
        repl = by_pos[p][idx]["total"]
        vors = [by_pos[p][i - 1]["total"] - repl for i in (1, 3, 5)]
        print(f"  {p:4} {repl:>5} " + " ".join(f"{v:>7}" for v in vors))

print()
print("=" * 74)
print("4. WHAT THE SCORING REWARDS")
print("=" * 74)
print("Receptions are worth 0. Yardage is bucketed. Do catches predict points?")
for p in ("WR", "TE"):
    grp = [h for h in by_pos[p] if h["games"] >= 14]
    grp.sort(key=lambda x: -x["rec"])
    print(f"\n  {p}s with >=14 games, sorted by receptions:")
    print(f"    {'player':22} {'rec':>4} {'yds':>5} {'TD':>3} {'pts':>4}")
    for h in grp[:6]:
        print(f"    {h['player']:22} {h['rec']:>4} {h['scrim_yds']:>5} {h['tds']:>3} {h['total']:>4}")

print("\n  Same-yardage pairs with very different touchdown counts:")
pairs = [("Dallas Goedert", "Juwan Johnson"), ("Tee Higgins", "Michael Wilson"),
         ("Zach Charbonnet", "Tony Pollard"), ("Wan'Dale Robinson", "Alec Pierce")]
lookup = {h["player"]: h for h in hist}
for a, b in pairs:
    ha, hb = lookup[a], lookup[b]
    print(f"    {a:22} {ha['scrim_yds']:>5}yd {ha['tds']:>2}TD {ha['rec']:>3}rec -> {ha['total']:>3}   "
          f"{b:22} {hb['scrim_yds']:>5}yd {hb['tds']:>2}TD {hb['rec']:>3}rec -> {hb['total']:>3}")

print()
print("=" * 74)
print("5. THE BOARD vs LAST YEAR  (undrafted players only)")
print("=" * 74)
rows = []
for h in hist:
    b = board.get(norm(h["player"]))
    if b and not b["owner"]:
        rows.append((int(b["rank"]), h))
rows.sort()
print("\n  Best 2025 finishers still on the board, by combined board rank:")
print(f"  {'board':>5} {'player':24} {'pos':4} {'2025 pts':>8} {'pos rk':>7} {'g':>3}")
for rank, h in sorted(rows, key=lambda x: -x[1]["total"])[:20]:
    pr = by_pos[h["pos"]].index(h) + 1
    print(f"  {rank:>5} {h['player']:24} {h['pos']:4} {h['total']:>8} {h['pos']+str(pr):>7} {h['games']:>3}")
