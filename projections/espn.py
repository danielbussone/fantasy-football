"""ESPN weekly stat projections from a HAR (or replayed kona_player_info).

appliedTotal is ESPN scoring — stored as espn_pts tooltip only, never as Present.
"""
from __future__ import annotations

import csv
import json
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cbs_client import norm

ROOT = Path(__file__).resolve().parents[1]
ESPN_WEEK = ROOT / "espn_week.csv"
ESPN_META = ROOT / "espn_week_meta.json"
ESPN_COOKIES = ROOT / "espn_cookies.txt"

KONA_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026"
    "/segments/0/leaguedefaults/1?view=kona_player_info"
)
POS_ID = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
PRO_TEAM = {
    1: "ATL",
    2: "BUF",
    3: "CHI",
    4: "CIN",
    5: "CLE",
    6: "DAL",
    7: "DEN",
    8: "DET",
    9: "GB",
    10: "TEN",
    11: "IND",
    12: "KC",
    13: "LV",
    14: "LAR",
    15: "MIA",
    16: "MIN",
    17: "NE",
    18: "NO",
    19: "NYG",
    20: "NYJ",
    21: "PHI",
    22: "ARI",
    23: "PIT",
    24: "LAC",
    25: "SF",
    26: "SEA",
    27: "TB",
    28: "WAS",
    29: "CAR",
    30: "JAC",
    33: "BAL",
    34: "HOU",
}
# Confirmed against Week 1 2026 kona payload (Hurts / Chase / Gibbs).
STAT_PASS_YDS = "3"
STAT_PASS_TD = "4"
STAT_RUSH_YDS = "24"
STAT_RUSH_TD = "25"
STAT_REC_YDS = "42"
STAT_REC_TD = "43"
STAT_FG = "80"
STAT_XP = "86"
STAT_SACK = "95"
STAT_INT = "96"
STAT_PA = "120"  # week points allowed (~16), not 127 yards allowed
STAT_DEF_TD = "93"

FIELDS = (
    "player",
    "team",
    "pos",
    "week",
    "espn_id",
    "espn_pts",
    "qb_ypg",
    "rush_ypg",
    "pass_td_rate",
    "rush_td_rate",
    "rec_td_rate",
    "scrim_ypg",
    "rec_share",
    "fg_rate",
    "xp_mean",
    "sack_mean",
    "int_mean",
    "pa_mean",
    "def_td_p",
)
PRIOR_KEYS = (
    "qb_ypg",
    "rush_ypg",
    "pass_td_rate",
    "rush_td_rate",
    "rec_td_rate",
    "scrim_ypg",
    "rec_share",
    "fg_rate",
    "xp_mean",
    "sack_mean",
    "int_mean",
    "pa_mean",
    "def_td_p",
)

_CTX = ssl.create_default_context()


def _sf(stats: dict, key: str) -> float | None:
    v = stats.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cookie_from_har(path: Path) -> str:
    har = json.loads(path.read_text(encoding="utf-8"))
    best = ""
    for entry in har.get("log", {}).get("entries", []):
        url = entry.get("request", {}).get("url") or ""
        host = url.lower()
        if not any(h in host for h in ("espn.com", "espncdn.com", "lm-api-reads")):
            continue
        for h in entry.get("request", {}).get("headers", []):
            if h.get("name", "").lower() == "cookie" and h.get("value"):
                val = h["value"]
                if len(val) > len(best):
                    best = val
    if not best:
        raise ValueError(f"no Cookie header for espn.com in HAR: {path}")
    return best


def save_cookies(cookie: str, path: Path | None = None) -> Path:
    p = path or ESPN_COOKIES
    p.write_text(cookie, encoding="utf-8")
    return p


def load_cookies(path: Path | None = None) -> str:
    p = path or ESPN_COOKIES
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def _fantasy_filter(week: int, limit: int) -> dict:
    period = f"112026{week}"
    return {
        "players": {
            "filterStatsForSplitTypeIds": {"value": [0, 1]},
            "filterSlotIds": {"value": list(range(20)) + [23, 24]},
            "filterStatsForSourceIds": {"value": [0, 1]},
            "useFullProjectionTable": {"value": True},
            "sortAppliedStatTotal": {"sortAsc": False, "sortPriority": 3, "value": period},
            "sortPercOwned": {"sortPriority": 4, "sortAsc": False},
            "limit": limit,
            "filterRanksForSlotIds": {
                "value": [0, 2, 4, 6, 17, 16, 8, 9, 10, 12, 13, 24, 11, 14, 15]
            },
            "filterStatsForTopScoringPeriodIds": {
                "value": 2,
                "additionalValue": ["002026", "102026", "002025", period, "022026"],
            },
        }
    }


