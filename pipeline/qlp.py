"""q_LP scoring (§17.2) — LP-perspective markout, direction-free.

    LP_markout(h) = oracle_value(received) − oracle_value(sent)
    q_LP(h)       = LP_markout(h) / notional

Amounts are POOL-perspective signed deltas (>0 received, <0 sent), so
with every leg valued at the benchmark price the markout is simply the
sum of signed values — no per-side negation anywhere (unit-tested both
directions).

Numeraire is token0 (USDC for both study pools). `price1_in_0` is the
benchmark price of token1 in token0 terms at t+h:
  - ETH/USDC pool:  ETHUSDT / USDCUSDT  (NumeraireCorrectedSeries)
  - USDC/USDT pool: 1 / USDCUSDT        (USDT valued in USDC)
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from .benchmark import NumeraireCorrectedSeries, PriceSeries
from .config import DATA_DIR, HORIZONS_S
from .pools import ETH_USDC, POOLS, USDC_USDT, Pool
from .normalization import normalized_time_us

SWAPS_DIR = DATA_DIR / "onchain" / "swaps"
SCORED_DIR = DATA_DIR / "onchain" / "scored"


def q_lp(amount0: np.ndarray, amount1: np.ndarray, price1_in_0: np.ndarray):
    """Vectorized q_LP. Amounts decimal-adjusted, pool-perspective signed.
    Returns (q, notional_token0)."""
    markout = amount0 + amount1 * price1_in_0
    notional = (np.abs(amount0) + np.abs(amount1) * price1_in_0) / 2.0
    with np.errstate(invalid="ignore", divide="ignore"):
        q = np.where(notional > 0, markout / notional, np.nan)
    return q, notional


class _InverseSeries:
    """price of token1 in token0 when the benchmark quotes token0 in token1
    (USDCUSDT quotes USDC in USDT; we need USDT in USDC)."""

    def __init__(self, inner: PriceSeries):
        self.inner = inner

    def price_at(self, t_us, horizon_s: float = 0.0):
        return 1.0 / self.inner.price_at(t_us, horizon_s)


def price1_series(pool: Pool):
    if pool.name == ETH_USDC.name:
        return NumeraireCorrectedSeries()
    if pool.name == USDC_USDT.name:
        return _InverseSeries(PriceSeries("USDCUSDT"))
    raise ValueError(pool.name)


def score_pool(pool: Pool) -> None:
    src = sorted((SWAPS_DIR / pool.name).glob("*.parquet"))
    if not src:
        raise SystemExit(f"no swaps for {pool.name}; run extract_swaps first")
    out_dir = SCORED_DIR / pool.name
    out_dir.mkdir(parents=True, exist_ok=True)
    series = price1_series(pool)

    for p in src:
        out = out_dir / p.name.replace(".parquet", ".scored.parquet")
        if out.exists():
            print(f"  ok (exists) {out.name}")
            continue
        df = pd.read_parquet(p)
        a0 = df["amount0_raw"].astype(float) / 10**pool.dec0
        a1 = df["amount1_raw"].astype(float) / 10**pool.dec1
        t_us = normalized_time_us(df)
        df["t_norm_us"] = t_us
        for h in HORIZONS_S:
            p1 = series.price_at(t_us.to_numpy(), horizon_s=h)
            q, notional = q_lp(a0.to_numpy(), a1.to_numpy(), p1)
            df[f"q_lp_h{h}"] = q
            if h == HORIZONS_S[0]:
                df["notional_token0"] = notional
        df.to_parquet(out, index=False)
        print(f"  wrote {out.name}: {len(df):,} scored")


def main() -> None:
    names = sys.argv[1:]
    for pool in POOLS:
        if names and pool.name not in names:
            continue
        print(pool.name)
        score_pool(pool)


if __name__ == "__main__":
    main()
