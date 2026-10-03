"""사전식 목적함수 단계.

단계마다 두 가지를 둔다.
  - model(ctx): CP-SAT 에서 최소화할 정수식
  - value(sets, a, rules): 같은 값을 순수 파이썬으로 계산 (해를 합치거나 검증할 때 사용)
tests/test_objective.py 가 두 계산이 같은 값을 내는지 확인한다.
"""
import itertools
import math
from collections import Counter

from .constraints.set_level import group_combos
from .stats import LH_BUCKETS, OE_BUCKETS


def _target_units(S, share):
    return round(100 * S * share)


def _abs_dev(ctx, total, share):
    """|세트 수 × 100 - 목표 세트 수 × 100|."""
    e = ctx.m.NewIntVar(0, 100 * ctx.S, "")
    ctx.m.AddAbsEquality(e, 100 * total - _target_units(ctx.S, share))
    return e


def _cat_total(ctx, attr, value):
    return sum(ctx.cat[attr][s].get(value, 0) for s in ctx.sets)


def _families(T):
    """(이름, 목표 dict) 목록. 목표 키는 세트 속성 값."""
    out = []
    for name in ("odd_even", "low_high", "carry", "group_mix", "sum_bins"):
        if T.get(name):
            keys = list(T[name].items())
            if name == "sum_bins":
                keys = [(i, p) for i, (_, p) in enumerate(keys)]
            if name == "carry":
                keys = [(int(k), p) for k, p in keys]
            out.append((name, keys))
    return out


def set_categories(s, a, bins):
    """세트 하나의 범주 속성 (분포 목표용)."""
    odd = sum(n % 2 for n in s)
    low = sum(n <= 22 for n in s)
    h = sum(n in a.hot for n in s)
    w = sum(n in a.warm for n in s)
    total = sum(s)
    return {"odd_even": next(k for k, vs in OE_BUCKETS.items() if odd in vs),
            "low_high": next(k for k, vs in LH_BUCKETS.items() if low in vs),
            "carry": sum(n in a.carry for n in s),
            "group_mix": (h, w, 6 - h - w),
            "sum_bins": next((i for i, (lo, hi) in enumerate(bins) if lo <= total <= hi), None) if bins else None}


# ---- 1) 분포 오차 ----

def distribution_error(ctx, **_):
    """목표 분포와의 오차 합 (단위: 세트 수×100). 홀짝·저고·이월수·그룹 구성·합계 구간."""
    attr = {"odd_even": None, "low_high": None, "carry": "carry", "group_mix": "combo", "sum_bins": "sum_bin"}
    terms = []
    for name, keys in _families(ctx.a.targets):
        for k, p in keys:
            if name == "odd_even":
                tot = ctx.oe_tot[k]
            elif name == "low_high":
                tot = ctx.lh_tot[k]
            else:
                tot = _cat_total(ctx, attr[name], k)
            terms.append(_abs_dev(ctx, tot, p))
    return sum(terms)


def distribution_error_value(sets, a, R, **_):
    S = len(sets)
    bins = list(a.targets["sum_bins"]) if a.targets.get("sum_bins") else None
    cats = [set_categories(s, a, bins) for s in sets]
    err = 0
    for name, keys in _families(a.targets):
        cnt = Counter(c[name] for c in cats)
        err += sum(abs(100 * cnt.get(k, 0) - _target_units(S, p)) for k, p in keys)
    return err


def _family_bound(S, units, cats, limits=None, value=None, window=None):
    """한 분포의 최소 오차: 범주별 세트 수(정수)를 정하는 모든 방법 중 목표에 가장 가까운 것 (작은 동적 계획법).

    units: {범주: 목표 단위(세트 수×100)}, cats: 세트가 실제로 가질 수 있는 범주 (목표 없는 범주는 비용 0),
    limits: {범주: (최소, 최대) 세트 수}, value/window: Σ 범주 값 × 세트 수가 window 안이어야 할 때.
    """
    fixed = sum(t for k, t in units.items() if k not in cats)  # 나올 수 없는 범주는 목표만큼 그대로 오차
    dp = {(0, 0): 0}  # (지금까지 정한 세트 수, 범주 값의 합) → 최소 오차
    for k in cats:
        lo, hi = (limits or {}).get(k, (0, S))
        v = value(k) if value else 0
        nxt = {}
        for (j, u), e in dp.items():
            for c in range(lo, min(hi, S - j) + 1):
                key, cost = (j + c, u + v * c), e + (abs(100 * c - units[k]) if k in units else 0)
                if cost < nxt.get(key, cost + 1):
                    nxt[key] = cost
        dp = nxt
    ok = [e for (j, u), e in dp.items() if j == S and (window is None or window[0] <= u <= window[1])]
    return fixed + min(ok, default=0)


def _carry_window(a, R, S):
    """세트별 이월수 개수의 합 = 이월수 6개의 출현 횟수 합. 그 합이 가질 수 있는 범위."""
    ap, (ulo, uhi) = R["appearance"], R["carry_over"]["per_number_uses"]
    lo = hi = 0
    for n in a.carry:
        g = ap["hot_top" if n in a.top else "general"]
        lo, hi = lo + max(g[0], ulo, 0), hi + min(g[1], uhi, S)
    return lo, hi