def _week_stats(player: dict, week: int) -> dict | None:
    for s in player.get("stats") or []:
        if s.get("statSourceId") == 1 and int(s.get("scoringPeriodId") or 0) == int(week):
            return s
    return None


def stats_to_prior(pos: str, stats: dict) -> dict[str, float]:
    """Map ESPN week-proj stat ids onto this repo's prior keys. No appliedTotal."""
    pos = (pos or "").upper()
    out: dict[str, float] = {}
    rush = _sf(stats, STAT_RUSH_YDS)
    rec = _sf(stats, STAT_REC_YDS)
    if pos == "QB":
        if (v := _sf(stats, STAT_PASS_YDS)) is not None:
            out["qb_ypg"] = v
        if rush is not None:
            out["rush_ypg"] = rush
        if (v := _sf(stats, STAT_PASS_TD)) is not None:
            out["pass_td_rate"] = v
        if (v := _sf(stats, STAT_RUSH_TD)) is not None:
            out["rush_td_rate"] = v
        return out
    if pos == "K":
        if (v := _sf(stats, STAT_FG)) is not None:
            out["fg_rate"] = v
        if (v := _sf(stats, STAT_XP)) is not None:
            out["xp_mean"] = v
        return out
    if pos == "DST":
        if (v := _sf(stats, STAT_SACK)) is not None:
            out["sack_mean"] = v
        if (v := _sf(stats, STAT_INT)) is not None:
            out["int_mean"] = v
        if (v := _sf(stats, STAT_PA)) is not None:
            out["pa_mean"] = v
        if (v := _sf(stats, STAT_DEF_TD)) is not None:
            out["def_td_p"] = v
        return out
    if rush is not None or rec is not None:
        r = rush or 0.0
        c = rec or 0.0
        scrim = r + c
        out["scrim_ypg"] = scrim
        if scrim:
            out["rec_share"] = c / scrim
    if (v := _sf(stats, STAT_RUSH_TD)) is not None:
        out["rush_td_rate"] = v
    if (v := _sf(stats, STAT_REC_TD)) is not None:
        out["rec_td_rate"] = v
    return out


def _dst_name(full: str, team: str) -> str:
    raw = (full or "").replace(" D/ST", "").replace(" DST", "").strip()
    # ESPN uses "Seahawks D/ST"; CBS roster is "Seahawks"
    return raw or team


def player_row(entry: dict, week: int) -> dict | None:
    pl = entry.get("player") or entry
    name = pl.get("fullName") or ""
    pos = POS_ID.get(int(pl.get("defaultPositionId") or 0), "")
    team = PRO_TEAM.get(int(pl.get("proTeamId") or 0), "")
    if not name or not pos:
        return None
    if pos == "DST":
        name = _dst_name(name, team)
    wk = _week_stats(pl, week)
    stats = (wk or {}).get("stats") or {}
    prior = stats_to_prior(pos, stats)
    espn_pts = (wk or {}).get("appliedTotal")
    try:
        espn_pts_s = "" if espn_pts is None else f"{float(espn_pts):.3f}"
    except (TypeError, ValueError):
        espn_pts_s = ""
    row = {
        "player": name,
        "team": team,
        "pos": pos,
        "week": week,
        "espn_id": pl.get("id") or entry.get("id") or "",
        "espn_pts": espn_pts_s,
    }
    for k in PRIOR_KEYS:
        v = prior.get(k)
        row[k] = "" if v is None else round(v, 4)
    return row


def parse_kona(payload: Any, week: int) -> list[dict]:
    if isinstance(payload, dict):
        players = payload.get("players") or []
    elif isinstance(payload, list):
        players = payload
    else:
        return []
    out = []
    for e in players:
        row = player_row(e, week)
        if row:
            out.append(row)
    return out


