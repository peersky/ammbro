import numpy as np

from pipeline.directional import SidedSeries, compose_eth_usdc, directional_price
from pipeline.qlp import q_lp


def test_stale_side_cannot_cross():
    # Old bid print at 101, then price falls: new ask print at 100.
    s = SidedSeries(ts_bid=[0], px_bid=[101.0], ts_ask=[10], px_ask=[100.0])
    q = s.quotes(np.array([20]))
    assert q["crossed_raw"][0]
    assert q["bid"][0] <= 100.0 <= q["ask"][0]


def test_nan_before_both_sides_print():
    s = SidedSeries(ts_bid=[5], px_bid=[99.0], ts_ask=[50], px_ask=[100.0])
    q = s.quotes(np.array([10]))
    assert np.isnan(q["bid"][0]) and np.isnan(q["ask"][0])


def test_composition_buy_leg_ask_over_sell_leg_bid():
    eth = {"bid": np.array([2000.0]), "ask": np.array([2001.0])}
    usdc = {"bid": np.array([0.9999]), "ask": np.array([1.0001])}
    bid, ask = compose_eth_usdc(eth, usdc)
    assert np.isclose(ask[0], 2001.0 / 0.9999)
    assert np.isclose(bid[0], 2000.0 / 1.0001)
    assert bid[0] < ask[0]


def test_convention_ordering_both_directions():
    bid, ask = np.array([1999.0, 1999.0]), np.array([2001.0, 2001.0])
    a0 = np.array([2000.0, -2000.0])   # pool receives / sends USDC
    a1 = np.array([-1.0, 1.0])         # pool sends / receives ETH
    qs = {c: q_lp(a0, a1, directional_price(a1, bid, ask, c))[0]
          for c in ("arb_exit", "mid", "paper_literal")}
    # arb_exit is the tolerant rule: never more LP-negative than mid,
    # paper_literal never less, in either trade direction.
    assert np.all(qs["arb_exit"] >= qs["mid"])
    assert np.all(qs["mid"] >= qs["paper_literal"])
    # At a mid-priced fill, arb_exit leaves the swap LP-positive.
    assert np.all(qs["arb_exit"] > 0) and np.all(qs["paper_literal"] < 0)


def test_zero_spread_reduces_to_trade_price():
    p = np.array([2000.0])
    a0, a1 = np.array([1990.0]), np.array([-1.0])
    base = q_lp(a0, a1, p)[0]
    for c in ("arb_exit", "mid", "paper_literal"):
        assert np.isclose(q_lp(a0, a1, directional_price(a1, p, p, c))[0], base)
