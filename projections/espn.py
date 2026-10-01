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


def espn_week_csv(week: int | None = None) -> Path:
    if week is None:
        return ESPN_WEEK
    return ROOT / f"espn_week{int(week)}.csv"

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
STAT_PASS_ATT = "0"
STAT_PASS_YDS = "3"
STAT_PASS_TD = "4"
STAT_CAR = "23"
STAT_RUSH_YDS = "24"
STAT_RUSH_TD = "25"
STAT_REC_YDS = "42"
STAT_REC_TD = "43"
STAT_REC = "53"
STAT_TAR = "58"
STAT_FG = "80"
STAT_XP = "86"
STAT_SACK = "95"
STAT_INT = "96"
STAT_PA = "120"  # week points allowed (~16), not 127 yards allowed
STAT_DEF_TD = "93"

RAW_KEYS = (
    "pass_att",
    "pass_yds",
    "pass_td",
    "carries",
    "rush_yds",
    "rush_td",
    "targets",
    "receptions",
    "rec_yds",
    "rec_td",
    "fg",
    "xp",
    "sacks",
    "pa",
)

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
    *RAW_KEYS,
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
        pass_yds = _sf(stats, STAT_PASS_YDS)
        # qb_ypg is pass+rush together everywhere else in this repo (history,
        # 3g, the Monte Carlo prior) — match that unit here, not pass-only.
        if pass_yds is not None or rush is not None:
            out["qb_ypg"] = (pass_yds or 0.0) + (rush or 0.0)
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


def raw_stats(stats: dict) -> dict[str, float]:
    """ESPN week volume as named stats (targets, rec, yards, TDs). Not FPTS."""
    out: dict[str, float] = {}
    for key, sid in (
        ("pass_att", STAT_PASS_ATT),
        ("pass_yds", STAT_PASS_YDS),
        ("pass_td", STAT_PASS_TD),
        ("carries", STAT_CAR),
        ("rush_yds", STAT_RUSH_YDS),
        ("rush_td", STAT_RUSH_TD),
        ("targets", STAT_TAR),
        ("receptions", STAT_REC),
        ("rec_yds", STAT_REC_YDS),
        ("rec_td", STAT_REC_TD),
        ("fg", STAT_FG),
        ("xp", STAT_XP),
        ("sacks", STAT_SACK),
        ("pa", STAT_PA),
    ):
        v = _sf(stats, sid)
        if v is not None:
            out[key] = round(v, 4)
    return out


def hydrate_espn(row: dict) -> dict:
    """Fill rec/rush yards from older csv rows that only stored scrim + rec_share."""
    out = dict(row)
    if _f(out, "rec_yds") is None and _f(out, "scrim_ypg") is not None:
        scrim = float(out["scrim_ypg"] or 0)
        share = float(out.get("rec_share") or 0)
        out["rec_yds"] = round(scrim * share, 4)
        if _f(out, "rush_yds") is None:
            out["rush_yds"] = round(scrim * (1.0 - share), 4)
    if _f(out, "rush_yds") is None and _f(out, "rush_ypg") is not None:
        out["rush_yds"] = out["rush_ypg"]
    if _f(out, "pass_yds") is None and _f(out, "qb_ypg") is not None:
        out["pass_yds"] = out["qb_ypg"]
    if _f(out, "pass_td") is None and _f(out, "pass_td_rate") is not None:
        out["pass_td"] = out["pass_td_rate"]
    if _f(out, "rush_td") is None and _f(out, "rush_td_rate") is not None:
        out["rush_td"] = out["rush_td_rate"]
    if _f(out, "rec_td") is None and _f(out, "rec_td_rate") is not None:
        out["rec_td"] = out["rec_td_rate"]
    if _f(out, "fg") is None and _f(out, "fg_rate") is not None:
        out["fg"] = out["fg_rate"]
    if _f(out, "xp") is None and _f(out, "xp_mean") is not None:
        out["xp"] = out["xp_mean"]
    if _f(out, "sacks") is None and _f(out, "sack_mean") is not None:
        out["sacks"] = out["sack_mean"]
    if _f(out, "pa") is None and _f(out, "pa_mean") is not None:
        out["pa"] = out["pa_mean"]
    return out


def _fmt_stat(v, *, td: bool = False) -> str | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if td:
        if abs(n - round(n)) < 0.05:
            return str(int(round(n)))
        return f"{n:.1f}"
    return str(int(n + 0.5)) if n >= 0 else str(int(n - 0.5))


