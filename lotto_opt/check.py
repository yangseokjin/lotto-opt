"""당첨 확인: 저장된 포트폴리오의 세트별 등수와 전체 요약.

등수 규칙 (로또 6/45): 1등 6개 일치, 2등 5개+보너스, 3등 5개, 4등 4개, 5등 3개, 그 밖은 낙첨.
"""
import json
from collections import Counter

RANKS = (1, 2, 3, 4, 5)
RANK_LABEL = {1: "1등", 2: "2등", 3: "3등", 4: "4등", 5: "5등", None: "낙첨"}
f2 = lambda L: ", ".join(f"{n:02d}" for n in L)


def rank(matched, bonus_hit):
    """일치 개수와 보너스 일치 여부 → 등수 (1~5) 또는 None."""
    if matched == 6:
        return 1
    if matched == 5:
        return 2 if bonus_hit else 3
    return {4: 4, 3: 5}.get(matched)


def winning(numbers, bonus):
    """당첨번호 6개 + 보너스 검증. (정렬된 번호, 보너스) 반환."""
    ns = sorted(int(n) for n in numbers)
    bonus = int(bonus)
    if len(ns) != 6 or len(set(ns)) != 6 or not all(1 <= n <= 45 for n in ns):
        raise ValueError(f"당첨번호는 1~45 사이 서로 다른 6개여야 합니다: {ns}")
    if not 1 <= bonus <= 45 or bonus in ns:
        raise ValueError(f"보너스 번호는 1~45 사이이고 당첨번호 6개와 달라야 합니다: {bonus}")
    return ns, bonus


def load_sets(path):
    """`cli.py run` 이 저장한 JSON(또는 세트 목록만 담은 JSON)에서 (세트 목록, 메타) 읽기."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    sets = raw["sets"] if isinstance(raw, dict) else raw
    meta = {k: raw.get(k) for k in ("preset", "seed", "range")} if isinstance(raw, dict) else {}
    out = []
    for i, s in enumerate(sets, 1):
        s = sorted(int(n) for n in s)
        if len(s) != 6 or len(set(s)) != 6 or not all(1 <= n <= 45 for n in s):
            raise ValueError(f"{i}번째 세트가 올바르지 않습니다: {s}")
        out.append(s)
    return out, meta


def check(sets, numbers, bonus):
    """세트별 결과와 전체 요약."""
    numbers, bonus = winning(numbers, bonus)
    win = set(numbers)
    rows = []
    for i, s in enumerate(sets, 1):
        hit = sorted(win.intersection(s))
        bonus_hit = len(hit) == 5 and bonus in s
        rows.append({"set": i, "numbers": list(s), "matched": hit, "match_count": len(hit),
                     "bonus_hit": bonus_hit, "rank": rank(len(hit), bonus_hit)})
    by_rank = Counter(r["rank"] for r in rows if r["rank"])
    ranks = [r["rank"] for r in rows if r["rank"]]
    summary = {"sets": len(rows), "by_rank": {str(k): by_rank.get(k, 0) for k in RANKS},
               "winning_sets": len(ranks), "best_rank": min(ranks) if ranks else None,
               "by_match_count": {str(k): sum(r["match_count"] == k for r in rows) for k in range(7)}}
    return {"numbers": numbers, "bonus": bonus, "results": rows, "summary": summary}


def render(res, draw=None, meta=None):
    """사람이 읽는 결과 (마크다운)."""
    meta = meta or {}
    sm = res["summary"]
    title = f"제{draw['draw_no']}회 ({draw['date']})" if draw else "직접 입력한 번호"
    lines = [f"# 당첨 확인: {title}", ""]
    if meta.get("preset"):
        lines.append(f"- 포트폴리오: {meta['preset']} · {sm['sets']}세트 · 시드 {meta.get('seed')}")
    if draw and meta.get("range") and draw["draw_no"] <= meta["range"][1]:
        lines.append(f"- 참고: 이 포트폴리오는 제{meta['range'][1]}회까지의 데이터로 만들어서, "
                     f"제{draw['draw_no']}회는 이미 분석에 들어간 회차입니다.")
    lines += [f"- 당첨번호: {f2(res['numbers'])} + 보너스 {res['bonus']:02d}",
              f"- 최고 등수: {RANK_LABEL[sm['best_rank']]}",
              "- 등수별: " + " / ".join(f"{RANK_LABEL[k]} {sm['by_rank'][str(k)]}" for k in RANKS)
              + f" (당첨 {sm['winning_sets']}세트, 낙첨 {sm['sets'] - sm['winning_sets']}세트)",
              "- 일치 개수별: " + " / ".join(f"{k}개 {v}" for k, v in sm["by_match_count"].items() if v),
              "", "| 세트 | 번호 | 일치 | 일치 번호 | 등수 |", "|---|---|---|---|---|"]
    for r in res["results"]:
        count = f"{r['match_count']}개" + ("+보너스" if r["bonus_hit"] else "")
        lines.append(f"| {r['set']} | {f2(r['numbers'])} | {count} | {f2(r['matched']) or '-'} | {RANK_LABEL[r['rank']]} |")
    return "\n".join(lines) + "\n"


def to_json(res, draw=None, meta=None):
    out = {"draw": draw, "portfolio": meta or {}, **res}
    return json.dumps(out, ensure_ascii=False, indent=1)
