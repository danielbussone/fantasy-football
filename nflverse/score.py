"""Exact GBFL points for an nflverse player-week.

Yardage comes from nflverse's weekly player stats. TD distances come from
play-by-play, since yardage buckets plus distance-banded TDs are what this
format scores (scoring/rules.py). Scored through scoring.rules.score_game,
the same scorer everything else here uses.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from cbs_client import norm
from scoring.actuals import line_has_box, row_to_actuals
from scoring.rules import Game, score_game

ROOT = Path(__file__).resolve().parents[1]
SKILL = frozenset({"QB", "RB", "WR", "TE"})
_POS_ALIAS = {"FB": "RB", "HB": "RB"}


def norm_pos(pos: str | None) -> str:
    p = (pos or "").upper()
    return _POS_ALIAS.get(p, p)


def _f(v) -> float:
    try:
        return float(v) if v not in (None, "", "NA") else 0.0
    except ValueError:
        return 0.0


def _new_events() -> dict:
    return {"pass": [], "rush": [], "rec": [], "ret": []}


def td_events(pbp: list[dict]) -> dict[tuple[str, int], dict]:
    """{(gsis player_id, week): {"pass"|"rush"|"rec"|"ret": [td yards, ...]}}.

    A pass TD credits the passer and the scorer (td_player_id — the receiver,
    or whoever recovered a fumble in the end zone). Return TDs are kickoff/
    punt returns only; INT/fumble return TDs belong to the defense.
    """
    ev: dict[tuple[str, int], dict] = defaultdict(_new_events)
    for r in pbp:
        if r.get("touchdown") != "1" or r.get("two_point_attempt") == "1":
            continue
        wk = int(r["week"])
        yds = _f(r.get("yards_gained"))
        scorer = r.get("td_player_id") or ""
        if r.get("pass_touchdown") == "1":
            if r.get("passer_player_id"):
                ev[(r["passer_player_id"], wk)]["pass"].append(yds)
            if scorer:
                ev[(scorer, wk)]["rec"].append(yds)
        elif r.get("rush_touchdown") == "1":
            if scorer:
                ev[(scorer, wk)]["rush"].append(yds)
        elif r.get("return_touchdown") == "1" and r.get("play_type") in ("kickoff", "punt") and scorer:
            ev[(scorer, wk)]["ret"].append(_f(r.get("return_yards")) or yds)
    return ev


def two_pt(row: dict) -> int:
    return int(
        _f(row.get("passing_2pt_conversions"))
        + _f(row.get("rushing_2pt_conversions"))
        + _f(row.get("receiving_2pt_conversions"))
    )


def player_game(row: dict, events: dict | None, pos: str | None = None) -> Game:
    ev = events or _new_events()
    return Game(
        pos=norm_pos(pos or row.get("position")),
        pass_yds=_f(row.get("passing_yards")),
        rush_yds=_f(row.get("rushing_yards")),
        rec_yds=_f(row.get("receiving_yards")),
        pass_td_yards=list(ev["pass"]),
        rush_td_yards=list(ev["rush"]),
        rec_td_yards=list(ev["rec"]),
        two_pt=two_pt(row),
        return_td_yards=list(ev["ret"]),
    )


def score_player_week(row: dict, events: dict | None, pos: str | None = None) -> float:
    return score_game(player_game(row, events, pos))


def scored_weeks(weekly: list[dict], pbp: list[dict]) -> list[dict]:
    """Regular-season skill-position player-weeks, each with a `gbfl` field."""
    ev = td_events(pbp)
    out = []
    for r in weekly:
        if r.get("season_type") != "REG":
            continue
        pos = norm_pos(r.get("position"))
        if pos not in SKILL:
            continue
        wk = int(r["week"])
        out.append({**r, "pos": pos, "week_n": wk, "gbfl": score_player_week(r, ev.get((r["player_id"], wk)), pos)})
    return out


def check_against_cbs(weekly: list[dict], pbp: list[dict], weeks: list[int]) -> dict:
    """Score nflverse lines under CBS's own positions and compare with CBS's exact
    `Total` (cbs_stats_week{N}.csv). Returns match stats plus the mismatches."""
    ev = td_events(pbp)
    by_name: dict[tuple[str, int], dict] = {}
    for r in weekly:
        if r.get("season_type") == "REG":
            by_name[(norm(r.get("player_display_name") or ""), int(r["week"]))] = r
    rows = []
    unmatched = []
    for wk in weeks:
        path = ROOT / f"cbs_stats_week{wk}.csv"
        if not path.exists():
            continue
        for cbs in csv.DictReader(path.open(encoding="utf-8")):
            line = row_to_actuals(cbs)
            pos = line["pos"]
            if pos not in SKILL or line.get("cbs_total") is None or not line_has_box(line):
                continue
            nfl = by_name.get((norm(cbs.get("player") or ""), wk))
            if nfl is None:
                unmatched.append({"player": cbs.get("player"), "week": wk, "pos": pos, "cbs": line["cbs_total"]})
                continue
            ours = score_player_week(nfl, ev.get((nfl["player_id"], wk)), pos)
            rows.append({
                "player": cbs.get("player"), "week": wk, "pos": pos,
                "cbs": float(line["cbs_total"]), "ours": ours,
                "nfl_yds": _f(nfl.get("passing_yards")) + _f(nfl.get("rushing_yards")) + _f(nfl.get("receiving_yards")),
                "cbs_yds": float(line.get("pass_yds") or 0) + float(line.get("rush_yds") or 0) + float(line.get("rec_yds") or 0),
                "td": ev.get((nfl["player_id"], wk)),
            })
    exact = [r for r in rows if abs(r["ours"] - r["cbs"]) < 1e-6]
    return {
        "n": len(rows),
        "exact": len(exact),
        "rate": (len(exact) / len(rows)) if rows else 0.0,
        "mismatches": [r for r in rows if abs(r["ours"] - r["cbs"]) >= 1e-6],
        "unmatched": unmatched,
    }


# ---------- Kickers and defenses ----------

CBS_TEAM = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}  # CBS abbreviation -> nflverse


def kicker_games(pbp: list[dict]) -> dict[tuple[str, int], dict]:
    """{(kicker gsis id, week): {"team", "fg_yards": [...made...], "fg_att", "fg_att_50", "xp", "xp_att"}}."""
    out: dict[tuple[str, int], dict] = {}
    for r in pbp:
        kid = r.get("kicker_player_id")
        if not kid or r.get("play_type") not in ("field_goal", "extra_point"):
            continue
        k = out.setdefault((kid, int(r["week"])), {"team": r.get("posteam") or "", "fg_yards": [], "fg_att": 0,
                                                    "fg_att_50": 0, "xp": 0, "xp_att": 0})
        if r["play_type"] == "field_goal":
            dist = _f(r.get("kick_distance"))
            k["fg_att"] += 1
            k["fg_att_50"] += 1 if dist >= 50 else 0
            if r.get("field_goal_result") == "made":
                k["fg_yards"].append(dist)
        else:
            k["xp_att"] += 1
            k["xp"] += 1 if r.get("extra_point_result") == "good" else 0
    return out


def score_kicker(k: dict) -> float:
    return score_game(Game(pos="K", fg_yards=list(k["fg_yards"]), xp=int(k["xp"])))


def dst_games(pbp: list[dict], team_week: list[dict], schedule: list[dict], season: int) -> dict[tuple[str, int], dict]:
    """{(team, week): defense/special-teams line} for one season.

    Sacks are counted from play-by-play; INTs, opponent fumbles recovered and safeties
    come from nflverse's weekly team stats. Return-TD distances come from play-by-play: any return TD credited
    to the team (INT, fumble, punt, kickoff, blocked kick). Points against is the
    opponent's final score, and also with the opponent's own return TDs removed,
    since leagues differ on that (the CBS check picks one).
    """
    tw = {(r["team"], int(r["week"])): r for r in team_week if r.get("season_type") == "REG"}
    tds: dict[tuple[str, int], list[float]] = defaultdict(list)
    sacks: dict[tuple[str, int], float] = defaultdict(float)
    for r in pbp:
        if r.get("sack") == "1" and r.get("defteam"):
            sacks[(r["defteam"], int(r["week"]))] += 1
    for r in pbp:
        if r.get("return_touchdown") != "1" or not r.get("td_team"):
            continue
        yds = _f(r.get("return_yards")) or _f(r.get("fumble_recovery_1_yards")) or abs(_f(r.get("yards_gained")))
        tds[(r["td_team"], int(r["week"]))].append(yds)
    out = {}
    for g in schedule:
        if str(g.get("season")) != str(season) or g.get("game_type") != "REG" or g.get("home_score") in (None, "", "NA"):
            continue
        wk = int(g["week"])
        for team, opp, opp_pts in ((g["home_team"], g["away_team"], g["away_score"]),
                                   (g["away_team"], g["home_team"], g["home_score"])):
            t = tw.get((team, wk)) or {}
            opp_ret = tds.get((opp, wk), [])
            out[(team, wk)] = {
                "team": team, "opp": opp, "week": wk,
                # Play-by-play sack count: the weekly team stat drops team/unassigned sacks.
                "sacks": sacks.get((team, wk), _f(t.get("def_sacks"))), "ints": _f(t.get("def_interceptions")),
                "fr": _f(t.get("fumble_recovery_opp")), "safeties": _f(t.get("def_safeties")),
                "def_td_yards": list(tds.get((team, wk), [])),
                "pa": int(_f(opp_pts)),
                "pa_no_ret": int(_f(opp_pts)) - 6 * len(opp_ret),
            }
    return out


def score_dst(dst: dict, pa_key: str = "pa") -> float:
    return score_game(Game(pos="DST", sacks=dst["sacks"], ints=dst["ints"], fumbles_recovered=dst["fr"],
                           safeties=dst["safeties"], points_against=int(dst[pa_key]), def_td_yards=list(dst["def_td_yards"])))


def check_special_against_cbs(pbp: list[dict], team_week: list[dict], schedule: list[dict], players: list[dict],
                              season: int, weeks: list[int]) -> dict:
    """K and DST scores from nflverse vs CBS's exact totals."""
    kg = kicker_games(pbp)
    dg = dst_games(pbp, team_week, schedule, season)
    k_by_name = {norm(p.get("display_name") or ""): p["gsis_id"] for p in players
                 if p.get("gsis_id") and (p.get("position") or "").upper() == "K"}
    res = {"K": [], "DST": {"pa": [], "pa_no_ret": []}, "unmatched": []}
    for wk in weeks:
        path = ROOT / f"cbs_stats_week{wk}.csv"
        if not path.exists():
            continue
        for cbs in csv.DictReader(path.open(encoding="utf-8")):
            line = row_to_actuals(cbs)
            if line["pos"] == "K" and line.get("cbs_total") is not None and line_has_box(line):
                gid = k_by_name.get(norm(cbs.get("player") or ""))
                k = kg.get((gid, wk)) if gid else None
                if not k:
                    res["unmatched"].append({"player": cbs.get("player"), "week": wk, "pos": "K"})
                    continue
                res["K"].append({"player": cbs.get("player"), "week": wk, "cbs": float(line["cbs_total"]), "ours": score_kicker(k),
                                 "fg": k["fg_yards"], "xp": k["xp"]})
            elif line["pos"] == "DST" and line.get("cbs_total") is not None:
                team = CBS_TEAM.get(cbs.get("team") or "", cbs.get("team") or "")
                dst = dg.get((team, wk))
                if not dst:
                    continue  # bye or not played yet
                for key in ("pa", "pa_no_ret"):
                    res["DST"][key].append({"team": team, "week": wk, "cbs": float(line["cbs_total"]), "ours": score_dst(dst, key),
                                            "cbs_pa": line.get("pa"), "pa": dst[key], "line": dst,
                                            "cbs_line": {k: line.get(k) for k in ("sacks", "ints", "fr", "safeties", "def_td")}})

    def rate(rows):
        exact = sum(1 for r in rows if abs(r["ours"] - r["cbs"]) < 1e-6)
        return {"n": len(rows), "exact": exact, "rate": exact / len(rows) if rows else 0.0,
                "mismatches": [r for r in rows if abs(r["ours"] - r["cbs"]) >= 1e-6]}

    return {"K": rate(res["K"]), "DST": {k: rate(v) for k, v in res["DST"].items()}, "unmatched": res["unmatched"]}
