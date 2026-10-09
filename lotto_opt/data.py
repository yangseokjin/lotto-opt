"""회차 데이터 수집·캐시·검증.

source=auto 는 동행복권 공식 API를 먼저 시도하고, 막히면 공개 미러를 쓴다.
결과는 data/draws.json 에 {draw_no, date, numbers, bonus} 목록으로 캐시한다.
"""
import datetime as dt
import json
import os
import urllib.request

OFFICIAL = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={}"
MIRROR = "https://raw.githubusercontent.com/smok95/lotto/main/results/all.json"
FIRST_DRAW = dt.date(2002, 12, 7)


def _get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "lotto-opt/0.2"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _normalize(rec):
    if "drwtNo1" in rec:  # 공식 API 형식
        return {"draw_no": rec["drwNo"], "date": rec["drwNoDate"],
                "numbers": sorted(rec[f"drwtNo{i}"] for i in range(1, 7)), "bonus": rec["bnusNo"]}
    if "bonus_no" in rec:  # 미러 형식
        return {"draw_no": rec["draw_no"], "date": rec["date"][:10],
                "numbers": sorted(rec["numbers"]), "bonus": rec["bonus_no"]}
    return rec  # 이미 정규화됨


def expected_latest(now=None):
    """지금(한국 시간) 기준 추첨이 끝났어야 할 최신 회차 (토요일 20:45 KST 추첨)."""
    now = now or dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9)))
    n = (now.date() - FIRST_DRAW).days // 7 + 1
    if now.weekday() == 5 and (now.hour, now.minute) < (21, 0):
        n -= 1
    return n


def draw_date(no):
    """회차의 추첨일 (매주 토요일)."""
    return FIRST_DRAW + dt.timedelta(weeks=no - 1)


def validate(draws):
    problems = []
    for prev, cur in zip(draws, draws[1:]):
        if cur["draw_no"] != prev["draw_no"] + 1:
            problems.append(f"회차 누락: {prev['draw_no']} → {cur['draw_no']}")
    for d in draws:
        ns = d["numbers"]
        if len(set(ns)) != 6 or not all(1 <= n <= 45 for n in ns):
            problems.append(f"{d['draw_no']}회 번호 이상: {ns}")
    return problems


def _fetch_official(cached):
    out = list(cached)
    n = (out[-1]["draw_no"] + 1) if out else 1
    while n <= expected_latest():
        rec = _get_json(OFFICIAL.format(n))
        if rec.get("returnValue") != "success":
            break
        out.append(_normalize(rec))
        n += 1
    return out


def load_draws(cache_path, source="auto"):
    """(전체 회차 목록, 사용한 출처) 반환."""
    cached = []
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cached = [_normalize(r) for r in json.load(f)]
        cached.sort(key=lambda d: d["draw_no"])
    if source == "cache" or (cached and cached[-1]["draw_no"] >= expected_latest()):
        return cached, "cache"
    used = None
    draws = cached
    if source in ("auto", "official"):
        try:
            draws, used = _fetch_official(cached), "official"
        except Exception:
            if source == "official":
                raise
    if used is None:
        try:
            draws, used = sorted((_normalize(r) for r in _get_json(MIRROR, 60)), key=lambda d: d["draw_no"]), "mirror"
        except Exception:
            if not cached or source == "mirror":
                raise
            return cached, "cache (최신 데이터를 받지 못함)"
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(draws, f, ensure_ascii=False)
    return draws, used
