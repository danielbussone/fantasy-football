"""Week-N Monte Carlo. TD distance is sampled, not assumed short."""
from __future__ import annotations

import csv
import math
import random
from pathlib import Path
from typing import Any

from scoring.rules import (
    Game,
    extra_point_points,
    fg_points,
    passing_td_points,
    receiving_td_points,
    rushing_td_points,
    score_game,
    yard_points,
)

ROOT = Path(__file__).resolve().parents[1]
PERCENTILES = (10, 25, 50, 75, 90)

# Empirical-ish distance mixes (yards). Long tail is why P90 >> P50 here.
REC_TD_DIST = [5, 8, 12, 18, 22, 28, 35, 42, 48, 55, 62, 75]
RUSH_TD_DIST = [1, 2, 3, 5, 8, 12, 18, 25, 35, 45, 60]
PASS_TD_DIST = [8, 12, 18, 25, 32, 40, 48, 58, 70]
FG_DIST = [28, 33, 38, 42, 47, 52, 55, 61]


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _sample_yards(mean: float, cv: float, rng: random.Random) -> float:
    mean = max(0.0, mean)
    if mean <= 1:
        return 0.0 if rng.random() > mean else max(0.0, rng.gauss(mean, 3))
    sd = max(8.0, mean * cv)
    # Gamma via mean/var
    k = (mean / sd) ** 2
    theta = sd**2 / mean
    try:
        return max(0.0, rng.gammavariate(max(k, 0.3), theta))
    except ValueError:
        return max(0.0, rng.gauss(mean, sd))


def _n_tds(rate: float, rng: random.Random) -> int:
    # Poisson
    L = math.exp(-max(0.0, rate))
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return max(0, k - 1)


def _pick(seq: list, rng: random.Random) -> float:
    return float(seq[rng.randrange(len(seq))])


def simulate_detail(prior: dict[str, Any], rng: random.Random) -> tuple[float, dict[str, float]]:
    pos = (prior.get("pos") or "WR").upper()
    zero = {
        "pass_yds": 0.0,
        "rush_yds": 0.0,
        "rec_yds": 0.0,
        "pass_td": 0.0,
        "rush_td": 0.0,
        "rec_td": 0.0,
        "fg": 0.0,
        "xp": 0.0,
        "sacks": 0.0,
        "pa": 0.0,
    }
    if pos == "K":
        fg_n = _n_tds(prior.get("fg_rate", 1.8), rng)
        xp = max(0, int(round(rng.gauss(prior.get("xp_mean", 2.2), 1.0))))
        fgs = [_pick(FG_DIST, rng) for _ in range(fg_n)]
        if prior.get("long_kicker"):
            fgs = [max(y, 50) if rng.random() < 0.35 else y for y in fgs]
        pts = score_game(Game(pos="K", fg_yards=fgs, xp=xp))
        return pts, {**zero, "fg": float(fg_n), "xp": float(xp)}
    if pos == "DST":
        pa = int(_clip(rng.gauss(prior.get("pa_mean", 21), 8), 0, 45))
        sacks = max(0, rng.gauss(prior.get("sack_mean", 2.4), 1.4))
        ints = max(0, rng.gauss(prior.get("int_mean", 0.8), 0.7))
        fum = max(0, rng.gauss(0.5, 0.5))
        n_td = 1 if rng.random() < prior.get("def_td_p", 0.12) else 0
        tds = [_pick([20, 35, 55, 80], rng) for _ in range(n_td)]
        sty = 1 if rng.random() < 0.04 else 0
        pts = score_game(
            Game(
                pos="DST",
                sacks=sacks,
                ints=ints,
                fumbles_recovered=fum,
                safeties=sty,
                points_against=pa,
                def_td_yards=tds,
            )
        )
        return pts, {**zero, "sacks": sacks, "pa": float(pa), "def_td": float(n_td)}
    if pos == "QB":
        yds = _sample_yards(prior.get("qb_ypg", 250), 0.28, rng)
        rush = _sample_yards(prior.get("rush_ypg", 12), 0.8, rng)
        ptd = _n_tds(prior.get("pass_td_rate", 1.4), rng)
        rtd = _n_tds(prior.get("rush_td_rate", 0.25), rng)
        pass_yds = max(0, yds - rush * 0.1)
        pts = score_game(
            Game(
                pos="QB",
                pass_yds=pass_yds,
                rush_yds=rush,
                pass_td_yards=[_pick(PASS_TD_DIST, rng) for _ in range(ptd)],
                rush_td_yards=[_pick(RUSH_TD_DIST, rng) for _ in range(rtd)],
            )
        )
        return pts, {**zero, "pass_yds": pass_yds, "rush_yds": rush, "pass_td": float(ptd), "rush_td": float(rtd)}
    yds = _sample_yards(prior.get("scrim_ypg", 55), prior.get("cv", 0.45), rng)
    rec_share = prior.get("rec_share", 0.5 if pos != "RB" else 0.2)
    rec_yds = yds * rec_share
    rush_yds = yds - rec_yds
    rtd = _n_tds(prior.get("rush_td_rate", 0.3 if pos == "RB" else 0.05), rng)
    rec_td = _n_tds(prior.get("rec_td_rate", 0.35 if pos != "RB" else 0.15), rng)
    rec_mix = REC_TD_DIST
    if prior.get("ypc", 11) >= 14:
        rec_mix = REC_TD_DIST[4:]
    pts = score_game(
        Game(
            pos=pos,
            rush_yds=rush_yds,
            rec_yds=rec_yds,
            rush_td_yards=[_pick(RUSH_TD_DIST, rng) for _ in range(rtd)],
            rec_td_yards=[_pick(rec_mix, rng) for _ in range(rec_td)],
        )
    )
    return pts, {**zero, "rush_yds": rush_yds, "rec_yds": rec_yds, "rush_td": float(rtd), "rec_td": float(rec_td)}


