"""Per-player decision-week feature rows, shared by the backtests and the live app.

One row per player per decision week d: features from games through week d, plus
(for backtests) targets from the weeks after. Teammate-injury context and the
RB next-man-up flag are added on top (add_breakout_context, mark_next_up).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import fmean, pstdev

from metrics.availability import status_key
from metrics.features import SHARE_STAT, by_player, injury_exit_weeks, window_features
from metrics.grades import replacement_rank

DECISIONS = range(3, 17)
HORIZON = 6
MIN_PAST = 2
MIN_FUTURE = 2
MIN_OPP_PG = 1.0      # carries+targets per game: below this there's no offensive role to grade
MIN_OPP_PG_QB = 15.0  # dropbacks + designed runs per game: a QB actually playing, not a mop-up backup


def primary_pos(gl: list[dict]) -> str:
    return Counter(g["pos"] for g in gl).most_common(1)[0][0]


def delta(l3: dict, std: dict, key: str | None) -> float | None:
    if not key or l3.get(key) is None or std.get(key) is None:
        return None
    return l3[key] - std[key]


def decision_rows(games: list[dict], season: int, positions: list[str], cuts: dict[str, float] | None = None, *,
                  decisions=DECISIONS,
                  exclude_exits: bool | set[str] = False, require_future: bool = True,
                  inj: dict | None = None, team_weeks: dict[str, set[int]] | None = None,
                  implied: dict[tuple[str, int], float] | None = None) -> list[dict]:
    """One row per player per decision week d: features from weeks <= d, targets after.

    exclude_exits drops injury-shortened games (metrics.features.injury_exit_weeks)
    from the features only (True, or a set of positions); targets keep every game.
    require_future=False keeps players who then barely played, for the availability
    test (y_ppg etc. are None there, y_total6 counts missed games as 0).
    Injury status is his report for week d+1, the last one before the next game.
    """
    rows = []
    for pid, gl in by_player(games).items():
        pos = primary_pos(gl)
        if pos not in positions:
            continue
        cut = (cuts or {}).get(pos, 0.0)
        drop_exits = exclude_exits is True or (isinstance(exclude_exits, set) and pos in exclude_exits)
        for d in decisions:
            past = [g for g in gl if g["week"] <= d]
            fut = [g for g in gl if d < g["week"] <= d + HORIZON]
            if len(past) < MIN_PAST or (require_future and len(fut) < MIN_FUTURE):
                continue
            exits = injury_exit_weeks(past) if drop_exits else set()
            feat = [g for g in past if g["week"] not in exits]
            if len(feat) < MIN_PAST:
                feat = past
            std = window_features(feat, pos)
            if std["opp_pg"] < (MIN_OPP_PG_QB if pos == "QB" else MIN_OPP_PG):
                continue
            l3 = window_features(feat[-3:], pos)
            nxt = next((g for g in fut if g["week"] == d + 1), None)
            fut_pts = [g["gbfl"] for g in fut]
            team = past[-1]["team"]
            nxt_wk = min((w for w in (team_weeks or {}).get(team, set()) if w > d), default=None)
            tweeks = {w for w in (team_weeks or {}).get(team, set()) if d < w <= d + HORIZON}
            if not tweeks:
                tweeks = {g["week"] for g in fut}
            played = {g["week"] for g in fut} & tweeks
            ok = len(fut) >= MIN_FUTURE
            rows.append({
                **std,
                "player_id": pid, "player": gl[-1]["player"], "team": team,
                "pos": pos, "season": season, "week": d,
                "l3_ppg": l3["ppg"],
                "d_share": delta(l3, std, SHARE_STAT.get(pos)),
                "d_snap": delta(l3, std, "snap_pct"),
                "next_implied": (implied or {}).get((team, nxt_wk)) if nxt_wk else None,
                "std_boom": sum(1 for g in feat if g["gbfl"] >= cut) / len(feat),
                "exits_dropped": len(exits),
                "status": status_key((inj or {}).get((pid, d + 1))),
                "team_games6": len(tweeks), "played6": len(played),
                "played_next": any(g["week"] == d + 1 for g in fut),
                "team_plays_next": (d + 1) in tweeks,
                "y_total6": sum(g["gbfl"] for g in fut if g["week"] in tweeks),
                "y_next": nxt["gbfl"] if nxt else None,
                "y_ppg": fmean(fut_pts) if ok else None,
                "y_delta": fmean(fut_pts) - std["ppg"] if ok else None,
                "y_boom": sum(1 for p in fut_pts if p >= cut) / len(fut_pts) if ok else None,
                "y_bust": sum(1 for p in fut_pts if p <= 0) / len(fut_pts) if ok else None,
                "y_sd": pstdev(fut_pts) if ok else None,
            })
    # Waiver tier: outside the league's rostered count at the position, by points so far.
    by_slice = defaultdict(list)
    for r in rows:
        by_slice[(r["season"], r["week"], r["pos"])].append(r)
    for (_, _, pos), sl in by_slice.items():
        sl.sort(key=lambda r: -r["ppg"])
        for i, r in enumerate(sl):
            r["waiver_tier"] = i >= replacement_rank(pos)
    return rows


BREAKOUT_POSITIONS = ("WR", "RB", "TE")
BREAKOUT_FEATURES = ["d_share", "d_snap", "vac_pos", "vac_pos_x_share", "vac_tgt", "ret_pos"]


def _share_of(g_list: list[dict], kind: str) -> float | None:
    if kind == "opp":
        num = sum(g["carries"] + g["targets"] for g in g_list)
        den = sum(g["team_carries"] + g["team_targets"] for g in g_list)
    else:
        num = sum(g["targets"] for g in g_list)
        den = sum(g["team_targets"] for g in g_list)
    return num / den if den > 0 else None


def add_breakout_context(rows: list[dict], games: list[dict], inj: dict, team_weeks: dict[str, set[int]],
                         extra_out: set[str] | None = None) -> None:
    """Teammate-injury features on each decision row (one season).

    A teammate's opportunity is "vacated" when he's Out/Doubtful for the next game, or
    missed week d and isn't on the next report at all (IR/suspension), and he played in
    week d or d−1 (newly gone, not already absorbed). "Returning" is a same-position
    teammate who missed week d but is Questionable/listed for the next game.
    vac_pos is same-position share (target share for WR/TE, opportunity share for RB);
    vac_tgt is vacated target share across all pass-catchers.

    `extra_out` = player ids another source says are out (the app's ESPN/CBS injury feed, an IR
    slot). nflverse's weekly report doesn't list players on injured reserve, and a player hurt
    in week d who played part of that game isn't a missed game yet, so neither shows up
    through the report alone. They count as vacated under the same "played recently" rule.
    """
    players = by_player(games)
    info = {}  # (pid) -> (pos, team history)
    for pid, gl in players.items():
        info[pid] = (primary_pos(gl), gl)
    ctx: dict[tuple[int, str], list[dict]] = defaultdict(list)
    needed: dict[str, set[int]] = defaultdict(set)
    for r in rows:
        needed[r["team"]].add(r["week"])
    for pid, (pos, gl) in info.items():
        if pos not in BREAKOUT_POSITIONS:
            continue
        for d, team in ((d, t) for t in {g["team"] for g in gl} for d in needed.get(t, ())):
            past = [g for g in gl if g["week"] <= d and g["team"] == team]
            if len(past) < 2:
                continue
            weeks_played = {g["week"] for g in past}
            played_d, played_prev = d in weeks_played, (d - 1) in weeks_played
            team_played_d = d in team_weeks.get(team, set())
            rep = inj.get((pid, d + 1))
            st = status_key(rep)
            gone = st in ("Out", "Doubtful") or (team_played_d and not played_d and rep is None) or pid in (extra_out or ())
            fresh = played_d or played_prev
            returning = team_played_d and not played_d and st in ("Questionable", "Listed")
            ctx[(d, team)].append({
                "pid": pid, "pos": pos,
                "tshare": _share_of(past, "tgt") or 0.0, "oshare": _share_of(past, "opp") or 0.0,
                "vacated": gone and fresh, "returning": returning,
            })
    for r in rows:
        mates = [m for m in ctx.get((r["week"], r["team"]), []) if m["pid"] != r["player_id"]]
        key = "oshare" if r["pos"] == "RB" else "tshare"
        same = [m for m in mates if m["pos"] == r["pos"]]
        r["vac_pos"] = sum(m[key] for m in same if m["vacated"])
        r["ret_pos"] = sum(m[key] for m in same if m["returning"])
        r["vac_tgt"] = sum(m["tshare"] for m in mates if m["vacated"])
        own = r.get(SHARE_STAT[r["pos"]]) or 0.0
        r["vac_pos_x_share"] = r["vac_pos"] * own


NEXT_UP_VACANCY = 0.15  # vacated RB opportunity share that counts as "the lead back is out"


def mark_next_up(rows: list[dict]) -> None:
    """RB "next man up": a starter-level RB vacancy on his team (vac_pos >= NEXT_UP_VACANCY)
    and he has the highest opportunity share among the RBs still available."""
    best: dict[tuple, tuple[float, int]] = {}
    for r in rows:
        if r["pos"] == "RB" and r.get("vac_pos", 0) >= NEXT_UP_VACANCY:
            key = (r["season"], r["week"], r["team"])
            share = r.get("opp_share") or 0.0
            if share > best.get(key, (-1.0, 0))[0]:
                best[key] = (share, id(r))
    for r in rows:
        r["next_up"] = r["pos"] == "RB" and best.get((r["season"], r["week"], r["team"]), (0, None))[1] == id(r)


