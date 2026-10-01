from metrics.grades import Model, fit, load_weights, par, percentile_grade, r2, replacement_rank, save_weights, spearman


def test_fit_recovers_a_linear_relation():
    rows = [{"x": float(x), "y": 2.0 + 3.0 * x} for x in range(10)]
    m = fit(rows, ["x"], "y", lam=0.0)
    assert abs(m.predict({"x": 4.0}) - 14.0) < 1e-9
    assert abs(r2([r["y"] for r in rows], [m.predict(r) for r in rows]) - 1.0) < 1e-12


def test_fit_blend_keeps_the_fixed_weight_ratio_and_predicts_target_units():
    from metrics.grades import fit_blend

    rows = [{"a": float(i), "b": float(i % 3), "y": 1.0 + 0.5 * i} for i in range(12)]
    m = fit_blend(rows, ["a", "b"], [0.4, 0.6], "y")
    assert abs(m.coefs[1] / m.coefs[2] - 0.4 / 0.6) < 1e-9
    preds = [m.predict(r) for r in rows]
    assert abs(sum(preds) / len(preds) - sum(r["y"] for r in rows) / len(rows)) < 1e-9


def test_missing_feature_imputes_the_training_mean():
    rows = [{"x": float(x), "y": float(x)} for x in range(5)]
    m = fit(rows, ["x"], "y", lam=0.0)
    assert abs(m.predict({"x": None}) - m.predict({"x": 2.0})) < 1e-9


def test_model_round_trips_through_dict():
    m = Model(["a"], [1.0], [2.0], [0.5, 1.5])
    assert Model.from_dict(m.to_dict()).predict({"a": 3.0}) == m.predict({"a": 3.0}) == 2.0


def test_par_is_points_above_the_first_player_past_the_rostered_count():
    assert replacement_rank("WR") == 60 and replacement_rank("TE") == 20
    preds = {f"p{i}": float(100 - i) for i in range(70)}  # p60 is the 61st best: 40.0
    out = par(preds, "WR", week=8)  # 10 weeks left
    assert out["p60"] == 0.0
    assert out["p0"] == (100.0 - 40.0) * 10
    assert out["p69"] < 0


def test_par_scales_by_expected_games_when_given():
    preds = {"hurt": 3.0, "healthy": 3.0, "repl": 1.0}
    out = par(preds, "TE", week=8, games={"hurt": 4.5})
    assert out["hurt"] == 2.0 * 4.5 and out["healthy"] == 2.0 * 10


def test_par_with_a_short_pool_uses_the_worst_player():
    assert par({"a": 3.0, "b": 1.0}, "TE", week=17)["a"] == 2.0


def test_percentile_grade():
    assert percentile_grade({"a": 1.0, "b": 2.0, "c": 3.0}) == {"a": 0, "b": 50, "c": 100}


def test_spearman_degenerate_inputs():
    assert spearman([1, 1, 1], [1, 2, 3]) == 0.0
    assert abs(spearman([1, 2, 3], [10, 20, 30]) - 1.0) < 1e-12


def test_weights_round_trip(tmp_path):
    p = save_weights({"positions": {"WR": {"x": 1}}}, tmp_path / "w.json")
    assert load_weights(p) == {"positions": {"WR": {"x": 1}}}
    assert load_weights(tmp_path / "missing.json") == {}
