"""Backtest: do usage grades predict future GBFL points?

Fit on 2023–24, freeze, test on 2025. At each decision week d (3–16) a
player's features use only games through week d; targets are his next game
and his next 6 weeks (points/game, boom rate, bust rate). Every week is
scored exactly under GBFL rules from nflverse data (nflverse/score.py —
checked against CBS's own 2026 totals with --check-scoring).

Baselines are points-only: season-to-date and last-3 GBFL points per game.
A metric earns a spot in the app only if it beats them on the 2025 holdout
(PASS_R2 / PASS_RHO) and is stable (split-half r >= PASS_STABILITY).

    python backtest_metrics.py --check-scoring
    python backtest_metrics.py --positions WR RB TE --out results.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, pstdev, quantiles

from metrics.features import (BOOM_FEATURES, FEATURE_HELP, FEATURE_LABELS, PAR_POINTS_WEIGHT, ROLE_FEATURES,
                              PAR_BLEND, SHARE_STAT, by_player, load_season_games, window_features)
from metrics.availability import expected_games, miss_table, status_key, team_weeks
from metrics.features import implied_totals, injury_exit_weeks, injury_index
from metrics.rows import (BREAKOUT_FEATURES, BREAKOUT_POSITIONS, DECISIONS, HORIZON, MIN_FUTURE, MIN_OPP_PG,  # noqa: F401
                          MIN_OPP_PG_QB, MIN_PAST, NEXT_UP_VACANCY, add_breakout_context, decision_rows, delta as _delta,
                          mark_next_up, primary_pos as _primary_pos)
from metrics.grades import (Model, fit, fit_blend, par, pearson, percentile_grade, r2, replacement_rank,
                            load_weights, save_weights, spearman)

TRAIN = (2023, 2024)
TEST = 2025
BOOM_PCTL = 85
PASS_R2 = 0.02
PASS_RHO = 0.03
PASS_STABILITY = 0.5
EXIT_MIN_GAIN = 0.01  # a rule change has to beat the simpler rule by this on 2024 validation
LAMBDA = 5.0
BASE = ["ppg", "l3_ppg"]


def boom_cuts(games_by_season: dict[int, list[dict]], positions: list[str]) -> dict[str, float]:
    """Top-15% weekly GBFL score per position, from involved train-season games."""
    cuts = {}
    for pos in positions:
        pts = [g["gbfl"] for s in TRAIN for g in games_by_season[s]
               if g["pos"] == pos and ((g.get("attempts") or 0) + g["carries"] >= 10 if pos == "QB"
                                       else g["targets"] + g["carries"] >= 1)]
        cuts[pos] = quantiles(pts, n=100)[BOOM_PCTL - 1] if len(pts) > 100 else 0.0
    return cuts


def within_week_rho(rows: list[dict], pred: dict[int, float], target: str) -> float:
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        if r.get(target) is not None:
            groups[(r["season"], r["week"])].append(i)
    num = den = 0.0
    for idx in groups.values():
        if len(idx) < 5:
            continue
        rho = spearman([pred[i] for i in idx], [rows[i][target] for i in idx])
        num += rho * len(idx)
        den += len(idx)
    return num / den if den else 0.0


def evaluate(model: Model, rows: list[dict], target: str) -> dict:
    idx = [i for i, r in enumerate(rows) if r.get(target) is not None]
    pred = {i: model.predict(rows[i]) for i in idx}
    y = [rows[i][target] for i in idx]
    yhat = [pred[i] for i in idx]
    return {"n": len(idx), "r2": r2(y, yhat), "rho": within_week_rho(rows, pred, target), "pearson": pearson(yhat, y)}


def top_decile(model: Model, rows: list[dict], target: str = "y_ppg") -> float:
    """Mean future pts/game of the top 10% by the model, per decision week."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["season"], r["week"])].append(r)
    picks = []
    for sl in groups.values():
        sl = sorted(sl, key=lambda r: -model.predict(r))
        k = max(1, len(sl) // 10)
        picks.extend(r[target] for r in sl[:k])
    return fmean(picks) if picks else 0.0


def boot_delta_rho(base: Model, cand: Model, rows: list[dict], target: str, reps: int = 300, seed: int = 0) -> tuple[float, float]:
    """95% CI of Δ pooled Spearman (candidate − base), resampling players."""
    by_pid = defaultdict(list)
    for r in rows:
        if r.get(target) is not None:
            by_pid[r["player_id"]].append(r)
    pids = list(by_pid)
    pb = {id(r): base.predict(r) for p in pids for r in by_pid[p]}
    pc = {id(r): cand.predict(r) for p in pids for r in by_pid[p]}
    rng = random.Random(seed)
    deltas = []
    for _ in range(reps):
        sample = [r for p in rng.choices(pids, k=len(pids)) for r in by_pid[p]]
        y = [r[target] for r in sample]
        deltas.append(spearman([pc[id(r)] for r in sample], y) - spearman([pb[id(r)] for r in sample], y))
    deltas.sort()
    return deltas[int(0.025 * reps)], deltas[int(0.975 * reps) - 1]


def split_half(games_by_season: dict[int, list[dict]], seasons: list[int], pos: str, feats: list[str],
               models: dict[str, Model]) -> dict:
    """Odd-week vs even-week correlation for each raw feature and each model score."""
    odd_rows, even_rows = [], []
    for s in seasons:
        for gl in by_player(games_by_season[s]).values():
            if _primary_pos(gl) != pos or len(gl) < 8:
                continue
            odd = [g for g in gl if g["week"] % 2 == 1]
            even = [g for g in gl if g["week"] % 2 == 0]
            fo, fe = window_features(odd, pos), window_features(even, pos)
            if min(fo.get("opp_pg") or 0, fe.get("opp_pg") or 0) < MIN_OPP_PG:
                continue
            fo["l3_ppg"], fe["l3_ppg"] = fo["ppg"], fe["ppg"]
            # Next-game lines only exist at a decision week; the season's average line stands in.
            fo["next_implied"], fe["next_implied"] = fo.get("implied"), fe.get("implied")
            odd_rows.append(fo)
            even_rows.append(fe)
    out = {"n": len(odd_rows), "features": {}, "scores": {}}
    for f in ["ppg"] + feats:
        pairs = [(a[f], b[f]) for a, b in zip(odd_rows, even_rows) if a.get(f) is not None and b.get(f) is not None]
        out["features"][f] = pearson([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) > 10 else None
    for name, m in models.items():
        out["scores"][name] = pearson([m.predict(r) for r in odd_rows], [m.predict(r) for r in even_rows])
    return out


def _sweep_w(w: float, usage: list[str]) -> list[float]:
    return [w] + [(1 - w) / len(usage)] * len(usage)


def _rhos(model: Model, test: list[dict], waiver: list[dict]) -> dict:
    return {"all": evaluate(model, test, "y_ppg")["rho"], "waiver": evaluate(model, waiver, "y_ppg")["rho"]}


def run_position(pos: str, rows: list[dict], games_by_season: dict[int, list[dict]]) -> dict:
    train = [r for r in rows if r["season"] in TRAIN and r["pos"] == pos]
    test = [r for r in rows if r["season"] == TEST and r["pos"] == pos]
    waiver = [r for r in test if r["waiver_tier"]]
    role, boom, share = ROLE_FEATURES[pos], BOOM_FEATURES[pos], SHARE_STAT[pos]
    par_feats, par_w = PAR_BLEND[pos]
    usage = par_feats[1:]  # the non-points part of the PAR blend

    m = {
        # Mean (next-6 pts/game). "role_only" is the Role grade (the one share
        # stat); "par" is the fixed PAR_BLEND behind GBFL-PAR.
        # The *_all rows use all six usage stats, kept for comparison.
        "base_std": fit(train, ["ppg"], "y_ppg", LAMBDA),
        "base_l3": fit(train, ["l3_ppg"], "y_ppg", LAMBDA),
        "base": fit(train, BASE, "y_ppg", LAMBDA),
        "role_only": fit(train, [share], "y_ppg", LAMBDA),
        "par": fit_blend(train, par_feats, par_w, "y_ppg"),
        "role_all": fit(train, role, "y_ppg", LAMBDA),
        "par_all": fit(train, BASE + role, "y_ppg", LAMBDA),
        "full": fit(train, par_feats + boom, "y_ppg", LAMBDA),
        # Boom has to tell us something the share stat doesn't: boom rate or
        # week-to-week swing, with past boom rate / points and share in the model.
        "boom_rate_ctrl": fit(train, ["std_boom"] + usage, "y_boom", LAMBDA),
        "boom_rate": fit(train, ["std_boom"] + usage + boom, "y_boom", LAMBDA),
        "swing_ctrl": fit(train, par_feats, "y_sd", LAMBDA),
        "swing": fit(train, par_feats + boom, "y_sd", LAMBDA),
        "boom_only": fit(train, boom, "y_boom", LAMBDA),
        "mean_ctrl": fit(train, par_feats, "y_ppg", LAMBDA),
    }
    res: dict = {"pos": pos, "share_stat": share, "n_train": len(train), "n_test": len(test), "n_waiver": len(waiver)}

    ev = {}
    for name in ("base_std", "base_l3", "base", "role_only", "par", "role_all", "par_all", "full", "mean_ctrl"):
        ev[name] = {
            "all": evaluate(m[name], test, "y_ppg"),
            "waiver": evaluate(m[name], waiver, "y_ppg"),
            "next": evaluate(m[name], test, "y_next"),
            "next_waiver": evaluate(m[name], waiver, "y_next"),
            "top_decile_waiver": top_decile(m[name], waiver),
        }
    for name in ("boom_rate_ctrl", "boom_rate", "boom_only"):
        ev[name] = {"all": evaluate(m[name], test, "y_boom"), "waiver": evaluate(m[name], waiver, "y_boom")}
    for name in ("swing_ctrl", "swing"):
        ev[name] = {"all": evaluate(m[name], test, "y_sd"), "waiver": evaluate(m[name], waiver, "y_sd")}
    res["eval"] = ev

    res["ci"] = {
        "role_vs_base": boot_delta_rho(m["base"], m["role_only"], test, "y_ppg"),
        "par_vs_base": boot_delta_rho(m["base"], m["par"], test, "y_ppg"),
        "boom_rate_vs_ctrl": boot_delta_rho(m["boom_rate_ctrl"], m["boom_rate"], test, "y_boom"),
        "swing_vs_ctrl": boot_delta_rho(m["swing_ctrl"], m["swing"], test, "y_sd"),
        "full_vs_ctrl": boot_delta_rho(m["mean_ctrl"], m["full"], test, "y_ppg"),
        "par_vs_par_all": boot_delta_rho(m["par_all"], m["par"], test, "y_ppg"),
    }
    res["stability"] = split_half(games_by_season, [*TRAIN, TEST], pos, role + boom,
                                  {"role_only": m["role_only"], "boom_only": m["boom_only"], "par": m["par"], "base": m["base"]})

    def gate(cand: str, base: str, stab: str | None = None) -> dict:
        c, b = ev[cand]["all"], ev[base]["all"]
        d_r2, d_rho = c["r2"] - b["r2"], c["rho"] - b["rho"]
        stable = res["stability"]["scores"].get(stab) if stab else None
        ok = (d_r2 >= PASS_R2 or d_rho >= PASS_RHO) and (stable is None or stable >= PASS_STABILITY)
        return {"d_r2": d_r2, "d_rho": d_rho, "stability": stable, "pass": ok}

    boom_rate_gate = gate("boom_rate", "boom_rate_ctrl", stab="boom_only")
    swing_gate = gate("swing", "swing_ctrl", stab="boom_only")
    res["gates"] = {
        "role": gate("role_only", "base", stab="role_only"),
        "par": gate("par", "base", stab="par"),
        "boom_rate": boom_rate_gate,
        "boom_swing": swing_gate,
        "boom_mean": gate("full", "mean_ctrl"),
    }
    res["gates"]["boom"] = {"pass": boom_rate_gate["pass"] or swing_gate["pass"]}
    res["single_stat"] = {
        f: {"alone": _rhos(fit(train, [f], "y_ppg", LAMBDA), test, waiver),
            "with_ppg": _rhos(fit(train, ["ppg", f], "y_ppg", LAMBDA), test, waiver)}
        for f in role
    }
    # Points-vs-share weight: fit 2023 / validate 2024 to choose, 2025 only reports.
    y23 = [r for r in train if r["season"] == TRAIN[0]]
    y24 = [r for r in train if r["season"] == TRAIN[1]]
    res["weight_sweep"] = [{
        "w": w,
        "val_2024": evaluate(fit_blend(y23, par_feats, _sweep_w(w, usage), "y_ppg"), y24, "y_ppg")["rho"],
        **_rhos(fit_blend(train, par_feats, _sweep_w(w, usage), "y_ppg"), test, waiver),
    } for w in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0)]
    res["models"] = {k: v.to_dict() for k, v in m.items()}
    res["example"] = par_example(pos, test, m["par"], m["role_only"], share)
    return res


def par_example(pos: str, test: list[dict], par_model: Model, role: Model, share: str, week: int = 6) -> list[dict]:
    """2025, after week `week`: top waiver-tier players by PAR, with what they did next."""
    sl = [r for r in test if r["week"] == week]
    pred = {r["player_id"]: par_model.predict(r) for r in sl}
    pars = par(pred, pos, week)
    role_pct = percentile_grade({r["player_id"]: role.predict(r) for r in sl})
    waiver = sorted((r for r in sl if r["waiver_tier"]), key=lambda r: -pars[r["player_id"]])[:10]
    return [{
        "player": r["player"], "team": r["team"], "ppg": r["ppg"], "games": r["n"],
        "role_grade": role_pct[r["player_id"]], "share": r.get(share), "snap_pct": r.get("snap_pct"),
        "pred_ppg": pred[r["player_id"]],
        "par": pars[r["player_id"]], "y_ppg": r["y_ppg"],
    } for r in waiver]


def exit_test(pos: str, keep_rows: list[dict], drop_rows: list[dict]) -> dict:
    """Keep or drop injury-shortened games from the features? Chosen on 2024 (fit 2023)
    with the PAR blend; 2025 only reports."""
    feats, w = PAR_BLEND[pos]

    def val(rows):
        y23 = [r for r in rows if r["pos"] == pos and r["season"] == TRAIN[0]]
        y24 = [r for r in rows if r["pos"] == pos and r["season"] == TRAIN[1]]
        return evaluate(fit_blend(y23, feats, w, "y_ppg"), y24, "y_ppg")["rho"]

    def test(rows):
        tr = [r for r in rows if r["pos"] == pos and r["season"] in TRAIN]
        te = [r for r in rows if r["pos"] == pos and r["season"] == TEST]
        return _rhos(fit_blend(tr, feats, w, "y_ppg"), te, [r for r in te if r["waiver_tier"]])

    vk, vd = val(keep_rows), val(drop_rows)
    n_ex = sum(1 for r in drop_rows if r["pos"] == pos and r["exits_dropped"])
    n = sum(1 for r in drop_rows if r["pos"] == pos)
    return {"val_keep": vk, "val_drop": vd, "drop": vd >= vk + EXIT_MIN_GAIN, "test_keep": test(keep_rows), "test_drop": test(drop_rows),
            "rows_with_exits": n_ex / n if n else 0.0}


def _avail_obs(r: dict) -> dict:
    return {"status": r["status"], "team_games": r["team_games6"], "played": r["played6"],
            "played_next": r["played_next"] if r["team_plays_next"] else r["played6"] > 0}


def availability_test(pos: str, rows: list[dict], par_model: Model, table: dict) -> dict:
    """Does scaling per-game value by expected games (from report status) rank next-6
    total points better than per-game value × team games? Missed games count as 0."""
    te = [r for r in rows if r["pos"] == pos and r["season"] == TEST and r["team_games6"] > 0]
    wv = [r for r in te if r["waiver_tier"]]
    for r in te:
        pg = max(0.0, par_model.predict(r))
        r["_plain"] = pg * r["team_games6"]
        r["_avail"] = pg * expected_games(r["status"], r["team_games6"], table)
    plain = Model(["_plain"], [0.0], [1.0], [0.0, 1.0])
    avail = Model(["_avail"], [0.0], [1.0], [0.0, 1.0])
    a = {"all": evaluate(plain, te, "y_total6")["rho"], "waiver": evaluate(plain, wv, "y_total6")["rho"]}
    b = {"all": evaluate(avail, te, "y_total6")["rho"], "waiver": evaluate(avail, wv, "y_total6")["rho"]}
    ci = boot_delta_rho(plain, avail, te, "y_total6")
    injured = [r for r in te if r["status"] != "Healthy"]
    return {"plain": a, "avail": b, "d_rho": b["all"] - a["all"], "ci": ci, "pass": b["all"] - a["all"] >= PASS_RHO or ci[0] > 0,
            "n": len(te), "n_injured": len(injured)}


def boot_rho(model: Model, rows: list[dict], target: str, reps: int = 300, seed: int = 0) -> tuple[float, float]:
    """95% CI of one model's pooled Spearman, resampling players."""
    by_pid = defaultdict(list)
    for r in rows:
        if r.get(target) is not None:
            by_pid[r["player_id"]].append(r)
    pids = list(by_pid)
    pred = {id(r): model.predict(r) for p in pids for r in by_pid[p]}
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        sample = [r for p in rng.choices(pids, k=len(pids)) for r in by_pid[p]]
        vals.append(spearman([pred[id(r)] for r in sample], [r[target] for r in sample]))
    vals.sort()
    return vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1]


