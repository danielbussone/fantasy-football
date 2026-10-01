"""Live grades for the app: Role grade, GBFL-PAR, expected games, the high-pick RB
bump and the next-man-up / buy-low flags, plus the DST and kicker stream scores.

Features, frozen weights and flag rules are exactly the ones the backtests used
(metrics/rows.py, metrics/weights.json). League-wide numbers come from nflverse
through the last completed week; the app overlays its own injury designations on
top (see `attach`). Everything degrades to "no grade" when nflverse isn't cached.
"""
from __future__ import annotations

from collections import defaultdict

from cbs_client import norm
from metrics.availability import expected_games, status_key, team_weeks
from metrics.features import SHARE_STAT, _optional, by_player, implied_totals, injury_index, load_season_games, pedigree, pedigree_index
from metrics.grades import Model, load_weights, percentile_grade, replacement_rank, replacement_value
from metrics.qb import qb_row
from metrics.rows import add_breakout_context, decision_rows, mark_next_up
from nflverse.pull import CURRENT_SEASON, load, read_meta

POS = ("WR", "RB", "TE")
LAST_WEEK = 18
IR_MIN_GAMES_OUT = 4              # NFL injured reserve keeps a player out at least 4 games
BUY_LOW_DECISION_WEEKS = range(3, 10)  # backtested 4–9; week 3 added so the flag exists early in the season
IR_SLOTS = frozenset({"injured", "ir"})

_CACHE: dict = {}
_QB_PRIOR: dict[int, dict] = {}  # finished seasons never change: {season: {player_id: QB game rows}}


def _qb_games(season: int) -> dict:
    if season not in _QB_PRIOR:
        try:
            _QB_PRIOR[season] = by_player([g for g in load_season_games(season) if g["pos"] == "QB"])
        except Exception:
            _QB_PRIOR[season] = {}
    return _QB_PRIOR[season]


def clear() -> None:
    _CACHE.clear()


def status_from_designation(designation: str | None) -> str | None:
    """CBS/ESPN designation -> Out / Doubtful / Questionable, or None when it says nothing."""
    d = (designation or "").strip().lower()
    if not d:
        return None
    if d in {"out", "ir", "injured", "pup", "suspended"} or "reserve" in d or d.startswith("out"):
        return "Out"
    if "doubt" in d:
        return "Doubtful"
    if "question" in d:
        return "Questionable"
    return None


def exp_games_for(status: str, team_games_left: int, table: dict, ir: bool = False) -> float:
    g = expected_games(status or "Healthy", team_games_left, table)
    if ir:
        g = min(g, max(0.0, team_games_left - IR_MIN_GAMES_OUT))
    return g


def _grade_fields(p: dict, repl: float, status: str, ir: bool, table: dict) -> dict:
    exp = exp_games_for(status, p["team_games_left"], table, ir)
    return {"status": status or "", "exp_games": round(exp, 1), "par": round((p["pred_ppg"] - repl) * exp, 1)}


def compute(week: int, season: int = CURRENT_SEASON, out_names: frozenset[str] = frozenset()) -> dict:
    """League-wide grades for fantasy week `week`, from games through the last completed week.

    `out_names` = normalized names of players the app's own injury feed has out or on IR, which
    is fresher than nflverse's weekly report (and the only place IR players show up)."""
    key = (season, int(week), read_meta().get("as_of") or "", frozenset(out_names))
    if key in _CACHE:
        return _CACHE[key]
    out = _compute(int(week), season, frozenset(out_names))
    _CACHE.clear()
    _CACHE[key] = out
    return out


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason, "players": {}, "by_name": {}}


