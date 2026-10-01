"""nflverse data from github.com/nflverse/nflverse-data releases (free, no auth).

Weekly player/team stats, snap counts, play-by-play, schedules and the
player ID map, cached under nflverse_cache/ (gitignored). A past season is
immutable once cached; the current season re-downloads when older than
max_age_hours. A failed or empty download never replaces a good cached file.

Play-by-play is ~19 MB gzipped per season, so it's stream-parsed once into
pbp_slim_{season}.csv holding only the columns scoring and usage need.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "nflverse_cache"
META_PATH = ROOT / "nflverse_meta.json"
BASE = "https://github.com/nflverse/nflverse-data/releases/download"
CURRENT_SEASON = 2026
_CTX = ssl.create_default_context()

SEASONAL = {
    "stats_player_week": ("stats_player", "stats_player_week_{season}.csv.gz"),
    "stats_team_week": ("stats_team", "stats_team_week_{season}.csv.gz"),
    "snap_counts": ("snap_counts", "snap_counts_{season}.csv.gz"),
    "pbp": ("pbp", "play_by_play_{season}.csv.gz"),
    "injuries": ("injuries", "injuries_{season}.csv.gz"),
}
STATIC = {
    "players": ("players", "players.csv.gz"),
    "games": ("schedules", "games.csv.gz"),
}

PBP_PLAY_TYPES = frozenset({"pass", "run", "field_goal", "extra_point", "kickoff", "punt"})
PBP_SLIM_FIELDS = [
    "game_id", "season", "week", "posteam", "defteam", "home_team", "away_team",
    "play_type", "yards_gained", "yardline_100", "air_yards",
    "pass_attempt", "rush_attempt", "complete_pass", "sack", "interception",
    "fumble_lost", "safety", "qb_dropback", "qb_scramble",
    "touchdown", "pass_touchdown", "rush_touchdown", "return_touchdown",
    "td_team", "td_player_id", "return_yards",
    "passer_player_id", "receiver_player_id", "rusher_player_id", "kicker_player_id",
    "field_goal_result", "kick_distance", "extra_point_result",
    "two_point_attempt", "two_point_conv_result",
    "fumble_recovery_1_team", "fumble_recovery_1_yards", "posteam_score_post", "defteam_score_post",
]


def _path(kind: str, season: int | None) -> Path:
    if kind in SEASONAL:
        return CACHE / SEASONAL[kind][1].format(season=int(season))
    return CACHE / STATIC[kind][1]


def _url(kind: str, season: int | None) -> str:
    tag, name = SEASONAL[kind] if kind in SEASONAL else STATIC[kind]
    return f"{BASE}/{tag}/{name.format(season=season)}"


def _download(url: str, dest: Path, timeout: int = 120) -> None:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, context=_CTX, timeout=timeout) as resp:
        data = resp.read()
    if len(data) < 100 or data[:2] != b"\x1f\x8b":
        raise ValueError(f"not a usable gzip download ({len(data)} bytes): {url}")
    gzip.decompress(data)  # raises on a truncated download, so a cut-off file is never cached
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)


def _fresh(path: Path, season: int | None, max_age_hours: float) -> bool:
    if not path.exists():
        return False
    if season is not None and int(season) < CURRENT_SEASON:
        return True
    return (time.time() - path.stat().st_mtime) < max_age_hours * 3600


def ensure(kind: str, season: int | None = None, max_age_hours: float = 12) -> Path:
    """Cached path for `kind` (and season), downloading it if missing or stale."""
    path = _path(kind, season)
    if _fresh(path, season, max_age_hours):
        return path
    try:
        _download(_url(kind, season), path)
    except Exception:
        if path.exists():
            return path
        raise
    return path


def _read_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def slim_pbp(season: int, max_age_hours: float = 12) -> Path:
    src = ensure("pbp", season, max_age_hours)
    out = CACHE / f"pbp_slim_{int(season)}.csv"
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    tmp = out.with_suffix(".csv.tmp")
    with gzip.open(src, "rt", encoding="utf-8", newline="") as f_in, tmp.open("w", encoding="utf-8", newline="") as f_out:
        reader = csv.DictReader(f_in)
        writer = csv.DictWriter(f_out, fieldnames=PBP_SLIM_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in reader:
            if r.get("season_type") != "REG":
                continue
            if r.get("play_type") not in PBP_PLAY_TYPES and r.get("two_point_attempt") != "1":
                continue
            writer.writerow(r)
    os.replace(tmp, out)
    return out


_MEMO: dict[tuple, list[dict]] = {}


def load(kind: str, season: int | None = None, max_age_hours: float = 12) -> list[dict]:
    """Rows of a cached nflverse file ("pbp" returns the slim play-by-play)."""
    key = (kind, season)
    if key in _MEMO:
        return _MEMO[key]
    if kind == "pbp":
        with slim_pbp(int(season), max_age_hours).open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    else:
        rows = _read_gz(ensure(kind, season, max_age_hours))
    _MEMO[key] = rows
    return rows


def clear_memo() -> None:
    _MEMO.clear()


def pull(seasons: list[int], max_age_hours: float = 12) -> dict:
    """Download everything the metrics need for `seasons`. Returns {file: ok/error}."""
    result: dict[str, str] = {}
    for kind in STATIC:
        try:
            ensure(kind, None, max_age_hours)
            result[kind] = "ok"
        except Exception as e:
            result[kind] = f"error: {e}"
    for season in seasons:
        for kind in SEASONAL:
            label = f"{kind}_{season}"
            try:
                if kind == "pbp":
                    slim_pbp(season, max_age_hours)
                else:
                    ensure(kind, season, max_age_hours)
                result[label] = "ok"
            except Exception as e:
                result[label] = f"error: {e}"
    clear_memo()
    return result


def latest_week(season: int = CURRENT_SEASON) -> int:
    """Last regular-season week with player stats in the cached weekly file (0 if none)."""
    try:
        weeks = [int(r["week"]) for r in load("stats_player_week", season) if r.get("season_type") == "REG"]
    except Exception:
        return 0
    return max(weeks, default=0)


def write_meta(result: dict, season: int = CURRENT_SEASON) -> dict:
    ok = all(v == "ok" for v in result.values())
    meta = {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "season": season,
            "latest_week": latest_week(season), "ok": ok,
            "errors": {k: v for k, v in result.items() if v != "ok"}}
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def read_meta() -> dict:
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def refresh(season: int = CURRENT_SEASON, max_age_hours: float = 1.5) -> dict:
    """Pull the current season (plus the static files) and record when. Never raises.
    A partial failure still records what is cached; `ok` says whether everything came down."""
    try:
        result = pull([season], max_age_hours)
        return write_meta(result, season)
    except Exception as e:  # a bad pull must not take the caller down
        return {"ok": False, "errors": {"pull": str(e)}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download/cache nflverse data.")
    ap.add_argument("--seasons", type=int, nargs="+", default=[2023, 2024, 2025, CURRENT_SEASON])
    ap.add_argument("--max-age-hours", type=float, default=12)
    args = ap.parse_args(argv)
    result = pull(args.seasons, args.max_age_hours)
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0 if all(v == "ok" for v in result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
