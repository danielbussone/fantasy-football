"""Receptions score zero, so yards per catch is the stat the consensus board ignores."""
import csv
import re

ALIAS = {"kenneth gainwell": "kenny gainwell"}


def norm(name):
    n = re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", name.lower().strip()).replace(".", "")
    return ALIAS.get(n, n)


hist = {}
for h in csv.DictReader(open("history_2025.csv", encoding="utf-8")):
    h["total"], h["rec"], h["rec_yds"] = int(h["total"]), int(h["rec"]), int(h["rec_yds"])
    h["avg"] = float(h["avg"])
    h["games"] = round(h["total"] / h["avg"])
    hist[norm(h["player"])] = h

board = {norm(b["player"]): b for b in csv.DictReader(open("combined.csv", encoding="utf-8"))}

rows = []
for k, h in hist.items():
    if h["pos"] not in ("WR", "TE") or h["rec"] < 30 or k not in board:
        continue
    b = board[k]
    rows.append({
        "player": h["player"], "pos": h["pos"], "rank": int(b["rank"]), "owner": b["owner"],
        "ypc": h["rec_yds"] / h["rec"], "rec": h["rec"], "yds": h["rec_yds"],
        "total": h["total"], "ppr_pts": h["rec"] + h["rec_yds"] / 10,
    })

rows.sort(key=lambda r: -r["ypc"])
print("Pass catchers sorted by yards per catch (2025, 30+ catches)")
print("'PPR rank' is where they'd rank among this group in a normal PPR league;")
print("'real rank' is where they actually finished under our scoring.\n")

ppr_order = {r["player"]: i + 1 for i, r in enumerate(sorted(rows, key=lambda r: -r["ppr_pts"]))}
real_order = {r["player"]: i + 1 for i, r in enumerate(sorted(rows, key=lambda r: -r["total"]))}
for r in rows:
    r["shift"] = ppr_order[r["player"]] - real_order[r["player"]]

print(f"{'player':24} {'pos':4} {'board':>5} {'ypc':>5} {'rec':>4} {'yds':>5} {'pts':>4} "
      f"{'PPR rk':>7} {'real rk':>8} {'shift':>6}")
for r in sorted(rows, key=lambda r: -r["shift"]):
    tag = "" if r["owner"] else "  FREE"
    print(f"{r['player']:24} {r['pos']:4} {r['rank']:>5} {r['ypc']:>5.1f} {r['rec']:>4} {r['yds']:>5} "
          f"{r['total']:>4} {ppr_order[r['player']]:>7} {real_order[r['player']]:>8} {r['shift']:>+6}{tag}")
