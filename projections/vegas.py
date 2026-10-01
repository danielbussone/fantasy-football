"""Vegas-implied team scoring, from ESPN's public (no-auth) scoreboard.

This is GBFL_RULES.md §7's top signal ("KING in a TD-bonus format") — a
team's over/under and spread already price in weather, pace, injuries, and
matchup strength, before any of this repo's own priors do. A team's
expected points = over/under split by the spread. Applied to the sim's
usage prior in app/assemble.py, *before* ESPN's own week projections are
blended in (those already bake Vegas in — applying this after would double
it up).

No auth needed: same public site.api.espn.com host the injury feed uses.
"""
from __future__ import annotations

import json
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SEASON = 2026
LEAGUE_AVG_FALLBACK = 22.0  # used only when a week has no odds at all yet
_CTX = ssl.create_default_context()

# The scoreboard endpoint uses different abbreviations than CBS (cbs_roster/
# cbs_fa) and this repo's own ESPN fantasy-API mapping (projections/espn.py
# PRO_TEAM) for the same two teams — normalize to the repo's canonical form
# so a player's team abbreviation always finds its Vegas line.
_TEAM_ALIAS = {"JAX": "JAC", "WSH": "WAS"}


def _norm_team(abbr: str) -> str:
    abbr = (abbr or "").upper()
    return _TEAM_ALIAS.get(abbr, abbr)


def vegas_week_json(week: int) -> Path:
    return ROOT / f"vegas_week{int(week)}.json"


def fetch_scoreboard(week: int, season: int = SEASON, timeout: int = 20) -> dict:
    url = f"{SCOREBOARD_URL}?week={int(week)}&seasontype=2&dates={int(season)}"
    # This exact minimal UA is what worked in testing against this endpoint —
    # the longer UA strings used elsewhere in this repo (news/injuries.py,
    # projections/espn.py) got a 403 here specifically.
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, context=_CTX, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def team_totals_from_scoreboard(payload: dict) -> dict[str, dict]:
    """{TEAM_ABBR: {total, opp, over_under, spread, indoor, kickoff, temperature}}.

    total is that team's Vegas-implied points for the week: over_under/2
    plus/minus half the spread. ESPN's `spread` is signed relative to the
    home team (negative = home favored) — confirmed against a live GB -5.5
    home favorite: spread=-5.5 gives home 24.0 / away 18.5 on a 42.5 total,
    which nets back to a 5.5-point home favorite and sums to the total.
    """
    out: dict[str, dict] = {}
    for ev in payload.get("events") or []:
        comps = ev.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        by_side = {c.get("homeAway"): c for c in (comp.get("competitors") or [])}
        home, away = by_side.get("home"), by_side.get("away")
        if not home or not away:
            continue
        home_abbr = _norm_team((home.get("team") or {}).get("abbreviation") or "")
        away_abbr = _norm_team((away.get("team") or {}).get("abbreviation") or "")
        if not home_abbr or not away_abbr:
            continue
        odds_list = comp.get("odds") or []
        odds = odds_list[0] if odds_list else {}
        total = odds.get("overUnder")
        spread = odds.get("spread")
        venue = comp.get("venue") or {}
        indoor = bool(venue.get("indoor"))
        weather = ev.get("weather") or comp.get("weather") or {}
        common = {
            "opp": None,  # filled per-side below
            "over_under": total,
            "indoor": indoor,
            "kickoff": ev.get("date") or "",
            "temperature": weather.get("temperature"),
        }
        if total is not None and spread is not None:
            home_pts = round(float(total) / 2 - float(spread) / 2, 2)
            away_pts = round(float(total) / 2 + float(spread) / 2, 2)
            out[home_abbr] = {**common, "total": home_pts, "opp": away_abbr, "spread": spread}
            out[away_abbr] = {**common, "total": away_pts, "opp": home_abbr, "spread": -float(spread)}
        else:
            # No line yet (early week, or an odds-less matchup) — still
            # record kickoff/indoor so the Opp column can show them.
            out.setdefault(home_abbr, {**common, "total": None, "opp": away_abbr, "spread": None})
            out.setdefault(away_abbr, {**common, "total": None, "opp": home_abbr, "spread": None})
    return out


