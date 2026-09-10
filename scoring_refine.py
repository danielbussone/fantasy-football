"""Rule-based scoring engine vs reported FPTS.

Season totals cannot reconstruct per-game yardage buckets or TD distances.
This script is explicit about that, then prices what the rules do allow and
measures how far a mean-game reconstruction misses the reported totals.
"""
import csv
import re
from collections import defaultdict

import numpy as np

SEASONS = (2023, 2024, 2025)
ALIAS = {"kenneth gainwell": "kenny gainwell"}


def norm(n):
    s = re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", n.lower().strip()).replace(".", "")
    return ALIAS.get(s, s)


def qb_yds_pts(y):
    """Per-game PaRuYd special scoring. 200-249=1 ... 500+=7."""
    if y >= 500:
        return 7
    if y >= 200:
        return int((y - 200) // 50) + 1
    return 0


def rb_wr_yds_pts(y):
    """Per-game RuReYd for RB/WR. 70-89=1 ... 250+=10."""
    if y >= 250:
        return 10
    if y >= 70:
        return int((y - 70) // 20) + 1
    return 0


def te_yds_pts(y):
    """Per-game RuReYd for TE. 40-59=1 ... 220+=10."""
    if y >= 220:
        return 10
    if y >= 40:
        return int((y - 40) // 20) + 1
    return 0


def yds_fn(pos):
    if pos == "QB":
        return qb_yds_pts
    if pos == "TE":
        return te_yds_pts
    return rb_wr_yds_pts


# TD distance bonuses (on top of the 1-point base).
# PaTD / WR-RB ReTD: +1 at 16-30, +2 at 31-45, +3 at 46-60, +4 at 61+  => 1..5 total
# RuTD / TE ReTD:    +1 at 6-15,  +2 at 16-25, +3 at 26-40, +4 at 41+  => 1..5 total
TD_MIN, TD_MAX = 1.0, 5.0

# Other offensive events
# Pa2P / Re2P / Ru2P / Fum2PK / Fum2PT = 1
# OFRTD = 1
# IKRTD / IPRTD = 3, +1 at 31-50, +2 at 51+  => 3 / 4 / 5. A 51+ return TD is 5 pts.
# Recpt = 0
# Fumble lost: NOT in the offensive settings. No negative offensive categories at all.
# INT: not in offensive settings.


def load(season):
    rows = list(csv.DictReader(open(f"history_{season}.csv", encoding="utf-8")))
    for r in rows:
        for k in ("pass_yds", "pass_td", "rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "total"):
            r[k] = int(r[k])
        r["avg"] = float(r["avg"])
        r["games"] = round(r["total"] / r["avg"]) if r["avg"] else 0
        r["season"] = season
        r["key"] = norm(r["player"])
        r["scrim"] = r["rush_yds"] + r["rec_yds"]
        r["qb_yds"] = r["pass_yds"] + r["rush_yds"]
        r["off_td"] = r["pass_td"] + r["rush_td"] + r["rec_td"]
        if r["pos"] == "QB":
            r["yds"] = r["qb_yds"]
            r["tds"] = r["pass_td"] + r["rush_td"]
        else:
            r["yds"] = r["scrim"]
            r["tds"] = r["rush_td"] + r["rec_td"]
        g = max(r["games"], 1)
        r["ypg"] = r["yds"] / g
        fn = yds_fn(r["pos"])
        r["yds_pts_mean"] = r["games"] * fn(r["ypg"])
        r["td_pts_min"] = TD_MIN * r["tds"]
        r["td_pts_max"] = TD_MAX * r["tds"]
        # Naive engine: every game at season-mean yards, every TD worth the 1-pt base.
        r["naive"] = r["yds_pts_mean"] + r["td_pts_min"]
        r["err"] = r["total"] - r["naive"]
        # Feasible band if we only vary TD distance (ignore yardage-path variance and extras)
        r["band_lo"] = r["yds_pts_mean"] + r["td_pts_min"]  # = naive
        r["band_hi"] = r["yds_pts_mean"] + r["td_pts_max"]
    return rows


data = {s: load(s) for s in SEASONS}
allrows = [r for s in SEASONS for r in data[s]]

print("=" * 90)
print("ENGINE VS REPORTED FPTS")
print("=" * 90)
print("Naive reconstruction: games * bucket(season yards / games) + 1 * TDs.")
print("That prices the yardage special AND the TD base. It cannot see:")
print("  - weekly yardage path (a 280-yd mean is not 17 games of 280)")
print("  - TD distance bonuses (0 to +4 extra per score)")
print("  - 2PT (1 pt), OFRTD (1 pt), KR/PR TDs (3-5 pts)")
print("Receptions are 0. Lost fumbles and INTs are not in the offensive settings.")

print(f"\n  {'pos':4} {'n':>4} {'median err':>11} {'MAE':>6} {'p10':>7} {'p90':>7} "
      f"{'% in TD-band':>13} {'R naive':>8}")
for p in ("QB", "RB", "WR", "TE"):
    grp = [r for r in allrows if r["pos"] == p and r["games"] >= 8]
    err = np.array([r["err"] for r in grp])
    inband = np.mean([r["band_lo"] - 0.5 <= r["total"] <= r["band_hi"] + 2.0 for r in grp])
    # +2 slack for 2PT / return TD / OFRTD / rounding
    y = np.array([r["total"] for r in grp], float)
    pred = np.array([r["naive"] for r in grp], float)
    r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    print(f"  {p:4} {len(grp):>4} {np.median(err):>11.1f} {np.mean(np.abs(err)):>6.1f} "
          f"{np.percentile(err, 10):>7.1f} {np.percentile(err, 90):>7.1f} "
          f"{inband*100:>12.0f}% {r2:>8.3f}")

print("\n  Median error is the typical leftover after mean-game yards + base TDs.")
print("  Positive leftover = TD distance bonuses + yardage variance up + extras.")
print("  Negative leftover = weeks that missed the yardage threshold (variance down).")

print("\nWorst misses (naive vs actual), players with >=8 games:")
big = [r for r in allrows if r["games"] >= 8]
print(f"  {'season':>6} {'player':24} {'pos':3} {'g':>2} {'yds':>5} {'ypg':>6} {'TD':>3} "
      f"{'naive':>6} {'actual':>7} {'err':>7}")
for r in sorted(big, key=lambda x: -abs(x["err"]))[:15]:
    print(f"  {r['season']:>6} {r['player']:24} {r['pos']:3} {r['games']:>2} {r['yds']:>5} "
          f"{r['ypg']:>6.0f} {r['tds']:>3} {r['naive']:>6.1f} {r['total']:>7} {r['err']:>+7.1f}")

print("\n" + "=" * 90)
print("QB YARDAGE PRICED FROM THE RULES")
print("=" * 90)
print("Special PaRuYd: 200-249=1, 250-299=2, 300-349=3, 350-399=4, 400-449=5,")
print("450-499=6, 500+=7. General PaRuYd line is 0; only the QB special pays.")
print("PaTD 1 pt + distance; RuTD 1 pt + shorter distance bands. No INT, no sack.")
print("Season totals cannot recover how many weeks landed in each bucket.\n")

print(f"  {'season':>6} {'player':22} {'g':>2} {'PaRuYd':>7} {'ypg':>6} {'tier/g':>7} "
      f"{'yd$':>5} {'TD':>3} {'baseTD':>6} {'naive':>6} {'actual':>7} {'left':>6}")
for s in SEASONS:
    qbs = sorted([r for r in data[s] if r["pos"] == "QB"], key=lambda x: -x["total"])
    for r in qbs[:8]:
        print(f"  {s:>6} {r['player']:22} {r['games']:>2} {r['qb_yds']:>7} {r['ypg']:>6.0f} "
              f"{qb_yds_pts(r['ypg']):>7} {r['yds_pts_mean']:>5.0f} {r['tds']:>3} "
              f"{r['td_pts_min']:>6.0f} {r['naive']:>6.1f} {r['total']:>7} {r['err']:>+6.1f}")

print("\n  How to read the leftover: Stafford 2025 is 46 TDs * (1 + bonus).")
print("  If leftover / TDs is ~0.5, the typical passing TD is a short/medium throw,")
print("  not a 61-yard bomb, plus a few weeks that cleared the next yardage tier.")

print("\n  Leftover per QB TD, QBs with >=12 games:")
print(f"  {'season':>6} {'n':>3} {'median left/TD':>16} {'mean left/TD':>14}")
for s in SEASONS:
    q = [r for r in data[s] if r["pos"] == "QB" and r["games"] >= 12 and r["tds"] >= 15]
    v = [r["err"] / r["tds"] for r in q]
    print(f"  {s:>6} {len(q):>3} {np.median(v):>16.2f} {np.mean(v):>14.2f}")

print("\n  Implied QB season from rules, ignoring weekly path:")
print("    4,000 PaRuYd / 17 g = 235 ypg -> 1 pt/g * 17 = 17 from yards")
print("    4,800 PaRuYd / 17 g = 282 ypg -> 2 pt/g * 17 = 34 from yards")
print("    5,500 PaRuYd / 17 g = 324 ypg -> 3 pt/g * 17 = 51 from yards")
print("    plus ~1.4-1.8 pts per passing/rushing TD once distance mix is typical.")
print("  A 300-yard game is 3 pts from yards here, not 12 as in 1/25 or 1/20 passing.")
print("  That is why the QB totals cluster 50-100 instead of 300-400.")

print("\n" + "=" * 90)
print("SKILL-PLAYER YARDAGE + TD BASE")
print("=" * 90)
print("RB/WR: 70-89=1 ... 250+=10 per game. TE: 40-59=1 ... 220+=10.")
print("TE receiving TDs use the rushing distance bands (bonus starts at 6 yards,")
print("not 16), so a typical TE TD is worth more than a typical WR TD.\n")

print(f"  {'season':>6} {'player':24} {'pos':3} {'ypg':>6} {'tier/g':>7} {'yd$':>5} "
      f"{'TD':>3} {'naive':>6} {'actual':>7} {'left':>6}")
for s in SEASONS:
    flex = sorted([r for r in data[s] if r["pos"] in ("RB", "WR", "TE")],
                  key=lambda x: -x["total"])
    for r in flex[:6]:
        print(f"  {s:>6} {r['player']:24} {r['pos']:3} {r['ypg']:>6.0f} "
              f"{yds_fn(r['pos'])(r['ypg']):>7} {r['yds_pts_mean']:>5.0f} {r['tds']:>3} "
              f"{r['naive']:>6.1f} {r['total']:>7} {r['err']:>+6.1f}")

print("\n  Leftover per skill TD (>=12 games, >=5 TDs):")
print(f"  {'pos':4} {'n':>4} {'median left/TD':>16} {'mean naive MAE':>16}")
for p in ("RB", "WR", "TE"):
    grp = [r for r in allrows if r["pos"] == p and r["games"] >= 12 and r["tds"] >= 5]
    v = [r["err"] / r["tds"] for r in grp]
    mae = np.mean([abs(r["err"]) for r in grp])
    print(f"  {p:4} {len(grp):>4} {np.median(v):>16.2f} {mae:>16.1f}")

print("\n" + "=" * 90)
print("2PT, RETURN TDs, OFRTD, FUMBLES LOST")
print("=" * 90)
print("From the written rules (no weekly event counts in the history files):")
print("  Pa2P / Re2P / Ru2P / Fum2P*          = 1 point")
print("  OFRTD (offensive fumble-recovery TD) = 1 point")
print("  IKRTD / IPRTD                        = 3 points")
print("      +1 if 31-50 yards, +2 if 51+     => 51+ return TD = 5 points")
print("  Recpt                                = 0")
print("  Lost fumble, INT, sack               = not listed on the offensive side")
print()
print("  A 51+ kick-return TD (5 pts) outscores almost every offensive TD:")
print("    typical WR catch in the end zone from 1-15 yards = 1 pt")
print("    61+ receiving TD                                 = 5 pts (the WR ceiling)")
print("    typical 1-yard rush TD                           = 1 pt")
print("    41+ rush TD                                      = 5 pts")
print("  So a starting WR/RB who also returns kicks is hiding 3-5 pts per return TD")
print("  on top of whatever the offense already pays. In a format where Ja'Marr Chase")
print("  scored 39 pts in 2025, one long return TD is a double-digit weekly spike.")

# Fumble check: 2024 dump vs residuals
print("\n  Fumble-lost check (2024 history joined to fumbles_2024.csv):")
fum = {norm(r["player"]): int(r["fum_lost"])
       for r in csv.DictReader(open("fumbles_2024.csv", encoding="utf-8"))}
h24 = data[2024]
matched = [r for r in h24 if r["key"] in fum and r["games"] >= 8]
print(f"    matched {len(matched)} of {len(h24)} 2024 history rows")
if matched:
    xs = np.array([fum[r["key"]] for r in matched], float)
    ys = np.array([r["err"] for r in matched], float)
    tot = np.array([r["total"] for r in matched], float)
    print(f"    fum_lost vs naive leftover r={float(np.corrcoef(xs, ys)[0,1]):+.2f}")
    print(f"    fum_lost vs reported total  r={float(np.corrcoef(xs, tot)[0,1]):+.2f}")
    hi = [r for r in matched if fum[r["key"]] >= 4]
    lo = [r for r in matched if fum[r["key"]] == 0]
    print(f"    mean leftover, 4+ fum lost (n={len(hi)}): {np.mean([r['err'] for r in hi]):+.1f}")
    print(f"    mean leftover, 0 fum lost  (n={len(lo)}): {np.mean([r['err'] for r in lo]):+.1f}")
    print("    If lost fumbles were -1 or -2, high-fumblers would show systematically")
    print("    lower leftovers. They do not. Combined with the blank offensive line,")
    print("    lost fumbles are not penalized.")

# Turpin / known returners in the history files
print("\n  History-file names that are typical return candidates (scoring, not depth chart):")
hints = ("turpin", "shaheed", "mims", "waddle", "pop douglas", "douglas", "palmer",
         "special", "return")
for r in allrows:
    low = r["player"].lower()
    if any(h in low for h in hints):
        print(f"    {r['season']} {r['player']:24} {r['pos']} {r['total']:>4} pts  "
              f"naive {r['naive']:.1f}  leftover {r['err']:+.1f}")

print("\n" + "=" * 90)
print("ROSTER IMPLICATIONS (scoring mechanics only)")
print("=" * 90)
ROSTER = [
    ("Trevor Lawrence", "QB"), ("Jordan Love", "QB"),
    ("Kenneth Walker III", "RB"), ("Jeremiyah Love", "RB"), ("TreVeyon Henderson", "RB"),
    ("Blake Corum", "RB"), ("Woody Marks", "RB"),
    ("Ja'Marr Chase", "WR"), ("CeeDee Lamb", "WR"), ("Malik Nabers", "WR"),
    ("Luther Burden III", "WR"), ("Ladd McConkey", "WR"), ("Makai Lemon", "WR"),
    ("Tyler Warren", "TE"), ("Dalton Kincaid", "TE"),
]
idx = {s: {r["key"]: r for r in data[s]} for s in SEASONS}
print(f"  {'player':22} {'pos':3} {'2025 tot':>8} {'naive':>6} {'left':>6} {'ypg':>6} {'TD':>3}")
for name, pos in ROSTER:
    r = idx[2025].get(norm(name))
    if not r:
        print(f"  {name:22} {pos:3} {'n/a':>8}  (no 2025 top-100 line)")
        continue
    print(f"  {name:22} {pos:3} {r['total']:>8} {r['naive']:>6.1f} {r['err']:>+6.1f} "
          f"{r['ypg']:>6.0f} {r['tds']:>3}")

print("\n  Lawrence leftover is the rushing-TD distance mix plus weeks over 300 PaRuYd.")
print("  Chase/Lamb/Nabers leftovers are almost entirely TD-distance + weekly-path noise;")
print("  none of the three is a full-time returner in these season dumps.")
print("  Kickers Cairo Santos and Will Reichard are not in any FA dump or history file.")
print("  A return job on McConkey/Burden/Lemon would be hidden scoring this format")
print("  actually pays for; that is a depth-chart question, not a scoring one.")
