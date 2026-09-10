"""Kicker scoring verification, VOR, repeatability, and long-range vs chip-shot value.

FA dumps only: rostered kickers (Santos, Reichard, other starters) are absent.
Site buckets 1-19/20-29/30-39/40-49/50+ do not match scoring 1-40/41-50/51-59/60+.
"""
import csv
from collections import defaultdict

import numpy as np

SEASONS = (2023, 2024, 2025)


def load(season):
    rows = list(csv.DictReader(open(f"kicker_{season}_fa.csv", encoding="utf-8")))
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
        r["games"] = round(r["total"] / r["avg"]) if r["avg"] else 0
        r["short"] = r["m_1_19"] + r["m_20_29"] + r["m_30_39"]  # all 1-39, definitely 1 pt
        # sanity: made FGs should sum
        r["made_sum"] = r["short"] + r["m_40_49"] + r["m_50"]
    rows.sort(key=lambda x: -x["total"])
    return rows


data = {s: load(s) for s in SEASONS}
allrows = [r for s in SEASONS for r in data[s]]

# Adopted reading: no base FG. A make is worth exactly its distance tier:
# 1-40 = 1, 41-50 = 2, 51-59 = 3, 60+ = 3.5. XP = 0.5.
# Site 40-49 mixes 40-yd (1 pt) with 41-49 (2 pt).
# Site 50+ mixes 50-yd (2 pt) with 51-59 (3) and 60+ (3.5).


def pred_bounds(r):
    xp = 0.5 * r["xp"]
    lo = xp + 1.0 * r["short"] + 1.0 * r["m_40_49"] + 2.0 * r["m_50"]
    # mid: 40-49 treated as 41-49 (2), 50+ treated as 51-59 (3). Ignores 40s, 50s, 60s.
    mid = xp + 1.0 * r["short"] + 2.0 * r["m_40_49"] + 3.0 * r["m_50"]
    hi = xp + 1.0 * r["short"] + 2.0 * r["m_40_49"] + 3.5 * r["m_50"]
    return lo, mid, hi


print("=" * 88)
print("READING ADOPTED: FG = exact distance-tier value (1 / 2 / 3 / 3.5). No base FG line.")
print("XP = 0.50. Misses score 0. Site buckets straddle the 40-yd and 50-yd scoring cuts.")
print("=" * 88)

# Smoking-gun rows: no 50+ makes, so the only uncertainty is 40-yd vs 41-49.
print("\nClean checks (no 50+ makes) -- predicted must match within the 40-yard 1-vs-2 swing:")
print(f"  {'season':>6} {'player':22} {'short':>5} {'40-49':>5} {'XP':>3} {'actual':>7} "
      f"{'if all 40s':>10} {'if all 41-49':>12} {'in range':>8}")
n_clean = n_clean_ok = 0
for r in allrows:
    if r["m_50"]:
        continue
    lo, mid, hi = pred_bounds(r)
    ok = lo - 1e-6 <= r["total"] <= hi + 1e-6
    n_clean += 1
    n_clean_ok += int(ok)
    print(f"  {r['season']:>6} {r['player']:22} {r['short']:>5} {r['m_40_49']:>5} {r['xp']:>3} "
          f"{r['total']:>7.2f} {lo:>10.2f} {hi:>12.2f} {'YES' if ok else 'NO':>8}")
print(f"  {n_clean_ok}/{n_clean} clean rows fall inside the 40-yard bound.")

print("\nAll rows vs [lower, mid, upper]. Mid = 40-49 as 2 pts, 50+ as 3 pts.")
print(f"  {'season':>6} {'player':22} {'actual':>7} {'lo':>7} {'mid':>7} {'hi':>7} "
      f"{'act-mid':>8} {'in [lo,hi]':>10}")
