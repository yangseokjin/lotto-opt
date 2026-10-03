"""CP-SAT 모델 조립과 단계별(사전식) 풀이, 자동 완화.

풀이 방식 (v0.2): 결정적 대규모 이웃 탐색(LNS)
  1) pool.construct 가 시드로 정해지는 출발 포트폴리오를 만든다 (모든 제약 만족).
  2) 목적 단계마다:
     a) search.improve: 번호 하나 바꾸기/맞바꾸기 같은 작은 이동을 빠르게 수만 번 시도
     b) CP-SAT 이웃 탐색: 라운드마다 세트 몇 개만 풀어 두고 나머지는 고정한 작은 모델 여러 개를 동시에 풀고,
        개선된 결과를 합친다. 하한에 닿거나 개선이 멈추면 끝
     c) 다시 a)
  3) 단계 결과는 다음 단계의 상한으로 고정한다 (사전식).
모든 풀이는 단일 스레드 + '결정적 시간' 제한이고 이웃 선택도 시드 난수라서, 같은 시드면 같은 결과가 나온다.
"""
import itertools
import random
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from . import pool, search
from .config import set_path
from .constraints import set_level, global_level
from . import validate
from .objective import STAGES, VALUES, bound
from .stats import NUMS, analyze

OK = (cp_model.OPTIMAL, cp_model.FEASIBLE)


@dataclass
class Ctx:
    m: cp_model.CpModel
    a: object
    rules: dict
    S: int
    fixed: dict = field(default_factory=dict)  # 세트 번호 → 고정된 번호 목록 (이웃 탐색용)
    x: dict = field(default_factory=dict)
    cat: dict = field(default_factory=lambda: defaultdict(dict))
    total: dict = field(default_factory=dict)
    no_pair: dict = field(default_factory=dict)
    appear_onehot: dict = field(default_factory=dict)

    @property
    def sets(self):
        return range(self.S)


def build(cfg, a, fixed=None, stages=None):
    """CP-SAT 모델. fixed 에 든 세트는 변수 대신 상수로 넣어 작은 모델을 만든다.

    stages: 목적식을 만들 단계 목록 (기본: 설정의 모든 단계).
    """
    S = cfg["portfolio"]["sets"]
    ctx = Ctx(cp_model.CpModel(), a, cfg["rules"], S, dict(fixed or {}))
    for s in ctx.sets:
        for n in NUMS:
            ctx.x[s, n] = int(n in ctx.fixed[s]) if s in ctx.fixed else ctx.m.NewBoolVar(f"x{s}_{n}")
    for s in ctx.sets:
        if s in ctx.fixed:
            set_level.add_fixed(ctx, s, ctx.fixed[s])
        else:
            set_level.add(ctx, s)
    global_level.add(ctx)
    ctx.objs = {st["name"]: STAGES[st["name"]](ctx, **_opts(st)) for st in (stages or cfg["objective"])}
    return ctx


def _opts(st):
    return {k: v for k, v in st.items() if k in ("start",)}


@dataclass
class Result:
    status: int
    value: float = None
    bound: float = None
    sets: list = None


def _solve(cfg, a, cur, free, dt, seed, stage, locks):
    """free 에 든 세트만 바꿀 수 있게 하고 나머지는 cur 로 고정해 푼다 (단일 스레드, 결정적 시간 dt).

    stage: 지금 최소화할 단계 설정, locks: 앞 단계 (설정, 값) — 앞 단계 값이 나빠지지 않게 상한으로 건다.
    """
    S = cfg["portfolio"]["sets"]
    fixed = {s: cur[s] for s in range(S) if s not in free} if cur else {}
    ctx = build(cfg, a, fixed, [st for st, _ in locks] + [stage])
    for st, v in locks:
        ctx.m.Add(ctx.objs[st["name"]] <= v)
    ctx.m.Minimize(ctx.objs[stage["name"]])
    if cur:
        for s in free:
            for n in NUMS:
                ctx.m.AddHint(ctx.x[s, n], n in cur[s])
    sv = cp_model.CpSolver()
    sp = sv.parameters
    sp.num_workers = 1
    sp.random_seed = seed % (2 ** 31)
    sp.max_deterministic_time = dt
    sp.max_presolve_iterations = 1
    sp.max_time_in_seconds = 600  # 안전장치 (정상이라면 결정적 시간이 먼저 끝난다)
    r = sv.Solve(ctx.m)
    if r not in OK:
        return Result(r)
    sets = [cur[s] if s in fixed else [n for n in NUMS if sv.Value(ctx.x[s, n])] for s in range(S)]
    return Result(r, round(sv.ObjectiveValue()), round(sv.BestObjectiveBound()), sets)


