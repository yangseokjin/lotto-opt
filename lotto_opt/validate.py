"""솔버와 독립된 검증기. 같은 규칙을 순수 파이썬으로 다시 검사한다."""
import itertools
import math
from .constraints.set_level import ZONES

NUMS = range(1, 46)


def ac(s):
    return len({abs(a - b) for a, b in itertools.combinations(s, 2)}) - 5


def set_violations(s, R, a):
    v = []
    gm = R["group_mix"]
    h, w, c = (sum(n in g for n in s) for g in (a.hot, a.warm, a.cold))
    if len(set(s)) != 6 or not all(1 <= n <= 45 for n in s): v.append("구성")
    for cnt, key in ((h, "hot"), (w, "warm"), (c, "cold")):
        if not gm[key][0] <= cnt <= gm[key][1]: v.append(f"그룹 {key}")
    if gm.get("combos") and [h, w, c] not in gm["combos"]: v.append("그룹 조합")
    co = sum(n in a.carry for n in s)
    if not R["carry_over"]["per_set"][0] <= co <= R["carry_over"]["per_set"][1]: v.append("이월수")
    if not R["sum_range"][0] <= sum(s) <= R["sum_range"][1]: v.append("합계")
    run, best = 1, 1
    for i in range(5):
        run = run + 1 if s[i + 1] - s[i] == 1 else 1
        best = max(best, run)
    if best > R["consecutive"]["max_run"]: v.append("연속 길이")
    if sum(s[i + 1] - s[i] == 1 for i in range(5)) > R["consecutive"]["max_pairs"]: v.append("연속 쌍")
    if ac(s) < R["ac_min"]: v.append("AC")
    zc = [sum(n in z for n in s) for z in ZONES]
    if sum(z > 0 for z in zc) < R["zones"]["min_zones"] or max(zc) > R["zones"]["max_per_zone"]: v.append("구간")
    odd, low = sum(n % 2 for n in s), sum(n <= 22 for n in s)
    if not R["odd_count"][0] <= odd <= R["odd_count"][1]: v.append("홀수 개수")
    if not R["low_count"][0] <= low <= R["low_count"][1]: v.append("저번호 개수")
    return v


def global_violations(sets, R, a):
    v, S = [], len(sets)
    C = {n: sum(n in s for s in sets) for n in NUMS}
    for n in NUMS:
        lo, hi = R["appearance"]["hot_top" if n in a.top else "general"]
        if not lo <= C[n] <= hi: v.append(f"출현 횟수 {n}")
    lo, hi = R["carry_over"]["per_number_uses"]
    v += [f"이월수 사용 {n}" for n in a.carry if not lo <= C[n] <= hi]
    cv = R["coverage"]
    if sum(C[n] > 0 for n in NUMS) < cv["total"]: v.append("커버리지 전체")
    for g in ("hot", "warm", "cold"):
        if sum(C[n] > 0 for n in getattr(a, g)) < cv[g]: v.append(f"커버리지 {g}")
    mr = R["mean_reversion"]
    if mr.get("mode") == "forced" and sum(C[n] >= mr["min_sets_each"] for n in a.long_absent) < mr["min_numbers"]:
        v.append("평균회귀 강제 포함")
    zp = sum(all(s[i + 1] - s[i] > 1 for i in range(5)) for s in sets)
    lo, hi = R["consecutive"]["zero_pair_share"]
    if not math.floor(lo * S) <= zp <= math.ceil(hi * S): v.append("연속수 0쌍 비율")
    from .stats import OE_BUCKETS, LH_BUCKETS
    for name, buckets, f in (("odd_even", OE_BUCKETS, lambda s: sum(n % 2 for n in s)),
                             ("low_high", LH_BUCKETS, lambda s: sum(n <= 22 for n in s))):
        for key, (blo, bhi) in R.get("bands", {}).get(name, {}).items():
            k = sum(f(s) in buckets[key] for s in sets)
            if not math.ceil(blo * S) <= k <= math.floor(bhi * S): v.append(f"밴드 {name} {key}")
    if max(len(set(p) & set(q)) for p, q in itertools.combinations(sets, 2)) > R["overlap"]["max_common"]:
        v.append("교집합")
    return v


def validate(sets, cfg, a):
    R = cfg["rules"]
    per_set = {i + 1: set_violations(s, R, a) for i, s in enumerate(sets)}
    return {"sets": {k: x for k, x in per_set.items() if x}, "global": global_violations(sets, R, a)}
