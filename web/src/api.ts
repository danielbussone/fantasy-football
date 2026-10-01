import type { WeekPayload, ReportCard, CurrentWeek } from "./types";

export async function loadCurrentWeek(): Promise<CurrentWeek | null> {
  // Best-effort: used only to default the week picker. Any failure (API
  // offline, no CBS pull yet) just means we keep whatever week is already
  // selected instead of surfacing an error for a non-essential nicety.
  try {
    const r = await fetch(`/api/current-week?_=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as CurrentWeek;
  } catch {
    return null;
  }
}

export async function loadWeek(
  week: number,
  boardWeight: number,
  preferMock: boolean,
  allowInjured = false,
  espnMix = 0.5
): Promise<WeekPayload> {
  if (!preferMock) {
    try {
      const r = await fetch(
        `/api/week?week=${week}&board_weight=${boardWeight}&espn_mix=${espnMix}&mock=false&allow_injured=${allowInjured}&_=${Date.now()}`,
        { cache: "no-store" }
      );
      if (r.ok) {
        const data = (await r.json()) as WeekPayload;
        data.mock = false;
        return data;
      }
      // API is up but errored (e.g. a 500) — that's a real bug, not "API
      // offline". Surface it instead of silently swapping in the fixture.
      const body = await r.text().catch(() => "");
      throw new Error(`API /api/week returned ${r.status}${body ? `: ${body.slice(0, 300)}` : ""}`);
    } catch (e) {
      if (e instanceof TypeError) {
        /* network error (API offline/unreachable) — fall through to fixture */
      } else {
        throw e;
      }
    }
  }
  const r = await fetch("/fixtures/week1.json");
  const data = (await r.json()) as WeekPayload;
  data.mock = true;
  data.week = week;
  data.waivers = { ...data.waivers, board_weight: boardWeight };
  return data;
}

export async function loadWaivers(
  week: number,
  boardWeight: number,
  espnMix = 0.5
): Promise<WeekPayload["waivers"]> {
  const r = await fetch(
    `/api/waivers?week=${week}&board_weight=${boardWeight}&espn_mix=${espnMix}&_=${Date.now()}`,
    { cache: "no-store" }
  );
  if (!r.ok) throw new Error("Waiver rescore failed (API offline?)");
  const body = (await r.json()) as { waivers: WeekPayload["waivers"] };
  return body.waivers;
}

export async function postRefresh(week = 1) {
  const r = await fetch(`/api/refresh?week=${week}`, { method: "POST" });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    throw new Error(
      (body as { detail?: string }).detail ||
        "CBS refresh failed (cookies/HAR missing or expired). Roster CSVs were not updated."
    );
  }
  return body;
}

export async function importRankings(dynasty?: File, redraft?: File) {
  const fd = new FormData();
  if (dynasty) fd.append("dynasty", dynasty);
  if (redraft) fd.append("redraft", redraft);
  const r = await fetch("/api/rankings/import", { method: "POST", body: fd });
  if (!r.ok) throw new Error("import failed (API offline?)");
  return r.json();
}

export async function importWeekly(files: File[], week: number) {
  const fd = new FormData();
  for (const f of files) fd.append("weekly", f);
  const r = await fetch(`/api/rankings/import?week=${week}`, { method: "POST", body: fd });
  if (!r.ok) throw new Error("weekly import failed (API offline?)");
  return r.json();
}

export async function importEspn(file: File, week: number) {
  const fd = new FormData();
  fd.append("har", file);
  const r = await fetch(`/api/espn/import?week=${week}`, { method: "POST", body: fd });
  if (!r.ok) throw new Error("ESPN import failed (API offline?)");
  return r.json();
}

export async function postLock(
  week: number,
  espnMix = 0.5,
  boardWeight = 0.35,
  mock = false,
  objective = "p50",
  allowInjured = false
) {
  const r = await fetch(
    `/api/lock?week=${week}&espn_mix=${espnMix}&board_weight=${boardWeight}&mock=${mock}&objective=${objective}&allow_injured=${allowInjured}`,
    { method: "POST" }
  );
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    throw new Error((body as { detail?: string }).detail || "Lock failed (API offline?)");
  }
  return body;
}

export async function loadReport(
  week = 1,
  preferMock = false,
  espnMix = 0.5,
  boardWeight = 0.35
): Promise<ReportCard> {
  if (!preferMock) {
    try {
      const r = await fetch(
        `/api/report?week=${week}&espn_mix=${espnMix}&board_weight=${boardWeight}&_=${Date.now()}`,
        { cache: "no-store" }
      );
      if (r.ok) return (await r.json()) as ReportCard;
      const body = await r.text().catch(() => "");
      throw new Error(`API /api/report returned ${r.status}${body ? `: ${body.slice(0, 300)}` : ""}`);
    } catch (e) {
      if (e instanceof TypeError) {
        /* network error (API offline/unreachable) — fall through to fixture */
      } else {
        throw e;
      }
    }
  }
  const r = await fetch("/fixtures/week1_report.json");
  if (!r.ok) throw new Error("Report fixture missing");
  return r.json();
}
