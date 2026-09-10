"""Full-board kicker analysis for 2023-2025. Reads kicker_YYYY.csv (all kickers)."""
import csv

import numpy as np

SEASONS = (2023, 2024, 2025)


def load(season):
    rows = list(csv.DictReader(open(f"kicker_{season}.csv", encoding="utf-8")))
    ints = (
        "fg", "fg_att", "m_1_19", "a_1_19", "m_20_29", "a_20_29",
        "m_30_39", "a_30_39", "m_40_49", "a_40_49", "m_50", "a_50",
        "xp", "xp_att",
    )
    for r in rows:
        for k in ints:
            r[k] = int(r[k])
        r["avg"] = float(r["avg"])
        r["total"] = float(r["total"])
        r["season"] = season
        r["short"] = r["m_1_19"] + r["m_20_29"] + r["m_30_39"]
        r["games"] = round(r["total"] / r["avg"]) if r["avg"] else 0
    rows.sort(key=lambda x: -x["total"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def bounds(r):
    xp = 0.5 * r["xp"]
    lo = xp + 1.0 * r["short"] + 1.0 * r["m_40_49"] + 2.0 * r["m_50"]
    mid = xp + 1.0 * r["short"] + 2.0 * r["m_40_49"] + 3.0 * r["m_50"]
    hi = xp + 1.0 * r["short"] + 2.0 * r["m_40_49"] + 3.5 * r["m_50"]
    return lo, mid, hi


def corr(xs, ys):
    if len(xs) < 3:
        return float("nan")
    return float(np.corrcoef(xs, ys)[0, 1])


data = {s: load(s) for s in SEASONS}
allrows = [r for s in SEASONS for r in data[s]]

print("=" * 88)
print("ENGINE CHECK ON FULL BOARDS  (FG = 1/2/3/3.5, XP = 0.5, no base)")
print("=" * 88)
n_ok = n = 0
focus = []
for r in allrows:
    lo, mid, hi = bounds(r)
    n += 1
    n_ok += int(lo - 1e-6 <= r["total"] <= hi + 1e-6)
    if r["player"] in ("Will Reichard", "Cairo Santos", "Chase McLaughlin",
                       "Jason Myers", "Brandon Aubrey") or r["rank"] <= 3:
        focus.append((r, lo, mid, hi))
print(f"  {n_ok}/{n} rows inside [lo, hi] bounds")
print(f"  {'season':>6} {'rk':>3} {'player':22} {'own':10} {'actual':>7} {'mid':>7} {'act-mid':>8} {'50+':>8}")
for r, lo, mid, hi in focus:
    print(f"  {r['season']:>6} {r['rank']:>3} {r['player']:22} {r['owner']:10} {r['total']:>7.2f} "
          f"{mid:>7.2f} {r['total']-mid:>+8.2f} {r['m_50']:>3}/{r['a_50']}")

print("\n" + "=" * 88)
print("TRUE K1-K10  (full boards, 10 teams start one kicker)")
print("=" * 88)
print(f"  {'season':>7} {'n':>3} {'K1':>7} {'K5':>7} {'K10':>7} {'K1-K10':>8} {'K5 VOR':>8}  K1 / K10")
k10 = {}
for s in SEASONS:
    d = data[s]
    k1, k5, k10s = d[0]["total"], d[4]["total"], d[9]["total"]
    k10[s] = k10s
    print(f"  {s:>7} {len(d):>3} {k1:>7.1f} {k5:>7.1f} {k10s:>7.1f} {k1-k10s:>8.1f} "
          f"{k5-k10s:>8.1f}  {d[0]['player']} {k1:.1f} / {d[9]['player']} {k10s:.1f}")

print("\n  2025 full top 15:")
print(f"  {'rk':>3} {'owner':10} {'player':22} {'pts':>6} {'50+':>8} {'XP':>6} {'short':>6} {'40-49':>6}")
for r in data[2025][:15]:
    print(f"  {r['rank']:>3} {r['owner']:10} {r['player']:22} {r['total']:>6.1f} "
          f"{r['m_50']:>3}/{r['a_50']:<3} {r['xp']:>6} {r['short']:>6} {r['m_40_49']:>6}")

print("\n" + "=" * 88)
print("BUSSONE PAIR + MCLAUGHLIN, THREE-YEAR ARCS")
print("=" * 88)
names = ("Will Reichard", "Cairo Santos", "Chase McLaughlin", "Jason Myers")
idx = {s: {r["player"]: r for r in data[s]} for s in SEASONS}
print(f"  {'player':22} {'2023':>18} {'2024':>18} {'2025':>18}")
for n in names:
    cells = []
    for s in SEASONS:
        r = idx[s].get(n)
        if not r:
            cells.append(f"{'absent':>18}")
        else:
            cells.append(f"{r['total']:5.1f} K{r['rank']:<2} {r['m_50']}/{r['a_50']} 50+")
    print(f"  {n:22} " + " ".join(f"{c:>18}" for c in cells))

print("\n  VOR vs that year's true K10 (Borregales 68.5 in 2025; Myers 66.5 in 2024; Dicker 67.5 in 2023):")
print(f"  {'player':22} {'2023':>8} {'2024':>8} {'2025':>8}")
for n in names:
    cells = []
    for s in SEASONS:
        r = idx[s].get(n)
        cells.append(f"{r['total']-k10[s]:>+8.1f}" if r else f"{'n/a':>8}")
    print(f"  {n:22} " + " ".join(cells))

print("\n  Reichard vs Santos, same season:")
for s in (2024, 2025):
    a, b = idx[s]["Will Reichard"], idx[s]["Cairo Santos"]
    print(f"    {s}: Reichard {a['total']:.1f} (K{a['rank']}, {a['m_50']}/{a['a_50']} from 50+)  "
          f"vs Santos {b['total']:.1f} (K{b['rank']}, {b['m_50']}/{b['a_50']} from 50+)  "
          f"gap {a['total']-b['total']:+.1f}")

print("\n" + "=" * 88)
print("STICKINESS, FULL UNIVERSE  (join by player; Reichard has no 2023)")
print("=" * 88)
for a, b in ((2023, 2024), (2024, 2025), (2023, 2025)):
    nameset = sorted(set(idx[a]) & set(idx[b]))
    xs = [idx[a][n]["total"] for n in nameset]
    ys = [idx[b][n]["total"] for n in nameset]
    top5 = [r["player"] for r in data[a][:5]]
    kept = [n for n in top5 if n in idx[b] and idx[b][n]["rank"] <= 10]
    print(f"  {a}->{b}: n={len(nameset)}  r={corr(xs, ys):+.2f}  r^2={corr(xs, ys)**2:.2f}  "
          f"top-5 -> next top-10: {len(kept)} of 5")
    print("    " + ", ".join(
        f"{n} K{idx[a][n]['rank']}->" + (f"K{idx[b][n]['rank']}" if n in idx[b] else "gone")
        for n in top5
    ))

print("\n  K1 year-to-year is a lottery; K10 is a stable floor:")
for s in SEASONS:
    d = data[s]
    print(f"    {s} K1 {d[0]['player']:20} {d[0]['total']:.1f}   K10 {d[9]['player']:20} {d[9]['total']:.1f}")

# skill / DST context 2025
skill = list(csv.DictReader(open("history_2025.csv", encoding="utf-8")))
for r in skill:
    r["total"] = int(r["total"])
skill.sort(key=lambda x: -x["total"])
dst = [r for r in csv.DictReader(open("dst_history.csv", encoding="utf-8")) if r["season"] == "2025"]
for r in dst:
    r["total"] = float(r["total"])
dst.sort(key=lambda x: -x["total"])


def skill_rank(pts):
    return sum(1 for r in skill if r["total"] > pts) + 1


print("\n" + "=" * 88)
print("KICKER vs SKILL vs DST, 2025")
print("=" * 88)
print(f"  skill QB1 Stafford {skill[0]['total']}, DST1 Seahawks {dst[0]['total']:.0f}, DST10 {dst[9]['total']:.0f}")
print(f"  QB10 {[r for r in skill if r['pos']=='QB'][9]['player']} "
      f"{[r for r in skill if r['pos']=='QB'][9]['total']}")
for n in ("Jason Myers", "Brandon Aubrey", "Will Reichard", "Chase McLaughlin", "Cairo Santos"):
    r = idx[2025][n]
    print(f"  K{r['rank']:<2} {n:22} {r['total']:>5.1f}  skill-rank #{skill_rank(r['total'])}  "
          f"{'above DST10' if r['total'] > dst[9]['total'] else 'below DST10'}")

print("\n" + "=" * 88)
print("MCLAUGHLIN WAIVER vs HOLDING SANTOS  (roster max 2 K)")
print("=" * 88)
print("  You already roster Reichard (K6, 77) and Santos (K15, 62.5).")
print("  McLaughlin is the only FA in the 2025 true top 10 (K7, 75.5).")
s25, r25, m25 = idx[2025]["Cairo Santos"], idx[2025]["Will Reichard"], idx[2025]["Chase McLaughlin"]
print(f"  Dropping Santos {s25['total']:.1f} for McLaughlin {m25['total']:.1f} is a "
      f"+{m25['total']-s25['total']:.1f} season-points upgrade on last year.")
print(f"  But Reichard {r25['total']:.1f} vs McLaughlin {m25['total']:.1f} is "
      f"{r25['total']-m25['total']:+.1f} -- they are the same player last year.")
print(f"  Santos 2023 was K4 at 70.5 with 7/8 from 50+. That profile can return.")
print(f"  Two-season hold of both: Reichard is the start, Santos is the bye/matchup #2.")
print(f"  Streaming replacement is FA K11+ (Patterson 60, Folk 59) -- below Santos 62.5.")