def _compute(week: int, season: int, out_names: frozenset[str] = frozenset()) -> dict:
    w = load_weights()
    if not w.get("positions") or not w.get("miss_table"):
        return _unavailable("metrics/weights.json missing: run backtest_metrics.py")
    try:
        games = load_season_games(season)
        schedule = load("games")
        players = load("players")
    except Exception as e:  # no cache yet / offline first run
        return _unavailable(f"nflverse data not cached: {e}")
    latest = max((g["week"] for g in games), default=0)
    d = min(week - 1, latest)
    if d < 2:
        return _unavailable("need two completed weeks")
    inj = injury_index(_optional(load, "injuries", season))
    tw = team_weeks(schedule, season)
    imp = implied_totals(schedule, season)
    rows = decision_rows(games, season, list(POS), None, decisions=[d], require_future=False,
                         inj=inj, team_weeks=tw, implied=imp)
    known_out = {g["player_id"] for g in games if norm(g["player"]) in out_names}
    add_breakout_context(rows, games, inj, tw, extra_out=known_out)
    mark_next_up(rows)
    ped = pedigree_index(players)
    table = w["miss_table"]["train"] if "train" in w["miss_table"] else w["miss_table"]
    bump_cfg = w.get("rb_pedigree_bump") or {}
    models = {pos: Model.from_dict(w["positions"][pos]["models"]["par"]) for pos in POS if pos in w["positions"]}

    out_players: dict[str, dict] = {}
    by_pos: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        pos = r["pos"]
        if pos not in models:
            continue
        pd_ = pedigree(ped, r["player_id"], season)
        share = r.get(SHARE_STAT[pos])
        bump = 0.0
        if pos == "RB" and pd_["young_high_pick"] and bump_cfg:
            bump = bump_cfg["low_share"] if (r.get("opp_share") or 0.0) < bump_cfg["share_cut"] else bump_cfg["high_share"]
        tg_left = len([x for x in tw.get(r["team"], set()) if x >= week])
        flags = []
        if r.get("next_up"):
            flags.append("next_up")
        if pd_["young_high_pick"] and r.get("waiver_tier") and d in BUY_LOW_DECISION_WEEKS:
            flags.append("buy_low")
        p = {
            "player_id": r["player_id"], "player": r["player"], "team": r["team"], "pos": pos,
            "usage_stat": SHARE_STAT[pos], "usage": share, "snap_pct": r.get("snap_pct"),
            "ppg": r["ppg"], "games": r["n"], "pred_ppg": models[pos].predict(r) + bump, "bump": bump,
            "years": pd_["years"], "round": pd_["round"], "waiver_tier": bool(r.get("waiver_tier")),
            "team_games_left": tg_left,
            "status": "Out" if r["player_id"] in known_out else (r["status"] if r["status"] != "Healthy" else ""),
            "flags": flags, "vac_pos": r.get("vac_pos") or 0.0,
        }
        out_players[r["player_id"]] = p
        by_pos[pos].append(p)

    qbs = _qb_players(games, season, d, week, tw, inj, w, known_out, ped)
    if qbs:
        out_players.update(qbs)
        by_pos["QB"] = list(qbs.values())

    repl: dict[str, float] = {}
    for pos, ps in by_pos.items():
        repl[pos] = replacement_value([p["pred_ppg"] for p in ps], pos)
        # QB "role" is the projection itself (his usage stat is efficiency, not volume).
        key = "pred_ppg" if pos == "QB" else "usage"
        role = percentile_grade({p["player_id"]: float(p[key] or 0.0) for p in ps})
        ranked = sorted(ps, key=lambda p: -p["pred_ppg"])
        for i, p in enumerate(ranked):
            p["rank"], p["of"] = i + 1, len(ranked)
        for p in ps:
            p["role"] = role[p["player_id"]]
            p.update(_grade_fields(p, repl[pos], p["status"], False, table))

    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for pid, p in out_players.items():
        by_name[(norm(p["player"]), p["pos"])].append(pid)
    meta = read_meta()
    return {"available": True, "week": week, "decision_week": d, "latest_week": latest, "players": out_players,
            "by_name": dict(by_name), "repl": repl, "table": table, "as_of": meta.get("as_of") or "",
            "buy_low_active": d in BUY_LOW_DECISION_WEEKS}


