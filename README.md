# GBFL in-season app

Lineup, waivers, and weekly projections for BUSSONE. Numbers on Roster / Start/Sit / Waivers are **this league’s scoring**, not CBS, ESPN, or FantasyPros projected points.

Strategy cheat sheet: [`docs/GBFL_RULES.md`](docs/GBFL_RULES.md). `scoring/SPEC.md` stays the one official scoring reference; the rules doc is strategy, corrected against that spec and this season's data.

```text
python -m pip install -r requirements.txt
python -m pytest -q
python -c "from app.assemble import dump_fixture; print(dump_fixture())"

cd web
npm install
npm run dev
```

API (UI falls back to `web/public/fixtures/week1.json` if this is down):

```text
python -m uvicorn app.main:app --reload --port 8000
```

Refresh CBS: `python cbs_pull.py --cookies cbs_cookies.txt` — omit `--week` and it auto-detects the current week from CBS itself (see below); pass `--week N` to pull a specific week instead. HAR files and cookie files are credentials — do not commit them.

Import dynasty/redraft, weekly FantasyPros CSVs, or an ESPN HAR from the UI when the API is up.

## Current week and auto-refresh

The week picker defaults to CBS's own idea of "this week" on load (`GET /api/current-week`) — pick another week and it stays put for the rest of the session. That detection reads CBS's live injury-report copy ("Questionable for Week 3 at Washington"): the most common week number mentioned wins. No NFL-calendar date to maintain, and it's naturally right for bye weeks, playoffs, etc. `current_week.json` holds the last detected value; a missing/unreachable CBS just keeps the last known one.

While `uvicorn` is running, a background task re-pulls CBS (`cbs_cookies.txt`), using the last HAR-imported cookie, ESPN (`espn_cookies.txt`), and Vegas's odds board (no auth needed) every 2 hours on its own — no clicking Refresh or re-exporting a HAR each time, as long as those cookies stay valid. `GBFL_AUTO_REFRESH=0` disables it; `GBFL_AUTO_REFRESH_SECONDS` changes the interval. ESPN cookies do eventually expire (there's no login flow this app can drive for ESPN) — when that happens the background pull fails loudly in the server log and the ESPN freshness chip below turns missing with an "Import ESPN" hint; CBS's cookie file usually needs the same manual refresh less often. The CBS pull also re-pulls the *previous* week's box scores every time, so a Monday-night final that lands after CBS's "current week" has already flipped forward still gets captured.

The freshness row under the header (CBS roster/stats, Injuries, ESPN, FantasyPros weekly, Vegas) shows each source's status at a glance: green **fresh** (recently pulled, right week), amber **stale** (present but old), or red **missing** (never pulled, or it's a different week's data — e.g. an ESPN import that doesn't match the week you're viewing). Hover a chip for the exact timestamp and, if it's not fresh, what to do about it.

## Matchups, Vegas, and pass rush (the sim's own read on the opponent)

Three signals feed a player's usage prior before ESPN's own week projections are blended in — applying them after would double-count what ESPN already prices in:

- **Vegas** (`projections/vegas.py`): each team's implied points (its share of the O/U, split by the spread), pulled from ESPN's public scoreboard — no login needed. Scales TD rates directly and yards by a damped `ratio ^ 0.3`; a DST's points-allowed prior leans toward its *opponent's* implied total. Shown on the Week-compare tab's Vegas row and in the Opp column tooltip.
- **Matchup (DvP)** (`projections/matchups.py`): points each defense has actually allowed to each position this season, from the same exact CBS box scores the Report tab grades from. Shrunk toward the league average by games played (`weight = games / (games + 4)`) — two games of DvP data is mostly noise — and capped to a ±15% adjustment either way.
- **Pass rush**: the opponent's sacks/game, blending 2025 `dst_history.csv` with this season's actual defensive box scores (same games-played shrink). A strong pass rush shifts the sim's passing/receiving TD-length draw shorter, not the TD rate itself — see the Week-compare tab's Matchup row.

**Player explosiveness** (`projections/explosiveness.py`) is a separate, player-specific pull on that same TD-length draw: CBS's exact `Total` makes "how many of this player's points came from TD *length*, not the flat base" a subtraction, shrunk toward the position average by TD count (`weight = tds / (tds + 6)`) and starting from a yards-per-catch/carry prior before there's a real in-season TD sample. A deep-threat dart and a possession/dink-and-dunk player at the same yardage no longer draw from the same TD-distance mix.

**Format edges** (Waivers tab): players where FantasyPros' weekly rank and this app's own simulated rank (by mean, within the same weekly list) disagree the most — not a hand-correction, just where the market and the sim part ways (§8 of `docs/GBFL_RULES.md`).

