"""Expected games a player will be available, from his injury report status.

The backtest measures, per report status, what share of his team's next six
games a player actually played. Those miss rates turn "weeks left" into
"games he'll likely play", so PAR stops grading an injured player like a
healthy one. IR isn't on the weekly report; the live app takes it from the
CBS IR slot / designation and counts those weeks as zero.
"""
from __future__ import annotations

from collections import defaultdict

STATUSES = ("Out", "Doubtful", "Questionable", "Listed", "Healthy")
HORIZON = 6


def status_key(entry: dict | None) -> str:
    """Report entry (metrics.features.injury_index value) -> one of STATUSES.
    "Listed" = on the report with an injury but no game status (usually plays)."""
    if not entry:
        return "Healthy"
    if entry.get("status"):
        return entry["status"]
    return "Listed" if entry.get("injured") else "Healthy"


def team_weeks(schedule: list[dict], season: int) -> dict[str, set[int]]:
    """{team: regular-season weeks it plays} from nflverse games.csv rows."""
    out: dict[str, set[int]] = defaultdict(set)
    for g in schedule:
        if str(g.get("season")) != str(season) or g.get("game_type") != "REG":
            continue
        wk = int(g["week"])
        out[g["home_team"]].add(wk)
        out[g["away_team"]].add(wk)
    return dict(out)


def miss_table(obs: list[dict]) -> dict[str, dict]:
    """obs: [{"status", "team_games", "played", "played_next"}] ->
    {status: {"n", "play_next", "miss_rate"}} where miss_rate = missed / team games
    over the next HORIZON weeks."""
    agg: dict[str, dict] = {s: {"n": 0, "next": 0, "tg": 0, "played": 0} for s in STATUSES}
    for o in obs:
        a = agg[o["status"]]
        a["n"] += 1
        a["next"] += 1 if o["played_next"] else 0
        a["tg"] += o["team_games"]
        a["played"] += o["played"]
    return {
        s: {
            "n": a["n"],
            "play_next": a["next"] / a["n"] if a["n"] else None,
            "miss_rate": 1 - a["played"] / a["tg"] if a["tg"] else None,
        }
        for s, a in agg.items()
    }


def expected_games(status: str, team_games_left: int, table: dict[str, dict], horizon: int = HORIZON) -> float:
    """Games he'll likely play out of his team's remaining games: the status's miss
    rate over the next `horizon`, the healthy rate after that."""
    healthy = table["Healthy"]["miss_rate"] or 0.0
    near_rate = table.get(status, {}).get("miss_rate")
    near_rate = healthy if near_rate is None else near_rate
    near = min(horizon, team_games_left)
    return near * (1 - near_rate) + (team_games_left - near) * (1 - healthy)
