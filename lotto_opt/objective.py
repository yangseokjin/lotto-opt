"""사전식 목적함수 단계. 각 함수는 최소화할 정수식을 반환한다."""
from .constraints.set_level import indicator_eq, NUMS


def _abs_dev(ctx, total, share):
    e = ctx.m.NewIntVar(0, 100 * ctx.S, "")
    ctx.m.AddAbsEquality(e, 100 * total - round(100 * ctx.S * share))
    return e


def distribution_error(ctx):
    """목표 분포와의 오차 합 (단위: 세트수×100). 홀짝·저고·이월수·그룹구성·합계구간."""
    m, T, terms = ctx.m, ctx.a.targets, []
    for tgt, tot in ((T.get("odd_even"), ctx.oe_tot), (T.get("low_high"), ctx.lh_tot)):
        if tgt:
            terms += [_abs_dev(ctx, tot[k], p) for k, p in tgt.items()]
    if T.get("carry"):
        for k, p in T["carry"].items():
            terms.append(_abs_dev(ctx, sum(indicator_eq(m, ctx.carry_count[s], int(k)) for s in ctx.sets), p))
    if T.get("group_mix"):
        for g, dist in T["group_mix"].items():
            for k, p in dist.items():
                terms.append(_abs_dev(ctx, sum(indicator_eq(m, ctx.group_count[s][g], int(k)) for s in ctx.sets), p))
    if T.get("sum_bins"):
        bins = list(T["sum_bins"].items())
        member = {}
        for s in ctx.sets:
            row = []
            for i, ((lo, hi), _) in enumerate(bins):
                b = m.NewBoolVar("")
                m.Add(ctx.total[s] >= lo).OnlyEnforceIf(b); m.Add(ctx.total[s] <= hi).OnlyEnforceIf(b)
                member[s, i] = b; row.append(b)
            m.AddExactlyOne(row)
        for i, (_, p) in enumerate(bins):
            terms.append(_abs_dev(ctx, sum(member[s, i] for s in ctx.sets), p))
    return sum(terms)


def overlap(ctx):
    """교집합 3개 쌍 수 + 100 × 교집합 4개 쌍 수."""
    pen = []
    for c in ctx.pair_common:
        b3 = ctx.m.NewBoolVar(""); ctx.m.Add(c <= 2).OnlyEnforceIf(b3.Not()); pen.append(b3)
        b4 = ctx.m.NewBoolVar(""); ctx.m.Add(c <= 3).OnlyEnforceIf(b4.Not()); pen.append(100 * b4)
    return sum(pen)


def appearance_spread(ctx):
    """10 × (번호별 출현 최대-최소) + (이월수별 사용 최대-최소)."""
    m, C = ctx.m, ctx.appear
    def spread(nums):
        hi, lo = m.NewIntVar(0, ctx.S, ""), m.NewIntVar(0, ctx.S, "")
        m.AddMaxEquality(hi, [C[n] for n in nums]); m.AddMinEquality(lo, [C[n] for n in nums])
        return hi - lo
    return 10 * spread(list(NUMS)) + spread(ctx.a.carry)


STAGES = {"distribution_error": distribution_error, "overlap": overlap, "appearance_spread": appearance_spread}
