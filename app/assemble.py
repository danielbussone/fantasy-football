"""Build the week payload the UI consumes (fixture or live API)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from cbs_client import MY_TEAM, TEAM_IDS, norm
from lineup.start_sit import ACTIVE_MAX, ACTIVE_MIN, OBJECTIVES, ROSTER_CAPS, apply_injury_proj, optimize
from news.injuries import from_cbs_slots, from_depth_tooltip, notes_for_week
from projections.espn import load_espn, lookup_espn, read_espn_meta, stamp_line as espn_stamp
from projections.weekly import blend_espn, breakout_marker, prior_for, project_player
from rankings.import_rankings import read_stamp
from rankings.weekly_fp import apply_weekly_shift, attach_weekly, index_weekly, read_meta, stamp_line as fp_stamp
from waiver.suggest import load_board, suggest

ROOT = Path(__file__).resolve().parents[1]

MOCK_INJURY = {
    "malik nabers": {
        "player": "Malik Nabers",
        "designation": "Questionable",
        "note": "Mock: limited in Wednesday practice (hamstring). Source placeholder until ESPN refresh.",
        "source": "mock",
        "as_of": "2026-09-09T12:00:00Z",
        "out": False,
    }
}


def _csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


def _notable_specials() -> tuple[set[str], set[str]]:
    ks, dsts = set(), set()
    for season in (2023, 2024, 2025):
        for name in (f"kicker_{season}.csv", f"kicker_{season}_fa.csv"):
            for r in _csv(ROOT / name):
                if r.get("player"):
                    ks.add(norm(r["player"]))
    for r in _csv(ROOT / "dst_history.csv"):
        if r.get("team"):
            dsts.add(norm(r["team"]))
    return ks, dsts


def _depth_map() -> dict:
    by_id, by_name = {}, {}
    for r in _csv(ROOT / "cbs_depth.csv"):
        try:
            rank = int(r.get("depth_rank") or 0)
        except ValueError:
            rank = 0
        if rank <= 0:
            continue
        entry = {
            "depth_rank": rank,
            "role_note": r.get("role_note") or "",
            "team": r.get("team") or "",
            "injury_note": r.get("injury_note") or "",
        }
        if r.get("cbs_id"):
            by_id[str(r["cbs_id"])] = entry
        if r.get("player"):
            by_name[norm(r["player"])] = entry
    return {"id": by_id, "name": by_name}


def _lookup_depth(rec: dict, depth: dict) -> dict:
    by_id = depth.get("id") or {}
    by_name = depth.get("name") or {}
    cid = str(rec.get("cbs_id") or "")
    return by_id.get(cid) or by_name.get(norm(rec.get("player") or "")) or {}


def _injury_for(rec: dict, injuries: dict, mock: bool) -> dict | None:
    key = norm(rec["player"])
    note = (injuries.get("notes") or {}).get(key)
    cbs = from_cbs_slots([rec]).get(key)
    depth_tip = from_depth_tooltip(rec.get("injury_note") or "", rec.get("player") or "")
    if cbs and note:
        merged = dict(note)
        merged.update(cbs)
        return merged
    if cbs:
        return cbs
    if note:
        return note
    if depth_tip:
        return depth_tip
    if mock:
        return MOCK_INJURY.get(key)
    return None


def _enrich(
    rec: dict,
    injuries: dict,
    board: dict,
    seed: int,
    depth: dict,
    mock: bool,
    espn_idx: dict | None = None,
    weekly_idx: dict | None = None,
    weekly_weight: float = 0.20,
) -> dict:
    pos = (rec.get("pos") or "").upper()
    team = rec.get("team") or ""
    name = rec["player"]
    d = _lookup_depth(rec, depth)
    if d.get("depth_rank"):
        depth_rank = int(d["depth_rank"])
    elif rec.get("depth_rank"):
        depth_rank = int(rec["depth_rank"])
    else:
        depth_rank = 1 if pos == "DST" else 0
    prior = dict(prior_for(name, pos, team, depth_rank=depth_rank or 1))
    br = board.get(norm(name), {}).get("rank")
    try:
        br_n = int(br) if br not in (None, "") else 999
    except ValueError:
        br_n = 999
    if br_n <= 80 and prior.get("scrim_ypg", 0) < 60 and pos in {"RB", "WR", "TE"}:
        prior = dict(prior)
        prior["scrim_ypg"] = max(float(prior.get("scrim_ypg") or 0), 72)
        if prior.get("source") == "role-prior":
            prior["source"] = "role-prior+board"
    if br_n <= 80 and pos == "QB":
        prior = dict(prior)
        prior["qb_ypg"] = max(float(prior.get("qb_ypg") or 0), 240)
    espn_row = lookup_espn(name, team, pos, espn_idx or {})
    prior = blend_espn(prior, espn_row, weight=0.45)
    rec = dict(rec)
    rec["proj"] = project_player(prior, n=1200, seed=seed)
    rec["depth_rank"] = depth_rank or None
    if pos == "DST":
        rec["role_note"] = f"{team} DST" if team else "DST"
    else:
        rec["role_note"] = d.get("role_note") or rec.get("role_note") or ""
    rec["prior_source"] = prior.get("source") or ""
    rec["injury_note"] = d.get("injury_note") or rec.get("injury_note") or ""
    rec["injury"] = _injury_for(rec, injuries, mock=mock)
    rec["roster_note"] = (injuries.get("roster_notes") or {}).get(norm(name))
    rec = apply_injury_proj(rec)
    rec = attach_weekly(rec, weekly_idx)
    rec = apply_weekly_shift(rec, weekly_weight)
    if espn_row:
        rec["espn_pts"] = espn_row.get("espn_pts") or ""
        rec["has_espn"] = True
        rec["espn_tip"] = _espn_tip(espn_row)
    else:
        rec["espn_pts"] = ""
        rec["has_espn"] = False
        rec["espn_tip"] = ""
    rec["breakout"] = breakout_marker(prior, depth_rank=depth_rank, pos=pos)
    rec["status_changed"] = bool(rec["injury"])
    b = board.get(norm(name))
    rec["board_rank"] = b.get("rank") if b else None
    rec["board_score"] = b.get("score") if b else None
    return rec


def _espn_tip(row: dict) -> str:
    bits = []
    if row.get("espn_pts"):
        bits.append(f"ESPN {row['espn_pts']} pts (their scoring)")
    for label, key in (
        ("pass", "qb_ypg"),
        ("rush", "rush_ypg"),
        ("scrim", "scrim_ypg"),
        ("rec share", "rec_share"),
    ):
        v = row.get(key)
        if v not in (None, ""):
            bits.append(f"{label} {v}")
    return " · ".join(bits)


def build_week(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    allow_injured: bool = False,
    weekly_weight: float = 0.20,
) -> dict:
    roster = _csv(ROOT / "cbs_roster.csv")
    fa = _csv(ROOT / "cbs_fa.csv")
    board = load_board()
    injuries = notes_for_week()
    stamp = read_stamp()
    depth = _depth_map()
    espn_idx = load_espn()
    weekly_idx = index_weekly()
    fp_meta = read_meta()
    espn_meta = read_espn_meta()

    mine = [r for r in roster if r.get("owner") == MY_TEAM]
    must = {
        "chase mclaughlin",
        "tyrone tracy jr",
        "zach charbonnet",
        "wandale robinson",
        "wan'dale robinson",
    }
    kick_names, dst_names = _notable_specials()
    fa_sel = []
    seen = set()
    for r in fa:
        k = norm(r["player"])
        b = board.get(k)
        rank = int(b["rank"]) if b and b.get("rank") else 999
        pos = (r.get("pos") or "").upper()
        notable_k = pos == "K" and (k in kick_names or "mclaughlin" in k)
        notable_d = pos == "DST" and k in dst_names
        if k in must or rank <= 180 or notable_k or notable_d:
            if k not in seen:
                fa_sel.append(r)
                seen.add(k)
    fa_sel = fa_sel[:90]

    mine_e = [
        _enrich(r, injuries, board, i, depth, mock, espn_idx, weekly_idx, weekly_weight)
        for i, r in enumerate(mine)
    ]
    fa_e = [
        _enrich(r, injuries, board, 100 + i, depth, False, espn_idx, weekly_idx, weekly_weight)
        for i, r in enumerate(fa_sel)
    ]

    lineups = {obj: optimize(mine_e, obj, allow_injured=allow_injured) for obj in OBJECTIVES}
    waivers = suggest(
        mine_e,
        fa_e,
        board_weight=board_weight,
        board=board,
        depth=depth,
        rankings_as_of=stamp,
        weekly_weight=weekly_weight,
    )

    g3_path = ROOT / "cbs_stats_3g.csv"
    format_note = (
        "A 46-yard receiving TD is 4 points (base 1 + 46–60 bonus 3). "
        "109 WR yards is only 2 (90–109 bucket) plus a 10-yard TD (1) = 3. "
        "P90 is the long-TD tail, not a CBS projection."
    )

    return {
        "mock": mock,
        "week": week,
        "team": MY_TEAM,
        "team_id": "12",
        "teams": TEAM_IDS,
        "rankings_as_of": stamp,
        "week_fp_as_of": fp_meta.get("as_of") or "",
        "week_fp_stamp": fp_stamp(fp_meta),
        "week_fp_lists": fp_meta.get("lists") or [],
        "espn_as_of": espn_meta.get("as_of") or "",
        "espn_stamp": espn_stamp(espn_meta),
        "espn_n": espn_meta.get("n") or 0,
        "weekly_weight": weekly_weight,
        "injury_as_of": injuries.get("as_of") or "",
        "format_note": format_note,
        "active_min": ACTIVE_MIN,
        "active_max": ACTIVE_MAX,
        "roster_caps": ROSTER_CAPS,
        "data_flags": {
            "stats_3g": g3_path.exists(),
            "depth": (ROOT / "cbs_depth.csv").exists(),
            "injury_notes": bool((injuries.get("notes") or {})),
            "has_3g_usage": any((p.get("proj") or {}).get("usage", {}).get("has_3g") for p in mine_e),
        },
        "roster": mine_e,
        "lineups": lineups,
        "lineup_p50": lineups["p50"],
        "lineup_p10": lineups["p10"],
        "waivers": waivers,
        "fa_sample": fa_e[:40],
    }


def dump_fixture(path: Path | None = None) -> Path:
    path = path or ROOT / "web" / "public" / "fixtures" / "week1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_week(week=1, mock=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
