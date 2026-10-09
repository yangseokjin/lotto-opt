"""시드 기반 출발점 만들기.

1) 개별 세트 제약을 모두 지키는 세트를 무작위로 뽑아 후보 풀을 만든다.
2) 풀에서 세트를 바꿔 끼우는 지역 탐색으로 전역 제약(출현 횟수, 이월수 사용, 교집합, 비율 등)을
   만족하고 목표 분포에 가까운 포트폴리오를 만든다.

이 결과가 첫 해가 된다. 이후 search.py 와 CP-SAT 이웃 탐색은 모든 제약을 지키는 범위에서만 고치고,
마지막에 validate.py 가 독립적으로 다시 검사한다. 시드가 다르면 풀과 출발점이 달라져 다른 포트폴리오가 나온다.
"""
import math
import random

from .constraints.set_level import ZONES, group_combos
from .stats import LH_BUCKETS, OE_BUCKETS

NUMS = range(1, 46)
_ZONE = {n: i for i, z in enumerate(ZONES) for n in z}


def _bucket(v, buckets):
    return next(k for k, vs in buckets.items() if v in vs)


def set_attrs(s, R, a, combos, bins):
    """세트 s(오름차순 6개)가 개별 제약을 모두 지키면 범주 속성 dict, 아니면 None."""
    h = sum(n in a.hot_set for n in s)
    w = sum(n in a.warm_set for n in s)
    combo = (h, w, 6 - h - w)
    if combo not in combos:
        return None
    co = sum(n in a.carry_set for n in s)
    if not R["carry_over"]["per_set"][0] <= co <= R["carry_over"]["per_set"][1]:
        return None
    total = sum(s)
    if not R["sum_range"][0] <= total <= R["sum_range"][1]:
        return None
    pairs, run, best = 0, 1, 1
    for i in range(5):
        if s[i + 1] - s[i] == 1:
            pairs += 1; run += 1; best = max(best, run)
        else:
            run = 1
    if best > R["consecutive"]["max_run"] or pairs > R["consecutive"]["max_pairs"]:
        return None
    zc = [0] * 5
    for n in s:
        zc[_ZONE[n]] += 1
    if max(zc) > R["zones"]["max_per_zone"] or sum(z > 0 for z in zc) < R["zones"]["min_zones"]:
        return None
    odd = sum(n % 2 for n in s)
    low = sum(n <= 22 for n in s)
    if not (R["odd_count"][0] <= odd <= R["odd_count"][1] and R["low_count"][0] <= low <= R["low_count"][1]):
        return None
    if len({s[j] - s[i] for i in range(6) for j in range(i + 1, 6)}) - 5 < R["ac_min"]:
        return None
    sb = next((i for i, (lo, hi) in enumerate(bins) if lo <= total <= hi), None) if bins else None
    return {"combo": combo, "carry": co, "sum_bin": sb, "no_pair": pairs == 0,
            "odd_even": _bucket(odd, OE_BUCKETS), "low_high": _bucket(low, LH_BUCKETS)}


def sample_pool(cfg, a, rng, size):
    """개별 제약을 지키는 서로 다른 세트 size 개 (시드 rng 로 균등 추출)."""
    R = cfg["rules"]
    combos = set(group_combos(R["group_mix"]))
    bins = list(a.targets["sum_bins"]) if a.targets.get("sum_bins") else None
    pool, attrs, seen = [], [], set()
    for _ in range(size * 100):
        s = tuple(sorted(rng.sample(range(1, 46), 6)))
        if s in seen:
            continue
        seen.add(s)
        at = set_attrs(s, R, a, combos, bins)
        if at:
            pool.append(s); attrs.append(at)
            if len(pool) == size:
                break
    return pool, attrs