def _qb_players(games: list[dict], season: int, d: int, week: int, tw: dict, inj: dict, w: dict,
                known_out: set[str], ped: dict) -> dict[str, dict]:
    """Rest-of-season projection for every active QB (metrics/qb.py), shaped like the skill-player grades."""
    cfg = w.get("qb_ros")
    if not cfg:
        return {}
    model = Model.from_dict(cfg["model"])
    prior = {b: _qb_games(season - b) for b in (1, 2)}
    cur = by_player([g for g in games if g["pos"] == "QB"])
    out: dict[str, dict] = {}
    for pid, gl in cur.items():
        past = [g for g in gl if g["week"] <= d]
        row = qb_row(past, {b: prior[b].get(pid, []) for b in (1, 2)}, cfg["mean_prior"])
        if row is None:
            continue
        pd_ = pedigree(ped, pid, season)
        team = past[-1]["team"]
        status = status_key(inj.get((pid, d + 1)))
        out[pid] = {
            "player_id": pid, "player": gl[-1]["player"], "team": team, "pos": "QB", "usage_stat": "epa", "usage": row["epa"],
            "snap_pct": None, "ppg": row["ppg"], "games": row["g"], "pred_ppg": model.predict(row), "bump": 0.0,
            "years": pd_["years"], "round": pd_["round"], "waiver_tier": False,
            "team_games_left": len([x for x in tw.get(team, set()) if x >= week]),
            "status": "Out" if pid in known_out else (status if status != "Healthy" else ""), "flags": [], "vac_pos": 0.0,
        }
    ranked = sorted(out.values(), key=lambda p: -p["ppg"])
    for i, p in enumerate(ranked):
        p["waiver_tier"] = i >= replacement_rank("QB")
    return out


def lookup(data: dict, name: str, pos: str, team: str = "") -> dict | None:
    pids = (data.get("by_name") or {}).get((norm(name), (pos or "").upper())) or []
    if not pids:
        return None
    cands = [data["players"][p] for p in pids]
    same = [c for c in cands if team and c["team"] == team]
    return max(same or cands, key=lambda c: c["games"])


def grade_for(data: dict, rec: dict) -> dict | None:
    """The `grade` object for one app player record, or None when nflverse has nothing on him.
    Uses the app's own injury designation (and IR slot) over nflverse's weekly report."""
    if not data.get("available"):
        return None
    pos = (rec.get("pos") or "").upper()
    p = lookup(data, rec.get("player") or "", pos, (rec.get("team") or "").upper())
    if not p:
        return None
    ir = (rec.get("slot") or "").strip().lower() in IR_SLOTS
    status = status_from_designation(((rec.get("injury") or {}).get("designation"))) or ("Out" if ir else None) or p["status"]
    g = _grade_fields(p, data["repl"][pos], status, ir, data["table"])
    return {
        "role": p["role"], "usage_stat": p["usage_stat"], "usage": None if p["usage"] is None else round(p["usage"], 3),
        "snap_pct": None if p["snap_pct"] is None else round(p["snap_pct"], 2),
        "par_ppg": round(p["pred_ppg"], 2), "par": g["par"], "exp_games": g["exp_games"], "status": g["status"],
        "team_games_left": p["team_games_left"], "games": p["games"], "ppg": round(p["ppg"], 2),
        "rank": p["rank"], "of": p["of"], "years": p["years"], "round": p["round"], "bump": round(p["bump"], 2), "flags": list(p["flags"]),
        "waiver_tier": p["waiver_tier"], "vac_pos": round(p["vac_pos"], 3),
    }


def wants_in_pool(data: dict, rec: dict) -> bool:
    """A free agent worth scoring: nflverse has him with a real offensive role (1+ carry or
    target a game over 2+ games), so waiver candidates aren't limited to the draft board."""
    if not data.get("available"):
        return False
    return lookup(data, rec.get("player") or "", (rec.get("pos") or "").upper(), (rec.get("team") or "").upper()) is not None


