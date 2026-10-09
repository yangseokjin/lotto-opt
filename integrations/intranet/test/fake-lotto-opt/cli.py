"""테스트용 가짜 lotto-opt.
run:   진짜 엔진처럼 --out 폴더에 <프리셋>_<세트수>sets_seed<시드>.json/.md 를 쓴다.
       FAKE_MODE: ok(기본) | violations(종료 코드 1) | crash(종료 코드 2) | slow(5초 대기) | nojson
check: 진짜 엔진의 `check --json` 과 같은 모양으로 출력한다. 회차 데이터는 제1243·1244회 두 개.
       FAKE_CHECK: ok(기본) | old(check 명령이 없는 옛 엔진) | slow(5초 대기) | garbage(JSON 아님)
"""
import argparse
import json
import os
import sys
import time

DRAWS = {
    1243: {"draw_no": 1243, "date": "2026-09-26", "numbers": [2, 9, 17, 25, 33, 41], "bonus": 44},
    1244: {"draw_no": 1244, "date": "2026-10-03", "numbers": [1, 7, 13, 19, 25, 31], "bonus": 37},
}


def check_main(argv):
    mode = os.environ.get("FAKE_CHECK", "ok")
    if mode == "old":
        print("lotto-opt: error: argument cmd: invalid choice: 'check' (choose from 'run', 'compare')", file=sys.stderr)
        sys.exit(2)
    if mode == "slow":
        time.sleep(5)
    p = argparse.ArgumentParser()
    p.add_argument("portfolio")
    p.add_argument("--draw", type=int)
    p.add_argument("--numbers")
    p.add_argument("--bonus", type=int)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if mode == "garbage":
        print("# 당첨 확인 (마크다운)")
        return 0
    with open(a.portfolio, encoding="utf-8") as f:
        raw = json.load(f)
    draw = None
    if a.numbers:
        numbers, bonus = sorted(int(n) for n in a.numbers.split(",")), a.bonus
    else:
        no = a.draw if a.draw is not None else max(DRAWS)
        if no not in DRAWS:
            sys.exit(f"제{no}회 당첨번호가 데이터에 없습니다 (제{min(DRAWS)}~{max(DRAWS)}회). --numbers/--bonus 로 직접 입력해 주세요.")
        draw = DRAWS[no]
        numbers, bonus = draw["numbers"], draw["bonus"]
    win = set(numbers)
    rows = []
    for i, s in enumerate(raw["sets"], 1):
        hit = sorted(win.intersection(s))
        bonus_hit = len(hit) == 5 and bonus in s
        rank = {6: 1, 5: 2 if bonus_hit else 3, 4: 4, 3: 5}.get(len(hit))
        rows.append({"set": i, "numbers": s, "matched": hit, "match_count": len(hit), "bonus_hit": bonus_hit, "rank": rank})
    ranks = [r["rank"] for r in rows if r["rank"]]
    summary = {"sets": len(rows), "by_rank": {str(k): ranks.count(k) for k in range(1, 6)}, "winning_sets": len(ranks),
               "best_rank": min(ranks) if ranks else None,
               "by_match_count": {str(k): sum(r["match_count"] == k for r in rows) for k in range(7)}}
    out = {"draw": draw, "portfolio": {k: raw.get(k) for k in ("preset", "seed", "range")},
           "numbers": numbers, "bonus": bonus, "results": rows, "summary": summary}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if len(sys.argv) > 1 and sys.argv[1] == "check":
    sys.exit(check_main(sys.argv[2:]))

p = argparse.ArgumentParser()
p.add_argument("cmd")
p.add_argument("--config", required=True)
p.add_argument("--sets", type=int, default=30)
p.add_argument("--seed", type=int)
p.add_argument("--out", required=True)
a = p.parse_args()
mode = os.environ.get("FAKE_MODE", "ok")
print("[가짜 엔진] 시작 · 한글 출력 확인")
if mode == "slow":
    time.sleep(5)
if mode == "crash":
    print("데이터 검증 실패: 테스트용 오류", file=sys.stderr)
    sys.exit(2)
preset = os.path.splitext(os.path.basename(a.config))[0]
seed = a.seed if a.seed is not None else 4242
sets = [[(i * 7 + k * 6) % 45 + 1 for k in range(6)] for i in range(a.sets)]
sets = [sorted(set(s)) for s in sets]
result = {"version": "0.2.0", "seed": seed, "preset": preset, "profile": f"{a.sets}세트 기준", "range": [1145, 1244],
          "hot": list(range(1, 15)), "warm": list(range(15, 32)), "cold": list(range(32, 46)), "carry": [1, 13, 18, 26, 34, 38],
          "sets": sets, "stages": [], "relaxed": [],
          "summary": {"sets": a.sets, "coverage": 45, "coverage_groups": {"hot": 14, "warm": 17, "cold": 14}}}
if mode != "nojson":
    base = os.path.join(a.out, f"{preset}_{a.sets}sets_seed{seed}")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(f"# 포트폴리오 리포트 · 프리셋 {preset} · {a.sets}세트 · 시드 {seed}\n")
print("저장 완료")
sys.exit(1 if mode == "violations" else 0)
