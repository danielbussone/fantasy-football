"""FantasyPros Week N FLX/QB/K/DST ranks. Does not touch merge.py math."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from cbs_client import norm

ROOT = Path(__file__).resolve().parents[1]
WEEK_FP = ROOT / "week_fp.csv"
META = ROOT / "week_fp_meta.json"

WEEK_RE = re.compile(r"Week[_\s]*(\d+)", re.I)
LIST_RE = re.compile(r"(?:^|[_\s-])(FLX|QB|K|DST)(?:[_\s.-]|$)", re.I)
POS_RE = re.compile(r"^([A-Z]+)")
FIELDS = (
    "player",
    "team",
    "pos",
    "list",
    "rk",
    "n",
    "weekly_value",
    "week",
    "opp",
    "matchup",
    "start_sit",
    "proj_fpts",
)

# CBS DST is "Seahawks" / SEA; FantasyPros uses city + mascot.
NICK_TO_ABBR = {
    "arizona cardinals": "ARI",
    "cardinals": "ARI",
    "atlanta falcons": "ATL",
    "falcons": "ATL",
    "baltimore ravens": "BAL",
    "ravens": "BAL",
    "buffalo bills": "BUF",
    "bills": "BUF",
    "carolina panthers": "CAR",
    "panthers": "CAR",
    "chicago bears": "CHI",
    "bears": "CHI",
    "cincinnati bengals": "CIN",
    "bengals": "CIN",
    "cleveland browns": "CLE",
    "browns": "CLE",
    "dallas cowboys": "DAL",
    "cowboys": "DAL",
    "denver broncos": "DEN",
    "broncos": "DEN",
    "detroit lions": "DET",
    "lions": "DET",
    "green bay packers": "GB",
    "packers": "GB",
    "houston texans": "HOU",
    "texans": "HOU",
    "indianapolis colts": "IND",
    "colts": "IND",
    "jacksonville jaguars": "JAC",
    "jaguars": "JAC",
    "kansas city chiefs": "KC",
    "chiefs": "KC",
    "las vegas raiders": "LV",
    "raiders": "LV",
    "los angeles chargers": "LAC",
    "chargers": "LAC",
    "los angeles rams": "LAR",
    "rams": "LAR",
    "miami dolphins": "MIA",
    "dolphins": "MIA",
    "minnesota vikings": "MIN",
    "vikings": "MIN",
    "new england patriots": "NE",
    "patriots": "NE",
    "new orleans saints": "NO",
    "saints": "NO",
    "new york giants": "NYG",
    "giants": "NYG",
    "new york jets": "NYJ",
    "jets": "NYJ",
    "philadelphia eagles": "PHI",
    "eagles": "PHI",
    "pittsburgh steelers": "PIT",
    "steelers": "PIT",
    "san francisco 49ers": "SF",
    "49ers": "SF",
    "seattle seahawks": "SEA",
    "seahawks": "SEA",
    "tampa bay buccaneers": "TB",
    "buccaneers": "TB",
    "tennessee titans": "TEN",
    "titans": "TEN",
    "washington commanders": "WAS",
    "commanders": "WAS",
}


def weekly_value(rk: int, n: int) -> float:
    """Per-list percentile scaled to ~0–8. #1 ≈ 8, last ≈ 0."""
    n = max(int(n), 1)
    rk = max(int(rk), 1)
    return round((1 - (rk - 1) / n) * 8, 3)


def infer_meta(filename: str, fallback_week: int = 1) -> tuple[int, str]:
    week_m = WEEK_RE.search(filename or "")
    list_m = LIST_RE.search(filename or "")
    week = int(week_m.group(1)) if week_m else fallback_week
    kind = (list_m.group(1) if list_m else "FLX").upper()
    if kind == "DST":
        kind = "DST"
    return week, kind


