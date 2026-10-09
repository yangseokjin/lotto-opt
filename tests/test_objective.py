"""CP-SAT 목적식과 파이썬 계산이 같은 값을 내는지, 하한이 실제로 하한인지 확인."""
import pytest
from ortools.sat.python import cp_model

from lotto_opt import objective, pool, solver, validate


def _portfolio(cfg, a, seed):
    sets, score = pool.construct(cfg, a, seed)
    assert score[0] == 0 and not any(validate.validate(sets, cfg, a).values())
    return sets


@pytest.mark.parametrize("preset,sets", [("to_be", 12), ("to_be", 30), ("spread", 30)])
def test_python_values_match_cp_sat(cfg_and_analysis, preset, sets):
    cfg, a = cfg_and_analysis(preset, sets)
    portfolio = _portfolio(cfg, a, f"t{sets}")
    S = len(portfolio)
    ctx = solver.build(cfg, a, {s: portfolio[s] for s in range(S)})  # 모든 세트 고정 → 목적식 값만 계산
    for st in cfg["objective"]:
        expr = ctx.objs[st["name"]]
        if isinstance(expr, int):
            got = expr
        else:
            ctx.m.Minimize(expr)
            sv = cp_model.CpSolver()
            sv.parameters.num_workers = 1
            assert sv.Solve(ctx.m) == cp_model.OPTIMAL
            got = round(sv.ObjectiveValue())
        assert got == objective.VALUES[st["name"]](portfolio, a, cfg["rules"], **solver._opts(st)), st["name"]


def test_distribution_bound_is_lower_bound(cfg_and_analysis):
    for preset, sets in (("to_be", 30), ("to_be", 50), ("spread", 30)):
        cfg, a = cfg_and_analysis(preset, sets)
        lb = objective.bound("distribution_error", a, cfg["rules"], sets)
        for seed in range(3):
            portfolio = _portfolio(cfg, a, f"b{seed}")
            assert lb <= objective.distribution_error_value(portfolio, a, cfg["rules"])


def test_overlap_value_is_lexicographic(cfg_and_analysis):
    cfg, a = cfg_and_analysis(sets=4)
    R = cfg["rules"]
    one_triple = [[1, 2, 3, 10, 20, 30], [1, 2, 3, 11, 21, 31], [4, 5, 6, 12, 22, 32], [7, 8, 9, 13, 23, 33]]
    many_doubles = [[1, 2, 10, 20, 30, 40], [1, 2, 11, 21, 31, 41], [3, 4, 10, 21, 32, 42], [3, 4, 11, 20, 33, 43]]
    # 3개 공유 1쌍이 2개 공유 여러 쌍보다 나쁘다
    assert objective.overlap_value(one_triple, a, R) > objective.overlap_value(many_doubles, a, R)


def test_family_bound_respects_rounding_and_carry_window():
    units = {0: 400, 1: 450, 2: 150}  # 10세트 중 목표 4 / 4.5 / 1.5세트
    assert objective._family_bound(10, units, [0, 1, 2]) == 100
    # 이월수 개수 합이 9 이상이어야 하면 (3, 5, 2)세트가 가장 가깝다
    assert objective._family_bound(10, units, [0, 1, 2], value=lambda k: k, window=(9, 20)) == 200
    # 목표 없는 범주에는 남는 세트를 오차 없이 둘 수 있고, 나올 수 없는 범주의 목표는 그대로 오차가 된다
    assert objective._family_bound(5, {"a": 300}, ["a", "b"]) == 0
    assert objective._family_bound(5, {"a": 300, "z": 200}, ["a", "b"]) == 200


def test_hit_weights_follow_exact_joint_win_counts():
    # 두 세트가 k개 공유할 때 같은 회차에 둘 다 3개 이상 맞는 추첨 수 (전체 8,145,060개 중, 직접 세어 확인한 값)
    assert [objective._both_win(k) for k in range(7)] == [400, 3700, 13900, 31470, 60486, 109770, 194130]
    w = objective._overlap_weights(30, 2, 3, "hit")
    assert w == {1: 33, 2: 102, 3: 176}
    # 2개 공유 1쌍이 1개 공유 2쌍보다 나쁘다 (번호를 고르게 퍼뜨리는 쪽이 낫다)
    assert w[1] + w[2] > 2 * w[1]
