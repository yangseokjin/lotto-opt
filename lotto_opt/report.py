"""결과 리포트 (지정 출력 형식 + 목표 대비 결과 + JSON + 프리셋 비교)."""
import itertools
import json
import os
import statistics
from collections import Counter

from . import __version__
from .objective import set_categories
from .stats import LH_BUCKETS, OE_BUCKETS
from .validate import ac

NUMS = range(1, 46)
f2 = lambda L: ", ".join(f"{n:02d}" for n in L)
FAMILY_LABEL = {"odd_even": "홀짝", "low_high": "저고", "carry": "이월수 개수", "group_mix": "세트 구성 H-W-C",
                "sum_bins": "합계 구간"}


def _label(k):
    return "기타" if k == "other" else k


def _key_label(name, k, a):
    if name == "carry":
        return f"{k}개"
    if name == "group_mix":
        return "-".join(map(str, k))
    if name == "sum_bins":
        lo, hi = list(a.targets["sum_bins"])[k]
        return f"{lo}~{hi}"
    return _label(k)


def summary(sets, a, cfg):
    S = len(sets)
    C = {n: sum(n in s for s in sets) for n in NUMS}
    inter = [len(set(p) & set(q)) for p, q in itertools.combinations(sets, 2)]
    bins = list(a.targets["sum_bins"]) if a.targets.get("sum_bins") else None
    cats = [set_categories(s, a, bins) for s in sets]
    return {
        "sets": S,
        "odd_even": {k: sum(c["odd_even"] == k for c in cats) for k in OE_BUCKETS},
        "low_high": {k: sum(c["low_high"] == k for c in cats) for k in LH_BUCKETS},
        "carry": dict(sorted(Counter(c["carry"] for c in cats).items())),
        "group_mix": dict(sorted(Counter(c["group_mix"] for c in cats).items(), key=lambda kv: (-kv[1], kv[0]))),
        "hot_per_set": dict(sorted(Counter(c["group_mix"][0] for c in cats).items())),
        "sum_min": min(map(sum, sets)), "sum_max": max(map(sum, sets)),
        "sum_mean": statistics.mean(map(sum, sets)),
        "no_pair": sum(all(s[i + 1] - s[i] > 1 for i in range(5)) for s in sets),
        "coverage": sum(C[n] > 0 for n in NUMS),
        "coverage_groups": {g: sum(C[n] > 0 for n in getattr(a, g)) for g in ("hot", "warm", "cold")},
        "appear_min": min(C.values()), "appear_max": max(C.values()),
        "appear_var": statistics.pvariance(C.values()), "counts": C,
        "carry_uses": {n: C[n] for n in a.carry},
        "overlap_max": max(inter), "overlap_mean": statistics.mean(inter),
        "overlap2": inter.count(2), "overlap3": inter.count(3), "overlap4": inter.count(4),
        "cats": cats,
    }


def target_rows(sm, a):
    """(분포 이름, 구간, 목표 세트 수, 실제 세트 수) 목록과 오차 합계(세트 단위)."""
    S, rows, err = sm["sets"], [], 0.0
    for name in ("odd_even", "low_high", "carry", "group_mix", "sum_bins"):
        tgt = a.targets.get(name)
        if not tgt:
            continue
        keys = list(tgt.items())
        if name == "sum_bins":
            keys = [(i, p) for i, (_, p) in enumerate(keys)]
        actual = Counter(c[name] for c in sm["cats"])
        for k, p in keys:
            k = int(k) if name == "carry" else k
            rows.append((name, _key_label(name, k, a), S * p, actual.get(k, 0)))
            err += abs(actual.get(k, 0) - round(100 * S * p) / 100)
    return rows, err


def _stage_line(st, sm):
    name = st["name"]
    if st.get("value") is None:
        return f"{name}: 해를 찾지 못함 ({st['status']})"
    if name == "distribution_error":
        tail = " → 최적 (더 줄일 수 없는 최소치에 도달)" if st["status"] == "OPTIMAL" else \
            f" (이론상 최소 {st['bound'] / 100:.2f}세트분)" if st.get("bound") is not None else ""
        return f"분포 오차 {st['value'] / 100:.2f}세트분{tail}"
    if name == "overlap":
        return f"세트 간 교집합: 최대 {sm['overlap_max']}개, 3개 공유 {sm['overlap3']}쌍, 2개 공유 {sm['overlap2']}쌍"
    if name.startswith("appearance"):
        uses = list(sm["carry_uses"].values())
        return f"번호별 출현 횟수 분산 {sm['appear_var']:.2f}, 이월수 사용 편차 {max(uses) - min(uses)}"
    return f"{name}: {st['value']}"


