# CBS Sports fantasy API map (GBFL / castrati)

League host: `https://castrati.football.cbssports.com`  
League id: `castrati`. Sport: football. Site UI is jQuery; stats “APIs” return **HTML tables**, not JSON.

**HAR files are credentials.** They contain session cookies. Do not commit a HAR, `cbs_cookies.txt`, or paste cookies into git. Refresh = export a new HAR (or reuse a still-valid cookie file) and re-run `python cbs_pull.py`.

## Auth

Send the browser `Cookie` header from a logged-in session.

Useful cookie names (values are secrets): `pid`, `cbsiaa`, `last_access`, plus consent/analytics cookies the browser also sends.

Required headers on XHR:

- `X-Requested-With: XMLHttpRequest`
- `Referer: https://castrati.football.cbssports.com/stats/stats-main`
- a normal browser `User-Agent`

No separate bearer token is required for the stats/roster pages. Page JS also embeds an `access_token` — ignore it; cookies are enough.

## Team ids (10-team GBFL)

| id | owner     |
|----|-----------|
| 1  | BOLDING   |
| 2  | MUCK/UZES |
| 5  | CHEN      |
| 6  | FORBES    |
| 8  | FREEMANS  |
| 9  | PRESTON   |
| 10 | THROBBER  |
| 11 | BAUKOL    |
| 12 | BUSSONE   |
| 13 | ANN       |

BUSSONE (the user’s team) is **12**. `/teams/13` in the HAR referer was a different owner.

## Endpoints

### Roster (canonical)

`GET /teams/{id}` — full HTML team page. Full player names, NFL team, position, lineup slot (starter / Bench / Injured). This is the roster source of truth.

`GET /teams/roster-grid` — all 10 rosters in one table, but names are abbreviated (`C Williams`). Do not use for joins.

`GET /teams`, `/teams/service`, `/teams/scout-team` — nav only / scout list.

### Stats / free agents / all players (jQuery XHR)

`GET /stats/data-stats-report/{pool}:{positions}/{period}:p/{cats}/{kind}`

Returns an HTML `<table class="data">`.

- **pool:** `all` (every player, Avail = owner or waivers), `fa` (current free agents / waivers), `team` (your team), `team:{id}` (one roster), `team:all`
- **positions:** `QB`, `RB`, `WR`, `TE`, `K`, `DST`, or combinations `QB:RB:WR:TE`
- **period:** `ytd`, `week1` (or `1`), `restofseason`, `season` (preseason proj), `2025`, `2024`, `3yr`, `3g`, `tp`, `ws`. **Week box scores:** use `1`, `2`, … (`tp` = this week). `week1` returns the player list with **empty** stat columns — do not use it for actuals.
- **cats:** `standard` (NFL stat categories — use this), `scoring` (site fantasy points; **not** this league’s engine)
- **kind:** `stats` or `projections` (CBS projections are a last-resort weak signal only)

Query:

- `print_rows=9999` — dump the full table (preferred)
- `start_row=101` — pagination, 100 rows/page
- `:sort_col=N` / `:sort_dir=1`

Row shape:

- Avail cell: `<span title="Rostered By BUSSONE">` or `<span title="On Waivers">W (9/16)</span>`
- Player: `<a class='playerLink' href='/players/playerpage/{id}'>Name</a> <span class='playerPositionAndTeam'>QB • JAC</span>`

### HTML shells (not the table payload)

`GET /stats/stats-main`  
`GET /stats/stats-main/{pool}:{positions}/{period}:p/{cats}/{kind}`

Same path language as `data-stats-report`, but a full page. The table is loaded by XHR.

`GET /print/csv/stats/stats-main` — site CSV export of the current stats view (same filters). HTML parse of `data-stats-report` is more reliable for automation.

### Other (seen in page JS / HAR; not needed for roster/FA)

| method | path | notes |
|--------|------|--------|
| PUT | `/api/league/chat/status` | form body, `league_id=castrati`, XML/JSON chat heartbeat |
| GET | `/api/league/owner-details` | owner blurb |
| POST | `/api/league/transactions/add-drop` | waiver/add-drop (do not call) |
| GET | `/standings/overall` | standings HTML |
| GET | `/players/playerpage/{id}` | player card |
| GET | `/players/rankings`, `/players/roster-trends`, `/players/depth-chart` | extras |

## Refresh (in-season)

1. Log into CBS in the browser.
2. Export a fresh HAR from the stats or team page, **or** save the `Cookie` header into gitignored `cbs_cookies.txt`.
3. `python cbs_pull.py --har "path\to\file.har"` (or `--cookies cbs_cookies.txt`).
4. That rewrites `cbs_roster.csv` (canonical), `cbs_fa.csv`, `cbs_players.csv`, and a CBS-derived `drafted.csv` so `merge.py` / the draft canvas keep working. Ownership on the board comes from CBS, not the old pick log.
5. Then `python merge.py` if you want `combined.csv` owner column refreshed (ranks/scores are unchanged).
