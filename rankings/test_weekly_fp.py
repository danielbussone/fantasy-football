from pathlib import Path

from lineup.start_sit import apply_injury_proj, optimize
from rankings.weekly_fp import (
    apply_weekly_shift,
    attach_weekly,
    index_weekly,
    infer_meta,
    lookup_weekly,
    merge_weekly,
    parse_fp_csv,
    weekly_usage_scale,
    weekly_value,
    write_weekly,
)


def _csv(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.write_text(text, encoding="utf-8")
    return p


def test_infer_meta_and_value():
    assert infer_meta("FantasyPros_2026_Week_1_FLX_Rankings.csv") == (1, "FLX")
    assert infer_meta("FantasyPros_2026_Week_1_QB_Rankings.csv") == (1, "QB")
    assert weekly_value(1, 80) == 8
    assert weekly_value(80, 80) == 0.1  # (1 - 79/80)*8


def test_parse_flx_strips_pos_and_walker_rank(tmp_path):
    p = _csv(
        tmp_path,
        "FantasyPros_2026_Week_1_FLX_Rankings.csv",
        """RK,PLAYER NAME,TEAM,POS,OPP,MATCHUP
1,Jahmyr Gibbs,DET,RB1,vs. NO,2 out of 5 stars
17,Kenneth Walker III,KC,RB13,vs. DEN,2 out of 5 stars
""",
    )
    rows = parse_fp_csv(p)
    assert len(rows) == 2
    g = rows[0]
    assert g["player"] == "Jahmyr Gibbs" and g["rk"] == 1 and g["pos"] == "RB"
    assert g["list"] == "FLX" and g["weekly_value"] == weekly_value(1, 2)
    w = rows[1]
    assert w["rk"] == 17 and w["pos"] == "RB"
    assert w["weekly_value"] == weekly_value(17, 2)


def test_parse_qb_k_dst(tmp_path):
    qb = _csv(
        tmp_path,
        "FantasyPros_2026_Week_1_QB_Rankings.csv",
        """RK,PLAYER NAME,TEAM,OPP,MATCHUP,START/SIT,PROJ. FPTS
8,Trevor Lawrence,JAC,vs. CLE,1 out of 5 stars,B,18.1
""",
    )
    k = _csv(
        tmp_path,
        "FantasyPros_2026_Week_1_K_Rankings.csv",
        """RK,PLAYER NAME,TEAM,OPP,MATCHUP,START/SIT,PROJ. FPTS
4,Cairo Santos,CHI,at CAR,3 out of 5 stars,B,8.2
""",
    )
    dst = _csv(
        tmp_path,
        "FantasyPros_2026_Week_1_DST_Rankings.csv",
        """RK,PLAYER NAME,TEAM,OPP,MATCHUP,START/SIT,PROJ. FPTS
6,Seattle Seahawks,SEA,vs. NE,2 out of 5 stars,B,7.4
9,Baltimore Ravens,BAL,at IND,1 out of 5 stars,B,7.0
""",
    )
    lawrence = parse_fp_csv(qb)[0]
    assert lawrence["rk"] == 8 and lawrence["pos"] == "QB" and lawrence["list"] == "QB"
    idx = index_weekly(parse_fp_csv(k) + parse_fp_csv(dst))
    assert lookup_weekly("Cairo Santos", "CHI", "K", idx)["rk"] == 4
    sea = lookup_weekly("Seahawks", "SEA", "DST", idx)
    assert sea and sea["rk"] == 6
    bal = lookup_weekly("Ravens", "BAL", "DST", idx)
    assert bal and bal["rk"] == 9


def test_partial_reimport_keeps_other_lists(tmp_path):
    a = [{"player": "A", "list": "FLX", "rk": 1, "n": 1, "weekly_value": 8, "week": 1, "team": "DET", "pos": "RB"}]
    b = [{"player": "B", "list": "QB", "rk": 1, "n": 1, "weekly_value": 8, "week": 1, "team": "BAL", "pos": "QB"}]
    merged = merge_weekly(a + b, [{"player": "C", "list": "FLX", "rk": 2, "n": 1, "weekly_value": 0, "week": 1, "team": "KC", "pos": "RB"}])
    lists = {r["list"] for r in merged}
    assert lists == {"FLX", "QB"}
    assert any(r["player"] == "C" for r in merged)
    assert not any(r["player"] == "A" for r in merged)


def test_weekly_usage_scale_from_rank():
    assert weekly_usage_scale(None, 0.2) == 1.0
    assert weekly_usage_scale(8, 0) == 1.0
    assert weekly_usage_scale(8, 0.2) == 1.2
    assert weekly_usage_scale(0, 0.2) == 0.8
    assert weekly_usage_scale(4, 0.2) == 1.0


def test_weekly_shift_does_not_fractionalize_points():
    rec = {
        "player": "X",
        "pos": "RB",
        "weekly_value": 8,
        "proj": {"p10": 1, "p25": 2, "p50": 3, "p75": 4, "p90": 5, "mean": 3},
    }
    z = apply_weekly_shift(dict(rec), 0)["proj"]
    assert (z["p10"], z["p50"], z["p90"]) == (1, 3, 5)
    s = apply_weekly_shift(dict(rec), 0.2)["proj"]
    assert (s["p10"], s["p50"], s["p90"]) == (1, 3, 5)


def test_fp_volume_moves_sim():
    from projections.weekly import blend_weekly_volume, project_player

    prior = {
        "player": "X",
        "pos": "WR",
        "scrim_ypg": 80,
        "rec_share": 0.95,
        "rec_td_rate": 0.4,
        "cv": 0.3,
        "ypc": 12,
    }
    hi = project_player(blend_weekly_volume(prior, 8, 0.5), n=500, seed=2)
    lo = project_player(blend_weekly_volume(prior, 0, 0.5), n=500, seed=2)
    h_yds = (hi["sim"].get("rec_yds") or 0) + (hi["sim"].get("rush_yds") or 0)
    l_yds = (lo["sim"].get("rec_yds") or 0) + (lo["sim"].get("rush_yds") or 0)
    assert h_yds > l_yds


def test_out_stays_zero_after_shift():
    rec = apply_injury_proj(
        {
            "player": "Hurt",
            "pos": "RB",
            "weekly_value": 8,
            "injury": {"designation": "Out", "out": True},
            "proj": {"p10": 4, "p25": 5, "p50": 6, "p75": 7, "p90": 8, "mean": 6},
        }
    )
    out = apply_weekly_shift(rec, 1.0)["proj"]
    assert out["p10"] == out["p50"] == out["p90"] == 0


def test_start_sit_can_flip_when_fp_disagrees():
    def wr(name, p50):
        return {
            "player": name,
            "pos": "WR",
            "proj": {"p10": p50 - 1, "p25": p50 - 0.5, "p50": p50, "p75": p50 + 1, "p90": p50 + 2, "mean": p50},
        }

    def filler(name, pos, p50):
        return {
            "player": name,
            "pos": pos,
            "proj": {"p10": p50 - 1, "p25": p50 - 0.5, "p50": p50, "p75": p50 + 1, "p90": p50 + 2, "mean": p50},
        }

    boom = wr("Low-FP", 4)
    quiet = wr("High-FP", 6)
    roster = [
        filler("QB-A", "QB", 5),
        filler("RB-A", "RB", 6),
        filler("RB-B", "RB", 5),
        filler("RB-C", "RB", 4),
        boom,
        quiet,
        filler("WR-C", "WR", 3),
        filler("WR-D", "WR", 2.5),
        filler("TE-A", "TE", 4),
        filler("K-A", "K", 3),
        filler("DST-A", "DST", 2),
    ]
    names = {p["player"] for p in optimize(roster, "p50")["starters"]}
    assert "High-FP" in names


def test_write_weekly_does_not_need_combined(tmp_path, monkeypatch):
    import rankings.weekly_fp as wf

    monkeypatch.setattr(wf, "WEEK_FP", tmp_path / "week_fp.csv")
    write_weekly(
        [
            {
                "player": "Jahmyr Gibbs",
                "team": "DET",
                "pos": "RB",
                "list": "FLX",
                "rk": 1,
                "n": 1,
                "weekly_value": 8,
                "week": 1,
                "opp": "",
                "matchup": "",
                "start_sit": "",
                "proj_fpts": "",
            }
        ]
    )
    idx = index_weekly()
    rec = attach_weekly({"player": "Jahmyr Gibbs", "pos": "RB", "team": "DET"}, idx)
    assert rec["weekly_rank"] == 1
