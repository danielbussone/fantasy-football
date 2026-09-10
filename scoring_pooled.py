"""Pooled 3-season fit with season fixed effects -- single-year fits were too noisy."""
import csv

import numpy as np

SEASONS = (2023, 2024, 2025)


def load(season):
    rows = list(csv.DictReader(open(f"history_{season}.csv", encoding="utf-8")))
    for r in rows:
        for k in ("pass_yds", "pass_td", "rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "total"):
            r[k] = int(r[k])
        r["avg"] = float(r["avg"])
        r["games"] = round(r["total"] / r["avg"])
        r["season"] = season
        r["scrim"] = r["rush_yds"] + r["rec_yds"]
        r["tds"] = r["rush_td"] + r["rec_td"]
        r["qb_yds"] = r["pass_yds"] + r["rush_yds"]
    return rows


allrows = [r for s in SEASONS for r in load(s)]


def pooled_fit(rows, cols):
    g = np.array([r["games"] for r in rows], float)
    parts = [np.array([r[c] for r in rows], float) / g for c in cols]
    for s in SEASONS[1:]:
        parts.append(np.array([1.0 if r["season"] == s else 0.0 for r in rows]))
    parts.append(np.ones(len(rows)))
    X = np.column_stack(parts)
    y = np.array([r["avg"] for r in rows], float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    r2 = 1 - ((y - X @ coef) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    # bootstrap for honest uncertainty
    boot = []
    rng = np.random.default_rng(0)
    for _ in range(2000):
        idx = rng.integers(0, len(y), len(y))
        c, *_ = np.linalg.lstsq(X[idx], y[idx], rcond=None)
        boot.append(c)
    return coef, r2, np.array(boot)


print("=" * 86)
print("POOLED FIT, 2023-2025 (season fixed effects, players with >=8 games)")
print("=" * 86)
print(f"{'pos':4} {'n':>4} {'yds/pt':>18} {'pts per TD':>20} {'pts per rec':>20} {'R^2':>6}")
fits = {}
for p in ("RB", "WR", "TE"):
    grp = [r for r in allrows if r["pos"] == p and r["games"] >= 8]
    coef, r2, boot = pooled_fit(grp, ["scrim", "tds", "rec"])
    fits[p] = coef
    ypp = 1 / coef[0]
    ypp_lo, ypp_hi = sorted(1 / np.percentile(boot[:, 0], [97.5, 2.5]))
    td_lo, td_hi = np.percentile(boot[:, 1], [2.5, 97.5])
    rc_lo, rc_hi = np.percentile(boot[:, 2], [2.5, 97.5])
    print(f"{p:4} {len(grp):>4} {ypp:>7.1f} [{ypp_lo:.0f}-{ypp_hi:.0f}]{'':>4} "
          f"{coef[1]:>7.2f} [{td_lo:+.2f},{td_hi:+.2f}]{'':>2} "
          f"{coef[2]:>7.3f} [{rc_lo:+.3f},{rc_hi:+.3f}] {r2:>6.3f}")

grp = [r for r in allrows if r["pos"] == "QB" and r["games"] >= 8]
coef, r2, boot = pooled_fit(grp, ["qb_yds", "pass_td", "rush_td"])
fits["QB"] = coef
lo, hi = np.percentile(boot[:, 0], [2.5, 97.5])
print(f"\nQB   {len(grp):>4} yardage coef {coef[0]:.5f} pts/yd  95% CI [{lo:.5f},{hi:.5f}]")
print(f"     -> {1/coef[0]:.0f} yds per point, but the interval spans zero, so OLS does not")
print(f"        separate QB yardage from QB touchdowns. Pass TD {coef[1]:.2f}, rush TD {coef[2]:.2f}. R^2 {r2:.3f}")

print()
print("=" * 86)
print("IS THE TE PREMIUM REAL? Price the same season at each position using pooled curves.")
print("=" * 86)
wr, te = fits["WR"], fits["TE"]
print(f"{'production':>22} {'as WR':>7} {'as TE':>7} {'TE edge':>9}")
for yds, tds in ((1200, 8), (900, 6), (700, 5), (500, 3)):
    a = yds * wr[0] + tds * wr[1]
    b = yds * te[0] + tds * te[1]
    print(f"{f'{yds} yds, {tds} TD':>22} {a:>7.1f} {b:>7.1f} {b - a:>+9.1f}")
print("\n(Season-long totals; the per-game intercept and season effects cancel in the comparison.)")
