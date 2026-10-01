"""Draft pedigree and second-half breakouts, on 2018–2025.

Three questions, all against the frozen GBFL-PAR model (fit on 2023–24, as in
backtest_metrics.py), measured as next-6-week GBFL points per game:

1. High-pick RBs: do round 1–2 RBs in their first two seasons beat PAR? An
   adjustment is fit on 2018–22 and tested on 2023–25.
2. Second-half breakouts: how many second-half starters come out of the
   midseason (after week 9) waiver pool, and which week-9 ranking finds them?
3. Buy-low: do slow-starting (waiver tier) young high picks beat PAR, and how
   often do they become second-half starters?

    python backtest_pedigree.py --out pedigree.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import fmean

import backtest_metrics as bt
from metrics.availability import team_weeks
from metrics.features import (PAR_BLEND, SHARE_STAT, _optional, by_player, implied_totals, injury_index,
                              load_season_games, pedigree, pedigree_index, window_features)
from metrics.grades import Model, fit_blend, spearman, save_weights, load_weights

SEASONS = list(range(2018, 2026))
FIT_ADJ = range(2018, 2023)   # pedigree adjustment fit seasons
TEST_ADJ = range(2023, 2026)  # and its test seasons
POS = ["WR", "RB", "TE"]
CUTS = {"WR": 2.0, "RB": 3.0, "TE": 2.0}
MID = 9
STARTABLE = {"WR": 30, "RB": 25, "TE": 12}   # about how many start league-wide (10 teams, 7 skill slots)
PRIOR_TOP = {"WR": 45, "RB": 38, "TE": 18}   # last season's top-N at a position is rostered, not on waivers
MIN_2H_GAMES = 4
LOW_SHARE = 0.25


def _boot_mean(grp: list[dict], key: str, reps: int = 2000) -> tuple[float, float]:
    by = defaultdict(list)
    for r in grp:
        if r.get(key) is not None:
            by[r["player_id"]].append(r[key])
    ids = list(by)
    if len(ids) < 3:
        return float("nan"), float("nan")
    rng = random.Random(0)
    ms = sorted(fmean([v for p in rng.choices(ids, k=len(ids)) for v in by[p]]) for _ in range(reps))
    return ms[int(0.025 * reps)], ms[int(0.975 * reps) - 1]


def summarize(grp: list[dict]) -> dict:
    if not grp:
        return {"n": 0}
    lo, hi = _boot_mean(grp, "resid")
    w9 = [r for r in grp if r["week"] == MID]
    sh = [r for r in grp if r.get("now_share") is not None and r.get("y_share") is not None]
    return {
        "n": len(grp), "players": len({r["player_id"] for r in grp}),
        "pred": fmean(r["pred"] for r in grp), "actual": fmean(r["y_ppg"] for r in grp),
        "miss": fmean(r["resid"] for r in grp), "ci": [lo, hi],
        "share_now": fmean(r["now_share"] for r in sh) if sh else None,
        "share_next": fmean(r["y_share"] for r in sh) if sh else None,
        "wk9": len(w9), "wk9_starters": sum(r["start_2h"] for r in w9),
    }


def season_rows(season: int, ped: dict, schedule: list[dict]) -> tuple[list[dict], dict]:
    from nflverse.pull import load

    games = load_season_games(season)
    inj = injury_index(_optional(load, "injuries", season))
    tw = team_weeks(schedule, season)
    bp = by_player(games)
    # Second-half starters: top-N by weeks 10–18 pts/game (4+ games).
    h2 = {}
    for pid, gl in bp.items():
        g2 = [g for g in gl if g["week"] > MID]
        if len(g2) >= MIN_2H_GAMES:
            h2[pid] = (bt._primary_pos(gl), fmean(g["gbfl"] for g in g2))
    start = set()
    for pos in POS:
        ranked = sorted(((v[1], pid) for pid, v in h2.items() if v[0] == pos), reverse=True)
        start |= {pid for _, pid in ranked[:STARTABLE[pos]]}
    rows = bt.decision_rows(games, season, POS, CUTS, inj=inj, team_weeks=tw, implied=implied_totals(schedule, season))
    mid_rows = bt.decision_rows(games, season, POS, CUTS, require_future=False, inj=inj, team_weeks=tw,
                                implied=implied_totals(schedule, season))
    mid_rows = [r for r in mid_rows if r["week"] == MID]
    for rs in (rows, mid_rows):
        for r in rs:
            pd_ = pedigree(ped, r["player_id"], season)
            r.update({"years": pd_["years"], "round": pd_["round"], "pick": pd_["pick"], "young_hi": pd_["young_high_pick"]})
            r["start_2h"] = r["player_id"] in start
            r["ppg2"] = h2[r["player_id"]][1] if r["player_id"] in h2 else None
            fut = [g for g in bp[r["player_id"]] if r["week"] < g["week"] <= r["week"] + bt.HORIZON]
            if r["pos"] == "RB":
                num, den = sum(g["carries"] + g["targets"] for g in fut), sum(g["team_carries"] + g["team_targets"] for g in fut)
                r["now_share"] = r.get("opp_share")
            else:
                num, den = sum(g["targets"] for g in fut), sum(g["team_targets"] for g in fut)
                r["now_share"] = r.get("tgt_share")
            r["y_share"] = num / den if den else None
    for r in mid_rows:
        first = [g for g in bp[r["player_id"]] if g["week"] <= MID]
        r["l3_share"] = window_features(first[-3:], r["pos"]).get(SHARE_STAT[r["pos"]])
        r["share"] = r.get(SHARE_STAT[r["pos"]])
    return rows, {"mid": mid_rows, "games": games}


def prior_top(games_prev: list[dict]) -> set[str]:
    out = set()
    bp = by_player(games_prev)
    for pos in POS:
        ranked = sorted(((fmean(g["gbfl"] for g in gl), pid) for pid, gl in bp.items()
                         if bt._primary_pos(gl) == pos and len(gl) >= 6), reverse=True)
        out |= {pid for _, pid in ranked[:PRIOR_TOP[pos]]}
    return out


def rb_pedigree(rows: list[dict]) -> dict:
    rb = [r for r in rows if r["pos"] == "RB"]
    rk = [r for r in rb if r["years"] == 1]
    groups = {
        "veterans": [r for r in rb if (r["years"] or 9) >= 2],
        "rookies": rk,
        "rookies_round1": [r for r in rk if r["round"] == 1],
        "rookies_round2": [r for r in rk if r["round"] == 2],
        "rookies_round3_4": [r for r in rk if r["round"] in (3, 4)],
        "rookies_round5plus": [r for r in rk if r["round"] >= 5],
        "young_hi_low_share": [r for r in rb if r["young_hi"] and (r["opp_share"] or 0) < LOW_SHARE],
        "young_hi_high_share": [r for r in rb if r["young_hi"] and (r["opp_share"] or 0) >= LOW_SHARE],
        "second_year_hi": [r for r in rb if r["years"] == 2 and r["round"] <= 2],
    }
    out = {k: summarize(v) for k, v in groups.items()}
    by_season = defaultdict(list)
    for r in rb:
        if r["young_hi"]:
            by_season[r["season"]].append(r)
    out["by_season"] = {s: {"miss": fmean(x["resid"] for x in v), "n": len(v), "players": sorted({x["player"] for x in v})}
                        for s, v in sorted(by_season.items())}
    fit_rows = [r for r in rb if r["season"] in FIT_ADJ]
    adj_low = fmean(r["resid"] for r in fit_rows if r["young_hi"] and (r["opp_share"] or 0) < LOW_SHARE)
    adj_high = fmean(r["resid"] for r in fit_rows if r["young_hi"] and (r["opp_share"] or 0) >= LOW_SHARE)
    test = [r for r in rb if r["season"] in TEST_ADJ]
    for r in test:
        bump = (adj_low if (r["opp_share"] or 0) < LOW_SHARE else adj_high) if r["young_hi"] else 0.0
        r["_par"], r["_adj"] = r["pred"], r["pred"] + bump
    m0, m1 = Model(["_par"], [0.0], [1.0], [0.0, 1.0]), Model(["_adj"], [0.0], [1.0], [0.0, 1.0])
    wv = [r for r in test if r["waiver_tier"]]
    flagged = [r for r in test if r["young_hi"]]
    out["adjustment"] = {
        "low_share": adj_low, "high_share": adj_high, "fit_seasons": [FIT_ADJ.start, FIT_ADJ.stop - 1],
        "rho_all": [bt.evaluate(m0, test, "y_ppg")["rho"], bt.evaluate(m1, test, "y_ppg")["rho"]],
        "ci_all": bt.boot_delta_rho(m0, m1, test, "y_ppg"),
        "rho_waiver": [bt.evaluate(m0, wv, "y_ppg")["rho"], bt.evaluate(m1, wv, "y_ppg")["rho"]],
        "flagged_n": len(flagged),
        "miss_before": fmean(r["y_ppg"] - r["_par"] for r in flagged),
        "miss_after": fmean(r["y_ppg"] - r["_adj"] for r in flagged),
    }
    return out


def second_half(mids: dict[int, list[dict]], established: dict[int, set[str]], frozen: dict[str, Model]) -> dict:
    """Week-9 pool = waiver tier by first-half points, minus last season's top-N and young high picks."""
    pool = {s: [r for r in rows if r["waiver_tier"] and r["player_id"] not in established[s] and not r["young_hi"]]
            for s, rows in mids.items()}
    out = {}
    for pos in POS:
        cand = [r for s in pool for r in pool[s] if r["pos"] == pos]
        starters = [r for s, rows in mids.items() for r in rows if r["pos"] == pos and r["start_2h"]]
        n_seasons = len(mids)
        test = [r for r in cand if r["season"] in TEST_ADJ]
        rankers = {
            "First-half pts/g": lambda r: r["ppg"],
            "Usage share": lambda r: r.get("share") or 0,
            "Last-3 usage share": lambda r: r.get("l3_share") or 0,
            "Usage trend (last 3 − season)": lambda r: r.get("d_share") or 0,
            "Snap share": lambda r: r.get("snap_pct") or 0,
            "GBFL-PAR": lambda r: frozen[pos].predict(r),
        }
        rank_res = {}
        for name, fn in rankers.items():
            hits = n = 0
            for s in TEST_ADJ:
                top = sorted((r for r in test if r["season"] == s), key=lambda r: -fn(r))[:10]
                hits += sum(r["start_2h"] for r in top)
                n += len(top)
            y2 = [r["ppg2"] if r["ppg2"] is not None else 0.0 for r in test]
            rank_res[name] = {"hits": hits, "n": n, "rho": spearman([fn(r) for r in test], y2)}
        hits_by_season = {}
        for s in TEST_ADJ:
            sl = sorted((r for r in test if r["season"] == s), key=lambda r: -frozen[pos].predict(r))
            hits_by_season[s] = {"pool": len(sl), "hits": [{"player": r["player"], "team": r["team"], "par_rank": i + 1,
                                                            "ppg1": r["ppg"], "ppg2": r["ppg2"]}
                                                           for i, r in enumerate(sl) if r["start_2h"]]}
        hit_rows = [r for r in cand if r["start_2h"]]
        rest = [r for r in cand if not r["start_2h"]]
        prof = {f: [fmean([r[f] for r in grp if r.get(f) is not None] or [0.0]) for grp in (hit_rows, rest)]
                for f in ("ppg", "share", "d_share", "snap_pct")}
        out[pos] = {
            "starters_per_season": len(starters) / n_seasons,
            "from_pool_per_season": sum(1 for r in cand if r["start_2h"]) / n_seasons,
            "pool_per_season": len(cand) / n_seasons,
            "base_rate": fmean(1.0 if r["start_2h"] else 0.0 for r in cand) if cand else 0.0,
            "test_base_rate": fmean(1.0 if r["start_2h"] else 0.0 for r in test) if test else 0.0,
            "rankers": rank_res, "hits_by_season": hits_by_season, "profile": prof,
        }
    return out


