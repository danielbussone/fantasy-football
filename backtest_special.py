"""Gate 3 backtest: kickers and team defenses.

Every week is scored exactly from nflverse (nflverse/score.py; checked against CBS
2026 weeks 1–3 with --check-scoring). Features use only weeks <= decision week d.
Two targets: the next game (K and DST are streamed weekly) and the next 6 weeks
(points per game). Baseline: GBFL points per game so far. Feature sets are picked
by forward selection with 2023 fit / 2024 validation; the final model is fit on
2023–24 and tested on 2021, 2022 and 2025 pooled (about 32 starters a season is
too few for one test season). A metric passes if it beats the baseline by at
least PASS_RHO with a bootstrap 95% CI above zero.

    python backtest_special.py --out special.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import fmean

import backtest_metrics as bt
from metrics.availability import team_weeks
from metrics.features import implied_totals
from metrics.grades import fit
from nflverse.pull import load
from nflverse.score import dst_games, kicker_games, score_dst, score_kicker

FIT = (2023, 2024)
TEST = (2021, 2022, 2025)
SEASONS = (2021, 2022, 2023, 2024, 2025)
DECISIONS = range(3, 17)
HORIZON = 6
PASS_RHO = 0.03
LAMBDA = 5.0
ROSTERED = {"K": 20, "DST": 20}  # 10 teams × 2

K_FEATURES = ["fg_att_pg", "fg50_share", "fg50_att_pg", "xp_att_pg", "fg_pct", "implied", "next_implied", "next_dome"]
DST_FEATURES = ["sacks_pg", "takeaways_pg", "pa_pg", "def_td_pg", "next_opp_implied", "next_opp_sacks_allowed",
                "next_opp_giveaways", "next_home", "next_implied_own", "sched6_opp_implied"]
LABELS = {
    "ppg": "GBFL pts/game so far",
    "fg_att_pg": "FG attempts/game", "fg50_share": "Share of FG attempts from 50+", "fg50_att_pg": "50+ FG attempts/game",
    "xp_att_pg": "XP attempts/game", "fg_pct": "FG accuracy", "implied": "Team implied total (season avg)",
    "next_implied": "Next game implied team total", "next_dome": "Next game in a dome",
    "sacks_pg": "Sacks/game", "takeaways_pg": "Takeaways/game", "pa_pg": "Points allowed/game",
    "def_td_pg": "Defensive/ST TDs/game", "next_opp_implied": "Next opponent's implied total",
    "next_opp_sacks_allowed": "Next opponent's sacks allowed/game", "next_opp_giveaways": "Next opponent's giveaways/game",
    "next_home": "Next game at home", "next_implied_own": "Own team implied total, next game",
    "sched6_opp_implied": "Next 6 opponents' season-avg implied total",
}


def _schedule_index(schedule: list[dict], season: int) -> dict[tuple[str, int], dict]:
    out = {}
    for g in schedule:
        if str(g.get("season")) != str(season) or g.get("game_type") != "REG":
            continue
        wk = int(g["week"])
        dome = 1.0 if (g.get("roof") or "") in ("dome", "closed") else 0.0
        out[(g["home_team"], wk)] = {"opp": g["away_team"], "home": 1.0, "dome": dome}
        out[(g["away_team"], wk)] = {"opp": g["home_team"], "home": 0.0, "dome": dome}
    return out


def _next_week(team: str, d: int, tweeks: dict[str, set[int]]) -> int | None:
    return min((w for w in tweeks.get(team, set()) if w > d), default=None)


def _tag_waiver(rows: list[dict], pos: str) -> None:
    by = defaultdict(list)
    for r in rows:
        by[(r["season"], r["week"])].append(r)
    for sl in by.values():
        sl.sort(key=lambda r: -r["ppg"])
        for i, r in enumerate(sl):
            r["waiver_tier"] = i >= ROSTERED[pos]


def kicker_rows(season: int, schedule: list[dict]) -> list[dict]:
    kg = kicker_games(load("pbp", season))
    imp = implied_totals(schedule, season)
    sched = _schedule_index(schedule, season)
    tweeks = team_weeks(schedule, season)
    by_k = defaultdict(list)
    for (kid, wk), k in kg.items():
        by_k[kid].append({**k, "week": wk, "pts": score_kicker(k), "implied": imp.get((k["team"], wk))})
    names = {p["gsis_id"]: p.get("display_name") or "" for p in load("players") if p.get("gsis_id")}
    rows = []
    for kid, gl in by_k.items():
        gl.sort(key=lambda g: g["week"])
        for d in DECISIONS:
            past = [g for g in gl if g["week"] <= d]
            fut = [g for g in gl if d < g["week"] <= d + HORIZON]
            if len(past) < 2:
                continue
            team = past[-1]["team"]
            nw = _next_week(team, d, tweeks)
            nxt = next((g for g in fut if g["week"] == nw), None)
            att = sum(g["fg_att"] for g in past)
            made = sum(len(g["fg_yards"]) for g in past)
            imps = [g["implied"] for g in past if g["implied"] is not None]
            n = len(past)
            rows.append({
                "player_id": kid, "player": names.get(kid, kid), "team": team, "season": season, "week": d,
                "ppg": fmean(g["pts"] for g in past),
                "fg_att_pg": att / n, "fg50_att_pg": sum(g["fg_att_50"] for g in past) / n,
                "fg50_share": sum(g["fg_att_50"] for g in past) / att if att >= 3 else None,
                "xp_att_pg": sum(g["xp_att"] for g in past) / n,
                "fg_pct": made / att if att >= 5 else None,
                "implied": fmean(imps) if imps else None,
                "next_implied": imp.get((team, nw)) if nw else None,
                "next_dome": (sched.get((team, nw)) or {}).get("dome") if nw else None,
                "y_next": nxt["pts"] if nxt else None,
                "y_ppg": fmean(g["pts"] for g in fut) if len(fut) >= 2 else None,
            })
    _tag_waiver(rows, "K")
    return rows


def dst_rows(season: int, schedule: list[dict]) -> list[dict]:
    dg = dst_games(load("pbp", season), load("stats_team_week", season), schedule, season)
    tw = {(r["team"], int(r["week"])): r for r in load("stats_team_week", season) if r.get("season_type") == "REG"}
    imp = implied_totals(schedule, season)
    sched = _schedule_index(schedule, season)
    tweeks = team_weeks(schedule, season)
    by_t = defaultdict(list)
    for (team, wk), g in dg.items():
        t = tw.get((team, wk)) or {}
        by_t[team].append({**g, "pts": score_dst(g),
                           # what this team's offense gave up that week
                           "off_sacks": float(t.get("sacks_suffered") or 0),
                           "off_giveaways": float(t.get("passing_interceptions") or 0) + float(t.get("sack_fumbles_lost") or 0)
                           + float(t.get("rushing_fumbles_lost") or 0) + float(t.get("receiving_fumbles_lost") or 0)})
    for gl in by_t.values():
        gl.sort(key=lambda g: g["week"])
    rows = []
    for team, gl in by_t.items():
        for d in DECISIONS:
            past = [g for g in gl if g["week"] <= d]
            fut = [g for g in gl if d < g["week"] <= d + HORIZON]
            if len(past) < 2:
                continue
            nw = _next_week(team, d, tweeks)
            nxt = next((g for g in fut if g["week"] == nw), None)
            opp = (sched.get((team, nw)) or {}).get("opp") if nw else None
            opp_past = [g for g in by_t.get(opp, []) if g["week"] <= d] if opp else []
            n = len(past)
            # Schedule strength: each of the next 6 opponents' average implied total so far (known at week d).
            opp_avgs = []
            for w in sorted(x for x in tweeks.get(team, set()) if d < x <= d + HORIZON):
                o = (sched.get((team, w)) or {}).get("opp")
                vals = [imp[(o, x)] for x in range(1, d + 1) if (o, x) in imp]
                if vals:
                    opp_avgs.append(fmean(vals))
            rows.append({
                "sched6_opp_implied": fmean(opp_avgs) if opp_avgs else None,
                "player_id": team, "player": team, "team": team, "season": season, "week": d,
                "ppg": fmean(g["pts"] for g in past),
                "sacks_pg": sum(g["sacks"] for g in past) / n,
                "takeaways_pg": sum(g["ints"] + g["fr"] for g in past) / n,
                "pa_pg": sum(g["pa"] for g in past) / n,
                "def_td_pg": sum(len(g["def_td_yards"]) for g in past) / n,
                "next_opp_implied": imp.get((opp, nw)) if opp else None,
                "next_implied_own": imp.get((team, nw)) if nw else None,
                "next_opp_sacks_allowed": fmean(g["off_sacks"] for g in opp_past) if opp_past else None,
                "next_opp_giveaways": fmean(g["off_giveaways"] for g in opp_past) if opp_past else None,
                "next_home": (sched.get((team, nw)) or {}).get("home") if nw else None,
                "y_next": nxt["pts"] if nxt else None,
                "y_ppg": fmean(g["pts"] for g in fut) if len(fut) >= 2 else None,
            })
    _tag_waiver(rows, "DST")
    return rows


def _fit(rows, feats, target):
    return fit([r for r in rows if r.get(target) is not None], feats, target, LAMBDA)


def forward_select(y23: list[dict], y24: list[dict], cands: list[str], target: str, start=("ppg",)) -> list[str]:
    chosen = list(start)
    best = bt.evaluate(_fit(y23, chosen, target), y24, target)["rho"]
    while True:
        trials = [(bt.evaluate(_fit(y23, chosen + [f], target), y24, target)["rho"], f) for f in cands if f not in chosen]
        if not trials:
            break
        v, f = max(trials)
        if v < best + 0.005:
            break
        chosen.append(f)
        best = v
    return chosen


def pick_gain(base, model, waiver: list[dict]) -> dict:
    """Streaming value: next-game points of the best waiver-tier pick each week, by model vs by
    points so far, against the average waiver option."""
    by = defaultdict(list)
    for r in waiver:
        if r.get("y_next") is not None:
            by[(r["season"], r["week"])].append(r)
    picks = {"model": [], "base": [], "avg": []}
    for sl in by.values():
        if len(sl) < 3:
            continue
        picks["model"].append(max(sl, key=model.predict)["y_next"])
        picks["base"].append(max(sl, key=base.predict)["y_next"])
        picks["avg"].append(fmean(r["y_next"] for r in sl))
    return {k: fmean(v) for k, v in picks.items()} | {"weeks": len(picks["model"])}


def run(pos: str, rows: list[dict], feats: list[str]) -> dict:
    y23 = [r for r in rows if r["season"] == 2023]
    y24 = [r for r in rows if r["season"] == 2024]
    train = y23 + y24
    test = [r for r in rows if r["season"] in TEST]
    waiver = [r for r in test if r["waiver_tier"]]
    out = {"n_test": len(test), "n_waiver": len(waiver), "targets": {}}
    for target in ("y_next", "y_ppg"):
        base = _fit(train, ["ppg"], target)
        single = {}
        for f in feats:
            m_alone, m_with = _fit(train, [f], target), _fit(train, ["ppg", f], target)
            single[f] = {"alone": bt.evaluate(m_alone, test, target)["rho"], "with_ppg": bt.evaluate(m_with, test, target)["rho"]}
        chosen = forward_select(y23, y24, feats, target)
        model = _fit(train, chosen, target)
        b_all, m_all = bt.evaluate(base, test, target)["rho"], bt.evaluate(model, test, target)["rho"]
        ci = bt.boot_delta_rho(base, model, test, target)
        b_w, m_w = bt.evaluate(base, waiver, target)["rho"], bt.evaluate(model, waiver, target)["rho"]
        ci_w = bt.boot_delta_rho(base, model, waiver, target)
        by_season = {s: [bt.evaluate(base, [r for r in test if r["season"] == s], target)["rho"],
                         bt.evaluate(model, [r for r in test if r["season"] == s], target)["rho"]] for s in TEST}
        out["targets"][target] = {
            "base": b_all, "model": m_all, "ci": ci, "base_waiver": b_w, "model_waiver": m_w, "ci_waiver": ci_w,
            "chosen": chosen, "coefs": dict(zip(model.feats, model.coefs[1:])), "single": single, "by_season": by_season,
            "pass": (m_all - b_all >= PASS_RHO) and ci[0] > 0, "model_dict": model.to_dict(),
        }
        if target == "y_next":
            out["targets"][target]["pick"] = pick_gain(base, model, waiver)
    return out


def check_scoring() -> dict:
    from nflverse.score import check_special_against_cbs

    r = check_special_against_cbs(load("pbp", 2026), load("stats_team_week", 2026), load("games"), load("players"), 2026, [1, 2, 3])
    print(f"nflverse vs CBS, 2026 weeks 1–3: K {r['K']['exact']}/{r['K']['n']} exact; DST {r['DST']['pa']['exact']}/{r['DST']['pa']['n']} exact"
          f" ({len(r['unmatched'])} unmatched)")
    return {"K": {k: v for k, v in r["K"].items() if k != "mismatches"},
            "DST": {k: v for k, v in r["DST"]["pa"].items() if k != "mismatches"}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check-scoring", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    scoring = check_scoring()
    if args.check_scoring:
        return 0
    schedule = load("games")
    results = {"scoring_check": scoring, "labels": LABELS, "config": {"fit": FIT, "test": TEST, "pass_rho": PASS_RHO}}
    for pos, builder, feats in (("K", kicker_rows, K_FEATURES), ("DST", dst_rows, DST_FEATURES)):
        by_season = {s: builder(s, schedule) for s in SEASONS}
        rows = [r for s in SEASONS for r in by_season[s]]
        res = run(pos, rows, feats)
        res["mean_ppg"] = fmean(r["ppg"] for r in rows if r["week"] == 16)
        results[pos] = res
        for target, t in res["targets"].items():
            lab = "next game" if target == "y_next" else "next 6 wks"
            print(f"\n{pos} {lab}: pts so far ρ {t['base']:.3f} -> model {t['model']:.3f} (CI {t['ci'][0]:+.3f} to {t['ci'][1]:+.3f})"
                  f" | waiver {t['base_waiver']:.3f} -> {t['model_waiver']:.3f} -> {'PASS' if t['pass'] else 'no'}")
            print(f"  picked: {' + '.join(LABELS[f] for f in t['chosen'])}")
            if "pick" in t:
                pk = t["pick"]
                print(f"  best available each week: by model {pk['model']:.2f} pts · by pts so far {pk['base']:.2f} · average option {pk['avg']:.2f} ({pk['weeks']} weeks)")
            print("  single: " + " · ".join(f"{LABELS[f]} {v['alone']:.3f}" for f, v in sorted(t["single"].items(), key=lambda kv: -kv[1]["alone"])))
    if args.out:
        args.out.write_text(json.dumps(results, indent=1, default=list), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
