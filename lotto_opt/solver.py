"""CP-SAT 모델 조립과 단계별(사전식) 풀이, 자동 완화."""
from dataclasses import dataclass, field
from ortools.sat.python import cp_model

from .config import set_path
from .constraints import set_level, global_level
from .objective import STAGES
from .stats import NUMS, analyze


@dataclass
class Ctx:
    m: cp_model.CpModel
    a: object
    rules: dict
    S: int
    x: dict = field(default_factory=dict)
    group_count: dict = field(default_factory=dict)
    carry_count: dict = field(default_factory=dict)
    total: dict = field(default_factory=dict)
    no_pair: dict = field(default_factory=dict)
    odd: dict = field(default_factory=dict)
    low: dict = field(default_factory=dict)

    @property
    def sets(self):
        return range(self.S)


def build(cfg, a):
    S = cfg["portfolio"]["sets"]
    ctx = Ctx(cp_model.CpModel(), a, cfg["rules"], S)
    ctx.x = {(s, n): ctx.m.NewBoolVar(f"x{s}_{n}") for s in ctx.sets for n in NUMS}
    for s in ctx.sets:
        set_level.add(ctx, s)
    global_level.add(ctx)
    ctx.objs = {st["name"]: STAGES[st["name"]](ctx) for st in cfg["objective"]}
    return ctx


def _solve_stages(cfg, ctx, log):
    solver = cp_model.CpSolver()
    p = cfg["portfolio"]
    solver.parameters.num_workers = p.get("workers", 4)
    solver.parameters.random_seed = p.get("seed", 0)
    stages, sets = [], None
    for st in cfg["objective"]:
        obj = ctx.objs[st["name"]]
        ctx.m.ClearObjective(); ctx.m.Minimize(obj)
        solver.parameters.max_time_in_seconds = st.get("time_limit", 60)
        r = solver.Solve(ctx.m)
        status = solver.StatusName(r)
        log(f"  [{st['name']}] {status} 값={solver.ObjectiveValue():.0f} 하한={solver.BestObjectiveBound():.0f} ({solver.WallTime():.1f}s)")
        if r not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if sets:  # 앞 단계 해는 유효하므로 그대로 반환
                stages.append({"name": st["name"], "status": status, "value": None, "bound": None, "seconds": None})
                return sets, stages, "ok"
            return None, stages, status
        v = int(round(solver.ObjectiveValue()))
        stages.append({"name": st["name"], "status": status, "value": v,
                       "bound": int(round(solver.BestObjectiveBound())), "seconds": round(solver.WallTime(), 1)})
        ctx.m.Add(obj <= v)  # 다음 단계에서 이 단계 결과를 지킨다
        ctx.m.ClearHints()
        for k, var in ctx.x.items():
            ctx.m.AddHint(var, solver.Value(var))
        sets = [[n for n in NUMS if solver.Value(ctx.x[s, n])] for s in ctx.sets]
    return sets, stages, "ok"


def run(cfg, draws, log=print):
    """완화 목록을 순서대로 적용하며 해를 찾는다. (sets, analysis, 최종 cfg, 단계기록, 적용한 완화) 반환."""
    applied = []
    attempts = [None] + list(cfg.get("relax", []))
    for step in attempts:
        if step:
            (path, val), = step.items()
            cfg = set_path(cfg, path, val)
            applied.append(f"{path} = {val}")
            log(f"완화 적용: {path} = {val}")
        a = analyze(draws, cfg)
        ctx = build(cfg, a)
        sets, stages, status = _solve_stages(cfg, ctx, log)
        if sets:
            return sorted(sets), a, cfg, stages, applied
        log(f"해 없음({status})")
    raise RuntimeError("모든 완화 단계를 적용해도 해를 찾지 못했습니다.")
