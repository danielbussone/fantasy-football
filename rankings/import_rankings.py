"""Reimport dynasty+redraft into combined.csv without changing scoring math."""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from rankings.weekly_fp import import_weekly_files

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "rankings_as_of.txt"


def write_stamp(when: str | None = None) -> str:
    when = when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    STAMP.write_text(when + "\n", encoding="utf-8")
    return when


def read_stamp() -> str:
    if STAMP.exists():
        return STAMP.read_text(encoding="utf-8").strip()
    csvp = ROOT / "combined.csv"
    if csvp.exists():
        return datetime.fromtimestamp(csvp.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ""


def import_files(dynasty: Path | None = None, redraft: Path | None = None) -> str:
    if dynasty:
        shutil.copyfile(dynasty, ROOT / "dynasty.csv")
    if redraft:
        shutil.copyfile(redraft, ROOT / "redraft.csv")
    subprocess.check_call([sys.executable, str(ROOT / "merge.py")], cwd=str(ROOT))
    return write_stamp()


def import_weekly(paths: list[Path], *, fallback_week: int = 1) -> dict:
    """Write week_fp.csv only. Does not run merge.py or touch combined.csv."""
    return import_weekly_files(paths, fallback_week=fallback_week)
