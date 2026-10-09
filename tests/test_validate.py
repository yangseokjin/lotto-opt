import random

from lotto_opt import pool, validate
from lotto_opt.constraints.set_level import group_combos


def test_ac_value():
    assert validate.ac([1, 2, 3, 4, 5, 6]) == 0
    assert validate.ac([1, 2, 4, 8, 16, 32]) == 10


def test_set_rule_violations_are_detected(cfg_and_analysis):
    cfg, a = cfg_and_analysis()
    R = cfg["rules"]
    cases = {
        "합계": [1, 2, 4, 7, 11, 16],
        "연속 길이": [10, 11, 12, 30, 35, 40],
        "연속 쌍": [10, 11, 20, 21, 35, 44],
        "AC": [5, 12, 19, 26, 33, 40],
        "구간": [1, 3, 5, 7, 30, 40],
    }
    for rule, s in cases.items():
        assert rule in validate.set_violations(s, R, a), (rule, s)


def test_pool_filter_agrees_with_validator(cfg_and_analysis):
    """후보 풀의 빠른 검사(pool.set_attrs)와 독립 검증기(validate)가 같은 판정을 내리는지 무작위 세트로 확인."""
    for preset in ("to_be", "spread"):
        cfg, a = cfg_and_analysis(preset)
        R = cfg["rules"]
        combos = set(group_combos(R["group_mix"]))
        bins = list(a.targets["sum_bins"]) if a.targets.get("sum_bins") else None
        rng = random.Random(1)
        agree = valid = 0
        for _ in range(3000):
            s = tuple(sorted(rng.sample(range(1, 46), 6)))
            fast = pool.set_attrs(s, R, a, combos, bins) is not None
            slow = not validate.set_violations(list(s), R, a)
            agree += fast == slow
            valid += slow
        assert agree == 3000, preset
        assert valid > 100, preset  # 유효한 세트도 충분히 섞여 있었는지


def test_global_violations(cfg_and_analysis):
    cfg, a = cfg_and_analysis(sets=12)
    sets = [[1, 2, 3, 4, 5, 6]] * 12  # 같은 세트 반복: 교집합·출현 횟수·커버리지 모두 위반
    v = validate.global_violations(sets, cfg["rules"], a)
    assert "교집합" in v and "커버리지 전체" in v
    assert any(x.startswith("출현 횟수") for x in v)
