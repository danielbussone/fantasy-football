"""The QB/TE bargains skew old -- check how much of the discount is dynasty age, not skill."""
import csv
import re


def norm(n):
    return re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", n.lower().strip()).replace(".", "")


hist = {}
for h in csv.DictReader(open("history_2025.csv", encoding="utf-8")):
    h["total"] = int(h["total"])
    hist[norm(h["player"])] = h

rows = []
for b in csv.DictReader(open("combined.csv", encoding="utf-8")):
    k = norm(b["player"])
    if b["owner"] or k not in hist:
        continue
    h = hist[k]
    if h["pos"] in ("QB", "TE") and h["total"] >= 25:
        rows.append((-h["total"], b, h))

print(f"{'player':22} {'pos':4} {'board':>5} {'age':>4} {'dyn':>4} {'red':>4} {'2025':>5}  split")
for _, b, h in sorted(rows, key=lambda x: x[0]):
    dyn = int(b["dynasty"]) if b["dynasty"] else None
    red = int(b["redraft"]) if b["redraft"] else None
    note = ""
    if dyn and red:
        note = f"dynasty drags him {dyn - red:+d}" if abs(dyn - red) > 25 else ""
    print(f"{b['player']:22} {h['pos']:4} {b['rank']:>5} {b['age'] or '-':>4} "
          f"{b['dynasty'] or '-':>4} {b['redraft'] or '-':>4} {h['total']:>5}  {note}")