n_ok = n_mid_close = 0
misses = []
for r in allrows:
    lo, mid, hi = pred_bounds(r)
    ok = lo - 1e-6 <= r["total"] <= hi + 1e-6
    n_ok += int(ok)
    err = r["total"] - mid
    if abs(err) <= 1.51:
        n_mid_close += 1
    misses.append((abs(err), err, r, lo, mid, hi, ok))
    flag = "YES" if ok else "NO"
    print(f"  {r['season']:>6} {r['player']:22} {r['total']:>7.2f} {lo:>7.2f} {mid:>7.2f} "
          f"{hi:>7.2f} {err:>+8.2f} {flag:>10}")
print(f"\n  {n_ok}/{len(allrows)} rows inside hard bounds.")
print(f"  {n_mid_close}/{len(allrows)} within 1.5 pts of the mid model (40-49=2, 50+=3).")
print("  act-mid < 0  => some 40-yarders (1 not 2) and/or exact-50s (2 not 3).")
print("  act-mid > 0  => some 60+ makes (3.5 not 3).")

print("\nLargest |actual - mid| (boundary mix, not a failed scoring rule):")
for aerr, err, r, lo, mid, hi, ok in sorted(misses, key=lambda x: -x[0])[:8]:
    print(f"  {r['season']} {r['player']:22} actual {r['total']:.2f}  mid {mid:.2f}  "
          f"delta {err:+.2f}  50+ {r['m_50']}/{r['a_50']}  40-49 {r['m_40_49']}")

# Recover coefficients by OLS: total ~ short + m_40_49 + m_50 + xp
print("\n" + "=" * 88)
print("OLS RECOVERY OF THE TIER VALUES (pooled FA rows)")
print("=" * 88)
X = np.column_stack([
    np.array([r["short"] for r in allrows], float),
    np.array([r["m_40_49"] for r in allrows], float),
    np.array([r["m_50"] for r in allrows], float),
    np.array([r["xp"] for r in allrows], float),
])
y = np.array([r["total"] for r in allrows], float)
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
pred = X @ coef
r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
print(f"  1-39 FG:   {coef[0]:.3f}  (rule 1.00)")
print(f"  40-49 FG:  {coef[1]:.3f}  (rule 1 or 2; expect ~1.8-2.0 if most are 41-49)")
print(f"  50+ FG:    {coef[2]:.3f}  (rule 2 / 3 / 3.5; expect ~3.0 if most are 51-59)")
print(f"  XP:        {coef[3]:.3f}  (rule 0.50)")
print(f"  R^2 {r2:.4f}  (no intercept; misses score 0)")

print("\n" + "=" * 88)
print("K1-K10 SPREAD  (FA pool is a LOWER BOUND on the true top)")
print("=" * 88)
print("  Rostered kickers are missing, so FA K1 <= true K1. Replacement K10 among all")
print("  NFL kickers is also higher than FA K10 once rostered names are inserted at the top.")
print(f"  {'season':>7} {'n':>3} {'K1':>7} {'K5':>7} {'K10':>7} {'K1-K10':>8} {'K1 VOR':>8} {'K5 VOR':>8}  K1 name")
for s in SEASONS:
    d = [x["total"] for x in data[s]]
    k1, k5, k10 = d[0], d[4], d[9]
    print(f"  {s:>7} {len(d):>3} {k1:>7.1f} {k5:>7.1f} {k10:>7.1f} {k1-k10:>8.1f} "
          f"{k1-k10:>8.1f} {k5-k10:>8.1f}  {data[s][0]['player']}")

print("\n  2025 FA top 10 (currently on waivers, 2025 FPTS):")
for i, r in enumerate(data[2025][:10], 1):
    print(f"    K{i:<2} {r['player']:22} {r['total']:>6.1f}   "
          f"{r['short']:>2} short  {r['m_40_49']:>2} from 40-49  {r['m_50']:>2}/{r['a_50']} from 50+  "
          f"{r['xp']} XP")

# Skill-player context for 2025
skill = list(csv.DictReader(open("history_2025.csv", encoding="utf-8")))
for r in skill:
    r["total"] = int(r["total"])
skill.sort(key=lambda x: -x["total"])


