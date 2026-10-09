"""정확한 확률 계산 확인."""
from math import comb

import numpy as np

from lotto_opt import objective, odds


def test_all_draws_are_every_combination_once():
    d = odds.all_draws()
    assert len(d) == comb(45, 6) == odds.TOTAL
    assert len(np.unique(d)) == len(d)
    assert np.all(np.bitwise_count(d) == 6)
    assert int(d.max()) < 1 << 45


def test_single_ticket_matches_hypergeometric():
    o = odds.portfolio([[1, 2, 3, 4, 5, 6]])
    for k in range(3, 7):
        assert abs(o["best"][k] - odds.ticket_at_least(k)) < 1e-12
    assert abs(sum(odds.ticket(k) for k in range(7)) - 1) < 1e-12


def test_pair_union_uses_joint_win_count():
    # 2개 공유하는 두 세트: P(하나라도) = 2 × P(한 세트) - P(둘 다)
    o = odds.portfolio([[1, 2, 3, 4, 5, 6], [1, 2, 7, 8, 9, 10]])
    expect = 2 * odds.ticket_at_least(3) - objective._both_win(2) / odds.TOTAL
    assert abs(o["best"][3] - expect) < 1e-12


def test_duplicate_ticket_adds_nothing_and_spread_helps():
    a = [1, 2, 3, 4, 5, 6]
    assert odds.portfolio([a, a])["best"] == odds.portfolio([a])["best"]
    spread = odds.portfolio([a, [7, 8, 9, 10, 11, 12]])["best"][3]
    close = odds.portfolio([a, [1, 2, 3, 10, 11, 12]])["best"][3]
    assert spread > close
