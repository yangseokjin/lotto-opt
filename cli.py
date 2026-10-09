"""사용법:
  python3 cli.py run [--config config/to_be.yaml] [--sets 30|50] [--seed N] [--set 점.경로=값] [--effort 1]
  python3 cli.py compare --config config/to_be.yaml --config config/spread.yaml [--sets 50] [--seed N]
  python3 cli.py check out/to_be_30sets_seed7.json [--draw 1243 | --numbers 1,2,3,4,5,6 --bonus 7] [--json]
  python3 cli.py odds out/to_be_30sets_seed7.json            # 하나라도 맞을 확률 (정확 계산)
  python3 cli.py backtest --config config/to_be.yaml --config config/spread.yaml [--draws 20] [--groups 500]

--seed 를 주지 않으면 실행마다 새 시드를 뽑아 다른 조합을 만들고, 리포트에 그 시드를 적어 둔다.
같은 시드·같은 설정·같은 데이터면 언제 다시 돌려도 같은 결과가 나온다.
"""
import argparse
import json
import os
import random
import shlex
import sys
import time

import yaml

from lotto_opt import backtest, check, config, data, odds, report, solver, validate

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
    o = odds.portfolio(sets)
    text = text.rstrip("\n") + "\n\n[6. 당첨 확률 (가능한 추첨 결과 8,145,060개를 모두 대입한 정확한 값)]\n" + odds.render(o) + "\n"
    os.makedirs(args.out, exist_ok=True)
    base = os.path.join(args.out, f"{cfg['name']}_{cfg['portfolio']['sets']}sets_seed{seed}")
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(text)
    with open(base + ".json", "w", encoding="utf-8") as f:
        f.write(report.to_json(sets, a, sm, stages, relaxed, meta, odds=o))
    if not quiet:
        print(text)
    print(f"저장: {base}.md / .json")
    return {"name": cfg["name"], "summary": sm, "checks": checks, "relaxed": relaxed, "stages": stages,
            "analysis": a, "path": base + ".md", "seed": seed, "seconds": seconds}


def run_check(args):
    """저장된 포트폴리오를 회차(또는 직접 입력한 번호)와 맞춰 본다."""
    try:
        sets, meta = check.load_sets(args.portfolio)
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"포트폴리오 파일을 읽지 못했습니다: {e}")
    draw = None
    if args.numbers:
        if args.bonus is None:
            sys.exit("--numbers 를 쓸 때는 --bonus 도 함께 주세요.")
        numbers, bonus = [n for n in args.numbers.replace(",", " ").split()], args.bonus
    else:
        if args.bonus is not None:
            sys.exit("--bonus 는 --numbers 와 함께 쓸 때만 씁니다.")
        draws, _ = data.load_draws(args.data, args.source or "auto")
        if not draws:
            sys.exit("회차 데이터가 없습니다. --numbers/--bonus 로 직접 입력해 주세요.")
        no = args.draw if args.draw is not None else draws[-1]["draw_no"]
        draw = next((d for d in draws if d["draw_no"] == no), None)
        if draw is None:
            sys.exit(f"제{no}회 당첨번호가 데이터에 없습니다 (제{draws[0]['draw_no']}~{draws[-1]['draw_no']}회). "
                     "--numbers/--bonus 로 직접 입력해 주세요.")
        numbers, bonus = draw["numbers"], draw["bonus"]
    try:
        res = check.check(sets, numbers, bonus)
    except ValueError as e:
        sys.exit(str(e))
    print(check.to_json(res, draw, meta) if args.json else check.render(res, draw, meta))
    return 0


def run_odds(args):
    try:
        sets, meta = check.load_sets(args.portfolio)
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"포트폴리오 파일을 읽지 못했습니다: {e}")
    o = odds.portfolio(sets)
    print(json.dumps(o, ensure_ascii=False, indent=1) if args.json else odds.render(o))
    return 0


