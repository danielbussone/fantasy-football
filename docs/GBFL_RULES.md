# GBFL — Rules & How to Leverage Them

_Stable ruleset + strategy cheat sheet. Companion to `GBFL_STATE.md` (volatile: roster, decisions, watchlist)._
_All scoring verified against the league app; QB tier and Safety value corrected from earlier drafts._

_This is your original doc, corrected against the app's own scoring engine (`scoring/rules.py` / `scoring/SPEC.md`), 2023–25 league history, and live CBS/ESPN data. Changes from the original are marked **[corrected]**. See the app's README for how these rules are actually wired into the sim._

---

## 1. Format DNA — why this isn't a normal league

- **Non-PPR (standard).** Receptions score **0**. Only yards and TDs count.
- **Cumulative season-long total points. No head-to-head, no playoffs.** You rank on YTD points. → **Maximize expected points every week.** No opponent to beat, so **variance is free** — chase the highest *mean*, never a ceiling to win a matchup or a floor to protect a lead.
- **[corrected]** Variance being free is about how you *value* a player (always the mean — this is now the app's default everywhere). It's a separate question from which *lineup* to actively start: chasing upside (P75) early in the season when a bust is easy to make up, sitting on the median (P50) mid-season, and leaning toward the floor (P25) late to protect a lead is a reasonable risk-preference choice tied to your standing and the calendar — not a scoring-math requirement. The app surfaces this as a clickable suggestion next to the lineup objective, never forced.
- **Banded yardage, not per-yard.** Yards pay in chunks; **clearing the next band** is what matters. Two players both under the next band both score the same (often 0).
- **Cheap base TDs, jackpot distance bonuses.** Every TD is 1 base; the points live in the length bonuses. **Explosive plays are the currency.**
- **No INT / fumble penalty.** Turnovers are free — gunslingers aren't punished here.

---

## 2. Exact scoring

### QB
- **Passing + Rushing yards COMBINED**, tiered: 200-249 = **1**, 250-299 = **2**, 300-349 = **3**, 350-399 = **4**, 400-449 = **5**, 450-499 = **6**, 500+ = **7**.
- Passing TD = **1** + bonus by length: 16-30 = +1, 31-45 = +2, 46-60 = +3, 61+ = +4.
- Rushing TD = **1** + bonus by length: 6-15 = +1, 16-25 = +2, 26-40 = +3, 41+ = +4.
- Passing/Rushing 2-pt = 1 each.
- **No yardage floor below 200 combined** → QB scoring is TD-and-big-game dependent. **Rushing double-dips** (feeds the combined-yards tier *and* rush-TD bonuses) — mobile QBs have two spigots.

### RB
- **Rush + Rec yards** tiered: 70-89 = **1**, 90-109 = **2**, 110-129 = **3**, 130-149 = **4**, 150-169 = **5**, 170-189 = **6**, 190-209 = **7**, 210-229 = **8**, 230-249 = **9**, 250+ = **10**.
- Rushing TD = 1 + (6-15 +1 / 16-25 +2 / 26-40 +3 / 41+ +4). Receiving TD = 1 + (16-30 +1 / 31-45 +2 / 46-60 +3 / 61+ +4).

### WR
- **Rush + Rec yards** tiered: same ladder as RB (70-89 = 1 … 250+ = 10).
- Receiving TD = 1 + (16-30 +1 / 31-45 +2 / 46-60 +3 / 61+ +4). Rushing TD = 1 + (6-15 +1 / … / 41+ +4).

### TE (boosted)
- **Rush + Rec yards** tiered — **starts at 40, +1 every 20**: 40-59 = **1**, 60-79 = **2**, 80-99 = **3**, 100-119 = **4**, 120-139 = **5**, 140-159 = **6**, 160-179 = **7**, 180-199 = **8**, 200-219 = **9**, 220+ = **10**.
- Receiving TD = 1 + **TE-specific (shorter) bonus bands**: 6-15 = +1, 16-25 = +2, 26-40 = +3, 41+ = +4.

### K (distance-scored, not volume)
- **[corrected]** FG: 1-40 = **1**, 41-50 = **2**, 51-59 = **3**, 60+ = **3.5**. XP = **0.5**. FG *made count* drives a kicker's season total far more than long-range makes do (2023–25 correlation: 0.94–0.96 for FG made vs. 0.73–0.86 for 50+ makes), and extra points alone are ~28% of a kicker's points. Rank kickers by their offense's expected scoring pace first; use leg strength or a dome as a tiebreak, not the headline signal.

### DST
- Points allowed: 0-1 = **5**, 2-9 = **4**, 10-14 = **3**, 15-17 = **2**, 18-21 = **1**, 22+ = **0**.
- Sack = .5, INT = .5, Fumble recovered = .5, **Safety = 3**, Defensive TD = 3 (+31-50 +1 / 51+ +2).
- Special teams: return TD = 3 (+31-50 +1 / 51+ +2), 2-pt return = 1.
- **[corrected]** Missing from the original: **receiving/rushing/passing 2-pt conversions and offensive fumble-recovery TDs also count** for the individual player (1 point each) — see `scoring/SPEC.md`.
- **[corrected]** Return TDs pay **both** the DST/special-teams unit *and* the individual returner — these are two separate, both-paid scoring events, not a conflict between two rulesets. A receiver who's also a punt/kick returner scores it twice: once on his own card, once on his team's DST.

---

## 3. Roster & lineup construction

- **Roster = 19, maxed at every position:** QB 2, RB 5, WR 6, TE 2, K 2, DST 2. (Sum = 19 → you're always full; **any add costs a same-position drop**, unless IR opens a slot.)
- **Slots:** 10 active + 9 reserve + 0-3 IR (**IR doesn't count against position limits** → moving an injured player to IR frees a slot).
- **Active (10):** QB 1 (fixed), K 1 (fixed), DST 1 (fixed), RB 1-4, WR 1-4, TE 1-2.
- **The flex insight (the real edge):** rank **every healthy RB/WR/TE by projected GBFL points**, then start 1 RB + 1 WR + 1 TE (minimums) **+ the best 4 of the rest** under the caps (max 4 RB / 4 WR / 2 TE). Let matchups pick the shape — 1/4/2, 4/2/1, 3/3/1 are all answers to the same optimization. **Default lands 1 RB / 4 WR / 2 TE.**
- With a 2-QB roster and exactly 1 active QB slot, which QB starts is a real decision **every week**, not just when the projections happen to be close — the app always surfaces this pairing, not only on close calls.

---

## 4. League mechanics

- **Total-points race** → optimize EV every week, no sentiment.
- **Waivers reset to reverse standings every Tuesday** → leading the league means **last (10th) priority Tuesday**. Assume you lose contested Tuesday claims.
  - **[corrected]** Deadline is **11 PM PST Tuesday night**; CBS's transaction log shows claims processing right after, around 2 AM ET Wednesday — same moment, just the deadline versus the observed processing timestamp.
  - **Real edge = the Thursday drop-pool** (you're first in line for players dropped *after* Tuesday's run, waiver-locked till Thursday) + **instant free-agent adds** anytime. **[corrected]** This is true only if other teams actually used their Tuesday claims first — it isn't guaranteed you're first for every drop.
  - As the front-runner: **don't fight Tuesday scrums.** Spend claims only on genuine difference-makers; win with roster quality, not priority.
  - **Kickers: free-agent adds only, never a claim.** (K-for-K swaps make the Thursday lock irrelevant.)
- **Keeper dynasty element: keep 4.**

---

## 5. Archetypes to TARGET (format over-values)

- **Deep-threat WRs with volume** — high aDOT clears bands + cashes TD-length bonuses; low catch totals cost nothing (non-PPR). **Volume gate:** aDOT only pays if the looks come. High aDOT + thin share = a dart (fine in a variance-free format, but a possession guy only beats the dart when his volume *reliably* clears a band the dart's median misses).
- **Goal-line + long-run RBs** — a 41+ yd rushing TD = 5 pts (1+4), same as five short scores. Bell cows who also break long runs are gold.
- **Mobile + downfield QBs** — rushing double-dips; two separate bonus spigots.
- **Big-play TEs** — generous ladder (starts at 40) + short TD-bonus bands, and **you start two** → quality TEs are core, not fringe. Seam-stretchers > dink-and-dunkers.
- **DSTs in low-total games** — PA tier is the baseline; target weak offenses, low Vegas totals, sack/takeaway upside.

## 6. Archetypes to FADE (format under-values)

- **Possession slot WRs** (high catch, low aDOT) — receptions score 0; short work rarely triggers bonuses.
- **Checkdown / game-manager QBs** — few band jumps, no explosive-TD bonuses, and no yardage floor to bail out a low-TD game.
- **Committee / short-yardage-only RBs** — no goal-line or breakaway; volume alone (no PPR) isn't enough.
- **Dink-and-dunk TEs** — short targets, no distance bonuses.
- **One-line test:** if value comes from *how often* he touches the ball rather than *how far* he takes it, this format pays him less than his name suggests.

---

## 7. Weekly workflow — the 3-signal triangulation (how to leverage)

For every start/sit, stack three signals and read them together:

1. **Vegas implied team total** (the player's own team) = scoring opportunity. **KING** in a TD-bonus format. **[in the app now]** the sim's usage prior is scaled by `team total ÷ league average` before ESPN's own week projections are blended in — see the Vegas freshness chip and the Vegas row on the Week-compare tab.
2. **This-year DvP actuals** (schedule-adjusted fantasy points allowed by position) = current form of the opposing D. **[corrected]** Two games of points-allowed data is mostly noise (a real week-2 example: CIN had allowed 0 GBFL points to WRs). Weight this signal by games played, not as a flat override — it should gain influence as the season goes on, not from week 1.
3. **Preseason talent ranks** (PFF pass-rush/DL + secondary) = stable prior / noise filter.

- **All three agree → conviction.** They **diverge → lean the current-week environment** (implied total + actuals) over the preseason rank, **once there's enough current-season sample to trust it**; until then, lean the preseason rank as the stabler prior. Vegas is reliable from week 1; DvP actuals are not.
- **GBFL wrinkle:** weight the **opposing pass rush** higher than a standard player would — pressure kills the deep shots where your points (long TDs, yardage bands) live.

Position-by-position:
- **QB:** start the highest projected **combined yards + pass/rush TDs**, best matchup; prefer rushing QBs (double-dip). Stream the better of your two — every week, not just when it's close.
- **Skill (RB/WR/TE):** rank all healthy by projected GBFL pts; start 1/1/1 + best 4 under caps.
- **DST:** stream the better matchup (low total, weak offense, sack/TO upside).
- **K:** distance-scored → big leg in a dome or clean weather; stream by leg + weather; free-agent adds only. **[corrected]** But volume (FG attempts on a good offense) is the headline signal, not leg strength — see §2.
- **Injury discipline:** **[corrected]** don't blanket-bench a questionable player — start whoever has the higher injury-adjusted average. Game timing matters more than the tag: a questionable player in a late window can be swapped out after inactives post (~90 min before kickoff); one in an early window can't.
- **Trust usage over box scores;** don't overreact to single-week duds.
- **Weather:** dome first. Wind (~15+ mph) kills deep passing and long FGs far more than rain; kickers take the biggest hit. Sloppy weather is a small tailwind for the DST stream.

---

## 8. Reading standard rankings (the leverage, distilled)

Standard boards systematically misprice this league. Apply these thumb-on-scale corrections:

- **They credit receptions you don't score** → over-rate possession/slot WRs and pass-catching committee RBs. Discount them.
- **They penalize turnovers you don't score** (−2 per INT/fumble) → under-rate gunslingers and mobile QBs. Lift them.
- **They undervalue rushing at QB** → mobile QBs are better for you than their rank implies.
- **They undervalue TEs** (single-TE standard pools) → **float your TEs up**; you start two and the ladder is generous.
- **Kicker boards are volume rankings** (every FG ≈ 3, XP = 1) → this happens to already be close to right for GBFL (§2) — the correction here is smaller than for other positions. Favor high-attempt offenses; leg strength is the tiebreak, not the headline. Kicker is still low-leverage; **stream, don't invest**.
- **[corrected]** **§8 itself is mostly unnecessary now** — the app simulates GBFL scoring directly from usage, not from standard-format ranks. Its best remaining use is spotting where FantasyPros' rank and the app's own simulation disagree the most — that gap is the market's blind spot, made visible instead of hand-corrected.
- **Bottom line:** standard ranks are a useful gut-check, not gospel. Re-score toward big plays, distance, rushing, and TEs — and always let the 3-signal read (§7) and this league's actual scoring override the stars.
