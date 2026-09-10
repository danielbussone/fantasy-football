from scoring.rules import (
    Game,
    fg_points,
    passing_td_points,
    rb_wr_yard_points,
    receiving_td_points,
    return_td_points,
    score_game,
    te_yard_points,
)


def test_46_yard_rec_td_is_four():
    assert passing_td_points(46) == 4
    assert receiving_td_points(46, "WR") == 4
    g = Game(pos="WR", rec_td_yards=[46])
    assert score_game(g) == 4


def test_109_yards_plus_10_yard_rec_td_is_three():
    assert rb_wr_yard_points(109) == 2
    assert receiving_td_points(10, "WR") == 1
    g = Game(pos="WR", rec_yds=109, rec_td_yards=[10])
    assert score_game(g) == 3
    assert score_game(Game(pos="WR", rec_td_yards=[46])) > score_game(g)


def test_te_yard_entry_and_td_bands():
    assert te_yard_points(39) == 0
    assert te_yard_points(40) == 1
    assert te_yard_points(48) == 1
    # TE rec TD uses rush bands: 10 yards = 1 + 1 (6-15)
    assert receiving_td_points(10, "TE") == 2


def test_qb_buckets():
    g = Game(pos="QB", pass_yds=249)
    assert score_game(g) == 1
    g2 = Game(pos="QB", pass_yds=250)
    assert score_game(g2) == 2


def test_kicker_and_xp():
    assert fg_points(39) == 1
    assert fg_points(41) == 2
    assert fg_points(51) == 3
    assert fg_points(60) == 3.5
    g = Game(pos="K", fg_yards=[39, 51], xp=2)
    assert score_game(g) == 1 + 3 + 1.0


def test_return_td_51_is_five():
    assert return_td_points(51) == 5
    assert return_td_points(30) == 3


def test_receptions_do_not_score():
    g = Game(pos="WR", rec_yds=69)
    assert score_game(g) == 0


def test_dst_pa_and_turnovers():
    from scoring.rules import dst_points

    assert dst_points(sacks=2, ints=1, fumbles_recovered=1, points_against=10) == 0.5 * 4 + 3
    assert dst_points(points_against=0) == 5
