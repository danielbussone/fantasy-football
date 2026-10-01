"""Per-position usage features from nflverse player-games.

One row per player-game (`build_games`), then trailing-window aggregates
(`window_features`). Shares are ratios of sums over the games a player
actually played (his targets / his team's targets in those games), not
averages of per-game ratios, so a 1-target game doesn't count like a
12-target one. A game with snaps but no stat line still counts, as zeros.

Role features measure how much of the offense runs through a player (what
drives the mean); Boom features measure how his points arrive — depth,
explosive plays, clearing this format's yardage buckets (GBFL_RULES.md §5/§6).
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean

from nflverse.score import SKILL, norm_pos, scored_weeks

# Yardage needed to score anything in this format (scoring/rules.py).
BUCKET_YDS = {"QB": 200, "RB": 70, "WR": 70, "TE": 40}

ROLE_FEATURES = {
    "WR": ["snap_pct", "tgt_share", "air_share", "wopr", "tpg", "rz_tpg"],
    "TE": ["snap_pct", "tgt_share", "air_share", "wopr", "tpg", "rz_tpg"],
    "RB": ["snap_pct", "rush_share", "tgt_share", "opp_share", "i10_share", "opp_pg"],
    "QB": ["snap_pct", "db_pg", "rush_att_pg", "qb_rush_share", "implied", "next_implied"],
}
# Depth/efficiency only. bucket_rate is kept out on purpose: it's production
# (it tracks volume at r ≈ 0.8–0.9), so it would let "Boom" pass on Role's signal.
BOOM_FEATURES = {
    "WR": ["adot", "deep_rate", "catch_rate", "ypt", "rec20_rate"],
    "TE": ["adot", "ez_tpg", "catch_rate", "ypt", "rec20_rate"],
    "RB": ["run15_rate", "run26_rate", "ypc", "ypt"],
    "QB": ["adot_pass", "deep_att_rate", "cpoe"],
}

# The one usage stat each position's grades use. The backtest found one stat
# ranks as well as all six ROLE_FEATURES together (they mostly measure the
# same volume), and these were the best single stats on 2023–25.
SHARE_STAT = {"WR": "wopr", "TE": "wopr", "RB": "opp_share", "QB": "next_implied"}
PAR_POINTS_WEIGHT = 0.4  # WR/RB/TE: score = 40% season pts/g + 60% share stat, both standardized
# The fixed blend behind GBFL-PAR, per position: (features, weights on their z-scores).
# QB volume barely varies among starters; the offense's scoring environment and the
# QB's own efficiency predict him, and on 2024 validation points so far added nothing.
PAR_BLEND = {
    "WR": (["ppg", "wopr"], [PAR_POINTS_WEIGHT, 1 - PAR_POINTS_WEIGHT]),
    "TE": (["ppg", "wopr"], [PAR_POINTS_WEIGHT, 1 - PAR_POINTS_WEIGHT]),
    "RB": (["ppg", "opp_share"], [PAR_POINTS_WEIGHT, 1 - PAR_POINTS_WEIGHT]),
    "QB": (["ppg", "next_implied", "epa_db"], [0.0, 0.5, 0.5]),
}

FEATURE_HELP = {
    "wopr": "Weighted Opportunity Rating: 1.5 × target share + 0.7 × air-yards share. "
            "Rewards being targeted often and downfield. WR1s run about 0.6–0.75, waiver WRs under 0.3.",
    "opp_share": "Opportunity share: the player's carries + targets ÷ his team's carries + targets, "
                 "in the games he played.",
    "next_implied": "Vegas implied team total for his next game: the over/under split by the spread. "
                    "It prices in the offense, the opponent and the game environment.",
    "epa_db": "EPA per play: expected points added per dropback or designed run, season to date. "
              "Measures how much each play moves his offense toward scoring.",
}

FEATURE_LABELS = {
    "ppg": "GBFL pts/game",
    "snap_pct": "Snap share",
    "tgt_share": "Target share",
    "air_share": "Air-yards share",
    "wopr": "WOPR",
    "tpg": "Targets/game",
    "rz_tpg": "Red-zone targets/game",
    "ez_tpg": "End-zone targets/game",
    "rush_share": "Rush share",
    "opp_share": "Opportunity share",
    "i10_share": "Inside-10 carry share",
    "opp_pg": "Carries+targets/game",
    "adot": "aDOT",
    "deep_rate": "Deep-target rate (20+ air)",
    "catch_rate": "Catch rate",
    "ypt": "Yards/target",
    "rec20_rate": "20+ yd catches/target",
    "bucket_rate": "Bucket-clear rate",
    "run15_rate": "15+ yd runs/carry",
    "run26_rate": "26+ yd runs/carry",
    "ypc": "Yards/carry",
    "db_pg": "Dropbacks/game",
    "rush_att_pg": "Designed runs/game",
    "qb_rush_share": "Share of team rushing yards",
    "implied": "Vegas implied team total",
    "next_implied": "Next game implied team total",
    "adot_pass": "Passing aDOT",
    "deep_att_rate": "Deep-attempt rate (20+ air)",
    "epa_db": "EPA per play",
    "cpoe": "CPOE",
}


def _f(v) -> float:
    try:
        return float(v) if v not in (None, "", "NA") else 0.0
    except ValueError:
        return 0.0


def _pbp_counts(pbp: list[dict]) -> tuple[dict, dict]:
    """Per (player, week) and per (team, week) play counts from play-by-play."""
    player: dict[tuple[str, int], dict] = defaultdict(lambda: defaultdict(float))
    team: dict[tuple[str, int], dict] = defaultdict(lambda: defaultdict(float))
    for r in pbp:
        if r.get("two_point_attempt") == "1":
            continue
        wk = int(r["week"])
        yl = _f(r.get("yardline_100"))
        tm = r.get("posteam") or ""
        if r.get("play_type") == "pass" and r.get("passer_player_id") and r.get("sack") != "1" and r.get("pass_attempt") == "1":
            qb = r["passer_player_id"]
            if _f(r.get("air_yards")) >= 20:
                player[(qb, wk)]["deep_att"] += 1
        if r.get("play_type") == "run" and r.get("qb_scramble") == "1" and r.get("rusher_player_id"):
            player[(r["rusher_player_id"], wk)]["scrambles"] += 1
        if r.get("play_type") == "pass" and r.get("receiver_player_id") and r.get("sack") != "1":
            pid = r["receiver_player_id"]
            air = _f(r.get("air_yards"))
            if yl <= 20:
                player[(pid, wk)]["rz_tgt"] += 1
            if yl > 0 and air >= yl:
                player[(pid, wk)]["ez_tgt"] += 1
            if air >= 20:
                player[(pid, wk)]["deep_tgt"] += 1
        elif r.get("play_type") == "run" and r.get("rusher_player_id"):
            pid = r["rusher_player_id"]
            yds = _f(r.get("yards_gained"))
            if yl <= 10:
                player[(pid, wk)]["i10_car"] += 1
                team[(tm, wk)]["i10_car"] += 1
            if yds >= 15:
                player[(pid, wk)]["run15"] += 1
            if yds >= 26:
                player[(pid, wk)]["run26"] += 1
    return player, team


def _snaps(snap_rows: list[dict], players: list[dict]) -> dict[tuple[str, int], dict]:
    pfr_to_gsis = {p["pfr_id"]: p["gsis_id"] for p in players if p.get("pfr_id") and p.get("gsis_id")}
    out = {}
    for r in snap_rows:
        if r.get("game_type") != "REG":
            continue
        gsis = pfr_to_gsis.get(r.get("pfr_player_id") or "")
        if not gsis:
            continue
        out[(gsis, int(r["week"]))] = {
            "snap_pct": _f(r.get("offense_pct")),
            "snaps": _f(r.get("offense_snaps")),
            "team": r.get("team") or "",
            "position": r.get("position") or "",
            "player": r.get("player") or "",
        }
    return out


def implied_totals(schedule: list[dict], season: int) -> dict[tuple[str, int], float]:
    """{(team, week): Vegas-implied points} from nflverse games.csv closing lines.
    nflverse's spread_line is positive when the home team is favored."""
    out = {}
    for g in schedule:
        if str(g.get("season")) != str(season) or g.get("game_type") != "REG":
            continue
        total, spread = g.get("total_line"), g.get("spread_line")
        if total in (None, "", "NA") or spread in (None, "", "NA"):
            continue
        t, sp, wk = float(total), float(spread), int(g["week"])
        out[(g["home_team"], wk)] = (t + sp) / 2
        out[(g["away_team"], wk)] = (t - sp) / 2
    return out


