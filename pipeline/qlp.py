"""q_LP definition (§17.2) and per-swap preparation for scoring.

`q_lp` is the LP-perspective markout, direction-free. `score_pool`
prepares each swap for Study E, which writes the canonical q_LP
(canonical.py): user-based positions and notional valued at the
benchmark's last trade at block time. No q is written here.

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
from .config import ONCHAIN_DIR
from .pools import POOLS, Pool
from .normalization import block_time_us, to_user_positions

SWAPS_DIR = ONCHAIN_DIR / "swaps"
SCORED_DIR = ONCHAIN_DIR / "scored"


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
    if pool.kind == "risky":
        return NumeraireCorrectedSeries(PriceSeries(pool.bench), PriceSeries(pool.numeraire))
    if pool.kind == "stable":
        return _InverseSeries(PriceSeries(pool.bench))
    raise ValueError(pool.kind)


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
        df = to_user_positions(pd.read_parquet(p))
        a0 = df["amount0_raw"].astype(float) / 10**pool.dec0
        a1 = df["amount1_raw"].astype(float) / 10**pool.dec1
        p1 = series.price_at(block_time_us(df))
        df["notional_token0"] = q_lp(a0.to_numpy(), a1.to_numpy(), p1)[1]
        df.to_parquet(out, index=False)
        print(f"  wrote {out.name}: {len(df):,} prepared")


def main() -> None:
    names = sys.argv[1:]
    for pool in POOLS:
        if names and pool.name not in names:
            continue
        print(pool.name)
        score_pool(pool)


if __name__ == "__main__":
    main()
