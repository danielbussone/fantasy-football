import csv
import json
import re
from pathlib import Path

PLAYER_POS = {"QB", "RB", "WR", "TE"}


def _norm(n):
    return re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", n.lower().strip()).replace(".", "")


def load(path):
    """Read a ranking CSV, drop K/DST, and re-rank 1..N among skill players only."""
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if r["pos"] in PLAYER_POS]
    rows.sort(key=lambda r: int(r["rank"]))
    return {(r["player"], r["team"]): (i, r) for i, r in enumerate(rows, 1)}


dyn = load("dynasty.csv")
red = load("redraft.csv")

MY_TEAM = "BUSSONE"

# drafted.csv also carries kicker and defense picks, which are unranked by
# design and stored with the position in the team column (e.g. "...,Seahawks,DST").
# They are held out of the owner lookup here so they can never collide with a
# ranked player, and passed through untouched -- make_canvas.py reads them back
# out of drafted.csv directly and puts them on the roster and the pick counter.
UNRANKED_POS = {"K", "DST"}
# CBS live roster is canonical once cbs_roster.csv exists. drafted.csv is the
# fallback / canvas pick log. Ranking math below does not change.
_cbs_path = Path("cbs_roster.csv")
owners_by_name = {}
if _cbs_path.exists():
    cbs = list(csv.DictReader(open(_cbs_path, encoding="utf-8")))
    unranked = [
        {"player": r["player"], "team": r["pos"], "owner": r["owner"]}
        for r in cbs
        if r.get("pos") in UNRANKED_POS
    ]
    owners = {
        (r["player"], r["team"]): r["owner"]
        for r in cbs
        if r.get("pos") not in UNRANKED_POS
    }
    owners_by_name = {
        _norm(r["player"]): r["owner"]
        for r in cbs
        if r.get("pos") not in UNRANKED_POS
    }
    drafted = cbs
    owner_src = "cbs_roster.csv"
else:
    drafted = list(csv.DictReader(open("drafted.csv", encoding="utf-8")))
    unranked = [d for d in drafted if d["team"] in UNRANKED_POS]
    owners = {
        (d["player"], d["team"]): d["owner"] for d in drafted if d["team"] not in UNRANKED_POS
    }
    owner_src = "drafted.csv"

# Anyone absent from a list is slotted one spot past that list's last player.
dyn_penalty = len(dyn) + 1
red_penalty = len(red) + 1

merged = []
for key in set(dyn) | set(red):
    name, team = key
    d = dyn.get(key)
    r = red.get(key)
    row = (d or r)[1]
    d_rank = d[0] if d else None
    r_rank = r[0] if r else None
    merged.append(
        {
            "player": name,
            "team": team,
            "pos": row["pos"],
            "age": (dyn[key][1].get("age") or "") if key in dyn else "",
            "status": row.get("status") or "",
            "dynasty": d_rank,
            "redraft": r_rank,
            "score": round(((d_rank or dyn_penalty) + (r_rank or red_penalty)) / 2, 1),
            "owner": owners.get(key) or owners_by_name.get(_norm(name), ""),
        }
    )

merged.sort(key=lambda x: (x["score"], min(x["dynasty"] or 9999, x["redraft"] or 9999)))

for i, m in enumerate(merged, 1):
    m["rank"] = i
    m["gap"] = (m["redraft"] - m["dynasty"]) if m["dynasty"] and m["redraft"] else None

cols = ["rank", "player", "team", "pos", "age", "status", "dynasty", "redraft", "score", "gap", "owner"]
with open("combined.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    for m in merged:
        w.writerow({c: ("" if m[c] is None else m[c]) for c in cols})

with open("combined.json", "w", encoding="utf-8") as f:
    json.dump(merged, f)

print(f"dynasty players: {len(dyn)}  redraft players: {len(red)}  combined: {len(merged)}")
print(f"penalty ranks -> dynasty {dyn_penalty}, redraft {red_penalty}")
matched = sum(1 for m in merged if m["owner"])
print(f"{owner_src} rows: {len(drafted)} -> {matched} matched to the board, "
      f"{len(unranked)} unranked K/DST kept out of the rankings")
if unranked:
    print("  unranked: " + ", ".join(f"{d['player']} ({d['team']}) {d['owner']}" for d in unranked))
missing = [
    d for d in drafted
    if (d.get("pos") or d.get("team")) not in UNRANKED_POS
    and (d["player"], d.get("team")) not in dyn
    and (d["player"], d.get("team")) not in red
]
if missing:
    print("  WARNING, drafted but not on either ranking list: "
          + ", ".join(f"{d['player']} ({d['team']})" for d in missing))
print()
avail = [m for m in merged if not m["owner"]]
mine = [m for m in merged if m["owner"] == MY_TEAM]

print(f"{MY_TEAM} roster: " + ", ".join(f"{m['player']} ({m['pos']})" for m in mine))
print()
print("Best available overall")
print(f"{'#':>3} {'player':24} {'pos':4} {'dyn':>4} {'red':>4} {'score':>6}")
for m in avail[:15]:
    print(
        f"{m['rank']:>3} {m['player']:24} {m['pos']:4} "
        f"{str(m['dynasty'] or '-'):>4} {str(m['redraft'] or '-'):>4} {m['score']:>6}"
    )
print()
for p in ("RB", "TE", "QB", "WR"):
    top = [m for m in avail if m["pos"] == p][:5]
    print(f"{p}: " + ", ".join(f"{m['player']} ({m['rank']})" for m in top))
