"""사용법:
  python3 cli.py run --config config/to_be.yaml [--sets 30|50] [--seed N] [--set 점.경로=값] [--effort 1]
  python3 cli.py compare --config config/as_is.yaml --config config/to_be.yaml [--sets 50] [--seed N]

--seed 를 주지 않으면 실행마다 새 시드를 뽑아 다른 조합을 만들고, 리포트에 그 시드를 적어 둔다.
같은 시드·같은 설정·같은 데이터면 언제 다시 돌려도 같은 결과가 나온다.
"""
import argparse
import os
import random
import shlex
import sys
import time

import yaml

from lotto_opt import config, data, report, solver, validate

ROOT = os.path.dirname(os.path.abspath(__file__))


def new_seed():
    return random.SystemRandom().randrange(1, 1_000_000)


def prepare(path, args, seed=None):
    """설정 파일 + 명령줄 덮어쓰기 + 세트 수 기준(profiles). (cfg, 기준 설명) 반환."""
    cfg = config.load(path)
    if args.sets:
        cfg["portfolio"]["sets"] = args.sets
    if args.source:
        cfg["data"]["source"] = args.source
    for item in args.set or []:  # --set 점.경로=YAML값
        key, _, raw = item.partition("=")
        cfg = config.set_path(cfg, key, yaml.safe_load(raw))
    if seed is None:
        seed = args.seed if args.seed is not None else cfg["portfolio"].get("seed")
    cfg["portfolio"]["seed"] = seed if seed is not None else new_seed()
    return config.apply_profile(cfg)


def command(path, cfg, args):
    parts = ["python3", "cli.py", "run", "--config", path, "--sets", str(cfg["portfolio"]["sets"]),
             "--seed", str(cfg["portfolio"]["seed"])]
    for item in args.set or []:
        parts += ["--set", item]
    if args.effort != 1.0:
        parts += ["--effort", str(args.effort)]
    return " ".join(shlex.quote(p) for p in parts)


def run_one(path, cfg, note, args, quiet=False):
    draws, source = data.load_draws(args.data, cfg["data"]["source"])
    problems = data.validate(draws[-cfg["data"]["window"]:])
    if problems:
        sys.exit("데이터 검증 실패: " + "; ".join(problems))
    if draws[-1]["draw_no"] < data.expected_latest() and not source.startswith("cache"):
        print(f"  주의: 최신 회차는 제{data.expected_latest()}회인데 받은 데이터는 제{draws[-1]['draw_no']}회까지입니다.")
    seed = cfg["portfolio"]["seed"]
    print(f"[{cfg['name']}] 데이터: 제{draws[-1]['draw_no']}회까지 ({source}) · {cfg['portfolio']['sets']}세트 · 시드 {seed}")
    if note:
        print(f"  세트 수 기준: {note}")
    t = time.time()
    try:
        sets, a, final_cfg, stages, relaxed = solver.run(cfg, draws, effort=args.effort)
    except RuntimeError as e:
        sys.exit(f"[{cfg['name']}] {e} 설정의 제약이 서로 맞지 않는지 확인해 주세요.")
    seconds = time.time() - t
    checks = validate.validate(sets, final_cfg, a)
    meta = {"seed": seed, "preset": cfg["name"], "profile": note, "seconds": seconds,
            "command": command(path, cfg, args)}
    text, sm = report.render(sets, a, final_cfg, stages, relaxed, checks, source, meta)
    os.makedirs(args.out, exist_ok=True)
    base = os.path.join(args.out, f"{cfg['name']}_{cfg['portfolio']['sets']}sets_seed{seed}")
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(text)
    with open(base + ".json", "w", encoding="utf-8") as f:
        f.write(report.to_json(sets, a, sm, stages, relaxed, meta))
    if not quiet:
        print(text)
    print(f"저장: {base}.md / .json")
    return {"name": cfg["name"], "summary": sm, "checks": checks, "relaxed": relaxed, "stages": stages,
            "analysis": a, "path": base + ".md", "seed": seed, "seconds": seconds}


def main(argv=None):
    p = argparse.ArgumentParser(prog="lotto-opt")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_ in (("run", "포트폴리오 최적화 실행"), ("compare", "여러 프리셋을 같은 데이터·같은 시드로 비교")):
        r = sub.add_parser(name, help=help_)
        r.add_argument("--config", required=True, action="append" if name == "compare" else "store")
        r.add_argument("--sets", type=int, help="세트 수 (30, 50은 기획서 기준, 그 밖의 수는 가까운 기준을 비례 조정)")
        r.add_argument("--seed", type=int, help="같은 시드면 같은 결과. 생략하면 실행마다 새 시드")
        r.add_argument("--source", help="auto | official | mirror | cache")
        r.add_argument("--set", action="append", help="설정 덮어쓰기: 점.경로=값")
        r.add_argument("--effort", "--time-scale", dest="effort", type=float, default=1.0,
                       help="탐색량 배수 (2 = 두 배 오래, 더 좋은 해를 찾을 수도 있음)")
        r.add_argument("--out", default=os.path.join(ROOT, "out"))
        r.add_argument("--data", default=os.path.join(ROOT, "data", "draws.json"), help="회차 데이터 캐시 파일")
    args = p.parse_args(argv)

    if args.cmd == "run":
        cfg, note = prepare(args.config, args)
        res = run_one(args.config, cfg, note, args)
        return 1 if res["checks"]["sets"] or res["checks"]["global"] else 0

    seed = args.seed if args.seed is not None else new_seed()  # 공정한 비교를 위해 모든 프리셋이 같은 시드
    results = [run_one(path, *prepare(path, args, seed), args, quiet=True) for path in args.config]
    text = report.compare(results)
    path = os.path.join(args.out, "compare_" + "_vs_".join(r["name"] for r in results) +
                        f"_{results[0]['summary']['sets']}sets_seed{seed}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"저장: {path}")
    return 1 if any(r["checks"]["sets"] or r["checks"]["global"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
