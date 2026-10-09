"""전역(포트폴리오) 제약."""
import math
from ..stats import OE_BUCKETS, LH_BUCKETS
from .set_level import NUMS, onehot


def bucket_totals(ctx, attr, buckets):
    """버킷별 해당 세트 수(불리언 합)."""
    cat = ctx.cat[attr]
    return {key: sum(cat[s][v] for s in ctx.sets for v in vals if v in cat[s]) for key, vals in buckets.items()}


def add(ctx):
    m, x, R, a, S = ctx.m, ctx.x, ctx.rules, ctx.a, ctx.S

    # 번호별 출현 횟수 (분산 목적을 위해 횟수도 원-핫으로 둔다)
    C = {n: sum(x[s, n] for s in ctx.sets) for n in NUMS}
    ctx.appear = C
    bounds = {n: list(R["appearance"]["hot_top" if n in a.top else "general"]) for n in NUMS}
    lo, hi = R["carry_over"]["per_number_uses"]
    for n in a.carry:
        bounds[n] = [max(bounds[n][0], lo), min(bounds[n][1], hi)]
    for n in NUMS:
        lo, hi = max(bounds[n][0], 0), min(bounds[n][1], S)
        m.Add(C[n] >= lo); m.Add(C[n] <= hi)
        if lo <= hi:
            ctx.appear_onehot[n] = onehot(m, C[n], range(lo, hi + 1))

    # 커버리지 (cov[n]=1 이려면 한 번 이상 나와야 함)
    cov = {n: m.NewBoolVar("") for n in NUMS}
    for n in NUMS:
        m.Add(cov[n] <= C[n])
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
    ctx.oe_tot = bucket_totals(ctx, "odd", OE_BUCKETS)
    ctx.lh_tot = bucket_totals(ctx, "low", LH_BUCKETS)
    for name, tot in (("odd_even", ctx.oe_tot), ("low_high", ctx.lh_tot)):
        for key, (blo, bhi) in (R.get("bands") or {}).get(name, {}).items():
            m.Add(tot[key] >= math.ceil(blo * S)); m.Add(tot[key] <= math.floor(bhi * S))

    # 세트 간 교집합: w = 두 세트에 모두 있는 번호 (상한만 필요하므로 '둘 다 있으면 w=1'만 건다)
    # 한쪽이 고정 세트면 그 세트 번호들에서 다른 쪽 x 의 합이 곧 교집합이고, 둘 다 고정이면 상수다.
    mc = R["overlap"]["max_common"]
    fixed = ctx.fixed
    ctx.pair_common = []
    for s in ctx.sets:
        for t in range(s + 1, S):
            if s in fixed and t in fixed:
                c = len(set(fixed[s]) & set(fixed[t]))
            elif s in fixed or t in fixed:
                f, v = (s, t) if s in fixed else (t, s)
                c = sum(x[v, n] for n in fixed[f])
                m.Add(c <= mc)
            else:
                ws = []
                for n in NUMS:
                    w = m.NewBoolVar("")
                    m.AddBoolOr([x[s, n].Not(), x[t, n].Not(), w])
                    ws.append(w)
                c = sum(ws)
                m.Add(c <= mc)
            ctx.pair_common.append(c)

    # 대칭 제거: 세트를 고정 순서로 정렬 (옵션, 기본 꺼짐: 첫 해 탐색이 크게 느려짐)
    if R.get("symmetry_breaking", False) and not fixed:
        key = [sum((46 - n) ** 2 * x[s, n] for n in NUMS) for s in ctx.sets]
        for s in range(S - 1):
            m.Add(key[s] >= key[s + 1])
