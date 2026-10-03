import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lotto_opt import config, data, stats  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "data", "draws_fixture.json")


@pytest.fixture(scope="session")
def draws():
    """제1124회~제1243회 실제 당첨번호 (네트워크 없이 테스트하려고 저장해 둔 값)."""
    out, source = data.load_draws(FIXTURE, "cache")
    assert source == "cache"
    return out


def make_cfg(preset="to_be", sets=30, seed=0, **overrides):
    cfg = config.load(os.path.join(ROOT, "config", f"{preset}.yaml"))
    cfg["portfolio"]["sets"] = sets
    cfg["portfolio"]["seed"] = seed
    for path, value in overrides.items():
        cfg = config.set_path(cfg, path.replace("__", "."), value)
    cfg, _ = config.apply_profile(cfg)
    return cfg


@pytest.fixture
def cfg_and_analysis(draws):
    def make(preset="to_be", sets=30, seed=0, **overrides):
        cfg = make_cfg(preset, sets, seed, **overrides)
        return cfg, stats.analyze(draws, cfg)
    return make
