"""전역(포트폴리오) 제약."""
import math
from ..stats import OE_BUCKETS, LH_BUCKETS
from .set_level import indicator_eq, NUMS


def bucket_totals(ctx, expr_by_set, buckets):
    """버킷별 해당 세트 수(정수식)."""
    out = {}
    for key, vals in buckets.items():
        out[key] = sum(indicator_eq(ctx.m, expr_by_set[s], v) for s in ctx.sets for v in vals)
    return out


def add(ctx):
    m, x, R, a, S = ctx.m, ctx.x, ctx.rules, ctx.a, ctx.S

    # 번호별 출현 횟수
    C = {n: sum(x[s, n] for s in ctx.sets) for n in NUMS}
    ctx.appear = C
    for n in NUMS:
        lo, hi = R["appearance"]["hot_top" if n in a.top else "general"]
        m.Add(C[n] >= lo); m.Add(C[n] <= hi)
    lo, hi = R["carry_over"]["per_number_uses"]
    for n in a.carry:
        m.Add(C[n] >= lo); m.Add(C[n] <= hi)

    # 커버리지
    cov = {n: m.NewBoolVar("") for n in NUMS}
    for n in NUMS:
        m.Add(C[n] >= 1).OnlyEnforceIf(cov[n]); m.Add(C[n] == 0).OnlyEnforceIf(cov[n].Not())
    cv = R["coverage"]
    m.Add(sum(cov.values()) >= cv["total"])
    for g in ("hot", "warm", "cold"):
        m.Add(sum(cov[n] for n in getattr(a, g)) >= cv[g])

    # 평균회귀 강제 포함
    mr = R["mean_reversion"]
    if mr.get("mode") == "forced":
        f = []
        for n in a.long_absent:
            b = m.NewBoolVar(""); m.Add(C[n] >= mr["min_sets_each"]).OnlyEnforceIf(b); f.append(b)
        m.Add(sum(f) >= mr["min_numbers"])

    # 연속수 0쌍 세트 비율
    lo, hi = R["consecutive"]["zero_pair_share"]
    zp = sum(ctx.no_pair.values())
    m.Add(zp >= math.floor(lo * S)); m.Add(zp <= math.ceil(hi * S))

    # 홀짝/저고 버킷 집계 + 하드 밴드
    ctx.oe_tot = bucket_totals(ctx, ctx.odd, OE_BUCKETS)
    ctx.lh_tot = bucket_totals(ctx, ctx.low, LH_BUCKETS)
    for name, tot in (("odd_even", ctx.oe_tot), ("low_high", ctx.lh_tot)):
        for key, (blo, bhi) in R.get("bands", {}).get(name, {}).items():
            m.Add(tot[key] >= math.ceil(blo * S)); m.Add(tot[key] <= math.floor(bhi * S))

    # 세트 간 교집합
    mc = R["overlap"]["max_common"]
    ctx.pair_common = []
    for s in ctx.sets:
        for t in range(s + 1, S):
            ws = []
            for n in NUMS:
                w = m.NewBoolVar("")  # w = x[s,n] AND x[t,n] (선형 표현)
                m.AddBoolOr([x[s, n].Not(), x[t, n].Not(), w])
                m.AddImplication(w, x[s, n]); m.AddImplication(w, x[t, n])
                ws.append(w)
            m.Add(sum(ws) <= mc)
            ctx.pair_common.append(sum(ws))

    # 대칭 제거: 세트를 고정 순서로 정렬 (옵션)
    if R.get("symmetry_breaking", False):
        key = [sum((46 - n) ** 2 * x[s, n] for n in NUMS) for s in ctx.sets]
        for s in range(S - 1):
            m.Add(key[s] >= key[s + 1])
