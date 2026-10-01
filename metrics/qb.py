"""Rest-of-season QB projection.

Within-season stats alone barely rank QBs (volume is flat among starters and weekly
scores are noisy). What works, tested leave-one-season-out over 2013–2025, is:

  * points per game so far and the last two seasons' points per game, each weighted by
    how many games it covers (a QB with 3 games leans on last year; with 12 on this year),
  * plus this season's EPA per play, the one efficiency stat that added signal.

Rank correlation with rest-of-season points per game: 0.50 vs 0.40 for points so far.
`qb_row` builds one QB's features at a decision week; the backtest, the weights and the
live app all use it, so they can't drift apart.
"""
from __future__ import annotations

from metrics.features import window_features

QB_FEATURES = ["ppg", "prior_ppg_i", "has_prior", "ppg_x_g", "prior_x_g", "epa_i"]
MIN_ACTIVE = 15.0      # dropbacks + designed runs per game: a QB actually playing
MIN_GAMES = 2
SEASON_GAMES = 17.0
PRIOR_MIN_GAMES = 5    # a prior season counts only with this many games
PRIOR_DECAY = 0.5      # two seasons back counts half as much per game


def prior_production(prior_games: dict[int, list[dict]]) -> dict | None:
    """prior_games = {1: last season's game rows, 2: the season before}. None without any usable season."""
    pts = n = 0.0
    for back, gl in prior_games.items():
        if len(gl) >= PRIOR_MIN_GAMES:
            w = len(gl) * (1.0 if back == 1 else PRIOR_DECAY)
            pts += window_features(gl, "QB")["ppg"] * w
            n += w
    return {"prior_ppg": pts / n, "prior_n": n} if n else None


def qb_row(games_so_far: list[dict], prior_games: dict[int, list[dict]], mean_prior: float) -> dict | None:
    """Features for one QB from his games through the decision week, or None if he isn't a starter."""
    if len(games_so_far) < MIN_GAMES:
        return None
    f = window_features(games_so_far, "QB")
    if f["opp_pg"] < MIN_ACTIVE:
        return None
    pr = prior_production(prior_games)
    prior = pr["prior_ppg"] if pr else mean_prior
    gfrac = len(games_so_far) / SEASON_GAMES
    epa = f.get("epa_db")
    return {
        "g": len(games_so_far), "ppg": f["ppg"], "epa": epa, "epa_i": epa if epa is not None else 0.0,
        "prior_ppg": pr["prior_ppg"] if pr else None, "prior_ppg_i": prior, "has_prior": 1.0 if pr else 0.0,
        "ppg_x_g": f["ppg"] * gfrac, "prior_x_g": prior * (1.0 - gfrac),
    }
