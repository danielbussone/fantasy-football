from cbs_client import (
    current_week_from_stats_html,
    parse_depth_chart,
    parse_public_depth_chart,
    parse_standings,
    parse_stats_players,
    parse_team_roster,
)


ROSTER_HTML = """
<table>
<tr>
  <td class="playerPosition">Injured</td>
  <td>
    <a href="/players/playerpage/26697761">Malik Nabers</a>
    <span class="playerPositionAndTeam">WR • NYG</span>
  </td>
</tr>
<tr>
  <td class="playerPosition">WR</td>
  <td>
    <a href="/players/playerpage/2966320">Ja'Marr Chase</a>
    <span class="playerPositionAndTeam">WR • CIN</span>
  </td>
</tr>
</table>
"""

STATS_HTML = """
<table>
<tr>
  <th class="sortableColumn">Action</th>
  <th class="sortableColumn">Avail</th>
  <th class="sortableColumn">Player</th>
  <th class="sortableColumn">ATT</th>
  <th class="sortableColumn">Yds</th>
  <th class="sortableColumn">TD</th>
  <th class="sortableColumn">Att</th>
  <th class="sortableColumn">Yds</th>
  <th class="sortableColumn">TD</th>
</tr>
<tr>
  <td></td>
  <td></td>
  <td>
    <a href="/players/playerpage/1">Trevor Lawrence</a>
    <span class="playerPositionAndTeam">QB • JAC</span>
  </td>
  <td>30</td><td>250</td><td>2</td><td>5</td><td>20</td><td>1</td>
</tr>
</table>
"""

DEPTH_HTML = """
<table>
<tr><td>WR</td></tr>
<tr>
  <td><a href="/players/playerpage/2">Ja'Marr Chase</a></td>
  <td><a href="/players/playerpage/3">Ladd McConkey</a></td>
</tr>
</table>
"""


def test_injured_slot_parsed():
    rows = parse_team_roster(ROSTER_HTML, "BUSSONE")
    by = {r["player"]: r for r in rows}
    assert by["Malik Nabers"]["slot"] == "Injured"
    assert by["Ja'Marr Chase"]["slot"] == "WR"
    assert by["Malik Nabers"]["owner"] == "BUSSONE"


def test_duplicate_stat_headers_kept():
    rows = parse_stats_players(STATS_HTML)
    assert rows
    r = rows[0]
    assert r["Yds"] == "250"
    assert r["Yds_2"] == "20"
    assert r["TD"] == "2"
    assert r["TD_2"] == "1"


def test_depth_chart_ranks():
    rows = parse_depth_chart(DEPTH_HTML)
    assert rows[0]["player"] == "Ja'Marr Chase"
    assert rows[0]["depth_rank"] == 1
    assert rows[1]["player"] == "Ladd McConkey"
    assert rows[1]["depth_rank"] == 2


PUBLIC_RB_HTML = """
<tr class="TableBase-bodyTr">
  <td><a href="/nfl/teams/LAR/los-angeles-rams/">LAR</a></td>
  <td>
    <span class="CellPlayerName--long">
      <a href="/nfl/players/1/kyren-williams/fantasy/">Kyren Williams</a>
    </span>
  </td>
  <td>
    <span class="CellPlayerName--long">
      <a href="/nfl/players/3169252/blake-corum/fantasy/">Blake Corum</a>
      <span class="CellPlayerName-icon icon-moon-injury">
        <div class="Tablebase-tooltipInner">Knee: Out for Week 1</div>
      </span>
    </span>
  </td>
  <td>
    <span class="CellPlayerName--long">
      <a href="/nfl/players/9/ronnie-rivers/fantasy/">Ronnie Rivers</a>
    </span>
  </td>
</tr>
"""


def test_current_week_from_stats_html_takes_the_mode():
    """"... for Week N" (the designation's own week) wins over an "Expected
    Return - Week N" mention (a different, future week) and over a lone
    outlier — matches a real `period=tp` pull: 112 "for Week 3" vs 2
    "for Week 6" on a real WR pool.
    """
    html = (
        '<span title="Elbow: Out for Week 3 vs. Seattle. Expected Return - Week 4">'
        '<span title="Lower Body: Questionable for Week 3 at Washington">'
        '<span title="Back: Injured Reserve. Expected Return - Week 5">'
        '<span title="Knee: Out for Week 6, long-term IR">'
    )
    assert current_week_from_stats_html(html) == 3


def test_current_week_from_stats_html_missing_is_none():
    assert current_week_from_stats_html("<table></table>") is None


# Real text from a live /standings/overall pull (plain()-ed HTML).
STANDINGS_TEXT = (
    "Rank Team Offensive Defensive Total Dif Behind "
    "1 BUSSONE 67.5 11.5 79.0 39.0 0.0 "
    "2 THROBBER 52.0 7.0 59.0 25.5 20.0 "
    "3 FORBES 53.0 5.5 58.5 38.5 20.5 "
    "4 BOLDING 43.5 14.0 57.5 22.0 21.5 "
    "5 FREEMANS 50.0 6.0 56.0 23.0 23.0 "
    "6 BAUKOL 49.0 6.0 55.0 23.5 24.0 "
    "7 MUCK/UZES 49.0 2.0 51.0 22.0 28.0 "
    "8 CHEN 42.5 7.5 50.0 22.5 29.0 "
    "9 PRESTON 46.5 2.5 49.0 30.5 30.0 "
    "10 ANN 42.5 4.0 46.5 11.0 32.5"
)


def test_parse_standings_orders_by_rank_and_ignores_unknown_teams():
    rows = parse_standings(STANDINGS_TEXT)
    assert [r["team"] for r in rows] == [
        "BUSSONE",
        "THROBBER",
        "FORBES",
        "BOLDING",
        "FREEMANS",
        "BAUKOL",
        "MUCK/UZES",
        "CHEN",
        "PRESTON",
        "ANN",
    ]
    assert rows[0]["total"] == 79.0
    assert rows[-1]["total"] == 46.5


def test_public_depth_is_team_relative():
    rows = parse_public_depth_chart(PUBLIC_RB_HTML, "RB")
    by = {r["player"]: r for r in rows}
    assert by["Kyren Williams"]["depth_rank"] == 1
    assert by["Blake Corum"]["depth_rank"] == 2
    assert by["Blake Corum"]["role_note"] == "LAR RB2"
    assert by["Blake Corum"]["injury_note"] == "Knee: Out for Week 1"
    assert by["Ronnie Rivers"]["role_note"] == "LAR RB3"
