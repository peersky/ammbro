"""Benchmark price series: price_at(timestamp, horizon) lookups over
parsed aggTrades, numeraire correction, and derived fixed-resolution bars.

Native ticks are canonical (§17.4 — do not pre-bucket coarser than 1s
for scoring). Bars (50ms/250ms) are a derived convenience layer for
inspection/plots, built by `build_bars`.

Numeraire (§17.6): the pool is ETH/USDC, the liquid benchmark is
ETH/USDT. `NumeraireCorrectedSeries` divides ETHUSDT by USDCUSDT to get
ETH in USDC terms. Mandatory on tail/depeg days, cheap enough to use
everywhere — so use it everywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BAR_RESOLUTIONS_MS, BARS_DIR, PARQUET_DIR, SYMBOLS


class PriceSeries:
    """Last-trade price lookup over one symbol's full parquet history.

    price_at(t_us, h_s): price of the last trade at or before t + h.
    Vectorized via searchsorted; O(log n) per lookup.
    """

    def __init__(self, symbol: str):
        src = sorted((PARQUET_DIR / "aggTrades" / symbol).glob("*.parquet"))
        if not src:
            raise FileNotFoundError(f"no parquet for {symbol}; run binance_parse")
        df = pd.concat((pd.read_parquet(p, columns=["ts_us", "price"]) for p in src))
        df = df.sort_values("ts_us")
        self.ts = df["ts_us"].to_numpy(dtype=np.int64)
        self.px = df["price"].to_numpy(dtype=np.float64)
        self.symbol = symbol

    def price_at(self, t_us, horizon_s: float = 0.0):
        """t_us: scalar or array of µs epoch timestamps. Returns price(s)
        of last trade <= t + horizon. NaN where t precedes first trade."""
        t = np.asarray(t_us, dtype=np.int64) + int(horizon_s * 1_000_000)
        idx = np.searchsorted(self.ts, t, side="right") - 1
        out = np.where(idx >= 0, self.px[np.clip(idx, 0, None)], np.nan)
        return float(out) if np.isscalar(t_us) else out


class NumeraireCorrectedSeries:
    """Risky asset in USDC terms: <bench>USDT / USDCUSDT at the same instant
    (§17.6). Defaults to the active chain's study-pool benchmark
    (mainnet / Arbitrum: ETHUSDT; HyperEVM: HYPEUSDT perp)."""

    def __init__(self, eth: PriceSeries | None = None, usdc: PriceSeries | None = None):
        from .pools import STUDY_POOL
        self.eth = eth or PriceSeries(STUDY_POOL.bench)
        self.usdc = usdc or PriceSeries(STUDY_POOL.numeraire)

    def price_at(self, t_us, horizon_s: float = 0.0):
        return self.eth.price_at(t_us, horizon_s) / self.usdc.price_at(t_us, horizon_s)


def build_bars(symbol: str, resolution_ms: int) -> Path:
    """Resample ticks to fixed-interval last-price bars (forward-filled).

    Output: ts_us (bar open time), price (last trade at or before bar
    close), plus per-bar volume and trade count where the bar had trades.
    """
    src = sorted((PARQUET_DIR / "aggTrades" / symbol).glob("*.parquet"))
    if not src:
        raise FileNotFoundError(f"no parquet for {symbol}; run binance_parse")
    out_dir = BARS_DIR / f"{resolution_ms}ms" / symbol
    out_dir.mkdir(parents=True, exist_ok=True)

    step = resolution_ms * 1000  # µs
    last_path = None
    for p in src:
        out = out_dir / (p.stem + f".{resolution_ms}ms.parquet")
        last_path = out
        if out.exists():
            continue
        df = pd.read_parquet(p)
        df["bar"] = (df["ts_us"] // step) * step
        g = df.groupby("bar")
        bars = pd.DataFrame(
            {
                "price": g["price"].last(),
                "volume": g["qty"].sum(),
                "n_trades": g["price"].size(),
            }
        )
        # Dense grid + ffill so every interval has a defined last price.
        grid = np.arange(bars.index.min(), bars.index.max() + step, step)
        bars = bars.reindex(grid)
        bars["price"] = bars["price"].ffill()
        bars[["volume", "n_trades"]] = bars[["volume", "n_trades"]].fillna(0)
        bars.index.name = "ts_us"
        bars.reset_index().to_parquet(out, index=False)
        print(f"  wrote {out.name}: {len(bars):,} bars")
    return last_path


def main() -> None:
    symbols = sys.argv[1:] or SYMBOLS
    for symbol in symbols:
        for res in BAR_RESOLUTIONS_MS:
            print(f"{symbol} @ {res}ms")
            build_bars(symbol, res)


if __name__ == "__main__":
    main()