def buy_low(rows: list[dict]) -> dict:
    out = {}
    for pos in POS:
        slow = [r for r in rows if r["pos"] == pos and r["waiver_tier"] and 4 <= r["week"] <= MID]
        young = [r for r in slow if (r["years"] or 9) <= 2]
        hi = [r for r in young if r["round"] <= 2]
        groups = {
            "veterans": [r for r in slow if (r["years"] or 9) >= 3],
            "young_round1": [r for r in young if r["round"] == 1],
            "young_round2": [r for r in young if r["round"] == 2],
            "young_round1_2": hi,
            "young_round3": [r for r in young if r["round"] == 3],
            "young_round4plus": [r for r in young if r["round"] >= 4],
            "hi_low_snaps": [r for r in hi if (r.get("snap_pct") or 0) < 0.7],
            "hi_high_snaps": [r for r in hi if (r.get("snap_pct") or 0) >= 0.7],
        }
        res = {k: summarize(v) for k, v in groups.items()}
        by_season = defaultdict(list)
        for r in hi:
            by_season[r["season"]].append(r)
        res["by_season"] = {s: {"miss": fmean(x["resid"] for x in v), "n": len(v)} for s, v in sorted(by_season.items())}
        first = {}
        for r in sorted(hi, key=lambda r: r["week"]):
            first.setdefault((r["season"], r["player_id"]), r)
        ex = sorted(first.values(), key=lambda r: -(r["y_ppg"] - r["pred"]))
        res["examples"] = [{"season": r["season"], "player": r["player"], "team": r["team"], "years": r["years"],
                            "round": r["round"], "week": r["week"], "ppg": r["ppg"], "pred": r["pred"], "y_ppg": r["y_ppg"],
                            "share": r.get("now_share"), "snap": r.get("snap_pct"), "start_2h": r["start_2h"]}
                           for r in ex[:8] + ex[-4:]]
        out[pos] = res
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    from nflverse.pull import load

    ped = pedigree_index(load("players"))
    schedule = load("games")
    rows, mids, games = [], {}, {}
    for s in SEASONS:
        r_, extra = season_rows(s, ped, schedule)
        rows += r_
        mids[s] = extra["mid"]
        games[s] = extra["games"]
    established = {s: prior_top(games[s - 1]) if (s - 1) in games else set() for s in SEASONS}
    frozen = {}
    for pos in POS:
        feats, w = PAR_BLEND[pos]
        frozen[pos] = fit_blend([r for r in rows if r["pos"] == pos and r["season"] in bt.TRAIN], feats, w, "y_ppg")
    for r in rows:
        r["pred"] = frozen[r["pos"]].predict(r)
        r["resid"] = r["y_ppg"] - r["pred"]

    mids_2h = {s: v for s, v in mids.items() if s >= SEASONS[1]}  # 2018 only serves as 2019's prior season
    results = {
        "seasons": [SEASONS[0], SEASONS[-1]],
        "rb_pedigree": rb_pedigree(rows),
        "second_half": second_half(mids_2h, established, frozen),
        "buy_low": buy_low(rows),
        "config": {"startable": STARTABLE, "prior_top": PRIOR_TOP, "mid": MID, "low_share": LOW_SHARE},
    }
    a = results["rb_pedigree"]["adjustment"]
    print(f"RB pedigree bump (fit {a['fit_seasons']}): +{a['low_share']:.2f}/g under {LOW_SHARE:.0%} share, +{a['high_share']:.2f} above;"
          f" 2023–25 flagged miss {a['miss_before']:+.2f} -> {a['miss_after']:+.2f}; ρ {a['rho_all'][0]:.3f} -> {a['rho_all'][1]:.3f}")
    for pos, v in results["second_half"].items():
        best = max(v["rankers"].items(), key=lambda kv: kv[1]["hits"])
        print(f"{pos} second half: {v['from_pool_per_season']:.1f} of {v['starters_per_season']:.0f} starters/season from the pool;"
              f" best week-9 ranking {best[0]} {best[1]['hits']}/{best[1]['n']}")
    for pos, v in results["buy_low"].items():
        g = v["young_round1_2"]
        print(f"{pos} buy-low (yr 1–2, rd 1–2, slow): miss {g['miss']:+.2f} [{g['ci'][0]:+.2f},{g['ci'][1]:+.2f}],"
              f" {g['wk9_starters']}/{g['wk9']} became 2H starters")
    w = load_weights()
    if w:
        w["rb_pedigree_bump"] = {"low_share": a["low_share"], "high_share": a["high_share"], "share_cut": LOW_SHARE,
                                 "applies_to": "RB, draft rounds 1–2, years 1–2", "fit_seasons": a["fit_seasons"]}
        save_weights(w)
    if args.out:
        args.out.write_text(json.dumps(results, indent=1, default=list), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
