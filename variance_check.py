"""In a tiered system, does week-to-week volatility help or hurt at a fixed average?"""
import numpy as np

def te_tier(y):
    return 0 if y < 40 else min(10, int((y - 40) // 20) + 1)

def wr_tier(y):
    return 0 if y < 70 else min(10, int((y - 70) // 20) + 1)

rng = np.random.default_rng(0)
print("Simulated 17-game seasons, gamma-distributed weekly yardage, 20000 trials each.")
print("Same season-long mean, different volatility (cv = coefficient of variation).\n")
for tier, label, means in ((te_tier, "TE", (48, 60, 75)), (wr_tier, "WR", (77, 90))):
    print(f"  {label} (bonus starts at {'40' if label == 'TE' else '70'} yds, steps every 20)")
    print(f"    {'mean yds/gm':>12} " + " ".join(f"{('cv '+str(c)):>9}" for c in (0.4, 0.6, 0.8, 1.0)))
    for m in means:
        row = []
        for cv in (0.4, 0.6, 0.8, 1.0):
            shape = 1 / cv**2
            draws = rng.gamma(shape, m / shape, size=(20000, 17))
            pts = np.vectorize(tier)(draws).sum(axis=1)
            row.append(f"{pts.mean():>9.1f}")
        print(f"    {m:>12} " + " ".join(row))
    print()

print("Reading: numbers are season point totals from yardage alone.")
