import { useEffect, useMemo, useState } from "react";
import { importEspn, importRankings, importWeekly, loadWeek, postRefresh } from "./api";
import type { Player, Proj, WeekPayload } from "./types";

type Tab = "roster" | "lineup" | "waivers" | "week";
type Obj = "p10" | "p25" | "p50" | "p75" | "p90";

const OBJ_OPTIONS: { id: Obj; label: string }[] = [
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
const PCT_IDX: Record<Obj, number> = { p10: 0, p25: 1, p50: 2, p75: 3, p90: 4 };

function Spark({ p, highlight }: { p: Proj; highlight?: Obj }) {
  const vals = [p.p10, p.p25, p.p50, p.p75, p.p90];
  const max = Math.max(...vals, 0.01);
  const [open, setOpen] = useState(false);
  const hi = highlight ? PCT_IDX[highlight] : 2;
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

function weeklyLabel(p: { weekly_rank?: number | null; weekly_list?: string | null }) {
  if (p.weekly_rank == null) return "—";
  const list = p.weekly_list || "";
  return list ? `${list} ${p.weekly_rank}` : String(p.weekly_rank);
}

function weeklyTip(p: {
  weekly_matchup?: string;
  weekly_opp?: string;
  weekly_start_sit?: string;
  weekly_proj_fpts?: string;
}) {
  return [p.weekly_matchup, p.weekly_opp, p.weekly_start_sit && `FP ${p.weekly_start_sit}`, p.weekly_proj_fpts && `FP ${p.weekly_proj_fpts} (not this league)`]
    .filter(Boolean)
    .join(" · ");
}

function BreakoutTag({ b }: { b: Player["breakout"] | { flag: string; why: string } | null | undefined }) {
  if (!b) return null;
  const cls = b.flag === "breakout" ? "ok" : "q";
  const label = b.flag === "needs-3g" ? "needs 3g" : b.flag;
  return (
    <span className={`badge ${cls}`} title={b.why}>
      {label}
    </span>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("roster");
  const [week, setWeek] = useState(1);
  const [boardWeight, setBoardWeight] = useState(0.35);
  const [weeklyWeight, setWeeklyWeight] = useState(0.2);
  const [mock, setMock] = useState(true);
  const [changedOnly, setChangedOnly] = useState(false);
  const [objective, setObjective] = useState<Obj>("p50");
  const [allowInjured, setAllowInjured] = useState(false);
  const [picked, setPicked] = useState<string>("");
  const [data, setData] = useState<WeekPayload | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh(preferMock = mock) {
    setBusy(true);
    setErr("");
    try {
      const d = await loadWeek(week, boardWeight, preferMock, allowInjured, weeklyWeight);
      setData(d);
      setMock(d.mock);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onCbsRefresh() {
    if (mock) {
      await refresh(true);
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await postRefresh();
      await refresh(false);
    } catch (e) {
      setErr(String(e));
      try {
        await refresh(false);
      } catch {
        /* keep the refresh error */
      }
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh(mock);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [week, boardWeight, weeklyWeight, allowInjured]);

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
    try {
      await importRankings(kind === "dynasty" ? f : undefined, kind === "redraft" ? f : undefined);
      await refresh(false);
    } catch (e) {
      setErr("Import needs the API running (uvicorn). " + e);
    } finally {
      setBusy(false);
    }
  }

  function openWeek(name: string) {
    setPicked(name);
    setTab("week");
  }

  const capsLine =
    "Active: QB 1 · RB 1–4 · WR 1–4 · TE 1–2 · K 1 · DST 1. Skill starters = 7 with those maxes (cannot start a 5th RB). Roster totals 2/5/6/2/2/2; Injured 0–3 can push to 22.";

  return (
    <div className="shell">
      {(mock || data?.mock) ? (
        <div className="banner">
          Mock mode — fixture JSON. Uncheck Fixture only to use live scoring / Monte Carlo / FastAPI. Not CBS
          projections.
        </div>
      ) : (
        <div className="muted" style={{ marginBottom: "0.5rem" }}>
          Live engines — P10–P90 are this league’s Monte Carlo, not CBS projected points.
        </div>
      )}
      <header className="top">
        <div>
          <h1>BUSSONE</h1>
          <div className="meta">GBFL · {capsLine} · 4 keepers any position</div>
        </div>
        <div className="row actions">
          <label>
            Week{" "}
            <select value={week} onChange={(e) => setWeek(Number(e.target.value))}>
              {Array.from({ length: 18 }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="chk">
            <input type="checkbox" checked={mock} onChange={(e) => { setMock(e.target.checked); refresh(e.target.checked); }} />
            Fixture only
          </label>
          <button className="ghost" type="button" onClick={() => onCbsRefresh()} disabled={busy}>
            Refresh
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
                try {
                  await importWeekly(files, week);
                  await refresh(false);
                } catch (err) {
                  setErr("Weekly import needs the API running (uvicorn). " + err);
                } finally {
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
                try {
                  await importEspn(f, week);
                  await refresh(false);
                } catch (err) {
                  setErr("ESPN import needs the API running (uvicorn). " + err);
                } finally {
                  setBusy(false);
                }
              }}
            />
          </label>
        </div>
      </header>
      {err && <div className="banner">{err}</div>}
      <div className="muted">
        Rankings as of {data?.rankings_as_of || "—"} · Injuries {data?.injury_as_of || "—"}
        {data?.week_fp_stamp ? ` · ${data.week_fp_stamp}` : ""}
        {data?.espn_stamp ? ` · ${data.espn_stamp}` : ""}
        {data?.data_flags && !data.data_flags.has_3g_usage ? " · 3g usage empty (week-1 zeros) — breakout needs a real 3g pull" : ""}
        {busy ? " · loading…" : ""}
      </div>
      <nav className="tabs">
        {(
          [
            ["roster", "Roster"],
            ["lineup", "Start/Sit"],
            ["waivers", "Waivers"],
            ["week", `Week ${week}`],
          ] as const
        ).map(([id, label]) => (
          <button key={id} className={tab === id ? "on" : ""} type="button" onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "roster" && (
        <div className="paper">
          <label className="chk">
            <input type="checkbox" checked={changedOnly} onChange={(e) => setChangedOnly(e.target.checked)} />
            Status changed only
          </label>
          <table>
            <thead>
              <tr>
                <th>Player</th>
                <th>Slot</th>
                <th>Depth</th>
                <th>Injury</th>
                <th>Notes</th>
                <th>Breakout</th>
                <th>Board</th>
                <th>Weekly</th>
                <th>ESPN</th>
                <th>P10</th>
                <th>P25</th>
                <th>P50</th>
                <th>P75</th>
                <th>P90</th>
                <th>Band</th>
              </tr>
            </thead>
            <tbody>
              {roster.map((p) => (
                <tr key={p.player} className="clickrow" onClick={() => openWeek(p.player)}>
                  <td>
                    <div className="name">{p.player}</div>
                    <div className="pos">
                      {p.pos} · {p.team}
                    </div>
                  </td>
                  <td>{p.slot || p.pos}</td>
                  <td title={p.role_note || "No team depth-chart rank yet"}>
                    {p.role_note || "—"}
                  </td>
                  <td>
                    <Badge p={p} />
                  </td>
                  <td>
                    {(p.roster_note?.text || p.injury?.note) && (
                      <div className="why" title={p.roster_note?.source || p.injury?.source}>
                        {p.roster_note?.text || p.injury?.note}
                      </div>
                    )}
                  </td>
                  <td>
                    <BreakoutTag b={p.breakout} />
                    {p.breakout && <div className="why">{p.breakout.why}</div>}
                  </td>
                  <td>{p.board_rank ?? "—"}</td>
                  <td title={weeklyTip(p)}>{weeklyLabel(p)}</td>
                  <td title={p.espn_tip || ""}>{p.has_espn ? p.espn_pts || "yes" : "—"}</td>
                  {PCTS.map((k) => (
                    <td key={k}>{p.proj?.[k] ?? "—"}</td>
                  ))}
                  <td>{p.proj && <Spark p={p.proj} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "lineup" && lineup && (
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
              <label className="chk">
                <input
                  type="checkbox"
                  checked={allowInjured}
                  onChange={(e) => setAllowInjured(e.target.checked)}
                />
                Override injured
              </label>
            </div>
            <div className="row" style={{ margin: "0.5rem 0" }}>
              <span>Trust sim</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={weeklyWeight}
                onChange={(e) => setWeeklyWeight(Number(e.target.value))}
              />
              <span>Trust FP this week</span>
              <span className="muted">{Math.round(weeklyWeight * 100)}% FP</span>
            </div>
            <p className="muted">
              Active max 4 RB / 4 WR / 2 TE. Out = 0/0/0/0/0. Q/D cut the floor more than the ceiling
              (more variance); a healthy player wins a tie. FP slider shifts the curve after the sim;
              ESPN volume is already inside P10–P90 when imported.
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

      {tab === "waivers" && data && (
        <div>
          <p className="muted">{capsLine} Cannot add a 7th WR or 6th RB.</p>
          <div className="row" style={{ marginBottom: "0.75rem" }}>
            <span>Trust this week</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={boardWeight}
              onChange={(e) => setBoardWeight(Number(e.target.value))}
            />
            <span>Trust board</span>
            <span className="muted">{Math.round(boardWeight * 100)}% board · rankings {data.waivers.rankings_as_of || "—"}</span>
          </div>
          <div className="row" style={{ marginBottom: "0.75rem" }}>
            <span>Trust sim</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={weeklyWeight}
              onChange={(e) => setWeeklyWeight(Number(e.target.value))}
            />
            <span>Trust FP this week</span>
            <span className="muted">{Math.round(weeklyWeight * 100)}% FP</span>
          </div>
          <p className="muted">
            Roster caps {Object.entries(data.waivers.caps).map(([k, v]) => `${v} ${k}`).join(" · ")}. Active max{" "}
            {Object.entries(data.waivers.active_max || { RB: 4, WR: 4, TE: 2 })
              .map(([k, v]) => `${v} ${k}`)
              .join(" · ")}.
          </p>
          {!data.data_flags?.has_3g_usage && (
            <p className="muted">Breakout: 3g file has no usable usage yet — markers say “needs 3g pull”, not a fake trend.</p>
          )}
          {data.waivers.recommendations.map((r) => (
            <div className="pair paper" key={r.add.player + r.drop.player}>
              <div>
                <div className="pos">Add</div>
                <div className="name">
                  {r.add.player} <BreakoutTag b={r.add.breakout} />
                </div>
                <div className="muted">
                  {r.add.pos} · present {r.add.present} · future {r.add.future} · keeper {r.add.keeper} · board {r.add.board_rank ?? "—"} · weekly {weeklyLabel(r.add)}
                </div>
                {r.add.breakout && <div className="why">{r.add.breakout.why}</div>}
              </div>
              <div className="arrow">→ drop</div>
              <div>
                <div className="pos">Drop</div>
                <div className="name">{r.drop.player}</div>
                <div className="muted">
                  {r.drop.pos} · present {r.drop.present} · future {r.drop.future} · keeper {r.drop.keeper} · board {r.drop.board_rank ?? "—"} · weekly {weeklyLabel(r.drop)}
                </div>
              </div>
              <div style={{ gridColumn: "1 / -1" }} className="why">
                {r.reason} (mock if banner is up)
              </div>
            </div>
          ))}
          <div className="paper">
            <strong>FA board (scored)</strong>
            <table>
              <thead>
                <tr>
                  <th>Player</th>
                  <th>Breakout</th>
                  <th>Past</th>
                  <th>Present</th>
                  <th>Future</th>
                  <th>Keeper</th>
                  <th>Board</th>
                  <th>Weekly</th>
                  <th>ESPN</th>
                  <th>As of</th>
                </tr>
              </thead>
              <tbody>
                {data.waivers.fa_top.slice(0, 20).map((p) => (
                  <tr key={p.player}>
                    <td>
                      {p.player} <span className="pos">{p.pos}</span>
                    </td>
                    <td>
                      <BreakoutTag b={p.breakout} />
                    </td>
                    <td>{p.past ?? "—"}</td>
                    <td>{p.present}</td>
                    <td>{p.future}</td>
                    <td>{p.keeper}</td>
                    <td>{p.board_rank ?? "—"}</td>
                    <td title={p.weekly_matchup || ""}>{weeklyLabel(p)}</td>
                    <td title={p.espn_tip || ""}>{p.has_espn ? p.espn_pts || "yes" : "—"}</td>
                    <td>{p.rankings_as_of || data.waivers.rankings_as_of || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "week" && data && (
        <div className="paper">
          <div className="callout">{data.format_note}</div>
          <label>
            Player{" "}
            <select value={picked || data.roster[0]?.player || ""} onChange={(e) => setPicked(e.target.value)}>
              {data.roster.map((p) => (
                <option key={p.player}>{p.player}</option>
              ))}
            </select>
          </label>
          {(() => {
            const p = data.roster.find((x) => x.player === (picked || data.roster[0]?.player));
            if (!p?.proj) return null;
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
                  {p.proj && <Spark p={p.proj} />}
                  <span className="muted">Hover the band: width = volatility.</span>
                </div>
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
                <h3 className="subh">Sim means (one game)</h3>
                <p className="muted">
                  Pass yds {sim.pass_yds ?? "—"} · rush {sim.rush_yds ?? "—"} · rec {sim.rec_yds ?? "—"} · pass TD{" "}
                  {sim.pass_td ?? "—"} · rush TD {sim.rush_td ?? "—"} · rec TD {sim.rec_td ?? "—"} · FG {sim.fg ?? "—"}
                </p>
                <h3 className="subh">How that becomes points</h3>
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
          })()}
          <p className="muted">P90 is the long-TD / long-FG tail. Not a CBS projection.</p>
        </div>
      )}
    </div>
  );
}
