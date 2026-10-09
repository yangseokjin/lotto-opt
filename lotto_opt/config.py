import copy
import math

import yaml

# 세트 수에 비례하는 항목 (프로필에 없는 세트 수를 고를 때 가까운 프로필에서 비례 조정)
SCALED = ("rules.appearance", "rules.carry_over.per_number_uses", "rules.mean_reversion.min_sets_each")


def load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_path(cfg, dotted, default=None):
    node = cfg
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def set_path(cfg, dotted, value):
    """'rules.overlap.max_common' 같은 점 경로에 값을 넣은 복사본을 반환."""
    out = copy.deepcopy(cfg)
    node = out
    *parents, last = dotted.split(".")
    for key in parents:
        node = node.setdefault(key, {})
    node[last] = value
    return out


def _scale(v, f):
    if isinstance(v, dict):
        return {k: _scale(x, f) for k, x in v.items()}
    if isinstance(v, list) and len(v) == 2:  # [하한, 상한]
        return [math.floor(v[0] * f), math.ceil(v[1] * f)]
    return max(1, round(v * f))


def apply_profile(cfg):
    """세트 수에 맞는 profiles 항목을 rules 에 적용한다. (새 cfg, 설명 문구) 반환.

    profiles 에 그 세트 수가 있으면 그대로 쓰고, 없으면 가장 가까운 세트 수의 값을 비례 조정한다.
    커버리지는 비례하지 않고, 세트 수로 채울 수 있는 칸(6×세트 수)을 넘지 않게만 줄인다.
    """
    profiles = cfg.get("profiles") or {}
    if not profiles:
        return cfg, None
    S = cfg["portfolio"]["sets"]
    sizes = sorted(int(k) for k in profiles)
    base = min(sizes, key=lambda k: (abs(k - S), -k))
    prof = profiles.get(base, profiles.get(str(base)))
    f = S / base
    for path, value in prof.items():
        if base != S and path in SCALED:
            value = _scale(value, f)
        if base != S and path == "rules.coverage":
            value = {k: min(v, 6 * S) for k, v in value.items()}
        cfg = set_path(cfg, path, value)
    note = f"{S}세트 기준" if base == S else f"{S}세트 기준 없음: {base}세트 기준을 비례 조정"
    return cfg, note
