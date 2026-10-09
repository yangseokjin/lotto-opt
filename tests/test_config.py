import os

from conftest import ROOT, make_cfg

from lotto_opt import config


def test_profile_30_and_50_follow_spec():
    c30 = make_cfg("to_be", 30)
    assert c30["rules"]["appearance"] == {"general": [2, 8], "hot_top": [3, 10]}
    assert c30["rules"]["carry_over"]["per_number_uses"] == [4, 6]
    assert c30["rules"]["coverage"] == {"total": 40, "hot": 13, "warm": 15, "cold": 12}
    c50 = make_cfg("to_be", 50)
    assert c50["rules"]["appearance"] == {"general": [3, 12], "hot_top": [4, 15]}
    assert c50["rules"]["carry_over"]["per_number_uses"] == [7, 10]
    assert c50["rules"]["coverage"] == {"total": 43, "hot": 13, "warm": 16, "cold": 13}
    assert c50["rules"]["mean_reversion"]["min_sets_each"] == 8
    assert make_cfg("as_is", 50)["rules"]["carry_over"]["per_number_uses"] == [7, 10]


def test_profile_scales_for_other_sizes():
    cfg = config.load(os.path.join(ROOT, "config", "to_be.yaml"))
    cfg["portfolio"]["sets"] = 12
    cfg, note = config.apply_profile(cfg)
    assert "30세트 기준을 비례 조정" in note
    assert cfg["rules"]["appearance"]["general"] == [0, 4]
    assert cfg["rules"]["carry_over"]["per_number_uses"] == [1, 3]
    assert cfg["rules"]["mean_reversion"]["min_sets_each"] == 2


def test_set_and_get_path_do_not_mutate():
    cfg = {"a": {"b": 1}}
    new = config.set_path(cfg, "a.c.d", 5)
    assert cfg == {"a": {"b": 1}}
    assert config.get_path(new, "a.c.d") == 5
    assert config.get_path(new, "a.x", "없음") == "없음"