def render(sets, a, cfg, stages, relaxed, checks, source, meta=None):
    meta = meta or {}
    sm = summary(sets, a, cfg)
    S = sm["sets"]
    R = cfg["rules"]
    pct = lambda d: ", ".join(f"{_label(k)}({v}개, {v / S * 100:.1f}%)" for k, v in d.items())
    tg = lambda d: ", ".join(f"{_label(k)} {v * 100:.0f}%" for k, v in d.items()) if d else "없음"
    mr = R["mean_reversion"]
    lines = []
    for i, s in enumerate(sets, 1):
        o, l = sum(n % 2 for n in s), sum(n <= 22 for n in s)
        c = [n for n in s if n in a.carry]
        lines.append(f"[{i:02d}세트] {f2(s)} | 합계: {sum(s)} | 홀짝: {o}:{6 - o} | 저고: {l}:{6 - l} | "
                     f"AC: {ac(s)} | H{sum(n in a.hot for n in s)}/W{sum(n in a.warm for n in s)}/C{sum(n in a.cold for n in s)} | "
                     f"이월수: {f2(c) if c else '없음'}")
    ob = a.observed
    ap, cu, cv = R["appearance"], R["carry_over"]["per_number_uses"], R["coverage"]
    seed = cfg["portfolio"].get("seed")
    rows, err = target_rows(sm, a)
    ok = not checks["sets"] and not checks["global"]
    out = [
        f"# 포트폴리오 리포트 · 프리셋 {cfg.get('name')} · {S}세트 · 시드 {seed}",
        "",
        "※ 모든 조합의 1등 확률은 1/8,145,060으로 같습니다. 이 엔진은 당첨 확률이 아니라 "
        "포트폴리오 구조(목표 분포, 세트 간 겹침, 번호를 고르게 쓰기)를 최적화합니다.",
        "",
    ]
    if meta.get("target_draw"):
        stale = meta["target_draw"] > a.last + 1
        out += [f"이 번호는 **제{meta['target_draw']}회**용입니다." +
                (f" 주의: 제{a.last + 1}회 추첨은 끝났지만 그 당첨번호를 아직 받지 못해 제{a.last}회까지로 계산했습니다."
                 if stale else ""), ""]
    if meta.get("command"):
        out += [f"같은 결과 다시 만들기: `{meta['command']}`", ""]
    out += [
        "[1. 분석 기준 메타데이터]",
        f"- 분석 회차 범위: 제{a.first}회 ~ 제{a.last}회 (최신 추첨일 {a.last_date or '알 수 없음'}, 데이터 출처: {source})",
        f"- Hot 번호 ({len(a.hot)}개): [{f2(a.hot)}] (최상위: {f2(a.top)})",
        f"- Warm 번호 ({len(a.warm)}개): [{f2(a.warm)}]",
        f"- Cold 번호 ({len(a.cold)}개): [{f2(a.cold)}] (최장 미출현 {len(a.long_absent)}개: {f2(a.long_absent)}, 방식: {mr.get('mode')})",
        f"- 직전 회차 이월수 (6개): [{f2(a.carry)}]",
        f"- 세트 수 기준: {meta.get('profile') or '설정 파일 값'} (번호별 출현 {ap['general'][0]}~{ap['general'][1]}회, "
        f"최상위 {ap['hot_top'][0]}~{ap['hot_top'][1]}회, 이월수 각 {cu[0]}~{cu[1]}회, 커버리지 {cv['total']}개 이상)",
        f"- 실측: 합계 평균 {ob['sum_mean']:.2f}, 연속수 없음 {ob['no_consecutive'] * 100:.0f}%, "
        f"홀짝 {tg(ob['odd_even'])}, 이월수 개수 " + ", ".join(f"{k}개 {v * 100:.0f}%" for k, v in ob['carry'].items()),
        "",
        "[2. 로또 번호 포트폴리오]",
        "```", *lines, "```",
        "",
        "[3. 전역 검증 요약]",
        f"- 생성 세트 수: {S}세트",
        f"- 독립 검증: {'위반 없음' if ok else checks}",
        f"- 홀짝 분포: {pct(sm['odd_even'])}",
        f"- 저고 분포: {pct(sm['low_high'])}",
        "- 이월수 개수: " + ", ".join(f"{k}개({v}세트)" for k, v in sm["carry"].items()),
        "- 세트 구성(Hot-Warm-Cold): " + ", ".join(f"{'-'.join(map(str, k))}({v}세트)" for k, v in sm["group_mix"].items()),
        f"- 합계: {sm['sum_min']}~{sm['sum_max']} (평균 {sm['sum_mean']:.1f})",
        f"- 연속수 0쌍 세트: {sm['no_pair']}개",
        f"- 전체 번호 커버리지: {sm['coverage']}/45 (Hot {sm['coverage_groups']['hot']}/{len(a.hot)}, "
        f"Warm {sm['coverage_groups']['warm']}/{len(a.warm)}, Cold {sm['coverage_groups']['cold']}/{len(a.cold)})",
        f"- 번호별 출현 횟수: 최소 {sm['appear_min']}회 / 최대 {sm['appear_max']}회 (분산 {sm['appear_var']:.2f})",
        "- 이월수 사용 횟수: " + ", ".join(f"{n:02d} {c}회" for n, c in sm["carry_uses"].items()),
        f"- 세트 간 교집합: 최대 {sm['overlap_max']}개 (평균 {sm['overlap_mean']:.2f}개, "
        f"2개 공유 {sm['overlap2']}쌍, 3개 공유 {sm['overlap3']}쌍)",
        f"- 조건 완화 적용 여부: {', '.join(relaxed) if relaxed else '없음'}",
        "",
    ]
    if rows:
        out += ["[4. 목표 분포 대비 결과] (세트 수)", "", "| 분포 | 구간 | 목표 | 실제 |", "|---|---|---|---|"]
        out += [f"| {FAMILY_LABEL[n]} | {k} | {t:.1f} | {v} |" for n, k, t, v in rows]
        out += ["", f"목표와의 차이 합계: {err:.2f}세트분", ""]
    out += ["[5. 최적화 단계] (위 단계 결과를 지키면서 다음 단계를 줄임)"]
    out += [f"{i}) {_stage_line(st, sm)}" for i, st in enumerate(stages, 1)]
    if meta.get("seconds") is not None:
        out += [f"(실행 시간 {meta['seconds']:.0f}초, lotto-opt {__version__})"]
    return "\n".join(out), sm