def extract_kona_from_har(path: Path, week: int) -> list[dict]:
    har = json.loads(path.read_text(encoding="utf-8"))
    best: list[dict] = []
    for entry in har.get("log", {}).get("entries", []):
        url = entry.get("request", {}).get("url") or ""
        if "kona_player_info" not in url:
            continue
        content = (entry.get("response") or {}).get("content") or {}
        text = content.get("text") or ""
        if content.get("encoding") == "base64":
            import base64

            text = base64.b64decode(text).decode("utf-8", errors="replace")
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        rows = parse_kona(data, week)
        if len(rows) > len(best):
            best = rows
    return best


def replay_kona(cookie: str, week: int, limit: int = 1000) -> list[dict]:
    filt = json.dumps(_fantasy_filter(week, limit), separators=(",", ":"))
    req = Request(
        KONA_URL,
        headers={
            "Cookie": cookie,
            "Accept": "application/json",
            "X-Fantasy-Filter": filt,
            "X-Fantasy-Source": "kona",
            "X-Fantasy-Platform": "espn-fantasy-web",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://fantasy.espn.com/",
        },
    )
    with urlopen(req, context=_CTX, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return parse_kona(data, week)


def write_espn_week(rows: list[dict], path: Path | None = None) -> Path:
    p = path or ESPN_WEEK
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(FIELDS))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    return p


def write_espn_meta(week: int, n: int, source: str, when: str | None = None) -> dict:
    when = when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"week": week, "n": n, "source": source, "as_of": when}
    ESPN_META.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def read_espn_meta() -> dict:
    if ESPN_META.exists():
        try:
            return json.loads(ESPN_META.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"week": 0, "n": 0, "source": "", "as_of": ""}


def _f(row: dict, key: str) -> float | None:
    v = row.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_espn(path: Path | None = None) -> dict[str, dict]:
    p = path or ESPN_WEEK
    if not p.exists():
        return {}
    by: dict[str, dict] = {}
    for r in csv.DictReader(p.open(encoding="utf-8")):
        rec = dict(r)
        for k in PRIOR_KEYS:
            rec[k] = _f(rec, k)
        rec["espn_pts"] = rec.get("espn_pts") or ""
        rec["has_espn"] = True
        by[norm(rec.get("player") or "")] = rec
        if (rec.get("pos") or "").upper() == "DST" and rec.get("team"):
            by[f"dst:{(rec['team'] or '').upper()}"] = rec
            by[norm(rec.get("team") or "")] = rec
    return by


def lookup_espn(name: str, team: str = "", pos: str = "", index: dict | None = None) -> dict | None:
    idx = index if index is not None else load_espn()
    hit = idx.get(norm(name))
    if hit:
        return hit
    if (pos or "").upper() == "DST":
        abbr = (team or "").upper()
        return idx.get(f"dst:{abbr}") or idx.get(norm(name))
    return None


def blend_espn(base: dict[str, Any], espn_row: dict | None, weight: float = 0.45) -> dict[str, Any]:
    """Mix history/3g prior with ESPN week volume. Missing row → unchanged."""
    out = dict(base)
    if not espn_row:
        return out
    w = float(weight)
    moved = False
    for k in PRIOR_KEYS:
        ev = espn_row.get(k)
        if ev is None or ev == "":
            continue
        evf = float(ev)
        if k in out and out[k] is not None:
            out[k] = (1 - w) * float(out[k]) + w * evf
        else:
            out[k] = evf
        moved = True
    if moved:
        src = out.get("source") or ""
        out["source"] = (src + "+espn") if src and "+espn" not in src else (src or "espn")
        out["has_espn"] = True
    return out


def import_espn_har(har_path: Path, *, week: int = 1, limit: int = 1000) -> dict:
    cookie = _cookie_from_har(har_path)
    save_cookies(cookie)
    source = "har"
    rows: list[dict] = []
    try:
        rows = replay_kona(cookie, week, limit=limit)
        source = "replay"
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        rows = []
    if not rows:
        rows = extract_kona_from_har(har_path, week)
        source = "har"
    write_espn_week(rows)
    return write_espn_meta(week, len(rows), source)


def stamp_line(meta: dict | None = None) -> str:
    m = meta if meta is not None else read_espn_meta()
    if not m.get("n") and not m.get("as_of"):
        return ""
    return f"ESPN week {m.get('week') or '?'} · {m.get('n') or 0} players · as of {m.get('as_of') or '—'}"
