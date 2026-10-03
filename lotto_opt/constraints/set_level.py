"""개별 세트 제약. 각 세트 s에 대해 x[s,n]=1 이면 번호 n 포함."""
ZONES = [range(1, 11), range(11, 21), range(21, 31), range(31, 41), range(41, 46)]
NUMS = range(1, 46)


def count(x, s, group):
    return sum(x[s, n] for n in group)


def indicator_eq(m, expr, v):
    b = m.NewBoolVar("")
    m.Add(expr == v).OnlyEnforceIf(b)
    m.Add(expr != v).OnlyEnforceIf(b.Not())
    return b


def add(ctx, s):
    m, x, R, a = ctx.m, ctx.x, ctx.rules, ctx.a
    m.Add(count(x, s, NUMS) == 6)

    # 그룹 구성
    gm = R["group_mix"]
    h, w, c = count(x, s, a.hot), count(x, s, a.warm), count(x, s, a.cold)
    for expr, key in ((h, "hot"), (w, "warm"), (c, "cold")):
        m.Add(expr >= gm[key][0]); m.Add(expr <= gm[key][1])
    if gm.get("combos"):
        picks = []
        for hh, ww, cc in gm["combos"]:
            b = m.NewBoolVar("")
            m.Add(h == hh).OnlyEnforceIf(b); m.Add(w == ww).OnlyEnforceIf(b); m.Add(c == cc).OnlyEnforceIf(b)
            picks.append(b)
        m.AddExactlyOne(picks)
    ctx.group_count[s] = {"hot": h, "warm": w, "cold": c}

    # 이월수
    co = count(x, s, a.carry)
    lo, hi = R["carry_over"]["per_set"]
    m.Add(co >= lo); m.Add(co <= hi)
    ctx.carry_count[s] = co

    # 합계
    total = sum(n * x[s, n] for n in NUMS)
    m.Add(total >= R["sum_range"][0]); m.Add(total <= R["sum_range"][1])
    ctx.total[s] = total

    # 연속수
    run = R["consecutive"]["max_run"]
    for n in range(1, 46 - run):
        m.Add(sum(x[s, n + k] for k in range(run + 1)) <= run)
    pairs = []
    for n in range(1, 45):
        p = m.NewBoolVar("")
        m.AddBoolOr([x[s, n].Not(), x[s, n + 1].Not(), p])
        m.AddImplication(p, x[s, n]); m.AddImplication(p, x[s, n + 1])
        pairs.append(p)
    m.Add(sum(pairs) <= R["consecutive"]["max_pairs"])
    ctx.no_pair[s] = indicator_eq(m, sum(pairs), 0)

    # AC값: 서로 다른 차이값 개수 - 5 >= ac_min
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

    # 홀짝 / 저고
    odd = count(x, s, [n for n in NUMS if n % 2])
    low = count(x, s, [n for n in NUMS if n <= 22])
    m.Add(odd >= R["odd_count"][0]); m.Add(odd <= R["odd_count"][1])
    m.Add(low >= R["low_count"][0]); m.Add(low <= R["low_count"][1])
    ctx.odd[s], ctx.low[s] = odd, low
