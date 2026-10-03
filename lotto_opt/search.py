"""빠른 지역 탐색 (파이썬, 결정적).

세트 하나의 번호 하나를 바꾸거나, 두 세트가 번호를 맞바꾸는 작은 이동을 수만 번 시도한다.
이동마다 개별 제약(pool.set_attrs)과 전역 제약을 증분 계산으로 확인하고, 앞 단계 값은 나빠지지 않으면서
지금 단계 값이 좋아지는(또는 같은) 이동만 받아들인다. CP-SAT 이웃 탐색 앞에서 넓고 빠르게 다듬는 역할이다.
"""
import math
from collections import Counter

from . import pool
from .constraints.set_level import group_combos
from .objective import _families, _overlap_weights, _target_units

NUMS = range(1, 46)
_FAM_ATTR = {"odd_even": "odd_even", "low_high": "low_high", "carry": "carry", "group_mix": "combo", "sum_bins": "sum_bin"}


class Portfolio:
    def __init__(self, sets, cfg, a):
        R = cfg["rules"]
        self.R, self.a, self.S = R, a, len(sets)
        self.combos = set(group_combos(R["group_mix"]))
        self.bins = list(a.targets["sum_bins"]) if a.targets.get("sum_bins") else None
        self.sets = [tuple(s) for s in sets]
        self.mask = [sum(1 << n for n in s) for s in self.sets]
        self.attrs = [pool.set_attrs(s, R, a, self.combos, self.bins) for s in self.sets]
        self.C = Counter(n for s in self.sets for n in s)
        lo_hi = {n: list(R["appearance"]["hot_top" if n in a.top else "general"]) for n in NUMS}
        cu = R["carry_over"]["per_number_uses"]
        for n in a.carry:
            lo_hi[n] = [max(lo_hi[n][0], cu[0]), min(lo_hi[n][1], cu[1])]
        self.lo_hi = lo_hi
        cv = R["coverage"]
        self.cov_groups = [(None, cv["total"])] + [(set(getattr(a, g)), cv[g]) for g in ("hot", "warm", "cold")]
        mr = R["mean_reversion"]
        self.mr = (set(a.long_absent), mr["min_sets_each"], mr["min_numbers"]) if mr.get("mode") == "forced" else None
        z = R["consecutive"]["zero_pair_share"]
        self.zp = (math.floor(z[0] * self.S), math.ceil(z[1] * self.S))
        self.bands = [(fam, key, math.ceil(lo * self.S), math.floor(hi * self.S))
                      for fam, d in (R.get("bands") or {}).items() for key, (lo, hi) in d.items()]
        self.mc = R["overlap"]["max_common"]
        self.fams = [(_FAM_ATTR[name], [(k, _target_units(self.S, p)) for k, p in keys])
                     for name, keys in _families(a.targets)]
        self.cnt = Counter((k, v) for at in self.attrs for k, v in at.items())
        self.ov = [[0] * self.S for _ in range(self.S)]
        for i in range(self.S):
            for j in range(i + 1, self.S):
                self.ov[i][j] = self.ov[j][i] = bin(self.mask[i] & self.mask[j]).count("1")
        ov_stage = next((st for st in cfg["objective"] if st["name"] == "overlap"), {})
        self.W = _overlap_weights(self.S, ov_stage.get("start", 2), self.mc)
        self.ge = {k: sum(self.ov[i][j] >= k for i in range(self.S) for j in range(i + 1, self.S)) for k in self.W}
        # 같은 그룹·홀짝·저고·이월수 여부인 번호끼리 바꾸면 세트의 범주(분포 목표)가 그대로 유지된다
        key = lambda n: (n in a.hot_set, n in a.warm_set, n % 2, n <= 22, n in a.carry_set)
        self.same = {n: [m for m in NUMS if m != n and key(m) == key(n)] for n in NUMS}

    # ---- 목적 값 ----
    def dist(self, cnt=None):
        cnt = cnt or self.cnt
        return sum(abs(100 * cnt.get((attr, k), 0) - t) for attr, keys in self.fams for k, t in keys)

    def overlap(self, ge=None):
        ge = ge or self.ge
        return sum(w * ge[k] for k, w in self.W.items())

    def variance(self, C=None):
        C = C or self.C
        uses = [C[n] for n in self.a.carry]
        return (self.S + 1) * sum(C[n] ** 2 for n in NUMS) + max(uses) - min(uses)

    def values(self):
        return {"distribution_error": self.dist(), "overlap": self.overlap(), "appearance_variance": self.variance()}

    # ---- 이동 평가 ----
    def evaluate(self, changes):
        """changes = {세트 번호: 새 세트(tuple)}. 모든 제약을 지키면 (새 목적 값 dict, 적용 정보), 아니면 None."""
        new_attrs = {}
        for s, ns in changes.items():
            at = pool.set_attrs(ns, self.R, self.a, self.combos, self.bins)
            if at is None:
                return None
            new_attrs[s] = at
        C = self.C.copy()
        for s, ns in changes.items():
            for n in self.sets[s]:
                C[n] -= 1
            for n in ns:
                C[n] += 1
        touched = {n for s, ns in changes.items() for n in set(self.sets[s]) ^ set(ns)}
        for n in touched:
            lo, hi = self.lo_hi[n]
            if not lo <= C[n] <= hi:
                return None
        for nums, need in self.cov_groups:
            if sum(C[n] > 0 for n in (nums or NUMS)) < need:
                return None
        if self.mr:
            nums, each, k = self.mr
            if sum(C[n] >= each for n in nums) < k:
                return None
        cnt = self.cnt.copy()
        for s, at in new_attrs.items():
            for k, v in self.attrs[s].items():
                cnt[k, v] -= 1
            for k, v in at.items():
                cnt[k, v] += 1
        zp = cnt.get(("no_pair", True), 0)
        if not self.zp[0] <= zp <= self.zp[1]:
            return None
        for fam, key, lo, hi in self.bands:
            if not lo <= cnt.get((fam, key), 0) <= hi:
                return None
        masks = {s: sum(1 << n for n in ns) for s, ns in changes.items()}
        ge = dict(self.ge)
        newov = {}
        for s, m in masks.items():
            for t in range(self.S):
                if t == s or (t in masks and t < s):
                    continue
                o = bin(m & masks.get(t, self.mask[t])).count("1")
                if o > self.mc:
                    return None
                old = self.ov[s][t]
                for k in ge:
                    ge[k] += (o >= k) - (old >= k)
                newov[s, t] = o
        vals = {"distribution_error": self.dist(cnt), "overlap": self.overlap(ge), "appearance_variance": self.variance(C)}
        return vals, (changes, new_attrs, C, cnt, ge, newov, masks)

    def apply(self, info):
        changes, new_attrs, C, cnt, ge, newov, masks = info
        for s, ns in changes.items():
            self.sets[s], self.attrs[s], self.mask[s] = ns, new_attrs[s], masks[s]
        self.C, self.cnt, self.ge = C, cnt, ge
        for (s, t), o in newov.items():
            self.ov[s][t] = self.ov[t][s] = o


