"""정확한 당첨 확률: 가능한 추첨 결과 8,145,060개(45개 중 6개)를 모두 대입해 센다.

로또 추첨은 매번 독립이고 모든 조합의 확률이 같다. 그래서
  - 세트 하나가 3개 이상 맞을 확률은 어떤 번호를 고르든 똑같다 (약 2.38%).
  - 30세트에서 나오는 당첨 세트 수의 '평균'도 어떤 포트폴리오든 똑같다.
  - 포트폴리오가 바꿀 수 있는 것은 '하나라도 맞을 확률'뿐이다. 세트끼리 번호를 덜 겹치면
    당첨이 한 회차에 몰리지 않고 여러 회차로 퍼져서, 한 세트도 못 맞히는 회차가 줄어든다.
이 모듈은 그 확률을 근사 없이 계산한다 (numpy, 약 4초).
"""
from functools import lru_cache
from math import comb

import numpy as np

TOTAL = comb(45, 6)
PRIZE_MIN = {5: 3, 4: 4, 3: 5, 1: 6}  # 등수 → 최소 일치 개수 (2등은 보너스가 필요해 3등과 같은 5개로 본다)


@lru_cache(maxsize=1)
def all_draws():
    """45개 중 6개 조합 전체를 비트마스크(uint64) 배열로."""
    cur = np.array([1 << i for i in range(45)], dtype=np.uint64)
    last = np.arange(45)
    for depth in range(5):
        reps = np.maximum(44 - last - (4 - depth), 0)  # 끝까지 6개를 채울 수 있는 다음 번호만
        idx = np.repeat(np.arange(len(cur)), reps)
        start = np.repeat(np.cumsum(reps) - reps, reps)
        nxt = np.repeat(last + 1, reps) + (np.arange(len(idx)) - start)
        cur = cur[idx] | (np.uint64(1) << nxt.astype(np.uint64))
        last = nxt
    return cur


def _mask(s):
    return np.uint64(sum(1 << (n - 1) for n in s))


def ticket(k):
    """세트 하나가 정확히 k개 맞을 확률."""
    return comb(6, k) * comb(39, 6 - k) / TOTAL


def ticket_at_least(k):
    return sum(ticket(j) for j in range(k, 7))


def portfolio(sets):
    """포트폴리오의 정확한 확률.

    best[k]: 가장 잘 맞은 세트가 k개 이상 맞을 확률 (= 그 회차에 k개 이상 맞는 세트가 하나라도 있을 확률)
    expected[k]: 회차당 k개 이상 맞는 세트 수의 평균 (포트폴리오와 무관하게 세트 수 × 한 세트 확률)
    random_best[k]: 무작위 세트를 같은 수만큼 샀을 때(서로 독립) 하나라도 k개 이상 맞을 확률
    """
    draws = all_draws()
    top = np.zeros(len(draws), np.uint8)
    for s in sets:
        np.maximum(top, np.bitwise_count(draws & _mask(s)), out=top)
    hist = np.bincount(top, minlength=7)
    S = len(sets)
    best = {k: float(hist[k:].sum() / TOTAL) for k in range(3, 7)}
    return {"sets": S, "best": best,
            "zero_win": 1 - best[3],
            "expected": {k: S * ticket_at_least(k) for k in range(3, 7)},
            "random_best": {k: 1 - (1 - ticket_at_least(k)) ** S for k in range(3, 7)}}


def render(o):
    S = o["sets"]
    p, r = o["best"][3], o["random_best"][3]
    return "\n".join([
        f"- {S}세트 중 하나라도 5등 이상(3개 이상 일치)일 확률: {p:.1%} (무작위 {S}세트: {r:.1%})",
        f"- 한 세트도 못 맞히는(3개 미만) 회차 비율: {1 - p:.1%} (무작위: {1 - r:.1%})",
        f"- 하나라도 4등 이상(4개 이상 일치)일 확률: {o['best'][4]:.2%} (무작위: {o['random_best'][4]:.2%})",
        f"- 회차당 5등 이상 세트 수 평균: {o['expected'][3]:.3f}개 (어떤 번호를 골라도 같음)",
    ])
