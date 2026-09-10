from pathlib import Path

from rankings.import_rankings import read_stamp, write_stamp


def test_stamp_roundtrip(tmp_path, monkeypatch):
    import rankings.import_rankings as ir

    monkeypatch.setattr(ir, "STAMP", tmp_path / "rankings_as_of.txt")
    monkeypatch.setattr(ir, "ROOT", tmp_path)
    s = ir.write_stamp("2026-09-09T12:00:00Z")
    assert s == "2026-09-09T12:00:00Z"
    assert ir.read_stamp() == s


def test_import_runs_merge_not_scoring(tmp_path, monkeypatch):
    import rankings.import_rankings as ir

    calls = []
    monkeypatch.setattr(ir, "ROOT", tmp_path)
    monkeypatch.setattr(ir, "STAMP", tmp_path / "rankings_as_of.txt")
    monkeypatch.setattr(ir.subprocess, "check_call", lambda cmd, cwd=None: calls.append((cmd, cwd)))
    src = tmp_path / "in_dyn.csv"
    src.write_text("player,team,pos,rank\nA,CIN,WR,1\n", encoding="utf-8")
    ir.import_files(src, None)
    assert (tmp_path / "dynasty.csv").exists()
    assert calls
    assert str(calls[0][0][-1]).endswith("merge.py")


def test_import_weekly_skips_merge(tmp_path, monkeypatch):
    import rankings.import_rankings as ir
    import rankings.weekly_fp as wf

    calls = []
    monkeypatch.setattr(ir, "ROOT", tmp_path)
    monkeypatch.setattr(ir, "STAMP", tmp_path / "rankings_as_of.txt")
    monkeypatch.setattr(ir.subprocess, "check_call", lambda cmd, cwd=None: calls.append(cmd))
    monkeypatch.setattr(wf, "WEEK_FP", tmp_path / "week_fp.csv")
    monkeypatch.setattr(wf, "META", tmp_path / "week_fp_meta.json")
    monkeypatch.setattr(wf, "ROOT", tmp_path)
    src = tmp_path / "FantasyPros_2026_Week_1_QB_Rankings.csv"
    src.write_text(
        "RK,PLAYER NAME,TEAM,OPP,MATCHUP,START/SIT,PROJ. FPTS\n8,Trevor Lawrence,JAC,vs. CLE,1,B,18.1\n",
        encoding="utf-8",
    )
    combined = tmp_path / "combined.csv"
    combined.write_text("player,rank,score\nKeep,1,10\n", encoding="utf-8")
    meta = ir.import_weekly([src], fallback_week=1)
    assert not calls
    assert combined.read_text(encoding="utf-8").startswith("player,rank,score")
    assert meta["week"] == 1
    assert "QB" in meta["lists"]


def test_merge_module_does_not_touch_scoring_math():
    src = (Path(__file__).resolve().parents[1] / "merge.py").read_text(encoding="utf-8")
    assert "from scoring" not in src
    assert "score_game" not in src
    assert "Ranking math below does not change" in src
