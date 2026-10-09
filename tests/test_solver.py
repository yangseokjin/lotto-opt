"""엔진 전체 실행: 독립 검증 통과, 같은 시드 재현, 다른 시드 다른 조합, 30/50세트."""
import itertools

import pytest

from conftest import make_cfg
from lotto_opt import solver, validate


def _run(draws, preset, sets, seed, effort=0.3):
    cfg = make_cfg(preset, sets, seed)
    out, a, final_cfg, stages, relaxed = solver.run(cfg, draws, log=lambda *_: None, effort=effort)
    return out, a, final_cfg, stages


def test_small_run_is_valid_and_reproducible(draws):
    a1 = _run(draws, "to_be", 12, seed=5)
    a2 = _run(draws, "to_be", 12, seed=5)
    assert a1[0] == a2[0]  # 같은 시드 → 같은 결과
    sets, a, cfg, stages = a1
    assert len(sets) == 12 and all(len(set(s)) == 6 for s in sets)
    assert not any(validate.validate(sets, cfg, a).values())
    assert [st["name"] for st in stages] == [st["name"] for st in cfg["objective"]]


def test_different_seeds_give_different_portfolios(draws):
    s1 = {tuple(s) for s in _run(draws, "to_be", 12, seed=1)[0]}
    s2 = {tuple(s) for s in _run(draws, "to_be", 12, seed=2)[0]}
    assert len(s1 & s2) <= 2


@pytest.mark.parametrize("preset,sets", [("to_be", 30), ("to_be", 50)])
def test_spec_sizes(draws, preset, sets):
    out, a, cfg, stages = _run(draws, preset, sets, seed=0)
    assert len(out) == sets
    assert not any(validate.validate(out, cfg, a).values())
    inter = [len(set(p) & set(q)) for p, q in itertools.combinations(out, 2)]
    assert max(inter) <= cfg["rules"]["overlap"]["max_common"]
    assert stages[0]["status"] == "OPTIMAL"  # 낮은 탐색량에서도 분포 오차가 피할 수 없는 최소치에 닿는다
