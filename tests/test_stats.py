from lotto_opt import stats
from lotto_opt.constraints.set_level import group_combos


def test_groups_partition_all_numbers(cfg_and_analysis):
    cfg, a = cfg_and_analysis()
    assert (len(a.hot), len(a.warm), len(a.cold)) == (14, 17, 14)
    assert sorted(a.hot + a.warm + a.cold) == list(range(1, 46))
    assert a.top == a.hot[:5]
    assert (a.first, a.last) == (1144, 1243)
    assert a.carry == [9, 18, 24, 38, 43, 44]


def test_ranking_tie_break(draws, cfg_and_analysis):
    """가중치 동률이면 최근 10회 출현 많은 순 → 최근 출현 회차 최신 순 → 번호 오름차순."""
    cfg, a = cfg_and_analysis()
    window = draws[-100:]
    recent = {n: sum(n in d["numbers"] for d in window[-10:]) for n in range(1, 46)}
    for x, y in zip(a.rank, a.rank[1:]):
        assert a.weight[x] >= a.weight[y]
        if a.weight[x] == a.weight[y]:
            assert (recent[x], a.last_seen[x], -x) > (recent[y], a.last_seen[y], -y)


def test_mean_reversion_weight_mode(cfg_and_analysis):
    _, forced = cfg_and_analysis("to_be")
    _, weighted = cfg_and_analysis("to_be", rules__mean_reversion={"mode": "weight", "candidates": 5, "bonus": 0.2})
    for n in weighted.long_absent:
        assert abs(weighted.weight[n] - forced.weight[n] - 0.2) < 1e-9
    assert set(forced.long_absent) <= set(forced.cold)


def test_auto_targets_are_distributions(cfg_and_analysis):
    cfg, a = cfg_and_analysis()
    T = a.targets
    for name in ("odd_even", "low_high", "carry", "group_mix", "sum_bins"):
        assert abs(sum(T[name].values()) - 1) < 1e-9, name
    lo, hi = cfg["rules"]["carry_over"]["per_set"]
    assert set(T["carry"]) == set(range(lo, hi + 1))
    assert set(T["group_mix"]) == set(group_combos(cfg["rules"]["group_mix"]))
    bins = sorted(T["sum_bins"])
    assert bins[0][0] == cfg["rules"]["sum_range"][0] and bins[-1][1] == cfg["rules"]["sum_range"][1]
    assert all(b[1] + 1 == c[0] for b, c in zip(bins, bins[1:]))  # 빈틈·겹침 없는 구간


def test_spec_targets_switch(cfg_and_analysis):
    _, a = cfg_and_analysis(targets__odd_even="spec", targets__low_high="spec", targets__carry="spec")
    assert a.targets["odd_even"] == stats.SPEC_TARGETS["odd_even"]
    assert a.targets["low_high"] == stats.SPEC_TARGETS["low_high"]
    assert a.targets["carry"] == stats.SPEC_TARGETS["carry"]
    _, auto = cfg_and_analysis()
    assert auto.targets["odd_even"] == auto.observed["odd_even"]


def test_explicit_group_mix_target(cfg_and_analysis):
    _, a = cfg_and_analysis(targets__group_mix={"2-3-1": 1, "3-2-1": 1})
    assert a.targets["group_mix"][(2, 3, 1)] == 0.5
    assert a.targets["group_mix"][(2, 2, 2)] == 0
