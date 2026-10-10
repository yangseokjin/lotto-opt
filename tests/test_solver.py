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


def test_display_order_is_seeded_shuffle():
    from lotto_opt.solver import _display_order
    sets = [(1, 2, 3, 4, 5, 6), (1, 7, 8, 9, 10, 11), (2, 3, 4, 5, 6, 7), (10, 20, 30, 40, 41, 42), (5, 6, 7, 8, 9, 10)]
    cfg = {"portfolio": {"seed": 42}}
    a = _display_order(sets, cfg)
    assert sorted(a) == sorted(sets)                      # 세트 내용은 그대로
    assert a == _display_order(list(reversed(sets)), cfg)  # 같은 시드면 같은 순서
    orders = {tuple(_display_order(sets, {"portfolio": {"seed": s}})) for s in range(1, 20)}
    assert len(orders) > 1                                # 시드가 바뀌면 순서도 바뀐다
