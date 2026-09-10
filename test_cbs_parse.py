from cbs_client import parse_depth_chart, parse_public_depth_chart, parse_stats_players, parse_team_roster


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


def test_public_depth_is_team_relative():
    rows = parse_public_depth_chart(PUBLIC_RB_HTML, "RB")
    by = {r["player"]: r for r in rows}
    assert by["Kyren Williams"]["depth_rank"] == 1
    assert by["Blake Corum"]["depth_rank"] == 2
    assert by["Blake Corum"]["role_note"] == "LAR RB2"
    assert by["Blake Corum"]["injury_note"] == "Knee: Out for Week 1"
    assert by["Ronnie Rivers"]["role_note"] == "LAR RB3"
