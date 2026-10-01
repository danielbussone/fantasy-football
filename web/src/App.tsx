import { useEffect, useMemo, useRef, useState } from "react";
import { importEspn, importRankings, importWeekly, loadCurrentWeek, loadReport, loadWaivers, loadWeek, postLock, postRefresh } from "./api";
import type { CurrentWeek, DstCard, FreshnessEntry, Grade, Grades, KickStream, Player, Proj, ReportCard, ReportDriver, ReportTracking, Scored, Stream, TrackerCard, WeekPayload } from "./types";

type Tab = "roster" | "lineup" | "waivers" | "week" | "report";
type Obj = "mean" | "p10" | "p25" | "p50" | "p75" | "p90";
const DEFAULT_OBJECTIVE: Obj = "mean";

const OBJ_OPTIONS: { id: Obj; label: string }[] = [
  { id: "mean", label: "Expected (mean)" },
  { id: "p10", label: "P10 — floor" },
  { id: "p25", label: "P25 — safe bets" },
  { id: "p50", label: "P50 — median" },
  { id: "p75", label: "P75 — high upside" },
  { id: "p90", label: "P90 — ceiling" },
];

const TICK_TIPS = [
  "P10 floor week",
  "P25 safe bets",
  "P50 typical week (median)",
  "P75 high upside",
  "P90 long-TD / chunk-play ceiling",
];

const PCTS: Obj[] = ["p10", "p25", "p50", "p75", "p90"];
// "mean" is not on the P10–P90 band at all — Partial so Spark can look it up
// without a dedicated case, and just show no dynamic highlight for it.
const PCT_IDX: Partial<Record<Obj, number>> = { p10: 0, p25: 1, p50: 2, p75: 3, p90: 4 };

// Not a rule — a nudge. §1's "variance is free" argues for chasing upside
// early (a bust is easy to make up over 18 weeks), settling on the median
// mid-season, and protecting a lead late. Never auto-applied.
function seasonStageSuggestion(week: number): { obj: Obj; label: string } | null {
  if (week <= 6) return { obj: "p75", label: "P75 (upside)" };
  if (week <= 12) return { obj: "p50", label: "P50 (balanced)" };
  if (week <= 18) return { obj: "p25", label: "P25 (protect the lead)" };
  return null;
}
const POS_FILTERS = ["ALL", "QB", "RB", "WR", "TE", "K", "DST"] as const;
type PosFilter = (typeof POS_FILTERS)[number];
type EspnMix = 0 | 0.5 | 1;
const ESPN_MIXES: { id: EspnMix; label: string; title: string }[] = [
  {
    id: 0,
    label: "Monte Carlo",
    title: "History + last-3-games + depth. ESPN stays in the ESPN column only.",
  },
  {
    id: 0.5,
    label: "50/50",
    title: "Average our usage prior with ESPN’s week yards/TDs, then simulate.",
  },
  {
    id: 1,
    label: "ESPN",
    title: "Center the sim on ESPN’s week stat line. Injury snaps still apply.",
  },
];

function Spark({ p, highlight, maxScale }: { p: Proj; highlight?: Obj; maxScale?: number }) {
  const vals = [p.p10, p.p25, p.p50, p.p75, p.p90];
  const max = maxScale ?? Math.max(...vals, 0.01);
  const [open, setOpen] = useState(false);
  const hi = highlight ? PCT_IDX[highlight] ?? -1 : 2;
  return (
    <span
      className="spark"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      tabIndex={0}
    >
      {vals.map((v, i) => (
        <i
          key={i}
          className={`${i === 2 ? "md" : ""} ${i === hi ? "on" : ""}`}
          style={{ height: `${Math.max(12, (v / max) * 100)}%` }}
          title={`${TICK_TIPS[i]}: ${v}`}
        />
      ))}
      {open && (
        <span className="tip" role="tooltip">
          Width = volatility (boom/bust). Left edge = floor week. Middle bar = typical
          week. Right tail = long-TD / chunk-play ceiling in this scoring, not CBS FPTS.
          <br />
          P10 {p.p10} · P25 {p.p25} · P50 {p.p50} · P75 {p.p75} · P90 {p.p90}
        </span>
      )}
    </span>
  );
}

function FreshnessChip({ entry }: { entry?: FreshnessEntry }) {
  if (!entry) return null;
  const age =
    entry.age_hours == null
      ? "never"
      : entry.age_hours < 1
      ? "<1h ago"
      : entry.age_hours < 48
      ? `${Math.round(entry.age_hours)}h ago`
      : `${Math.round(entry.age_hours / 24)}d ago`;
  const title = [entry.as_of ? `as of ${entry.as_of}` : "no data on file", entry.hint].filter(Boolean).join(" — ");
  return (
    <span className={`freshness-chip ${entry.status}`} title={title}>
      <span className="dot" aria-hidden="true" />
      {entry.label}: {entry.status === "missing" ? "missing" : age}
    </span>
  );
}

function Badge({ p }: { p: Player }) {
  const slot = p.slot || "";
  const d = p.injury?.designation || (/injured|^ir$|^o$|^out$/i.test(slot) ? slot : "");
  if (!d) return null;
  const cls = /out|ir|injured/i.test(d) ? "out" : "q";
  return (
    <span className={`badge ${cls}`} title={`${p.injury?.note || slot} (${p.injury?.source || "CBS slot"})`}>
      {d}
    </span>
  );
}

const ESPN_EV_VS_P50 =
  "Mean-line EV, not the P50. Scores ESPN’s average yards/TDs as if that line hit. P50 is the median of scored games — yardage buckets make those disagree.";

const WAIVER_COL = {
  past: "Last scored season in this format (2025 if we have it, else 2024).",
  present: "This week’s expected points (mean) — the injury-adjusted GBFL sim average, not the median. Variance is free in this format, so every valuation targets the mean.",
  future: "Expected points × weeks left in the season (through week 18) × a depth factor (1.0 starter / 0.625 depth-2 / 0.375 backup).",
  keeper: "Board/age mix: younger board names get more weight; kickers/DST with a real week can use present × 4.",
};

const WAIVER_SCORE_KEY =
  "Past = last season in this format · Present = this week’s expected points (mean) · Future = present × weeks left · Keeper = board/age mix.";

function espnCell(
  p: {
    has_espn?: boolean;
    espn_line?: string;
    espn_gbfl?: number | null;
    espn_pts?: string;
    espn_tip?: string;
  },
  compact = false
) {
  if (!p.has_espn) return <td>—</td>;
  const line = p.espn_line || "";
  const tip = [p.espn_tip, ESPN_EV_VS_P50].filter(Boolean).join(" · ");
  return (
    <td title={tip}>
      <div className="espn-line">{line || "—"}</div>
      {line && p.espn_gbfl != null ? (
        <>
          <div className="pos">this format EV ~{p.espn_gbfl}</div>
          {compact ? null : <div className="pos">Mean-line EV, not the P50</div>}
        </>
      ) : null}
    </td>
  );
}

function EvVsP50({ ev, p50 }: { ev?: number | null; p50?: number | null }) {
  if (ev == null && p50 == null) return null;
  return (
    <div className="ev-p50" title={ESPN_EV_VS_P50}>
      <span>
        <strong>{ev ?? "—"}</strong>
        <span className="pos"> ESPN mean-line EV</span>
      </span>
      <span className="muted">vs</span>
      <span>
        <strong>{p50 ?? "—"}</strong>
        <span className="pos"> P50 median</span>
      </span>
    </div>
  );
}

function weeklyLabel(p: { weekly_rank?: number | null; weekly_list?: string | null }) {
  if (p.weekly_rank == null) return "—";
  const list = p.weekly_list || "";
  return list ? `${list} ${p.weekly_rank}` : String(p.weekly_rank);
}

// §7's top signal, made visible: O/U is the scoring environment (both
// teams), spread is who's expected to control the game script. Negative
// spread = this team favored by that many; positive = underdog.
function vegasLine(p: {
  team?: string;
  vegas_over_under?: number | null;
  vegas_spread?: number | null;
  vegas_total?: number | null;
  vegas_opp?: string;
  vegas_indoor?: boolean;
}): string {
  if (p.vegas_over_under == null) return "";
  const spread = p.vegas_spread;
  const spreadStr = spread == null ? "" : spread > 0 ? `+${spread}` : `${spread}`;
  return [
    `O/U ${p.vegas_over_under}`,
    spreadStr && `${p.team || "team"} ${spreadStr}${p.vegas_opp ? ` vs ${p.vegas_opp}` : ""}`,
    p.vegas_total != null && `implied ${p.vegas_total}`,
    p.vegas_indoor && "dome",
  ]
    .filter(Boolean)
    .join(" · ");
}

// A defense's own shrunk points-allowed-by-position ratio (GBFL_RULES.md
// §7's DvP signal) and the opponent's pass-rush pull on TD distance —
// separate from Vegas's team-total read, both already baked into the sim.
function matchupLine(p: { matchup_ratio?: number | null; pass_rush_skew?: number | null }): string {
  const bits: string[] = [];
  if (p.matchup_ratio != null && Math.abs(p.matchup_ratio - 1) > 0.01) {
    const pct = Math.round((p.matchup_ratio - 1) * 100);
    bits.push(`matchup ${pct > 0 ? "+" : ""}${pct}%`);
  }
  if (p.pass_rush_skew != null && Math.abs(p.pass_rush_skew) > 0.02) {
    bits.push(p.pass_rush_skew < 0 ? "vs. strong pass rush (shorter TDs)" : "vs. weak pass rush (longer TDs)");
  }
  return bits.join(" · ");
}

