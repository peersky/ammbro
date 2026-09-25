"""§17.9 mandatory tests: price_at lookup against hand-checked
timestamps, and numeraire conversion on a constructed depeg datapoint.
Uses synthetic series (no downloaded data required)."""
import numpy as np
import pytest

from pipeline.benchmark import NumeraireCorrectedSeries, PriceSeries


def make_series(ts, px):
    s = PriceSeries.__new__(PriceSeries)
    s.ts = np.asarray(ts, dtype=np.int64)
    s.px = np.asarray(px, dtype=np.float64)
    s.symbol = "TEST"
    return s


T0 = 1_750_000_000_000_000  # µs epoch, mid-2025


def test_exact_and_between_and_before():
    s = make_series([T0, T0 + 1_000_000, T0 + 2_000_000], [100.0, 101.0, 102.0])
    assert s.price_at(T0) == 100.0                    # exact hit
    assert s.price_at(T0 + 500_000) == 100.0          # between trades → last
    assert s.price_at(T0 + 1_999_999) == 101.0        # just before next
    assert np.isnan(s.price_at(T0 - 1))               # before first trade


def test_horizon_shift():
    s = make_series([T0, T0 + 12_000_000], [100.0, 110.0])
    assert s.price_at(T0, horizon_s=0) == 100.0
    assert s.price_at(T0, horizon_s=12) == 110.0
    assert s.price_at(T0, horizon_s=11.999) == 100.0


def test_vectorized_lookup():
    s = make_series([T0, T0 + 1_000_000], [100.0, 101.0])
    out = s.price_at(np.array([T0, T0 + 1_500_000]))
    assert list(out) == [100.0, 101.0]


def test_numeraire_depeg_correction():
    # Constructed depeg: ETHUSDT flat at 2000, USDC trades at 0.95 USDT.
    # ETH in USDC terms must be 2000/0.95, not 2000 (§17.6).
    eth = make_series([T0], [2000.0])
    usdc = make_series([T0], [0.95])
    n = NumeraireCorrectedSeries(eth=eth, usdc=usdc)
    assert n.price_at(T0) == pytest.approx(2000.0 / 0.95)