def breakout_test(pos: str, rows: list[dict]) -> dict:
    """Breakout = recent usage change + teammate injuries, fit to predict the change in
    points/game (next 6 minus season so far). Passes if its 2025 ρ with that change has a
    95% CI above 0. Also tested as an add-on to a fitted PAR-inputs model."""
    train = [r for r in rows if r["season"] in TRAIN and r["pos"] == pos and r.get("y_delta") is not None]
    test = [r for r in rows if r["season"] == TEST and r["pos"] == pos and r.get("y_delta") is not None]
    waiver = [r for r in test if r["waiver_tier"]]
    par_feats = PAR_BLEND[pos][0]
    inj_feats = ["vac_pos", "vac_pos_x_share", "vac_tgt", "ret_pos"]
    bo = fit(train, BREAKOUT_FEATURES, "y_delta", LAMBDA)
    trend = fit(train, ["d_share", "d_snap"], "y_delta", LAMBDA)
    inj_only = fit(train, inj_feats, "y_delta", LAMBDA)
    par_fit = fit(train, par_feats, "y_ppg", LAMBDA)
    par_bo = fit(train, par_feats + BREAKOUT_FEATURES, "y_ppg", LAMBDA)
    par_inj = fit(train, par_feats + inj_feats, "y_ppg", LAMBDA)
    out = {
        "n_test": len(test), "n_waiver": len(waiver),
        "breakout": {"all": evaluate(bo, test, "y_delta")["rho"], "waiver": evaluate(bo, waiver, "y_delta")["rho"],
                     "ci": boot_rho(bo, test, "y_delta"), "ci_waiver": boot_rho(bo, waiver, "y_delta")},
        "trend_only": {"all": evaluate(trend, test, "y_delta")["rho"], "waiver": evaluate(trend, waiver, "y_delta")["rho"]},
        "injury_only": {"all": evaluate(inj_only, test, "y_delta")["rho"], "waiver": evaluate(inj_only, waiver, "y_delta")["rho"],
                        "ci": boot_rho(inj_only, test, "y_delta")},
        "par": _rhos(par_fit, test, waiver),
        "par_plus_breakout": _rhos(par_bo, test, waiver),
        "par_plus_injury": _rhos(par_inj, test, waiver),
        "ci_add": boot_delta_rho(par_fit, par_bo, test, "y_ppg"),
        "ci_add_waiver": boot_delta_rho(par_fit, par_bo, waiver, "y_ppg"),
        "coefs": dict(zip(bo.feats, bo.coefs[1:])),
        "coef_sds": dict(zip(bo.feats, bo.sds)),
        "share_with_vacancy": sum(1 for r in test if r["vac_pos"] > 0) / len(test) if test else 0.0,
        "model": bo.to_dict(),
    }
    out["pass"] = out["breakout"]["ci"][0] > 0
    out["adds_to_par"] = (out["par_plus_breakout"]["all"] - out["par"]["all"] >= PASS_RHO) or out["ci_add"][0] > 0
    # Spot check: 2025 waiver-tier players with the highest Breakout score, weeks 3–10.
    cand = sorted((r for r in waiver if r["week"] <= 10), key=lambda r: -bo.predict(r))
    seen, ex = set(), []
    for r in cand:
        if r["player_id"] in seen:
            continue
        seen.add(r["player_id"])
        ex.append({"player": r["player"], "team": r["team"], "week": r["week"], "score": bo.predict(r),
                   "ppg": r["ppg"], "y_ppg": r["y_ppg"], "d_share": r.get("d_share"), "vac_pos": r["vac_pos"],
                   "share": r.get(SHARE_STAT[pos])})
        if len(ex) == 10:
            break
    out["examples"] = ex
    return out


