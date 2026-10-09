import json
import os

import cli
from conftest import FIXTURE, ROOT


def _args(tmp_path, *extra):
    return [*extra, "--source", "cache", "--data", FIXTURE, "--out", str(tmp_path), "--effort", "0.3"]


def test_run_writes_report(tmp_path):
    code = cli.main(_args(tmp_path, "run", "--config", os.path.join(ROOT, "config", "to_be.yaml"),
                          "--sets", "12", "--seed", "3"))
    assert code == 0
    md = (tmp_path / "to_be_12sets_seed3.md").read_text(encoding="utf-8")
    assert "독립 검증: 위반 없음" in md and "--seed 3" in md
    data = json.loads((tmp_path / "to_be_12sets_seed3.json").read_text(encoding="utf-8"))
    assert data["seed"] == 3 and len(data["sets"]) == 12


def test_run_without_seed_picks_one(tmp_path):
    assert cli.main(_args(tmp_path, "run", "--config", os.path.join(ROOT, "config", "to_be.yaml"), "--sets", "12")) == 0
    files = list(tmp_path.glob("to_be_12sets_seed*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text(encoding="utf-8"))["seed"] is not None


def test_compare_uses_one_seed(tmp_path):
    code = cli.main(_args(tmp_path, "compare", "--config", os.path.join(ROOT, "config", "to_be.yaml"),
                          "--config", os.path.join(ROOT, "config", "spread.yaml"), "--sets", "12", "--seed", "4"))
    assert code == 0
    assert (tmp_path / "compare_to_be_vs_spread_12sets_seed4.md").exists()
    assert (tmp_path / "to_be_12sets_seed4.md").exists() and (tmp_path / "spread_12sets_seed4.md").exists()


def test_run_defaults_to_to_be(tmp_path):
    assert cli.main(_args(tmp_path, "run", "--sets", "12", "--seed", "5")) == 0
    assert (tmp_path / "to_be_12sets_seed5.json").exists()