def league_average_total(team_totals: dict[str, dict]) -> float:
    vals = [t["total"] for t in team_totals.values() if t.get("total") is not None]
    return round(sum(vals) / len(vals), 2) if vals else LEAGUE_AVG_FALLBACK


def write_vegas_week(week: int, team_totals: dict, when: str | None = None) -> dict:
    payload = {
        "week": int(week),
        "as_of": when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "league_avg": league_average_total(team_totals),
        "teams": team_totals,
    }
    vegas_week_json(week).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def read_vegas_week(week: int) -> dict:
    p = vegas_week_json(week)
    if not p.exists():
        return {"week": int(week), "as_of": "", "league_avg": LEAGUE_AVG_FALLBACK, "teams": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"week": int(week), "as_of": "", "league_avg": LEAGUE_AVG_FALLBACK, "teams": {}}


def refresh_vegas(week: int, season: int = SEASON) -> dict:
    """Fetch + persist this week's Vegas team totals.

    Never raises and never overwrites good data with nothing: a network
    hiccup or an empty response just returns what's already on disk.
    """
    try:
        payload = fetch_scoreboard(week, season)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return read_vegas_week(week)
    team_totals = team_totals_from_scoreboard(payload)
    if not team_totals:
        return read_vegas_week(week)
    return write_vegas_week(week, team_totals)


def team_total(team: str, week: int) -> dict | None:
    data = read_vegas_week(week)
    return (data.get("teams") or {}).get((team or "").upper())


# Usage-prior keys this touches. TD rates move with a team's own scoring
# pace; yards move less (a damped ^0.3 — volume/game-script drive yards more
# than raw scoring rate does). A DST's PA prior instead leans toward its
# *opponent's* implied total, since that's what it's actually defending.
_TD_KEYS = ("pass_td_rate", "rush_td_rate", "rec_td_rate")
_YARD_KEYS = ("scrim_ypg", "qb_ypg", "rush_ypg")
_RATIO_CLAMP = (0.5, 1.8)  # damp extreme lines so one game can't wreck a prior
_PA_BLEND_WEIGHT = 0.6


def apply_vegas(prior: dict, team: str, pos: str, vegas_data: dict) -> dict:
    """Scale a usage prior toward this team's (or opponent's, for DST) Vegas
    line. A no-op when there's no line for this team yet — bye week, a
    missing pull, or the odds board not posted — so it never silently
    zeroes anything out; callers just get the unadjusted prior back.
    """
    teams = vegas_data.get("teams") or {}
    entry = teams.get((team or "").upper())
    if not entry or entry.get("total") is None:
        return prior
    league_avg = float(vegas_data.get("league_avg") or LEAGUE_AVG_FALLBACK)
    if league_avg <= 0:
        return prior
    pos = (pos or "").upper()
    out = dict(prior)
    if pos == "DST":
        opp_entry = teams.get((entry.get("opp") or "").upper())
        if opp_entry and opp_entry.get("total") is not None and out.get("pa_mean") is not None:
            out["pa_mean"] = round(
                (1 - _PA_BLEND_WEIGHT) * float(out["pa_mean"]) + _PA_BLEND_WEIGHT * float(opp_entry["total"]), 2
            )
        out["vegas_total"] = entry.get("total")
        return out
    ratio = max(_RATIO_CLAMP[0], min(_RATIO_CLAMP[1], float(entry["total"]) / league_avg))
    yard_ratio = ratio**0.3
    for k in _TD_KEYS:
        if out.get(k) is not None:
            out[k] = float(out[k]) * ratio
    for k in _YARD_KEYS:
        if out.get(k) is not None:
            out[k] = float(out[k]) * yard_ratio
    if pos == "K":
        for k in ("fg_rate", "xp_mean"):
            if out.get(k) is not None:
                out[k] = float(out[k]) * ratio
        if entry.get("indoor") and out.get("fg_rate"):
            out["fg_rate"] = float(out["fg_rate"]) * 1.03  # small dome nudge — a tiebreak, not the main signal
    out["vegas_total"] = entry.get("total")
    out["vegas_ratio"] = round(ratio, 3)
    return out