INJURY_STATUSES = ("Out", "Doubtful", "Questionable")
EXIT_SNAP_RATIO = 0.5  # snaps below half his own usual = a shortened game


def injury_index(injuries: list[dict]) -> dict[tuple[str, int], dict]:
    """{(gsis_id, week): {"status": Out/Doubtful/Questionable/"", "injured": bool}} from the
    weekly injury report. "Not injury related" (rest, personal) doesn't count as injured."""
    out: dict[tuple[str, int], dict] = {}
    for r in injuries:
        if r.get("game_type") != "REG" or not r.get("gsis_id"):
            continue
        reasons = [(r.get(k) or "").strip() for k in ("report_primary_injury", "practice_primary_injury")]
        injured = any(x and not x.lower().startswith("not injury related") for x in reasons)
        status = (r.get("report_status") or "").strip()
        out[(r["gsis_id"], int(r["week"]))] = {
            "status": status if status in INJURY_STATUSES else "",
            "injured": injured or status in INJURY_STATUSES,
        }
    return out


def injury_exit_weeks(past: list[dict], ratio: float = EXIT_SNAP_RATIO) -> set[int]:
    """Weeks among `past` that were injury-shortened: snaps under `ratio` × his median
    snaps in `past`, and he was on the injury report that week or the next. Uses only
    `past`, so a decision week never looks at later snap counts."""
    snaps = [g["snap_pct"] for g in past if g.get("snap_pct")]
    if len(snaps) < 3:
        return set()
    med = sorted(snaps)[len(snaps) // 2]
    return {g["week"] for g in past
            if g.get("snap_pct") is not None and g["snap_pct"] < ratio * med
            and (g.get("inj_listed") or g.get("inj_listed_next"))}


def build_games(season: int, *, weekly: list[dict], team_week: list[dict], pbp: list[dict],
                snaps: list[dict], players: list[dict], injuries: list[dict] | None = None,
                schedule: list[dict] | None = None) -> list[dict]:
    """One row per skill-position player-game with GBFL points and raw usage."""
    tw = {(r["team"], int(r["week"])): r for r in team_week if r.get("season_type") == "REG"}
    pc, tc = _pbp_counts(pbp)
    sn = _snaps(snaps, players)
    pos_of = {p["gsis_id"]: norm_pos(p.get("position")) for p in players if p.get("gsis_id")}
    name_of = {p["gsis_id"]: p.get("display_name") or "" for p in players if p.get("gsis_id")}

    rows: dict[tuple[str, int], dict] = {}
    for r in scored_weeks(weekly, pbp):
        rows[(r["player_id"], r["week_n"])] = {
            "player_id": r["player_id"], "player": r.get("player_display_name") or "",
            "pos": r["pos"], "team": r.get("team") or "", "week": r["week_n"], "gbfl": r["gbfl"],
            "targets": _f(r.get("targets")), "rec": _f(r.get("receptions")),
            "rec_yds": _f(r.get("receiving_yards")), "air_yds": _f(r.get("receiving_air_yards")),
            "rec20": _f(r.get("receiving_20")),
            "carries": _f(r.get("carries")), "rush_yds": _f(r.get("rushing_yards")),
            "pass_yds": _f(r.get("passing_yards")),
            "attempts": _f(r.get("attempts")), "sacks": _f(r.get("sacks_suffered")),
            "pass_air": _f(r.get("passing_air_yards")),
            "epa": _f(r.get("passing_epa")) + _f(r.get("rushing_epa")),
            "cpoe": None if r.get("passing_cpoe") in (None, "", "NA") else _f(r.get("passing_cpoe")),
        }
    # Played (took offensive snaps) but no stat line: a real zero, not a missed game.
    for (pid, wk), s in sn.items():
        if (pid, wk) in rows or s["snaps"] <= 0:
            continue
        pos = pos_of.get(pid) or norm_pos(s["position"])
        if pos not in SKILL:
            continue
        rows[(pid, wk)] = {
            "player_id": pid, "player": name_of.get(pid) or s["player"], "pos": pos,
            "team": s["team"], "week": wk, "gbfl": 0.0,
            "targets": 0.0, "rec": 0.0, "rec_yds": 0.0, "air_yds": 0.0, "rec20": 0.0,
            "carries": 0.0, "rush_yds": 0.0, "pass_yds": 0.0,
            "attempts": 0.0, "sacks": 0.0, "pass_air": 0.0, "epa": 0.0, "cpoe": None,
        }

    inj = injury_index(injuries or [])
    imp = implied_totals(schedule or [], season)
    out = []
    for (pid, wk), g in rows.items():
        g["inj_listed"] = (inj.get((pid, wk)) or {}).get("injured", False)
        g["inj_listed_next"] = (inj.get((pid, wk + 1)) or {}).get("injured", False)
        t = tw.get((g["team"], wk)) or {}
        s = sn.get((pid, wk)) or {}
        p = pc.get((pid, wk)) or {}
        g.update({
            "season": int(season),
            "snap_pct": s.get("snap_pct"),
            "team_targets": _f(t.get("targets")), "team_air": _f(t.get("receiving_air_yards")),
            "team_carries": _f(t.get("carries")),
            "team_i10": (tc.get((g["team"], wk)) or {}).get("i10_car", 0.0),
            "rz_tgt": p.get("rz_tgt", 0.0), "ez_tgt": p.get("ez_tgt", 0.0), "deep_tgt": p.get("deep_tgt", 0.0),
            "i10_car": p.get("i10_car", 0.0), "run15": p.get("run15", 0.0), "run26": p.get("run26", 0.0),
            "deep_att": p.get("deep_att", 0.0), "scrambles": p.get("scrambles", 0.0),
            "team_rush_yds": _f(t.get("rushing_yards")),
            "implied": imp.get((g["team"], wk)),
            "scrim_yds": g["rush_yds"] + g["rec_yds"],
        })
        out.append(g)
    out.sort(key=lambda g: (g["player_id"], g["week"]))
    return out


def _ratio(num: float, den: float) -> float | None:
    return num / den if den > 0 else None


def _bucket_yards(g: dict, pos: str) -> float:
    if pos == "QB":
        return (g.get("pass_yds") or 0.0) + (g.get("rush_yds") or 0.0)
    return g.get("scrim_yds") or 0.0


def window_features(games: list[dict], pos: str) -> dict:
    """Aggregate features over a list of one player's games."""
    n = len(games)
    if n == 0:
        return {"n": 0}
    s = defaultdict(float)
    for g in games:
        for k in ("gbfl", "targets", "rec", "rec_yds", "air_yds", "rec20", "carries", "rush_yds",
                  "team_targets", "team_air", "team_carries", "team_i10", "rz_tgt", "ez_tgt",
                  "deep_tgt", "i10_car", "run15", "run26", "attempts", "sacks", "pass_air", "epa",
                  "deep_att", "scrambles", "team_rush_yds"):
            s[k] += g.get(k) or 0.0
    snaps = [g["snap_pct"] for g in games if g.get("snap_pct") is not None]
    tgt_share = _ratio(s["targets"], s["team_targets"])
    air_share = _ratio(s["air_yds"], s["team_air"])
    wopr = None if tgt_share is None or air_share is None else 1.5 * tgt_share + 0.7 * air_share
    thresh = BUCKET_YDS.get(pos, 70)
    cleared = sum(1 for g in games if _bucket_yards(g, pos) >= thresh)
    dropbacks = s["attempts"] + s["sacks"] + s["scrambles"]
    designed = max(0.0, s["carries"] - s["scrambles"])
    cp = [(g["cpoe"], g["attempts"]) for g in games if g.get("cpoe") is not None and g.get("attempts")]
    implied = [g["implied"] for g in games if g.get("implied") is not None]
    return {
        "n": n,
        "ppg": s["gbfl"] / n,
        "snap_pct": mean(snaps) if snaps else None,
        "tgt_share": tgt_share,
        "air_share": air_share,
        "wopr": wopr,
        "tpg": s["targets"] / n,
        "rz_tpg": s["rz_tgt"] / n,
        "ez_tpg": s["ez_tgt"] / n,
        "rush_share": _ratio(s["carries"], s["team_carries"]),
        "opp_share": _ratio(s["carries"] + s["targets"], s["team_carries"] + s["team_targets"]),
        "i10_share": _ratio(s["i10_car"], s["team_i10"]),
        # QBs have no targets: their "opportunity" is dropbacks plus carries.
        "opp_pg": ((dropbacks + designed) if pos == "QB" else (s["carries"] + s["targets"])) / n,
        "adot": _ratio(s["air_yds"], s["targets"]) if s["targets"] >= 3 else None,
        "deep_rate": _ratio(s["deep_tgt"], s["targets"]) if s["targets"] >= 3 else None,
        "catch_rate": _ratio(s["rec"], s["targets"]) if s["targets"] >= 3 else None,
        "ypt": _ratio(s["rec_yds"], s["targets"]) if s["targets"] >= 3 else None,
        "rec20_rate": _ratio(s["rec20"], s["targets"]) if s["targets"] >= 3 else None,
        "ypc": _ratio(s["rush_yds"], s["carries"]) if s["carries"] >= 5 else None,
        "run15_rate": _ratio(s["run15"], s["carries"]) if s["carries"] >= 5 else None,
        "run26_rate": _ratio(s["run26"], s["carries"]) if s["carries"] >= 5 else None,
        "bucket_rate": cleared / n,
        "db_pg": dropbacks / n,
        "rush_att_pg": designed / n,
        "qb_rush_share": _ratio(s["rush_yds"], s["team_rush_yds"]),
        "implied": mean(implied) if implied else None,
        "adot_pass": _ratio(s["pass_air"], s["attempts"]) if s["attempts"] >= 20 else None,
        "deep_att_rate": _ratio(s["deep_att"], s["attempts"]) if s["attempts"] >= 20 else None,
        "epa_db": _ratio(s["epa"], dropbacks + designed) if dropbacks >= 20 else None,
        "cpoe": (sum(c * a for c, a in cp) / sum(a for _, a in cp)) if cp and sum(a for _, a in cp) >= 20 else None,
    }


def by_player(games: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for g in games:
        out[g["player_id"]].append(g)
    for gl in out.values():
        gl.sort(key=lambda g: g["week"])
    return out


def pedigree_index(players: list[dict]) -> dict[str, dict]:
    """{gsis_id: {"rookie_season", "draft_round", "draft_pick"}} from nflverse players.csv.
    Undrafted players get round 8 / pick 300 so "round <= 2" checks stay simple."""
    def _int(v, default):
        return int(v) if v not in (None, "", "NA") else default

    return {p["gsis_id"]: {"rookie_season": _int(p.get("rookie_season"), None),
                           "draft_round": _int(p.get("draft_round"), 8),
                           "draft_pick": _int(p.get("draft_pick"), 300)}
            for p in players if p.get("gsis_id")}


def pedigree(index: dict[str, dict], player_id: str, season: int) -> dict:
    """Years in the league (1 = rookie), draft round and pick for one player-season."""
    p = index.get(player_id) or {}
    rs = p.get("rookie_season")
    years = season - rs + 1 if rs else None
    return {"years": years, "round": p.get("draft_round", 8), "pick": p.get("draft_pick", 300),
            "young_high_pick": bool(years and years <= 2 and p.get("draft_round", 8) <= 2)}


def _optional(load, kind: str, season: int) -> list[dict]:
    try:
        return load(kind, season)
    except Exception:
        return []


def load_season_games(season: int) -> list[dict]:
    """build_games over the cached nflverse files for `season`."""
    from nflverse.pull import load

    return build_games(
        season,
        weekly=load("stats_player_week", season),
        team_week=load("stats_team_week", season),
        pbp=load("pbp", season),
        snaps=_optional(load, "snap_counts", season),  # nflverse's 2012 file is empty; QB/K/DST work needs no snaps
        players=load("players"),
        injuries=_optional(load, "injuries", season),  # nflverse has no injury file before 2023
        schedule=load("games"),
    )
