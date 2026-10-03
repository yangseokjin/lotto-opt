"""사용법: python3 cli.py run --config config/to_be.yaml [--sets 30] [--seed 0] [--source auto|cache]"""
import argparse
import os
import sys

from lotto_opt import config, data, report, solver, validate

ROOT = os.path.dirname(os.path.abspath(__file__))


def main(argv=None):
    p = argparse.ArgumentParser(prog="lotto-opt")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="포트폴리오 최적화 실행")
    r.add_argument("--config", required=True)
    r.add_argument("--sets", type=int)
    r.add_argument("--seed", type=int)
    r.add_argument("--source")
    r.add_argument("--time-scale", type=float, default=1.0, help="단계별 시간 제한 배수")
    r.add_argument("--out", default=os.path.join(ROOT, "out"))
    args = p.parse_args(argv)

    cfg = config.load(args.config)
    if args.sets: cfg["portfolio"]["sets"] = args.sets
    if args.seed is not None: cfg["portfolio"]["seed"] = args.seed
    if args.source: cfg["data"]["source"] = args.source
    for st in cfg["objective"]:
        st["time_limit"] = st.get("time_limit", 60) * args.time_scale

    draws, source = data.load_draws(os.path.join(ROOT, "data", "draws.json"), cfg["data"]["source"])
    problems = data.validate(draws[-cfg["data"]["window"]:])
    if problems:
        sys.exit("데이터 검증 실패: " + "; ".join(problems))
    print(f"데이터: 제{draws[-1]['draw_no']}회까지 ({source})")

    sets, a, final_cfg, stages, relaxed = solver.run(cfg, draws)
    checks = validate.validate(sets, final_cfg, a)
    text, sm = report.render(sets, a, final_cfg, stages, relaxed, checks, source)
    os.makedirs(args.out, exist_ok=True)
    base = os.path.join(args.out, f"{cfg['name']}_{cfg['portfolio']['sets']}sets_seed{cfg['portfolio']['seed']}")
    open(base + ".md", "w", encoding="utf-8").write(text)
    open(base + ".json", "w", encoding="utf-8").write(report.to_json(sets, a, sm, stages, relaxed))
    print(text)
    print(f"\n저장: {base}.md / .json")
    return 1 if checks["sets"] or checks["global"] else 0


if __name__ == "__main__":
    sys.exit(main())
