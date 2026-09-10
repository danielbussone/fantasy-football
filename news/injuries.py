"""Injury notes: CBS slot plus ESPN NFL injury feed. Fail soft."""
from __future__ import annotations

import gzip
import json
import re
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cbs_client import norm

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "injury_notes.json"
_CTX = ssl.create_default_context()
ESPN_NEWS = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=50"
ESPN_INJ = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"


def _get(url: str, timeout: int = 20) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Encoding": "gzip",
        },
    )
    with urlopen(req, timeout=timeout, context=_CTX) as resp:
        raw = resp.read()
        if raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
        return raw.decode("utf-8", "replace")


OFFICIAL_STATUS = {
    "out": "Out",
    "doubtful": "Doubtful",
    "questionable": "Questionable",
    "probable": "Probable",
    "ir": "IR",
    "injured reserve": "IR",
    "injured": "Injured",
    "pup": "PUP",
    "suspended": "SUS",
}


def official_status(status: str) -> str | None:
    """Only an explicit designation. Never infer Q from a news blurb."""
    return OFFICIAL_STATUS.get((status or "").strip().lower())


def designation_from_text(text: str) -> str | None:
    """Parse a CBS-style injury line ('Ankle: Out for Week 1'). None if no designation."""
    low = (text or "").lower()
    if "injured reserve" in low or re.search(r"\bir\b", low) or re.search(r"\bpup\b", low):
        return "IR"
    if re.search(r"\bout\b", low):
        return "Out"
    if "doubt" in low:
        return "Doubtful"
    if "probab" in low:
        return "Probable"
    if "question" in low:
        return "Questionable"
    return None


def is_out(designation: str) -> bool:
    return (designation or "").lower() in {"out", "ir", "doubtful"}


