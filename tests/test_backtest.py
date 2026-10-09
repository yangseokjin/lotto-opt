import json
import os

import cli
from conftest import FIXTURE, ROOT, make_cfg
from lotto_opt import backtest


def test_group_hits_counts_each_draw(draws):
    cfg = make_cfg()
    gh = backtest.group_hits(draws, cfg, 15)
    assert gh["draws"] == 15 and gh["last"] == draws[-1]["draw_no"]
    rows = {r["group"]: r for r in gh["rows"]}
    # Hot·Warm·Cold 는 45개를 나누므로 세 그룹 평균의 합은 항상 6
    assert abs(rows["Hot"]["mean"] + rows["Warm"]["mean"] + rows["Cold"]["mean"] - 6) < 1e-9
    assert abs(rows["Hot"]["expected"] - 6 * 14 / 45) < 1e-9


def test_random_baseline_and_render(draws):
    rows = backtest.random_portfolios(draws, 3, 5, seed=1)
    assert [r["draw"] for r in rows] == [d["draw_no"] for d in draws[-3:]]
    assert all(sum(r["match"].values()) == 5 for r in rows)
    text = backtest.render(None, {"무작위": rows}, 5)
    assert "포트폴리오 성적" in text and "무작위" in text


def test_backtest_command_builds_portfolios_from_past_only(tmp_path):
    code = cli.main(["backtest", "--config", os.path.join(ROOT, "config", "to_be.yaml"), "--draws", "1",
                     "--groups", "5", "--sets", "12", "--effort", "0.3", "--source", "cache", "--data", FIXTURE,
                     "--out", str(tmp_path)])
    assert code == 0
    md = next(tmp_path.glob("backtest_*.md")).read_text(encoding="utf-8")
    assert "그룹 적중률" in md and "| to_be | 1 |" in md


def test_odds_command_and_run_report(tmp_path, capsys):
    args = ["--source", "cache", "--data", FIXTURE, "--out", str(tmp_path), "--effort", "0.3"]
    assert cli.main(["run", "--config", os.path.join(ROOT, "config", "spread.yaml"), "--sets", "12",
                     "--seed", "2", *args]) == 0
    md = (tmp_path / "spread_12sets_seed2.md").read_text(encoding="utf-8")
    assert "당첨 확률" in md and "하나라도 5등 이상" in md
    path = tmp_path / "spread_12sets_seed2.json"
    assert 0 < json.loads(path.read_text(encoding="utf-8"))["odds"]["best"]["3"] < 1
    capsys.readouterr()
    assert cli.main(["odds", str(path)]) == 0
    assert "하나라도 5등 이상" in capsys.readouterr().out
