"""Points allowed by position and opponent pass rush, from actual CBS box scores.

`cbs_stats_week*.csv` are the same files `scoring/actuals.py` grades the
Report tab from — CBS's own `Total`/`Total_3` column is this league's exact
score, so "how many GBFL points has defense X allowed to WRs" is a sum, not
a distance-mix guess. Shrunk toward the league average by games played
(two games of DvP data is mostly noise — GBFL_RULES.md §7), then applied as
a capped multiplier on top of a player's usage prior, and (for pass rush)
as a skew on which end of the TD-distance mix the sim draws from.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from scoring.actuals import line_has_box, row_to_actuals, score_actual_line

ROOT = Path(__file__).resolve().parents[1]
POSITIONS = ("QB", "RB", "WR", "TE")
SHRINK_K = 4.0  # weight = games / (games + K); 2 games -> 1/3 trust, 6 -> 3/5
ADJUST_CLAMP = (0.85, 1.15)
PASS_RUSH_SKEW_CLAMP = (-0.4, 0.4)
SEASON_GAMES = 17


def _opp_team(raw: str) -> str:
    s = (raw or "").strip().upper()
    if not s or s in ("BYE", "-", "N/R", "---"):
        return ""
    return s.lstrip("@")


def week_stats_files(root: Path = ROOT) -> list[Path]:
    out = []
    for p in root.glob("cbs_stats_week*.csv"):
        m = re.search(r"week(\d+)", p.name)
        if m:
            out.append((int(m.group(1)), p))
    return [p for _, p in sorted(out)]


def points_allowed_table(paths: list[Path] | None = None) -> dict[str, dict]:
    """{TEAM: {"games": n, "QB": pts, "RB": pts, "WR": pts, "TE": pts}} —
    total GBFL points that team's defense has allowed to each position,
    plus how many of its games have an actual box score on file.
    """
    paths = paths if paths is not None else week_stats_files()
    allowed: dict[str, dict[str, float]] = {}
    games_seen: dict[str, set[int]] = {}
    for path in paths:
        if not path.exists():
            continue
        m = re.search(r"week(\d+)", path.name)
        week = int(m.group(1)) if m else 0
        for row in csv.DictReader(path.open(encoding="utf-8")):
            pos = (row.get("pos") or "").upper()
            if pos not in POSITIONS:
                continue
            opp = _opp_team(row.get("Opp") or "")
            if not opp:
                continue
            line = row_to_actuals(row)
            if not line_has_box(line):
                continue
            scored = score_actual_line(line.get("pos") or pos, line)
            allowed.setdefault(opp, {p: 0.0 for p in POSITIONS})[pos] += scored["pts"]
            games_seen.setdefault(opp, set()).add(week)
    return {team: {**pts, "games": len(games_seen.get(team, set()))} for team, pts in allowed.items()}


def league_averages(table: dict[str, dict]) -> dict[str, float]:
    """Pooled per-game average allowed at each position, across all teams
    with at least one game on file — the shrinkage target."""
    totals = {p: 0.0 for p in POSITIONS}
    games = 0
    for entry in table.values():
        g = entry.get("games") or 0
        if g <= 0:
            continue
        games += g
        for p in POSITIONS:
            totals[p] += entry.get(p, 0.0)
    if games <= 0:
        return {p: 0.0 for p in POSITIONS}
    return {p: totals[p] / games for p in POSITIONS}


def matchup_ratio(team: str, pos: str, table: dict[str, dict], avgs: dict[str, float]) -> float:
    """This team's shrunk, capped points-allowed ratio at `pos` vs. league
    average — 1.0 means "no matchup edge either way" (unknown team, no
    games yet, or the position doesn't apply). Feed straight into a usage
    prior as a multiplier.
    """
    pos = (pos or "").upper()
    league_avg = avgs.get(pos, 0.0)
    entry = table.get((team or "").upper())
    if not entry or league_avg <= 0:
        return 1.0
    games = entry.get("games") or 0
    if games <= 0:
        return 1.0
    raw_rate = entry.get(pos, 0.0) / games
    weight = games / (games + SHRINK_K)
    shrunk = weight * raw_rate + (1 - weight) * league_avg
    ratio = shrunk / league_avg
    return max(ADJUST_CLAMP[0], min(ADJUST_CLAMP[1], ratio))


def apply_matchup(prior: dict, opp_team: str, pos: str, table: dict[str, dict], avgs: dict[str, float]) -> dict:
    """Scale a usage prior by the opponent's shrunk points-allowed ratio at
    this position. A no-op (ratio 1.0) for an unknown/gameless opponent.
    """
    ratio = matchup_ratio(opp_team, pos, table, avgs)
    if ratio == 1.0:
        return prior
    pos = (pos or "").upper()
    out = dict(prior)
    yard_ratio = ratio**0.5
    for k in ("pass_td_rate", "rush_td_rate", "rec_td_rate"):
        if out.get(k) is not None:
            out[k] = float(out[k]) * ratio
    for k in ("scrim_ypg", "qb_ypg", "rush_ypg"):
        if out.get(k) is not None:
            out[k] = float(out[k]) * yard_ratio
    out["matchup_ratio"] = round(ratio, 3)
    return out


def sack_rates(dst_history_path: Path | None = None, week_files: list[Path] | None = None) -> dict[str, float]:
    """Sacks/game per team, blending 2025 dst_history.csv (a full-season
    prior) with this season's actual defensive box scores — the same
    "history + current games, weighted by sample" pattern the rest of the
    app's priors use, not a hard cutover to noisy early-season data.
    """
    hist: dict[str, float] = {}
    dst_history_path = dst_history_path or (ROOT / "dst_history.csv")
    if dst_history_path.exists():
        for r in csv.DictReader(dst_history_path.open(encoding="utf-8")):
            if int(r.get("season") or 0) != 2025:
                continue
            team = (r.get("team") or "").upper()
            try:
                hist[team] = float(r["sack"]) / SEASON_GAMES
            except (KeyError, ValueError):
                continue

    season_sacks: dict[str, float] = {}
    season_games: dict[str, set[int]] = {}
    for path in week_files if week_files is not None else week_stats_files():
        if not path.exists():
            continue
        m = re.search(r"week(\d+)", path.name)
        week = int(m.group(1)) if m else 0
        for row in csv.DictReader(path.open(encoding="utf-8")):
            if (row.get("pos") or "").upper() != "DST":
                continue
            team = (row.get("team") or "").upper()
            line = row_to_actuals(row)
            if not line_has_box(line):
                continue
            season_sacks[team] = season_sacks.get(team, 0.0) + float(line.get("sacks") or 0)
            season_games.setdefault(team, set()).add(week)

    out: dict[str, float] = {}
    teams = set(hist) | set(season_sacks)
    for team in teams:
        prior_rate = hist.get(team)
        g = len(season_games.get(team) or ())
        season_rate = (season_sacks.get(team, 0.0) / g) if g else None
        if season_rate is None:
            out[team] = prior_rate if prior_rate is not None else 0.0
            continue
        if prior_rate is None:
            out[team] = season_rate
            continue
        # Same games/(games+K) shrink as the matchup table — a couple of
        # real games earns real weight, but doesn't overwrite the prior.
        w = g / (g + SHRINK_K)
        out[team] = w * season_rate + (1 - w) * prior_rate
    return out


def pass_rush_skew(team: str, rates: dict[str, float]) -> float:
    """-1..1-ish, clamped: negative means a stronger-than-average pass rush
    (sim should draw shorter TD lengths against it), positive a weaker one.
    0 for an unknown team.
    """
    rate = rates.get((team or "").upper())
    if not rate:
        return 0.0
    vals = [v for v in rates.values() if v]
    if not vals:
        return 0.0
    league_avg = sum(vals) / len(vals)
    if league_avg <= 0:
        return 0.0
    delta = (rate / league_avg) - 1.0
    skew = -delta  # stronger pass rush (rate > avg) -> negative skew
    return max(PASS_RUSH_SKEW_CLAMP[0], min(PASS_RUSH_SKEW_CLAMP[1], skew))
