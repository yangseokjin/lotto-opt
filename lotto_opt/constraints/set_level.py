"""개별 세트 제약. 각 세트 s에 대해 x[s,n]=1 이면 번호 n 포함.

세트의 범주형 속성(홀수 개수, 저번호 개수, 이월수 개수, 그룹 구성, 합계 구간)은
값마다 불리언 하나를 두는 원-핫 변수로 표현한다(ctx.cat[속성][s] = {값: 불리언}).
전역 분포 집계가 불리언의 단순 합이 되어, 조건부 등식으로 셀 때보다 솔버의 하한이 훨씬 강하다.

고정된 세트(이웃 탐색에서 바꾸지 않는 세트)는 add_fixed 로 같은 자리에 상수(0/1)를 넣는다.
그래서 전역 제약과 목적함수 코드는 세트가 변수인지 상수인지 구분하지 않아도 된다.
"""
import itertools

ZONES = [range(1, 11), range(11, 21), range(21, 31), range(31, 41), range(41, 46)]
NUMS = range(1, 46)
ODD = [n for n in NUMS if n % 2]
LOW = [n for n in NUMS if n <= 22]


def count(x, s, group):
    return sum(x[s, n] for n in group)


def onehot(m, expr, values):
    """expr 의 값을 values 중 하나로 고정하는 원-핫 불리언 {값: 불리언}."""
    b = {v: m.NewBoolVar("") for v in values}
    m.AddExactlyOne(b.values())
    m.Add(sum(v * bv for v, bv in b.items()) == expr)
    return b


def group_combos(gm):
    """허용되는 (Hot, Warm, Cold) 개수 조합. combos 가 있으면 그 목록, 없으면 범위 안의 모든 조합."""
    if gm.get("combos"):
        return [tuple(c) for c in gm["combos"]]
    rng = lambda k: range(gm[k][0], gm[k][1] + 1)
    return [(h, w, c) for h, w, c in itertools.product(rng("hot"), rng("warm"), rng("cold")) if h + w + c == 6]


def sum_bins(ctx):
    """합계 목표 구간 [(lo, hi), ...] 또는 None."""
    bins = ctx.a.targets.get("sum_bins")
    return list(bins) if bins else None


def add(ctx, s):
    m, x, R, a = ctx.m, ctx.x, ctx.rules, ctx.a
    m.Add(count(x, s, NUMS) == 6)

    # 그룹 구성: (Hot, Warm, Cold) 조합 하나를 고른다
    h, w, c = count(x, s, a.hot), count(x, s, a.warm), count(x, s, a.cold)
    combo = {k: m.NewBoolVar("") for k in group_combos(R["group_mix"])}
    m.AddExactlyOne(combo.values())
    for i, expr in enumerate((h, w, c)):
        m.Add(sum(k[i] * b for k, b in combo.items()) == expr)
    ctx.cat["combo"][s] = combo

    # 이월수 개수
    lo, hi = R["carry_over"]["per_set"]
    ctx.cat["carry"][s] = onehot(m, count(x, s, a.carry), range(lo, hi + 1))

    # 합계: 범위 + (목표가 있으면) 구간 원-핫
    total = sum(n * x[s, n] for n in NUMS)
    m.Add(total >= R["sum_range"][0]); m.Add(total <= R["sum_range"][1])
    bins = sum_bins(ctx)
    if bins:
        sb = {i: m.NewBoolVar("") for i in range(len(bins))}
        m.AddExactlyOne(sb.values())
        m.Add(total >= sum(bins[i][0] * b for i, b in sb.items()))
        m.Add(total <= sum(bins[i][1] * b for i, b in sb.items()))
        ctx.cat["sum_bin"][s] = sb
    ctx.total[s] = total

    # 연속수: run+1 개 연속 금지, 연속 쌍 개수 제한, 0쌍 여부
    run = R["consecutive"]["max_run"]
    for n in range(1, 46 - run):
        m.Add(sum(x[s, n + k] for k in range(run + 1)) <= run)
    pairs = []
    for n in range(1, 45):
        p = m.NewBoolVar("")  # p = x[s,n] AND x[s,n+1]
        m.AddBoolOr([x[s, n].Not(), x[s, n + 1].Not(), p])
        m.AddImplication(p, x[s, n]); m.AddImplication(p, x[s, n + 1])
        pairs.append(p)
    max_pairs = R["consecutive"]["max_pairs"]
    m.Add(sum(pairs) <= max_pairs)
    no_pair = m.NewBoolVar("")
    if max_pairs == 1:
        m.Add(no_pair + sum(pairs) == 1)
    else:
        m.Add(sum(pairs) == 0).OnlyEnforceIf(no_pair)
        m.Add(sum(pairs) >= 1).OnlyEnforceIf(no_pair.Not())
    ctx.no_pair[s] = no_pair

    # AC값: 서로 다른 차이값 개수 - 5 >= ac_min (차이 k가 '있다'고 셀 때는 그 차이를 만드는 두 번호가 있어야 함)
    diffs = []
    for k in range(1, 45):
        ys = []
        for n in range(1, 46 - k):
            y = m.NewBoolVar("")
            m.AddImplication(y, x[s, n]); m.AddImplication(y, x[s, n + k])
            ys.append(y)
        d = m.NewBoolVar("")
        m.Add(d <= sum(ys))
        diffs.append(d)
    m.Add(sum(diffs) >= R["ac_min"] + 5)

    # 구간 분산
    used = []
    for z in ZONES:
        cz = count(x, s, z)
        m.Add(cz <= R["zones"]["max_per_zone"])
        b = m.NewBoolVar(""); m.Add(b <= cz); used.append(b)
    m.Add(sum(used) >= R["zones"]["min_zones"])

    # 홀수 / 저번호 개수
    ctx.cat["odd"][s] = onehot(m, count(x, s, ODD), range(R["odd_count"][0], R["odd_count"][1] + 1))
    ctx.cat["low"][s] = onehot(m, count(x, s, LOW), range(R["low_count"][0], R["low_count"][1] + 1))


def add_fixed(ctx, s, nums):
    """고정 세트 s(번호 목록 nums)의 속성을 상수로 채운다. 개별 제약은 이미 지킨 세트라고 본다."""
    a = ctx.a
    combo = (sum(n in a.hot for n in nums), sum(n in a.warm for n in nums), sum(n in a.cold for n in nums))
    ctx.cat["combo"][s] = {combo: 1}
    ctx.cat["carry"][s] = {sum(n in a.carry for n in nums): 1}
    total = sum(nums)
    bins = sum_bins(ctx)
    if bins:
        ctx.cat["sum_bin"][s] = {i: 1 for i, (lo, hi) in enumerate(bins) if lo <= total <= hi}
    ctx.total[s] = total
    ctx.no_pair[s] = int(all(b - a_ > 1 for a_, b in zip(nums, nums[1:])))
    ctx.cat["odd"][s] = {sum(n % 2 for n in nums): 1}
    ctx.cat["low"][s] = {sum(n <= 22 for n in nums): 1}
