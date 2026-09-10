"""Local API for the in-season app. CBS cookies stay on disk, never in git."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.assemble import build_week, dump_fixture
from rankings.import_rankings import import_files, import_weekly, read_stamp

app = FastAPI(title="GBFL in-season")
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
    weekly_weight: float = 0.20,
) -> dict:
    return build_week(
        week=week,
        board_weight=board_weight,
        mock=mock,
        allow_injured=allow_injured,
        weekly_weight=weekly_weight,
    )


@app.get("/api/health")
def health():
    return {"ok": True, "rankings_as_of": read_stamp()}


@app.get("/api/week")
@app.get("/week")
def week(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    allow_injured: bool = False,
    weekly_weight: float = 0.20,
):
    return JSONResponse(
        _week(week, board_weight, mock, allow_injured, weekly_weight),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/roster")
@app.get("/roster")
def roster(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    allow_injured: bool = False,
    weekly_weight: float = 0.20,
):
    w = _week(week, board_weight, mock, allow_injured, weekly_weight)
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
    objective: str = Query("p50"),
    weekly_weight: float = 0.20,
):
    w = _week(week, board_weight, mock, allow_injured, weekly_weight)
    key = f"lineup_{objective}" if f"lineup_{objective}" in w else None
    lineup = (w.get("lineups") or {}).get(objective) or w.get(key) or w["lineup_p50"]
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
def waivers(week: int = 1, board_weight: float = 0.35, mock: bool = False, weekly_weight: float = 0.20):
    w = _week(week, board_weight, mock, False, weekly_weight)
    return {"week": w["week"], "waivers": w["waivers"]}


@app.get("/api/projections")
@app.get("/projections")
def projections(week: int = 1):
    w = _week(week, 0.35, False, False)
    rows = []
    for p in w["roster"] + (w.get("fa_sample") or []):
        rows.append({"player": p.get("player"), "pos": p.get("pos"), "proj": p.get("proj")})
    return {"week": w["week"], "format_note": w["format_note"], "projections": rows}


@app.post("/api/refresh")
@app.post("/refresh")
def refresh(har: str | None = None, cookies: str | None = None):
    from cbs_pull import main as pull_main
    import sys as _sys

    argv = ["cbs_pull.py"]
    if har:
        argv += ["--har", har]
    if cookies:
        argv += ["--cookies", cookies]
    old = _sys.argv
    _sys.argv = argv
    try:
        code = pull_main()
    finally:
        _sys.argv = old
    if code:
        return JSONResponse({"ok": False, "code": code}, status_code=400)
    return {"ok": True, "week": build_week()}


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
            dest = tmp / (f.filename or f"weekly_{i}.csv")
            dest.write_bytes(await f.read())
            paths.append(dest)
        out["week_fp"] = import_weekly(paths, fallback_week=week)
    if not dpath and not rpath and not weekly_files:
        return JSONResponse({"ok": False, "error": "no files"}, status_code=400)
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
    dest = tmp / (har.filename or "espn.har")
    dest.write_bytes(await har.read())
    from projections.espn import import_espn_har

    meta = import_espn_har(dest, week=week)
    return {"ok": True, "espn": meta}


@app.post("/api/fixture/dump")
def fixture_dump():
    p = dump_fixture()
    return {"ok": True, "path": str(p)}