def espn_stat_line(row: dict, pos: str | None = None) -> str:
    """Compact ESPN volume line. Receptions/targets are volume, not GBFL points."""
    pos = (pos or row.get("pos") or "").upper()
    bits: list[str] = []

    def add(key: str, lab: str, skip_zero: bool = False, td: bool = False):
        s = _fmt_stat(row.get(key), td=td)
        if s is None:
            return
        if skip_zero and s in {"0", "0.0"}:
            return
        bits.append(f"{s}\u00a0{lab}")

    if pos == "QB":
        add("pass_yds", "pass")
        add("rush_yds", "ru", skip_zero=True)
        add("pass_td", "pass TD", td=True)
        add("rush_td", "ru TD", skip_zero=True, td=True)
    elif pos == "K":
        add("fg", "FG", td=True)
        add("xp", "XP", td=True)
    elif pos == "DST":
        add("pa", "PA")
        add("sacks", "sacks", td=True)
    else:
        add("targets", "tar")
        add("receptions", "rec")
        add("rec_yds", "rec yds")
        add("rec_td", "rec TD", td=True)
        add("carries", "car", skip_zero=True)
        add("rush_yds", "ru", skip_zero=True)
        add("rush_td", "ru TD", skip_zero=True, td=True)
    return " · ".join(bits)


def espn_to_sim(row: dict) -> dict[str, float]:
    """ESPN mean stats in the shape explain_from_sim / the Week tab sim block use."""
    row = hydrate_espn(row)

    def f(key: str) -> float:
        v = _f(row, key)
        return 0.0 if v is None else float(v)

    return {
        "pass_yds": f("pass_yds"),
        "rush_yds": f("rush_yds"),
        "rec_yds": f("rec_yds"),
        "pass_td": f("pass_td"),
        "rush_td": f("rush_td"),
        "rec_td": f("rec_td"),
        "fg": f("fg"),
        "xp": f("xp"),
        "sacks": f("sacks"),
        "pa": f("pa"),
    }


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
    raw = raw_stats(stats)
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
    for k in RAW_KEYS:
        v = raw.get(k)
        row[k] = "" if v is None else v
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


def write_espn_week(rows: list[dict], path: Path | None = None, week: int | None = None) -> Path:
    p = path or (espn_week_csv(week) if week is not None else ESPN_WEEK)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(FIELDS))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    if week is not None and p.resolve() != ESPN_WEEK.resolve():
        write_espn_week(rows, path=ESPN_WEEK)
    return p


def write_espn_meta(week: int, n: int, source: str, when: str | None = None) -> dict:
    when = when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev = read_espn_meta()
    by = dict(prev.get("by_week") or {}) if isinstance(prev.get("by_week"), dict) else {}
    entry = {"week": int(week), "n": n, "source": source, "as_of": when}
    by[str(int(week))] = entry
    meta = {**entry, "by_week": by}
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


def load_espn(path: Path | None = None, week: int | None = None) -> dict[str, dict]:
    p = path
    if p is None and week is not None:
        specific = espn_week_csv(week)
        if specific.exists() and specific.resolve() != ESPN_WEEK.resolve():
            p = specific
        else:
            meta = read_espn_meta()
            if int(meta.get("week") or 0) != int(week):
                return {}
            p = ESPN_WEEK
    p = p or ESPN_WEEK
    if not p.exists():
        return {}
    by: dict[str, dict] = {}
    for r in csv.DictReader(p.open(encoding="utf-8")):
        rec = dict(r)
        row_week = rec.get("week")
        if week is not None and row_week not in (None, "") and int(float(row_week)) != int(week):
            continue
        for k in PRIOR_KEYS:
            rec[k] = _f(rec, k)
        for k in RAW_KEYS:
            if rec.get(k) not in (None, ""):
                rec[k] = _f(rec, k)
        rec = hydrate_espn(rec)
        if (rec.get("pos") or "").upper() == "QB":
            # Older espn_week*.csv files stored qb_ypg as pass yards only;
            # recompute pass+rush from the raw columns so files already on
            # disk don't need a re-import to match history/3g's units.
            py = _f(rec, "pass_yds")
            ry = _f(rec, "rush_yds")
            if py is not None or ry is not None:
                rec["qb_ypg"] = (py or 0.0) + (ry or 0.0)
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


