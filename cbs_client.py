"""CBS Sports fantasy football client for the castrati (GBFL) league.

Auth is a browser Cookie header loaded from a gitignored file, an env var, or a
HAR export. HAR files are credentials — never commit them.

See cbs_api.md for the endpoint map. Stats endpoints return HTML tables
(jQuery XHR), not JSON. CBS projections are ignored by default.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import ssl
from collections import Counter
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOST = "https://castrati.football.cbssports.com"
LEAGUE_ID = "castrati"
MY_TEAM = "BUSSONE"
MY_TEAM_ID = "12"

# 10-team GBFL. Gaps (3, 4, 7) are unused ids, not missing teams.
TEAM_IDS = {
    "1": "BOLDING",
    "2": "MUCK/UZES",
    "5": "CHEN",
    "6": "FORBES",
    "8": "FREEMANS",
    "9": "PRESTON",
    "10": "THROBBER",
    "11": "BAUKOL",
    "12": "BUSSONE",
    "13": "ANN",
}
OWNER_TO_ID = {v: k for k, v in TEAM_IDS.items()}

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0"
)
COOKIE_FILE_CANDIDATES = ("cbs_cookies.txt", "cbs_cookies")
ALIAS = {
    "kenneth gainwell": "kenny gainwell",
    "devon achane": "de'von achane",
    "d'von achane": "de'von achane",
    "andres borregales": "andy borregales",  # CBS uses his full name, nflverse "Andy"
}

_CTX = ssl.create_default_context()
_BULLET = re.compile(r"\s*[•·\u2022]\s*|&(?:#149|#8226|bull);")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def norm(name: str) -> str:
    s = re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", (name or "").lower().strip())
    s = s.replace(".", "")
    return ALIAS.get(s, s)


def plain(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", html or ""))).strip()


def split_pos_team(blob: str) -> tuple[str, str]:
    blob = unescape(blob or "").strip()
    parts = [p.strip() for p in _BULLET.split(blob) if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return (parts[0] if parts else ""), ""


def load_cookie_header(
    cookies_path: str | os.PathLike | None = None,
    har_path: str | os.PathLike | None = None,
) -> str:
    """Return a raw Cookie header value. Never logs the value."""
    if har_path:
        return _cookie_from_har(har_path)
    if cookies_path:
        return _cookie_from_file(cookies_path)
    env = os.environ.get("CBS_COOKIES") or os.environ.get("CBS_COOKIE")
    if env:
        return env.strip()
    for name in COOKIE_FILE_CANDIDATES:
        p = Path(name)
        if p.is_file():
            return _cookie_from_file(p)
    raise FileNotFoundError(
        "No CBS cookies. Pass --har PATH, --cookies PATH, set CBS_COOKIES, "
        "or write a gitignored cbs_cookies.txt (Cookie header or name=value lines)."
    )


def _cookie_from_file(path: str | os.PathLike) -> str:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"empty cookie file: {path}")
    if text.lower().startswith("cookie:"):
        return text.split(":", 1)[1].strip()
    # Netscape cookie file
    if text.lstrip().startswith("# Netscape") or "\t" in text.splitlines()[0]:
        pairs = []
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) >= 7:
                pairs.append(f"{cols[5]}={cols[6]}")
        if pairs:
            return "; ".join(pairs)
    # name=value per line, or a single Cookie header
    if "\n" in text:
        pairs = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                pairs.append(line if ";" not in line else line)
        if pairs and all(p.count("=") >= 1 and "\n" not in p for p in pairs):
            return "; ".join(pairs)
    return text


def _cookie_from_har(path: str | os.PathLike) -> str:
    har = json.loads(Path(path).read_text(encoding="utf-8"))
    best = ""
    for entry in har.get("log", {}).get("entries", []):
        url = entry.get("request", {}).get("url") or ""
        if "football.cbssports.com" not in url:
            continue
        for h in entry.get("request", {}).get("headers", []):
            if h.get("name", "").lower() == "cookie" and h.get("value"):
                val = h["value"]
                if len(val) > len(best):
                    best = val
    if not best:
        raise ValueError(f"no Cookie header for cbssports.com in HAR: {path}")
    return best


class AuthError(RuntimeError):
    pass


class CBSClient:
    def __init__(self, cookie: str, user_agent: str | None = None):
        self.cookie = cookie
        self.user_agent = user_agent or DEFAULT_UA

    def get(self, path: str, xhr: bool = False, timeout: int = 30) -> str:
        url = path if path.startswith("http") else HOST + path
        headers = {
            "User-Agent": self.user_agent,
            "Cookie": self.cookie,
            "Referer": HOST + "/stats/stats-main",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html, */*; q=0.01" if xhr else "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        if xhr:
            headers["X-Requested-With"] = "XMLHttpRequest"
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=timeout, context=_CTX) as resp:
                raw = resp.read()
                enc = (resp.headers.get("Content-Encoding") or "").lower()
                if enc == "gzip" or raw[:2] == b"\x1f\x8b":
                    try:
                        raw = gzip.decompress(raw)
                    except OSError:
                        pass
                text = raw.decode("utf-8", "replace")
                final = resp.geturl()
        except HTTPError as e:
            raise AuthError(f"HTTP {e.code} for {path}") from e
        except URLError as e:
            raise ConnectionError(f"network error for {path}: {e.reason}") from e
        if _looks_like_login(text, final):
            raise AuthError(
                "CBS returned a login/paywall page. Export a fresh HAR or paste new cookies."
            )
        return text

    def stats_report(
        self,
        pool: str,
        positions: str,
        period: str = "2025",
        kind: str = "stats",
        cats: str = "standard",
        print_rows: int = 9999,
    ) -> str:
        path = (
            f"/stats/data-stats-report/{pool}:{positions}/{period}:p/{cats}/{kind}"
            f"?print_rows={print_rows}"
        )
        return self.get(path, xhr=True)

    def team_page(self, team_id: str) -> str:
        return self.get(f"/teams/{team_id}")

    def depth_chart(self) -> str:
        return self.get("/players/depth-chart")

    def standings_page(self) -> str:
        return self.get("/standings/overall")


def _looks_like_login(text: str, final_url: str) -> bool:
    u = (final_url or "").lower()
    if any(x in u for x in ("/login", "/signin", "account.cbs", "id.cbs")):
        return True
    if "playerLink" in text or "playerpage/" in text:
        return False
    if re.search(r"sign in|log in|enter your password", text, re.I):
        return True
    return False


_FOR_WEEK = re.compile(r"for Week (\d+)", re.I)


def current_week_from_stats_html(html: str) -> int | None:
    """CBS's own idea of "this week", read off its `period=tp` ("this period")
    stats response — no NFL calendar math, no season-start date to maintain.

    That response's injury tooltips are CBS's own copy, e.g. "Questionable
    for Week 3 at Washington" or "Out for Week 3, set for more tests" —
    always phrased as "... for Week N" for the week the designation applies
    to (an "Expected Return - Week N" phrase for a different, future week
    does not match "for Week", so it's not counted). Across a full position
    pool this is a very lopsided, redundant signal — on a real pull, 112
    "for Week 3" mentions vs 2 stray "for Week 6" (a long-term IR note) —
    so the most common week number wins. Returns None if the pool has no
    injury tooltips to read (e.g. a bye week with nobody hurt, or CBS
    returned a page this doesn't recognize) — callers should fall back.
    """
    counts = Counter(int(n) for n in _FOR_WEEK.findall(html))
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def parse_stats_players(html: str) -> list[dict]:
    """Parse a data-stats-report HTML table into player dicts."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I)
    headers: list[str] = []
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if "sortableColumn" in row and re.search(r">Player<", row, re.I):
            headers = [plain(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", row, re.S | re.I)]
            continue
        if "playerpage/" not in row or "playerPositionAndTeam" not in row:
            continue
        rec = _parse_player_row(row, headers)
        if not rec:
            continue
        key = rec.get("cbs_id") or rec["player"]
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def parse_team_roster(html: str, owner: str) -> list[dict]:
    """Parse /teams/{id} into roster rows with lineup slot."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I)
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if "playerpage/" not in row or "playerPositionAndTeam" not in row:
            continue
        rec = _parse_player_row(row, headers=[])
        if not rec:
            continue
        rec["owner"] = owner
        rec["status"] = "rostered"
        key = rec.get("cbs_id") or rec["player"]
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def _parse_player_row(row: str, headers: list[str]) -> dict | None:
    # Prefer the real player anchor; skip news "Update" playerLink clones.
    name = ""
    cbs_id = ""
    for m in re.finditer(
        r"<a[^>]*href=['\"][^'\"]*playerpage/(\d+)['\"][^>]*>([^<]+)</a>",
        row,
        re.I,
    ):
        tag_start = row[max(0, m.start() - 80) : m.start()]
        if "subtab=" in tag_start or 'subtab="' in m.group(0):
            continue
        cbs_id, name = m.group(1), unescape(m.group(2)).strip()
        break
    if not name:
        m = re.search(r"playerpage/(\d+)[^>]*>([^<]+)<", row)
        if not m:
            return None
        cbs_id, name = m.group(1), unescape(m.group(2)).strip()
    pt = re.search(r"playerPositionAndTeam['\"]>([^<]+)<", row)
    pos, nfl = split_pos_team(pt.group(1) if pt else "")
    owner = ""
    status = ""
    m_own = re.search(r'title="Rostered By ([^"]+)"', row)
    if m_own:
        owner = unescape(m_own.group(1)).strip()
        status = "rostered"
    elif re.search(r'title="On Waivers"', row) or re.search(r">W\s*\(", row):
        status = "waivers"
    slot = ""
    m_slot = re.search(r'class="playerPosition">([^<]*)<', row)
    if m_slot:
        slot = unescape(m_slot.group(1)).strip()
    rec = {
        "player": name,
        "team": nfl,
        "pos": pos,
        "owner": owner,
        "status": status,
        "slot": slot,
        "cbs_id": cbs_id,
        "key": norm(name),
    }
    if headers:
        cells = [plain(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
        # First cells are Action / Avail / Player — zip remaining onto leftover headers.
        skip = 0
        for h in headers:
            hl = h.lower()
            if hl in {"action", "avail", "player"} or skip < 3 and hl in {"", "action"}:
                skip += 1
            else:
                break
        stat_headers = [h for h in headers[skip:] if h]
        stat_cells = cells[skip:]
        seen: dict[str, int] = {}
        for h, v in zip(stat_headers, stat_cells):
            n = seen.get(h, 0) + 1
            seen[h] = n
            rec[h if n == 1 else f"{h}_{n}"] = v
    return rec


def parse_standings(html: str) -> list[dict]:
    """Parse /standings/overall into rank-ordered team totals.

    This is a cumulative-total-points league (no head-to-head, no
    playoffs) — the standings ARE just each team's season GBFL total, and
    reverse standings order is exactly Tuesday's waiver priority.
    Confirmed live: "1 BUSSONE 67.5 11.5 79.0 39.0 0.0  2 THROBBER 52.0
    7.0 59.0 25.5 20.0  ..." (rank, team, offensive, defensive, total,
    dif, behind).
    """
    text = plain(html)
    known = set(TEAM_IDS.values())
    rows: list[dict] = []
    for m in re.finditer(r"(\d+)\s+([A-Z0-9/]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", text):
        rank, team, off, deff, total, _dif, _behind = m.groups()
        if team not in known:
            continue
        rows.append({"rank": int(rank), "team": team, "offensive": float(off), "defensive": float(deff), "total": float(total)})
    rows.sort(key=lambda r: r["rank"])
    return rows


def parse_depth_chart(html: str) -> list[dict]:
    """Best-effort ordered names from CBS league depth-chart HTML."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I)
    out: list[dict] = []
    current_pos = ""
    rank_by_team_pos: dict[tuple[str, str], int] = {}
    for row in rows:
        header = re.search(r"\b(QB|RB|WR|TE|FB|K|PK|P)\b", plain(row))
        names = []
        for m in re.finditer(
            r"<a[^>]*href=['\"][^'\"]*playerpage/(\d+)['\"][^>]*>([^<]+)</a>",
            row,
            re.I,
        ):
            names.append((m.group(1), unescape(m.group(2)).strip()))
        if header and not names:
            current_pos = header.group(1)
            if current_pos == "PK":
                current_pos = "K"
            continue
        pos = current_pos
        if header and names:
            pos = header.group(1)
            if pos == "PK":
                pos = "K"
        if not names:
            continue
        pt = re.search(r"playerPositionAndTeam['\"]>([^<]+)<", row)
        _, team = split_pos_team(pt.group(1) if pt else "")
        for cbs_id, name in names:
            key = (team or "_", pos)
            rank_by_team_pos[key] = rank_by_team_pos.get(key, 0) + 1
            rank = rank_by_team_pos[key]
            label = f"{team} {pos}{rank}".strip() if team else f"{pos}{rank}"
            out.append(
                {
                    "player": name,
                    "team": team,
                    "pos": pos,
                    "cbs_id": cbs_id,
                    "depth_rank": rank,
                    "role_note": label,
                    "key": norm(name),
                }
            )
    return out


PUBLIC_DEPTH_POS = ("QB", "RB", "WR", "TE", "K")
PUBLIC_DEPTH_URL = "https://www.cbssports.com/fantasy/football/depth-chart/{pos}/"


def fetch_public_html(url: str, timeout: int = 30) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
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


def parse_public_depth_chart(html: str, pos: str) -> list[dict]:
    """Team-relative ranks from cbssports.com/fantasy/football/depth-chart/{POS}/."""
    pos = (pos or "").upper()
    if pos == "PK":
        pos = "K"
    blocks = re.findall(r'<tr class="TableBase-bodyTr">(.*?)</tr>', html, re.S)
    if not blocks:
        blocks = re.findall(r"<tr[^>]*TableBase-bodyTr[^>]*>(.*?)</tr>", html, re.S)
    out: list[dict] = []
    for row in blocks:
        tm = re.search(r"/nfl/teams/([A-Z]{2,3})/", row)
        team = tm.group(1) if tm else ""
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        rank = 0
        seen: set[str] = set()
        for td in tds[1:]:
            players = re.findall(
                r'<span class="CellPlayerName--long">.*?<a href="/nfl/players/(\d+)/[^"]+"[^>]*>([^<]+)</a>',
                td,
                re.S,
            )
            if not players:
                seen_td: set[str] = set()
                players = []
                for m in re.finditer(r"/nfl/players/(\d+)/([^/]+)/", td):
                    if m.group(1) in seen_td:
                        continue
                    seen_td.add(m.group(1))
                    slug = m.group(2).replace("-", " ").title()
                    players.append((m.group(1), slug))
            for cbs_id, name in players:
                if cbs_id in seen:
                    continue
                seen.add(cbs_id)
                rank += 1
                name = unescape(name).strip()
                label = f"{team} {pos}{rank}".strip() if team else f"{pos}{rank}"
                tip_m = re.search(
                    rf'/nfl/players/{re.escape(cbs_id)}/[^"]+"[^>]*>.*?</a>\s*'
                    rf'<span class="CellPlayerName-icon icon-moon-injury">.*?'
                    rf'<div class="Tablebase-tooltipInner">\s*([^<]+)',
                    td,
                    re.S,
                )
                injury_note = unescape(tip_m.group(1)).strip() if tip_m else ""
                out.append(
                    {
                        "player": name,
                        "team": team,
                        "pos": pos,
                        "cbs_id": cbs_id,
                        "depth_rank": rank,
                        "role_note": label,
                        "injury_note": injury_note,
                        "key": norm(name),
                    }
                )
    return out


def pull_public_depth_charts() -> list[dict]:
    """Fetch official CBS fantasy depth charts (no league cookies)."""
    out: list[dict] = []
    for pos in PUBLIC_DEPTH_POS:
        html = fetch_public_html(PUBLIC_DEPTH_URL.format(pos=pos))
        out.extend(parse_public_depth_chart(html, pos))
    return out


def is_free_agent(rec: dict) -> bool:
    if rec.get("status") == "waivers":
        return True
    if rec.get("status") == "rostered" or rec.get("owner"):
        return False
    return True
