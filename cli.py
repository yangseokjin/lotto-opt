"""사용법:
  python3 cli.py run --config config/to_be.yaml [--sets 30] [--seed 0] [--set targets.odd_even=auto]
  python3 cli.py compare --config config/as_is.yaml --config config/to_be.yaml [--time-scale 0.5]
"""
import argparse
import os
import sys

import yaml

from lotto_opt import config, data, report, solver, validate

ROOT = os.path.dirname(os.path.abspath(__file__))


def prepare(path, args):
    cfg = config.load(path)
    if args.sets: cfg["portfolio"]["sets"] = args.sets
    if args.seed is not None: cfg["portfolio"]["seed"] = args.seed
    if args.source: cfg["data"]["source"] = args.source
    for item in args.set or []:  # --set 점.경로=YAML값
        key, _, raw = item.partition("=")
        cfg = config.set_path(cfg, key, yaml.safe_load(raw))
    for st in cfg["objective"]:
        st["time_limit"] = st.get("time_limit", 60) * args.time_scale
    return cfg


def run_one(cfg, args, quiet=False):
    draws, source = data.load_draws(os.path.join(ROOT, "data", "draws.json"), cfg["data"]["source"])
    problems = data.validate(draws[-cfg["data"]["window"]:])
    if problems:
        sys.exit("데이터 검증 실패: " + "; ".join(problems))
    print(f"[{cfg['name']}] 데이터: 제{draws[-1]['draw_no']}회까지 ({source})")
    sets, a, final_cfg, stages, relaxed = solver.run(cfg, draws)
    checks = validate.validate(sets, final_cfg, a)
    text, sm = report.render(sets, a, final_cfg, stages, relaxed, checks, source)
    os.makedirs(args.out, exist_ok=True)
    base = os.path.join(args.out, f"{cfg['name']}_{cfg['portfolio']['sets']}sets_seed{cfg['portfolio']['seed']}")
    open(base + ".md", "w", encoding="utf-8").write(text)
    open(base + ".json", "w", encoding="utf-8").write(report.to_json(sets, a, sm, stages, relaxed))
    if not quiet:
        print(text)
    print(f"저장: {base}.md / .json")
    return {"name": cfg["name"], "summary": sm, "checks": checks, "relaxed": relaxed,
            "stages": stages, "analysis": a, "path": base + ".md"}


def main(argv=None):
    p = argparse.ArgumentParser(prog="lotto-opt")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_ in (("run", "포트폴리오 최적화 실행"), ("compare", "여러 프리셋을 같은 데이터로 비교")):
        r = sub.add_parser(name, help=help_)
        r.add_argument("--config", required=True, action="append" if name == "compare" else "store")
        r.add_argument("--sets", type=int)
        r.add_argument("--seed", type=int)
        r.add_argument("--source")
        r.add_argument("--set", action="append", help="설정 덮어쓰기: 점.경로=값")
        r.add_argument("--time-scale", type=float, default=1.0, help="단계별 시간 제한 배수")
        r.add_argument("--out", default=os.path.join(ROOT, "out"))
    args = p.parse_args(argv)

    if args.cmd == "run":
        res = run_one(prepare(args.config, args), args)
        return 1 if res["checks"]["sets"] or res["checks"]["global"] else 0

    results = [run_one(prepare(path, args), args, quiet=True) for path in args.config]
    text = report.compare(results)
    path = os.path.join(args.out, "compare_" + "_vs_".join(r["name"] for r in results) + ".md")
    open(path, "w", encoding="utf-8").write(text)
    print(text)
    print(f"저장: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