def fetch_espn_player_items() -> tuple[dict[str, dict], dict[str, dict]]:
    """Split ESPN's feed: official designations vs roster blurbs (no badge)."""
    try:
        data = json.loads(_get(ESPN_INJ, timeout=20))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {}, {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    injuries: dict[str, dict] = {}
    roster_notes: dict[str, dict] = {}
    for team in data.get("injuries") or []:
        for inj in team.get("injuries") or []:
            ath = inj.get("athlete") or {}
            name = ath.get("displayName") or ""
            if not name:
                continue
            details = inj.get("details") or {}
            fantasy = (details.get("fantasyStatus") or {}).get("abbreviation") or ""
            designation = official_status(inj.get("status") or "") or official_status(fantasy)
            body = details.get("type") or ""
            ret = details.get("returnDate") or ""
            comment = (inj.get("shortComment") or inj.get("longComment") or "").strip()
            as_of = inj.get("date") or now
            if comment:
                text = comment
                if ret and designation:
                    text = f"{text} Expected return {ret}."
                roster_notes[norm(name)] = {
                    "player": name,
                    "text": text,
                    "source": "ESPN",
                    "as_of": as_of,
                }
            if not designation:
                continue
            note = comment or (f"{body} — {designation}".strip(" —") if body else designation)
            if ret:
                note = f"{note} Expected return {ret}."
            injuries[norm(name)] = {
                "player": name,
                "designation": designation,
                "note": note,
                "source": "ESPN injury report",
                "as_of": as_of,
                "out": is_out(designation),
            }
    return injuries, roster_notes


def fetch_espn_injury_report() -> dict[str, dict]:
    """Official ESPN designations only."""
    injuries, _ = fetch_espn_player_items()
    return injuries


def from_depth_tooltip(text: str, player: str = "") -> dict | None:
    tip = (text or "").strip()
    if not tip:
        return None
    designation = designation_from_text(tip)
    if not designation:
        return None
    return {
        "player": player,
        "designation": designation,
        "note": tip,
        "source": "CBS depth chart",
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "out": is_out(designation),
    }


def fetch_espn_blurbs() -> list[dict]:
    try:
        raw = _get(ESPN_NEWS)
        data = json.loads(raw)
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    out = []
    for art in data.get("articles") or []:
        headline = art.get("headline") or art.get("description") or ""
        if not headline:
            continue
        out.append(
            {
                "headline": headline,
                "description": art.get("description") or "",
                "published": art.get("published") or "",
                "source": "ESPN",
            }
        )
    return out


def match_notes(names: list[str], blurbs: list[dict]) -> dict[str, dict]:
    notes = {}
    skip = {"jr", "sr", "ii", "iii", "iv"}
    for name in names:
        key = norm(name)
        bits = [p for p in re.split(r"\s+", name.strip()) if p.lower().strip(".") not in skip]
        last = bits[-1] if bits else name
        hits = []
        for b in blurbs:
            blob = (b["headline"] + " " + b["description"]).lower()
            if last.lower() in blob and len(last) > 3:
                hits.append(b)
        if not hits:
            continue
        h = hits[0]
        designation = designation_from_text(h["headline"] + " " + h.get("description", ""))
        if not designation:
            continue
        notes[key] = {
            "player": name,
            "designation": designation,
            "note": h["headline"],
            "source": "ESPN news",
            "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "out": is_out(designation),
        }
    return notes


def from_cbs_slots(roster: list[dict]) -> dict[str, dict]:
    notes = {}
    for r in roster:
        slot = (r.get("slot") or "").lower()
        if slot in {"injured", "ir", "o", "out"}:
            notes[norm(r["player"])] = {
                "player": r["player"],
                "designation": "Out" if slot != "injured" else "Injured",
                "note": f"CBS lineup slot: {r.get('slot')}",
                "source": "CBS",
                "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "out": True,
            }
    return notes


_ESPN_CACHE: dict = {"t": 0.0, "injuries": {}, "roster_notes": {}}


def cached_espn_feed(ttl: float = 600) -> tuple[dict[str, dict], dict[str, dict]]:
    now = time.time()
    if _ESPN_CACHE["injuries"] and now - _ESPN_CACHE["t"] < ttl:
        return _ESPN_CACHE["injuries"], _ESPN_CACHE["roster_notes"]
    injuries, roster_notes = fetch_espn_player_items()
    if injuries or roster_notes:
        _ESPN_CACHE["t"] = now
        _ESPN_CACHE["injuries"] = injuries
        _ESPN_CACHE["roster_notes"] = roster_notes
        return injuries, roster_notes
    return _ESPN_CACHE["injuries"] or {}, _ESPN_CACHE["roster_notes"] or {}


def cached_espn_report(ttl: float = 600) -> dict[str, dict]:
    injuries, _ = cached_espn_feed(ttl)
    return injuries


def _keep_note(note: dict) -> bool:
    if (note.get("source") or "") == "ESPN news":
        return False
    return bool(official_status(note.get("designation") or ""))


def notes_for_week() -> dict:
    """Official designations in `notes`; ESPN blurbs in `roster_notes` (no badge)."""
    disk = load()
    kept = {k: v for k, v in (disk.get("notes") or {}).items() if _keep_note(v)}
    injuries, roster_notes = cached_espn_feed()
    disk_blurbs = disk.get("roster_notes") or {}
    return {
        "as_of": disk.get("as_of") or "",
        "notes": {**kept, **injuries},
        "roster_notes": {**disk_blurbs, **roster_notes},
    }


def refresh(roster: list[dict], extra_names: list[str] | None = None) -> dict:
    existing = {k: v for k, v in (load().get("notes") or {}).items() if _keep_note(v)}
    cbs = from_cbs_slots(roster)
    injuries, roster_notes = fetch_espn_player_items()
    if injuries or roster_notes:
        _ESPN_CACHE["t"] = time.time()
        _ESPN_CACHE["injuries"] = injuries
        _ESPN_CACHE["roster_notes"] = roster_notes
        merged = {**injuries, **cbs}
    else:
        merged = {**existing, **cbs}
        roster_notes = load().get("roster_notes") or {}
    payload = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": merged,
        "roster_notes": roster_notes,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load() -> dict:
    if not OUT.exists():
        return {"as_of": "", "notes": {}}
    return json.loads(OUT.read_text(encoding="utf-8"))
