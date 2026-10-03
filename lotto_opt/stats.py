"""가중 빈도, 그룹 분류, 목표 분포 자동 산출."""
from dataclasses import dataclass, field

NUMS = range(1, 46)
OE_BUCKETS = {"4:2": [4], "3:3": [3], "2:4": [2], "other": [0, 1, 5, 6]}
LH_BUCKETS = {"3:3": [3], "4:2": [4], "2:4": [2], "other": [0, 1, 5, 6]}


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
    targets: dict = field(default_factory=dict)
    observed: dict = field(default_factory=dict)


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
                 rank[:W["hot_top"]], long_absent, draws[-1]["numbers"], last_seen)

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
    }
    a.targets = _targets(cfg, a, draws, sums)
    return a


def _clip(dist, lo, hi):
    d = {k: v for k, v in dist.items() if lo <= k <= hi}
    s = sum(d.values()) or 1
    return {k: v / s for k, v in d.items()}


def _targets(cfg, a, draws, sums):
    T, R = cfg["targets"], cfg["rules"]
    out = {}
    out["odd_even"] = a.observed["odd_even"] if T.get("odd_even") == "auto" else T.get("odd_even")
    out["low_high"] = a.observed["low_high"] if T.get("low_high") == "auto" else T.get("low_high")
    if T.get("carry") == "auto":
        out["carry"] = _clip(a.observed["carry"], *R["carry_over"]["per_set"])
    else:
        out["carry"] = T.get("carry")
    if T.get("group_mix") == "auto":
        # 주의: 현재 그룹을 같은 100회에 대입한 값이라 표본 내(in-sample) 추정치다.
        gm = {}
        for name, grp in (("hot", a.hot), ("warm", a.warm), ("cold", a.cold)):
            counts = [sum(n in grp for n in d["numbers"]) for d in draws]
            dist = {k: counts.count(k) / len(counts) for k in range(7)}
            gm[name] = _clip(dist, *R["group_mix"][name])
        out["group_mix"] = gm
    else:
        out["group_mix"] = T.get("group_mix")
    if T.get("sum_bins") == "auto":
        lo, hi = R["sum_range"]
        inrange = [s for s in sums if lo <= s <= hi]
        q = [inrange[int(len(inrange) * i / 5)] for i in range(1, 5)]
        edges = [lo] + q + [hi + 1]
        out["sum_bins"] = {(edges[i], edges[i + 1] - 1): 0.2 for i in range(5)}
    else:
        out["sum_bins"] = T.get("sum_bins")
    return out