ESPN_MIXES = (0.0, 0.5, 1.0)
ESPN_MIX_LABEL = {0.0: "Monte Carlo", 0.5: "50/50", 1.0: "ESPN"}
# ESPN raw volume → usage-prior keys the Monte Carlo / Week tab read.
VOL_MAP = (
    ("targets", "targets_pg"),
    ("receptions", "rec_pg"),
    ("carries", "carries_pg"),
    ("pass_att", "pass_att_pg"),
)


def snap_espn_mix(v) -> float:
    """0 = full Monte Carlo prior, 0.5 = 50/50, 1 = ESPN week stats as the prior."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.5
    return min(ESPN_MIXES, key=lambda m: abs(m - x))


def mix_label(v) -> str:
    return ESPN_MIX_LABEL[snap_espn_mix(v)]


def blend_espn(base: dict[str, Any], espn_row: dict | None, weight: float = 0.5) -> dict[str, Any]:
    """Mix history/3g prior with ESPN week volume. weight 0 or missing row → unchanged."""
    out = dict(base)
    w = snap_espn_mix(weight)
    if not espn_row or w <= 0:
        return out
    moved = False

    def _mix_key(dst: str, ev) -> None:
        nonlocal moved
        if ev is None or ev == "":
            return
        try:
            evf = float(ev)
        except (TypeError, ValueError):
            return
        if dst in out and out[dst] is not None and out[dst] != "":
            out[dst] = (1 - w) * float(out[dst]) + w * evf
        else:
            out[dst] = evf
        moved = True

    for k in PRIOR_KEYS:
        _mix_key(k, espn_row.get(k))
    for src, dst in VOL_MAP:
        _mix_key(dst, espn_row.get(src))
    if moved:
        if w >= 1:
            out["source"] = "espn week stats"
        else:
            src = out.get("source") or ""
            out["source"] = (src + "+espn") if src and "+espn" not in src else (src or "espn")
        out["has_espn"] = True
        out["espn_mix"] = w
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
    write_espn_week(rows, week=week)
    return write_espn_meta(week, len(rows), source)


def refresh_espn_from_saved_cookies(week: int, limit: int = 1000) -> dict:
    """Re-pull ESPN's week stats using the cookie saved from the last HAR import.

    No fresh HAR needed as long as that cookie is still valid — this is what
    makes an unattended/background ESPN refresh possible at all. On any
    failure (expired cookie, ESPN unreachable, empty result) existing
    espn_week*.csv/meta are left untouched rather than overwritten with
    nothing, and the error is reported so the UI can say "re-import a HAR"
    instead of just going quiet.
    """
    cookie = load_cookies()
    if not cookie:
        return {"ok": False, "week": week, "error": "no stored ESPN cookie — import a HAR once"}
    try:
        rows = replay_kona(cookie, week, limit=limit)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
        return {"ok": False, "week": week, "error": f"{type(e).__name__}: {e}"}
    if not rows:
        return {"ok": False, "week": week, "error": "ESPN returned 0 players — cookie may be expired"}
    write_espn_week(rows, week=week)
    meta = write_espn_meta(week, len(rows), "auto")
    return {"ok": True, "week": week, "n": len(rows), **meta}


def stamp_line(meta: dict | None = None, week: int | None = None) -> str:
    m = meta if meta is not None else read_espn_meta()
    if week is not None:
        by = m.get("by_week") if isinstance(m.get("by_week"), dict) else {}
        hit = by.get(str(int(week))) if by else None
        if hit:
            return f"ESPN week {hit.get('week') or week} · {hit.get('n') or 0} players · as of {hit.get('as_of') or '—'}"
        if espn_week_csv(week).exists() and espn_week_csv(week).resolve() != ESPN_WEEK.resolve():
            return f"ESPN week {week} on file"
        if int(m.get("week") or 0) == int(week):
            return f"ESPN week {m.get('week') or '?'} · {m.get('n') or 0} players · as of {m.get('as_of') or '—'}"
        if m.get("n") or m.get("as_of"):
            return f"ESPN week {m.get('week') or '?'} on file — not used for week {week}. Import ESPN."
        return ""
    if not m.get("n") and not m.get("as_of"):
        return ""
    return f"ESPN week {m.get('week') or '?'} · {m.get('n') or 0} players · as of {m.get('as_of') or '—'}"