def _boot_mean(vals_by_player: dict[str, list[float]], reps: int = 1000, seed: int = 0) -> tuple[float, float]:
    ids = list(vals_by_player)
    if not ids:
        return 0.0, 0.0
    rng = random.Random(seed)
    means = sorted(fmean([v for p in rng.choices(ids, k=len(ids)) for v in vals_by_player[p]]) for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def next_up_test(rows: list[dict]) -> dict:
    """How much flagged RBs beat their PAR prediction (next-6 pts/game), by group."""
    rb = [r for r in rows if r["pos"] == "RB" and r.get("y_ppg") is not None]
    feats, w = PAR_BLEND["RB"]
    par_model = fit_blend([r for r in rb if r["season"] in TRAIN], feats, w, "y_ppg")
    groups = {
        "next_up_train": [r for r in rb if r["next_up"] and r["season"] in TRAIN],
        "next_up_test": [r for r in rb if r["next_up"] and r["season"] == TEST],
        "next_up_waiver": [r for r in rb if r["next_up"] and r["waiver_tier"]],
        "other_backups": [r for r in rb if r.get("vac_pos", 0) >= NEXT_UP_VACANCY and not r["next_up"]],
    }
    out = {}
    for name, grp in groups.items():
        by = defaultdict(list)
        for r in grp:
            by[r["player_id"]].append(r["y_ppg"] - par_model.predict(r))
        out[name] = {
            "n": len(grp), "players": len(by),
            "actual": fmean(r["y_ppg"] for r in grp) if grp else None,
            "predicted": fmean(par_model.predict(r) for r in grp) if grp else None,
            "miss": fmean(v for vs in by.values() for v in vs) if grp else None,
            "ci": _boot_mean(by),
        }
    weeks = defaultdict(int)
    for r in rb:
        if r["next_up"]:
            weeks[(r["season"], r["week"])] += 1
    out["per_week"] = fmean(weeks.values()) if weeks else 0.0
    ex = sorted((r for r in groups["next_up_test"]), key=lambda r: -r["vac_pos"])[:10]
    out["examples"] = [{"player": r["player"], "team": r["team"], "week": r["week"], "opp_share": r.get("opp_share"),
                        "vac": r["vac_pos"], "ppg": r["ppg"], "pred": par_model.predict(r), "y_ppg": r["y_ppg"]} for r in ex]
    return out


def qb_extra_test(cuts: dict, seasons=(2021, 2022, TEST)) -> dict:
    """The frozen 2023–24 QB blend on more held-out seasons: 2021–22 plus 2025."""
    from nflverse.pull import load

    from metrics.features import _optional

    def rows_for(s):
        return decision_rows(load_season_games(s), s, ["QB"], cuts, inj=injury_index(_optional(load, "injuries", s)),
                             team_weeks=team_weeks(load("games"), s), implied=implied_totals(load("games"), s))

    train = [r for s in TRAIN for r in rows_for(s)]
    feats, w = PAR_BLEND["QB"]
    par_m, base = fit_blend(train, feats, w, "y_ppg"), fit(train, BASE, "y_ppg", LAMBDA)
    pooled = [r for s in seasons for r in rows_for(s)]
    wv = [r for r in pooled if r["waiver_tier"]]
    out = {"seasons": list(seasons), "n": len(pooled), "n_waiver": len(wv)}
    for key, rows_, tgt in (("next6", pooled, "y_ppg"), ("next_game", pooled, "y_next"),
                            ("next6_waiver", wv, "y_ppg"), ("next_game_waiver", wv, "y_next")):
        out[key] = {"base": evaluate(base, rows_, tgt)["rho"], "par": evaluate(par_m, rows_, tgt)["rho"],
                    "ci": boot_delta_rho(base, par_m, rows_, tgt)}
    return out


def check_scoring() -> dict:
    from nflverse.pull import load
    from nflverse.score import check_against_cbs

    res = check_against_cbs(load("stats_player_week", 2026), load("pbp", 2026), [1, 2, 3])
    print(f"nflverse vs CBS Total, 2026 weeks 1–3: {res['exact']}/{res['n']} exact ({res['rate']:.1%}); "
          f"{len(res['unmatched'])} CBS rows with no nflverse name match")
    for mm in res["mismatches"][:20]:
        print(f"  wk{mm['week']} {mm['pos']} {mm['player']}: CBS {mm['cbs']} vs ours {mm['ours']}")
    return {k: v for k, v in res.items() if k != "mismatches"} | {"mismatches": res["mismatches"][:50]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--positions", nargs="+", default=["WR", "RB", "TE", "QB"])
    ap.add_argument("--check-scoring", action="store_true")
    ap.add_argument("--out", type=Path, default=None, help="write full results JSON here")
    ap.add_argument("--no-weights", action="store_true", help="don't write metrics/weights.json")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # ρ/Δ/² in the summary; the Windows console defaults to cp1252

    scoring = check_scoring()
    if args.check_scoring:
        return 0 if scoring["rate"] >= 0.95 else 1

    from nflverse.pull import load

    seasons = (*TRAIN, TEST)
    games = {s: load_season_games(s) for s in seasons}
    inj = {s: injury_index(load("injuries", s)) for s in seasons}
    tweeks = {s: team_weeks(load("games"), s) for s in seasons}
    implied = {s: implied_totals(load("games"), s) for s in seasons}
    cuts = boom_cuts(games, args.positions)

    def all_rows(exclude, require_future=True):
        return [r for s in seasons for r in decision_rows(games[s], s, args.positions, cuts, exclude_exits=exclude,
                                                          require_future=require_future, inj=inj[s], team_weeks=tweeks[s],
                                                          implied=implied[s])]

    exits = {pos: exit_test(pos, all_rows(False), all_rows(True)) for pos in args.positions}
    drop_for = {p for p, e in exits.items() if e["drop"]}
    rows = all_rows(drop_for)
    for s in seasons:
        add_breakout_context([r for r in rows if r["season"] == s], games[s], inj[s], tweeks[s])
    mark_next_up(rows)
    results = {
        "config": {"train": TRAIN, "test": TEST, "decisions": [DECISIONS.start, DECISIONS.stop - 1],
                   "horizon": HORIZON, "boom_pctl": BOOM_PCTL, "boom_cuts": cuts, "min_opp_pg": MIN_OPP_PG,
                   "pass_r2": PASS_R2, "pass_rho": PASS_RHO, "pass_stability": PASS_STABILITY, "lambda": LAMBDA,
                   "share_stat": SHARE_STAT, "par_points_weight": PAR_POINTS_WEIGHT,
                   "par_blend": PAR_BLEND},
        "labels": FEATURE_LABELS,
        "help": FEATURE_HELP,
        "scoring_check": scoring,
        "injury_exits": exits,
        "positions": {},
    }
    avail_rows = all_rows(drop_for, require_future=False)
    table = miss_table([_avail_obs(r) for r in avail_rows if r["season"] in TRAIN and r["team_games6"] > 0])
    results["miss_table"] = {"train": table,
                             "test": miss_table([_avail_obs(r) for r in avail_rows if r["season"] == TEST and r["team_games6"] > 0])}
    print("\nAvailability by report status (train 2023–24): " + " · ".join(
        f"{s} n={v['n']} plays next {v['play_next']:.0%} misses {v['miss_rate']:.0%} of next 6"
        for s, v in table.items() if v["n"]))
    for pos in args.positions:
        res = run_position(pos, rows, games)
        res["availability"] = availability_test(pos, avail_rows, Model.from_dict(res["models"]["par"]), table)
        if pos in BREAKOUT_POSITIONS:
            res["breakout"] = breakout_test(pos, rows)
        results["positions"][pos] = res
        g = res["gates"]
        e = res["eval"]
        ex, av = exits[pos], res["availability"]
        print(f"\n{pos}: train {res['n_train']} / test {res['n_test']} rows (waiver tier {res['n_waiver']}); boom cut {cuts[pos]:.1f}")
        print(f"  injury exits: 2024 val ρ keep {ex['val_keep']:.3f} vs drop {ex['val_drop']:.3f} -> {'DROP' if ex['drop'] else 'keep'}"
              f" | 2025 PAR ρ {ex['test_keep']['all']:.3f}/{ex['test_keep']['waiver']:.3f} vs {ex['test_drop']['all']:.3f}/{ex['test_drop']['waiver']:.3f}")
        print(f"  availability (next-6 total pts): ρ per-game only {av['plain']['all']:.3f}/{av['plain']['waiver']:.3f}"
              f" -> with status {av['avail']['all']:.3f}/{av['avail']['waiver']:.3f} (Δ {av['d_rho']:+.3f}, CI {av['ci'][0]:+.3f} to {av['ci'][1]:+.3f})"
              f" -> {'PASS' if av['pass'] else 'no'}")
        if "breakout" in res:
            b = res["breakout"]
            print(f"  breakout vs pts change: ρ {b['breakout']['all']:.3f} (CI {b['breakout']['ci'][0]:+.3f} to {b['breakout']['ci'][1]:+.3f})"
                  f" waiver {b['breakout']['waiver']:.3f} | trend only {b['trend_only']['all']:.3f} | injuries only {b['injury_only']['all']:.3f}"
                  f" -> {'PASS' if b['pass'] else 'no'}")
            print(f"  PAR inputs {b['par']['all']:.3f}/{b['par']['waiver']:.3f} -> + breakout {b['par_plus_breakout']['all']:.3f}/{b['par_plus_breakout']['waiver']:.3f}"
                  f" (CI {b['ci_add'][0]:+.3f} to {b['ci_add'][1]:+.3f}) | + injuries only {b['par_plus_injury']['all']:.3f}/{b['par_plus_injury']['waiver']:.3f}"
                  f" | rows with a vacancy {b['share_with_vacancy']:.0%}")
        for name in ("base_std", "base_l3", "base", "role_only", "par", "role_all", "par_all", "full"):
            a, w = e[name]["all"], e[name]["waiver"]
            print(f"  {name:14s} R² {a['r2']:.3f}  ρ {a['rho']:.3f} | waiver R² {w['r2']:.3f} ρ {w['rho']:.3f} "
                  f"top10% {e[name]['top_decile_waiver']:.2f} | next-wk ρ {e[name]['next']['rho']:.3f}")
        for name in ("boom_rate_ctrl", "boom_rate", "boom_only", "swing_ctrl", "swing"):
            a = e[name]["all"]
            print(f"  {name:14s} R² {a['r2']:.3f}  ρ {a['rho']:.3f}")
        for k, v in g.items():
            if "d_r2" not in v:
                print(f"  gate {k:12s} -> {'PASS' if v['pass'] else 'no'}")
                continue
            stab = "—" if v["stability"] is None else f"{v['stability']:.2f}"
            print(f"  gate {k:12s} ΔR² {v['d_r2']:+.3f} Δρ {v['d_rho']:+.3f} stability {stab} -> {'PASS' if v['pass'] else 'no'}")

    if "RB" in args.positions:
        nu = results["rb_next_up"] = next_up_test(rows)
        print("\nRB next man up (vs PAR prediction, next-6 pts/g): " + " · ".join(
            f"{k} n={v['n']} {v['miss']:+.2f} (CI {v['ci'][0]:+.2f} to {v['ci'][1]:+.2f})"
            for k, v in nu.items() if isinstance(v, dict) and "miss" in v and v["n"]) + f" · {nu['per_week']:.1f}/week")
    if "QB" in args.positions:
        q = results["qb_extra"] = qb_extra_test(cuts)
        print("QB, frozen blend on 2021–22 + 2025: " + " · ".join(
            f"{k} {v['base']:.3f}->{v['par']:.3f} (CI {v['ci'][0]:+.3f} to {v['ci'][1]:+.3f})"
            for k, v in q.items() if isinstance(v, dict)))

    if not args.no_weights:
        keep = {k: v for k, v in load_weights().items() if k == "rb_pedigree_bump"}  # written by backtest_pedigree.py
        save_weights({**keep, 
            "fit_on": list(TRAIN), "boom_cuts": cuts, "config": results["config"],
            "share_stat": SHARE_STAT, "par_points_weight": PAR_POINTS_WEIGHT, "par_blend": PAR_BLEND, "help": FEATURE_HELP,
            "drop_injury_exits": sorted(drop_for), "miss_table": table, "next_up_vacancy": NEXT_UP_VACANCY,
            "positions": {p: {"models": r["models"], "gates": r["gates"],
                              **({"breakout": r["breakout"]["model"]} if "breakout" in r else {})}
                          for p, r in results["positions"].items()},
        })
    if args.out:
        args.out.write_text(json.dumps(results, indent=2, default=list), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
