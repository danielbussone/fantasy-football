import type { WeekPayload } from "./types";

export async function loadWeek(
  week: number,
  boardWeight: number,
  preferMock: boolean,
  allowInjured = false,
  weeklyWeight = 0.2
): Promise<WeekPayload> {
  if (!preferMock) {
    try {
      const r = await fetch(
        `/api/week?week=${week}&board_weight=${boardWeight}&mock=false&allow_injured=${allowInjured}&weekly_weight=${weeklyWeight}&_=${Date.now()}`,
        { cache: "no-store" }
      );
      if (r.ok) {
        const data = (await r.json()) as WeekPayload;
        data.mock = false;
        return data;
      }
    } catch {
      /* fall through to fixture */
    }
  }
  const r = await fetch("/fixtures/week1.json");
  const data = (await r.json()) as WeekPayload;
  data.mock = true;
  data.week = week;
  data.waivers = { ...data.waivers, board_weight: boardWeight, weekly_weight: weeklyWeight };
  data.weekly_weight = weeklyWeight;
  return data;
}

export async function postRefresh() {
  const r = await fetch("/api/refresh", { method: "POST" });
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
