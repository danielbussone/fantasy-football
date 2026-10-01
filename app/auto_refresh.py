"""Background CBS/ESPN/Vegas refresh while the API process is running.

Runs on a timer inside uvicorn's event loop (started from app/main.py's
lifespan). Every tick: pull CBS (roster/FA/3g/week box scores/depth/
injuries), which also detects and records CBS's current week; try ESPN via
its saved cookie for that same week (no HAR needed unless that cookie has
expired); and pull Vegas's odds board for that week (no auth needed at
all). Every step is best-effort — a missing cookie file, an expired ESPN
cookie, or a network hiccup logs and moves on; it never brings the loop
down, and a failed pull never overwrites good data with nothing.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger("gbfl.auto_refresh")

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INTERVAL_SECONDS = 2 * 60 * 60  # 2 hours
STARTUP_DELAY_SECONDS = 30


def run_auto_refresh_once() -> dict:
    """One refresh pass. Returns a small status dict for logging/testing. Never raises."""
    result: dict = {"cbs": None, "espn": None, "vegas": None, "nflverse": None}

    if (ROOT / "cbs_cookies.txt").exists():
        try:
            import cbs_pull

            code = cbs_pull.main([])  # no --week: cbs_pull auto-detects it
            result["cbs"] = {"ok": code == 0}
            if code != 0:
                logger.warning("auto-refresh: CBS pull exited %s", code)
        except Exception as e:  # a bad pull must not kill the background loop
            logger.warning("auto-refresh: CBS pull raised: %s", e)
            result["cbs"] = {"ok": False, "error": str(e)}
    else:
        result["cbs"] = {"ok": False, "error": "no cbs_cookies.txt"}

    try:
        from nflverse.pull import refresh as refresh_nflverse

        meta = refresh_nflverse()
        result["nflverse"] = {"ok": bool(meta.get("ok")), "latest_week": meta.get("latest_week")}
        if not meta.get("ok"):
            logger.warning("auto-refresh: nflverse pull incomplete: %s", meta.get("errors"))
    except Exception as e:
        logger.warning("auto-refresh: nflverse pull raised: %s", e)
        result["nflverse"] = {"ok": False, "error": str(e)}

    if (ROOT / "espn_cookies.txt").exists():
        try:
            from cbs_pull import read_current_week
            from projections.espn import refresh_espn_from_saved_cookies

            week = int(read_current_week().get("week") or 1)
            result["espn"] = refresh_espn_from_saved_cookies(week)
            if not result["espn"]["ok"]:
                logger.warning("auto-refresh: ESPN pull failed: %s", result["espn"].get("error"))
        except Exception as e:
            logger.warning("auto-refresh: ESPN pull raised: %s", e)
            result["espn"] = {"ok": False, "error": str(e)}
    else:
        result["espn"] = {"ok": False, "error": "no espn_cookies.txt"}

    try:
        from cbs_pull import read_current_week
        from projections.vegas import refresh_vegas

        week = int(read_current_week().get("week") or 1)
        vegas_data = refresh_vegas(week)
        result["vegas"] = {"ok": bool(vegas_data.get("as_of")), "week": week, "n": len(vegas_data.get("teams") or {})}
        if not result["vegas"]["ok"]:
            logger.warning("auto-refresh: Vegas pull returned nothing for week %s", week)
    except Exception as e:
        logger.warning("auto-refresh: Vegas pull raised: %s", e)
        result["vegas"] = {"ok": False, "error": str(e)}

    if (result["cbs"] and result["cbs"].get("ok")) or (result["nflverse"] and result["nflverse"].get("ok")):
        from app.assemble import clear_proj_cache

        clear_proj_cache()

    return result


async def auto_refresh_loop(interval_seconds: float = DEFAULT_INTERVAL_SECONDS) -> None:
    """Run run_auto_refresh_once() forever, off the event loop thread, on a timer."""
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            result = await asyncio.to_thread(run_auto_refresh_once)
            logger.info("auto-refresh: %s", result)
        except Exception as e:  # belt and suspenders — the loop itself must survive
            logger.warning("auto-refresh: unexpected error: %s", e)
        await asyncio.sleep(interval_seconds)
