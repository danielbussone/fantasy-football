"""Build the week payload the UI consumes (fixture or live API)."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from cbs_pull import load_cbs_opps, read_cbs_pull_meta, read_current_week
from cbs_client import MY_TEAM, TEAM_IDS, norm
from metrics import live as live_metrics
from lineup.start_sit import ACTIVE_MAX, ACTIVE_MIN, ALL_OBJECTIVES, DEFAULT_OBJECTIVE, ROSTER_CAPS, apply_injury_proj, injury_tag, optimize
from nflverse.pull import read_meta as read_nflverse_meta
from news.injuries import from_cbs_slots, from_depth_tooltip, notes_for_week
from projections.espn import espn_stat_line, espn_to_sim, hydrate_espn, load_espn, lookup_espn, mix_label, read_espn_meta, snap_espn_mix, stamp_line as espn_stamp
from projections.explosiveness import explosiveness_skew, format_edges as _format_edges, player_td_bonus_table, position_avg_bonus_per_td
from projections.matchups import apply_matchup, league_averages, pass_rush_skew, points_allowed_table, sack_rates
from projections.vegas import apply_vegas, read_vegas_week
from projections.weekly import blend_espn, clear_prior_cache, explain_from_sim, prior_for, project_player
from rankings.import_rankings import read_stamp
from rankings.weekly_fp import attach_weekly, index_weekly, read_meta, stamp_line as fp_stamp
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


def _age_hours(as_of: str) -> float | None:
    if not as_of:
        return None
    try:
        dt = datetime.strptime(as_of, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def _freshness(label: str, as_of: str, *, fresh_hours: float, week_match: bool | None = None, hint: str = "") -> dict:
    """One data source's freshness: fresh (recent, right week), stale (old
    but present), or missing (never pulled, or it's a different week's data).
    """
    age = _age_hours(as_of)
    if age is None or week_match is False:
        status = "missing"
    elif age <= fresh_hours:
        status = "fresh"
    else:
        status = "stale"
    return {
        "label": label,
        "as_of": as_of or "",
        "age_hours": round(age, 1) if age is not None else None,
        "status": status,
        "hint": hint if status != "fresh" else "",
    }


def _espn_as_of_for_week(espn_meta: dict, week: int) -> str:
    by = espn_meta.get("by_week") if isinstance(espn_meta.get("by_week"), dict) else {}
    hit = by.get(str(int(week))) if by else None
    if hit:
        return hit.get("as_of") or ""
    if int(espn_meta.get("week") or 0) == int(week):
        return espn_meta.get("as_of") or ""
    return ""


def build_freshness(
    *,
    week: int,
    injuries: dict,
    espn_meta: dict,
    fp_meta: dict,
    espn_week_match: bool,
    fp_week_match: bool,
    vegas_data: dict | None = None,
    nflverse_meta: dict | None = None,
) -> dict:
    cbs_meta = read_cbs_pull_meta()
    nfl = nflverse_meta if nflverse_meta is not None else read_nflverse_meta()
    cw = read_current_week()
    vegas_data = vegas_data or {}
    return {
        # Each vegas_week{N}.json is already scoped to one week (unlike
        # ESPN/FP's single "last imported" meta), so there's no separate
        # week-match concept here — missing as_of alone means "missing".
        "vegas": _freshness(
            "Vegas",
            vegas_data.get("as_of") or "",
            fresh_hours=48,
            hint="Odds board not pulled for this week yet.",
        ),
        # Fresh needs a recent pull that has the last completed week's games in it.
        "nflverse": {
            **_freshness(
                "nflverse",
                nfl.get("as_of") or "",
                fresh_hours=24,
                week_match=(int(nfl.get("latest_week") or 0) >= int(week) - 1) if nfl.get("as_of") else None,
                hint=f"Usage grades need the last completed week (nflverse has through week {nfl.get('latest_week') or 0}). Click Refresh.",
            ),
            "latest_week": nfl.get("latest_week"),
        },
        "cbs": _freshness(
            "CBS roster/stats",
            cbs_meta.get("as_of") or "",
            fresh_hours=24,
            hint="Click Refresh.",
        ),
        "injuries": _freshness(
            "Injuries",
            injuries.get("as_of") or "",
            fresh_hours=8,
            hint="Click Refresh.",
        ),
        "espn": _freshness(
            "ESPN",
            _espn_as_of_for_week(espn_meta, week),
            fresh_hours=48,
            week_match=espn_week_match,
            hint="Import ESPN (HAR) — the saved cookie may have expired.",
        ),
        "weekly_fp": _freshness(
            "FantasyPros weekly",
            fp_meta.get("as_of") or "",
            fresh_hours=48,
            week_match=fp_week_match,
            hint="Import weekly.",
        ),
        "current_week": {
            "week": cw.get("week"),
            "source": cw.get("source") or "",
            **_freshness("Current week", cw.get("as_of") or "", fresh_hours=24, hint="Click Refresh."),
        },
    }


def _notable_specials() -> tuple[set[str], set[str]]:
    ks, dsts = set(), set()
    # Kickers only from the current season: a name from kicker_2023/2024.csv
    # alone had no 2025 snaps, which usually means they're off an NFL roster
    # entirely (e.g. Justin Tucker, released in 2025) — pulling them in from
    # old history alone surfaced them as waiver adds with a generic default
    # projection standing in for real current-season data.
    for name in ("kicker_2025.csv", "kicker_2025_fa.csv"):
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


def _cbs_opp_for(rec: dict, opps: dict) -> str:
    name = norm(rec.get("player") or "")
    if name and opps.get(name):
        return opps[name]
    team = (rec.get("team") or "").upper()
    if team:
        return opps.get(f"team:{team}") or ""
    return ""


def _raw_opp_team(formatted_opp: str) -> str:
    """"vs. TB" / "at CAR" -> "TB" / "CAR" — cbs_pull.format_cbs_opp's own
    display strings are the only place this repo already tracks a player's
    weekly opponent, so parse the team code back out instead of adding a
    second lookup path."""
    s = (formatted_opp or "").strip()
    if s.startswith("vs. "):
        return s[4:].strip().upper()
    if s.startswith("at "):
        return s[3:].strip().upper()
    return ""


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
    espn_mix: float = 0.5,
    week: int = 1,
    cbs_opps: dict | None = None,
    vegas_data: dict | None = None,
    matchup_table: dict | None = None,
    matchup_avgs: dict | None = None,
    sack_rate_table: dict | None = None,
    explosiveness_table: dict | None = None,
    explosiveness_avgs: dict | None = None,
) -> dict:
    pos = (rec.get("pos") or "").upper()
    team = rec.get("team") or ""
    name = rec["player"]
    opp_team = _raw_opp_team(_cbs_opp_for(rec, cbs_opps or {}))
    d = _lookup_depth(rec, depth)
    if d.get("depth_rank"):
        depth_rank = int(d["depth_rank"])
    elif rec.get("depth_rank"):
        depth_rank = int(rec["depth_rank"])
    else:
        depth_rank = 1 if pos == "DST" else 0
    prior = dict(prior_for(name, pos, team, depth_rank=depth_rank or 1, week=week))
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
    # Vegas before ESPN: ESPN's own week projections already price in the
    # Vegas line, so adjusting the prior with it *after* blending ESPN in
    # would double-count it. Matchup/pass-rush are this repo's own reads on
    # the opponent, so they belong in the same "before ESPN" stage.
    if vegas_data:
        prior = apply_vegas(prior, team, pos, vegas_data)
    if opp_team and pos in {"QB", "RB", "WR", "TE"}:
        if matchup_table is not None and matchup_avgs is not None:
            prior = apply_matchup(prior, opp_team, pos, matchup_table, matchup_avgs)
        if sack_rate_table:
            skew = pass_rush_skew(opp_team, sack_rate_table)
            if skew:
                prior = dict(prior)
                prior["pass_rush_skew"] = skew
    if pos in {"QB", "RB", "WR", "TE"} and explosiveness_table is not None and explosiveness_avgs is not None:
        pl_skew = explosiveness_skew(name, pos, prior, explosiveness_table, explosiveness_avgs)
        if pl_skew:
            prior = dict(prior)
            prior["player_td_skew"] = pl_skew
    espn_row = lookup_espn(name, team, pos, espn_idx or {})
    prior = blend_espn(prior, espn_row, weight=espn_mix)
    rec = dict(rec)
    rec["depth_rank"] = depth_rank or None
    if pos == "DST":
        rec["role_note"] = f"{team} DST" if team else "DST"
    else:
        rec["role_note"] = d.get("role_note") or rec.get("role_note") or ""
    rec["prior_source"] = prior.get("source") or ""
    rec["injury_note"] = d.get("injury_note") or rec.get("injury_note") or ""
    rec["injury"] = _injury_for(rec, injuries, mock=mock)
    rec["roster_note"] = (injuries.get("roster_notes") or {}).get(norm(name))
    v_entry = ((vegas_data or {}).get("teams") or {}).get(team.upper()) if team else None
    rec["vegas_total"] = v_entry.get("total") if v_entry else None
    rec["vegas_kickoff"] = (v_entry.get("kickoff") or "") if v_entry else ""
    rec["vegas_indoor"] = bool(v_entry.get("indoor")) if v_entry else False
    rec["vegas_over_under"] = v_entry.get("over_under") if v_entry else None
    rec["vegas_spread"] = v_entry.get("spread") if v_entry else None
    rec["vegas_opp"] = (v_entry.get("opp") or "") if v_entry else ""
    rec = attach_weekly(rec, weekly_idx, cbs_opp=_cbs_opp_for(rec, cbs_opps or {}))
    rec["prior_source"] = prior.get("source") or rec.get("prior_source") or ""
    rec["matchup_ratio"] = prior.get("matchup_ratio")
    rec["pass_rush_skew"] = prior.get("pass_rush_skew")
    rec["player_td_skew"] = prior.get("player_td_skew")
    rec["proj"] = project_player(prior, n=1200, seed=seed, injury=injury_tag(rec))
    rec = apply_injury_proj(rec)
    if espn_row:
        rec.update(_espn_display(espn_row, pos))
    else:
        rec["espn_pts"] = ""
        rec["has_espn"] = False
        rec["espn_tip"] = ""
        rec["espn_line"] = ""
        rec["espn_gbfl"] = None
        rec["espn_sim"] = None
        rec["espn_explain"] = None
    rec["status_changed"] = bool(rec["injury"])
    b = board.get(norm(name))
    rec["board_rank"] = b.get("rank") if b else None
    rec["board_score"] = b.get("score") if b else None
    return rec


def _espn_display(row: dict, pos: str) -> dict:
    row = hydrate_espn(row)
    sim = espn_to_sim(row)
    explain = explain_from_sim(pos, sim)
    line = espn_stat_line(row, pos)
    tip = line
    if row.get("espn_pts"):
        tip = f"{line} · ESPN {row['espn_pts']} FPTS (their scoring, ignore)" if line else f"ESPN {row['espn_pts']} FPTS (their scoring, ignore)"
    return {
        "espn_pts": row.get("espn_pts") or "",
        "has_espn": True,
        "espn_line": line,
        "espn_gbfl": explain.get("approx_pts"),
        "espn_sim": sim,
        "espn_explain": explain,
        "espn_tip": tip,
    }


def known_out_names(roster_rows: list[dict], injuries: dict) -> frozenset[str]:
    """Normalized names of every player the app's own feeds have out: an Out/IR designation in the
    ESPN injury notes, or sitting in a CBS IR slot. League-wide, not just this roster."""
    out = set()
    for name, note in (injuries.get("notes") or {}).items():
        if note.get("out") or live_metrics.status_from_designation(note.get("designation")) == "Out":
            out.add(norm(name))
    for r in roster_rows:
        if (r.get("slot") or "").strip().lower() in live_metrics.IR_SLOTS:
            out.add(norm(r["player"]))
    return frozenset(out)


MAX_EXTRA_FA = 120  # extra free-agent skill players scored for grades, beyond the board/notable pool


def attach_metrics(recs: list[dict], data: dict, vegas: dict | None) -> dict:
    """Set `grade` (WR/RB/TE), `stream` (DST) and `kick` (K) on enriched records, in place.
    Returns the league-wide DST and kicker stream tables."""
    dst, kick = live_metrics.dst_stream(vegas or {}), live_metrics.kicker_stream(vegas or {})
    for rec in recs:
        pos = (rec.get("pos") or "").upper()
        team = (rec.get("team") or "").upper()
        if pos == "QB" and (rec.get("depth_rank") or 1) > 1:
            # A fill-in who played while the starter was out (Lock for Darnold) projects like a starter
            # on his last few games; the depth chart says he isn't one now, so he gets no grade.
            rec["grade"] = None
        elif pos in {"WR", "RB", "TE", "QB"}:
            rec["grade"] = live_metrics.grade_for(data, rec)
        elif pos == "DST":
            rec["stream"] = dst.get(team)
        elif pos == "K":
            rec["kick"] = kick.get(team)
    return {"dst": dst, "kick": kick}


def grades_payload(data: dict, week: int, roster: list[dict], fa: list[dict], mine_e: list[dict], fa_e: list[dict], streams: dict) -> dict:
    """The `grades` block: availability, trackers and the DST stream card."""
    out = {"available": bool(data.get("available")), "reason": data.get("reason") or "", "as_of": data.get("as_of") or "",
           "decision_week": data.get("decision_week"), "latest_week": data.get("latest_week"),
           "buy_low_active": bool(data.get("buy_low_active")), "replacement": data.get("repl") or {}}
    out.update(live_metrics.trackers(data, week, roster, fa))
    mine_dst = [r for r in mine_e if (r.get("pos") or "").upper() == "DST"]
    free_dst = sorted((r for r in fa_e if (r.get("pos") or "").upper() == "DST" and r.get("stream")),
                      key=lambda r: -r["stream"]["score"])
    keep = lambda r: {"player": r["player"], "team": r["team"], "waiver_status": r.get("status") or "", **(r.get("stream") or {})}
    out["dst"] = {"mine": [keep(r) for r in mine_dst if r.get("stream")], "top": [keep(r) for r in free_dst[:3]]}
    return out


def build_week(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    allow_injured: bool = False,
    weekly_weight: float = 0.0,
    espn_mix: float = 0.5,
) -> dict:
    _ = weekly_weight  # kept on the API; FP ranks are display-only for now
    espn_mix = snap_espn_mix(espn_mix)
    roster = _csv(ROOT / "cbs_roster.csv")
    fa = _csv(ROOT / "cbs_fa.csv")
    board = load_board()
    injuries = notes_for_week()
    stamp = read_stamp()
    depth = _depth_map()
    fp_meta = read_meta()
    espn_meta = read_espn_meta()
    fp_match = int(fp_meta.get("week") or 0) == int(week)
    espn_idx = load_espn(week=week)
    weekly_idx = index_weekly() if fp_match else {}
    cbs_opps = load_cbs_opps(week)
    vegas_data = read_vegas_week(week)
    matchup_table = points_allowed_table()
    matchup_avgs = league_averages(matchup_table)
    sack_rate_table = sack_rates()
    explosiveness_table = player_td_bonus_table()
    explosiveness_avgs = position_avg_bonus_per_td(explosiveness_table)

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
    # Usage grades only help if the pool isn't limited to the draft board: add every free-agent
    # skill player nflverse says has a real offensive role.
    metrics_data = live_metrics.compute(week, out_names=known_out_names(roster, injuries))
    extras = []
    for r in fa:
        k = norm(r["player"])
        if k in seen or (r.get("pos") or "").upper() not in {"WR", "RB", "TE", "QB"}:
            continue
        if live_metrics.wants_in_pool(metrics_data, r):
            extras.append(r)
            seen.add(k)
    fa_sel = fa_sel + extras[:MAX_EXTRA_FA]

    # seed is the week, not a roster/FA-list index: project_player's
    # _stable_seed already hashes in the player name, so an index-based seed
    # bought nothing but made every player's draw reshuffle whenever the
    # roster or FA sample order changed (add/drop, re-sort, etc).
    mine_e = [
        _enrich(
            r, injuries, board, week, depth, mock, espn_idx, weekly_idx, espn_mix, week, cbs_opps, vegas_data,
            matchup_table, matchup_avgs, sack_rate_table, explosiveness_table, explosiveness_avgs,
        )
        for r in mine
    ]
    fa_e = [
        _enrich(
            r, injuries, board, week, depth, False, espn_idx, weekly_idx, espn_mix, week, cbs_opps, vegas_data,
            matchup_table, matchup_avgs, sack_rate_table, explosiveness_table, explosiveness_avgs,
        )
        for r in fa_sel
    ]

    streams = attach_metrics(mine_e + fa_e, metrics_data, vegas_data)
    lineups = {obj: optimize(mine_e, obj, allow_injured=allow_injured) for obj in ALL_OBJECTIVES}
    store_week_projections(week, mock, espn_mix, mine_e, fa_e, board, depth, stamp)
    waivers = suggest(
        mine_e,
        fa_e,
        board_weight=board_weight,
        board=board,
        depth=depth,
        rankings_as_of=stamp,
        week=week,
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
        "week_fp_stamp": fp_stamp(fp_meta, week=week),
        "week_fp_lists": fp_meta.get("lists") or [],
        "espn_as_of": espn_meta.get("as_of") or "",
        "espn_stamp": espn_stamp(espn_meta, week=week),
        "espn_n": espn_meta.get("n") or 0,
        "espn_mix": espn_mix,
        "espn_mix_label": mix_label(espn_mix),
        "weekly_weight": 0,
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
            "espn_week_match": bool(espn_idx),
            "fp_week_match": fp_match,
        },
        "freshness": build_freshness(
            week=week,
            injuries=injuries,
            espn_meta=espn_meta,
            fp_meta=fp_meta,
            espn_week_match=bool(espn_idx),
            fp_week_match=fp_match,
            vegas_data=vegas_data,
        ),
        "grades": grades_payload(metrics_data, week, roster, fa, mine_e, fa_e, streams),
        "roster": mine_e,
        "lineups": lineups,
        "lineup_mean": lineups[DEFAULT_OBJECTIVE],
        "lineup_p50": lineups["p50"],
        "lineup_p10": lineups["p10"],
        "waivers": waivers,
        "fa_sample": fa_e[:40],
        "format_edges": _format_edges(mine_e + fa_e),
    }


# Last enriched roster/FA for this process. Board-slider rescores reuse it
# so Trust this week ↔ Trust board does not rerun the Monte Carlo.
_PROJ_CACHE: dict[tuple, dict] = {}


def _proj_key(week: int, mock: bool, espn_mix: float) -> tuple:
    return (int(week), bool(mock), snap_espn_mix(espn_mix))


def clear_proj_cache() -> None:
    from nflverse.pull import clear_memo

    _PROJ_CACHE.clear()
    clear_prior_cache()
    live_metrics.clear()
    clear_memo()


def store_week_projections(
    week: int,
    mock: bool,
    espn_mix: float,
    mine_e: list,
    fa_e: list,
    board: dict,
    depth: dict,
    stamp: str,
) -> None:
    _PROJ_CACHE[_proj_key(week, mock, espn_mix)] = {
        "mine_e": mine_e,
        "fa_e": fa_e,
        "board": board,
        "depth": depth,
        "stamp": stamp,
    }


def rescore_waivers(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    espn_mix: float = 0.5,
    weekly_weight: float = 0.0,
) -> dict:
    """Re-rank add/drops from cached projections. Cache miss → full build_week."""
    hit = _PROJ_CACHE.get(_proj_key(week, mock, espn_mix))
    if not hit:
        return build_week(
            week=week,
            board_weight=board_weight,
            mock=mock,
            espn_mix=espn_mix,
            weekly_weight=weekly_weight,
        )["waivers"]
    return suggest(
        hit["mine_e"],
        hit["fa_e"],
        board_weight=board_weight,
        board=hit["board"],
        depth=hit["depth"],
        rankings_as_of=hit["stamp"],
        weekly_weight=weekly_weight,
        week=week,
    )


def week_for_report(
    week: int = 1,
    board_weight: float = 0.35,
    mock: bool = False,
    espn_mix: float = 0.5,
    allow_injured: bool = False,
    weekly_weight: float = 0.0,
) -> dict:
    """Reuse cached roster/FA sims when present so Report does not rerun Monte Carlo."""
    _ = weekly_weight
    espn_mix = snap_espn_mix(espn_mix)
    hit = _PROJ_CACHE.get(_proj_key(week, mock, espn_mix))
    if not hit:
        return build_week(
            week=week,
            board_weight=board_weight,
            mock=mock,
            espn_mix=espn_mix,
            allow_injured=allow_injured,
        )
    mine, fa = hit["mine_e"], hit["fa_e"]
    waivers = suggest(
        mine,
        fa,
        board_weight=board_weight,
        board=hit["board"],
        depth=hit["depth"],
        rankings_as_of=hit["stamp"],
        week=week,
    )
    lineups = {obj: optimize(mine, obj, allow_injured=allow_injured) for obj in ALL_OBJECTIVES}
    return {
        "mock": mock,
        "week": week,
        "team": MY_TEAM,
        "espn_mix": espn_mix,
        "espn_mix_label": mix_label(espn_mix),
        "roster": mine,
        "fa_sample": fa[:40],
        "waivers": waivers,
        "lineups": lineups,
        "lineup_mean": lineups[DEFAULT_OBJECTIVE],
        "lineup_p50": lineups["p50"],
        "data_flags": {
            "has_3g_usage": any((p.get("proj") or {}).get("usage", {}).get("has_3g") for p in mine),
        },
    }


def dump_fixture(path: Path | None = None) -> Path:
    path = path or ROOT / "web" / "public" / "fixtures" / "week1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_week(week=1, mock=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    from report.snapshot import fixture_snapshot_path, snapshot_from_payload, write_snapshot

    snap = snapshot_from_payload(payload)
    write_snapshot(snap)
    write_snapshot(snap, fixture_snapshot_path(1))
    return path