def overall_rank(pts):
    return sum(1 for r in skill if r["total"] > pts) + 1


print("\n  Where 2025 FA kickers would rank among the top-100 skill-player dump:")
for i in (0, 4, 9):
    r = data[2025][i]
    print(f"    FA K{i+1} {r['player']:22} {r['total']:>6.1f}  would rank #{overall_rank(r['total'])} "
          f"among skill players (ahead of {sum(1 for p in skill if p['total'] < r['total'])} of them)")

print("\n" + "=" * 88)
print("YEAR-OVER-YEAR REPEATABILITY  (join current-FA kickers by name)")
print("=" * 88)
print("  These lists are the Sept 2026 waiver pool, season-filtered. A kicker who is")
print("  rostered now is missing in EVERY year, so this is stickiness among leftovers,")
print("  not among the true positional universe. Retention is biased DOWN: anyone who")
print("  got rostered after a big year vanishes from the next FA list.")


def corr(xs, ys):
    if len(xs) < 3:
        return float("nan")
    return float(np.corrcoef(xs, ys)[0, 1])


def spearman(xs, ys):
    def rk(v):
        return np.argsort(np.argsort(-np.array(v))).astype(float)
    return corr(rk(xs), rk(ys))


idx = {s: {r["player"]: r for r in data[s]} for s in SEASONS}
rank = {s: {r["player"]: i + 1 for i, r in enumerate(data[s])} for s in SEASONS}

for a, b in ((2023, 2024), (2024, 2025), (2023, 2025)):
    names = sorted(set(idx[a]) & set(idx[b]))
    xs = [idx[a][n]["total"] for n in names]
    ys = [idx[b][n]["total"] for n in names]
    print(f"\n  {a}->{b}: n={len(names)}  points r={corr(xs, ys):+.2f}  "
          f"rank r={spearman(xs, ys):+.2f}  r^2={corr(xs, ys)**2:.2f}")
    top5 = [r["player"] for r in data[a][:5]]
    kept10 = [n for n in top5 if n in rank[b] and rank[b][n] <= 10]
    missing = [n for n in top5 if n not in rank[b]]
    dropped = [n for n in top5 if n in rank[b] and rank[b][n] > 10]
    print(f"    {a} FA top-5 -> {b} FA top-10: {len(kept10)} of 5 stayed")
    print("    " + ", ".join(
        f"{n} K{rank[a][n]}->" + (f"K{rank[b][n]}" if n in rank[b] else "absent")
        for n in top5
    ))
    if missing:
        print(f"    absent from {b} FA list (rostered, retired, or no stats): {', '.join(missing)}")
    if dropped:
        print(f"    present but outside top-10: {', '.join(dropped)}")

print("\n  Chase McLaughlin, three-year FA line:")
for s in SEASONS:
    r = idx[s].get("Chase McLaughlin")
    if r:
        print(f"    {s}: {r['total']:>6.1f}  {r['fg']}/{r['fg_att']} FG  "
              f"{r['m_50']}/{r['a_50']} from 50+  {r['xp']}/{r['xp_att']} XP  {r['avg']:.2f}/g")

print("\n  Kickers present in all three FA seasons, sorted by 2025 total:")
all3 = sorted(set(idx[2023]) & set(idx[2024]) & set(idx[2025]),
              key=lambda n: -idx[2025][n]["total"])
print(f"  {'player':22} {'2023':>7} {'2024':>7} {'2025':>7} {'mean':>7}")
for n in all3:
    a, b, c = idx[2023][n]["total"], idx[2024][n]["total"], idx[2025][n]["total"]
    print(f"  {n:22} {a:>7.1f} {b:>7.1f} {c:>7.1f} {(a+b+c)/3:>7.1f}")

print("\n" + "=" * 88)
print("LONG-RANGE VOLUME VS CHIP-SHOT VOLUME")
print("=" * 88)
print("  Mid-model point split (1 / 2 / 3 / 0.5), as a share of predicted total.")
print(f"  {'season':>6} {'player':22} {'pts':>6} {'short$':>7} {'40-49$':>7} {'50+$':>6} "
      f"{'XP$':>6} {'50+ shr':>8} {'50+ makes':>10}")

