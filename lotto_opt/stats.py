"""가중 빈도, 그룹 분류, 목표 분포 자동 산출."""
from collections import Counter
from dataclasses import dataclass, field

from .constraints.set_level import group_combos

NUMS = range(1, 46)
OE_BUCKETS = {"4:2": [4], "3:3": [3], "2:4": [2], "other": [0, 1, 5, 6]}
LH_BUCKETS = {"3:3": [3], "4:2": [4], "2:4": [2], "other": [0, 1, 5, 6]}

# 기획서에 적힌 고정 목표값. targets.<항목>: spec 으로 고른다.
SPEC_TARGETS = {
    "odd_even": {"4:2": 0.36, "3:3": 0.33, "2:4": 0.24, "other": 0.07},
    "low_high": {"3:3": 0.35, "4:2": 0.35, "2:4": 0.25, "other": 0.05},
    "carry": {0: 0.30, 1: 0.55, 2: 0.15},
}


@dataclass
class Analysis:
    first: int
    last: int
    weight: dict
    rank: list
    hot: list
    warm: list
    cold: list
    top: list
    long_absent: list
    carry: list
    last_seen: dict
    last_date: str = ""
    targets: dict = field(default_factory=dict)
    observed: dict = field(default_factory=dict)

    def __post_init__(self):
        self.hot_set, self.warm_set, self.carry_set = set(self.hot), set(self.warm), set(self.carry)


def _dist(values, buckets):
    total = len(values)
    return {k: sum(v in vs for v in values) / total for k, vs in buckets.items()}


def analyze(all_draws, cfg):
    W = cfg["weighting"]
    draws = all_draws[-cfg["data"]["window"]:]
    recent = draws[-W["recent_window"]:]
    older = draws[:-W["recent_window"]]
    c_recent = {n: sum(n in d["numbers"] for d in recent) for n in NUMS}
    c_older = {n: sum(n in d["numbers"] for d in older) for n in NUMS}
    last_seen = {n: max((d["draw_no"] for d in draws if n in d["numbers"]), default=0) for n in NUMS}
    weight = {n: W["recent_weight"] * c_recent[n] + W["base_weight"] * c_older[n] for n in NUMS}

    def ranked(w):
        # 동률: 최근 출현 다빈도 > 최근 출현 회차 최신 > 번호 오름차순
        return sorted(NUMS, key=lambda n: (-w[n], -c_recent[n], -last_seen[n], n))

    g = W["groups"]
    rank = ranked(weight)
    cold = rank[g["hot"] + g["warm"]:]
    long_absent = sorted(cold, key=lambda n: (last_seen[n], n))[:cfg["rules"]["mean_reversion"].get("candidates", 5)]
    mr = cfg["rules"]["mean_reversion"]
    if mr.get("mode") == "weight":  # 원본: 보정치를 더한 뒤 그룹 재산정
        weight = {n: weight[n] + (mr.get("bonus", 0.2) if n in long_absent else 0) for n in NUMS}
        rank = ranked(weight)
    hot, warm, cold = rank[:g["hot"]], rank[g["hot"]:g["hot"] + g["warm"]], rank[g["hot"] + g["warm"]:]

    a = Analysis(draws[0]["draw_no"], draws[-1]["draw_no"], weight, rank, hot, warm, cold,
                 rank[:W["hot_top"]], long_absent, sorted(draws[-1]["numbers"]), last_seen,
                 str(draws[-1].get("date", ""))[:10])

    sums = sorted(sum(d["numbers"]) for d in draws)
    odd = [sum(n % 2 for n in d["numbers"]) for d in draws]
    low = [sum(n <= 22 for n in d["numbers"]) for d in draws]
    carry = [len(set(a_["numbers"]) & set(b["numbers"])) for a_, b in zip(draws, draws[1:])]
    a.observed = {
        "sum_mean": sum(sums) / len(sums),
        "odd_even": _dist(odd, OE_BUCKETS),
        "low_high": _dist(low, LH_BUCKETS),
        "carry": {k: carry.count(k) / len(carry) for k in sorted(set(carry))},
        "no_consecutive": sum(all(d["numbers"][i + 1] - d["numbers"][i] > 1 for i in range(5)) for d in draws) / len(draws),
        "combo": dict(Counter(tuple(sum(n in grp for n in d["numbers"]) for grp in (hot, warm, cold)) for d in draws)),
    }
    a.targets = _targets(cfg, a, sums)
    return a


def _clip(dist, keys):
    """dist 를 keys 에 해당하는 값만 남기고 합이 1이 되도록 다시 나눈다."""
    d = {k: dist.get(k, 0) for k in keys}
    s = sum(d.values())
    return {k: v / s for k, v in d.items()} if s else None


def combo_key(k):
    """그룹 구성 키 (h, w, c) ↔ 'h-w-c' 문자열."""
    return tuple(int(v) for v in k.split("-")) if isinstance(k, str) else tuple(k)


def _pick(T, name, observed):
    """auto(실측) | spec(기획서 값) | 숫자 분포 | 없음(null)."""
    v = T.get(name)
    if v == "auto":
        return observed
    if v == "spec":
        return SPEC_TARGETS[name]
    return v


def _targets(cfg, a, sums):
    T, R = cfg["targets"], cfg["rules"]
    out = {"odd_even": _pick(T, "odd_even", a.observed["odd_even"]),
           "low_high": _pick(T, "low_high", a.observed["low_high"])}
    lo, hi = R["carry_over"]["per_set"]
    carry = _pick(T, "carry", a.observed["carry"])
    out["carry"] = _clip({int(k): v for k, v in carry.items()}, range(lo, hi + 1)) if carry else None

    # 그룹 구성: 세트 하나의 (Hot, Warm, Cold) 개수 조합 분포.
    # auto 는 현재 그룹을 같은 회차들에 대입한 표본 내(in-sample) 추정치다.
    allowed = group_combos(R["group_mix"])
    gm = T.get("group_mix")
    if gm == "auto":
        out["group_mix"] = _clip(a.observed["combo"], allowed)
    elif gm:
        out["group_mix"] = _clip({combo_key(k): v for k, v in gm.items()}, allowed)
    else:
        out["group_mix"] = None

    # 합계: 범위 안 과거 합계를 5분위로 나눈 구간마다 실제 비율(약 20%)을 목표로
    sb = T.get("sum_bins")
    if sb == "auto":
        lo, hi = R["sum_range"]
        inrange = [s for s in sums if lo <= s <= hi]
        cuts = sorted({inrange[len(inrange) * i // 5] for i in range(1, 5)} - {lo}) if inrange else []
        edges = [lo] + cuts + [hi + 1]
        bins = [(edges[i], edges[i + 1] - 1) for i in range(len(edges) - 1)]
        out["sum_bins"] = {b: sum(b[0] <= s <= b[1] for s in inrange) / len(inrange) for b in bins} if inrange else None
    elif sb:
        out["sum_bins"] = {tuple(k) if not isinstance(k, str) else tuple(int(v) for v in k.split("-")): p for k, p in sb.items()}
    else:
        out["sum_bins"] = None
    return out