class _State:
    """선택된 세트들의 전역 위반량과 분포 오차를 증분 계산한다."""

    def __init__(self, cfg, a, pool, attrs, S):
        R, self.S = cfg["rules"], S
        self.pool, self.attrs = pool, attrs
        self.mask = [sum(1 << n for n in s) for s in pool]
        lo_hi = {n: list(R["appearance"]["hot_top" if n in a.top else "general"]) for n in NUMS}
        cu = R["carry_over"]["per_number_uses"]
        for n in a.carry:
            lo_hi[n] = [max(lo_hi[n][0], cu[0]), min(lo_hi[n][1], cu[1])]
        self.lo_hi = lo_hi
        self.mc = R["overlap"]["max_common"]
        z = R["consecutive"]["zero_pair_share"]
        self.zp = (math.floor(z[0] * S), math.ceil(z[1] * S))
        self.bands = [(fam, key, math.ceil(lo * S), math.floor(hi * S))
                      for fam, d in (R.get("bands") or {}).items() for key, (lo, hi) in d.items()]
        mr = R["mean_reversion"]
        self.mr = (list(a.long_absent), mr["min_sets_each"], mr["min_numbers"]) if mr.get("mode") == "forced" else None
        cv = R["coverage"]
        self.cov = [(set(NUMS), cv["total"])] + [(set(getattr(a, g)), cv[g]) for g in ("hot", "warm", "cold")]
        T = a.targets
        self.targets = {}
        for fam in ("odd_even", "low_high", "carry", "group_mix", "sum_bins"):
            if T.get(fam):
                key = {"group_mix": "combo", "sum_bins": "sum_bin"}.get(fam, fam)
                vals = list(T[fam].items()) if fam != "sum_bins" else list(enumerate(T[fam].values()))
                self.targets[key] = {(int(k) if key == "carry" else k): p * S for k, p in vals}

    def score(self, chosen):
        """(전역 제약 위반량, 목표 분포 오차)."""
        C = [0] * 46
        for j in chosen:
            for n in self.pool[j]:
                C[n] += 1
        v = sum(max(0, lo - C[n]) + max(0, C[n] - hi) for n, (lo, hi) in self.lo_hi.items())
        for nums, need in self.cov:
            v += max(0, need - sum(C[n] > 0 for n in nums))
        if self.mr:
            nums, each, k = self.mr
            v += max(0, k - sum(C[n] >= each for n in nums)) * each
        cnt = {}
        for j in chosen:
            for key, val in self.attrs[j].items():
                cnt[key, val] = cnt.get((key, val), 0) + 1
        zp = cnt.get(("no_pair", True), 0)
        v += max(0, self.zp[0] - zp) + max(0, zp - self.zp[1])
        for fam, key, lo, hi in self.bands:
            k = cnt.get((fam, key), 0)
            v += max(0, lo - k) + max(0, k - hi)
        masks = [self.mask[j] for j in chosen]
        for i in range(len(masks)):
            for k in range(i + 1, len(masks)):
                v += max(0, bin(masks[i] & masks[k]).count("1") - self.mc) * 10
        err = sum(abs(cnt.get((key, val), 0) - t) for key, tg in self.targets.items() for val, t in tg.items())
        return v, err


def construct(cfg, a, seed, pool_size=6000, iters=4000):
    """시드로 정해지는 출발 포트폴리오 (세트 목록) 와 위반량."""
    rng = random.Random(seed)
    S = cfg["portfolio"]["sets"]
    pool, attrs = sample_pool(cfg, a, rng, pool_size)
    if len(pool) < S:
        return None, None
    st = _State(cfg, a, pool, attrs, S)
    chosen = rng.sample(range(len(pool)), S)
    cur = st.score(chosen)
    for _ in range(iters):
        i = rng.randrange(S)
        j = rng.randrange(len(pool))
        if j in chosen:
            continue
        old = chosen[i]
        chosen[i] = j
        new = st.score(chosen)
        if new <= cur:
            cur = new
        else:
            chosen[i] = old
    return sorted(list(pool[j]) for j in chosen), cur
