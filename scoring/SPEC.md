# GBFL scoring spec

Single source of truth for this league. Edit here, then `scoring/rules.py`. Receptions are worth **0**. Lost fumbles and interceptions are **not** penalized. Yardage is **per-game buckets**, not per-yard.

Illustrative: a **46-yard receiving TD = 4** (base 1 + 46–60 bonus 3). **109 WR/RB yards = 2** (90–109 bucket) plus a **10-yard receiving TD = 1** → **3**. The long score wins.

## Yardage (per game)

| Position | Stat | 0 | then |
|---|---|---|---|
| QB | Pass + rush yards | < 200 | 200–249=1, +1 per 50 yards, 500+=7 |
| RB, WR | Rush + rec yards | < 70 | 70–89=1, +1 per 20 yards, 250+=10 |
| TE | Rush + rec yards | < 40 | 40–59=1, +1 per 20 yards, 220+=10 |

## Touchdowns (each)

Base **1**, plus distance. Max **5**.

| Kind | +1 | +2 | +3 | +4 |
|---|---|---|---|---|
| Pass TD, WR/RB rec TD | 16–30 | 31–45 | 46–60 | 61+ |
| Rush TD, **TE rec TD** | 6–15 | 16–25 | 26–40 | 41+ |

## Other offense

| Event | Points |
|---|---|
| Reception | 0 |
| 2-pt (pass/rush/rec/fumble) | 1 |
| Offensive fumble-recovery TD | 1 |
| Kick/punt return TD | 3; +1 if 31–50; +2 if 51+ (**51+ = 5**) |
| Extra point | 0.50 |
| FG 1–40 / 41–50 / 51–59 / 60+ | 1 / 2 / 3 / 3.50 |
| Lost fumble, INT | 0 |

## Defense / ST

| Event | Points |
|---|---|
| Sack, INT, fumble recovered | 0.50 each |
| Safety | 3 |
| Defensive / ST TD | 3; +1 if 31–50; +2 if 51+ |
| Points against | 0–1=5, 2–9=4, 10–14=3, 15–17=2, 18–21=1, 22+=0 |

CBS site “scoring” / projections are **not** this system.
