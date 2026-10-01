"""Rest-of-season QB projection backtest (metrics/qb.py), 2013–2025.

Target: a QB's points per game over weeks d+1..18 (3+ games), at decision weeks 4–12.
Leave-one-season-out: every season is predicted by a model fit on the other twelve, so
nothing is scored on data it was fit on. Baseline: points per game so far. A set passes if
its pooled rank correlation beats the baseline with a bootstrap 95% CI (resampling players)
above zero. The final model is fit on all seasons and saved to metrics/weights.json.

    python backtest_qb.py --out qb_ros.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import fmean

from metrics.features import by_player, load_season_games
from metrics.grades import fit, load_weights, save_weights, spearman
from metrics.qb import QB_FEATURES, SEASON_GAMES, qb_row

SEASONS = list(range(2013, 2026))
FIRST_PRIOR_SEASON = 2012
DECISIONS = (4, 6, 8, 10, 12)
MIN_FUTURE_GAMES = 3
LAMBDA = 5.0
SETS = {
    "Points so far": ["ppg"],
    "+ last two seasons": ["ppg", "prior_ppg_i", "has_prior"],
    "+ weighted by games played": ["ppg", "prior_ppg_i", "has_prior", "ppg_x_g", "prior_x_g"],
    "+ EPA per play (the model)": QB_FEATURES,
}


def build_rows() -> tuple[list[dict], float]:
    games = {s: by_player([g for g in load_season_games(s) if g["pos"] == "QB"]) for s in range(FIRST_PRIOR_SEASON, SEASONS[-1] + 1)}
    prior_ppgs = []
    from metrics.features import window_features

    for s in SEASONS:
        for pid in games[s]:
            for back in (1,):
                gl = games.get(s - back, {}).get(pid, [])
                if len(gl) >= 5:
                    prior_ppgs.append(window_features(gl, "QB")["ppg"])
    mean_prior = fmean(prior_ppgs)
    rows = []
    for s in SEASONS:
        for pid, gl in games[s].items():
            prior = {b: games.get(s - b, {}).get(pid, []) for b in (1, 2)}
            for d in DECISIONS:
                past = [g for g in gl if g["week"] <= d]
                fut = [g for g in gl if g["week"] > d]
                if len(fut) < MIN_FUTURE_GAMES:
                    continue
                r = qb_row(past, prior, mean_prior)
                if r is None:
                    continue
                r.update({"player_id": pid, "player": gl[-1]["player"], "season": s, "week": d, "y_ros": fmean(g["gbfl"] for g in fut)})
                rows.append(r)
    return rows, mean_prior


def within_rho(rows: list[dict], pred: list[float]) -> float:
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[(r["season"], r["week"])].append(i)
    num = den = 0.0
    for idx in groups.values():
        if len(idx) < 8:
            continue
        num += spearman([pred[i] for i in idx], [rows[i]["y_ros"] for i in idx]) * len(idx)
        den += len(idx)
    return num / den if den else 0.0


def top_n_hit(rows: list[dict], pred: list[float], n: int = 12) -> float:
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[(r["season"], r["week"])].append(i)
    hits = tot = 0
    for idx in groups.values():
        if len(idx) < n * 1.5:
            continue
        hits += len(set(sorted(idx, key=lambda i: -rows[i]["y_ros"])[:n]) & set(sorted(idx, key=lambda i: -pred[i])[:n]))
        tot += n
    return hits / tot if tot else float("nan")


def loso(rows: list[dict], feats: list[str]) -> list[float]:
    pred = [0.0] * len(rows)
    for s in sorted({r["season"] for r in rows}):
        m = fit([r for r in rows if r["season"] != s], feats, "y_ros", LAMBDA)
        for i, r in enumerate(rows):
            if r["season"] == s:
                pred[i] = m.predict(r)
    return pred


def boot_delta(rows: list[dict], base: list[float], cand: list[float], reps: int = 300) -> tuple[float, float]:
    by = defaultdict(list)
    for i, r in enumerate(rows):
        by[r["player_id"]].append(i)
    ids = list(by)
    rng = random.Random(0)
    ds = []
    for _ in range(reps):
        idx = [i for p in rng.choices(ids, k=len(ids)) for i in by[p]]
        sub = [rows[i] for i in idx]
        ds.append(within_rho(sub, [cand[i] for i in idx]) - within_rho(sub, [base[i] for i in idx]))
    ds.sort()
    return ds[int(0.025 * reps)], ds[int(0.975 * reps) - 1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-weights", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    rows, mean_prior = build_rows()
    seasons = sorted({r["season"] for r in rows})
    print(f"{len(rows)} QB decision rows, {len({r['player_id'] for r in rows})} QBs, seasons {seasons[0]}-{seasons[-1]}")
    recent = [i for i, r in enumerate(rows) if r["season"] >= 2021]
    base = loso(rows, SETS["Points so far"])
    results = {"n": len(rows), "qbs": len({r["player_id"] for r in rows}), "seasons": [seasons[0], seasons[-1]], "sets": {}, "by_week": {}}
    preds = {}
    for name, feats in SETS.items():
        pr = loso(rows, feats)
        preds[name] = pr
        lo, hi = boot_delta(rows, base, pr) if name != "Points so far" else (0.0, 0.0)
        rr = [rows[i] for i in recent]
        results["sets"][name] = {
            "rho": within_rho(rows, pr), "top12": top_n_hit(rows, pr), "rho_2021plus": within_rho(rr, [pr[i] for i in recent]),
            "top12_2021plus": top_n_hit(rr, [pr[i] for i in recent]), "d_rho": within_rho(rows, pr) - within_rho(rows, base), "ci": [lo, hi]}
        s = results["sets"][name]
        print(f"  {name:30s} ρ {s['rho']:.3f}  top-12 {s['top12']:.1%} | 2021+ ρ {s['rho_2021plus']:.3f}  Δρ {s['d_rho']:+.3f} (CI {lo:+.3f} to {hi:+.3f})")
    for d in DECISIONS:
        idx = [i for i, r in enumerate(rows) if r["week"] == d]
        sub = [rows[i] for i in idx]
        results["by_week"][d] = {"n": len(sub), **{name: within_rho(sub, [preds[name][i] for i in idx]) for name in SETS}}
    print("  by decision week:", {d: {k: round(v, 3) for k, v in w.items() if k != "n"} for d, w in results["by_week"].items()})
    final = fit(rows, QB_FEATURES, "y_ros", LAMBDA)
    results["model"] = final.to_dict()
    results["mean_prior"] = mean_prior
    results["coefs_per_sd"] = dict(zip(final.feats, final.coefs[1:]))
    print("  final model coefficients per SD:", {k: round(v, 3) for k, v in results["coefs_per_sd"].items()})
    if not args.no_weights:
        w = load_weights()
        w["qb_ros"] = {"model": final.to_dict(), "mean_prior": mean_prior, "features": QB_FEATURES, "fit_seasons": [seasons[0], seasons[-1]],
                       "loso_rho": results["sets"]["+ EPA per play (the model)"]["rho"], "baseline_rho": results["sets"]["Points so far"]["rho"]}
        save_weights(w)
    if args.out:
        args.out.write_text(json.dumps(results, indent=1, default=list), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