def _neighborhood(name, cur, rng, k, S):
    """이번 라운드에 풀어 둘 세트 번호들. 단계 목적에 맞게 문제 있는 세트를 우선 고른다."""
    k = min(k, S)
    focus = []
    if name == "overlap":
        inter = {(i, j): len(set(cur[i]) & set(cur[j])) for i, j in itertools.combinations(range(S), 2)}
        worst = max(inter.values())
        if worst >= 2:
            focus = list(rng.choice([p for p, v in inter.items() if v == worst]))
    elif name.startswith("appearance"):
        C = Counter(n for s in cur for n in s)
        hi = max(C.values())
        nums = [n for n in NUMS if C[n] == hi]
        n = rng.choice(nums)
        cand = [i for i in range(S) if n in cur[i]]
        focus = rng.sample(cand, min(len(cand), max(1, k // 2)))
    rest = [i for i in range(S) if i not in focus]
    return set(focus) | set(rng.sample(rest, k - len(focus)))


def _stage(a, st, cur, cfg, effort, log, locks):
    """한 목적 단계. 라운드마다 이웃 여러 개를 동시에 풀고, 개선된 것들을 겹치지 않는 범위에서 합친다.

    locks: 앞 단계들의 (단계 설정, 값). 작은 문제마다 상한으로 걸고, 합친 해도 이를 지키는지 확인한다.
    (현재 해, 단계 기록) 반환.
    """
    p = cfg["portfolio"]
    S, name = p["sets"], st["name"]
    value = lambda sets, s_=st: VALUES[s_["name"]](sets, a, cfg["rules"], **_opts(s_))

    def acceptable(sets):
        if any(validate.validate(sets, cfg, a).values()):
            return False
        return all(value(sets, s_) <= v for s_, v in locks)

    seed = p.get("seed") or 0
    rng = random.Random(f"{seed}:{name}")
    t = time.time()
    lb = bound(name, a, cfg["rules"], S)
    ls_iters = round(st.get("ls_iters", 20000) * effort)
    cur, _ = search.improve(cur, cfg, a, st, locks, rng, ls_iters)
    best = value(cur)
    workers, k = p.get("workers", 4), st.get("free_sets", p.get("free_sets", 5))
    rounds, patience = round(st.get("rounds", 20) * effort), st.get("patience", 6)
    sub_dt = st.get("sub_dt", 1.0)
    stall, done = 0, 0
    with ThreadPoolExecutor(workers) as ex:
        while done < rounds and (lb is None or best > lb) and stall < patience:
            done += 1
            hoods = [_neighborhood(name, cur, rng, k, S) for _ in range(workers)]
            seeds = [rng.randrange(2 ** 31) for _ in range(workers)]
            res = list(ex.map(lambda h: _solve(cfg, a, cur, h[0], sub_dt, h[1], st, locks), zip(hoods, seeds)))
            better = sorted((r.value, i) for i, r in enumerate(res) if r.status in OK and r.value < best)
            if not better:
                same = [r for r in res if r.status in OK and r.value == best]
                if same:  # 같은 값의 다른 해로 옮겨 가며 정체 구간을 벗어난다
                    cur = same[0].sets
                stall += 1
                continue
            v, i = better[0]
            cur, best, used = res[i].sets, v, set(hoods[i])
            for _, j in better[1:]:  # 서로 다른 세트를 바꾼 개선은 합쳐 본다
                if hoods[j] & used:
                    continue
                trial = [res[j].sets[s] if s in hoods[j] else cur[s] for s in range(S)]
                tv = value(trial)
                if tv < best and acceptable(trial):
                    cur, best = trial, tv
                    used |= hoods[j]
            stall = 0
    if lb is None or best > lb:
        cur, _ = search.improve(cur, cfg, a, st, locks, rng, ls_iters)
        best = value(cur)
    status = "OPTIMAL" if lb is not None and best <= lb else "FEASIBLE"
    locks.append((st, best))  # 다음 단계에서 이 단계 결과를 지킨다
    rec = {"name": name, "status": status, "value": best, "bound": lb,
           "seconds": round(time.time() - t, 1), "rounds": done}
    log(f"  [{name}] {status} 값={best} 하한={lb} (라운드 {done}, {rec['seconds']}s)")
    return cur, rec


def _status(code):
    return {cp_model.INFEASIBLE: "INFEASIBLE", cp_model.MODEL_INVALID: "MODEL_INVALID"}.get(code, "UNKNOWN")


def _start(cfg, a, log):
    """출발 포트폴리오. 지역 탐색으로 못 맞추면 전체 모델을 한 번 풀어 실행 가능한 해를 찾는다."""
    p = cfg["portfolio"]
    t = time.time()
    cur, score = None, None
    for attempt in range(3):  # 위반이 남으면 반복 횟수를 늘려 다시 (결정적)
        cur, score = pool.construct(cfg, a, f"{p.get('seed') or 0}:{attempt}", p.get("pool", 6000),
                                    p.get("construct_iters", 4000) * 2 ** attempt)
        if cur is None or score[0] == 0:
            break
    if cur is not None and score[0] == 0:
        log(f"  [출발점] 분포 오차 {score[1]:.1f}세트 ({time.time() - t:.1f}s)")
        return cur, None
    log("  [출발점] 지역 탐색으로 모든 제약을 맞추지 못해 전체 모델로 찾는 중")
    r = _solve(cfg, a, cur, set(range(p["sets"])), p.get("feasibility_dt", 60.0), p.get("seed") or 0,
               cfg["objective"][0], [])
    if r.status not in OK:
        return None, _status(r.status)
    return r.sets, None


def _solve_stages(cfg, a, log, effort=1.0):
    cur, status = _start(cfg, a, log)
    if cur is None:
        return None, [], status
    stages, locks = [], []
    for st in cfg["objective"]:
        cur, rec = _stage(a, st, cur, cfg, effort, log, locks)
        stages.append(rec)
    return cur, stages, "ok"


def run(cfg, draws, log=print, effort=1.0):
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
        sets, stages, status = _solve_stages(cfg, a, log, effort)
        if sets:
            return sorted(sets), a, cfg, stages, applied
        log(f"해 없음({status})")
    raise RuntimeError("모든 완화 단계를 적용해도 해를 찾지 못했습니다.")