def to_json(sets, a, sm, stages, relaxed, meta=None, odds=None):
    meta = meta or {}
    keep = {k: v for k, v in sm.items() if k not in ("counts", "cats")}
    keep["group_mix"] = {"-".join(map(str, k)): v for k, v in keep["group_mix"].items()}
    return json.dumps({"version": __version__, "seed": meta.get("seed"), "preset": meta.get("preset"),
                       "profile": meta.get("profile"), "range": [a.first, a.last], "target_draw": meta.get("target_draw"), "hot": a.hot, "warm": a.warm,
                       "cold": a.cold, "carry": a.carry, "sets": sets, "stages": stages, "relaxed": relaxed,
                       "summary": keep, "odds": odds}, ensure_ascii=False, indent=1, default=str)


def compare(results):
    """프리셋별 결과를 한 표로 비교."""
    def dist(d):
        return " / ".join(f"{_label(k)} {v}" for k, v in d.items())

    rows = [
        ("독립 검증", lambda r: "위반 없음" if not r["checks"]["sets"] and not r["checks"]["global"] else "위반 있음"),
        ("조건 완화", lambda r: ", ".join(r["relaxed"]) or "없음"),
        ("홀짝 분포(세트)", lambda r: dist(r["summary"]["odd_even"])),
        ("저고 분포(세트)", lambda r: dist(r["summary"]["low_high"])),
        ("이월수 개수별 세트", lambda r: ", ".join(f"{k}개 {v}" for k, v in r["summary"]["carry"].items())),
        ("세트당 Hot 개수", lambda r: ", ".join(f"{k}개 {v}" for k, v in r["summary"]["hot_per_set"].items())),
        ("합계 범위(평균)", lambda r: f"{r['summary']['sum_min']}~{r['summary']['sum_max']} ({r['summary']['sum_mean']:.1f})"),
        ("연속수 0쌍 세트", lambda r: str(r["summary"]["no_pair"])),
        ("커버리지", lambda r: f"{r['summary']['coverage']}/45"),
        ("번호별 출현 최소~최대(분산)",
         lambda r: f"{r['summary']['appear_min']}~{r['summary']['appear_max']} ({r['summary']['appear_var']:.2f})"),
        ("교집합 최대(평균)", lambda r: f"{r['summary']['overlap_max']} ({r['summary']['overlap_mean']:.2f})"),
        ("교집합 3개 / 2개 쌍", lambda r: f"{r['summary']['overlap3']} / {r['summary']['overlap2']}"),
        ("목표와의 차이(세트분)", lambda r: f"{target_rows(r['summary'], r['analysis'])[1]:.2f}"),
        ("실행 시간", lambda r: f"{r['seconds']:.0f}초"),
    ]
    a = results[0]["analysis"]
    head = "| 항목 | " + " | ".join(r["name"] for r in results) + " |"
    sep = "|---|" + "---|" * len(results)
    body = [f"| {label} | " + " | ".join(fn(r) for r in results) + " |" for label, fn in rows]
    return "\n".join([
        f"# 프리셋 비교 (제{a.first}회 ~ 제{a.last}회 기준, {results[0]['summary']['sets']}세트, 시드 {results[0]['seed']})", "",
        "※ 모든 조합의 1등 확률은 같습니다. 아래는 포트폴리오 구조 비교입니다. "
        "목표 분포는 프리셋마다 다르므로 '목표와의 차이'는 각자 자기 목표 기준입니다.", "",
        head, sep, *body, "",
        "세트 목록: " + ", ".join(os.path.basename(r["path"]) for r in results),
    ])
