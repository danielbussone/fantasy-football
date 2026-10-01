"""Pre-kickoff lock for the week report card."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbs_client import norm

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = ROOT / "snapshots"
FIXTURE_DIR = ROOT / "web" / "public" / "fixtures"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot_path(week: int) -> Path:
    return SNAP_DIR / f"week{int(week)}_pre.json"


def fixture_snapshot_path(week: int) -> Path:
    return FIXTURE_DIR / f"week{int(week)}_pre.json"


def slim_proj(proj: dict | None) -> dict[str, Any]:
    p = proj or {}
    usage = p.get("usage") or {}
    return {
        "p10": p.get("p10"),
        "p25": p.get("p25"),
        "p50": p.get("p50"),
        "p75": p.get("p75"),
        "p90": p.get("p90"),
        "mean": p.get("mean"),
        "source": p.get("source") or "",
        "usage": {
            "source": usage.get("source") or "",
            "has_3g": bool(usage.get("has_3g")),
            "targets": usage.get("targets"),
            "carries": usage.get("carries"),
            "pass_att": usage.get("pass_att"),
            "receptions": usage.get("receptions"),
            "g3_targets": usage.get("g3_targets"),
            "g3_carries": usage.get("g3_carries"),
        },
    }


def slim_injury(inj: dict | None) -> dict[str, Any] | None:
    if not inj:
        return None
    return {
        "designation": inj.get("designation") or "",
        "out": bool(inj.get("out")),
        "note": inj.get("note") or "",
    }


def slim_player(p: dict) -> dict[str, Any]:
    return {
        "player": p.get("player") or "",
        "pos": (p.get("pos") or "").upper(),
        "team": p.get("team") or "",
        "slot": p.get("slot") or "",
        "proj": slim_proj(p.get("proj")),
        "espn_line": p.get("espn_line") or "",
        "espn_sim": p.get("espn_sim"),
        "injury": slim_injury(p.get("injury")),
        "depth_rank": p.get("depth_rank"),
        "role_note": p.get("role_note") or "",
    }


def _names(rows: list[dict]) -> list[dict[str, Any]]:
    out = []
    for p in rows or []:
        out.append(
            {
                "player": p.get("player") or "",
                "pos": (p.get("pos") or "").upper(),
                "slot": p.get("lineup_slot") or p.get("slot") or "",
            }
        )
    return out


def metrics_block(payload: dict) -> dict[str, Any] | None:
    """What the usage metrics predicted at lock, so the Report tab can score them later:
    per-game predictions, flags, and the DST matchups on offer. None when grades are off."""
    g = payload.get("grades") or {}
    if not g.get("available"):
        return None
    mine = {norm(p.get("player") or "") for p in payload.get("roster") or []}
    grades: dict[str, dict] = {}
    scored = list(payload.get("roster") or []) + list((payload.get("waivers") or {}).get("fa_top") or [])
    for p in scored:
        gr = p.get("grade")
        if not gr:
            continue
        grades[norm(p["player"])] = {"player": p["player"], "pos": (p.get("pos") or "").upper(), "par_ppg": gr["par_ppg"],
                                     "par": gr["par"], "role": gr["role"], "flags": gr["flags"], "exp_games": gr["exp_games"]}
    for c in list(g.get("buy_low") or []) + list(g.get("next_up") or []):
        grades.setdefault(norm(c["player"]), {"player": c["player"], "pos": c["pos"], "par_ppg": c.get("pred_ppg"),
                                              "par": c["par"], "role": c["role"], "flags": c["flags"], "exp_games": c["exp_games"]})
    dst = []
    for p in scored:
        st = p.get("stream")
        if st and (p.get("pos") or "").upper() == "DST":
            dst.append({"player": p["player"], "team": p.get("team") or "", "opp": st["opp"], "opp_total": st["opp_total"],
                        "score": st["score"], "mine": norm(p["player"]) in mine})
    return {
        "decision_week": g.get("decision_week"),
        "grades": grades,
        "next_up": [c["player"] for c in g.get("next_up") or []],
        "buy_low": [c["player"] for c in g.get("buy_low") or []],
        "dst": dst,
    }


def snapshot_from_payload(payload: dict, *, objective: str = "mean") -> dict[str, Any]:
    lineup = (payload.get("lineups") or {}).get(objective) or payload.get("lineup_p50") or {}
    players = {}
    for p in list(payload.get("roster") or []) + list(payload.get("fa_sample") or []):
        name = p.get("player") or ""
        if not name:
            continue
        players[norm(name)] = slim_player(p)
    return {
        "week": int(payload.get("week") or 1),
        "locked_at": _now(),
        "team": payload.get("team") or "BUSSONE",
        "mix": payload.get("espn_mix"),
        "mix_label": payload.get("espn_mix_label") or "",
        "objective": objective,
        "metrics": metrics_block(payload),
        "players": players,
        "lineup_p50": {
            "starters": _names(lineup.get("starters") or []),
            "bench": _names(lineup.get("bench") or []),
            "why": [
                {"player": w.get("player"), "text": w.get("text"), "kind": w.get("kind")}
                for w in (lineup.get("why") or [])
                if w.get("kind") in {"close", "tiebreak"}
            ],
        },
    }


def write_snapshot(snap: dict, path: Path | None = None) -> Path:
    week = int(snap.get("week") or 1)
    path = path or snapshot_path(week)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    return path


def load_snapshot(week: int, *, mock: bool = False) -> dict | None:
    week = int(week)
    if mock:
        for p in (fixture_snapshot_path(week), fixture_snapshot_path(1)):
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        return None
    live = snapshot_path(week)
    if live.exists():
        return json.loads(live.read_text(encoding="utf-8"))
    return None
