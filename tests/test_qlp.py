"""§17.9 mandatory: q_LP sign on hand-constructed buy AND sell swaps —
overpayment in both directions must come out LP-positive with no
per-side negation; extraction must come out LP-negative."""
import numpy as np
import pytest

from pipeline.qlp import q_lp

P = 2000.0  # benchmark: token1 (ETH) in token0 (USDC)


def one(a0, a1):
    q, notional = q_lp(np.array([a0]), np.array([a1]), np.array([P]))
    return float(q[0]), float(notional[0])


def test_buy_eth_overpayment_is_lp_positive():
    # Trader buys 1 ETH, pays 2010 USDC (overpays 10):
    # pool receives 2010 USDC (a0=+2010), sends 1 ETH (a1=-1).
    q, _ = one(+2010.0, -1.0)
    assert q > 0
    assert q == pytest.approx(10.0 / 2005.0, rel=1e-9)


def test_sell_eth_overpayment_is_lp_positive():
    # Trader sells 1 ETH, receives only 1990 USDC (underpaid by 10):
    # pool receives 1 ETH (a1=+1), sends 1990 USDC (a0=-1990).
    q, _ = one(-1990.0, +1.0)
    assert q > 0
    assert q == pytest.approx(10.0 / 1995.0, rel=1e-9)


def test_buy_eth_extraction_is_lp_negative():
    # Arb buys 1 ETH for 1980 USDC while true price is 2000: LP loses 20.
    q, _ = one(+1980.0, -1.0)
    assert q < 0
    assert q == pytest.approx(-20.0 / 1990.0, rel=1e-9)


def test_sell_eth_extraction_is_lp_negative():
    # Arb sells 1 ETH for 2020 USDC while true price is 2000: LP loses 20.
    q, _ = one(-2020.0, +1.0)
    assert q < 0


def test_fair_swap_is_zero():
    q, _ = one(+2000.0, -1.0)
    assert q == pytest.approx(0.0, abs=1e-12)


def test_no_per_side_negation_symmetry():
    # Same 10-USDC overpayment, both directions → both positive, similar scale.
    q_buy, _ = one(+2010.0, -1.0)
    q_sell, _ = one(-1990.0, +1.0)
    assert q_buy > 0 and q_sell > 0
    assert q_buy == pytest.approx(q_sell, rel=0.01)
