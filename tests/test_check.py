import json
import os

import pytest

import cli
from conftest import FIXTURE
from lotto_opt import check

WIN, BONUS = [3, 8, 17, 30, 33, 34], 28  # 제1124회
SETS = [
    [3, 8, 17, 30, 33, 34],   # 1등
    [3, 8, 17, 30, 33, 28],   # 2등 (5개 + 보너스)
    [3, 8, 17, 30, 33, 45],   # 3등
    [3, 8, 17, 30, 1, 2],     # 4등
    [3, 8, 17, 1, 2, 28],     # 5등 (보너스는 5개 일치에서만 셈)
    [3, 8, 1, 2, 4, 5],       # 낙첨
]


@pytest.mark.parametrize("matched, bonus_hit, expected", [
    (6, False, 1), (5, True, 2), (5, False, 3), (4, False, 4), (4, True, 4), (3, False, 5), (2, True, None), (0, False, None),
])
def test_rank(matched, bonus_hit, expected):
    assert check.rank(matched, bonus_hit) == expected


def test_check_every_rank():
    res = check.check(SETS, WIN, BONUS)
    assert [r["rank"] for r in res["results"]] == [1, 2, 3, 4, 5, None]
    assert res["results"][1]["bonus_hit"] and not res["results"][4]["bonus_hit"]
    assert res["results"][3]["matched"] == [3, 8, 17, 30]
    sm = res["summary"]
    assert sm["by_rank"] == {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1}
    assert sm["best_rank"] == 1 and sm["winning_sets"] == 5
    assert sm["by_match_count"]["5"] == 2 and sm["by_match_count"]["2"] == 1


def test_no_win():
    sm = check.check([[1, 2, 4, 5, 6, 7]], WIN, BONUS)["summary"]
    assert sm["best_rank"] is None and sm["winning_sets"] == 0
    assert "낙첨" in check.render(check.check([[1, 2, 4, 5, 6, 7]], WIN, BONUS))


@pytest.mark.parametrize("numbers, bonus", [
    ([1, 2, 3, 4, 5], 7), ([1, 1, 2, 3, 4, 5], 7), ([0, 2, 3, 4, 5, 6], 7), ([1, 2, 3, 4, 5, 6], 6), ([1, 2, 3, 4, 5, 6], 46),
])
def test_bad_winning_numbers(numbers, bonus):
    with pytest.raises(ValueError):
        check.check(SETS, numbers, bonus)


def _portfolio(tmp_path, sets=SETS):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"preset": "to_be", "seed": 1, "range": [1104, 1123], "sets": sets}), encoding="utf-8")
    return str(path)


def test_cli_check_by_draw(tmp_path, capsys):
    code = cli.main(["check", _portfolio(tmp_path), "--draw", "1124", "--source", "cache", "--data", FIXTURE, "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["draw"]["draw_no"] == 1124 and out["bonus"] == BONUS
    assert out["summary"]["best_rank"] == 1 and out["portfolio"]["seed"] == 1


def test_cli_check_latest_and_manual(tmp_path, capsys):
    path = _portfolio(tmp_path)
    # 회차를 안 주면 분석 마지막 회차(1123)의 다음 회차와 비교한다
    assert cli.main(["check", path, "--source", "cache", "--data", FIXTURE]) == 0
    assert "제1124회" in capsys.readouterr().out
    no_range = tmp_path / "old.json"
    no_range.write_text(json.dumps({"sets": SETS}), encoding="utf-8")  # 분석 범위가 없는 옛 파일은 최신 회차
    assert cli.main(["check", str(no_range), "--source", "cache", "--data", FIXTURE]) == 0
    assert "제1243회" in capsys.readouterr().out
    assert cli.main(["check", path, "--numbers", "3, 8, 17, 30, 33, 45", "--bonus", "28", "--json"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["draw"] is None and [r["rank"] for r in res["results"]][:3] == [3, 2, 1]


def test_cli_check_errors(tmp_path):
    path = _portfolio(tmp_path)
    for argv in (["--draw", "99999", "--source", "cache", "--data", FIXTURE],
                 ["--numbers", "1,2,3,4,5,6"],
                 ["--numbers", "1,2,3,4,5", "--bonus", "7"]):
        with pytest.raises(SystemExit) as e:
            cli.main(["check", path, *argv])
        assert e.value.code not in (0, None)
    with pytest.raises(SystemExit):
        cli.main(["check", _portfolio(tmp_path, [[1, 2, 3]]), "--numbers", "1,2,3,4,5,6", "--bonus", "7"])


def test_check_reads_run_output(tmp_path, capsys):
    out = tmp_path / "out"
    assert cli.main(["run", "--config", os.path.join(os.path.dirname(FIXTURE), "..", "..", "config", "to_be.yaml"),
                     "--sets", "12", "--seed", "3", "--source", "cache", "--data", FIXTURE, "--out", str(out),
                     "--effort", "0.3"]) == 0
    capsys.readouterr()
    assert cli.main(["check", str(out / "to_be_12sets_seed3.json"), "--draw", "1243",
                     "--source", "cache", "--data", FIXTURE]) == 0
    text = capsys.readouterr().out
    assert "12세트" in text and "이미 계산에 들어간 지난 회차" in text and "나올 수 없습니다" in text
    # 분석 마지막 회차와는 이월수 규칙(세트당 최대 2개) 때문에 3개 이상 맞는 세트가 구조상 없다
    assert cli.main(["check", str(out / "to_be_12sets_seed3.json"), "--draw", "1243", "--json",
                     "--source", "cache", "--data", FIXTURE]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["in_sample"] and res["target_draw"] == 1244
    assert max(r["match_count"] for r in res["results"]) <= 2


def test_cli_check_target_not_drawn_yet(tmp_path, capsys):
    path = tmp_path / "p.json"  # 데이터 마지막 회차(1243)까지로 만든 결과 → 노린 회차 1244는 아직 없음
    path.write_text(json.dumps({"preset": "to_be", "seed": 1, "range": [1144, 1243], "sets": SETS}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["check", str(path), "--source", "cache", "--data", FIXTURE])
    assert "제1244회" in str(e.value.code) and "추첨 전" in str(e.value.code)
