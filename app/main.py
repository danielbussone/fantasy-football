"""Local API for the in-season app. CBS cookies stay on disk, never in git."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.assemble import build_week, clear_proj_cache, dump_fixture, rescore_waivers, week_for_report
from app.auto_refresh import DEFAULT_INTERVAL_SECONDS, auto_refresh_loop
from cbs_pull import read_current_week
from lineup.start_sit import DEFAULT_OBJECTIVE
from rankings.import_rankings import import_files, import_weekly, read_stamp

# A no-op if something else (pytest, an embedding process) already added a
# handler — but under plain `uvicorn app.main:app`, nothing does, and
# without this the auto-refresh loop's own logger.info/.warning calls have
# no handler anywhere in their chain and are silently dropped, defeating
# the point of logging "when an update happened".
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("gbfl.api")

# GBFL_AUTO_REFRESH=0 disables the background CBS/ESPN refresh loop entirely
# (e.g. for tests, or a read-only preview instance). GBFL_AUTO_REFRESH_SECONDS
# overrides the default interval.
AUTO_REFRESH_ENABLED = os.environ.get("GBFL_AUTO_REFRESH", "1") not in ("0", "false", "False")
AUTO_REFRESH_SECONDS = float(os.environ.get("GBFL_AUTO_REFRESH_SECONDS") or DEFAULT_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = None
    if AUTO_REFRESH_ENABLED:
        task = asyncio.create_task(auto_refresh_loop(AUTO_REFRESH_SECONDS))
        logger.info("auto-refresh loop started (every %ss)", AUTO_REFRESH_SECONDS)
    try:
        yield
    finally:
        if task:
            task.cancel()


app = FastAPI(title="GBFL in-season", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _week(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    allow_injured: bool = False,
    weekly_weight: float = 0.0,
    espn_mix: float = 0.5,
) -> dict:
    return build_week(
        week=week,
        board_weight=board_weight,
        mock=mock,
        allow_injured=allow_injured,
        weekly_weight=weekly_weight,
        espn_mix=espn_mix,
    )


@app.get("/api/health")
def health():
    return {"ok": True, "rankings_as_of": read_stamp()}


@app.get("/api/current-week")
def current_week():
    """CBS's own idea of "this week" (see cbs_client.current_week_from_stats_html),
    last recorded by a CBS pull — manual or the background auto-refresh loop.
    The UI uses this to default the week picker; it's a starting point, not
    a lock, since `week` is None until the first successful pull.
    """
    return read_current_week()


@app.get("/api/week")
@app.get("/week")
def week(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    allow_injured: bool = False,
    weekly_weight: float = 0.0,
    espn_mix: float = 0.5,
):
    return JSONResponse(
        _week(week, board_weight, mock, allow_injured, weekly_weight, espn_mix),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/roster")
@app.get("/roster")
def roster(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    allow_injured: bool = False,
    weekly_weight: float = 0.0,
    espn_mix: float = 0.5,
):
    w = _week(week, board_weight, mock, allow_injured, weekly_weight, espn_mix)
    return {
        "week": w["week"],
        "team": w["team"],
        "rankings_as_of": w["rankings_as_of"],
        "injury_as_of": w["injury_as_of"],
        "roster": w["roster"],
    }


@app.get("/api/lineup")
@app.get("/lineup")
def lineup(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    allow_injured: bool = False,
    objective: str = Query(DEFAULT_OBJECTIVE),
    weekly_weight: float = 0.0,
    espn_mix: float = 0.5,
):
    w = _week(week, board_weight, mock, allow_injured, weekly_weight, espn_mix)
    key = f"lineup_{objective}" if f"lineup_{objective}" in w else None
    lineup = (w.get("lineups") or {}).get(objective) or w.get(key) or w.get("lineup_mean") or w["lineup_p50"]
    return {
        "week": w["week"],
        "objective": objective,
        "allow_injured": allow_injured,
        "lineup": lineup,
        "lineups": w.get("lineups"),
        "lineup_p50": w["lineup_p50"],
        "lineup_p10": w["lineup_p10"],
    }


@app.get("/api/waivers")
@app.get("/waivers")
def waivers(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    weekly_weight: float = 0.0,
    espn_mix: float = 0.5,
):
    return {
        "week": week,
        "waivers": rescore_waivers(
            week=week,
            board_weight=board_weight,
            mock=mock,
            espn_mix=espn_mix,
            weekly_weight=weekly_weight,
        ),
    }


@app.get("/api/projections")
@app.get("/projections")
def projections(week: int = 1, espn_mix: float = 0.5):
    w = _week(week, 0.35, False, False, espn_mix=espn_mix)
    rows = []
    for p in w["roster"] + (w.get("fa_sample") or []):
        rows.append({"player": p.get("player"), "pos": p.get("pos"), "proj": p.get("proj")})
    return {"week": w["week"], "format_note": w["format_note"], "projections": rows}


@app.post("/api/refresh")
@app.post("/refresh")
def refresh(har: str | None = None, cookies: str | None = None, week: int = 1):
    from cbs_pull import main as pull_main

    argv = ["--week", str(int(week))]
    if har:
        argv += ["--har", har]
    if cookies:
        argv += ["--cookies", cookies]
    code = pull_main(argv)
    if code:
        return JSONResponse({"ok": False, "code": code}, status_code=400)
    from nflverse.pull import refresh as refresh_nflverse

    refresh_nflverse()  # best-effort: grades just show "—" if it fails
    clear_proj_cache()
    return {"ok": True, "week": build_week(week=week)}


@app.post("/api/rankings/import")
async def rankings_import(
    dynasty: UploadFile | None = File(None),
    redraft: UploadFile | None = File(None),
    weekly: list[UploadFile] | None = File(None),
    week: int = Query(1),
):
    dpath = None
    rpath = None
    tmp = ROOT / ".import_tmp"
    tmp.mkdir(exist_ok=True)
    out: dict = {"ok": True}
    if dynasty:
        dpath = tmp / "dynasty.csv"
        dpath.write_bytes(await dynasty.read())
    if redraft:
        rpath = tmp / "redraft.csv"
        rpath.write_bytes(await redraft.read())
    if dpath or rpath:
        out["rankings_as_of"] = import_files(dpath, rpath)
    weekly_files = [f for f in (weekly or []) if f and f.filename]
    if weekly_files:
        paths = []
        for i, f in enumerate(weekly_files):
            # Path(...).name strips any directory components (e.g. "../x")
            # so an uploaded filename can't write outside .import_tmp.
            safe_name = Path(f.filename or "").name or f"weekly_{i}.csv"
            dest = tmp / safe_name
            dest.write_bytes(await f.read())
            paths.append(dest)
        out["week_fp"] = import_weekly(paths, fallback_week=week)
    if not dpath and not rpath and not weekly_files:
        return JSONResponse({"ok": False, "error": "no files"}, status_code=400)
    clear_proj_cache()
    return out


@app.post("/api/espn/import")
async def espn_import(
    har: UploadFile | None = File(None),
    week: int = Query(1),
):
    if not har:
        return JSONResponse({"ok": False, "error": "no HAR"}, status_code=400)
    tmp = ROOT / ".import_tmp"
    tmp.mkdir(exist_ok=True)
    safe_name = Path(har.filename or "").name or "espn.har"
    dest = tmp / safe_name
    dest.write_bytes(await har.read())
    from projections.espn import import_espn_har

    meta = import_espn_har(dest, week=week)
    clear_proj_cache()
    return {"ok": True, "espn": meta}


@app.post("/api/lock")
def lock_week(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    allow_injured: bool = False,
    espn_mix: float = 0.5,
    objective: str = Query(DEFAULT_OBJECTIVE),
):
    from report.snapshot import snapshot_from_payload, write_snapshot

    payload = week_for_report(
        week,
        board_weight=board_weight,
        mock=mock,
        espn_mix=espn_mix,
        allow_injured=allow_injured,
    )
    snap = snapshot_from_payload(payload, objective=objective)
    path = write_snapshot(snap)
    return {
        "ok": True,
        "week": int(week),
        "path": str(path),
        "locked_at": snap.get("locked_at"),
        "n": len(snap.get("players") or {}),
    }


@app.get("/api/report")
def report(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    allow_injured: bool = False,
    espn_mix: float = 0.5,
):
    from report.week_card import build_report

    return JSONResponse(
        build_report(
            week,
            board_weight=board_weight,
            espn_mix=espn_mix,
            mock=mock,
            allow_injured=allow_injured,
        ),
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/fixture/dump")
def fixture_dump():
    p = dump_fixture()
    return {"ok": True, "path": str(p)}