def _cell(row: dict, *names: str) -> str:
    lower = {re.sub(r"\s+", " ", (k or "").strip().strip('"').upper()): v for k, v in row.items()}
    for n in names:
        v = lower.get(n.upper())
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _strip_pos(raw: str, fallback: str) -> str:
    m = POS_RE.match((raw or "").strip().upper())
    if m:
        return m.group(1)
    return (fallback or "").upper()


def parse_fp_csv(path: Path, *, fallback_week: int = 1, list_name: str | None = None) -> list[dict]:
    week, kind = infer_meta(path.name, fallback_week)
    if list_name:
        kind = list_name.upper()
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    n = len(rows)
    out = []
    for r in rows:
        try:
            rk = int(float(_cell(r, "RK", "RANK")))
        except (TypeError, ValueError):
            continue
        name = _cell(r, "PLAYER NAME", "PLAYER", "NAME")
        if not name:
            continue
        team = _cell(r, "TEAM").upper()
        pos = _strip_pos(_cell(r, "POS"), kind if kind != "FLX" else "")
        if kind != "FLX" and not pos:
            pos = kind
        if kind == "DST":
            pos = "DST"
            if not team:
                team = NICK_TO_ABBR.get(norm(name), "")
        out.append(
            {
                "player": name,
                "team": team,
                "pos": pos,
                "list": kind,
                "rk": rk,
                "n": n,
                "weekly_value": weekly_value(rk, n),
                "week": week,
                "opp": _cell(r, "OPP"),
                "matchup": _cell(r, "MATCHUP"),
                "start_sit": _cell(r, "START/SIT", "START SIT"),
                "proj_fpts": _cell(r, "PROJ. FPTS", "PROJ FPTS", "FPTS"),
            }
        )
    return out


def load_weekly(path: Path | None = None) -> list[dict]:
    p = path or WEEK_FP
    if not p.exists():
        return []
    rows = []
    for r in csv.DictReader(p.open(encoding="utf-8")):
        rec = dict(r)
        try:
            rec["rk"] = int(float(rec.get("rk") or 0))
        except (TypeError, ValueError):
            rec["rk"] = 0
        try:
            rec["n"] = int(float(rec.get("n") or 0))
        except (TypeError, ValueError):
            rec["n"] = 0
        try:
            rec["weekly_value"] = float(rec.get("weekly_value") or 0)
        except (TypeError, ValueError):
            rec["weekly_value"] = weekly_value(rec["rk"], rec["n"] or 1)
        try:
            rec["week"] = int(float(rec.get("week") or 0))
        except (TypeError, ValueError):
            rec["week"] = 0
        rows.append(rec)
    return rows


def write_weekly(rows: list[dict], path: Path | None = None) -> Path:
    p = path or WEEK_FP
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(FIELDS))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    return p