def _focus(pf, name):
    """이동을 집중할 대상: 교집합이 가장 큰 세트 쌍들, 또는 가장 많이 쓰인 번호들."""
    if name == "overlap":
        worst = max(max(row) for row in pf.ov)
        return [(i, j) for i in range(pf.S) for j in range(i + 1, pf.S) if pf.ov[i][j] == worst]
    if name.startswith("appearance"):
        top = max(pf.C[n] for n in NUMS)
        return [n for n in NUMS if pf.C[n] == top]
    return None


def _propose(pf, name, rng, focus):
    """단계에 맞춘 무작위 이동 하나."""
    S = pf.S
    if name == "overlap" and focus and rng.random() < 0.7:
        i, j = rng.choice(focus)
        s = rng.choice((i, j))
        common = sorted(set(pf.sets[i]) & set(pf.sets[j]))
        u = rng.choice(common) if common else rng.choice(pf.sets[s])
    elif name.startswith("appearance") and focus and rng.random() < 0.7:
        u = rng.choice(focus)
        s = rng.choice([i for i in range(S) if u in pf.sets[i]])
    else:
        s = rng.randrange(S)
        u = rng.choice(pf.sets[s])
    if rng.random() < 0.5:  # 두 세트가 번호 맞바꾸기 (출현 횟수 유지)
        t = rng.randrange(S)
        if t != s and u not in pf.sets[t]:
            opts = [v for v in pf.sets[t] if v not in pf.sets[s]]
            if opts:
                v = rng.choice(opts)
                return {s: tuple(sorted([n for n in pf.sets[s] if n != u] + [v])),
                        t: tuple(sorted([n for n in pf.sets[t] if n != v] + [u]))}
    opts = [n for n in pf.same[u] if n not in pf.sets[s]] if rng.random() < 0.6 else []
    if opts and name.startswith("appearance"):
        low = min(pf.C[n] for n in opts)
        opts = [n for n in opts if pf.C[n] == low]
    v = rng.choice(opts or [n for n in NUMS if n not in pf.sets[s]])
    return {s: tuple(sorted([n for n in pf.sets[s] if n != u] + [v]))}


def improve(sets, cfg, a, stage, locks, rng, iters):
    """stage 값을 줄인다. locks = [(단계 설정, 상한)], 이 상한은 지킨다. (세트 목록, 값) 반환."""
    name = stage["name"]
    known = ("distribution_error", "overlap", "appearance_variance")
    if name not in known or any(st["name"] not in known for st, _ in locks):  # 계산할 줄 모르는 단계는 건너뜀
        return sets, None
    pf = Portfolio(sets, cfg, a)
    lock = {st["name"]: v for st, v in locks}
    cur = pf.values()[name]
    focus = _focus(pf, name)
    for _ in range(iters):
        res = pf.evaluate(_propose(pf, name, rng, focus))
        if res is None:
            continue
        vals, info = res
        if any(vals[n] > v for n, v in lock.items() if n in vals):
            continue
        if vals[name] < cur or (vals[name] == cur and rng.random() < 0.3):
            pf.apply(info)
            cur = vals[name]
            focus = _focus(pf, name)
    return [list(s) for s in pf.sets], cur