def run_backtest(args):
    """과거 회차마다 '그 직전 데이터'로 포트폴리오를 만들어 그 회차와 비교한다."""
    draws, source = data.load_draws(args.data, args.source or "auto")
    print(f"데이터: 제{draws[0]['draw_no']}~{draws[-1]['draw_no']}회 ({source})")
    cfg0 = config.load(args.config[0]) if args.config else config.load(os.path.join(ROOT, "config", "to_be.yaml"))
    gh = backtest.group_hits(draws, cfg0, args.groups) if args.groups else None
    results = {}
    if args.draws:
        seed = args.seed if args.seed is not None else 0
        results = backtest.portfolios(draws, args.config or [], args.draws, args.sets, seed, args.effort)
        results["무작위"] = backtest.random_portfolios(draws, args.draws, args.sets, seed)
    text = backtest.render(gh, results, args.sets)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"backtest_{draws[-1]['draw_no']}_{args.draws}draws_{args.sets}sets.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"저장: {path}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="lotto-opt")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_ in (("run", "포트폴리오 최적화 실행"), ("compare", "여러 프리셋을 같은 데이터·같은 시드로 비교")):
        r = sub.add_parser(name, help=help_)
        if name == "compare":
            r.add_argument("--config", required=True, action="append")
        else:
            r.add_argument("--config", help="설정 파일 (기본: config/to_be.yaml)")
        r.add_argument("--sets", type=int, help="세트 수 (30, 50은 기획서 기준, 그 밖의 수는 가까운 기준을 비례 조정)")
        r.add_argument("--seed", type=int, help="같은 시드면 같은 결과. 생략하면 실행마다 새 시드")
        r.add_argument("--source", help="auto | official | mirror | cache")
        r.add_argument("--set", action="append", help="설정 덮어쓰기: 점.경로=값")
        r.add_argument("--effort", "--time-scale", dest="effort", type=float, default=1.0,
                       help="탐색량 배수 (2 = 두 배 오래, 더 좋은 해를 찾을 수도 있음)")
        r.add_argument("--out", default=os.path.join(ROOT, "out"))
        r.add_argument("--data", default=os.path.join(ROOT, "data", "draws.json"), help="회차 데이터 캐시 파일")
    c = sub.add_parser("check", help="저장된 포트폴리오(JSON)의 당첨 확인")
    c.add_argument("portfolio", help="run 이 저장한 out/*.json 파일")
    c.add_argument("--draw", type=int, help="확인할 회차 (생략하면 데이터의 최신 회차)")
    c.add_argument("--numbers", help="당첨번호 6개 직접 입력 (예: 1,2,3,4,5,6)")
    c.add_argument("--bonus", type=int, help="보너스 번호 (--numbers 와 함께)")
    c.add_argument("--json", action="store_true", help="결과를 JSON으로 출력 (다른 프로그램에서 읽을 때)")
    c.add_argument("--source", help="auto | official | mirror | cache")
    c.add_argument("--data", default=os.path.join(ROOT, "data", "draws.json"), help="회차 데이터 캐시 파일")
    o = sub.add_parser("odds", help="저장된 포트폴리오가 한 회차에 하나라도 맞을 정확한 확률")
    o.add_argument("portfolio", help="run 이 저장한 out/*.json 파일")
    o.add_argument("--json", action="store_true")
    b = sub.add_parser("backtest", help="과거 회차로 그룹 적중률과 포트폴리오 성적 확인")
    b.add_argument("--config", action="append", help="비교할 프리셋 (여러 번 가능). 첫 번째 설정으로 그룹을 나눈다")
    b.add_argument("--draws", type=int, default=20, help="포트폴리오를 만들어 볼 최근 회차 수 (회차당 수십 초, 0이면 생략)")
    b.add_argument("--groups", type=int, default=500, help="그룹 적중률을 볼 최근 회차 수 (빠름, 0이면 생략)")
    b.add_argument("--sets", type=int, default=30)
    b.add_argument("--seed", type=int, help="회차별 시드 = 이 값 + 회차 번호 (기본 0)")
    b.add_argument("--effort", type=float, default=1.0)
    b.add_argument("--source", help="auto | official | mirror | cache")
    b.add_argument("--out", default=os.path.join(ROOT, "out"))
    b.add_argument("--data", default=os.path.join(ROOT, "data", "draws.json"), help="회차 데이터 캐시 파일")
    args = p.parse_args(argv)

    if args.cmd == "check":
        return run_check(args)
    if args.cmd == "odds":
        return run_odds(args)
    if args.cmd == "backtest":
        return run_backtest(args)

    if args.cmd == "run":
        args.config = args.config or os.path.relpath(os.path.join(ROOT, "config", "to_be.yaml"))
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
