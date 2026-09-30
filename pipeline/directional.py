"""Directional (bid/ask) benchmark proxy for Study D (P§3.6, P§4.2).

The paper scores against Chainlink Data Streams LWBA bid/ask. Until the
Layer-1 feed arrives, a touch-level proxy is built from Binance aggTrades
using the aggressor flag:

    is_buyer_maker = False  -> buyer lifted the offer -> print at the ASK
    is_buyer_maker = True   -> seller hit the bid     -> print at the BID

At time t the proxy quote is the last print on each side, bounded by the
last print overall so a stale side can never cross the book:

    bid = min(last_bid_print, last_print)
    ask = max(last_ask_print, last_print)

This is TOUCH, not depth-weighted: LWBA spreads are wider for size, so
the proxy understates how much the directional rule relaxes scoring on
large trades. Stated in every D output.

Composition to ETH in USDC (P§4.2: buy-leg-ask over sell-leg-bid):

    ask_eth_usdc = ETHUSDT_ask / USDCUSDT_bid
    bid_eth_usdc = ETHUSDT_bid / USDCUSDT_ask

Two conventions for which side values the pool's ETH leg, because the
paper's text and its stated intent disagree (open paper item):

    arb_exit       pool sends ETH -> bid, pool receives ETH -> ask.
                   The price an arb can exit at; leaves a no-flag band
                   [bid, ask] that widens with the spread. Matches the
                   paper's stated intent (volatility-tolerant, permissive).
    paper_literal  pool sends ETH -> ask, pool receives ETH -> bid.
                   The literal sentence in P§3.6/P§4.2; flags MORE flow
                   as the spread widens.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import PARQUET_DIR


class SidedSeries:
    """Last bid-side and ask-side prints for one symbol."""

    def __init__(self, ts_bid, px_bid, ts_ask, px_ask, symbol: str = ""):
        self.ts_b = np.asarray(ts_bid, dtype=np.int64)
        self.px_b = np.asarray(px_bid, dtype=np.float64)
        self.ts_a = np.asarray(ts_ask, dtype=np.int64)
        self.px_a = np.asarray(px_ask, dtype=np.float64)
        self.symbol = symbol

    @classmethod
    def load(cls, symbol: str) -> "SidedSeries":
        src = sorted((PARQUET_DIR / "aggTrades" / symbol).glob("*.parquet"))
        if not src:
            raise FileNotFoundError(f"no parquet for {symbol}; run binance_parse")
        df = pd.concat(
            pd.read_parquet(p, columns=["ts_us", "price", "is_buyer_maker"]) for p in src
        ).sort_values("ts_us", kind="stable")
        bid = df["is_buyer_maker"].to_numpy()
        ts = df["ts_us"].to_numpy(dtype=np.int64)
        px = df["price"].to_numpy(dtype=np.float64)
        return cls(ts[bid], px[bid], ts[~bid], px[~bid], symbol)

    def quotes(self, t_us, horizon_s: float = 0.0) -> dict:
        """Bounded bid/ask at t + h, plus diagnostics. NaN before the
        first print on either side."""
        t = np.asarray(t_us, dtype=np.int64) + int(horizon_s * 1_000_000)
        ib = np.searchsorted(self.ts_b, t, side="right") - 1
        ia = np.searchsorted(self.ts_a, t, side="right") - 1
        ok = (ib >= 0) & (ia >= 0)
        ib_c, ia_c = np.clip(ib, 0, None), np.clip(ia, 0, None)
        bid_raw, ask_raw = self.px_b[ib_c], self.px_a[ia_c]
        tb, ta = self.ts_b[ib_c], self.ts_a[ia_c]
        last = np.where(ta >= tb, ask_raw, bid_raw)
        nan = np.where(ok, 1.0, np.nan)
        return {
            "bid": np.minimum(bid_raw, last) * nan,
            "ask": np.maximum(ask_raw, last) * nan,
            "crossed_raw": ok & (bid_raw > ask_raw),
            "stale_bid_s": (t - tb) / 1e6,
            "stale_ask_s": (t - ta) / 1e6,
        }


def compose_eth_usdc(eth: dict, usdc: dict) -> tuple[np.ndarray, np.ndarray]:
    """ETH priced in USDC from ETHUSDT and USDCUSDT sided quotes."""
    return eth["bid"] / usdc["ask"], eth["ask"] / usdc["bid"]


def directional_price(amount1: np.ndarray, bid: np.ndarray, ask: np.ndarray, convention: str) -> np.ndarray:
    """Price of token1 in token0 used to value the pool's token1 leg.
    amount1 < 0 means the pool SENT token1."""
    sent = amount1 < 0
    if convention == "arb_exit":
        return np.where(sent, bid, ask)
    if convention == "paper_literal":
        return np.where(sent, ask, bid)
    if convention == "mid":
        return (bid + ask) / 2.0
    raise ValueError(convention)