function weeklyTip(p: {
  weekly_matchup?: string;
  weekly_opp?: string;
  weekly_start_sit?: string;
  weekly_proj_fpts?: string;
  vegas_total?: number | null;
  vegas_kickoff?: string;
  vegas_indoor?: boolean;
  matchup_ratio?: number | null;
  pass_rush_skew?: number | null;
}) {
  const kickoff = p.vegas_kickoff ? new Date(p.vegas_kickoff).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" }) : "";
  return [
    p.weekly_matchup,
    p.weekly_opp,
    p.weekly_start_sit && `FP ${p.weekly_start_sit}`,
    p.weekly_proj_fpts && `FP ${p.weekly_proj_fpts} (not this league)`,
    p.vegas_total != null && `Vegas implied ${p.vegas_total} pts${p.vegas_indoor ? " (dome)" : ""}`,
    kickoff && `kickoff ${kickoff}`,
    matchupLine(p) || null,
  ]
    .filter(Boolean)
    .join(" · ");
}

const GRADE_TIP = {
  role: "Usage percentile at his position this season: WOPR for WR/TE, opportunity share for RB. 100 = the most-used player. For a QB it's his rank by projected points per game for the rest of the season (shown as #rank).",
  qb: "Rest-of-season QB projection: points per game this season and the last two, weighted by how many games each covers, plus this season's EPA per play. Ranks QBs by points per game over the rest of the season: rank correlation 0.50 vs 0.40 for points so far (13-season backtest).",
  epa: "EPA per play: expected points added per dropback or designed run, season to date. Measures how much each play moves his offense toward scoring.",
  par: "Points above the best free agent for the rest of the season, adjusted for injury status. Negative means a free agent should outscore him.",
  wopr: "Weighted Opportunity Rating: 1.5 × target share + 0.7 × air-yards share. Rewards being targeted often and downfield. WR1s run about 0.6–0.75, waiver WRs under 0.3.",
  opp_share: "Opportunity share: his carries + targets ÷ his team's carries + targets, in the games he played.",
  exp_games: "Games he'll likely play the rest of the season, from his team's schedule and his injury report status.",
  matchup: "Defense: next opponent's Vegas implied total (lower is a better week). Kicker: his own team's implied total (higher is better).",
  next_up: "Lead back is out; he has the biggest remaining share of the RB work. Backups in this spot beat their projection by about 0.6 pts/game.",
  buy_low: "First- or second-year round 1–2 pick off to a slow start. These break out about 3× as often as other slow starters.",
  pedigree: "Round 1–2 RB in years 1–2: PAR includes +1.1 pts/game while his share is under 25%, +0.5 after.",
};

function fmtPar(v?: number | null) {
  return v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
}

function usageText(g: NonNullable<Grade>) {
  if (g.usage == null) return "—";
  if (g.usage_stat === "epa") return `EPA ${g.usage.toFixed(2)}`;
  return g.usage_stat === "wopr" ? `WOPR ${g.usage.toFixed(2)}` : `Opp ${Math.round(g.usage * 100)}%`;
}

function GradeFlags({ g }: { g?: Grade }) {
  if (!g) return null;
  return (
    <>
      {g.flags.includes("next_up") && (
        <span className="badge ok" title={GRADE_TIP.next_up}>
          NEXT UP
        </span>
      )}{" "}
      {g.flags.includes("buy_low") && (
        <span className="badge q" title={GRADE_TIP.buy_low}>
          BUY LOW
        </span>
      )}{" "}
      {g.bump > 0 && (
        <span className="badge ok" title={GRADE_TIP.pedigree}>
          +PEDIGREE
        </span>
      )}
    </>
  );
}

function gradeTitle(g: NonNullable<Grade>) {
  return [
    `${usageText(g)}${g.snap_pct != null ? ` · ${Math.round(g.snap_pct * 100)}% of snaps` : ""} over ${g.games} games${g.usage_stat === "epa" ? ` · QB #${g.rank} of ${g.of} by projection` : ""}`,
    `predicts ${g.par_ppg.toFixed(2)} pts/game${g.bump > 0 ? ` (incl. +${g.bump.toFixed(2)} pedigree)` : ""}`,
    `${g.exp_games} of ${g.team_games_left} games expected${g.status ? ` (${g.status})` : ""}`,
  ].join(" · ");
}

function roleCell(p: { grade?: Grade }) {
  const g = p.grade;
  if (!g) return <td>—</td>;
  return (
    <td title={g.usage_stat === "epa" ? `${GRADE_TIP.qb} ${gradeTitle(g)}` : gradeTitle(g)}>{g.usage_stat === "epa" ? `#${g.rank}` : g.role}</td>
  );
}

function parCell(p: { grade?: Grade }, compact = false) {
  const g = p.grade;
  if (!g) return <td>—</td>;
  return (
    <td title={gradeTitle(g)}>
      <strong>{fmtPar(g.par)}</strong>
      {compact ? null : (
        <div className="pos" title={GRADE_TIP.exp_games}>
          {g.exp_games} g{g.status ? ` · ${g.status}` : ""}
        </div>
      )}
    </td>
  );
}

function matchupCell(p: { stream?: Stream; kick?: KickStream }) {
  if (p.stream) {
    return (
      <td title={GRADE_TIP.matchup}>
        vs {p.stream.opp} · {p.stream.opp_total}
        <div className="pos">
          #{p.stream.rank}/{p.stream.of}
        </div>
      </td>
    );
  }
  if (p.kick) {
    return (
      <td title={GRADE_TIP.matchup}>
        {p.kick.implied}
        {p.kick.dome ? " dome" : ""}
        <div className="pos">
          #{p.kick.rank}/{p.kick.of}
        </div>
      </td>
    );
  }
  return <td>—</td>;
}

type SortKey = "par" | "role" | "exp" | "matchup" | "present" | "future" | "keeper";
type SortState = { key: SortKey; dir: "asc" | "desc" } | null;

function sortValue(p: Scored, k: SortKey): number | null {
  switch (k) {
    case "par":
      return p.grade?.par ?? null;
    case "role":
      return p.grade?.role ?? null;
    case "exp":
      return p.grade?.exp_games ?? null;
    case "matchup":
      return p.stream?.score ?? p.kick?.score ?? null;
    case "present":
      return p.present;
    case "future":
      return p.future;
    case "keeper":
      return p.keeper;
  }
}

function defaultSort(pos: PosFilter): SortKey {
  if (pos === "QB") return "present";
  if (pos === "K" || pos === "DST") return "matchup";
  return "par";
}

function sortRows(rows: Scored[], key: SortKey, dir: "asc" | "desc"): Scored[] {
  const sign = dir === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => {
    const va = sortValue(a, key);
    const vb = sortValue(b, key);
    if (va == null && vb == null) return 0;
    if (va == null) return 1; // players with no grade always sort last
    if (vb == null) return -1;
    return sign * (va - vb);
  });
}

