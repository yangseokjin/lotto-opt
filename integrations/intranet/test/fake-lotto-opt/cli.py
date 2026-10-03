"""테스트용 가짜 lotto-opt. 진짜 엔진처럼 --out 폴더에 <프리셋>_<세트수>sets_seed<시드>.json/.md 를 쓴다.
FAKE_MODE: ok(기본) | violations(종료 코드 1) | crash(종료 코드 2) | slow(5초 대기) | nojson
"""
import argparse
import json
import os
import sys
import time

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