# ---------- streams: DST and kicker ----------

def dst_stream(vegas: dict) -> dict[str, dict]:
    """{team: {opp, opp_total, own_total, rank, of, score}} from the Vegas board for the week.
    Lower opponent implied total is better; `score` = league average − opponent total."""
    teams = (vegas or {}).get("teams") or {}
    rows = []
    for team, e in teams.items():
        opp = (e.get("opp") or "").upper()
        opp_total = (teams.get(opp) or {}).get("total")
        if opp_total is None:
            continue
        rows.append({"team": team.upper(), "opp": opp, "opp_total": float(opp_total), "own_total": e.get("total")})
    if not rows:
        return {}
    avg = sum(r["opp_total"] for r in rows) / len(rows)
    rows.sort(key=lambda r: r["opp_total"])
    return {r["team"]: {**r, "rank": i + 1, "of": len(rows), "score": round(avg - r["opp_total"], 2)} for i, r in enumerate(rows)}


def kicker_stream(vegas: dict) -> dict[str, dict]:
    """{team: {implied, dome, rank, of, score}}: higher implied total is better, dome breaks ties."""
    teams = (vegas or {}).get("teams") or {}
    rows = [{"team": t.upper(), "implied": float(e["total"]), "dome": bool(e.get("indoor"))}
            for t, e in teams.items() if e.get("total") is not None]
    if not rows:
        return {}
    rows.sort(key=lambda r: (-r["implied"], not r["dome"]))
    return {r["team"]: {**r, "rank": i + 1, "of": len(rows), "score": round(r["implied"] + (0.01 if r["dome"] else 0.0), 2)}
            for i, r in enumerate(rows)}


# ---------- trackers ----------

WR_WATCH_FROM_WEEK = 8
WR_WATCH_SIZE = 10
_TRACKER_FIELDS = ("player", "team", "pos", "usage_stat", "usage", "snap_pct", "ppg", "years", "round", "flags")


def _owners(roster_rows: list[dict], fa_rows: list[dict]) -> tuple[dict, dict]:
    owner = {(norm(r["player"]), (r.get("pos") or "").upper()): r.get("owner") or "" for r in roster_rows}
    fa_status = {(norm(r["player"]), (r.get("pos") or "").upper()): (r.get("status") or "").lower() for r in fa_rows}
    return owner, fa_status


def trackers(data: dict, week: int, roster_rows: list[dict], fa_rows: list[dict]) -> dict:
    """League-wide lists: every flagged buy-low / next-man-up player (free or rostered, with owner)
    and, from week 8, the top 10 available WRs by PAR."""
    if not data.get("available"):
        return {"buy_low": [], "next_up": [], "wr_watch": {"active": False, "players": []}}
    owner, fa_status = _owners(roster_rows, fa_rows)
    repl = data["repl"]

    def card(p: dict) -> dict:
        k = (norm(p["player"]), p["pos"])
        g = _grade_fields(p, repl[p["pos"]], p["status"], False, data["table"])
        own = owner.get(k, "")
        return {**{key: p.get(key) for key in _TRACKER_FIELDS}, **g, "role": p["role"], "pred_ppg": round(p["pred_ppg"], 2),
                "owner": own, "available": not own,
                "waiver_status": ("waivers" if fa_status.get(k) == "waivers" else "free_agent") if not own else ""}

    cards = [card(p) for p in data["players"].values() if p["flags"]]
    cards.sort(key=lambda c: -c["par"])
    watch = sorted((card(p) for p in data["players"].values() if p["pos"] == "WR"), key=lambda c: -c["par"])
    watch = [c for c in watch if c["available"]][:WR_WATCH_SIZE]
    return {
        "buy_low": [c for c in cards if "buy_low" in c["flags"]],
        "next_up": [c for c in cards if "next_up" in c["flags"]],
        "wr_watch": {"active": int(week) >= WR_WATCH_FROM_WEEK, "players": watch},
    }
