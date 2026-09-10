"""Generates the draft-companion canvas from combined.json + drafted.csv.

The strategy panels are recomputed here from history_2023-2025.csv and
dst_history.csv rather than hardcoded, mirroring scoring_pooled.py,
scoring_stability.py, repeatability_vor.py, tiers_flex.py and dst_analysis.py,
so the canvas cannot drift from those scripts.
"""
import csv
import json
import re

import numpy as np

MY_TEAM = "BUSSONE"
SEASONS = (2023, 2024, 2025)
POSITIONS = ("QB", "RB", "WR", "TE")
FLEX_POS = ("RB", "WR", "TE")
ALIAS = {"kenneth gainwell": "kenny gainwell"}
STATS = ("pass_yds", "pass_td", "rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "total")
TIER_DEPTH = 12
CURVE_MAX = 140

# Straight (non-snake) order, same every round.
DRAFT_ORDER = [
    "BUSSONE",
    "BOLDING",
    "MUCK/UZES",
    "FREEMANS",
    "BAUKOL",
    "ANN",
    "CHEN",
    "FORBES",
    "THROBBER",
    "PRESTON",
]

# ------------------------------------------------------------------ the board
rows = json.load(open("combined.json", encoding="utf-8"))
drafted_rows = list(csv.DictReader(open("drafted.csv", encoding="utf-8")))
teams = sorted({d["owner"] for d in drafted_rows})
assert sorted(DRAFT_ORDER) == teams, f"draft order does not match drafted.csv owners: {teams}"

# Kickers and defenses are deliberately absent from the rankings (merge.py drops
# them), so drafted.csv carries them with the position in the team column:
#   BUSSONE,Brandon Aubrey,K   /   BUSSONE,Seahawks,DST
# They are picks like any other and have to keep the pick counter honest, so
# they ride alongside the board rather than inside it.
EXTRA_POS = ("K", "DST")
file_extras = [
    {"name": d["player"], "pos": d["team"], "owner": d["owner"]}
    for d in drafted_rows
    if d["team"] in EXTRA_POS
]

data = [
    [
        r["rank"],
        r["player"],
        r["team"],
        r["pos"],
        r["age"],
        r["dynasty"],
        r["redraft"],
        r["score"],
        r["status"],
        r["owner"],
    ]
    for r in rows
]


# ------------------------------------------------------------- season history
def norm(name):
    s = re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", name.lower().strip()).replace(".", "")
    return ALIAS.get(s, s)


def load_history(season):
    out = list(csv.DictReader(open(f"history_{season}.csv", encoding="utf-8")))
    for r in out:
        for k in STATS:
            r[k] = int(r[k])
        r["avg"] = float(r["avg"])
        r["games"] = round(r["total"] / r["avg"])
        r["season"] = season
        r["key"] = norm(r["player"])
        r["scrim"] = r["rush_yds"] + r["rec_yds"]
        r["tds"] = r["rush_td"] + r["rec_td"]
        r["qb_yds"] = r["pass_yds"] + r["rush_yds"]
    return out


hist = {s: load_history(s) for s in SEASONS}
allrows = [r for s in SEASONS for r in hist[s]]
idx = {s: {r["key"]: r for r in hist[s]} for s in SEASONS}
bypos = {
    s: {p: sorted((r for r in hist[s] if r["pos"] == p), key=lambda r: -r["total"]) for p in POSITIONS}
    for s in SEASONS
}
posrank = {s: {} for s in SEASONS}
for s in SEASONS:
    for p in POSITIONS:
        for i, r in enumerate(bypos[s][p], 1):
            posrank[s][r["key"]] = i

dst = {}
for r in csv.DictReader(open("dst_history.csv", encoding="utf-8")):
    r["total"] = float(r["total"])
    dst.setdefault(int(r["season"]), []).append(r)
for s in dst:
    dst[s].sort(key=lambda x: -x["total"])

# The 32 defenses are a fixed, known list, so the canvas offers them as a
# dropdown instead of free text. Kickers get free text; there is no kicker data.
nfl_defenses = sorted({d["team"] for s in SEASONS for d in dst[s]})


# ----------------------------------------------------------- scoring geometry
def fit(group, cols, season_effects=False):
    """OLS of points/game on stats/game. Mirrors scoring_pooled / scoring_stability."""
    g = np.array([r["games"] for r in group], float)
    parts = [np.array([r[c] for r in group], float) / g for c in cols]
    if season_effects:
        for s in SEASONS[1:]:
            parts.append(np.array([1.0 if r["season"] == s else 0.0 for r in group]))
    parts.append(np.ones(len(group)))
    X = np.column_stack(parts)
    y = np.array([r["avg"] for r in group], float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    r2 = 1 - ((y - X @ coef) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return coef, float(r2)


scoring, pooled_coef = [], {}
for p in FLEX_POS:
    grp = [r for r in allrows if r["pos"] == p and r["games"] >= 8]
    c, r2 = fit(grp, ["scrim", "tds", "rec"], season_effects=True)
    pooled_coef[p] = c
    ypp = 1 / c[0]
    scoring.append(
        {
            "pos": p,
            "n": len(grp),
            "ydsPerPoint": round(ypp, 1),
            "ptsPerTd": round(float(c[1]), 2),
            "ptsPerRec": round(float(c[2]), 3),
            "tdInYards": round(float(c[1] * ypp)),
            "r2": round(r2, 3),
        }
    )

scoring_season = []
for p in FLEX_POS:
    for s in SEASONS:
        grp = [r for r in hist[s] if r["pos"] == p and r["games"] >= 8]
        c, _ = fit(grp, ["scrim", "tds", "rec"])
        ypp = 1 / c[0]
        scoring_season.append(
            {
                "pos": p,
                "season": s,
                "ydsPerPoint": round(ypp, 1),
                "ptsPerTd": round(float(c[1]), 2),
                "ptsPerRec": round(float(c[2]), 3),
                "tdInYards": round(float(c[1] * ypp)),
            }
        )

# The TE premium: price one identical stat line at each position.
te_premium = []
for yds, tds in ((1200, 8), (900, 6), (700, 5), (500, 3)):
    as_wr = yds * pooled_coef["WR"][0] + tds * pooled_coef["WR"][1]
    as_te = yds * pooled_coef["TE"][0] + tds * pooled_coef["TE"][1]
    te_premium.append(
        {
            "line": f"{yds} yds, {tds} TD",
            "asWr": round(float(as_wr), 1),
            "asTe": round(float(as_te), 1),
            "edge": round(float(as_te - as_wr), 1),
        }
    )

te_premium_season = []
for s in SEASONS:
    wr = next(x for x in scoring_season if x["pos"] == "WR" and x["season"] == s)
    te = next(x for x in scoring_season if x["pos"] == "TE" and x["season"] == s)
    as_wr = 900 / wr["ydsPerPoint"] + 6 * wr["ptsPerTd"]
    as_te = 900 / te["ydsPerPoint"] + 6 * te["ptsPerTd"]
    te_premium_season.append({"season": s, "edge": round(as_te - as_wr, 1)})


# --------------------------------------------------------------- repeatability
stick, stick_pairs = {}, []
for p in POSITIONS:
    rs = []
    for a, b in ((2023, 2024), (2024, 2025)):
        both = [k for k in idx[a] if k in idx[b] and idx[a][k]["pos"] == p and idx[b][k]["pos"] == p]
        if len(both) < 5:
            continue
        r = float(np.corrcoef([idx[a][k]["total"] for k in both], [idx[b][k]["total"] for k in both])[0, 1])
        rs.append(r)
        stick_pairs.append({"pos": p, "pair": f"{a}\u2013{b}", "n": len(both), "r": round(r, 2)})
    stick[p] = round(float(np.mean(rs)), 2)

dst_teams = sorted({d["team"] for d in dst[2023]})
dst_tbl = {s: {d["team"]: d["total"] for d in dst[s]} for s in SEASONS}
dst_rs = []
for a, b in ((2023, 2024), (2024, 2025)):
    r = float(np.corrcoef([dst_tbl[a][t] for t in dst_teams], [dst_tbl[b][t] for t in dst_teams])[0, 1])
    dst_rs.append(r)
    stick_pairs.append({"pos": "DST", "pair": f"{a}\u2013{b}", "n": len(dst_teams), "r": round(r, 2)})
dst_gap_r = float(
    np.corrcoef([dst_tbl[2023][t] for t in dst_teams], [dst_tbl[2025][t] for t in dst_teams])[0, 1]
)
stick["DST"] = round(float(np.mean(dst_rs)), 2)


# ------------------------------------------------- replacement levels and VOR
flex_repl = {}
for s in SEASONS:
    pool = sorted(
        bypos[s]["RB"] + bypos[s]["WR"] + bypos[s]["TE"], key=lambda x: -x["total"]
    )
    tail = [(i + 1, pool[i]["total"]) for i in range(29, len(pool))]
    lr = np.polyfit(np.log([t[0] for t in tail]), np.log([t[1] for t in tail]), 1)
    flex_repl[s] = float(np.exp(np.polyval(lr, np.log(70))))

SLOTS_VOR = (1, 3, 5, 10)
vor = {}
for p in FLEX_POS:
    vor[p] = [
        round(float(np.mean([bypos[s][p][i - 1]["total"] - flex_repl[s] for s in SEASONS if len(bypos[s][p]) >= i])))
        for i in SLOTS_VOR
    ]
vor["QB"] = [
    round(float(np.mean([bypos[s]["QB"][i - 1]["total"] - bypos[s]["QB"][9]["total"] for s in SEASONS])))
    for i in SLOTS_VOR
]
vor["DST"] = [
    round(float(np.mean([dst[s][i - 1]["total"] - dst[s][9]["total"] for s in SEASONS])))
    for i in SLOTS_VOR
]

repl = {
    "flex": round(float(np.mean(list(flex_repl.values()))), 1),
    "qb": round(float(np.mean([bypos[s]["QB"][9]["total"] for s in SEASONS])), 1),
    "dst": round(float(np.mean([dst[s][9]["total"] for s in SEASONS])), 1),
}

# Three-season mean points at each positional finish rank, extended past the
# data floor with the same power-law tail fit used for flex replacement.
curve, curve_depth = {}, {}
for p in POSITIONS:
    depth = min(len(bypos[s][p]) for s in SEASONS)
    means = [float(np.mean([bypos[s][p][i - 1]["total"] for s in SEASONS])) for i in range(1, depth + 1)]
    start = max(4, depth // 2)
    lr = np.polyfit(np.log(np.arange(start, depth + 1)), np.log(means[start - 1 :]), 1)
    ext = list(means) + [
        float(np.exp(np.polyval(lr, np.log(k)))) for k in range(depth + 1, CURVE_MAX + 1)
    ]
    curve[p] = [round(v, 1) for v in ext]
    curve_depth[p] = depth


# ---------------------------------------------------------------- tiers, mix
cliffs = []
for p in POSITIONS:
    for s in SEASONS:
        v = [r["total"] for r in bypos[s][p][:TIER_DEPTH]]
        i = max(range(len(v) - 1), key=lambda j: v[j] - v[j + 1])
        cliffs.append(
            {"pos": p, "season": s, "from": i + 1, "drop": v[i] - v[i + 1], "share": round(100 * (v[i] - v[i + 1]) / v[i])}
        )

drops = {
    p: [
        round(float(np.mean([bypos[s][p][i - 1]["total"] - bypos[s][p][i]["total"] for s in SEASONS])), 1)
        for i in range(1, TIER_DEPTH)
    ]
    for p in POSITIONS
}

flexmix = []
for s in SEASONS:
    pool = sorted(bypos[s]["RB"] + bypos[s]["WR"] + bypos[s]["TE"], key=lambda x: -x["total"])[:20]
    c = {"RB": 0, "WR": 0, "TE": 0}
    for r in pool:
        c[r["pos"]] += 1
    flexmix.append({"season": s, "rb": c["RB"], "wr": c["WR"], "te": c["TE"], "cut": pool[-1]["total"]})


# ------------------------------------------------------------------------ DST
def overall_rank(pts, season):
    return sum(1 for r in hist[season] if r["total"] > pts) + 1


dst_rows = []
for s in SEASONS:
    d = [x["total"] for x in dst[s]]
    dst_rows.append(
        {
            "season": s,
            "top": dst[s][0]["team"],
            "d1": round(d[0]),
            "d5": round(d[4]),
            "d10": round(d[9]),
            "d1Overall": overall_rank(d[0], s),
            "d10Overall": overall_rank(d[9], s),
            "wr1": bypos[s]["WR"][0]["total"],
            "wrBeaten": sum(1 for r in bypos[s]["WR"] if r["total"] < d[9]),
            "wrTotal": len(bypos[s]["WR"]),
        }
    )
dst_corr = [
    {"pair": "2023 \u2192 2024", "r": round(dst_rs[0], 2)},
    {"pair": "2024 \u2192 2025", "r": round(dst_rs[1], 2)},
    {"pair": "2023 \u2192 2025", "r": round(dst_gap_r, 2)},
]

trunc = []
for s in SEASONS:
    counts = {p: len(bypos[s][p]) for p in POSITIONS}
    flex = counts["RB"] + counts["WR"] + counts["TE"]
    trunc.append(
        {
            "season": s,
            "qb": counts["QB"],
            "rb": counts["RB"],
            "wr": counts["WR"],
            "te": counts["TE"],
            "flex": flex,
            "short": max(0, 70 - flex),
            "floor": min(r["total"] for r in bypos[s]["RB"] + bypos[s]["WR"] + bypos[s]["TE"]),
            "flexRepl": round(flex_repl[s]),
        }
    )

# Per-player three-season record, keyed the way the board is keyed.
finishes = {}
for r0 in rows:
    k = norm(r0["player"])
    fin = [
        [s, posrank[s][k], idx[s][k]["total"]]
        for s in SEASONS
        if k in idx[s] and idx[s][k]["pos"] == r0["pos"]
    ]
    if fin:
        finishes[f'{r0["player"]}|{r0["team"]}'] = fin


CANVAS = """import { useMemo } from "react";
import {
  BarChart,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  LineChart,
  Pill,
  Row,
  Select,
  Spacer,
  Stack,
  Stat,
  Table,
  Text,
  TextArea,
  TextInput,
  Toggle,
  useCanvasAction,
  useCanvasState,
  useHostTheme,
} from "cursor/canvas";

type PlayerRow = {
  rank: number;
  player: string;
  team: string;
  pos: string;
  age: string;
  dynasty: number | null;
  redraft: number | null;
  score: number;
  status: string;
  owner: string;
};

const MY_TEAM = "__ME__";
const TEAMS: string[] = __TEAMS__;
const DEFAULT_ORDER: string[] = __ORDER__;
const DYNASTY_SIZE = __DYN__;
const REDRAFT_SIZE = __RED__;

/**
 * Kickers and defenses are not ranked and never enter the board \\u2014 merge.py
 * drops them from both source lists on purpose. They are still real picks, so
 * they live in a parallel list that shares the pick counter, the draft order,
 * the roster and the undo stack, but touches nothing that is ranked or scored.
 *
 * drafted.csv carries them with the position in the team column, e.g.
 * `BUSSONE,Brandon Aubrey,K` and `BUSSONE,Seahawks,DST`.
 */
type Extra = { id: string; name: string; pos: string; owner: string };
const EXTRA_POS = ["K", "DST"];
const NFL_DEFENSES: string[] = __DEFENSES__;
const FILE_EXTRAS: { name: string; pos: string; owner: string }[] = __FILEEXTRAS__;
const FILE_PICKS = __FILEPICKS__;

const extraId = (pos: string, name: string) => `${pos}:${name}`;

const RAW: [number, string, string, string, string, number | null, number | null, number, string, string][] = __DATA__;

const ROWS: PlayerRow[] = RAW.map(
  ([rank, player, team, pos, age, dynasty, redraft, score, status, owner]) => ({
    rank,
    player,
    team,
    pos,
    age,
    dynasty,
    redraft,
    score,
    status,
    owner,
  }),
);

/* ------------------------------------------------------------------ analysis
   Every figure below is recomputed by make_canvas.py from history_2023.csv,
   history_2024.csv, history_2025.csv and dst_history.csv. Nothing is typed by
   hand, so these panels track the analysis scripts exactly.                  */

type Scoring = {
  pos: string;
  n: number;
  ydsPerPoint: number;
  ptsPerTd: number;
  ptsPerRec: number;
  tdInYards: number;
  r2: number;
};
type ScoringSeason = {
  pos: string;
  season: number;
  ydsPerPoint: number;
  ptsPerTd: number;
  ptsPerRec: number;
  tdInYards: number;
};

const SEASONS: number[] = __SEASONS__;
const SCORING: Scoring[] = __SCORING__;
const SCORING_SEASON: ScoringSeason[] = __SCORINGSEASON__;
const TE_PREMIUM: { line: string; asWr: number; asTe: number; edge: number }[] = __TEPREM__;
const TE_PREMIUM_SEASON: { season: number; edge: number }[] = __TEPREMSEASON__;
const STICK: Record<string, number> = __STICK__;
const STICK_PAIRS: { pos: string; pair: string; n: number; r: number }[] = __STICKPAIRS__;
const VOR: Record<string, number[]> = __VOR__;
const VOR_SLOTS = [1, 3, 5, 10];
const REPL: { flex: number; qb: number; dst: number } = __REPL__;
const CURVE: Record<string, number[]> = __CURVE__;
const CURVE_DEPTH: Record<string, number> = __CURVEDEPTH__;
const CLIFFS: { pos: string; season: number; from: number; drop: number; share: number }[] = __CLIFFS__;
const DROPS: Record<string, number[]> = __DROPS__;
const FLEXMIX: { season: number; rb: number; wr: number; te: number; cut: number }[] = __FLEXMIX__;
const DST_ROWS: {
  season: number;
  top: string;
  d1: number;
  d5: number;
  d10: number;
  d1Overall: number;
  d10Overall: number;
  wr1: number;
  wrBeaten: number;
  wrTotal: number;
}[] = __DSTROWS__;
const DST_CORR: { pair: string; r: number }[] = __DSTCORR__;
const TRUNC: {
  season: number;
  qb: number;
  rb: number;
  wr: number;
  te: number;
  flex: number;
  short: number;
  floor: number;
  flexRepl: number;
}[] = __TRUNC__;
const FINISHES: Record<string, [number, number, number][]> = __FINISHES__;

/* --------------------------------------------------------------- league setup */

const BOARD_POS = ["RB", "WR", "TE", "QB"];
const CAPS: Record<string, number> = { QB: 2, RB: 5, WR: 6, TE: 2, K: 2, DST: 2 };
const FLEX_SLOTS = ["FLEX1", "FLEX2", "FLEX3", "FLEX4"];
const LINEUP: { id: string; label: string; accepts: string[] }[] = [
  { id: "QB", label: "QB", accepts: ["QB"] },
  { id: "RB", label: "RB", accepts: ["RB"] },
  { id: "WR", label: "WR", accepts: ["WR"] },
  { id: "TE", label: "TE", accepts: ["TE"] },
  { id: "FLEX1", label: "FLEX", accepts: ["RB", "WR", "TE"] },
  { id: "FLEX2", label: "FLEX", accepts: ["RB", "WR", "TE"] },
  { id: "FLEX3", label: "FLEX", accepts: ["RB", "WR", "TE"] },
  { id: "FLEX4", label: "FLEX", accepts: ["RB", "WR", "TE"] },
  { id: "K", label: "K", accepts: ["K"] },
  { id: "DST", label: "DST", accepts: ["DST"] },
];
/** K and DST are not on this board \\u2014 merge.py drops them from both source lists. */
const OFF_BOARD = ["K", "DST"];

const keyOf = (r: PlayerRow) => `${r.player}|${r.team}`;
const rankText = (v: number | null) => (v === null ? "\\u2014" : String(v));
const signed = (v: number) => (v > 0 ? `+${Math.round(v)}` : String(Math.round(v)));

/** Replacement baseline a position's points should be measured against. */
function replacementFor(pos: string) {
  return pos === "QB" ? REPL.qb : REPL.flex;
}

/** Three-season mean points for the k-th best player at a position. */
function curveAt(pos: string, k: number) {
  const c = CURVE[pos];
  if (!c) return 0;
  const i = Math.min(Math.max(Math.round(k), 1), c.length);
  return c[i - 1];
}

/** Straight order: the same sequence repeats every round, no snake reversal. */
function teamOnClock(order: string[], pickIndex: number) {
  if (order.length === 0) return MY_TEAM;
  return order[pickIndex % order.length];
}

/** Overall pick numbers for this team's next `n` turns, from `pickIndex`. */
function upcomingPicks(order: string[], pickIndex: number, n: number) {
  const out: number[] = [];
  if (order.length === 0) return out;
  for (let i = pickIndex; i < pickIndex + order.length * (n + 1) && out.length < n; i++) {
    if (order[i % order.length] === MY_TEAM) out.push(i + 1);
  }
  return out;
}

/**
 * Assign a roster to the starting lineup: dedicated slots first, leftovers into
 * FLEX. Returns which slot ids are covered.
 */
function fillLineup(counts: Record<string, number>) {
  const left: Record<string, number> = { ...counts };
  const filled: Record<string, boolean> = {};
  for (const slot of LINEUP) {
    if (slot.accepts.length !== 1) continue;
    const p = slot.accepts[0];
    if ((left[p] ?? 0) > 0) {
      left[p] -= 1;
      filled[slot.id] = true;
    }
  }
  for (const slot of LINEUP) {
    if (slot.accepts.length === 1) continue;
    const p = slot.accepts.find((x) => (left[x] ?? 0) > 0);
    if (p) {
      left[p] -= 1;
      filled[slot.id] = true;
    }
  }
  return filled;
}

export default function DraftCompanion() {
  const theme = useHostTheme();
  const dispatch = useCanvasAction();

  const [tab, setTab] = useCanvasState("tabV1", "pick");
  const [pos, setPos] = useCanvasState("pos", "ALL");
  const [query, setQuery] = useCanvasState("query", "");
  const [sort, setSort] = useCanvasState("sort", "combined");
  const [showTaken, setShowTaken] = useCanvasState("showTaken", false);
  const [cliffPos, setCliffPos] = useCanvasState("cliffPosV1", "RB");

  // Picks made inside the canvas, layered on top of the baked-in drafted.csv.
  // "" marks a player as explicitly available again.
  const [overrides, setOverrides] = useCanvasState<Record<string, string>>("overrides", {});
  const [log, setLog] = useCanvasState<string[]>("log", []);
  const [order, setOrder] = useCanvasState<string[]>("orderV2", DEFAULT_ORDER);
  const [manualTeam, setManualTeam] = useCanvasState("manualTeamV2", MY_TEAM);
  const [followOrder, setFollowOrder] = useCanvasState("followOrderV2", true);
  const [orderMode, setOrderMode] = useCanvasState("orderMode", false);
  const [pendingOrder, setPendingOrder] = useCanvasState<string[]>("pendingOrder", []);

  // Same overlay pattern as `overrides`, for the unranked K/DST picks:
  // "" means released, anything else is the owning team, absent means the value
  // baked in from drafted.csv wins.
  const [extraOwners, setExtraOwners] = useCanvasState<Record<string, string>>("extraOwnersV1", {});
  const [extraPos, setExtraPos] = useCanvasState("extraPosV1", "DST");
  const [extraName, setExtraName] = useCanvasState("extraNameV1", "");
  const [extraDefense, setExtraDefense] = useCanvasState("extraDefenseV1", "");
  const [extraOwner, setExtraOwner] = useCanvasState("extraOwnerV1", "");

  const ownerOf = (r: PlayerRow) => {
    const o = overrides[keyOf(r)];
    return o === undefined ? r.owner : o;
  };

  const board = useMemo(() => ROWS.map((r) => ({ ...r, owner: ownerOf(r) })), [overrides]);

  const available = board.filter((r) => !r.owner);
  const drafted = board.filter((r) => r.owner);
  const myRoster = drafted.filter((r) => r.owner === MY_TEAM).sort((a, b) => a.rank - b.rank);

  /* ---- unranked K/DST picks, resolved the same way ranked picks are ------ */

  const extras: Extra[] = useMemo(() => {
    const base: Record<string, string> = {};
    for (const e of FILE_EXTRAS) base[extraId(e.pos, e.name)] = e.owner;
    const ids = Array.from(new Set([...Object.keys(base), ...Object.keys(extraOwners)]));
    return ids
      .map((id) => {
        const cut = id.indexOf(":");
        return {
          id,
          pos: id.slice(0, cut),
          name: id.slice(cut + 1),
          owner: extraOwners[id] ?? base[id] ?? "",
        };
      })
      .filter((e) => e.owner)
      .sort((a, b) => (a.pos === b.pos ? a.name.localeCompare(b.name) : a.pos.localeCompare(b.pos)));
  }, [extraOwners]);

  const myExtras = extras.filter((e) => e.owner === MY_TEAM);

  // Every pick counts, ranked or not, or the clock drifts out of sync.
  const totalPicks = drafted.length + extras.length;
  // Derived from who is actually owned, so undo and release roll the clock back too.
  const nextPickIndex = totalPicks;
  const round = Math.floor(nextPickIndex / order.length) + 1;
  const slot = (nextPickIndex % order.length) + 1;
  const activeTeam = followOrder ? teamOnClock(order, nextPickIndex) : manualTeam;
  const canvasPicks = totalPicks - FILE_PICKS;

  const myCounts: Record<string, number> = {};
  for (const r of myRoster) myCounts[r.pos] = (myCounts[r.pos] ?? 0) + 1;
  for (const e of myExtras) myCounts[e.pos] = (myCounts[e.pos] ?? 0) + 1;
  const lineupFilled = fillLineup(myCounts);
  const startersLeft = LINEUP.filter((s) => !lineupFilled[s.id]);

  /* ---- live positional supply ------------------------------------------- */

  const goneByPos: Record<string, number> = {};
  for (const r of drafted) goneByPos[r.pos] = (goneByPos[r.pos] ?? 0) + 1;
  const availByPos: Record<string, PlayerRow[]> = {};
  for (const p of BOARD_POS) availByPos[p] = available.filter((r) => r.pos === p);

  const opponentPicks = Math.max(order.length - 1, 0);
  const burn: Record<string, number> = {};
  for (const p of BOARD_POS) {
    burn[p] = drafted.length > 0 ? (goneByPos[p] ?? 0) / drafted.length : 0;
  }

  const myPicks = upcomingPicks(order, nextPickIndex, 6);

  /** What each position costs you if you wait one full turn of the order. */
  const waiting = BOARD_POS.map((p) => {
    const gone = goneByPos[p] ?? 0;
    const goneNext = burn[p] * opponentPicks;
    const nowPts = curveAt(p, gone + 1);
    const laterPts = curveAt(p, gone + 1 + goneNext);
    const best = availByPos[p][0];
    return {
      pos: p,
      gone,
      perRound: burn[p] * order.length,
      best,
      nowPts,
      laterPts,
      cost: nowPts - laterPts,
      vor: nowPts - replacementFor(p),
      extrapolated: gone + 1 > CURVE_DEPTH[p],
    };
  });
  const maxCost = Math.max(...waiting.map((w) => w.cost), 0.001);

  /**
   * Greedy plan over the next few turns: at each of my picks take the position
   * with the most value over replacement that still fills a starting slot, then
   * advance the board by the observed positional burn rate.
   */
  const plan = useMemo(() => {
    const counts: Record<string, number> = { ...myCounts };
    const used: Record<string, number> = {};
    for (const p of BOARD_POS) used[p] = 0;
    const out: { pick: number; pos: string; player?: PlayerRow; vor: number; reason: string }[] = [];

    for (const pick of myPicks) {
      const filled = fillLineup(counts);
      const openFlex = FLEX_SLOTS.filter((s) => !filled[s]).length;
      const cands = BOARD_POS.filter((p) => {
        if ((counts[p] ?? 0) >= CAPS[p]) return false;
        const dedicated = !filled[p];
        const flexEligible = p !== "QB" && openFlex > 0;
        return dedicated || flexEligible;
      });
      if (cands.length === 0) break;

      let bestPos = cands[0];
      let bestVor = -Infinity;
      for (const p of cands) {
        const rankNow = (goneByPos[p] ?? 0) + used[p] + 1;
        const v = curveAt(p, rankNow) - replacementFor(p);
        if (v > bestVor) {
          bestVor = v;
          bestPos = p;
        }
      }
      const filledNow = fillLineup(counts);
      const dedicated = !filledNow[bestPos];
      out.push({
        pick,
        pos: bestPos,
        player: availByPos[bestPos][Math.floor(used[bestPos])],
        vor: bestVor,
        reason: dedicated ? `fills the ${bestPos} slot` : "fills a FLEX slot",
      });
      counts[bestPos] = (counts[bestPos] ?? 0) + 1;
      used[bestPos] += 1;
      for (const p of BOARD_POS) used[p] += burn[p] * opponentPicks;
    }
    return out;
  }, [overrides, order]);

  const headline = plan[0];
  const headlineCandidates = headline ? availByPos[headline.pos].slice(0, 3) : [];
  const headlineWait = waiting.find((w) => w.pos === headline?.pos);

  /* ---- actions ----------------------------------------------------------- */

  const draftTo = (r: PlayerRow, team: string) => {
    const k = keyOf(r);
    setOverrides({ ...overrides, [k]: team });
    setLog([...log, k]);
  };

  const release = (r: PlayerRow) => {
    const k = keyOf(r);
    setOverrides({ ...overrides, [k]: "" });
    setLog([...log, k]);
  };

  /* K/DST entries share the undo stack with ranked picks. Ranked log entries are
     `player|team`; unranked ones are prefixed with "~", which no player name can
     start with, so old logs keep working unchanged. */
  const setExtra = (id: string, owner: string) => {
    setExtraOwners({ ...extraOwners, [id]: owner });
    setLog([...log, `~${id}`]);
  };

  const pendingOwner = extraOwner || activeTeam;
  // Commas would break the drafted.csv round trip, so they never make it in.
  const pendingName = (extraPos === "DST" ? extraDefense : extraName).split(",").join(" ").trim();
  const pendingDuplicate = pendingName !== "" && extras.some((e) => e.id === extraId(extraPos, pendingName));
  const pendingAtCap =
    extras.filter((e) => e.owner === pendingOwner && e.pos === extraPos).length >= CAPS[extraPos];
  const canAddExtra = pendingName !== "" && !pendingDuplicate && !pendingAtCap;
  const freeDefenses = NFL_DEFENSES.filter(
    (d) => !extras.some((e) => e.pos === "DST" && e.name === d),
  );

  const addExtra = () => {
    if (!canAddExtra) return;
    setExtra(extraId(extraPos, pendingName), pendingOwner);
    setExtraName("");
    setExtraDefense("");
  };

  const undo = () => {
    if (log.length === 0) return;
    const last = log[log.length - 1];
    if (last.startsWith("~")) {
      const next = { ...extraOwners };
      delete next[last.slice(1)];
      setExtraOwners(next);
    } else {
      const next = { ...overrides };
      delete next[last];
      setOverrides(next);
    }
    setLog(log.slice(0, -1));
  };

  const resetToFile = () => {
    setOverrides({});
    setExtraOwners({});
    setLog([]);
  };

  const clickTeam = (t: string) => {
    if (!orderMode) {
      setManualTeam(t);
      setFollowOrder(false);
      return;
    }
    if (pendingOrder.includes(t)) return;
    const nextOrder = [...pendingOrder, t];
    if (nextOrder.length === TEAMS.length) {
      setOrder(nextOrder);
      setPendingOrder([]);
      setOrderMode(false);
    } else {
      setPendingOrder(nextOrder);
    }
  };

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    let out = board.filter((r) => {
      if (!showTaken && r.owner) return false;
      if (pos !== "ALL" && r.pos !== pos) return false;
      if (q && !r.player.toLowerCase().includes(q) && !r.team.toLowerCase().includes(q)) return false;
      return true;
    });
    if (sort === "dynasty") {
      out = [...out].sort((a, b) => (a.dynasty ?? 9999) - (b.dynasty ?? 9999));
    } else if (sort === "redraft") {
      out = [...out].sort((a, b) => (a.redraft ?? 9999) - (b.redraft ?? 9999));
    } else if (sort === "gap") {
      const gap = (r: PlayerRow) =>
        r.dynasty !== null && r.redraft !== null ? Math.abs(r.redraft - r.dynasty) : -1;
      out = [...out].sort((a, b) => gap(b) - gap(a));
    }
    return out;
  }, [board, pos, query, sort, showTaken]);

  /* The one path back to drafted.csv. K/DST rows go out in the same shape the
     generator reads back in, so they survive a regenerate exactly like ranked
     picks do. */
  const exportCsv = useMemo(() => {
    const lines = [
      ...drafted.map((r) => ({ owner: r.owner, player: r.player, team: r.team, rank: r.rank })),
      ...extras.map((e) => ({ owner: e.owner, player: e.name, team: e.pos, rank: 1e9 })),
    ];
    lines.sort((a, b) => (a.owner === b.owner ? a.rank - b.rank : a.owner.localeCompare(b.owner)));
    return "owner,player,team\\n" + lines.map((l) => `${l.owner},${l.player},${l.team}`).join("\\n");
  }, [drafted, extras]);

  const recent = [...log]
    .reverse()
    .slice(0, 8)
    .map((k) => {
      if (k.startsWith("~")) {
        const e = extras.find((x) => x.id === k.slice(1));
        const cut = k.indexOf(":");
        return e
          ? { player: e.name, pos: e.pos, owner: e.owner }
          : { player: k.slice(cut + 1), pos: k.slice(1, cut), owner: "" };
      }
      const r = board.find((x) => keyOf(x) === k);
      return r ? { player: r.player, pos: r.pos, owner: r.owner } : null;
    })
    .filter((x): x is { player: string; pos: string; owner: string } => x !== null);

  const gapCell = (r: PlayerRow) => {
    const d = r.redraft! - r.dynasty!;
    return (
      <Text as="span" style={{ color: d > 0 ? theme.accent.primary : theme.text.secondary }}>
        {d > 0 ? `+${d}` : String(d)}
      </Text>
    );
  };

  /** "RB2 / RB18 / RB15" \\u2014 the player's finish at his position each season. */
  const recordOf = (r: PlayerRow) => {
    const f = FINISHES[keyOf(r)];
    if (!f || f.length === 0) return null;
    return f.map(([, rk]) => `${r.pos}${rk}`).join(" \\u00b7 ");
  };

  const recordCell = (r: PlayerRow) => {
    const t = recordOf(r);
    return (
      <Text as="span" size="small" tone={t ? "secondary" : "quaternary"}>
        {t ?? "no top-100 season"}
      </Text>
    );
  };

  return (
    <Stack gap={20} style={{ padding: 24 }}>
      <Stack gap={4}>
        <H1>Draft companion</H1>
        <Text tone="secondary" size="small">
          10 teams \\u00b7 1 QB, 1 RB, 1 WR, 1 TE, 4 FLEX, 1 K, 1 DST \\u00b7 straight order, no snake, {MY_TEAM}{" "}
          picks first every round. Rankings are FantasyPros 2026 dynasty ECR and redraft consensus ECR
          weighted equally; strategy panels come from 2023\\u20132025 actual scoring.
        </Text>
      </Stack>

      {/* ------------------------------------------------------- on the clock */}
      <div
        style={{
          background: theme.fill.tertiary,
          border: `1px solid ${theme.stroke.tertiary}`,
          borderRadius: 8,
          padding: 16,
        }}
      >
        <Stack gap={12}>
          <Row gap={16} align="center" wrap>
            <Text as="span" style={{ fontSize: 22, fontWeight: 600 }}>
              Round {round} \\u00b7 Pick {nextPickIndex + 1}
            </Text>
            <Text as="span" size="small" tone="secondary">
              slot {slot} of {order.length}
            </Text>
            <div
              style={{
                padding: "2px 10px",
                borderRadius: 4,
                background: activeTeam === MY_TEAM ? theme.accent.primary : theme.fill.secondary,
                color: activeTeam === MY_TEAM ? theme.text.onAccent : theme.text.secondary,
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              {activeTeam} on the clock
            </div>
            <Spacer />
            <Text as="span" size="small" tone="tertiary">
              {FILE_PICKS} picks from drafted.csv
              {canvasPicks > 0 ? ` + ${canvasPicks} logged here` : ""}
            </Text>
            {canvasPicks > 0 ? (
              <Button variant="ghost" onClick={resetToFile}>
                Reset to file (pick {FILE_PICKS + 1})
              </Button>
            ) : null}
          </Row>

          <Row gap={8} align="center" wrap>
            <Text weight="semibold" size="small">
              {orderMode
                ? `Click teams in pick order (${pendingOrder.length}/${TEAMS.length})`
                : "Assign pick to"}
            </Text>
            {(orderMode ? TEAMS.filter((t) => !pendingOrder.includes(t)) : TEAMS).map((t) => (
              <span key={t}>
                <Pill active={!orderMode && activeTeam === t} onClick={() => clickTeam(t)}>
                  {t}
                </Pill>
              </span>
            ))}
          </Row>

          <Row gap={12} align="center" wrap>
            <Button variant="secondary" disabled={log.length === 0} onClick={undo}>
              Undo last ({log.length})
            </Button>
            <Row gap={6} align="center">
              <Text size="small" tone="secondary">
                Follow draft order
              </Text>
              <Toggle checked={followOrder} onChange={setFollowOrder} />
            </Row>
            <Button
              variant="ghost"
              onClick={() => {
                setPendingOrder([]);
                setOrderMode(!orderMode);
              }}
            >
              {orderMode ? "Cancel" : "Set pick order"}
            </Button>
            <Text size="small" tone="tertiary">
              Order: {order.join(" \\u2192 ")}
            </Text>
          </Row>
        </Stack>
      </div>

      <Row gap={8} align="center" wrap>
        {[
          { id: "pick", label: `This pick (${nextPickIndex + 1})` },
          { id: "board", label: "Full board" },
          { id: "why", label: "Why \\u2014 three seasons of scoring" },
        ].map((t) => (
          <span key={t.id}>
            <Pill active={tab === t.id} onClick={() => setTab(t.id)}>
              {t.label}
            </Pill>
          </span>
        ))}
      </Row>

      {/* =================================================== TAB: this pick */}
      {tab === "pick" ? (
        <Stack gap={24}>
          <Grid columns="1.35fr 1fr" gap={16} align="start">
            <Stack gap={12}>
              {headline && headline.player ? (
                <Stack gap={10}>
                  <Row gap={10} align="center" wrap>
                    <Text as="span" style={{ fontSize: 18, color: theme.text.secondary }}>
                      Take a
                    </Text>
                    <Text as="span" style={{ fontSize: 26, fontWeight: 700, color: theme.accent.primary }}>
                      {headline.pos}
                    </Text>
                    <Text as="span" size="small" tone="secondary">
                      {signed(headline.vor)} pts over a replacement starter, and it {headline.reason}
                    </Text>
                  </Row>
                  {headlineWait ? (
                    <Text size="small" tone="secondary">
                      {headlineWait.gone} {headline.pos}s are already gone, at{" "}
                      {headlineWait.perRound.toFixed(1)} per round. Waiting one turn moves you from the
                      best {headline.pos} left on the board to roughly the number{" "}
                      {Math.round(headlineWait.gone + 1 + burn[headline.pos] * opponentPicks)} back at the
                      position \\u2014 historically about {Math.round(headlineWait.cost)} fewer points across a
                      season.
                    </Text>
                  ) : null}
                  <Table
                    headers={["Take now", "Ovr", "Team", "Three-season finishes", ""]}
                    columnAlign={["left", "right", "left", "left", "right"]}
                    rows={headlineCandidates.map((r) => [
                      <Text as="span" weight="semibold">
                        {r.player}
                      </Text>,
                      r.rank,
                      r.team,
                      recordCell(r),
                      <Button variant="primary" onClick={() => draftTo(r, activeTeam)}>
                        Draft
                      </Button>,
                    ])}
                  />
                </Stack>
              ) : (
                <Callout tone="success" title="Every startable slot on this board is filled">
                  QB, RB, WR, TE and all four FLEX spots are covered. What is left is a kicker and a
                  defense, neither of which is ranked \\u2014 enter them below \\u2014 plus bench depth.
                </Callout>
              )}
            </Stack>

            <Card>
              <CardHeader trailing={<Pill size="sm">greedy</Pill>}>Plan for your next turns</CardHeader>
              <CardBody>
                <Stack gap={10}>
                  <Table
                    framed={false}
                    headers={["Pick", "Pos", "Likely there", "VOR"]}
                    columnAlign={["right", "left", "left", "right"]}
                    rows={plan.map((p) => [
                      p.pick,
                      <Text as="span" weight="semibold">
                        {p.pos}
                      </Text>,
                      p.player ? p.player.player : "\\u2014",
                      signed(p.vor),
                    ])}
                  />
                  <Text size="small" tone="tertiary">
                    Each turn takes the highest value over replacement that still fills a starting slot,
                    then advances the board by the burn rate each position is actually going at. "Likely
                    there" assumes that rate holds.
                  </Text>
                  <Divider />
                  <Text size="small" tone="secondary">
                    The plan stops once every slot this board can fill is covered. Kicker and both
                    defenses come in the final rounds \\u2014 log those below, they are not ranked.
                  </Text>
                </Stack>
              </CardBody>
            </Card>
          </Grid>

          {/* ------------------------------------------------ lineup + roster */}
          <Stack gap={10}>
            <Row gap={12} align="center" wrap>
              <H2>Your lineup</H2>
              <Text as="span" size="small" tone="tertiary">
                {LINEUP.length - startersLeft.length} of {LINEUP.length} starting slots covered
              </Text>
            </Row>
            <Row gap={8} align="center" wrap>
              {LINEUP.map((s) => {
                const isFilled = !!lineupFilled[s.id];
                const offBoard = OFF_BOARD.includes(s.id);
                return (
                  <div
                    key={s.id}
                    style={{
                      minWidth: 64,
                      padding: "8px 12px",
                      borderRadius: 6,
                      textAlign: "center",
                      background: isFilled ? theme.fill.secondary : "transparent",
                      border: `1px ${offBoard ? "dashed" : "solid"} ${
                        isFilled ? theme.stroke.secondary : theme.stroke.tertiary
                      }`,
                    }}
                  >
                    <Text
                      as="span"
                      size="small"
                      weight="semibold"
                      style={{ color: isFilled ? theme.text.primary : theme.text.quaternary }}
                    >
                      {s.label}
                    </Text>
                  </div>
                );
              })}
            </Row>
            <Text size="small" tone="secondary">
              Still open: {startersLeft.map((s) => s.label).join(", ") || "nothing"}. Roster caps:{" "}
              {Object.keys(CAPS)
                .map((p) => `${myCounts[p] ?? 0}/${CAPS[p]} ${p}`)
                .join(" \\u00b7 ")}
              .
            </Text>
          </Stack>

          {/* --------------------------------------- kickers and defenses */}
          <Card>
            <CardHeader
              trailing={
                <Pill size="sm">
                  {extras.length} logged
                </Pill>
              }
            >
              Kickers and defenses
            </CardHeader>
            <CardBody>
              <Stack gap={12}>
                <Text size="small" tone="secondary">
                  Neither position is ranked, so neither appears on the board \\u2014 but both get drafted,
                  and an unrecorded pick throws the round and pick counter off for everyone. Type one in
                  here and it behaves like any other pick: it takes the next slot in the order, lands on
                  that team's roster, and can be released or undone with the same controls.
                </Text>

                <Row gap={8} align="center" wrap>
                  {EXTRA_POS.map((p) => (
                    <span key={p}>
                      <Pill active={extraPos === p} onClick={() => setExtraPos(p)}>
                        {p}
                      </Pill>
                    </span>
                  ))}
                  {extraPos === "DST" ? (
                    <Select
                      value={extraDefense}
                      onChange={setExtraDefense}
                      options={[
                        { value: "", label: "Choose a defense\\u2026" },
                        ...freeDefenses.map((d) => ({ value: d, label: d })),
                      ]}
                    />
                  ) : (
                    <TextInput
                      value={extraName}
                      onChange={setExtraName}
                      placeholder="Kicker name"
                      style={{ width: 220 }}
                    />
                  )}
                  <Select
                    value={extraOwner}
                    onChange={setExtraOwner}
                    options={[
                      { value: "", label: `On the clock \\u2014 ${activeTeam}` },
                      ...TEAMS.map((t) => ({ value: t, label: t })),
                    ]}
                  />
                  <Button variant="primary" disabled={!canAddExtra} onClick={addExtra}>
                    Draft to {pendingOwner}
                  </Button>
                  {pendingDuplicate ? (
                    <Text size="small" tone="secondary">
                      {pendingName} is already off the board.
                    </Text>
                  ) : null}
                  {pendingAtCap ? (
                    <Text size="small" tone="secondary">
                      {pendingOwner} already has {CAPS[extraPos]} {extraPos}, the roster maximum.
                    </Text>
                  ) : null}
                </Row>

                {extras.length > 0 ? (
                  <Table
                    framed={false}
                    headers={["Pos", "Name", "Team", ""]}
                    columnAlign={["left", "left", "left", "right"]}
                    rows={extras.map((e) => [
                      e.pos,
                      e.name,
                      <Text
                        as="span"
                        style={{
                          color: e.owner === MY_TEAM ? theme.accent.primary : theme.text.secondary,
                        }}
                      >
                        {e.owner}
                      </Text>,
                      <Button variant="ghost" onClick={() => setExtra(e.id, "")}>
                        Release
                      </Button>,
                    ])}
                  />
                ) : null}
              </Stack>
            </CardBody>
          </Card>

          {/* ------------------------------------------------- cost of waiting */}
          <Stack gap={10}>
            <H2>What waiting one turn costs</H2>
            <Text tone="secondary" size="small">
              For each position: how fast it is coming off the board right now, who is best available,
              and how much worse the best available is expected to be at your next turn. Points are
              full-season fantasy points, three-season mean at that positional finish.
            </Text>
            <Table
              headers={[
                "Pos",
                "Gone",
                "Per round",
                "Best available",
                "Worth now",
                "At pick " + (myPicks[1] ?? nextPickIndex + order.length),
                "Cost of waiting",
                "Urgency",
              ]}
              columnAlign={["left", "right", "right", "left", "right", "right", "right", "left"]}
              rowTone={waiting.map((w) =>
                w.cost >= maxCost * 0.75 ? "warning" : w.cost <= maxCost * 0.3 ? "neutral" : undefined,
              )}
              rows={waiting
                .slice()
                .sort((a, b) => b.cost - a.cost)
                .map((w) => [
                  <Text as="span" weight="semibold">
                    {w.pos}
                  </Text>,
                  w.gone,
                  w.perRound.toFixed(1),
                  w.best ? w.best.player : "\\u2014",
                  Math.round(w.nowPts),
                  Math.round(w.laterPts),
                  <Text as="span" weight="semibold">
                    {`\\u2212${Math.round(w.cost)}`}
                  </Text>,
                  <div
                    style={{
                      height: 8,
                      width: `${Math.max(6, (w.cost / maxCost) * 100)}%`,
                      minWidth: 6,
                      borderRadius: 2,
                      background: w.cost >= maxCost * 0.75 ? theme.accent.primary : theme.fill.primary,
                    }}
                  />,
                ])}
            />
            <Text size="small" tone="tertiary">
              This assumes the order players are drafted in predicts the order they finish in, which
              stickiness says is only partly true \\u2014 see the scoring tab. Positions where more than{" "}
              {CURVE_DEPTH.WR} players deep is required are extrapolated past the data floor.
            </Text>
          </Stack>

          {/* ------------------------------------------------- best available */}
          <Stack gap={10}>
            <H2>Best available</H2>
            <Text tone="secondary" size="small">
              Top five undrafted at each position by combined rank, with how they actually finished at
              their position in each of the last three seasons.
            </Text>
            <Grid columns={2} gap={16}>
              {BOARD_POS.map((p) => {
                const w = waiting.find((x) => x.pos === p);
                return (
                  <div key={p}>
                    <Card>
                      <CardHeader
                        trailing={
                          <Pill size="sm">{w ? `\\u2212${Math.round(w.cost)} if you wait` : ""}</Pill>
                        }
                      >
                        {p}
                      </CardHeader>
                      <CardBody style={{ padding: 0 }}>
                        <Table
                          framed={false}
                          headers={["Player", "Ovr", "Finishes", ""]}
                          columnAlign={["left", "right", "left", "right"]}
                          rows={availByPos[p].slice(0, 5).map((r) => [
                            r.player,
                            r.rank,
                            recordCell(r),
                            <Button variant="ghost" onClick={() => draftTo(r, activeTeam)}>
                              Draft
                            </Button>,
                          ])}
                        />
                      </CardBody>
                    </Card>
                  </div>
                );
              })}
            </Grid>
          </Stack>

          <Grid columns="2fr 1fr" gap={16} align="start">
            <Stack gap={8}>
              <Row gap={8} align="center" wrap>
                <H3>Your roster</H3>
                <Text tone="tertiary" size="small">
                  {[...BOARD_POS, ...EXTRA_POS].map((p) => `${myCounts[p] ?? 0} ${p}`).join(" \\u00b7 ")}
                </Text>
              </Row>
              <Table
                headers={["#", "Player", "Pos", "Team", "Finishes", ""]}
                columnAlign={["right", "left", "left", "left", "left", "right"]}
                rows={[
                  ...myRoster.map((r) => [
                    r.rank,
                    r.player,
                    r.pos,
                    r.team,
                    recordCell(r),
                    <Button variant="ghost" onClick={() => release(r)}>
                      Release
                    </Button>,
                  ]),
                  ...myExtras.map((e) => [
                    <Text as="span" tone="quaternary">
                      {"\\u2014"}
                    </Text>,
                    e.name,
                    e.pos,
                    "",
                    <Text as="span" size="small" tone="quaternary">
                      unranked
                    </Text>,
                    <Button variant="ghost" onClick={() => setExtra(e.id, "")}>
                      Release
                    </Button>,
                  ]),
                ]}
                emptyMessage="No picks yet."
              />
            </Stack>
            {recent.length > 0 ? (
              <Stack gap={8}>
                <H3>Recent picks here</H3>
                <Table
                  headers={["Player", "Pos", "To"]}
                  rows={recent.map((r) => [r.player, r.pos, r.owner || "released"])}
                />
              </Stack>
            ) : (
              <Stack gap={8}>
                <H3>How to log a pick</H3>
                <Text size="small" tone="secondary">
                  Press Draft on any row and the player goes to the team on the clock, which steps
                  through the order automatically. Click a team pill to override for a single pick.
                </Text>
              </Stack>
            )}
          </Grid>
        </Stack>
      ) : null}

      {/* ================================================== TAB: full board */}
      {tab === "board" ? (
        <Stack gap={24}>
          <Stack gap={10}>
            <Row gap={8} align="center" wrap>
              {["ALL", "QB", "RB", "WR", "TE"].map((p) => (
                <span key={p}>
                  <Pill active={pos === p} onClick={() => setPos(p)}>
                    {p}
                  </Pill>
                </span>
              ))}
              <span>
                <Pill active={showTaken} onClick={() => setShowTaken(!showTaken)}>
                  Include drafted
                </Pill>
              </span>
              <Spacer />
              <TextInput
                value={query}
                onChange={setQuery}
                placeholder="Search player or team"
                style={{ width: 200 }}
              />
              <Select
                value={sort}
                onChange={setSort}
                options={[
                  { value: "combined", label: "Sort: combined" },
                  { value: "dynasty", label: "Sort: dynasty" },
                  { value: "redraft", label: "Sort: redraft" },
                  { value: "gap", label: "Sort: biggest disagreement" },
                ]}
              />
            </Row>

            <Text tone="tertiary" size="small">
              Showing {visible.length} of {showTaken ? board.length : available.length}. Score is the
              mean of the two ranks; Gap is redraft rank minus dynasty rank, so positive means dynasty
              likes the player more. Players missing from one list sit at that list's last spot + 1
              (dynasty {DYNASTY_SIZE + 1}, redraft {REDRAFT_SIZE + 1}).
            </Text>

            <Table
              stickyHeader
              striped
              headers={["#", "Player", "Pos", "Team", "Age", "Dyn", "Red", "Score", "Gap", "Finishes", "Owner", ""]}
              columnAlign={[
                "right",
                "left",
                "left",
                "left",
                "right",
                "right",
                "right",
                "right",
                "right",
                "left",
                "left",
                "right",
              ]}
              rows={visible.map((r) => [
                r.rank,
                r.status ? `${r.player} (${r.status})` : r.player,
                r.pos,
                r.team,
                r.age || "\\u2014",
                rankText(r.dynasty),
                rankText(r.redraft),
                r.score.toFixed(1),
                r.dynasty !== null && r.redraft !== null ? gapCell(r) : "\\u2014",
                recordCell(r),
                r.owner ? (
                  <Text
                    as="span"
                    style={{ color: r.owner === MY_TEAM ? theme.accent.primary : theme.text.tertiary }}
                  >
                    {r.owner}
                  </Text>
                ) : (
                  ""
                ),
                r.owner ? (
                  <Button variant="ghost" onClick={() => release(r)}>
                    Release
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={() => draftTo(r, activeTeam)}>
                    Draft
                  </Button>
                ),
              ])}
              style={{ maxHeight: 620 }}
            />
          </Stack>

          <Stack gap={10}>
            <H2>Sync back to the repo</H2>
            <Text tone="secondary" size="small">
              The canvas keeps its own picks, but `drafted.csv` is the file the ranking scripts read.
              Send the current board to chat to have it written back, or copy the CSV yourself.
            </Text>
            <Row gap={8} align="center" wrap>
              <Button
                variant="primary"
                onClick={() =>
                  dispatch({
                    type: "newComposerChat",
                    userPrompt:
                      "Replace the contents of drafted.csv with exactly this, then run " +
                      "`python merge.py; python make_canvas.py`:\\n\\n" +
                      exportCsv,
                  })
                }
              >
                Send board to chat
              </Button>
              <Button variant="ghost" onClick={resetToFile}>
                Clear canvas picks
              </Button>
              <Text size="small" tone="tertiary">
                Clear after syncing so the file and the canvas agree.
              </Text>
            </Row>
            <TextArea value={exportCsv} onChange={() => {}} rows={6} />
          </Stack>
        </Stack>
      ) : null}

      {/* ==================================================== TAB: the why */}
      {tab === "why" ? (
        <Stack gap={28}>
          {/* ------------------------------------------------ scoring quirks */}
          <Stack gap={12}>
            <H2>How this league actually scores</H2>
            <Text tone="secondary" size="small">
              Fitted by regressing each player's points per game on his yards, touchdowns and
              receptions per game, pooled across {SEASONS[0]}\\u2013{SEASONS[SEASONS.length - 1]} with season
              fixed effects, players with at least eight games. Source: history_{SEASONS[0]}.csv \\u2026
              history_{SEASONS[SEASONS.length - 1]}.csv via scoring_pooled.py.
            </Text>

            <Grid columns={3} gap={16}>
              <Stat value="\\u22480" label="Points per reception" tone="warning" />
              <Stat
                value={`${Math.min(...SCORING.map((s) => s.tdInYards))}\\u2013${Math.max(
                  ...SCORING.map((s) => s.tdInYards),
                )} yds`}
                label="What a touchdown is worth"
              />
              <Stat
                value={`${Math.min(...SCORING.map((s) => s.ydsPerPoint)).toFixed(1)}\\u2013${Math.max(
                  ...SCORING.map((s) => s.ydsPerPoint),
                ).toFixed(1)}`}
                label="Yards per fantasy point"
              />
            </Grid>

            <Callout tone="info" title="Volume is the whole edge">
              Yardage is bucketed, not paid per yard, and a catch is worth nothing on its own \\u2014 the
              pooled reception coefficients run{" "}
              {SCORING.map((s) => s.ptsPerRec.toFixed(3)).join(", ")} points, statistically
              indistinguishable from zero. A touchdown buys you about the same as{" "}
              {Math.round(SCORING.reduce((a, s) => a + s.tdInYards, 0) / SCORING.length)} extra yards,
              roughly half what standard scoring pays. Draft target share and carries, not red-zone
              reputation or PPR floor.
            </Callout>

            <Grid columns="1fr 1fr" gap={16} align="start">
              <Stack gap={8}>
                <H3>Yards needed for one fantasy point</H3>
                <BarChart
                  categories={SCORING.map((s) => s.pos)}
                  series={[{ name: "Scrimmage yards per point", data: SCORING.map((s) => s.ydsPerPoint) }]}
                  valueSuffix=" yds"
                  height={180}
                  showValues
                />
                <Text size="small" tone="tertiary">
                  x: position \\u00b7 y: scrimmage yards required per fantasy point (lower is better).
                  Pooled 2023\\u20132025 fit.
                </Text>
              </Stack>
              <Stack gap={8}>
                <H3>Pooled coefficients</H3>
                <Table
                  headers={["Pos", "n", "Yds/pt", "Pts/TD", "TD in yds", "Pts/rec", "R\\u00b2"]}
                  columnAlign={["left", "right", "right", "right", "right", "right", "right"]}
                  rows={SCORING.map((s) => [
                    s.pos,
                    s.n,
                    s.ydsPerPoint.toFixed(1),
                    s.ptsPerTd.toFixed(2),
                    s.tdInYards,
                    s.ptsPerRec.toFixed(3),
                    s.r2.toFixed(3),
                  ])}
                />
                <Text size="small" tone="tertiary">
                  Reception coefficients are near zero at every position. Per season they range from{" "}
                  {Math.min(...SCORING_SEASON.map((s) => s.ptsPerRec)).toFixed(3)} to{" "}
                  {Math.max(...SCORING_SEASON.map((s) => s.ptsPerRec)).toFixed(3)} and change sign, which
                  is what a coefficient of zero plus noise looks like.
                </Text>
              </Stack>
            </Grid>

            <Stack gap={8}>
              <H3>Why the single-season touchdown estimate could not be trusted</H3>
              <BarChart
                categories={SEASONS.map(String)}
                series={["RB", "WR", "TE"].map((p) => ({
                  name: p,
                  data: SEASONS.map(
                    (s) => SCORING_SEASON.find((x) => x.pos === p && x.season === s)?.ptsPerTd ?? 0,
                  ),
                }))}
                valueSuffix=" pts"
                height={200}
              />
              <Text size="small" tone="tertiary">
                x: season \\u00b7 y: fitted fantasy points per touchdown \\u00b7 series: position. Source:
                scoring_stability.py, single-season fits. The WR estimate slides from{" "}
                {SCORING_SEASON.find((x) => x.pos === "WR" && x.season === SEASONS[0])?.ptsPerTd.toFixed(2)}{" "}
                to{" "}
                {SCORING_SEASON.find((x) => x.pos === "WR" && x.season === SEASONS[2])?.ptsPerTd.toFixed(2)}{" "}
                across three years, so the low 2025-only reading was noise, not a discovery. The pooled
                fit is the number to use.
              </Text>
            </Stack>

            <Stack gap={8}>
              <H3>The tight end premium is real but small</H3>
              <Grid columns="1fr 1fr" gap={16} align="start">
                <Table
                  headers={["Identical season", "As WR", "As TE", "TE edge"]}
                  columnAlign={["left", "right", "right", "right"]}
                  rows={TE_PREMIUM.map((t) => [
                    t.line,
                    t.asWr.toFixed(1),
                    t.asTe.toFixed(1),
                    <Text as="span" weight="semibold">
                      {`+${t.edge.toFixed(1)}`}
                    </Text>,
                  ])}
                />
                <Stack gap={6}>
                  <Text size="small" tone="secondary">
                    Pricing one identical stat line through each position's pooled curve. A typical
                    starting tight end line is worth about{" "}
                    <Text as="span" weight="semibold">
                      +{TE_PREMIUM[1].edge.toFixed(1)}
                    </Text>{" "}
                    points across a whole season versus the same production from a receiver \\u2014 real,
                    but not a reason to reach.
                  </Text>
                  <Text size="small" tone="tertiary">
                    Fitting each season on its own gives{" "}
                    {TE_PREMIUM_SEASON.map((t) => `${t.season} +${t.edge.toFixed(1)}`).join(", ")}, which is
                    why the pooled number is the honest one.
                  </Text>
                </Stack>
              </Grid>
            </Stack>
          </Stack>

          <Divider />

          {/* --------------------------------------------- value and stickiness */}
          <Stack gap={12}>
            <H2>What each position is worth, and how much of it you can target</H2>
            <Text tone="secondary" size="small">
              Value over replacement uses the replacement this lineup actually creates: QB10 and DST10
              are exact because ten teams start one of each; the flex baseline is the 70th-best
              RB/WR/TE. Stickiness is the year-over-year correlation of a player's season points.
              Source: repeatability_vor.py, three-season means.
            </Text>

            <Grid columns="1.3fr 1fr" gap={16} align="start">
              <Stack gap={8}>
                <H3>Points above replacement by positional slot</H3>
                <BarChart
                  categories={Object.keys(VOR)}
                  series={VOR_SLOTS.map((s, i) => ({
                    name: `#${s} at the position`,
                    data: Object.keys(VOR).map((p) => VOR[p][i]),
                  }))}
                  valueSuffix=" pts"
                  height={240}
                />
                <Text size="small" tone="tertiary">
                  x: position \\u00b7 y: full-season fantasy points above replacement \\u00b7 series: finish
                  within the position. Three-season mean, 2023\\u20132025.
                </Text>
              </Stack>

              <Stack gap={8}>
                <H3>Value you can actually draft</H3>
                <Table
                  headers={["Pos", "#1 VOR", "Stickiness", "Targetable"]}
                  columnAlign={["left", "right", "right", "right"]}
                  rows={Object.keys(VOR)
                    .slice()
                    .sort((a, b) => VOR[b][0] * STICK[b] - VOR[a][0] * STICK[a])
                    .map((p) => [
                      <Text as="span" weight="semibold">
                        {p}
                      </Text>,
                      VOR[p][0],
                      STICK[p].toFixed(2),
                      <Text
                        as="span"
                        weight="semibold"
                        style={{ color: p === "RB" ? theme.accent.primary : theme.text.primary }}
                      >
                        {Math.round(VOR[p][0] * STICK[p])}
                      </Text>,
                    ])}
                />
                <Text size="small" tone="secondary">
                  A big edge you cannot predict is not an edge. Shrinking each position's top-end value
                  by how repeatable it is leaves running back roughly{" "}
                  {(
                    (VOR.RB[0] * STICK.RB) /
                    Math.max(
                      ...Object.keys(VOR)
                        .filter((p) => p !== "RB")
                        .map((p) => VOR[p][0] * STICK[p]),
                    )
                  ).toFixed(1)}
                  \\u00d7 the next best position. The weighting is a heuristic; the ordering is not
                  sensitive to it.
                </Text>
              </Stack>
            </Grid>

            <Stack gap={8}>
              <H3>Stickiness, pair by pair</H3>
              <Table
                headers={["Pos", "Seasons", "Players", "Correlation"]}
                columnAlign={["left", "left", "right", "right"]}
                rows={STICK_PAIRS.map((s) => [s.pos, s.pair, s.n, s.r.toFixed(2)])}
              />
              <Text size="small" tone="tertiary">
                Only players who appear in the top 100 in both seasons are counted, so these are biased
                upward \\u2014 anyone who fell off the list entirely is excluded. True stickiness is lower
                than shown at every position.
              </Text>
            </Stack>
          </Stack>

          <Divider />

          {/* ------------------------------------------------------- the flex */}
          <Stack gap={12}>
            <H2>Four flex slots make this a running back league</H2>
            <Grid columns="1fr 1fr" gap={16} align="start">
              <Stack gap={8}>
                <H3>Composition of the top 20 flex-eligible scorers</H3>
                <BarChart
                  categories={FLEXMIX.map((f) => String(f.season))}
                  series={[
                    { name: "RB", data: FLEXMIX.map((f) => f.rb) },
                    { name: "WR", data: FLEXMIX.map((f) => f.wr) },
                    { name: "TE", data: FLEXMIX.map((f) => f.te) },
                  ]}
                  stacked
                  height={200}
                />
                <Text size="small" tone="tertiary">
                  x: season \\u00b7 y: players among the 20 highest-scoring RB/WR/TE \\u00b7 series: position.
                  Running backs are {Math.min(...FLEXMIX.map((f) => f.rb))} to{" "}
                  {Math.max(...FLEXMIX.map((f) => f.rb))} of the top 20 every year. Source: tiers_flex.py.
                </Text>
              </Stack>

              <Stack gap={8}>
                <H3>Should the second flex slot be a tight end?</H3>
                <Table
                  headers={["Slot", "RB", "WR", "TE"]}
                  columnAlign={["left", "right", "right", "right"]}
                  rows={[0, 1, 2, 3].map((i) => [
                    `#${VOR_SLOTS[i]} at the position`,
                    signed(VOR.RB[i]),
                    signed(VOR.WR[i]),
                    signed(VOR.TE[i]),
                  ])}
                />
                <Text size="small" tone="secondary">
                  A top-five tight end in a flex slot is genuinely good, worth {signed(VOR.TE[2])} to{" "}
                  {signed(VOR.TE[1])}. A realistic second tight end lands around TE10 and is worth{" "}
                  {signed(VOR.TE[3])}, against {signed(VOR.RB[3])} for a tenth-best running back in the
                  same slot. Roster two tight ends because you need one starter and the backup is free,
                  not as a strategy.
                </Text>
              </Stack>
            </Grid>
          </Stack>

          <Divider />

          {/* ------------------------------------------------------- the cliffs */}
          <Stack gap={12}>
            <H2>Where the tiers break</H2>
            <Stack gap={8}>
              <H3>Season points by positional finish</H3>
              <LineChart
                categories={Array.from({ length: 12 }, (_, i) => String(i + 1))}
                series={["RB", "WR", "TE", "QB"].map((p) => ({
                  name: p,
                  data: CURVE[p].slice(0, 12),
                }))}
                height={260}
                referenceLines={[
                  { value: REPL.flex, label: "flex replacement", tone: "warning" },
                  { value: REPL.qb, label: "QB10", tone: "info" },
                ]}
              />
              <Text size="small" tone="tertiary">
                x: finish within the position (1 = best) \\u00b7 y: full-season fantasy points \\u00b7 series:
                position. Three-season mean, 2023\\u20132025. The dashed lines are the replacement levels
                this lineup creates.
              </Text>
            </Stack>

            <Stack gap={8}>
              <Row gap={8} align="center" wrap>
                <H3>Points lost stepping down one rank</H3>
                <Spacer />
                {["RB", "WR", "TE", "QB"].map((p) => (
                  <span key={p}>
                    <Pill active={cliffPos === p} onClick={() => setCliffPos(p)}>
                      {p}
                    </Pill>
                  </span>
                ))}
              </Row>
              <BarChart
                categories={Array.from({ length: 11 }, (_, i) => `${i + 1}\\u2192${i + 2}`)}
                series={[{ name: `${cliffPos} drop between consecutive finishes`, data: DROPS[cliffPos] }]}
                valueSuffix=" pts"
                height={200}
                showValues
              />
              <Text size="small" tone="tertiary">
                x: step between adjacent positional finishes \\u00b7 y: full-season fantasy points lost,
                three-season mean. Source: tiers_flex.py.
              </Text>
            </Stack>

            <Stack gap={8}>
              <H3>The biggest single-rank drop inside the top 12, by season</H3>
              <Table
                headers={["Pos", ...SEASONS.map(String)]}
                columnAlign={["left", "left", "left", "left"]}
                rows={["RB", "WR", "TE", "QB"].map((p) => [
                  <Text as="span" weight="semibold">
                    {p}
                  </Text>,
                  ...SEASONS.map((s) => {
                    const c = CLIFFS.find((x) => x.pos === p && x.season === s)!;
                    return `${p}${c.from}\\u2192${p}${c.from + 1}   \\u2212${c.drop} (${c.share}%)`;
                  }),
                ])}
              />
              <Text size="small" tone="secondary">
                The receiver cliff is the dependable one: it lands inside the top three every single
                season, so once two or three receivers are gone the position flattens out. The running
                back cliff is larger but moves \\u2014 top of the position in{" "}
                {CLIFFS.filter((c) => c.pos === "RB" && c.from === 1)
                  .map((c) => c.season)
                  .join(" and ")}
                , mid-tier in{" "}
                {CLIFFS.filter((c) => c.pos === "RB" && c.from !== 1)
                  .map((c) => `${c.season} at RB${c.from}`)
                  .join(", ")}
                . You cannot time it, which is the argument for taking backs early rather than trying to
                catch the break.
              </Text>
            </Stack>
          </Stack>

          <Divider />

          {/* ------------------------------------------------------------- DST */}
          <Stack gap={12}>
            <H2>Defenses score like stars and behave like coin flips</H2>
            <Grid columns="1fr 1fr" gap={16} align="start">
              <Stack gap={8}>
                <H3>Where a defense would rank among all scorers</H3>
                <Table
                  headers={["Season", "Best DST", "Pts", "Overall", "DST10", "Overall", "WRs it beats"]}
                  columnAlign={["left", "left", "right", "right", "right", "right", "right"]}
                  rows={DST_ROWS.map((d) => [
                    d.season,
                    d.top,
                    d.d1,
                    `#${d.d1Overall}`,
                    d.d10,
                    `#${d.d10Overall}`,
                    `${d.wrBeaten}/${d.wrTotal}`,
                  ])}
                />
                <Text size="small" tone="tertiary">
                  "Overall" is where that point total would have placed among every ranked skill player
                  that season. The last column counts how many top-100 receivers the replacement-level
                  tenth defense outscored. Source: dst_analysis.py.
                </Text>
              </Stack>
              <Stack gap={8}>
                <H3>And yet it is not draftable</H3>
                <Table
                  headers={["Seasons", "Correlation"]}
                  columnAlign={["left", "right"]}
                  rows={DST_CORR.map((c) => [c.pair, c.r.toFixed(2)])}
                />
                <Callout tone="warning" title="Stream, do not draft">
                  The best defense would have been a top-{Math.max(...DST_ROWS.map((d) => d.d1Overall))}{" "}
                  overall scorer in all three seasons, but there is no way to know in August which one
                  it will be. Year-over-year correlation averages {STICK.DST.toFixed(2)} and swings from{" "}
                  {Math.min(...DST_CORR.map((c) => c.r)).toFixed(2)} to{" "}
                  {Math.max(...DST_CORR.map((c) => c.r)).toFixed(2)}. Because the tenth-best defense
                  still scores {Math.min(...DST_ROWS.map((d) => d.d10))}\\u2013
                  {Math.max(...DST_ROWS.map((d) => d.d10))}, the cost of guessing wrong is small and the
                  reward for guessing right is unrepeatable. Take both defenses in the last rounds.
                </Callout>
              </Stack>
            </Grid>
          </Stack>

          <Divider />

          {/* ---------------------------------------------------- known gaps */}
          <Stack gap={12}>
            <H2>What this analysis cannot tell you</H2>
            <Grid columns="1fr 1fr" gap={16} align="start">
              <Stack gap={8}>
                <H3>The source lists stop short of flex replacement</H3>
                <Table
                  headers={["Season", "RB", "WR", "TE", "Flex pool", "Short of 70", "Floor", "Est. repl."]}
                  columnAlign={["left", "right", "right", "right", "right", "right", "right", "right"]}
                  rows={TRUNC.map((t) => [
                    t.season,
                    t.rb,
                    t.wr,
                    t.te,
                    t.flex,
                    t.short,
                    t.floor,
                    t.flexRepl,
                  ])}
                />
                <Text size="small" tone="secondary">
                  Ten teams start seven RB/WR/TE, so replacement is the 70th-best flex body \\u2014 below
                  where the data ends every season. That level is extrapolated from a power-law fit on
                  the tail, so every RB, WR and TE value-over-replacement figure on this page is
                  approximate in magnitude. The ordering between positions is safe; the exact point
                  totals are not. QB10 and DST10 are measured directly and are exact.
                </Text>
              </Stack>
              <Stack gap={8}>
                <H3>There is no kicker data at all</H3>
                <Callout tone="danger" title="One of ten starting slots is unmodelled">
                  Neither the historical scoring files nor the ranking board carry kickers, and both
                  source ranking lists drop kickers and defenses before merging. Nothing on this page
                  says anything about which kicker to take, only that you should take one late.
                </Callout>
                <Text size="small" tone="secondary">
                  Defenses at least have three seasons of scoring behind them, which is what the panel
                  above is built on, but they are still unranked and unscored here. Both positions are
                  logged by hand on the first tab so the pick counter stays honest; they never enter the
                  rankings, the best-available lists or any value calculation.
                </Text>
              </Stack>
            </Grid>
          </Stack>
        </Stack>
      ) : null}
    </Stack>
  );
}
"""

out = (
    CANVAS.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    .replace("__TEAMS__", json.dumps(teams, ensure_ascii=False))
    .replace("__ORDER__", json.dumps(DRAFT_ORDER, ensure_ascii=False))
    .replace("__DYN__", "432")
    .replace("__RED__", "476")
    .replace("__FILEPICKS__", str(sum(1 for r in rows if r["owner"]) + len(file_extras)))
    .replace("__FILEEXTRAS__", json.dumps(file_extras, ensure_ascii=False))
    .replace("__DEFENSES__", json.dumps(nfl_defenses, ensure_ascii=False))
    .replace("__SEASONS__", json.dumps(list(SEASONS)))
    .replace("__SCORING__", json.dumps(scoring))
    .replace("__SCORINGSEASON__", json.dumps(scoring_season))
    .replace("__TEPREMSEASON__", json.dumps(te_premium_season))
    .replace("__TEPREM__", json.dumps(te_premium))
    .replace("__STICKPAIRS__", json.dumps(stick_pairs, ensure_ascii=False))
    .replace("__STICK__", json.dumps(stick))
    .replace("__VOR__", json.dumps(vor))
    .replace("__REPL__", json.dumps(repl))
    .replace("__CURVEDEPTH__", json.dumps(curve_depth))
    .replace("__CURVE__", json.dumps(curve))
    .replace("__CLIFFS__", json.dumps(cliffs))
    .replace("__DROPS__", json.dumps(drops))
    .replace("__FLEXMIX__", json.dumps(flexmix))
    .replace("__DSTROWS__", json.dumps(dst_rows, ensure_ascii=False))
    .replace("__DSTCORR__", json.dumps(dst_corr, ensure_ascii=False))
    .replace("__TRUNC__", json.dumps(trunc))
    .replace("__FINISHES__", json.dumps(finishes, ensure_ascii=False))
    .replace("__ME__", MY_TEAM)
)

path = r"C:\Users\Danny\.cursor\projects\c-Users-Danny-fantasy-footbal\canvases\combined-rankings.canvas.tsx"
open(path, "w", encoding="utf-8").write(out)
print("wrote", path, len(out), "bytes")

print("\nverification against the analysis scripts")
for s in scoring:
    print(f"  {s['pos']}: {s['ydsPerPoint']} yds/pt, {s['ptsPerTd']} pts/TD "
          f"({s['tdInYards']} yds), {s['ptsPerRec']:+.3f} pts/rec")
print("  stickiness: " + ", ".join(f"{p} {stick[p]:+.2f}" for p in ("RB", "WR", "TE", "QB", "DST")))
print("  VOR #1:     " + ", ".join(f"{p} {vor[p][0]:+d}" for p in ("RB", "WR", "TE", "QB", "DST")))
print("  VOR #10:    " + ", ".join(f"{p} {vor[p][3]:+d}" for p in ("RB", "WR", "TE")))
print(f"  replacement: flex {repl['flex']}, QB10 {repl['qb']}, DST10 {repl['dst']}")
print(f"  TE premium on 900 yds / 6 TD: {te_premium[1]['edge']:+.1f} pooled, "
      + ", ".join(f"{t['season']} {t['edge']:+.1f}" for t in te_premium_season))
print("  top-20 flex RB share: " + ", ".join(f"{f['season']} {f['rb']}/20" for f in flexmix))
print("  biggest top-12 drop: " + ", ".join(
    f"{c['pos']}{c['from']} in {c['season']} ({c['drop']})" for c in cliffs if c["pos"] in ("RB", "WR")))