def distribution_error_bound(a, S, R):
    """분포 오차의 하한. 이 값에 닿으면 최적.

    분포마다 따로, 세트 수가 정수라는 점과 그 분포에 직접 걸린 제약(홀짝·저고 밴드, 이월수 사용 횟수)만
    반영해 가장 가까운 배분을 찾는다. 예: 50세트에서 이월수를 각 7회 이상 쓰면 이월수 목표보다
    이월수 든 세트가 많아질 수밖에 없는데, 그만큼은 피할 수 없는 오차로 친다.
    """
    cats = {"odd_even": list(OE_BUCKETS), "low_high": list(LH_BUCKETS),
            "carry": list(range(R["carry_over"]["per_set"][0], R["carry_over"]["per_set"][1] + 1)),
            "group_mix": group_combos(R["group_mix"]),
            "sum_bins": list(range(len(a.targets.get("sum_bins") or {})))}
    bands = R.get("bands") or {}
    total = 0
    for name, keys in _families(a.targets):
        units = {k: _target_units(S, p) for k, p in keys}
        limits = {k: (math.ceil(lo * S), math.floor(hi * S)) for k, (lo, hi) in bands.get(name, {}).items()}
        extra = {"value": lambda k: k, "window": _carry_window(a, R, S)} if name == "carry" else {}
        total += _family_bound(S, units, cats[name], limits, **extra)
    return total


# ---- 2) 교집합 ----

def _overlap_weights(S, start, mc):
    P = S * (S - 1) // 2
    return {k: (P + 1) ** (k - start) for k in range(start, mc + 1)}


def overlap(ctx, start=2, **_):
    """세트 쌍 교집합을 큰 것부터 사전식으로 줄인다.

    교집합 k개 이상인 쌍 수를 k가 클수록 훨씬 큰 가중치로 더한다. 즉 최대 교집합 크기를 먼저 줄이고,
    그다음 그 크기의 쌍 수를 줄이고, 마지막으로 start개(기본 2개, 같은 번호 쌍이 두 세트에 나온 경우)
    공유하는 쌍 수를 줄인다.
    """
    m, mc = ctx.m, ctx.rules["overlap"]["max_common"]
    pen = []
    for k, weight in _overlap_weights(ctx.S, start, mc).items():
        level = []
        for c in ctx.pair_common:
            if isinstance(c, int):  # 고정 세트끼리의 쌍
                level.append(int(c >= k))
                continue
            b = m.NewBoolVar("")  # 교집합이 k개 이상이면 b=1
            m.Add(c - (k - 1) <= (mc - k + 1) * b)
            level.append(b)
        pen.append(weight * sum(level))
    return sum(pen)


def overlap_value(sets, a, R, start=2, **_):
    inter = [len(set(p) & set(q)) for p, q in itertools.combinations(sets, 2)]
    W = _overlap_weights(len(sets), start, R["overlap"]["max_common"])
    return sum(w * sum(c >= k for c in inter) for k, w in W.items())


# ---- 3) 출현 횟수 ----

def appearance_variance(ctx, **_):
    """(S+1) × Σ 번호별 출현 횟수² + (이월수 6개 사용 횟수 최대-최소).

    세트 수가 정해지면 출현 횟수의 합(6×S)이 고정이므로 제곱합 최소화 = 분산 최소화다.
    """
    m, C = ctx.m, ctx.appear
    sq = sum(k * k * b for oh in ctx.appear_onehot.values() for k, b in oh.items())
    hi, lo = m.NewIntVar(0, ctx.S, ""), m.NewIntVar(0, ctx.S, "")
    m.AddMaxEquality(hi, [C[n] for n in ctx.a.carry]); m.AddMinEquality(lo, [C[n] for n in ctx.a.carry])
    return (ctx.S + 1) * sq + (hi - lo)


def appearance_variance_value(sets, a, R, **_):
    C = Counter(n for s in sets for n in s)
    uses = [C[n] for n in a.carry]
    return (len(sets) + 1) * sum(C[n] ** 2 for n in range(1, 46)) + max(uses) - min(uses)


def appearance_spread(ctx, **_):
    """(v0.1 방식) 10 × (번호별 출현 최대-최소) + (이월수별 사용 최대-최소)."""
    m, C = ctx.m, ctx.appear
    def spread(nums):
        hi, lo = m.NewIntVar(0, ctx.S, ""), m.NewIntVar(0, ctx.S, "")
        m.AddMaxEquality(hi, [C[n] for n in nums]); m.AddMinEquality(lo, [C[n] for n in nums])
        return hi - lo
    return 10 * spread(list(C)) + spread(ctx.a.carry)


def appearance_spread_value(sets, a, R, **_):
    C = Counter(n for s in sets for n in s)
    allc = [C[n] for n in range(1, 46)]
    uses = [C[n] for n in a.carry]
    return 10 * (max(allc) - min(allc)) + max(uses) - min(uses)


STAGES = {"distribution_error": distribution_error, "overlap": overlap,
          "appearance_variance": appearance_variance, "appearance_spread": appearance_spread}
VALUES = {"distribution_error": distribution_error_value, "overlap": overlap_value,
          "appearance_variance": appearance_variance_value, "appearance_spread": appearance_spread_value}


def bound(name, a, R, S):
    """단계 값의 하한 (계산이 싼 경우만). 없으면 None."""
    if name == "distribution_error":
        return distribution_error_bound(a, S, R)
    if name == "overlap":
        return 0
    return None
