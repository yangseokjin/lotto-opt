"""과거 회차 백테스트: '그 회차 직전까지의 데이터'만으로 포트폴리오를 만들어 그 회차와 맞춰 본다.

두 가지를 본다.
  1) 그룹 적중률 (빠름, 수백 회차): Hot/Warm/Cold·이월수·장기 미출현 번호가 다음 회차에
     실제로 몇 개씩 나왔는지를, 아무 번호나 골랐을 때의 기대값과 비교한다.
  2) 포트폴리오 성적 (느림, 회차당 수십 초): 프리셋마다 실제로 30세트를 만들어
     일치 개수 분포, 당첨 세트 수, 정확한 '하나라도 맞을 확률'을 무작위 기준과 비교한다.
"""
import random
import statistics
from collections import Counter

from . import check, config, odds, solver
from .stats import analyze

NUMS = range(1, 46)


def group_hits(draws, cfg, count):
    """최근 count 회차 각각에 대해, 직전 데이터로 나눈 그룹에서 몇 개가 나왔는지 평균."""
    groups = {"Hot": lambda a: a.hot, "Warm": lambda a: a.warm, "Cold": lambda a: a.cold,
              "이월수(직전 회차 번호)": lambda a: a.carry, "장기 미출현 Cold": lambda a: a.long_absent}
    hits = {g: [] for g in groups}
    sizes = {}
    window = cfg["data"]["window"]
    start = max(window, len(draws) - count)
    for i in range(start, len(draws)):
        a = analyze(draws[:i], cfg)
        nxt = set(draws[i]["numbers"])
        for g, get in groups.items():
            nums = get(a)
            sizes[g] = len(nums)
            hits[g].append(len(nxt & set(nums)))
    rows = []
    for g, h in hits.items():
        exp = 6 * sizes[g] / 45
        rows.append({"group": g, "size": sizes[g], "mean": statistics.mean(h), "expected": exp,
                     "se": statistics.stdev(h) / len(h) ** 0.5})
    return {"draws": len(draws) - start, "first": draws[start]["draw_no"], "last": draws[-1]["draw_no"], "rows": rows}


def portfolios(draws, presets, count, sets, seed, effort=1.0, log=print):
    """프리셋별로 최근 count 회차를 하나씩: 직전 데이터로 sets 세트를 만들고 그 회차와 비교."""
    out = {}
    for path in presets:
        base = config.load(path)
        base["portfolio"]["sets"] = sets
        rows = []
        for i in range(len(draws) - count, len(draws)):
            target = draws[i]
            cfg = dict(base, portfolio=dict(base["portfolio"], seed=seed + target["draw_no"]))
            cfg, _ = config.apply_profile(cfg)
            res, _, _, _, relaxed = solver.run(cfg, draws[:i], log=lambda *_: None, effort=effort)
            got = check.check(res, target["numbers"], target["bonus"])
            o = odds.portfolio(res)
            rows.append({"draw": target["draw_no"], "match": got["summary"]["by_match_count"],
                         "winning_sets": got["summary"]["winning_sets"], "best_rank": got["summary"]["best_rank"],
                         "p_any": o["best"][3], "relaxed": relaxed})
            log(f"  [{base['name']}] 제{target['draw_no']}회: 당첨 {rows[-1]['winning_sets']}세트, "
                f"하나라도 맞을 확률 {o['best'][3]:.1%}")
        out[base["name"]] = rows
    return out


def random_portfolios(draws, count, sets, seed):
    """비교용: 회차마다 무작위 sets 세트."""
    rng = random.Random(seed)
    rows = []
    for d in draws[-count:]:
        res = [sorted(rng.sample(NUMS, 6)) for _ in range(sets)]
        got = check.check(res, d["numbers"], d["bonus"])
        rows.append({"draw": d["draw_no"], "match": got["summary"]["by_match_count"],
                     "winning_sets": got["summary"]["winning_sets"], "best_rank": got["summary"]["best_rank"],
                     "p_any": odds.portfolio(res)["best"][3], "relaxed": []})
    return rows


def _row_summary(rows, sets):
    n = len(rows)
    m = Counter()
    for r in rows:
        m.update({int(k): v for k, v in r["match"].items()})
    tickets = n * sets
    return {"draws": n, "tickets": tickets,
            "avg_match": sum(k * v for k, v in m.items()) / tickets,
            "ge3_tickets": sum(v for k, v in m.items() if k >= 3),
            "draws_with_win": sum(r["winning_sets"] > 0 for r in rows),
            "p_any_mean": statistics.mean(r["p_any"] for r in rows),
            "relaxed": sum(bool(r["relaxed"]) for r in rows)}


def render(gh, results, sets):
    lines = ["# 백테스트 결과", ""]
    if gh:
        lines += [f"## 1. 그룹 적중률 (제{gh['first']}~{gh['last']}회, {gh['draws']}회차)", "",
                  "각 회차 직전 100회로 그룹을 나누고, 그 회차 당첨번호 6개 중 몇 개가 그 그룹에서 나왔는지 평균.",
                  "기대값은 그룹 크기만큼 아무 번호나 골랐을 때의 값(6 × 그룹 크기 ÷ 45).", "",
                  "| 그룹 | 번호 수 | 실제 평균 | 기대값 | 차이 | 오차 범위(±2σ) |", "|---|---|---|---|---|---|"]
        for r in gh["rows"]:
            lines.append(f"| {r['group']} | {r['size']} | {r['mean']:.3f} | {r['expected']:.3f} | "
                         f"{r['mean'] - r['expected']:+.3f} | ±{2 * r['se']:.3f} |")
        lines += ["", "차이가 오차 범위 안이면 그 그룹이 다음 회차를 더 잘(또는 덜) 맞힌다는 근거가 없다는 뜻입니다.", ""]
    if results:
        tick = odds.ticket_at_least(3)
        lines += [f"## 2. 포트폴리오 성적 ({sets}세트, 회차마다 직전 데이터로 새로 생성)", "",
                  "| 방식 | 회차 수 | 세트 평균 일치 | 5등 이상 세트 (기대값) | 당첨 나온 회차 | 하나라도 맞을 확률(정확 계산 평균) |",
                  "|---|---|---|---|---|---|"]
        for name, rows in results.items():
            s = _row_summary(rows, sets)
            lines.append(f"| {name} | {s['draws']} | {s['avg_match']:.3f} | {s['ge3_tickets']} "
                         f"({s['tickets'] * tick:.1f}) | {s['draws_with_win']}/{s['draws']} | {s['p_any_mean']:.1%} |")
        lines += ["", f"- 세트 하나의 평균 일치 개수는 어떤 번호든 0.800개, 5등 이상 확률은 {tick:.2%}로 같습니다.",
                  "- '당첨 나온 회차'는 실제 결과라서 운의 영향이 큽니다. 방식 간 차이는 마지막 열(모든 추첨 결과를 "
                  "대입한 정확한 확률)로 비교하는 것이 정확합니다.", ""]
        for name, rows in results.items():
            lines += [f"### {name} 회차별", "", "| 회차 | 일치 개수별 세트 수 | 당첨 세트 | 하나라도 맞을 확률 |", "|---|---|---|---|"]
            for r in rows:
                dist = " / ".join(f"{k}개 {v}" for k, v in r["match"].items() if v)
                lines.append(f"| {r['draw']} | {dist} | {r['winning_sets']} | {r['p_any']:.1%} |")
            lines.append("")
    return "\n".join(lines)