def simulate_game(prior: dict[str, Any], rng: random.Random) -> float:
    return simulate_detail(prior, rng)[0]


def percentile_dict(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {f"p{p}": 0.0 for p in PERCENTILES} | {"mean": 0.0}
    s = sorted(samples)
    n = len(s)

    def pct(p: int) -> float:
        i = min(n - 1, max(0, int(round((p / 100) * (n - 1)))))
        return round(s[i], 2)

    return {f"p{p}": pct(p) for p in PERCENTILES} | {"mean": round(sum(s) / n, 2)}


def _stable_seed(player: str, seed: int) -> int:
    h = 2166136261
    for b in (player or "").encode("utf-8"):
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return seed + (h % 10_000)


def _mean_detail(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    keys = rows[0].keys()
    return {k: round(sum(r[k] for r in rows) / len(rows), 2) for k in keys}


def _yard_bucket_note(pos: str, yards: float) -> str:
    y = yards
    p = (pos or "").upper()
    if p == "QB":
        if y < 200:
            return "<200 = 0"
        if y >= 500:
            return "500+ = 7"
        lo = 200 + 50 * int((y - 200) // 50)
        return f"{lo}–{lo + 49} bucket"
    if p == "TE":
        if y < 40:
            return "<40 = 0"
        if y >= 220:
            return "220+ = 10"
        lo = 40 + 20 * int((y - 40) // 20)
        return f"{lo}–{lo + 19} bucket"
    if y < 70:
        return "<70 = 0"
    if y >= 250:
        return "250+ = 10"
    lo = 70 + 20 * int((y - 70) // 20)
    return f"{lo}–{lo + 19} bucket"


def explain_from_sim(pos: str, sim: dict[str, float]) -> dict[str, Any]:
    pos = (pos or "").upper()
    rows = []
    lines = []
    if pos == "QB":
        y = float(sim.get("pass_yds", 0) + sim.get("rush_yds", 0))
        yp = yard_points(pos, y)
        rows.append({"cat": "Pass+rush yards", "input": f"~{y:.0f}", "pts": yp, "note": _yard_bucket_note(pos, y)})
        avg_p = sum(passing_td_points(d) for d in PASS_TD_DIST) / len(PASS_TD_DIST)
        avg_r = sum(rushing_td_points(d) for d in RUSH_TD_DIST) / len(RUSH_TD_DIST)
        ptd, rtd = float(sim.get("pass_td", 0)), float(sim.get("rush_td", 0))
        rows.append({"cat": "Pass TDs", "input": f"~{ptd:.2f}", "pts": round(ptd * avg_p, 2), "note": "distance-banded"})
        rows.append({"cat": "Rush TDs", "input": f"~{rtd:.2f}", "pts": round(rtd * avg_r, 2), "note": "distance-banded"})
        lines.append(f"~{y:.0f} pass+rush yards → {_yard_bucket_note(pos, y)} = {yp:g} pts.")
        lines.append(f"~{ptd:.2f} pass TDs and ~{rtd:.2f} rush TDs with a sampled distance mix.")
    elif pos in {"RB", "WR", "TE"}:
        y = float(sim.get("rush_yds", 0) + sim.get("rec_yds", 0))
        yp = yard_points(pos, y)
        rows.append({"cat": "Scrimmage yards", "input": f"~{y:.0f} ({sim.get('rush_yds', 0):.0f} ru / {sim.get('rec_yds', 0):.0f} rec)", "pts": yp, "note": _yard_bucket_note(pos, y)})
        avg_rec = sum(receiving_td_points(d, pos) for d in REC_TD_DIST) / len(REC_TD_DIST)
        avg_ru = sum(rushing_td_points(d) for d in RUSH_TD_DIST) / len(RUSH_TD_DIST)
        rec_td, ru_td = float(sim.get("rec_td", 0)), float(sim.get("rush_td", 0))
        rows.append({"cat": "Rec TDs", "input": f"~{rec_td:.2f}", "pts": round(rec_td * avg_rec, 2), "note": "46-yd rec TD = 4 for WR/RB"})
        rows.append({"cat": "Rush TDs", "input": f"~{ru_td:.2f}", "pts": round(ru_td * avg_ru, 2), "note": "distance-banded"})
        lines.append(f"~{y:.0f} scrimmage yards → {_yard_bucket_note(pos, y)} = {yp:g} pts.")
        lines.append(f"~{rec_td:.2f} rec TDs (distance mix; a 46-yard catch is 4) and ~{ru_td:.2f} rush TDs.")
    elif pos == "K":
        fg_n, xp = float(sim.get("fg", 0)), float(sim.get("xp", 0))
        avg_fg = sum(fg_points(d) for d in FG_DIST) / len(FG_DIST)
        rows.append({"cat": "FG", "input": f"~{fg_n:.2f}", "pts": round(fg_n * avg_fg, 2), "note": "1 / 2 / 3 / 3.5 by distance"})
        rows.append({"cat": "XP", "input": f"~{xp:.1f}", "pts": extra_point_points(int(round(xp))), "note": "0.5 each"})
        lines.append(f"~{fg_n:.2f} FG (distance mix) and ~{xp:.1f} XP at 0.5 each.")
    else:
        rows.append({"cat": "PA / sacks / TDs", "input": f"PA ~{sim.get('pa', 0):.0f}, sacks ~{sim.get('sacks', 0):.1f}", "pts": None, "note": "PA buckets + 0.5 turnovers"})
        lines.append("DST: points-against buckets, 0.5 per sack/INT/FR, TDs are the lottery tail.")
    tot = round(sum(r["pts"] or 0 for r in rows), 2)
    return {"rows": rows, "lines": lines, "approx_pts": tot}


def usage_block(prior: dict[str, Any]) -> dict[str, Any]:
    src = prior.get("source") or "season history"
    if prior.get("has_3g"):
        src = "3g" if src == "3g" else "3g+history"
    elif src == "role-prior" or src == "role-prior+board":
        src = "role-prior"
    else:
        src = "season history"
    return {
        "source": src,
        "pass_att": _r(prior.get("pass_att_pg")),
        "carries": _r(prior.get("carries_pg")),
        "targets": _r(prior.get("targets_pg")),
        "receptions": _r(prior.get("rec_pg")),
        "fg_att": _r(prior.get("fg_rate")),
        "has_3g": bool(prior.get("has_3g")),
        "season_carries": _r(prior.get("season_carries_pg")),
        "season_targets": _r(prior.get("season_targets_pg")),
        "g3_carries": _r(prior.get("g3_carries_pg")),
        "g3_targets": _r(prior.get("g3_targets_pg")),
        "ypc": _r(prior.get("rush_ypc") or prior.get("ypc")),
        "ypt": _r(prior.get("ypt")),
    }


def _r(v) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def breakout_marker(prior: dict[str, Any], depth_rank: int = 1, pos: str = "") -> dict[str, Any] | None:
    pos = (pos or prior.get("pos") or "").upper()
    if pos not in {"RB", "WR"}:
        return None
    role = f"{pos}{depth_rank}" if depth_rank else pos
    src = prior.get("source") or ""
    if not prior.get("has_3g"):
        if "role-prior" in src or int(depth_rank or 1) >= 2:
            return {
                "flag": "needs-3g",
                "why": f"watch: opportunity — {role}; role-prior, needs 3g pull (no usable last-3-games usage yet)",
            }
        return None
    g3_c = float(prior.get("g3_carries_pg") or 0)
    g3_t = float(prior.get("g3_targets_pg") or 0)
    s_c = float(prior.get("season_carries_pg") or 0)
    s_t = float(prior.get("season_targets_pg") or 0)
    ypc = prior.get("rush_ypc")
    ypt = prior.get("ypt")
    up_c = g3_c >= 1 and (s_c <= 0.5 or g3_c >= s_c * 1.3)
    up_t = g3_t >= 1 and (s_t <= 0.5 or g3_t >= s_t * 1.3)
    eff = (ypc is not None and float(ypc) >= 4.5) or (ypt is not None and float(ypt) >= 7)
    bits = []
    if g3_c or s_c:
        bits.append(f"3g carries {g3_c:.1f} vs season {s_c:.1f}")
    if g3_t or s_t:
        bits.append(f"3g targets {g3_t:.1f} vs season {s_t:.1f}")
    if ypc:
        bits.append(f"{float(ypc):.1f} YPC")
    if ypt:
        bits.append(f"{float(ypt):.1f} YPT")
    bits.append(f"depth {role}")
    why = "; ".join(bits)
    if (up_c or up_t) and (eff or int(depth_rank or 1) >= 2):
        return {"flag": "breakout", "why": why}
    if up_c or up_t:
        return {"flag": "watch", "why": why}
    if int(depth_rank or 1) >= 2:
        return {"flag": "watch", "why": why}
    return None


def project_player(prior: dict[str, Any], n: int = 2500, seed: int = 1) -> dict[str, Any]:
    rng = random.Random(_stable_seed(str(prior.get("player") or ""), seed))
    samples = []
    details = []
    for _ in range(n):
        pts, det = simulate_detail(prior, rng)
        samples.append(pts)
        details.append(det)
    out = percentile_dict(samples)
    sim = _mean_detail(details)
    pos = (prior.get("pos") or "WR").upper()
    out["sim"] = sim
    out["usage"] = usage_block(prior)
    out["explain"] = explain_from_sim(pos, sim)
    out["source"] = (prior.get("source") or "season history")
    return out


def load_history_priors() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for season in (2023, 2024, 2025):
        path = ROOT / f"history_{season}.csv"
        if not path.exists():
            continue
        for r in csv.DictReader(path.open(encoding="utf-8")):
            total = float(r["total"])
            avg = float(r["avg"] or 0)
            games = max(1, round(total / avg) if avg else 1)
            pos = r["pos"]
            rec = int(r["rec"])
            rec_yds = int(r["rec_yds"])
            rush = int(r["rush_yds"])
            rec_td = int(r["rec_td"])
            rush_td = int(r["rush_td"])
            pass_td = int(r["pass_td"])
            pass_yds = int(r["pass_yds"])
            carries_est = rush / 4.4 / games if rush else 0.0
            rec_pg = rec / games
            tar_est = rec_pg / 0.65 if rec_pg else 0.0
            prior = {
                "player": r["player"],
                "pos": pos,
                "scrim_ypg": (rush + rec_yds) / games,
                "qb_ypg": (pass_yds + rush) / games,
                "rush_ypg": rush / games,
                "rec_share": (rec_yds / (rush + rec_yds)) if (rush + rec_yds) else 0.5,
                "ypc": rec_yds / rec if rec else 11.0,
                "rush_ypc": 4.4,
                "ypt": rec_yds / max(rec / 0.65, 1) if rec else None,
                "cv": 0.55 if rec and rec_yds / max(rec, 1) >= 14 else 0.4,
                "pass_td_rate": pass_td / games,
                "rush_td_rate": rush_td / games,
                "rec_td_rate": rec_td / games,
                "carries_pg": carries_est,
                "targets_pg": tar_est,
                "rec_pg": rec_pg,
                "season_carries_pg": carries_est,
                "season_targets_pg": tar_est,
                "source": "season history",
            }
            out[r["player"].lower()] = prior
    return out


def load_kicker_priors() -> dict[str, dict]:
    out = {}
    path = ROOT / "kicker_2025.csv"
    if not path.exists():
        return out
    for r in csv.DictReader(path.open(encoding="utf-8")):
        fg = int(r["fg"])
        xp = int(r["xp"])
        games = 17
        a50 = int(r.get("a_50") or 0)
        out[r["player"].lower()] = {
            "player": r["player"],
            "pos": "K",
            "fg_rate": fg / games,
            "xp_mean": xp / games,
            "long_kicker": a50 >= 10,
        }
    return out


def load_dst_priors() -> dict[str, dict]:
    out = {}
    path = ROOT / "dst_history.csv"
    if not path.exists():
        return out
    for r in csv.DictReader(path.open(encoding="utf-8")):
        if int(r["season"]) != 2025:
            continue
        games = 17
        name = r["team"]
        out[name.lower()] = {
            "player": name,
            "pos": "DST",
            "sack_mean": float(r["sack"]) / games,
            "int_mean": float(r["int"]) / games,
            "pa_mean": float(r["pts_ag"]) / games,
            "def_td_p": min(0.4, float(r["td"]) / games),
        }
    return out


def default_prior(player: str, pos: str) -> dict[str, Any]:
    pos = pos.upper()
    base = {"player": player, "pos": pos}
    if pos == "QB":
        return {**base, "qb_ypg": 230, "rush_ypg": 10, "pass_td_rate": 1.2, "rush_td_rate": 0.15}
    if pos == "RB":
        return {**base, "scrim_ypg": 50, "rec_share": 0.2, "rush_td_rate": 0.3, "rec_td_rate": 0.1, "cv": 0.5}
    if pos == "WR":
        return {**base, "scrim_ypg": 55, "rec_share": 0.95, "rec_td_rate": 0.3, "cv": 0.5, "ypc": 12}
    if pos == "TE":
        return {**base, "scrim_ypg": 45, "rec_share": 0.95, "rec_td_rate": 0.25, "cv": 0.45, "ypc": 11}
    if pos == "K":
        return {**base, "fg_rate": 1.7, "xp_mean": 2.0, "long_kicker": False}
    return {**base, "sack_mean": 2.2, "int_mean": 0.7, "pa_mean": 22, "def_td_p": 0.1}


def _num(row: dict, *keys: str) -> float | None:
    for k in keys:
        v = row.get(k)
        if v in (None, "", "-", "N/R", "—"):
            continue
        try:
            return float(str(v).replace(",", ""))
        except ValueError:
            continue
    return None


def row_to_3g_prior(row: dict) -> dict[str, Any]:
    """Turn one CBS last-3-games stats row into a usage prior (per game)."""
    pos = (row.get("pos") or "WR").upper()
    gp = _num(row, "GP", "G", "Games") or 3.0
    gp = max(1.0, gp)
    player = row.get("player") or ""
    base: dict[str, Any] = {"player": player, "pos": pos, "source": "3g"}
    if pos == "QB":
        pass_yds = _num(row, "Pass Yds", "Passing Yds", "Yds") or 0.0
        rush_yds = _num(row, "Rush Yds", "Rushing Yds", "Yds_2") or 0.0
        ptd = _num(row, "Pass TD", "PaTD", "TD") or 0.0
        rtd = _num(row, "Rush TD", "RuTD", "TD_2") or 0.0
        return {
            **base,
            "qb_ypg": (pass_yds + rush_yds) / gp,
            "rush_ypg": rush_yds / gp,
            "pass_td_rate": ptd / gp,
            "rush_td_rate": rtd / gp,
            "pass_att_pg": (_num(row, "ATT") or 0.0) / gp,
            "carries_pg": (_num(row, "Att") or 0.0) / gp,
            "has_3g": (pass_yds + rush_yds) > 20,
        }
    if pos == "K":
        return {
            **base,
            "fg_rate": (_num(row, "FG", "FGM") or 0.0) / gp,
            "xp_mean": (_num(row, "XP", "XPM") or 0.0) / gp,
            "long_kicker": False,
        }
    if pos == "DST":
        return {
            **base,
            "sack_mean": (_num(row, "SACK", "Sack", "Sacks") or 0.0) / gp,
            "int_mean": (_num(row, "Int", "INT") or 0.0) / gp,
            "pa_mean": _num(row, "Pts Ag", "PA", "Pts") or 22.0,
            "def_td_p": min(0.4, (_num(row, "TD", "DTD") or 0.0) / gp),
        }
    rec_yds = _num(row, "Rec Yds", "Receiving Yds", "Yds_2", "Yds") or 0.0
    rush_yds = _num(row, "Rush Yds", "Rushing Yds", "Yds") or 0.0
    if pos != "RB" and _num(row, "Yds_2") is None:
        # WR/TE tables usually list receiving Yds first.
        rec_yds = _num(row, "Yds") or rec_yds
        rush_yds = _num(row, "Yds_2") or 0.0
    rec = _num(row, "Rec", "Receptions") or 0.0
    rec_td = _num(row, "Rec TD", "ReTD", "TD_2", "TD") or 0.0
    rush_td = _num(row, "Rush TD", "RuTD") or 0.0
    att = _num(row, "Att") or 0.0
    tar = _num(row, "Tar") or 0.0
    pass_att = _num(row, "ATT") or 0.0
    scrim = rush_yds + rec_yds
    has = (att + tar + scrim) > 3
    return {
        **base,
        "scrim_ypg": scrim / gp,
        "rush_ypg": rush_yds / gp,
        "rec_share": (rec_yds / scrim) if scrim else (0.2 if pos == "RB" else 0.95),
        "ypc": (rec_yds / rec) if rec else 11.0,
        "rush_ypc": (rush_yds / att) if att else None,
        "ypt": (rec_yds / tar) if tar else None,
        "cv": 0.55 if rec and rec_yds / max(rec, 1) >= 14 else 0.4,
        "rush_td_rate": rush_td / gp,
        "rec_td_rate": rec_td / gp,
        "carries_pg": att / gp,
        "targets_pg": tar / gp,
        "rec_pg": rec / gp,
        "pass_att_pg": pass_att / gp,
        "g3_carries_pg": att / gp,
        "g3_targets_pg": tar / gp,
        "has_3g": has,
    }


def load_3g_priors() -> dict[str, dict]:
    path = ROOT / "cbs_stats_3g.csv"
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(path.open(encoding="utf-8")):
        name = (r.get("player") or "").lower()
        if name:
            out[name] = row_to_3g_prior(r)
    return out


def blend_espn(base: dict[str, Any], espn_row: dict | None, weight: float = 0.45) -> dict[str, Any]:
    """Delegate to projections.espn so assemble/tests can import from weekly."""
    from projections.espn import blend_espn as _blend

    return _blend(base, espn_row, weight=weight)


def blend_usage(base: dict[str, Any], g3: dict[str, Any] | None, depth_rank: int = 1) -> dict[str, Any]:
    """Mix season prior with last-3-games; down-weight backups."""
    out = dict(base)
    keys = (
        "scrim_ypg",
        "qb_ypg",
        "rush_ypg",
        "pass_td_rate",
        "rush_td_rate",
        "rec_td_rate",
        "fg_rate",
        "xp_mean",
        "sack_mean",
        "int_mean",
        "pa_mean",
        "def_td_p",
        "rec_share",
        "ypc",
        "cv",
    )
    if g3 and g3.get("has_3g"):
        w = 0.7
        for k in keys:
            if k in g3 and g3[k] is not None:
                if k in out and out[k] is not None:
                    out[k] = (1 - w) * float(out[k]) + w * float(g3[k])
                else:
                    out[k] = g3[k]
        out["source"] = "3g+history" if base.get("source") != "3g" else "3g"
        out["has_3g"] = True
        if g3.get("g3_carries_pg") is not None:
            out["g3_carries_pg"] = g3["g3_carries_pg"]
            out["carries_pg"] = g3.get("carries_pg", out.get("carries_pg"))
        if g3.get("g3_targets_pg") is not None:
            out["g3_targets_pg"] = g3["g3_targets_pg"]
            out["targets_pg"] = g3.get("targets_pg", out.get("targets_pg"))
        if g3.get("rush_ypc") is not None:
            out["rush_ypc"] = g3["rush_ypc"]
        if g3.get("ypt") is not None:
            out["ypt"] = g3["ypt"]
        if g3.get("pass_att_pg") is not None:
            out["pass_att_pg"] = g3["pass_att_pg"]
    else:
        out["has_3g"] = False
    if int(depth_rank or 1) >= 3:
        for k in ("scrim_ypg", "qb_ypg", "rush_ypg", "fg_rate"):
            if k in out and out[k] is not None:
                out[k] = float(out[k]) * 0.45
        out["role"] = "backup"
    return out


_HIST = None
_K = None
_D = None
_G3 = None


def priors_cached():
    global _HIST, _K, _D, _G3
    if _HIST is None:
        _HIST = load_history_priors()
        _K = load_kicker_priors()
        _D = load_dst_priors()
        _G3 = load_3g_priors()
    return _HIST, _K, _D, _G3


def prior_for(player: str, pos: str, team: str = "", depth_rank: int = 1) -> dict[str, Any]:
    hist, ks, ds, g3s = priors_cached()
    key = player.lower()
    base: dict[str, Any] | None = None
    if pos == "K" and key in ks:
        base = dict(ks[key])
    elif pos == "DST":
        d = ds.get(key) or ds.get((team or "").lower()) or ds.get(player.lower().replace(" dst", ""))
        if d:
            base = dict(d)
    if base is None and key in hist:
        base = dict(hist[key])
    if base is None:
        last = key.split()[-1]
        for k, v in hist.items():
            if k.endswith(last) and v.get("pos") == pos:
                base = dict(v)
                break
    if base is None:
        base = default_prior(player, pos)
        base["source"] = "role-prior"
    g3 = g3s.get(key)
    return blend_usage(base, g3, depth_rank=depth_rank)