def merge_weekly(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Replace only the lists present in incoming; keep the rest."""
    lists = {r["list"] for r in incoming}
    kept = [r for r in existing if r.get("list") not in lists]
    return kept + incoming


def write_meta(week: int, lists: list[str], when: str | None = None) -> dict:
    when = when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"week": week, "lists": sorted(set(lists)), "as_of": when}
    META.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def read_meta() -> dict:
    if META.exists():
        try:
            return json.loads(META.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    rows = load_weekly()
    if not rows:
        return {"week": 0, "lists": [], "as_of": ""}
    lists = sorted({r.get("list") or "" for r in rows if r.get("list")})
    return {"week": rows[0].get("week") or 0, "lists": lists, "as_of": ""}


def import_weekly_files(paths: list[Path], *, fallback_week: int = 1) -> dict:
    incoming: list[dict] = []
    for p in paths:
        incoming.extend(parse_fp_csv(p, fallback_week=fallback_week))
    if not incoming:
        return read_meta()
    merged = merge_weekly(load_weekly(), incoming)
    write_weekly(merged)
    week = incoming[0].get("week") or fallback_week
    return write_meta(int(week), [r["list"] for r in merged])


def _dst_key(name: str, team: str) -> str:
    abbr = (team or "").upper()
    if abbr:
        return f"dst:{abbr}"
    nick = NICK_TO_ABBR.get(norm(name), "")
    return f"dst:{nick}" if nick else ""


def index_weekly(rows: list[dict] | None = None) -> dict[str, dict]:
    """Lookup by norm(name) and dst:SEA."""
    rows = rows if rows is not None else load_weekly()
    by: dict[str, dict] = {}
    for r in rows:
        by[norm(r.get("player") or "")] = r
        if (r.get("pos") or "").upper() == "DST" or (r.get("list") or "") == "DST":
            dk = _dst_key(r.get("player") or "", r.get("team") or "")
            if dk:
                by[dk] = r
            nick = NICK_TO_ABBR.get(norm(r.get("player") or ""), "")
            if nick:
                by[f"dst:{nick}"] = r
            # CBS roster uses nickname only
            parts = (r.get("player") or "").split()
            if parts:
                by[norm(parts[-1])] = r
    return by


def lookup_weekly(name: str, team: str = "", pos: str = "", index: dict | None = None) -> dict | None:
    idx = index if index is not None else index_weekly()
    hit = idx.get(norm(name))
    if hit:
        return hit
    if (pos or "").upper() == "DST" or NICK_TO_ABBR.get(norm(name)):
        abbr = (team or "").upper() or NICK_TO_ABBR.get(norm(name), "")
        if abbr:
            return idx.get(f"dst:{abbr}")
    return None


def attach_weekly(rec: dict, index: dict | None = None) -> dict:
    row = lookup_weekly(rec.get("player") or "", rec.get("team") or "", rec.get("pos") or "", index)
    out = dict(rec)
    if not row:
        out["weekly_rank"] = None
        out["weekly_value"] = None
        out["weekly_list"] = None
        out["weekly_opp"] = ""
        out["weekly_matchup"] = ""
        out["weekly_start_sit"] = ""
        return out
    out["weekly_rank"] = row.get("rk")
    out["weekly_value"] = row.get("weekly_value")
    out["weekly_list"] = row.get("list")
    out["weekly_opp"] = row.get("opp") or ""
    out["weekly_matchup"] = row.get("matchup") or ""
    out["weekly_start_sit"] = row.get("start_sit") or ""
    out["weekly_proj_fpts"] = row.get("proj_fpts") or ""
    return out


def apply_weekly_shift(player: dict, weekly_weight: float) -> dict:
    """Shift the injury-adjusted curve toward FP weekly_value; keep P90-P10 spread.

    Out/IR stay 0. weekly_weight 0 is a no-op on the numbers.
    """
    from lineup.start_sit import OBJECTIVES, injury_tag

    p = dict(player)
    proj = dict(p.get("proj") or {})
    if proj.get("_weekly_adj"):
        return p
    tag = injury_tag(p)
    wv = p.get("weekly_value")
    if tag in {"out", "ir", "injured", "pup"} or wv is None or float(weekly_weight or 0) <= 0:
        proj["_weekly_adj"] = True
        p["proj"] = proj
        return p
    p50 = float(proj.get("p50") or 0)
    delta = float(weekly_weight) * (float(wv) - p50)
    for key in (*OBJECTIVES, "mean"):
        if proj.get(key) is not None:
            proj[key] = round(float(proj[key]) + delta, 2)
    proj["weekly_shift"] = round(delta, 3)
    proj["_weekly_adj"] = True
    p["proj"] = proj
    return p


def stamp_line(meta: dict | None = None) -> str:
    m = meta if meta is not None else read_meta()
    lists = m.get("lists") or []
    if not lists and not m.get("as_of"):
        return ""
    bits = "+".join(lists) if lists else "—"
    return f"Weekly FP week {m.get('week') or '?'} · {bits} · as of {m.get('as_of') or '—'}"