function TrackingCard({ t }: { t: ReportTracking }) {
  const pts = (v?: number | null) => (v == null ? "—" : v.toFixed(2));
  const beat = (v?: number) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}`);
  const flagRow = (label: string, tip: string, s: ReportTracking["next_up"]) => (
    <tr>
      <td title={tip}>{label}</td>
      <td>{s.n}</td>
      <td>{pts(s.pred)}</td>
      <td>{pts(s.actual)}</td>
      <td>
        <strong>{beat(s.beat)}</strong>
      </td>
      <td>{s.hit_rate == null ? "—" : `${Math.round(s.hit_rate * 100)}%`}</td>
    </tr>
  );
  return (
    <div className="paper" style={{ marginTop: "0.75rem" }}>
      <strong>Usage metrics, live tracking</strong>
      <p className="muted">
        Each lock records what the grades predicted; once box scores are in, they're scored here. The RB next-man-up and buy-low flags came from
        samples of a few dozen players, so this is where they get confirmed or dropped. Locked weeks scored so far:{" "}
        {t.weeks.length ? t.weeks.join(", ") : "none yet — lock a week before kickoff, then refresh after the games."}
      </p>
      {t.weeks.length > 0 && (
        <>
          <table>
            <thead>
              <tr>
                <th>Flag</th>
                <th>Player-weeks</th>
                <th title="PAR's predicted points/game for these players at lock.">Predicted pts/g</th>
                <th>Actual pts</th>
                <th title="Actual minus predicted. The backtest said next man up beats prediction by about +0.6.">Beat prediction by</th>
                <th>Beat it</th>
              </tr>
            </thead>
            <tbody>
              {flagRow("Next man up", GRADE_TIP.next_up, t.next_up)}
              {flagRow("Buy low", GRADE_TIP.buy_low, t.buy_low)}
            </tbody>
          </table>
          <table>
            <thead>
              <tr>
                <th>Position</th>
                <th>Player-weeks</th>
                <th title="Mean of actual − predicted points/game. Near 0 means PAR's per-game level is unbiased.">Mean error</th>
                <th title="Mean absolute error in points/game.">Typical miss</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(t.par).map(([pos, e]) => (
                <tr key={pos}>
                  <td>{pos}</td>
                  <td>{e.n}</td>
                  <td>{beat(e.mean_err)}</td>
                  <td>{e.mae.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {t.dst.weeks > 0 && (
            <table>
              <thead>
                <tr>
                  <th title={GRADE_TIP.matchup}>Defense stream pick</th>
                  <th>Opponent implied</th>
                  <th>Pick scored</th>
                  <th>Average free defense</th>
                </tr>
              </thead>
              <tbody>
                {t.dst.rows.map((r) => (
                  <tr key={r.week}>
                    <td>
                      Wk {r.week}: {r.pick}
                    </td>
                    <td>
                      vs {r.opp} · {r.opp_total}
                    </td>
                    <td>{pts(r.pick_pts)}</td>
                    <td>{pts(r.avg_free_pts)}</td>
                  </tr>
                ))}
                <tr>
                  <td>
                    <strong>Season so far ({t.dst.weeks} wk)</strong>
                  </td>
                  <td />
                  <td>
                    <strong>{pts(t.dst.pick_pts)}</strong>
                  </td>
                  <td>
                    <strong>{pts(t.dst.avg_free_pts)}</strong>
                  </td>
                </tr>
              </tbody>
            </table>
          )}
          {t.flag_rows.length > 0 && (
            <p className="muted">
              Recent flags: {t.flag_rows.slice(0, 8).map((r) => `wk ${r.week} ${r.player} (${r.flag === "next_up" ? "next up" : "buy low"}: ${r.actual} vs ${r.pred.toFixed(2)})`).join(" · ")}
            </p>
          )}
        </>
      )}
    </div>
  );
}

function TrackerTable({ rows, empty, showOwner = true }: { rows: TrackerCard[]; empty: string; showOwner?: boolean }) {
  if (rows.length === 0) return <p className="muted">{empty}</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Player</th>
          {showOwner ? <th>Owner</th> : null}
          <th title="Draft round and years in the league.">Draft</th>
          <th title={`${GRADE_TIP.wopr} ${GRADE_TIP.opp_share}`}>Usage</th>
          <th title="Share of the team's offensive snaps, season to date.">Snaps</th>
          <th title="GBFL points per game so far.">Pts/g</th>
          <th title={GRADE_TIP.par}>PAR</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.player + c.pos}>
            <td>
              {c.player}{" "}
              <span className="pos">
                {c.pos} · {c.team}
              </span>{" "}
              <GradeFlags g={{ flags: c.flags, bump: 0 } as NonNullable<Grade>} />
            </td>
            {showOwner ? (
              <td>
                {c.owner ? c.owner : <WaiverStatusTag status={c.waiver_status || "free_agent"} />}
              </td>
            ) : null}
            <td>
              Rd {c.round > 7 ? "UDFA" : c.round} · yr {c.years ?? "—"}
            </td>
            <td>{c.usage == null ? "—" : c.usage_stat === "wopr" ? `WOPR ${c.usage.toFixed(2)}` : `Opp ${Math.round(c.usage * 100)}%`}</td>
            <td>{c.snap_pct == null ? "—" : `${Math.round(c.snap_pct * 100)}%`}</td>
            <td>{c.ppg.toFixed(2)}</td>
            <td>
              <strong>{fmtPar(c.par)}</strong>
              {c.status ? <span className="pos"> · {c.status}</span> : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DstStreamCard({ g }: { g?: Grades }) {
  if (!g?.available || (g.dst.mine.length === 0 && g.dst.top.length === 0)) return null;
  const best = [...g.dst.mine].sort((a, b) => b.score - a.score)[0];
  const top = g.dst.top[0];
  const swap = best && top && top.score >= best.score + 1.0 ? top : null;
  const row = (d: DstCard, mine: boolean) => (
    <tr key={d.team + (mine ? "m" : "f")}>
      <td>
        {d.player} <span className="pos">{mine ? "yours" : d.waiver_status === "waivers" ? "waivers" : "free agent"}</span>
      </td>
      <td>
        vs {d.opp} · {d.opp_total}
      </td>
      <td>
        #{d.rank}/{d.of}
      </td>
    </tr>
  );
  return (
    <div className="paper" style={{ marginBottom: "0.75rem" }}>
      <strong title={GRADE_TIP.matchup}>Defense stream</strong>{" "}
      <span className="muted">Next opponent's implied total, lowest first. Streaming by matchup beat picking by points so far by about 1.5 pts a week in the backtest.</span>
      {swap ? (
        <div className="banner" style={{ marginTop: "0.5rem" }}>
          <strong>{swap.player}</strong> (vs {swap.opp}, implied {swap.opp_total}) is a softer matchup than your best, {best.player} (vs {best.opp}, {best.opp_total}).
        </div>
      ) : (
        <div className="muted">Your best defense already has the softer matchup.</div>
      )}
      <table>
        <thead>
          <tr>
            <th>Defense</th>
            <th>Opponent implied</th>
            <th>League rank</th>
          </tr>
        </thead>
        <tbody>
          {g.dst.mine.map((d) => row(d, true))}
          {g.dst.top.map((d) => row(d, false))}
        </tbody>
      </table>
    </div>
  );
}

function Trackers({ g, week }: { g: Grades; week: number }) {
  return (
    <>
      <div className="paper" style={{ marginBottom: "0.75rem" }}>
        <strong title={GRADE_TIP.buy_low}>Buy-low tracker</strong>{" "}
        <span className="muted">
          Young round 1–2 picks sitting in the waiver tier by points. Free ones are adds, rostered ones are trade targets.
          {g.buy_low_active ? "" : " Flags run through week 10."}
        </span>
        <TrackerTable rows={g.buy_low} empty="No young high picks are off to a slow start." />
      </div>
      <div className="paper" style={{ marginBottom: "0.75rem" }}>
        <strong title={GRADE_TIP.next_up}>Next man up</strong>
        <TrackerTable rows={g.next_up} empty="No lead back with 15%+ of his team's work is out right now." />
      </div>
      <div className="paper" style={{ marginBottom: "0.75rem" }}>
        <strong>WR watch list</strong>{" "}
        <span className="muted">Top 10 available WRs by PAR. In the backtest this list held about two second-half starters a season, league-wide.</span>
        {g.wr_watch.active ? (
          <TrackerTable rows={g.wr_watch.players} empty="No available WRs have a role." showOwner={false} />
        ) : (
          <p className="muted">Starts in week 8 (it's week {week}).</p>
        )}
      </div>
    </>
  );
}

function WaiverStatusTag({ status }: { status?: string }) {
  if (status === "free_agent") {
    return (
      <span className="badge ok" title="Free agent — add any time, no claim needed.">
        FA
      </span>
    );
  }
  if (status === "waivers") {
    return (
      <span className="badge q" title="On waivers — contested claim, priority order applies.">
        Waivers
      </span>
    );
  }
  return null;
}

function findPlayer(data: WeekPayload, name: string): Player | undefined {
  if (!name) return undefined;
  return data.roster.find((p) => p.player === name) || (data.fa_sample || []).find((p) => p.player === name);
}

function parseVs(label: string): [string, string] | null {
  const parts = label.split(/\s+vs\.?\s+/i);
  if (parts.length !== 2) return null;
  return [parts[0].trim(), parts[1].trim().replace(/\.$/, "")];
}

function simVal(sim: Record<string, number> | undefined, key: string): string {
  const v = sim?.[key];
  return v == null ? "—" : String(v);
}

function CmpCell({ a, b }: { a?: number | null; b?: number | null }) {
  if (a == null || b == null) return <td>—</td>;
  const cls = a > b ? "cmp-win" : a < b ? "cmp-lose" : "cmp-tie";
  return <td className={cls}>{a}</td>;
}

function PlayerSelectOptions({ roster, fa, includeEmpty }: { roster: Player[]; fa: Player[]; includeEmpty?: string }) {
  return (
    <>
      {includeEmpty != null && <option value="">{includeEmpty}</option>}
      <optgroup label="Roster">
        {roster.map((p) => (
          <option key={p.player} value={p.player}>
            {p.player}
          </option>
        ))}
      </optgroup>
      {fa.length > 0 && (
        <optgroup label="Free agents">
          {fa.map((p) => (
            <option key={p.player} value={p.player}>
              {p.player}
            </option>
          ))}
        </optgroup>
      )}
    </>
  );
}

function WeekPlayerBody({ p, sparkMax, mixLabel }: { p: Player; sparkMax?: number; mixLabel?: string }) {
  const rows: [string, number][] = [
    ["10th", p.proj.p10],
    ["25th", p.proj.p25],
    ["50th", p.proj.p50],
    ["75th", p.proj.p75],
    ["90th", p.proj.p90],
  ];
  const u = p.proj.usage;
  const sim = p.proj.sim || {};
  return (
    <>
      <div className="row" style={{ marginTop: "0.75rem", alignItems: "flex-end" }}>
        <Spark p={p.proj} maxScale={sparkMax} />
        <span className="muted">Hover the band: width = volatility.</span>
      </div>
      {p.has_espn ? (
        <>
          <EvVsP50 ev={p.espn_gbfl} p50={p.proj.p50} />
          <p className="muted" style={{ marginTop: "0.25rem" }}>
            Mean-line EV, not the P50. ESPN’s average yards/TDs scored as if that line hit; P50 is the
            median of 1,200 games. Buckets (70 / 90 / 110…) make those diverge.
          </p>
        </>
      ) : null}
      <table style={{ marginTop: "0.75rem", maxWidth: 360 }}>
        <thead>
          <tr>
            <th>Percentile</th>
            <th>Pts (this format)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([l, v]) => (
            <tr key={l}>
              <td>{l}</td>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3 className="subh">Usage prior ({u?.source || p.prior_source || "—"})</h3>
      <p className="muted">
        Pass att {u?.pass_att ?? "—"} · carries {u?.carries ?? "—"} · targets {u?.targets ?? "—"} · rec{" "}
        {u?.receptions ?? "—"} · FG att {u?.fg_att ?? "—"}
        {u?.has_3g ? "" : " · 3g not usable yet"}
      </p>
      <h3 className="subh">Sim means (one game{mixLabel ? `, ${mixLabel}` : ""})</h3>
      <p className="muted">
        Pass yds {sim.pass_yds ?? "—"} · rush {sim.rush_yds ?? "—"} · rec {sim.rec_yds ?? "—"} · pass TD{" "}
        {sim.pass_td ?? "—"} · rush TD {sim.rush_td ?? "—"} · rec TD {sim.rec_td ?? "—"} · FG {sim.fg ?? "—"}
      </p>
      {p.has_espn ? (
        <>
          <h3 className="subh">ESPN week proj (their stats)</h3>
          <p className="muted">{p.espn_line || "—"}</p>
          <p className="muted">
            If that volume hits, mean-line EV is {p.espn_gbfl ?? "—"} — not the P50 ({p.proj.p50}). ESPN FPTS{" "}
            {p.espn_pts || "—"} is their scoring — ignore it.
          </p>
          {(p.espn_explain?.lines || []).map((ln) => (
            <p className="why" key={ln}>
              {ln}
            </p>
          ))}
        </>
      ) : null}
      <h3 className="subh">How that becomes points</h3>
      <p className="muted">
        Expected value from sim means (fractional TDs are averages). That is also an EV, not the P50. The percentile
        table is scored games in this format.
      </p>
      {(p.proj.explain?.lines || []).map((ln) => (
        <p className="why" key={ln}>
          {ln}
        </p>
      ))}
      {p.proj.explain?.rows && (
        <table style={{ maxWidth: 520 }}>
          <thead>
            <tr>
              <th>Category</th>
              <th>Input</th>
              <th>Pts</th>
            </tr>
          </thead>
          <tbody>
            {p.proj.explain.rows.map((r) => (
              <tr key={r.cat}>
                <td>{r.cat}</td>
                <td>
                  {r.input}
                  {r.note ? <div className="why">{r.note}</div> : null}
                </td>
                <td>{r.pts ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function WeekCompare({ a, b, aFa, bFa }: { a: Player; b: Player; aFa?: boolean; bFa?: boolean }) {
  const sparkMax = Math.max(a.proj.p90, b.proj.p90, 0.01);
  const sa = a.proj.sim || {};
  const sb = b.proj.sim || {};
  const ua = a.proj.usage;
  const ub = b.proj.usage;
  const pctRows: { label: string; key: Obj }[] = [
    { label: "10th (floor)", key: "p10" },
    { label: "25th", key: "p25" },
    { label: "50th (median)", key: "p50" },
    { label: "75th", key: "p75" },
    { label: "90th (ceiling)", key: "p90" },
  ];
  return (
    <>
      <div className="grid-cmp" style={{ marginTop: "0.75rem" }}>
        <div>
          <div className="name">
            {a.player} <Badge p={a} />
          </div>
          <div className="pos">
            {a.pos} · {a.team}
            {a.role_note ? ` · ${a.role_note}` : ""}
            {aFa ? " · FA" : ""}
          </div>
          {vegasLine(a) ? <div className="muted vegas-line">{vegasLine(a)}</div> : null}
          <div className="row" style={{ marginTop: "0.4rem", alignItems: "flex-end" }}>
            <Spark p={a.proj} maxScale={sparkMax} />
          </div>
          <EvVsP50 ev={a.espn_gbfl} p50={a.proj.p50} />
        </div>
        <div>
          <div className="name">
            {b.player} <Badge p={b} />
          </div>
          <div className="pos">
            {b.pos} · {b.team}
            {b.role_note ? ` · ${b.role_note}` : ""}
            {bFa ? " · FA" : ""}
          </div>
          {vegasLine(b) ? <div className="muted vegas-line">{vegasLine(b)}</div> : null}
          <div className="row" style={{ marginTop: "0.4rem", alignItems: "flex-end" }}>
            <Spark p={b.proj} maxScale={sparkMax} />
          </div>
          <EvVsP50 ev={b.espn_gbfl} p50={b.proj.p50} />
        </div>
      </div>
      <p className="muted" style={{ marginTop: "0.35rem" }}>
        Bands share a scale so height is comparable. Green = higher GBFL points at that percentile. Mean-line EV, not
        the P50 — buckets make those two disagree.
      </p>
      <table className="cmp">
        <thead>
          <tr>
            <th></th>
            <th>{a.player}</th>
            <th>{b.player}</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Weekly</td>
            <td title={weeklyTip(a)}>{weeklyLabel(a)}</td>
            <td title={weeklyTip(b)}>{weeklyLabel(b)}</td>
          </tr>
          <tr>
            <td title="§7's top signal: O/U is the scoring environment, spread is who controls game script. Negative = favored by that many; positive = underdog.">
              Vegas
            </td>
            <td>{vegasLine(a) || "—"}</td>
            <td>{vegasLine(b) || "—"}</td>
          </tr>
          <tr>
            <td title="Opposing defense's own shrunk points-allowed-by-position rate (a couple of games is mostly noise, so this leans on the league average early), plus their pass rush's pull on TD distance.">
              Matchup
            </td>
            <td>{matchupLine(a) || "—"}</td>
            <td>{matchupLine(b) || "—"}</td>
          </tr>
          <tr>
            <td>ESPN stats</td>
            {espnCell(a)}
            {espnCell(b)}
          </tr>
          {pctRows.map((r) => (
            <tr key={r.key}>
              <td>{r.label}</td>
              <CmpCell a={a.proj[r.key]} b={b.proj[r.key]} />
              <CmpCell a={b.proj[r.key]} b={a.proj[r.key]} />
            </tr>
          ))}
          <tr>
            <td>Mean</td>
            <CmpCell a={a.proj.mean} b={b.proj.mean} />
            <CmpCell a={b.proj.mean} b={a.proj.mean} />
          </tr>
          <tr>
            <td>Pass yds</td>
            <td>{simVal(sa, "pass_yds")}</td>
            <td>{simVal(sb, "pass_yds")}</td>
          </tr>
          <tr>
            <td>Rush yds</td>
            <td>{simVal(sa, "rush_yds")}</td>
            <td>{simVal(sb, "rush_yds")}</td>
          </tr>
          <tr>
            <td>Rec yds</td>
            <td>{simVal(sa, "rec_yds")}</td>
            <td>{simVal(sb, "rec_yds")}</td>
          </tr>
          <tr>
            <td>Pass TD</td>
            <td>{simVal(sa, "pass_td")}</td>
            <td>{simVal(sb, "pass_td")}</td>
          </tr>
          <tr>
            <td>Rush TD</td>
            <td>{simVal(sa, "rush_td")}</td>
            <td>{simVal(sb, "rush_td")}</td>
          </tr>
          <tr>
            <td>Rec TD</td>
            <td>{simVal(sa, "rec_td")}</td>
            <td>{simVal(sb, "rec_td")}</td>
          </tr>
          <tr>
            <td>Targets / carries</td>
            <td>
              {ua?.targets ?? "—"} / {ua?.carries ?? "—"}
            </td>
            <td>
              {ub?.targets ?? "—"} / {ub?.carries ?? "—"}
            </td>
          </tr>
        </tbody>
      </table>
      <div className="grid-cmp">
        <div>
          <h3 className="subh">{a.player}</h3>
          {(a.proj.explain?.lines || []).map((ln) => (
            <p className="why" key={ln}>
              {ln}
            </p>
          ))}
        </div>
        <div>
          <h3 className="subh">{b.player}</h3>
          {(b.proj.explain?.lines || []).map((ln) => (
            <p className="why" key={ln}>
              {ln}
            </p>
          ))}
        </div>
      </div>
    </>
  );
}

function fmtDelta(n: number) {
  return n > 0 ? `+${n}` : String(n);
}

function DriverChips({ drivers }: { drivers: ReportDriver[] }) {
  return (
    <span className="driver-chips">
      {drivers.map((d) => (
        <span key={d} className="tag">
          {d}
        </span>
      ))}
    </span>
  );
}

function ReportCardView({ report, onOpen }: { report: ReportCard; onOpen: (name: string) => void }) {
  const empty = report.status === "no_lock" || report.status === "no_actuals";
  return (
    <div>
      <div className="banner">{report.banner}</div>
      <div className="callout">{report.format_note}</div>
      <p className="muted">
        Week {report.week} · {report.team} · mix at lock {report.mix_label || "—"}
      </p>
      {(report.pending || []).length ? (
        <div className="paper">
          <strong>No box yet (MNF / DNP)</strong>
          <p className="muted">{(report.pending || []).join(", ")} — omitted from grades, not scored as 0.</p>
        </div>
      ) : null}
      {report.status === "no_lock" ? (
        <div className="paper">
          <strong>No lock for this week</strong>
          <p className="muted">Lock week {report.week} next to Refresh before kickoff (or after, knowing it is stale).</p>
        </div>
      ) : null}
      {report.status === "no_actuals" ? (
        <div className="paper">
          <strong>Locked lineup</strong>
          <p className="muted">Refresh CBS after games to pull week-{report.week} box scores and grade vs the band.</p>
          <table>
            <thead>
              <tr>
                <th>Player</th>
                <th>Slot</th>
                <th>Rec?</th>
                <th>Injury</th>
              </tr>
            </thead>
            <tbody>
              {(report.locked_lineup || []).map((g) => (
                <tr key={g.player} className="clickrow" onClick={() => onOpen(g.player)}>
                  <td>
                    {g.player} <span className="pos">{g.pos}</span>
                  </td>
                  <td>{g.slot || "Bench"}</td>
                  <td>{g.rec ? "yes" : ""}</td>
                  <td>{g.designation || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {!empty ? (
      <>
      <div className="report-split">
        <div className="paper">
          <strong>Went right</strong>
          {report.went_right.map((h) => (
            <div key={h.player}>
              <div className="name clickrow" onClick={() => onOpen(h.player)}>
                {h.player} <span className="pos">{h.pos}</span>
              </div>
              <div className="muted">
                {h.actual} vs Exp {h.exp} ({fmtDelta(h.actual - h.exp)})
              </div>
              <p className="why">{h.why}</p>
            </div>
          ))}
        </div>
        <div className="paper">
          <strong>Went wrong</strong>
          {report.went_wrong.map((h) => (
            <div key={h.player}>
              <div className="name clickrow" onClick={() => onOpen(h.player)}>
                {h.player} <span className="pos">{h.pos}</span>
              </div>
              <div className="muted">
                {h.actual} vs Exp {h.exp} ({fmtDelta(h.actual - h.exp)})
              </div>
              <p className="why">{h.why}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="paper" style={{ marginTop: "0.75rem" }}>
        <strong>Grade vs the band</strong>
        <p className="muted">
          {report.grades_note ||
            "Actual GBFL vs locked P50. Bust < P25 · typical P25–P75 · boom > P75."}
          {report.mock ? " Invented in this mock." : ""}
        </p>
        <table>
          <thead>
            <tr>
              <th>Player</th>
              <th>Slot</th>
              <th>Rec?</th>
              <th>Actual</th>
              <th title="Expected points (mean) at lock time">Exp</th>
              <th>Band</th>
              <th>Delta</th>
            </tr>
          </thead>
          <tbody>
            {report.grades
              .slice()
              .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
              .map((g) => (
              <tr key={g.player} className="clickrow" onClick={() => onOpen(g.player)}>
                <td>
                  {g.player} <span className="pos">{g.pos}</span>
                </td>
                <td>{g.slot || "Bench"}</td>
                <td>{g.rec ? "yes" : ""}</td>
                <td>{g.actual}</td>
                <td>{g.exp}</td>
                <td className={g.band === "boom" ? "cmp-win" : g.band === "bust" ? "cmp-lose" : undefined}>{g.band}</td>
                <td className={g.delta > 0 ? "cmp-win" : g.delta < 0 ? "cmp-lose" : undefined}>{fmtDelta(g.delta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="paper" style={{ marginTop: "0.75rem" }}>
        <strong>Start/Sit hindsight</strong>
        {report.sit_misses.length ? (
          report.sit_misses.map((m) => (
          <div className="close" key={`${m.started}|${m.sat}`}>
            <strong>
              {m.started} ({m.started_actual}) vs {m.sat} ({m.sat_actual}).
            </strong>{" "}
            {m.text}
          </div>
          ))
        ) : (
          <p className="muted">No start/sit miss vs actuals.</p>
        )}
      </div>
      </>
      ) : null}
      {report.status !== "no_lock" ? (
      <>
      <div className="paper" style={{ marginTop: "0.75rem" }}>
        <strong>Looking ahead</strong>
        <p className="muted">
          Locked Exp (mean) vs now after Refresh. Chips are input diffs (3g / injury / depth / ESPN), not a split of the delta.
        </p>
        {report.outlook_note ? <p className="why">{report.outlook_note}</p> : null}
        <table>
          <thead>
            <tr>
              <th>Player</th>
              <th>Locked Exp</th>
              <th>Now Exp</th>
              <th>Δ</th>
              <th>Drivers</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {report.outlook.map((o) => (
              <tr key={o.player} className="clickrow" onClick={() => onOpen(o.player)}>
                <td>
                  {o.player} <span className="pos">{o.pos}</span>
                </td>
                <td>{o.locked_exp}</td>
                <td>{o.now_exp}</td>
                <td className={o.delta > 0 ? "cmp-win" : o.delta < 0 ? "cmp-lose" : undefined}>{fmtDelta(o.delta)}</td>
                <td>
                  <DriverChips drivers={o.drivers} />
                </td>
                <td>
                  <div className="why" style={{ margin: 0, maxWidth: "22rem" }}>
                    {o.note}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ marginTop: "0.75rem" }}>
        <strong>Next-week add/drops</strong>
        <p className="muted">
          {report.mock ? "Same suggestions as Waivers (invented reasons in this mock). " : "Current waiver recs. "}
          Does not POST to CBS.
        </p>
        {report.actions.map((r) => (
          <div className="pair paper" key={r.add.player + r.drop.player}>
            <div>
              <div className="pos">Add</div>
              <div className="name clickrow" onClick={() => onOpen(r.add.player)}>
                {r.add.player}
              </div>
              <div className="muted">
                {r.add.pos} · present {r.add.present} · future {r.add.future} · keeper {r.add.keeper} · board{" "}
                {r.add.board_rank ?? "—"} · weekly {weeklyLabel(r.add)}
              </div>
            </div>
            <div className="arrow">→ drop</div>
            <div>
              <div className="pos">Drop</div>
              <div className="name clickrow" onClick={() => onOpen(r.drop.player)}>
                {r.drop.player}
              </div>
              <div className="muted">
                {r.drop.pos} · present {r.drop.present} · future {r.drop.future} · keeper {r.drop.keeper} · board{" "}
                {r.drop.board_rank ?? "—"} · weekly {weeklyLabel(r.drop)}
              </div>
            </div>
            <div style={{ gridColumn: "1 / -1" }} className="why">
              {r.reason}
            </div>
          </div>
        ))}
      </div>
      </>
      ) : null}
      {report.tracking ? <TrackingCard t={report.tracking} /> : null}
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("roster");
  const [week, setWeek] = useState(1);
  const [boardSlider, setBoardSlider] = useState(0.35);
  const [boardWeight, setBoardWeight] = useState(0.35);
  const [mock, setMock] = useState(false);
  const [changedOnly, setChangedOnly] = useState(false);
  const [rosterDense, setRosterDense] = useState(false);
  const [objective, setObjective] = useState<Obj>(DEFAULT_OBJECTIVE);
  const [allowInjured, setAllowInjured] = useState(false);
  const [picked, setPicked] = useState<string>("");
  const [pickedB, setPickedB] = useState<string>("");
  const [waiverPos, setWaiverPos] = useState<PosFilter>("ALL");
  const [waiverSort, setWaiverSort] = useState<SortState>(null);
  const [espnMix, setEspnMix] = useState<EspnMix>(0.5);
  const [data, setData] = useState<WeekPayload | null>(null);
  const [currentWeek, setCurrentWeek] = useState<CurrentWeek | null>(null);
  const [report, setReport] = useState<ReportCard | null>(null);
  const [reportTick, setReportTick] = useState(0);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(true);
  const [busyLabel, setBusyLabel] = useState("Loading week…");
  const [waiverBusy, setWaiverBusy] = useState(false);
  const reqSeq = useRef(0);
  const waiverSeq = useRef(0);

  async function refresh(preferMock = mock, label = "Recalculating projections…") {
    const seq = ++reqSeq.current;
    setBusy(true);
    setBusyLabel(label);
    setErr("");
    try {
      const d = await loadWeek(week, boardWeight, preferMock, allowInjured, espnMix);
      if (seq !== reqSeq.current) return;
      setData(d);
      setMock(d.mock);
    } catch (e) {
      if (seq !== reqSeq.current) return;
      setErr(String(e));
    } finally {
      if (seq === reqSeq.current) setBusy(false);
    }
  }

  async function onCbsRefresh() {
    if (mock) {
      await refresh(true, "Loading fixture…");
      return;
    }
    const seq = ++reqSeq.current;
    setBusy(true);
    setBusyLabel("Refreshing CBS roster…");
    setErr("");
    try {
      await postRefresh(week);
      if (seq !== reqSeq.current) return;
      setReportTick((t) => t + 1);
      await refresh(false, "Recalculating projections…");
    } catch (e) {
      if (seq !== reqSeq.current) return;
      setErr(String(e));
      try {
        await refresh(false, "Recalculating projections…");
      } catch {
        /* keep the refresh error */
      }
    }
  }

  async function refreshWaivers() {
    if (mock) {
      setData((d) => (d ? { ...d, waivers: { ...d.waivers, board_weight: boardWeight } } : d));
      return;
    }
    const seq = ++waiverSeq.current;
    setWaiverBusy(true);
    setErr("");
    try {
      const w = await loadWaivers(week, boardWeight, espnMix);
      if (seq !== waiverSeq.current) return;
      setData((d) => (d ? { ...d, waivers: w } : d));
    } catch (e) {
      if (seq !== waiverSeq.current) return;
      setErr(String(e));
    } finally {
      if (seq === waiverSeq.current) setWaiverBusy(false);
    }
  }

  useEffect(() => {
    const t = window.setTimeout(() => setBoardWeight(boardSlider), 400);
    return () => window.clearTimeout(t);
  }, [boardSlider]);

  useEffect(() => {
    refresh(mock, "Recalculating projections…");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [week, allowInjured, espnMix]);

  useEffect(() => {
    // Pin the week picker to CBS's own idea of "current" on first load only —
    // a default, not a lock; picking another week afterward stays sticky for
    // the rest of the session.
    loadCurrentWeek().then((cw) => {
      setCurrentWeek(cw);
      if (cw?.week) setWeek(cw.week);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onLockWeek() {
    const seq = ++reqSeq.current;
    setBusy(true);
    setBusyLabel(`Locking week ${week}…`);
    setErr("");
    try {
      await postLock(week, espnMix, boardWeight, mock, objective, allowInjured);
      if (seq !== reqSeq.current) return;
      setReportTick((t) => t + 1);
    } catch (e) {
      if (seq !== reqSeq.current) return;
      setErr(String(e));
    } finally {
      if (seq === reqSeq.current) setBusy(false);
    }
  }

  useEffect(() => {
    loadReport(week, mock, espnMix, boardWeight)
      .then(setReport)
      .catch((e) => setErr(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [week, mock, espnMix, boardWeight, reportTick]);

  useEffect(() => {
    if (!data) return;
    if (data.waivers && Math.abs((data.waivers.board_weight ?? boardWeight) - boardWeight) < 1e-9) return;
    refreshWaivers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boardWeight, data]);

  const faPool = useMemo(() => {
    if (!data) return [];
    const names = new Set(data.roster.map((p) => p.player));
    return (data.fa_sample || []).filter((p) => !names.has(p.player));
  }, [data]);

  const roster = useMemo(() => {
    const rows = data?.roster ?? [];
    return changedOnly ? rows.filter((p) => p.status_changed || p.injury || /injured|ir/i.test(p.slot || "")) : rows;
  }, [data, changedOnly]);

  const lineup =
    data?.lineups?.[objective] || (objective === "p10" ? data?.lineup_p10 : data?.lineup_p50);
  const objMeta = OBJ_OPTIONS.find((o) => o.id === objective);
  const starterWhy = Object.fromEntries(
    (lineup?.why || []).filter((w) => w.kind !== "close" && !/ vs /i.test(w.player)).map((w) => [w.player, w.text])
  );
  const closeCalls = (lineup?.why || []).filter((w) => w.kind === "close" || / vs /i.test(w.player));
  const bench = useMemo(() => {
    const POS: Record<string, number> = { QB: 0, RB: 1, WR: 2, TE: 3, K: 4, DST: 5 };
    return [...(lineup?.bench || [])].sort((a, b) => {
      const pa = POS[(a.pos || "").toUpperCase()] ?? 9;
      const pb = POS[(b.pos || "").toUpperCase()] ?? 9;
      if (pa !== pb) return pa - pb;
      const sa = a.proj?.[objective] ?? 0;
      const sb = b.proj?.[objective] ?? 0;
      if (sa !== sb) return sb - sa;
      return a.player.localeCompare(b.player);
    });
  }, [lineup, objective]);

  async function onImport(kind: "dynasty" | "redraft", f: File | undefined) {
    if (!f) return;
    setBusy(true);
    setBusyLabel("Importing rankings…");
    try {
      await importRankings(kind === "dynasty" ? f : undefined, kind === "redraft" ? f : undefined);
      await refresh(false, "Recalculating projections…");
    } catch (e) {
      setErr("Import needs the API running (uvicorn). " + e);
      setBusy(false);
    }
  }

  function openWeek(name: string) {
    setPicked(name);
    setTab("week");
  }

  const pendingBoard = boardSlider !== boardWeight;
  const showBusy = busy || pendingBoard || waiverBusy;
  const shownLabel = busy ? busyLabel : "Recalculating waivers…";
  const dimStage = busy;
  const capsLine =
    "Active: QB 1 · RB 1–4 · WR 1–4 · TE 1–2 · K 1 · DST 1. Skill starters = 7 with those maxes (cannot start a 5th RB). Roster totals 2/5/6/2/2/2; Injured 0–3 can push to 22.";

  return (
    <div className={`shell${showBusy ? " is-busy" : ""}`}>
      {data && (mock || data.mock) ? (
        <div className="banner">
          Fixture JSON — not live scoring. Uncheck Fixture only to hit the API.
        </div>
      ) : data ? (
        <div className="muted" style={{ marginBottom: "0.5rem" }}>
          Live engines — P10–P90 are this league’s Monte Carlo around the selected stat line
          ({data.espn_mix_label || "50/50"}), not CBS projected points.
        </div>
      ) : null}
      <header className="top">
        <div>
          <h1>BUSSONE</h1>
          <div className="meta">GBFL · {capsLine} · 4 keepers any position</div>
        </div>
        <div className="row actions">
          <label>
            Week{" "}
            <select
              value={week}
              onChange={(e) => {
                setWeek(Number(e.target.value));
                setBusy(true);
                setBusyLabel("Loading week…");
              }}
            >
              {Array.from({ length: 18 }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n}
                  {currentWeek?.week === n ? " (current)" : ""}
                </option>
              ))}
            </select>
          </label>
          {currentWeek?.week && currentWeek.week !== week ? (
            <button className="ghost" type="button" onClick={() => setWeek(currentWeek.week as number)} title={`CBS's current week, per its own live injury report (${currentWeek.source || "cbs"})`}>
              Jump to current (Week {currentWeek.week})
            </button>
          ) : null}
          <label className="chk">
            <input
              type="checkbox"
              checked={mock}
              onChange={(e) => {
                const on = e.target.checked;
                setMock(on);
                refresh(on, on ? "Loading fixture…" : "Loading live week…");
              }}
            />
            Fixture only
          </label>
          <button className="ghost" type="button" onClick={() => onCbsRefresh()} disabled={busy}>
            {busy ? "Working…" : "Refresh"}
          </button>
          <button className="ghost" type="button" onClick={() => onLockWeek()} disabled={busy} title="Snapshot this week's P50, lineup, injuries, and usage before kickoff">
            Lock week {week}
          </button>
          <label className="ghost">
            Import dynasty{" "}
            <input type="file" accept=".csv" hidden onChange={(e) => onImport("dynasty", e.target.files?.[0])} />
          </label>
          <label className="ghost">
            Import redraft{" "}
            <input type="file" accept=".csv" hidden onChange={(e) => onImport("redraft", e.target.files?.[0])} />
          </label>
          <label className="ghost">
            Import weekly{" "}
            <input
              type="file"
              accept=".csv"
              hidden
              multiple
              onChange={async (e) => {
                const files = [...(e.target.files || [])];
                e.target.value = "";
                if (!files.length) return;
                setBusy(true);
                setBusyLabel("Importing weekly ranks…");
                try {
                  await importWeekly(files, week);
                  await refresh(false, "Recalculating projections…");
                } catch (err) {
                  setErr("Weekly import needs the API running (uvicorn). " + err);
                  setBusy(false);
                }
              }}
            />
          </label>
          <label className="ghost">
            Import ESPN{" "}
            <input
              type="file"
              accept=".har"
              hidden
              onChange={async (e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                setBusy(true);
                setBusyLabel("Importing ESPN…");
                try {
                  await importEspn(f, week);
                  await refresh(false, "Recalculating projections…");
                } catch (err) {
                  setErr("ESPN import needs the API running (uvicorn). " + err);
                  setBusy(false);
                }
              }}
            />
          </label>
        </div>
      </header>
      {err && <div className="banner">{err}</div>}
      {data?.freshness ? (
        <div className="freshness-row">
          <FreshnessChip entry={data.freshness.cbs} />
          <FreshnessChip entry={data.freshness.injuries} />
          <FreshnessChip entry={data.freshness.espn} />
          <FreshnessChip entry={data.freshness.weekly_fp} />
          <FreshnessChip entry={data.freshness.vegas} />
          <FreshnessChip entry={data.freshness.nflverse} />
        </div>
      ) : null}
      <div className="muted">
        Rankings as of {data?.rankings_as_of || "—"}
        {data?.espn_mix_label ? ` · stat line ${data.espn_mix_label}` : ""}
        {data?.data_flags && !data.data_flags.has_3g_usage ? "" : ""}
      </div>
      {data?.data_flags && data.data_flags.fp_week_match === false ? (
        <div className="banner">Opp from CBS week {week}. FantasyPros ranks are another week — Import weekly for this slate.</div>
      ) : null}
      {data?.data_flags && data.data_flags.espn_week_match === false ? (
        <div className="banner">ESPN column/mix skipped — the import on file is not week {week}. Import ESPN.</div>
      ) : null}
      <div className="cmp-chips mix-row">
        <span className="muted">Stat line</span>
        {ESPN_MIXES.map((m) => (
          <button
            key={m.id}
            className={`chip${espnMix === m.id ? " on" : ""}`}
            type="button"
            disabled={mock}
            title={mock ? "Uncheck Fixture only to change the mix" : m.title}
            onClick={() => {
              if (m.id === espnMix) return;
              setEspnMix(m.id);
              setBusy(true);
              setBusyLabel("Recalculating projections…");
            }}
          >
            {m.label}
          </button>
        ))}
        <span className="muted">
          {espnMix === 0
            ? "P10–P90 from our prior only. ESPN column is still their week stats."
            : espnMix === 1
              ? "Sim centered on ESPN yards/TDs, scored in this format."
              : "Our prior and ESPN week stats, averaged, then simulated."}
        </span>
      </div>
      {showBusy && (
        <div className="busy-strip" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <span>{shownLabel}</span>
          {data ? <span className="busy-note">Numbers below are from the last finished run.</span> : null}
        </div>
      )}
      <nav className="tabs">
        {(
          [
            ["roster", "Roster"],
            ["lineup", "Start/Sit"],
            ["waivers", "Waivers"],
            ["week", `Week ${week}`],
            ["report", "Report"],
          ] as const
        ).map(([id, label]) => (
          <button key={id} className={tab === id ? "on" : ""} type="button" onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>

      <div className={`stage${dimStage && tab !== "report" ? " is-busy" : ""}`} aria-busy={showBusy && tab !== "report"}>
      {!data && !showBusy && tab !== "report" && (
        <div className="paper">
          <p className="muted">No week loaded. Start the API (`uvicorn` on port 8000) or check Fixture only.</p>
        </div>
      )}
      {!data && showBusy && tab !== "report" && (
        <div className="paper busy-panel">
          <p>
            <strong>{shownLabel}</strong>
          </p>
          <p className="muted">
            Simulating one-game GBFL scores for the roster and waiver pool. This usually takes several seconds.
          </p>
        </div>
      )}
      {tab === "report" && (
        report ? (
          <ReportCardView report={report} onOpen={openWeek} />
        ) : (
          <div className="paper">
            <p className="muted">Loading mock report…</p>
          </div>
        )
      )}
      {tab === "roster" && data && (
        <div className="paper">
          <div className="row roster-tools">
            <label className="chk">
              <input type="checkbox" checked={changedOnly} onChange={(e) => setChangedOnly(e.target.checked)} />
              Status changed only
            </label>
            <label className="chk">
              <input type="checkbox" checked={rosterDense} onChange={(e) => setRosterDense(e.target.checked)} />
              Dense
            </label>
            <span className="muted">
              {rosterDense
                ? "Notes, usage, board, and the rest of the band. Click a row for Week."
                : "Click a row for notes, usage, and the rest of the band."}
            </span>
          </div>
          <table>
            <thead>
              <tr>
                <th>Player</th>
                <th>Slot</th>
                <th>Opp</th>
                <th>Weekly</th>
                <th title={ESPN_EV_VS_P50}>ESPN</th>
                <th title="Expected points (mean) — variance is free in this league, so this is what every ranking here targets, not the median.">Mean</th>
                <th>Band</th>
                <th title={GRADE_TIP.role}>Role</th>
                <th title={GRADE_TIP.par}>PAR</th>
                <th title={GRADE_TIP.matchup}>Matchup</th>
                {rosterDense ? (
                  <>
                    <th>P10</th>
                    <th>P25</th>
                    <th>P50</th>
                    <th>P75</th>
                    <th>P90</th>
                    <th>Depth</th>
                    <th>Notes</th>
                    <th title={`${GRADE_TIP.wopr} ${GRADE_TIP.opp_share}`}>Usage</th>
                    <th>Board</th>
                  </>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {roster.map((p) => (
                <tr key={p.player} className="clickrow" onClick={() => openWeek(p.player)}>
                  <td>
                    <div className="name">
                      {p.player} <Badge p={p} /> <GradeFlags g={p.grade} />
                    </div>
                    <div className="pos">
                      {p.pos} · {p.team}
                    </div>
                  </td>
                  <td>{p.slot || p.pos}</td>
                  <td title={weeklyTip(p)}>{p.weekly_opp || "—"}</td>
                  <td title={weeklyTip(p)}>{weeklyLabel(p)}</td>
                  {espnCell(p, true)}
                  <td>{p.proj?.mean ?? "—"}</td>
                  <td>{p.proj && <Spark p={p.proj} />}</td>
                  {roleCell(p)}
                  {parCell(p)}
                  {matchupCell(p)}
                  {rosterDense ? (
                    <>
                      <td>{p.proj?.p10 ?? "—"}</td>
                      <td>{p.proj?.p25 ?? "—"}</td>
                      <td>{p.proj?.p50 ?? "—"}</td>
                      <td>{p.proj?.p75 ?? "—"}</td>
                      <td>{p.proj?.p90 ?? "—"}</td>
                      <td title={p.role_note || "No team depth-chart rank yet"}>{p.role_note || "—"}</td>
                      <td>
                        {(p.roster_note?.text || p.injury?.note) && (
                          <div className="why" title={p.roster_note?.source || p.injury?.source}>
                            {p.roster_note?.text || p.injury?.note}
                          </div>
                        )}
                      </td>
                      <td title={p.grade ? gradeTitle(p.grade) : ""}>{p.grade ? usageText(p.grade) : "—"}</td>
                      <td>{p.board_rank ?? "—"}</td>
                    </>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "lineup" && data && lineup && (
        <div className="grid2">
          <div className="paper">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>
                Starters · best {objMeta?.label || objective} · {lineup.total}
                {lineup.mix ? ` · mix ${lineup.mix.RB} RB / ${lineup.mix.WR} WR / ${lineup.mix.TE} TE` : ""}
              </strong>
              <label>
                Optimize{" "}
                <select value={objective} onChange={(e) => setObjective(e.target.value as Obj)}>
                  {OBJ_OPTIONS.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              {(() => {
                const suggestion = seasonStageSuggestion(week);
                if (!suggestion || suggestion.obj === objective) return null;
                return (
                  <button
                    className="ghost"
                    type="button"
                    title="Not a rule — variance is free in this format, so this is just a seasonal risk-preference nudge: upside early, balanced mid-season, protect the lead late."
                    onClick={() => setObjective(suggestion.obj)}
                  >
                    Week {week} suggestion: {suggestion.label}
                  </button>
                );
              })()}
              <label className="chk">
                <input
                  type="checkbox"
                  checked={allowInjured}
                  onChange={(e) => {
                    setAllowInjured(e.target.checked);
                    setBusy(true);
                    setBusyLabel("Recalculating lineup…");
                  }}
                />
                Override injured
              </label>
            </div>
            <p className="muted">
              Active max 4 RB / 4 WR / 2 TE. Out = 0. Q/D cut snaps/volume in the sim (floor more
              than the ceiling); points are still GBFL scores. A healthy player wins a tie. ESPN
              volume follows the Stat line mix above (Monte Carlo / 50/50 / ESPN). The ESPN column is
              always their raw week stats.
            </p>
            {closeCalls.map((w) => (
              <div className="close" key={w.player}>
                <strong>{w.player}.</strong> {w.text}
              </div>
            ))}
            <table>
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Player</th>
                  {PCTS.map((k) => (
                    <th key={k} className={k === objective ? "obj-col" : undefined}>
                      {k.toUpperCase()}
                    </th>
                  ))}
                  <th>Band</th>
                </tr>
              </thead>
              <tbody>
                {lineup.starters.map((p) => (
                  <tr key={p.player}>
                    <td>{p.lineup_slot}</td>
                    <td>
                      <div className="name">{p.player}</div>
                      <div className="pos">{p.pos}</div>
                      {starterWhy[p.player] && <div className="starter-why">{starterWhy[p.player]}</div>}
                    </td>
                    {PCTS.map((k) => (
                      <td key={k} className={k === objective ? "obj-cell" : undefined}>
                        {p.proj?.[k] ?? "—"}
                      </td>
                    ))}
                    <td>{p.proj && <Spark p={p.proj} highlight={objective} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="paper">
            <strong>Bench · {objective.toUpperCase()}</strong>
            <table>
              <thead>
                <tr>
                  <th>Player</th>
                  {PCTS.map((k) => (
                    <th key={k} className={k === objective ? "obj-col" : undefined}>
                      {k.toUpperCase()}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bench.map((p) => (
                  <tr key={p.player}>
                    <td>
                      {p.player} <span className="pos">{p.pos}</span>
                    </td>
                    {PCTS.map((k) => (
                      <td key={k} className={k === objective ? "obj-cell" : undefined}>
                        {p.proj?.[k] ?? "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "lineup" && data?.grades?.available ? <DstStreamCard g={data.grades} /> : null}

      {tab === "waivers" && data && (() => {
        const recs = (data.waivers?.recommendations || []).filter(
          (r) => waiverPos === "ALL" || (r.add.pos || "").toUpperCase() === waiverPos
        );
        const poolRows = (data.waivers?.fa_top || []).filter((p) => waiverPos === "ALL" || (p.pos || "").toUpperCase() === waiverPos);
        // A remembered sort that none of the visible rows can be ranked by (Role on DST) falls back to the position's default.
        const wanted = waiverSort?.key ?? defaultSort(waiverPos);
        const usable = poolRows.some((p) => sortValue(p, wanted) != null);
        const sortKey = usable ? wanted : defaultSort(waiverPos);
        const sortDir = usable ? waiverSort?.dir ?? "desc" : "desc";
        const faRows = sortRows(poolRows, sortKey, sortDir);
        const faShown = waiverPos === "ALL" ? faRows.slice(0, 30) : faRows;
        const SortTh = ({ k, label, title }: { k: SortKey; label: string; title: string }) => (
          <th
            className="sortable"
            title={`${title} Click to sort.`}
            aria-sort={sortKey === k ? (sortDir === "desc" ? "descending" : "ascending") : "none"}
            onClick={() => setWaiverSort({ key: k, dir: sortKey === k && sortDir === "desc" ? "asc" : "desc" })}
          >
            {label}
            {sortKey === k ? (sortDir === "desc" ? " ▼" : " ▲") : ""}
          </th>
        );
        return (
        <div>
          <p className="muted">{capsLine} Cannot add a 7th WR or 6th RB.</p>
          <div className="row" style={{ marginBottom: "0.75rem" }}>
            <span>Trust this week</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={boardSlider}
              onChange={(e) => setBoardSlider(Number(e.target.value))}
            />
            <span>Trust board</span>
            <span className="muted">{Math.round(boardSlider * 100)}% board · rankings {data.waivers.rankings_as_of || "—"}</span>
          </div>
          <div className="cmp-chips">
            <span className="muted">Position</span>
            {POS_FILTERS.map((pos) => {
              const n =
                pos === "ALL"
                  ? 0
                  : (data.waivers.fa_top || []).filter((p) => (p.pos || "").toUpperCase() === pos).length;
              return (
              <button
                key={pos}
                className={`chip${waiverPos === pos ? " on" : ""}`}
                type="button"
                onClick={() => setWaiverPos(pos)}
              >
                {pos === "ALL" ? "All" : n ? `${pos} ${n}` : pos}
              </button>
              );
            })}
          </div>
          <p className="muted" title={`${WAIVER_COL.past} ${WAIVER_COL.present} ${WAIVER_COL.future} ${WAIVER_COL.keeper}`}>
            {WAIVER_SCORE_KEY}
          </p>
          <p className="muted">
            Roster caps {Object.entries(data.waivers.caps).map(([k, v]) => `${v} ${k}`).join(" · ")}. Active max{" "}
            {Object.entries(data.waivers.active_max || { RB: 4, WR: 4, TE: 2 })
              .map(([k, v]) => `${v} ${k}`)
              .join(" · ")}.
          </p>
          {data.waivers.waiver_priority ? (
            <p className="muted" title="Total-points league, no head-to-head — waivers reset to reverse standings every Tuesday. The leader (you, if this is low) claims last.">
              Tuesday waiver priority: {data.waivers.waiver_priority}/{data.waivers.waiver_teams}
              {data.waivers.waiver_priority === data.waivers.waiver_teams ? " — you're last; don't fight Tuesday scrums, spend claims only on genuine difference-makers." : ""}
            </p>
          ) : null}
          {(data.waivers.ir_candidates || []).length > 0 && (
            <div className="banner">
              {data.waivers.ir_candidates!.map((c) => (
                <div key={c.player}>
                  Move <strong>{c.player}</strong> ({c.pos}, {c.designation}) to IR — {c.note}
                </div>
              ))}
            </div>
          )}
          {data.grades && !data.grades.available && (
            <p className="muted">Usage grades unavailable: {data.grades.reason}. Rankings fall back to this week's expected points.</p>
          )}
          {recs.length === 0 && (
            <p className="muted">
              {waiverPos === "ALL" ? "No add/drops this week." : `No ${waiverPos} add/drops in the current list.`}
            </p>
          )}
          {recs.map((r) => (
            <div className="pair paper" key={r.add.player + r.drop.player}>
              <div>
                <div className="pos">Add</div>
                <div className="name">
                  {r.add.player} <WaiverStatusTag status={r.add.waiver_status} /> <GradeFlags g={r.add.grade} />
                </div>
                <div className="muted">
                  {r.add.pos} · {r.add.grade ? <><span title={gradeTitle(r.add.grade)}>PAR {fmtPar(r.add.grade.par)} · role {r.add.grade.role}</span> · </> : null}
                  {r.add.stream ? <><span title={GRADE_TIP.matchup}>vs {r.add.stream.opp} · {r.add.stream.opp_total}</span> · </> : null}
                  <span title={WAIVER_COL.present}>present {r.add.present}</span> ·{" "}
                  <span title={WAIVER_COL.future}>future {r.add.future}</span> ·{" "}
                  <span title={WAIVER_COL.keeper}>keeper {r.add.keeper}</span> · board {r.add.board_rank ?? "—"} · weekly{" "}
                  {weeklyLabel(r.add)}
                </div>
              </div>
              <div className="arrow">→ drop</div>
              <div>
                <div className="pos">Drop</div>
                <div className="name">
                  {r.drop.player} <GradeFlags g={r.drop.grade} />
                </div>
                <div className="muted">
                  {r.drop.pos} · {r.drop.grade ? <><span title={gradeTitle(r.drop.grade)}>PAR {fmtPar(r.drop.grade.par)} · role {r.drop.grade.role}</span> · </> : null}
                  {r.drop.stream ? <><span title={GRADE_TIP.matchup}>vs {r.drop.stream.opp} · {r.drop.stream.opp_total}</span> · </> : null}
                  <span title={WAIVER_COL.present}>present {r.drop.present}</span> ·{" "}
                  <span title={WAIVER_COL.future}>future {r.drop.future}</span> ·{" "}
                  <span title={WAIVER_COL.keeper}>keeper {r.drop.keeper}</span> · board {r.drop.board_rank ?? "—"} · weekly{" "}
                  {weeklyLabel(r.drop)}
                </div>
              </div>
              <div style={{ gridColumn: "1 / -1" }} className="why">
                {r.reason} (mock if banner is up)
              </div>
            </div>
          ))}
          {data.grades?.available && <DstStreamCard g={data.grades} />}
          {data.grades?.available && <Trackers g={data.grades} week={week} />}
          {(data.format_edges || []).length > 0 && (
            <div className="paper" style={{ marginBottom: "0.75rem" }}>
              <strong title="§8: not a hand-correction, just where FantasyPros' weekly rank and this app's own simulation (by mean, within the same weekly list) disagree most.">
                Format edges
              </strong>
              {(data.format_edges || []).map((e) => (
                <div key={e.player} className="muted">
                  <strong>{e.player}</strong> ({e.pos}) — app #{e.app_rank} vs FantasyPros #{e.fp_rank} on {e.weekly_list}. {e.note}.
                </div>
              ))}
            </div>
          )}
          <div className="paper">
            <strong>
              FA board (scored)
              {waiverPos !== "ALL" ? ` · ${waiverPos}` : ""}
              {faShown.length ? ` · ${faShown.length}` : ""}
            </strong>
            {faShown.length === 0 ? (
              <p className="muted">No scored free agents at this position in the current pool.</p>
            ) : (
            <table>
              <thead>
                <tr>
                  <th>Player</th>
                  <th>Status</th>
                  <SortTh k="role" label="Role" title={GRADE_TIP.role} />
                  <SortTh k="par" label="PAR" title={GRADE_TIP.par} />
                  <SortTh k="exp" label="Exp. games" title={GRADE_TIP.exp_games} />
                  <SortTh k="matchup" label="Matchup" title={GRADE_TIP.matchup} />
                  <th title={WAIVER_COL.past}>Past</th>
                  <SortTh k="present" label="Present" title={WAIVER_COL.present} />
                  <SortTh k="future" label="Future" title={WAIVER_COL.future} />
                  <SortTh k="keeper" label="Keeper" title={WAIVER_COL.keeper} />
                  <th>Board</th>
                  <th>Weekly</th>
                  <th title={ESPN_EV_VS_P50}>ESPN</th>
                </tr>
              </thead>
              <tbody>
                {faShown.map((p) => (
                  <tr
                    key={p.player}
                    className="clickrow"
                    onClick={() => {
                      const same = data.roster.find(
                        (r) => (r.pos || "").toUpperCase() === (p.pos || "").toUpperCase()
                      );
                      if (same) setPicked(same.player);
                      setPickedB(p.player);
                      setTab("week");
                    }}
                  >
                    <td>
                      {p.player} <span className="pos">{p.pos}</span>
                    </td>
                    <td>
                      <WaiverStatusTag status={p.waiver_status} /> <GradeFlags g={p.grade} />
                    </td>
                    {roleCell(p)}
                    {parCell(p, true)}
                    <td title={p.grade ? GRADE_TIP.exp_games : ""}>
                      {p.grade ? p.grade.exp_games : "—"}
                      {p.grade?.status ? <div className="pos">{p.grade.status}</div> : null}
                    </td>
                    {matchupCell(p)}
                    <td>{p.past ?? "—"}</td>
                    <td>{p.present}</td>
                    <td>{p.future}</td>
                    <td>{p.keeper}</td>
                    <td>{p.board_rank ?? "—"}</td>
                    <td title={p.weekly_matchup || ""}>{weeklyLabel(p)}</td>
                    {espnCell(p)}
                  </tr>
                ))}
              </tbody>
            </table>
            )}
          </div>
        </div>
        );
      })()}

      {tab === "week" && data && (
        <div className="paper">
          <div className="callout">{data.format_note}</div>
          <div className="compare-picks">
            <label>
              Player{" "}
              <select value={picked || data.roster[0]?.player || ""} onChange={(e) => setPicked(e.target.value)}>
                <PlayerSelectOptions roster={data.roster} fa={faPool} />
              </select>
            </label>
            <span className="muted">vs</span>
            <label>
              Compare{" "}
              <select
                value={pickedB}
                onChange={(e) => setPickedB(e.target.value)}
              >
                <PlayerSelectOptions roster={data.roster} fa={faPool} includeEmpty="— pick a second player —" />
              </select>
            </label>
            {pickedB ? (
              <button
                className="ghost"
                type="button"
                onClick={() => {
                  const aName = picked || data.roster[0]?.player || "";
                  setPicked(pickedB);
                  setPickedB(aName);
                }}
              >
                Swap
              </button>
            ) : null}
          </div>
          {(() => {
            const seen = new Set<string>();
            const chips: [string, string][] = [];
            for (const w of data.lineups?.mean?.why || data.lineup_mean?.why || data.lineups?.p50?.why || data.lineup_p50?.why || []) {
              const pair = parseVs(w.player);
              if (!pair) continue;
              const key = pair.slice().sort().join("|");
              if (seen.has(key)) continue;
              seen.add(key);
              chips.push(pair);
            }
            if (!chips.length) return null;
            return (
              <div className="cmp-chips">
                <span className="muted">Start/Sit close calls:</span>
                {chips.map(([x, y]) => (
                  <button
                    key={`${x}|${y}`}
                    className="chip"
                    type="button"
                    onClick={() => {
                      setPicked(x);
                      setPickedB(y);
                    }}
                  >
                    {x} vs {y}
                  </button>
                ))}
              </div>
            );
          })()}
          {(() => {
            const a = findPlayer(data, picked || data.roster[0]?.player || "");
            const b = pickedB && pickedB !== a?.player ? findPlayer(data, pickedB) : undefined;
            if (!a?.proj) return null;
            if (b?.proj) {
              const rosterNames = new Set(data.roster.map((p) => p.player));
              return (
                <WeekCompare
                  a={a}
                  b={b}
                  aFa={!rosterNames.has(a.player)}
                  bFa={!rosterNames.has(b.player)}
                />
              );
            }
            return <WeekPlayerBody p={a} mixLabel={data.espn_mix_label} />;
          })()}
          <p className="muted">P90 is the long-TD / long-FG tail. Not a CBS projection.</p>
        </div>
      )}
      </div>
    </div>
  );
}