## Week report card

The **Report** tab looks backward. It does **not** write the Monte Carlo.

1. **Lock week N** (next to Refresh) before kickoff. Writes `snapshots/weekN_pre.json` (gitignored) with P10–P90, usage, ESPN line, CBS slots, the recommended (expected-points) lineup, injuries, and depth.
2. Play the games.
3. **Refresh** after the games (`cbs_pull.py --week N`) so `cbs_stats_weekN.csv` (box scores) and last-3-games / injuries / depth update.
4. Open **Report**. Actual GBFL points are CBS's own league-scoring total (exact TD/FG distance and 2-pt conversions included, since CBS computes it under this league's own custom scoring settings) — not the sim's mix EV. Yard/PA/XP/sack rows underneath are this app's own breakdown of that same score.

Looking ahead is locked Exp (mean) vs now after Refresh. Driver chips (3g / Injury / Depth / ESPN) are input diffs, not a split of the delta. Residuals never enter next week’s sim.

## Usage grades (nflverse)

Backtested on 2023–25 (report: GBFL Usage Grades); only what passed ships. Data comes from [nflverse](https://github.com/nflverse/nflverse-data) (free, no login), pulled with the 2-hour auto-refresh and by the Refresh button into `nflverse_cache/` (gitignored). The **nflverse** freshness chip is fresh only when the pull includes the last completed week. With no nflverse data the app works as before: grade columns show "—" and sorts fall back to Present.

- **Role** (WR/TE/RB): 0–100 percentile of WOPR (WR/TE) or opportunity share (RB), season to date.
- **PAR**: points above the best free agent for the rest of the season. 40% points so far + 60% usage stat, scaled to points per game, minus the replacement player (WR61 / RB51 / TE21), times **expected games** from his injury status (the app's designation, CBS IR slot counts as out at least 4 games). Round 1–2 RBs in years 1–2 get a pedigree bump (+1.1 pts/g under 25% opportunity share, +0.5 above).
- **QB rest of season**: the Role column shows `#rank` by projected points per game. Model (`metrics/qb.py`, `backtest_qb.py`): points per game this season and the last two, weighted by games played, plus EPA per play. Leave-one-season-out 2013–25: rank correlation 0.50 vs 0.40 for points so far (top-12 hit rate 59% vs 53%). Still noisy; with 3 games it leans mostly on last season. QB availability uses the skill-player miss table as an approximation.
- **Flags**: NEXT UP (RB whose lead teammate with 15%+ of the work is out and who has the most left), BUY LOW (years 1–2, round 1–2, in the waiver tier by points; weeks 4–10), +PEDIGREE.
- **Waivers tab**: FA board sorts by PAR by default (click any grade column to re-sort); add/drop suggestions compare PAR. Also: defense stream card (next opponent's Vegas implied total, lowest first), buy-low tracker, next-man-up list, and from week 8 a WR watch list. Kickers sort by their team's implied total; they stay free-agent adds only.
- **Report tab**: each lock stores the grades' predictions; "Usage metrics, live tracking" scores flags, PAR error and the DST stream pick once box scores are in, so the thin-sample signals (next man up, buy-low) get confirmed or dropped on 2026 data.

What failed the backtests and is deliberately not built: a Boom grade (aDOT, catch rate, deep targets, explosive runs), usage-trend breakouts (the old breakout badge is gone), a kicker grade. The backtests are reproducible:

```text
python backtest_metrics.py      # WR/RB/TE/QB grades, injuries, Breakout; rewrites metrics/weights.json
python backtest_pedigree.py     # draft pedigree, second-half breakouts, buy-low; adds the RB bump to the weights
python backtest_special.py      # kickers and defenses
python -m nflverse.pull         # download/refresh the nflverse cache by hand
```

## How projections are calculated

Each player gets a P10 / P25 / P50 / P75 / P90 band of **one-game GBFL points**, plus the **mean** of all simulated draws. This is a cumulative total-points league — no head-to-head, no playoffs — so variance is free and every ranking (Start/Sit's default objective, Waivers' Present/Future, the Report grades) targets the **mean**, not the median. P50 is still shown as the median simulated week, and P90 is a long-TD / long-FG tail, not a CBS “ceiling” — useful context, just not what drives a recommendation.

```text
history + last-3-games + depth
        ↓
  usage prior (yards / TDs per game)
        ↓
  ESPN week stats mixed in (optional mix)
        ↓
  Monte Carlo, each draw:
      injury snap/volume × yards and TD rates
              ↓
      score that game with GBFL rules
        ↓
  Roster columns, Start/Sit, waiver Present
```

CBS site projections are ignored. FantasyPros `PROJ. FPTS` and ESPN `appliedTotal` are tooltips only — they use PPR/standard, not GBFL buckets and distance-band TDs.

### 1. Usage prior

A prior is “what a typical game looks like” before any points are scored.

**Season history** (`history_2023.csv` … `history_2025.csv`): yards and TDs per **games played**, `games = round(season total / season avg)`, not a blanket 17. 2025 overwrites 2024/2023 when the same name appears. Kickers use `kicker_2025.csv` ÷ 17. DST uses 2025 rows in `dst_history.csv` ÷ 17.

**Last 3 games** (`cbs_stats_3g.csv`): if those stats are real (not week-1 zeros), they mix in, up to **70% recent / 30% season** once 3 games are in the window (less early in the season — 1 game gets roughly a third of that weight). TD rates get half whatever weight yards get, since one game's TD count is noisier than one game's yards. Empty 3g leaves the season prior alone.

**Depth:** CBS team chart (`cbs_depth.csv`). Depth rank ≥ 3 (backup) cuts volume 55% (`× 0.45`) on yards / FG rate.

**Board floor:** if the player is combined-board rank ≤ 80 and the history prior is thin, skill volume is floored to 72 scrimmage ypg (QB pass+rush floored to 240). This is a usage nudge, not a point blend.

**Unknown names** get a position default (role prior).

### 2. ESPN week stats (inside the sim)

Import ESPN (HAR). The app replays ESPN’s week projection table and maps **stat lines**, not ESPN points:

| Position | ESPN fields used |
|---|---|
| QB | pass yards, rush yards, pass TDs, rush TDs |
| RB/WR/TE | rush + rec yards, rush/rec TDs; targets and receptions shown, not scored |
| K | FG made, XP |
| DST | sacks, INTs, points allowed, def TD rate |

Those keys can feed the Monte Carlo as the **stat-line mix** (not ESPN points):

| Mix | What P10–P90 are centered on |
|---|---|
| Monte Carlo | History + last-3-games + depth only |
| 50/50 | Average of that prior and ESPN’s week yards/TDs (default) |
| ESPN | ESPN’s week stat line. Injury snap sampling still applies |

No ESPN row → mix does nothing; the prior is unchanged. Then the Monte Carlo still scores GBFL.

The ESPN column is always **their** stat line (targets, rec, yards, TDs), plus what it is worth under GBFL buckets — so you can compare it to the sim. ESPN `appliedTotal` / FPTS stays in the tooltip only.

### 3. Monte Carlo

About **1,200** one-game draws per player (`projections/weekly.py`). Each draw:

- If the player is Out/IR, snaps are 0 and the game scores 0. Otherwise a snap/volume factor is sampled (see §4) and applied to **yards and TD rates**, not to points.
- Yards ~ gamma around that injured/healthy prior.
- TD **counts** ~ Poisson from the scaled rates.
- Each TD gets a **distance** from an empirical mix (short punch-ins through 60+). High YPC receivers sample a longer rec-TD mix. That is why a 46-yard rec TD (4 pts) can beat 109 yards + a 10-yard rec TD (3 pts) in this format — see `scoring/SPEC.md`.
- Kickers: Poisson FGs + sampled FG distance (long kickers bias 50+). DST: Gaussian PA / sacks / INTs, rare def TD. K/DST volume (FG, XP, sacks) is scaled the same way; DST points-against is not.

That raw game is passed through `scoring/rules.py` (yardage **buckets**, distance-banded TDs, receptions = 0, no fumble/INT penalty). Sorted draws become P10…P90, and their average is the **mean**. **Present** on Waivers is that mean, not P50 — see "Ranking by mean, not median" below.

### 4. Injury (snaps / volume, not points)

Official ESPN report (plus CBS slot) only. News blurbs do not become Questionable.

Injury does **not** multiply a finished P50 by 0.75. This league’s yardage is buckets (whole points); XP and sacks are 0.5. So a Questionable WR is modeled as fewer snaps: maybe ~60 yards instead of 80, then that lands in a bucket (or misses it).

Each draw samples a snap/volume factor from these knots (floor cut harder than ceiling, so Q/D weeks stay wide):

| Status | P10 | P25 | P50 | P75 | P90 |
|---|---|---|---|---|---|
| Out / IR | 0 | 0 | 0 | 0 | 0 |
| Doubtful | 0 | 0.15 | 0.35 | 0.55 | 0.70 |
| Questionable | 0.45 | 0.60 | 0.75 | 0.90 | 1.05 |
| Probable | 0.85 | 0.90 | 0.95 | 1.0 | 1.0 |

Healthy wins a Start/Sit tie.

### 5. FantasyPros weekly ranks (display only)

Import weekly FLX / QB / K / DST CSVs. Rank is inverted **per list** (QB lists are short; FLX is long) and shown in the **Weekly** column (`FLX 9`, `QB 8`). DST matches on team abbr (`Seahawks` / `SEA`).

Those ranks do **not** change yards, TDs, or GBFL points. How to use them in the sim is still open.

The Waivers **Trust this week ↔ Trust board** slider is dynasty+redraft `combined.csv` only (`board_weight`). Moving it re-ranks add/drops from the last simulated week — it does not rerun the Monte Carlo. `merge.py` ranking math is untouched.

### Waiver mechanics (this league's own rules, not a generic add/drop)

This is a total-points league with no head-to-head — "standings" is each team's season GBFL total, pulled straight from CBS (`/standings/overall`, `standings.json`), and Tuesday's waiver priority is exactly the reverse of it (the leader claims last). The Waivers tab shows your own priority number and:

- **Free agent vs. waivers**: an FA/Waivers badge on every add (from `cbs_fa.csv`'s own `status` column) — a free agent can be added any time, no claim needed; a "waivers" player is still in the post-drop lock and contested claims go by priority.
- **Kickers are free-agent adds only, never a claim** — a kicker on waivers is filtered out of recommendations entirely, per the doc's own rule (a K-for-K swap makes the Thursday drop-pool lock irrelevant).
- **IR doesn't count against the 19-man position caps.** A rostered player in a CBS IR slot is excluded from the position-cap count, so a same-position drop isn't required to add around him.
- **Move to IR suggestions**: a rostered player who's Out/IR by designation but not yet sitting in a CBS IR slot shows up as a suggestion — moving him is free and opens a roster spot without a drop.

### Ranking by mean, not median

This is a cumulative-points league with no head-to-head and no playoffs — you just add up points all season. There's no opponent to beat in a given week, so a boom-or-bust player and a steady one with the same median are **not** equivalent: the one with the higher *average* nets more points over 18 weeks. Every default ranking targets the mean:

- **Start/Sit** defaults to the `mean` (expected points) objective, not P50. P10–P90 stay available in the objective picker for exploring the band.
- **Waivers**: Present = mean; Future = mean × weeks left in the season (through week 18) × a depth factor (1.0 starter / 0.625 depth-2 / 0.375 backup) — not a flat ×16/×10/×6 that never shrank as the season went on.
- **Report**: grades and the "Looking ahead" delta compare the mean, not P50 (`Exp` columns). `band_hit` (bust/typical/boom) still uses P25/P75 — that's a different question, how typical the actual game was relative to the distribution's shape.

A **season-stage suggestion** sits next to the Start/Sit objective picker — not a rule, just a nudge: P75 (upside) early, when a bust is easy to make up over the rest of the season; P50 (balanced) mid-season; P25 (protect the lead) late. Click it to apply, or ignore it — Present/Future/grading always use the mean regardless of which lineup-optimization objective you're browsing.

### What you are looking at

| Column | Meaning |
|---|---|
| P10 | Floor week in this scoring |
| Mean / Present | Expected GBFL points — the sim's average draw (injury already in the sim) |
| Past | Last scored season in this format (2025 if present, else 2024) |
| Future | Mean × weeks left in the season × depth factor |
| Keeper | Board/age mix for long-term hold value |
| P50 | Median simulated week (shown in Dense mode; not what rankings target) |
| P90 | Long-TD / chunk-play tail in **this** scoring |
| Opp | This week’s opponent from FantasyPros (`vs. TB` / `at CAR`) |
| Weekly | FantasyPros rank on that week’s list (`FLX 17`, `QB 8`) |
| ESPN | Their week **stats** (tar / rec / yds / TD). `this format EV` is mean-line expected value of that volume — close in spirit to the sim's mean, but computed straight off ESPN's volume line, not from scored Monte Carlo draws. Buckets can make those disagree. Not ESPN FPTS. Independent of the Stat line mix |

Roster defaults to Player (injury badge on the name) / Slot / Opp / Weekly / ESPN / Mean / Band. **Dense** adds notes, breakout, board, depth, and P10–P90 (including P50). Click a row for the Week tab.

Start/Sit sums the chosen objective (mean by default) across a **legal** GBFL lineup (1 QB, 1 K, 1 DST, 7 skill with RB 1–4 / WR 1–4 / TE 1–2).