# Does 50+ volume predict total better than short volume?
for s in SEASONS:
    rows = [r for r in data[s] if r["fg"] >= 10]
    print(f"\n  {s}  (kickers with 10+ makes)")
    for r in rows[:8]:
        short_p = 1.0 * r["short"]
        mid_p = 2.0 * r["m_40_49"]
        long_p = 3.0 * r["m_50"]
        xp_p = 0.5 * r["xp"]
        pred = short_p + mid_p + long_p + xp_p
        shr = long_p / pred if pred else 0
        print(f"  {s:>6} {r['player']:22} {r['total']:>6.1f} {short_p:>7.1f} {mid_p:>7.1f} "
              f"{long_p:>6.1f} {xp_p:>6.1f} {shr*100:>7.0f}%  {r['m_50']:>3}/{r['a_50']:<3}")

print("\n  Pooled correlations with season total (all FA rows, 10+ FG):")
big = [r for r in allrows if r["fg"] >= 10]
print(f"    n={len(big)}")
print(f"    vs 1-39 makes:   r={corr([r['short'] for r in big], [r['total'] for r in big]):+.2f}")
print(f"    vs 40-49 makes:  r={corr([r['m_40_49'] for r in big], [r['total'] for r in big]):+.2f}")
print(f"    vs 50+ makes:    r={corr([r['m_50'] for r in big], [r['total'] for r in big]):+.2f}")
print(f"    vs XP makes:     r={corr([r['xp'] for r in big], [r['total'] for r in big]):+.2f}")
print(f"    vs FG makes:     r={corr([r['fg'] for r in big], [r['total'] for r in big]):+.2f}")
print(f"    vs 50+ attempts: r={corr([r['a_50'] for r in big], [r['total'] for r in big]):+.2f}")

# Holding FG count fixed: residual of total ~ FG + XP, then correlate residual with 50+ makes
X2 = np.column_stack([
    np.array([r["fg"] for r in big], float),
    np.array([r["xp"] for r in big], float),
    np.ones(len(big)),
])
y2 = np.array([r["total"] for r in big], float)
c2, *_ = np.linalg.lstsq(X2, y2, rcond=None)
resid = y2 - X2 @ c2
print(f"\n  After controlling for FG makes + XP, residual vs 50+ makes: "
      f"r={corr(resid, [r['m_50'] for r in big]):+.2f}")
print(f"  residual vs 1-39 makes: r={corr(resid, [r['short'] for r in big]):+.2f}")
print("  Same number of makes is not the same: swapping a chip-shot for a 50+ is +2 pts.")

print("\n  Illustrative 2025 mix: McLaughlin 11/12 from 50+ vs Patterson 3/4 from 50+")
m, p = idx[2025]["Chase McLaughlin"], idx[2025]["Riley Patterson"]
print(f"    McLaughlin  {m['fg']} FG, {m['m_50']} from 50+, {m['xp']} XP -> {m['total']:.1f}")
print(f"    Patterson   {p['fg']} FG, {p['m_50']} from 50+, {p['xp']} XP -> {p['total']:.1f}")
print(f"    Patterson made 5 fewer FGs but 2 more XP; the 8-extra 50+ makes are the gap.")

print("\n" + "=" * 88)
print("WHAT A ROSTERED-KICKER DUMP WOULD CLOSE")
print("=" * 88)
print("  Need the same distance-bucket table WITHOUT the FA filter, or at least")
print("  Cairo Santos (CHI) and Will Reichard (MIN) plus every other currently")
print("  rostered starter (Aubrey, Boswell, Bates, etc.). Even better: split 50+")
print("  into 50 / 51-59 / 60+ and split 40-49 into 40 / 41-49 so the bounds collapse.")
print("  Weekly FG distances would let us price the engine exactly instead of bounding.")
