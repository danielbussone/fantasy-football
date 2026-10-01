"""Per-player touchdown-distance tendency, from actual CBS box scores.

CBS's own `Total` is exact GBFL scoring, so "how much of a game's score
came from TD *length*, not the flat 1-point base" is a subtraction, not a
guess: bonus = Total - yard_points - TD count. Shrunk toward the position
average by TD sample size (GBFL_RULES.md §5/§6 — the sim otherwise can't
tell a deep-threat dart from a possession/dink-and-dunk player apart), and
starting from a yards-per-catch/carry prior before there's a real in-season
TD sample to trust at all. Early season this is mostly the YPC/YPA prior;
it gains real weight as TDs accumulate.

This mixes a player's long-bucket TDs (passing/receiving, except TE) and
short-bucket TDs (rushing, TE receiving) into one bonus-per-TD figure
rather than tracking them separately — a deliberate simplification, since
CBS's box score total doesn't break a multi-TD game down by which score was
which length. Applied only to a player's own *primary* scoring TD type
(a QB's passing TDs, a skill player's receiving TDs), not rushing TDs.
"""
from __future__ import annotations

import csv
from pathlib import Path

from cbs_client import norm
from scoring.actuals import line_has_box, row_to_actuals
from scoring.rules import yard_points

ROOT = Path(__file__).resolve().parents[1]
SHRINK_TDS = 6.0  # weight = tds / (tds + SHRINK_TDS)
SKEW_CLAMP = (-0.4, 0.4)
YPC_SKEW_CLAMP = (-0.3, 0.3)


def _game_td_bonus(line: dict) -> tuple[float, int]:
    """(bonus points above the flat 1-per-TD base, TD count) for one
    actuals line. None/0 TDs or no CBS total on file -> (0.0, tds)."""
    pos = (line.get("pos") or "").upper()
    if pos == "QB":
        yards = float(line.get("pass_yds") or 0) + float(line.get("rush_yds") or 0)
    elif pos in ("RB", "WR", "TE"):
        yards = float(line.get("rush_yds") or 0) + float(line.get("rec_yds") or 0)
    else:
        return 0.0, 0
    n_tds = int(line.get("pass_td") or 0) + int(line.get("rush_td") or 0) + int(line.get("rec_td") or 0)
    total = line.get("cbs_total")
    if total is None or n_tds <= 0:
        return 0.0, n_tds
    bonus = float(total) - yard_points(pos, yards) - n_tds
    return bonus, n_tds


def player_td_bonus_table(paths: list[Path] | None = None) -> dict[str, dict]:
    """{norm(player): {"pos": .., "tds": n, "bonus": sum}} pooled across
    every cbs_stats_week*.csv with a real box score."""
    from projections.matchups import week_stats_files

    paths = paths if paths is not None else week_stats_files()
    out: dict[str, dict] = {}
    for path in paths:
        if not path.exists():
            continue
        for row in csv.DictReader(path.open(encoding="utf-8")):
            pos = (row.get("pos") or "").upper()
            if pos not in ("QB", "RB", "WR", "TE"):
                continue
            line = row_to_actuals(row)
            if not line_has_box(line):
                continue
            bonus, n_tds = _game_td_bonus(line)
            if n_tds <= 0:
                continue
            key = norm(row.get("player") or "")
            if not key:
                continue
            entry = out.setdefault(key, {"pos": pos, "tds": 0, "bonus": 0.0})
            entry["tds"] += n_tds
            entry["bonus"] += bonus
    return out


def position_avg_bonus_per_td(table: dict[str, dict]) -> dict[str, float]:
    totals: dict[str, list[float]] = {}
    for entry in table.values():
        pos = entry["pos"]
        acc = totals.setdefault(pos, [0.0, 0])
        acc[0] += entry["bonus"]
        acc[1] += entry["tds"]
    return {pos: (b / n) for pos, (b, n) in totals.items() if n > 0}


def ypc_based_skew(pos: str, prior: dict) -> float:
    """A rough explosiveness prior from yards/catch or yards/carry, used
    before there's a real in-season TD sample: 0 at a "normal" efficiency
    (11 ypc receiving, 4.4 ypc rushing), positive for a bigger-play profile.
    """
    pos = (pos or "").upper()
    if pos == "RB":
        ypc = prior.get("rush_ypc")
        if not ypc:
            return 0.0
        lo, hi = YPC_SKEW_CLAMP
        return max(lo, min(hi, (float(ypc) - 4.4) / 10.0))
    ypc = prior.get("ypc")
    if not ypc:
        return 0.0
    lo, hi = YPC_SKEW_CLAMP
    return max(lo, min(hi, (float(ypc) - 11.0) / 15.0))


def explosiveness_skew(
    player: str,
    pos: str,
    prior: dict,
    table: dict[str, dict],
    pos_avgs: dict[str, float],
) -> float:
    """This player's own pull on their TD-distance draw: real in-season
    bonus-per-TD vs. the position average, shrunk toward a YPC/YPA-based
    prior by TD count (SHRINK_TDS games' worth of weight for a full-trust
    real sample), then clamped to the same range _pick_skewed expects.
    """
    prior_skew = ypc_based_skew(pos, prior)
    entry = table.get(norm(player or ""))
    if not entry or not entry.get("tds"):
        return prior_skew
    tds = entry["tds"]
    avg_bonus = entry["bonus"] / tds
    pos_avg = pos_avgs.get((pos or "").upper())
    if not pos_avg:
        return prior_skew
    sample_skew = max(SKEW_CLAMP[0], min(SKEW_CLAMP[1], (avg_bonus - pos_avg) / max(abs(pos_avg), 1.0)))
    weight = tds / (tds + SHRINK_TDS)
    blended = weight * sample_skew + (1 - weight) * prior_skew
    return max(SKEW_CLAMP[0], min(SKEW_CLAMP[1], blended))


def format_edges(players: list[dict], min_gap: int = 15, limit: int = 10) -> list[dict]:
    """Players where FantasyPros' weekly rank and this app's own simulated
    rank (by mean, within the same weekly list) disagree the most —
    GBFL_RULES.md §8's best remaining use for a standard-board comparison:
    not hand-correcting ranks, just showing where the market and the sim
    part ways.
    """
    by_list: dict[str, list[dict]] = {}
    for p in players:
        wl = p.get("weekly_list")
        wr = p.get("weekly_rank")
        if not wl or wr in (None, ""):
            continue
        try:
            int(wr)
        except (TypeError, ValueError):
            continue
        by_list.setdefault(wl, []).append(p)

    edges: list[dict] = []
    for wl, group in by_list.items():
        ranked = sorted(group, key=lambda p: -(float((p.get("proj") or {}).get("mean") or 0)))
        app_rank = {id(p): i + 1 for i, p in enumerate(ranked)}
        for p in group:
            fp_rank = int(p["weekly_rank"])
            gap = fp_rank - app_rank[id(p)]
            if abs(gap) < min_gap:
                continue
            edges.append(
                {
                    "player": p.get("player"),
                    "pos": p.get("pos"),
                    "weekly_list": wl,
                    "fp_rank": fp_rank,
                    "app_rank": app_rank[id(p)],
                    "gap": gap,
                    "note": "App ranks him much higher than FantasyPros" if gap > 0 else "FantasyPros ranks him much higher than the app",
                }
            )
    edges.sort(key=lambda e: -abs(e["gap"]))
    return edges[:limit]
