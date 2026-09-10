"""Canonical GBFL scoring. See scoring/SPEC.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


def qb_yard_points(pass_plus_rush: float) -> float:
    y = pass_plus_rush
    if y >= 500:
        return 7.0
    if y >= 200:
        return float(int((y - 200) // 50) + 1)
    return 0.0


def rb_wr_yard_points(rush_plus_rec: float) -> float:
    y = rush_plus_rec
    if y >= 250:
        return 10.0
    if y >= 70:
        return float(int((y - 70) // 20) + 1)
    return 0.0


def te_yard_points(rush_plus_rec: float) -> float:
    y = rush_plus_rec
    if y >= 220:
        return 10.0
    if y >= 40:
        return float(int((y - 40) // 20) + 1)
    return 0.0


def yard_points(pos: str, yards: float) -> float:
    p = (pos or "").upper()
    if p == "QB":
        return qb_yard_points(yards)
    if p == "TE":
        return te_yard_points(yards)
    if p in {"RB", "WR"}:
        return rb_wr_yard_points(yards)
    return 0.0


def passing_td_points(yards: float) -> float:
    """PaTD and WR/RB receiving TDs."""
    pts = 1.0
    if yards >= 61:
        pts += 4
    elif yards >= 46:
        pts += 3
    elif yards >= 31:
        pts += 2
    elif yards >= 16:
        pts += 1
    return pts


def rushing_td_points(yards: float) -> float:
    """RuTD and TE receiving TDs."""
    pts = 1.0
    if yards >= 41:
        pts += 4
    elif yards >= 26:
        pts += 3
    elif yards >= 16:
        pts += 2
    elif yards >= 6:
        pts += 1
    return pts


def receiving_td_points(yards: float, pos: str) -> float:
    if (pos or "").upper() == "TE":
        return rushing_td_points(yards)
    return passing_td_points(yards)


def extra_point_points(made: int = 1) -> float:
    return 0.5 * made


def fg_points(yards: float) -> float:
    if yards >= 60:
        return 3.5
    if yards >= 51:
        return 3.0
    if yards >= 41:
        return 2.0
    if yards >= 1:
        return 1.0
    return 0.0


def two_point_points(n: int = 1) -> float:
    return float(n)


def return_td_points(yards: float) -> float:
    pts = 3.0
    if yards >= 51:
        pts += 2
    elif yards >= 31:
        pts += 1
    return pts


def pa_points(points_against: int) -> float:
    if points_against <= 1:
        return 5.0
    if points_against <= 9:
        return 4.0
    if points_against <= 14:
        return 3.0
    if points_against <= 17:
        return 2.0
    if points_against <= 21:
        return 1.0
    return 0.0


def def_td_points(yards: float) -> float:
    pts = 3.0
    if yards >= 51:
        pts += 2
    elif yards >= 31:
        pts += 1
    return pts


def dst_points(
    *,
    sacks: float = 0,
    ints: float = 0,
    fumbles_recovered: float = 0,
    safeties: float = 0,
    points_against: int = 22,
    def_td_yards: Iterable[float] = (),
) -> float:
    pts = 0.5 * (sacks + ints + fumbles_recovered)
    pts += 3.0 * safeties
    pts += pa_points(points_against)
    pts += sum(def_td_points(y) for y in def_td_yards)
    return pts


@dataclass
class Game:
    pos: str
    pass_yds: float = 0
    rush_yds: float = 0
    rec_yds: float = 0
    pass_td_yards: list[float] = field(default_factory=list)
    rush_td_yards: list[float] = field(default_factory=list)
    rec_td_yards: list[float] = field(default_factory=list)
    two_pt: int = 0
    return_td_yards: list[float] = field(default_factory=list)
    fg_yards: list[float] = field(default_factory=list)
    xp: int = 0
    sacks: float = 0
    ints: float = 0
    fumbles_recovered: float = 0
    safeties: float = 0
    points_against: int = 22
    def_td_yards: list[float] = field(default_factory=list)


def score_game(g: Game) -> float:
    pos = (g.pos or "").upper()
    pts = 0.0
    if pos == "QB":
        pts += qb_yard_points(g.pass_yds + g.rush_yds)
        pts += sum(passing_td_points(y) for y in g.pass_td_yards)
        pts += sum(rushing_td_points(y) for y in g.rush_td_yards)
    elif pos in {"RB", "WR", "TE"}:
        pts += yard_points(pos, g.rush_yds + g.rec_yds)
        pts += sum(rushing_td_points(y) for y in g.rush_td_yards)
        pts += sum(receiving_td_points(y, pos) for y in g.rec_td_yards)
        pts += sum(passing_td_points(y) for y in g.pass_td_yards)
    elif pos == "K":
        pts += sum(fg_points(y) for y in g.fg_yards)
        pts += extra_point_points(g.xp)
    elif pos == "DST":
        pts += dst_points(
            sacks=g.sacks,
            ints=g.ints,
            fumbles_recovered=g.fumbles_recovered,
            safeties=g.safeties,
            points_against=g.points_against,
            def_td_yards=g.def_td_yards,
        )
    pts += two_point_points(g.two_pt)
    pts += sum(return_td_points(y) for y in g.return_td_yards)
    return pts
