"""결과 리포트 (지정 출력 형식 + JSON)."""
import itertools
import json
import os
import statistics

from .stats import OE_BUCKETS, LH_BUCKETS
from .validate import ac

NUMS = range(1, 46)
f2 = lambda L: ", ".join(f"{n:02d}" for n in L)


def _bucket(v, buckets):
    return next(k for k, vs in buckets.items() if v in vs)


def _label(k):
    return "기타" if k == "other" else k


def summary(sets, a, cfg):
    S = len(sets)
    C = {n: sum(n in s for s in sets) for n in NUMS}
    inter = [len(set(p) & set(q)) for p, q in itertools.combinations(sets, 2)]
    oe = {k: sum(_bucket(sum(n % 2 for n in s), OE_BUCKETS) == k for s in sets) for k in OE_BUCKETS}
    lh = {k: sum(_bucket(sum(n <= 22 for n in s), LH_BUCKETS) == k for s in sets) for k in LH_BUCKETS}
    hot = [sum(n in a.hot for n in s) for s in sets]
    return {
        "sets": S, "odd_even": oe, "low_high": lh,
        "carry": {k: sum(sum(n in a.carry for n in s) == k for s in sets) for k in range(3)},
        "hot_per_set": {k: hot.count(k) for k in sorted(set(hot))},
        "sum_min": min(map(sum, sets)), "sum_max": max(map(sum, sets)),
        "sum_mean": statistics.mean(map(sum, sets)),
        "no_pair": sum(all(s[i + 1] - s[i] > 1 for i in range(5)) for s in sets),
        "coverage": sum(C[n] > 0 for n in NUMS),
        "coverage_groups": {g: sum(C[n] > 0 for n in getattr(a, g)) for g in ("hot", "warm", "cold")},
        "appear_min": min(C.values()), "appear_max": max(C.values()),
        "appear_var": statistics.pvariance(C.values()), "counts": C,
        "overlap_max": max(inter), "overlap_mean": statistics.mean(inter), "overlap3": inter.count(3),
    }


def render(sets, a, cfg, stages, relaxed, checks, source):
    sm = summary(sets, a, cfg)
    S = sm["sets"]
    pct = lambda d: ", ".join(f"{_label(k)}({v}개, {v / S * 100:.1f}%)" for k, v in d.items())
    tg = lambda d: ", ".join(f"{_label(k)} {v * 100:.0f}%" for k, v in d.items()) if d else "없음"
    mr = cfg["rules"]["mean_reversion"]
    lines = []
    for i, s in enumerate(sets, 1):
        o, l = sum(n % 2 for n in s), sum(n <= 22 for n in s)
        c = [n for n in s if n in a.carry]
        lines.append(f"[{i:02d}세트] {f2(s)} | 합계: {sum(s)} | 홀짝: {o}:{6 - o} | 저고: {l}:{6 - l} | "
                     f"AC: {ac(s)} | H{sum(n in a.hot for n in s)}/W{sum(n in a.warm for n in s)}/C{sum(n in a.cold for n in s)} | "
                     f"이월수: {f2(c) if c else '없음'}")
    ob = a.observed
    out = [
        f"# 포트폴리오 리포트 · 프리셋 {cfg.get('name')}",
        "",
        "※ 모든 조합의 1등 확률은 1/8,145,060으로 같습니다. 이 엔진은 당첨 확률이 아니라 포트폴리오 구조를 최적화합니다.",
        "",
        "[1. 분석 기준 메타데이터]",
        f"- 분석 회차 범위: 제{a.first}회 ~ 제{a.last}회 (데이터 출처: {source})",
        f"- Hot 번호 (14개): [{f2(a.hot)}] (최상위: {f2(a.top)})",
        f"- Warm 번호 (17개): [{f2(a.warm)}]",
        f"- Cold 번호 (14개): [{f2(a.cold)}] (최장 미출현 {len(a.long_absent)}개: {f2(a.long_absent)}, 방식: {mr.get('mode')})",
        f"- 직전 회차 이월수 (6개): [{f2(a.carry)}]",
        f"- 실측: 합계 평균 {ob['sum_mean']:.2f}, 연속수 없음 {ob['no_consecutive'] * 100:.0f}%, "
        f"홀짝 {tg(ob['odd_even'])}, 이월수 개수 " + ", ".join(f"{k}개 {v * 100:.0f}%" for k, v in ob['carry'].items()),
        f"- 사용한 목표: 홀짝 [{tg(a.targets.get('odd_even'))}], 저고 [{tg(a.targets.get('low_high'))}], "
        f"이월수 [{tg(a.targets.get('carry'))}], Hot 개수 [{tg((a.targets.get('group_mix') or {}).get('hot'))}]",
        "",
        "[2. 로또 번호 포트폴리오]",
        "```", *lines, "```",
        "",
        "[3. 전역 검증 요약]",
        f"- 생성 세트 수: {S}세트",
        f"- 독립 검증: {'위반 없음' if not checks['sets'] and not checks['global'] else checks}",
        f"- 홀짝 분포: {pct(sm['odd_even'])}",
        f"- 저고 분포: {pct(sm['low_high'])}",
        f"- 이월수 개수: " + ", ".join(f"{k}개({v}세트)" for k, v in sm["carry"].items()),
        f"- 세트당 Hot 개수: " + ", ".join(f"{k}개({v}세트)" for k, v in sm["hot_per_set"].items()),
        f"- 합계: {sm['sum_min']}~{sm['sum_max']} (평균 {sm['sum_mean']:.1f})",
        f"- 연속수 0쌍 세트: {sm['no_pair']}개",
        f"- 전체 번호 커버리지: {sm['coverage']}/45 (Hot {sm['coverage_groups']['hot']}/14, Warm {sm['coverage_groups']['warm']}/17, Cold {sm['coverage_groups']['cold']}/14)",
        f"- 번호별 출현 횟수: 최소 {sm['appear_min']}회 / 최대 {sm['appear_max']}회 (분산 {sm['appear_var']:.2f})",
        f"- 세트 간 교집합: 최대 {sm['overlap_max']}개 (평균 {sm['overlap_mean']:.2f}개, 3개 공유 {sm['overlap3']}쌍)",
        f"- 조건 완화 적용 여부: {', '.join(relaxed) if relaxed else '없음'}",
        "- 최적화 단계: " + "; ".join(f"{s['name']} {s['status']} {s['value']} (하한 {s['bound']})" for s in stages),
    ]
    return "\n".join(out), sm


