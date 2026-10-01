"""Pull live CBS roster / FA / stats and dump CSVs for this league.

CBS is the source of truth for who is rostered. Draft logs and typed lists are not.

  python cbs_pull.py --har "C:\\Users\\Danny\\Downloads\\something.har"
  python cbs_pull.py --cookies cbs_cookies.txt

Writes cbs_roster.csv, cbs_fa.csv, cbs_players.csv, roster.json, and regenerates
drafted.csv from CBS so merge.py / the draft canvas keep working. Does not change
ranking scores. HAR/cookies stay out of git.

CBS projections are not used for ranking. Waiver notes use history_*.csv,
kicker_*_fa.csv, dst_history.csv, and combined.csv board context.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from cbs_client import (
    HOST,
    MY_TEAM,
    POSITIONS,
    TEAM_IDS,
    AuthError,
    CBSClient,
    current_week_from_stats_html,
    load_cookie_header,
    norm,
    parse_standings,
    parse_stats_players,
    parse_team_roster,
    parse_depth_chart,
)

ROOT = Path(__file__).resolve().parent
ROSTER_CSV = ROOT / "cbs_roster.csv"
FA_CSV = ROOT / "cbs_fa.csv"
PLAYERS_CSV = ROOT / "cbs_players.csv"
ROSTER_JSON = ROOT / "roster.json"
DRAFTED_CSV = ROOT / "drafted.csv"
STATS_3G = ROOT / "cbs_stats_3g.csv"
DEPTH_CSV = ROOT / "cbs_depth.csv"
CURRENT_WEEK_JSON = ROOT / "current_week.json"
CBS_PULL_META = ROOT / "cbs_pull_meta.json"
STANDINGS_JSON = ROOT / "standings.json"
UNRANKED_POS = {"K", "DST"}


def detect_current_week(client: CBSClient) -> int | None:
    """Ask CBS which week it thinks is current (see current_week_from_stats_html)."""
    try:
        html = client.stats_report("all", "QB", period="tp", kind="stats")
    except (AuthError, ConnectionError, TimeoutError, OSError):
        return None
    return current_week_from_stats_html(html)


def read_current_week() -> dict:
    if not CURRENT_WEEK_JSON.exists():
        return {"week": None, "source": "", "as_of": ""}
    try:
        return json.loads(CURRENT_WEEK_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"week": None, "source": "", "as_of": ""}


def write_current_week(week: int, source: str, when: str | None = None) -> dict:
    payload = {
        "week": int(week),
        "source": source,
        "as_of": when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    CURRENT_WEEK_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def write_cbs_pull_meta(week: int, when: str | None = None) -> dict:
    payload = {
        "week": int(week),
        "as_of": when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    CBS_PULL_META.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def read_cbs_pull_meta() -> dict:
    if not CBS_PULL_META.exists():
        return {"week": None, "as_of": ""}
    try:
        return json.loads(CBS_PULL_META.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"week": None, "as_of": ""}


def write_standings(rows: list[dict], when: str | None = None) -> dict:
    payload = {
        "as_of": when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "teams": rows,
    }
    STANDINGS_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def read_standings() -> dict:
    if not STANDINGS_JSON.exists():
        return {"as_of": "", "teams": []}
    try:
        return json.loads(STANDINGS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"as_of": "", "teams": []}


def waiver_priority_map(standings: dict | None = None) -> dict[str, int]:
    """{owner: waiver priority}, 1 = claims first. This is a total-points
    league with no head-to-head, so "standings" is just each team's season
    GBFL total — Tuesday's waiver order is the reverse of it: the worst
    record claims first, the leader claims last.
    """
    standings = standings if standings is not None else read_standings()
    teams = standings.get("teams") or []
    n = len(teams)
    if not n:
        return {}
    by_rank = sorted(teams, key=lambda r: r.get("rank") or 0)
    return {r["team"]: n - i for i, r in enumerate(by_rank)}


def week_stats_csv(week: int) -> Path:
    return ROOT / f"cbs_stats_week{int(week)}.csv"


def format_cbs_opp(raw: str | None) -> str:
    s = (raw or "").strip()
    if not s or s in {"-", "N/R", "—"}:
        return ""
    if s.startswith("@"):
        return f"at {s[1:]}"
    return f"vs. {s}"


def load_cbs_opps(week: int) -> dict[str, str]:
    """Scheduled Opp for this NFL week from cbs_stats_weekN.csv (even if boxes are empty)."""
    path = week_stats_csv(week)
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for r in csv.DictReader(path.open(encoding="utf-8")):
        name = r.get("player") or ""
        label = format_cbs_opp(r.get("Opp"))
        if not name or not label:
            continue
        out[norm(name)] = label
        team = (r.get("team") or "").upper()
        if team:
            out.setdefault(f"team:{team}", label)
    return out


def log(msg: str) -> None:
    print(msg, flush=True)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def drafted_shape(rows: list[dict]) -> list[dict]:
    """drafted.csv schema: skill uses NFL team; K/DST put the position in team."""
    out = []
    for r in rows:
        pos = (r.get("pos") or "").upper()
        team = pos if pos in UNRANKED_POS else r.get("team") or ""
        out.append({"owner": r.get("owner") or "", "player": r["player"], "team": team})
    out.sort(key=lambda d: (d["owner"], d["player"]))
    return out


def load_old_drafted() -> list[dict]:
    if not DRAFTED_CSV.exists():
        return []
    return list(csv.DictReader(DRAFTED_CSV.open(encoding="utf-8")))


def print_roster_diff(old: list[dict], new_rows: list[dict]) -> None:
    def key(r):
        return (norm(r.get("player") or ""), (r.get("owner") or "").upper())

    old_by_name = {norm(r["player"]): r for r in old if r.get("player")}
    new_by_name = {norm(r["player"]): r for r in new_rows if r.get("player")}
    only_old = [old_by_name[k] for k in old_by_name if k not in new_by_name]
    only_new = [new_by_name[k] for k in new_by_name if k not in old_by_name]
    owner_mismatch = []
    for k, nr in new_by_name.items():
        o = old_by_name.get(k)
        if o and (o.get("owner") or "") != (nr.get("owner") or ""):
            owner_mismatch.append((o, nr))

    log("\n=== DIFF vs drafted.csv (CBS wins) ===")
    if not old:
        log("No prior drafted.csv.")
        return
    log(f"drafted.csv rows: {len(old)}  CBS roster rows: {len(new_rows)}")
    if only_old:
        log("In drafted.csv, not on any CBS roster (dropped / never actually rostered):")
        for r in only_old:
            log(f"  - {r.get('owner')} {r.get('player')} ({r.get('team')})")
    if only_new:
        log("On CBS roster, missing from drafted.csv (CBS is canonical):")
        # group by owner so the dump is readable
        by_o = defaultdict(list)
        for r in only_new:
            by_o[r.get("owner") or "?"].append(r)
        for owner in sorted(by_o):
            names = ", ".join(f"{x['player']} {x.get('pos') or x.get('team')}" for x in by_o[owner])
            log(f"  {owner}: {names}")
    if owner_mismatch:
        log("Owner mismatches (drafted.csv -> CBS):")
        for o, n in owner_mismatch:
            log(f"  {o['player']}: {o.get('owner')} -> {n.get('owner')}")
    if not only_old and not only_new and not owner_mismatch:
        log("No player/owner disagreements. drafted.csv was just a shorter snapshot.")


def pull_rosters(client: CBSClient) -> list[dict]:
    all_rows: list[dict] = []
    for tid, owner in TEAM_IDS.items():
        log(f"  roster {tid} {owner} ...")
        html = client.team_page(tid)
        rows = parse_team_roster(html, owner)
        if not rows:
            raise RuntimeError(f"parsed 0 players from /teams/{tid} ({owner})")
        all_rows.extend(rows)
        log(f"    {len(rows)} players")
    return all_rows


def pull_pool(client: CBSClient, pool: str, period: str) -> list[dict]:
    out: list[dict] = []
    for pos in POSITIONS:
        log(f"  {pool}:{pos}/{period} ...")
        html = client.stats_report(pool, pos, period=period, kind="stats")
        rows = parse_stats_players(html)
        log(f"    {len(rows)} rows")
        out.extend(rows)
    return out


def week_stat_periods(week: int) -> list[str]:
    """CBS week-N box scores and *this week's* Opp live at period=N (`2`).

    Do not fall through to `tp` / `ytd` — those stay on the last played week
    (`@MIN`, filled boxes) after kickoff, so week-2 actuals and opps would lie.
    `weekN` is names + scheduled Opp with empty stat columns.
    """
    n = int(week)
    return [str(n), f"week{n}"]


def pull_week_stats(client: CBSClient, week: int) -> list[dict]:
    from scoring.actuals import row_has_box_stats

    last: list[dict] = []
    for period in week_stat_periods(week):
        log(f"  week-{week} stats period={period} ...")
        rows = pull_pool(client, "all", period)
        last = rows
        nz = sum(1 for r in rows if row_has_box_stats(r))
        log(f"    {len(rows)} rows, {nz} with box-score stats")
        if nz >= 5:
            return rows
        log(f"    {period} looks empty; trying next period")
    return last


def write_pool_csv(path: Path, rows: list[dict]) -> None:
    fields = ["player", "team", "pos", "cbs_id"]
    extra: list[str] = []
    for r in rows:
        for k in r:
            if k not in fields and k not in extra and k not in {"owner", "slot", "key", "status"}:
                extra.append(k)
    write_csv(path, rows, fields + extra)


def load_history() -> dict:
    hist = {}
    for season in (2025, 2024, 2023):
        p = ROOT / f"history_{season}.csv"
        if not p.exists():
            continue
        for r in csv.DictReader(p.open(encoding="utf-8")):
            rec = dict(r)
            rec["season"] = season
            for k in ("pass_yds", "pass_td", "rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "total"):
                rec[k] = int(rec[k])
            rec["avg"] = float(rec["avg"])
            rec["scrim"] = rec["rush_yds"] + rec["rec_yds"]
            rec["ypc"] = rec["rec_yds"] / rec["rec"] if rec["rec"] else 0.0
            rec["rush_ypc"] = rec["rush_yds"] / max(1, rec.get("att", 0) or 1)
            hist.setdefault(norm(r["player"]), {})[season] = rec
    return hist


def load_kickers() -> dict:
    out = {}
    for season in (2025, 2024, 2023):
        for name in (f"kicker_{season}_fa.csv", f"kicker_{season}.csv"):
            p = ROOT / name
            if not p.exists():
                continue
            for r in csv.DictReader(p.open(encoding="utf-8")):
                rec = dict(r)
                rec["season"] = season
                rec["total"] = float(r["total"])
                rec["m_50"] = int(r.get("m_50") or 0)
                rec["a_50"] = int(r.get("a_50") or 0)
                rec["xp"] = int(r.get("xp") or 0)
                rec["fg"] = int(r.get("fg") or 0)
                out.setdefault(norm(r["player"]), {})[season] = rec
    return out


def load_dst() -> dict:
    out = defaultdict(dict)
    p = ROOT / "dst_history.csv"
    if not p.exists():
        return out
    for r in csv.DictReader(p.open(encoding="utf-8")):
        out[norm(r["team"])][int(r["season"])] = r
    return out


def load_board() -> dict:
    p = ROOT / "combined.csv"
    if not p.exists():
        return {}
    return {norm(r["player"]): r for r in csv.DictReader(p.open(encoding="utf-8"))}


def waiver_watchlist(fa: list[dict], roster: list[dict]) -> None:
    hist = load_history()
    kickers = load_kickers()
    dst = load_dst()
    board = load_board()
    mine = {norm(r["player"]) for r in roster if r.get("owner") == MY_TEAM}

    skill, ks, dsts, qbs = [], [], [], []
    for r in fa:
        k = r["key"]
        if k in mine:
            continue
        pos = (r.get("pos") or "").upper()
        if pos == "K":
            kk = kickers.get(k, {}).get(2025)
            if kk:
                ks.append((r, kk))
        elif pos == "DST":
            d = dst.get(k, {}).get(2025) or dst.get(norm(r.get("team") or ""), {}).get(2025)
            if d:
                dsts.append((r, d))
        elif pos == "QB":
            h = hist.get(k, {}).get(2025)
            if h:
                qbs.append((r, h))
        elif pos in {"RB", "WR", "TE"}:
            h = hist.get(k, {}).get(2025)
            b = board.get(k, {})
            skill.append((r, h, b))

    log("\n=== WAIVER WATCHLIST (CBS availability + 2025 league scoring, not CBS projections) ===")
    log("Profile: scrimmage yards / YPC / workhorse RB / 50+ FG volume / leftover high-scoring DST.")
    log("Receptions score 0 in this league. CBS rest-of-season projections were not used.\n")

    # Kickers first — McLaughlin was the known FA target
    ks.sort(key=lambda x: -x[1]["total"])
    log("Kickers still on waivers (2025 FA-file scoring):")
    if not ks:
        log("  (none of the scored kickers are on CBS waivers, or names did not join)")
    for r, kk in ks[:8]:
        flag = "  << top-10 kicker" if kk["total"] >= 70 or "mclaughlin" in r["key"] else ""
        log(
            f"  {r['player']:22} {r.get('team') or '':3}  {kk['total']:5.1f} pts  "
            f"{kk['m_50']}/{kk['a_50']} from 50+  {kk['fg']} FG{flag}"
        )
    mcl = next((r for r, _ in ks if "mclaughlin" in r["key"] and "jaleel" not in r["key"]), None)
    if mcl:
        log("  Reichard stays the start; McLaughlin is the only add if a K slot opens.")
    elif any("mclaughlin" in r["key"] and "jaleel" not in r["key"] for r in fa):
        log("  Chase McLaughlin is on CBS waivers but missing from kicker CSVs — treat as the FA K target.")
    else:
        log("  Chase McLaughlin is NOT on the CBS FA list (rostered or name mismatch).")

    # Skill: in our 2025 history dump AND currently FA
    hits = [(r, h, b) for r, h, b in skill if h]
    hits.sort(key=lambda x: (-x[1]["scrim"], -x[1]["total"]))
    log("\nSkill players on waivers who scored in this league in 2025 (by scrimmage yards):")
    if not hits:
        log("  No 2025 history names are on CBS waivers. Week-1 FA pool is mostly deep bench.")
    shown = 0
    for r, h, b in hits:
        if shown >= 12:
            break
        ypc = f"{h['ypc']:.1f} ypc" if h["rec"] >= 20 else ""
        rush = f"{h['rush_yds']} ru" if h["rush_yds"] >= 400 else ""
        bits = " ".join(x for x in (f"{h['scrim']} scrim", f"{h['total']} pts", rush, ypc) if x)
        br = b.get("rank") or "-"
        log(f"  {r['player']:22} {h['pos']:3}  {bits}  board {br}")
        shown += 1

    # Workhorse-ish RBs even if lower on the board: 2025 rush yards among FA
    rbs = [(r, h) for r, h, _ in hits if h["pos"] == "RB" and h["rush_yds"] >= 500]
    rbs.sort(key=lambda x: -x[1]["rush_yds"])
    if rbs:
        log("\nFA RBs with 500+ rush yards in 2025 (workhorse leftover):")
        for r, h in rbs[:6]:
            log(f"  {r['player']:22}  {h['rush_yds']} rush / {h['scrim']} scrim / {h['total']} pts")

    dsts.sort(key=lambda x: -float(x[1]["total"]))
    if dsts:
        log("\nFA DST with 2025 league points:")
        for r, d in dsts[:6]:
            log(f"  {r['player']:22}  {float(d['total']):5.1f} pts  {d.get('sack')} sack  {d.get('int')} INT")

    qbs.sort(key=lambda x: -x[1]["total"])
    if qbs:
        log("\nFA QBs who scored in 2025 (2QB roster — only streamers):")
        for r, h in qbs[:5]:
            log(f"  {r['player']:22}  {h['total']} pts  {h['pass_yds']} pass yds")

    # Sample of FA names (so the user sees the pull worked even if history is empty)
    sample = [r["player"] for r in fa if (r.get("pos") or "") in {"RB", "WR", "TE", "K"}][:15]
    log("\nFA name sample: " + ", ".join(sample))


def print_bussone(roster: list[dict]) -> None:
    mine = [r for r in roster if r.get("owner") == MY_TEAM]
    order = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "K": 4, "DST": 5}
    mine.sort(key=lambda r: (order.get(r.get("pos") or "", 9), r["player"]))
    log("\n=== OFFICIAL BUSSONE ROSTER (CBS) ===")
    log(f"{len(mine)} players")
    for r in mine:
        slot = r.get("slot") or r.get("pos") or ""
        log(f"  {slot:8} {r['player']:22} {r.get('pos') or '':3} {r.get('team') or ''}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Pull CBS GBFL roster and free agents")
    ap.add_argument("--har", help="Firefox/Chrome HAR export (contains session cookies)")
    ap.add_argument("--cookies", help="gitignored cookie file (Cookie header or name=value lines)")
    ap.add_argument("--period", default="2025", help="stats period (default 2025; ytd is empty in week 1)")
    ap.add_argument(
        "--week",
        type=int,
        default=None,
        help="NFL week for box-score stats (cbs_stats_weekN.csv); omit to auto-detect from CBS",
    )
    args = ap.parse_args(argv)

    log("WARNING: HAR files and cookie files are login credentials. Do not commit them.")
    try:
        cookie = load_cookie_header(cookies_path=args.cookies, har_path=args.har)
    except FileNotFoundError as e:
        log(str(e))
        return 2

    cookie_file = ROOT / "cbs_cookies.txt"
    if args.har and not cookie_file.exists():
        cookie_file.write_text(cookie, encoding="utf-8")
        log("Wrote gitignored cbs_cookies.txt for later --cookies reuse. Do not commit it.")

    client = CBSClient(cookie)
    log(f"Host {HOST}")

    # CBS's own idea of "this week" (from its live injury-report copy), not
    # an NFL-calendar guess. Detected independently of --week so a manual
    # backfill pull (an old or future week) never clobbers the app's sense
    # of what week is actually current.
    detected = detect_current_week(client)
    if detected:
        write_current_week(detected, source="cbs-tp")
        log(f"CBS current week: {detected}")
    else:
        log("Could not read CBS's current week (no injury tooltips, or a network hiccup) — keeping the last known value.")
    week = args.week if args.week is not None else (detected or read_current_week().get("week") or 1)
    log(f"Box-score target: week {week}" + ("" if args.week is not None else " (auto-detected)"))

    log("Pulling 10 team pages (canonical rosters)...")
    try:
        roster = pull_rosters(client)
    except AuthError as e:
        log(f"AUTH FAILED: {e}")
        log("Export a fresh HAR from a logged-in CBS session, or paste cookies into cbs_cookies.txt.")
        return 2

    log("Pulling current free agents (2025 stats attached; CBS projections skipped)...")
    fa_rows = pull_pool(client, "fa", args.period)
    log("Pulling all-player pool (ownership + stats)...")
    all_rows = pull_pool(client, "all", args.period)

    # Canonical roster = team pages. Attach cbs_id from stats if missing.
    id_by_key = {r["key"]: r.get("cbs_id") for r in all_rows if r.get("cbs_id")}
    for r in roster:
        r["cbs_id"] = r.get("cbs_id") or id_by_key.get(r["key"], "")

    fa_keys = {r["key"] for r in fa_rows}
    roster_keys = {r["key"] for r in roster}
    # FA list is CBS availability. Drop anyone who is actually on a roster page.
    fa_clean = [r for r in fa_rows if r["key"] not in roster_keys]

    roster_fields = ["owner", "player", "team", "pos", "slot", "cbs_id"]
    fa_fields = ["player", "team", "pos", "cbs_id", "status"]
    extra_stat_keys = []
    for r in fa_rows:
        for k in r:
            if k not in fa_fields and k not in {"owner", "slot", "key"} and k not in extra_stat_keys:
                extra_stat_keys.append(k)
    fa_fields = fa_fields + extra_stat_keys

    player_fields = ["owner", "player", "team", "pos", "status", "cbs_id"]
    write_csv(ROSTER_CSV, sorted(roster, key=lambda r: (r.get("owner") or "", r["player"])), roster_fields)
    write_csv(FA_CSV, sorted(fa_clean, key=lambda r: (r.get("pos") or "", r["player"])), fa_fields)
    write_csv(
        PLAYERS_CSV,
        sorted(all_rows, key=lambda r: (r.get("owner") or "zzz", r["player"])),
        player_fields,
    )

    payload = {
        "league": "castrati",
        "host": HOST,
        "my_team": MY_TEAM,
        "my_team_id": "12",
        "teams": TEAM_IDS,
        "rosters": {
            owner: [
                {k: r.get(k, "") for k in roster_fields}
                for r in roster
                if r.get("owner") == owner
            ]
            for owner in TEAM_IDS.values()
        },
    }
    ROSTER_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    old = load_old_drafted()
    print_roster_diff(old, roster)
    write_csv(DRAFTED_CSV, drafted_shape(roster), ["owner", "player", "team"])

    log("Pulling last-3-games stats (usage prior)...")
    try:
        g3 = pull_pool(client, "all", "3g")
        g3_fields = ["player", "team", "pos", "cbs_id"]
        extra = []
        for r in g3:
            for k in r:
                if k not in g3_fields and k not in extra and k not in {"owner", "slot", "key", "status"}:
                    extra.append(k)
        write_csv(STATS_3G, g3, g3_fields + extra)
        log(f"  wrote {STATS_3G.name} ({len(g3)} rows)")
    except Exception as e:
        log(f"  3g stats skipped: {e}")

    log(f"Pulling week-{week} NFL stats (box scores)...")
    try:
        week_rows = pull_week_stats(client, week)
        dest = week_stats_csv(week)
        write_pool_csv(dest, week_rows)
        log(f"  wrote {dest.name} ({len(week_rows)} rows)")
        write_cbs_pull_meta(week)
    except Exception as e:
        log(f"  week stats skipped: {e}")

    # Re-pull the previous week too: CBS's "current week" (tp) flips to the
    # new week Tue/Wed morning, and the background auto-refresh loop only
    # ever asks for that current week — without this, a Monday-night final
    # that lands after the last pre-flip pull is never captured, and the
    # Report tab grades that game as pending forever.
    if week > 1:
        prev = week - 1
        log(f"Re-pulling week-{prev} NFL stats too (in case Monday night finished after the last pull)...")
        try:
            prev_rows = pull_week_stats(client, prev)
            write_pool_csv(week_stats_csv(prev), prev_rows)
            log(f"  wrote {week_stats_csv(prev).name} ({len(prev_rows)} rows)")
        except Exception as e:
            log(f"  week-{prev} re-pull skipped: {e}")

    log("Pulling standings (this league's total-points ranking = waiver order)...")
    try:
        standings = parse_standings(client.standings_page())
        write_standings(standings)
        log(f"  wrote {STANDINGS_JSON.name} ({len(standings)} teams)")
    except Exception as e:
        log(f"  standings skipped: {e}")

    log("Pulling CBS team depth charts (RB1 / WR2, not league-wide)...")
    depth = []
    try:
        from cbs_client import pull_public_depth_charts

        depth = pull_public_depth_charts()
        log(f"  public charts: {len(depth)} rows")
    except Exception as e:
        log(f"  public depth skipped: {e}")
    if not depth:
        try:
            dhtml = client.depth_chart()
            depth = parse_depth_chart(dhtml)
        except Exception as e:
            log(f"  league depth skipped: {e}")
    if depth:
        write_csv(
            DEPTH_CSV,
            depth,
            ["player", "team", "pos", "cbs_id", "depth_rank", "role_note"],
        )
        log(f"  wrote {DEPTH_CSV.name} ({len(depth)} rows)")

    try:
        from news.injuries import refresh as injury_refresh

        log("Refreshing injury notes (CBS slots + ESPN news)...")
        extra = [r["player"] for r in fa_clean[:80]]
        injury_refresh(roster, extra)
        log("  wrote injury_notes.json")
    except Exception as e:
        log(f"  injury news skipped: {e}")

    log("\n=== PULL COUNTS ===")
    log(f"CBS roster players (all teams): {len(roster)}")
    log(f"BUSSONE: {sum(1 for r in roster if r.get('owner') == MY_TEAM)}")
    log(f"Free agents (CBS waivers, not on a roster page): {len(fa_clean)}")
    log(f"All-player stats rows: {len(all_rows)}")
    log(f"Wrote {ROSTER_CSV.name}, {FA_CSV.name}, {PLAYERS_CSV.name}, {ROSTER_JSON.name}, {DRAFTED_CSV.name}")
    by_pos = defaultdict(int)
    for r in fa_clean:
        by_pos[r.get("pos") or "?"] += 1
    log("FA by pos: " + ", ".join(f"{p} {by_pos[p]}" for p in POSITIONS if by_pos[p]))
    sample = [r["player"] for r in fa_clean[:12]]
    log("FA sample: " + ", ".join(sample))

    print_bussone(roster)
    waiver_watchlist(fa_clean, roster)
    log("\nRefresh later: export a new HAR (or reuse cbs_cookies.txt) and re-run this script.")
    log("Then python merge.py to copy CBS owners onto combined.csv (ranks/scores unchanged).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