def to_json(sets, a, sm, stages, relaxed):
    return json.dumps({"range": [a.first, a.last], "hot": a.hot, "warm": a.warm, "cold": a.cold,
                       "carry": a.carry, "sets": sets, "stages": stages, "relaxed": relaxed,
                       "summary": {k: v for k, v in sm.items() if k != "counts"}}, ensure_ascii=False, indent=1)


def compare(results):
    """프리셋별 결과를 한 표로 비교."""
    def dist(d, S):
        return " / ".join(f"{_label(k)} {v}" for k, v in d.items())

    rows = [
        ("독립 검증", lambda r: "위반 없음" if not r["checks"]["sets"] and not r["checks"]["global"] else "위반 있음"),
        ("조건 완화", lambda r: ", ".join(r["relaxed"]) or "없음"),
        ("홀짝 분포(세트)", lambda r: dist(r["summary"]["odd_even"], r["summary"]["sets"])),
        ("저고 분포(세트)", lambda r: dist(r["summary"]["low_high"], r["summary"]["sets"])),
        ("이월수 0/1/2개", lambda r: " / ".join(str(v) for v in r["summary"]["carry"].values())),
        ("세트당 Hot 개수", lambda r: ", ".join(f"{k}개 {v}" for k, v in r["summary"]["hot_per_set"].items())),
        ("합계 범위(평균)", lambda r: f"{r['summary']['sum_min']}~{r['summary']['sum_max']} ({r['summary']['sum_mean']:.1f})"),
        ("연속수 0쌍 세트", lambda r: str(r["summary"]["no_pair"])),
        ("커버리지", lambda r: f"{r['summary']['coverage']}/45"),
        ("번호별 출현 최소~최대(분산)", lambda r: f"{r['summary']['appear_min']}~{r['summary']['appear_max']} ({r['summary']['appear_var']:.2f})"),
        ("교집합 최대(평균)", lambda r: f"{r['summary']['overlap_max']} ({r['summary']['overlap_mean']:.2f})"),
        ("교집합 3개 쌍", lambda r: str(r["summary"]["overlap3"])),
        ("최적화 단계", lambda r: "; ".join(f"{s['name']} {s['status']}" for s in r["stages"])),
    ]
    a = results[0]["analysis"]
    head = "| 항목 | " + " | ".join(r["name"] for r in results) + " |"
    sep = "|---|" + "---|" * len(results)
    body = [f"| {label} | " + " | ".join(fn(r) for r in results) + " |" for label, fn in rows]
    return "\n".join([
        f"# 프리셋 비교 (제{a.first}회 ~ 제{a.last}회 기준)", "",
        "※ 모든 조합의 1등 확률은 같습니다. 아래는 포트폴리오 구조 비교입니다.", "",
        head, sep, *body, "",
        "세트 목록: " + ", ".join(os.path.basename(r["path"]) for r in results),
    ])
