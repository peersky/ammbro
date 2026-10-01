"""Intra-block position normalization (§17.7) — standalone, pluggable.

Ethereum L1 has no per-tx timestamps; reconstruct a synthetic intra-block
timeline:

    block_duration      = next_block_ts − block_ts        # typically 12s
    normalized_position = tx_index / tx_count × block_duration
    t_norm              = block_ts + normalized_position

This is a NOISY PROXY (builders reorder; execution is not uniform in
time). Any position↔divergence correlation survives the noise, it is not
precise. Alternative strategies (e.g. gas-weighted) plug in here without
touching the rest of the pipeline.
"""
from __future__ import annotations

import pandas as pd

from .chains import ACTIVE

DEFAULT_BLOCK_S = ACTIVE.slot_s or 1   # mainnet 12s slots; L2 blocks are <= 1s


def uniform_normalized_position_s(
    tx_index: pd.Series, tx_count: pd.Series, block_duration_s: pd.Series
) -> pd.Series:
    """Seconds into the block under the uniform-time assumption."""
    frac = tx_index / tx_count.clip(lower=1)
    return frac * block_duration_s


def normalized_time_us(df: pd.DataFrame) -> pd.Series:
    """t_norm in µs epoch from a swaps frame with block_ts, next_block_ts,
    tx_index, tx_count columns."""
    if "block_ts_us" in df.columns and df["block_ts_us"].notna().all():
        # L2: blocks are shorter than their 1s timestamps; spread the block's
        # transactions over the block's own slice of its second (1/N s,
        # centred on block_ts_us — see subsecond_split), not a whole second.
        n = df["blocks_in_second"].where(df["blocks_in_second"] > 0, 1)
        slice_us = 1_000_000 / n
        frac = df["tx_index"] / df["tx_count"].clip(lower=1)
        return (df["block_ts_us"] - slice_us / 2 + frac * slice_us).astype("int64")
    dur = (df["next_block_ts"] - df["block_ts"]).fillna(DEFAULT_BLOCK_S).clip(1, 60)
    pos = uniform_normalized_position_s(df["tx_index"], df["tx_count"], dur)
    return ((df["block_ts"] + pos) * 1_000_000).astype("int64")


def subsecond_split(block: int, lo: int, hi: int, ts_s: int) -> int:
    """Sub-second time (µs) of a block whose timestamp has 1s resolution.

    On chains producing several blocks per second (Arbitrum ~4/s) the N
    blocks lo..hi sharing timestamp `ts_s` are spread uniformly across that
    second; block k-th of N is placed at the midpoint of its slice:
    ts_s + (k + 0.5) / N. On a chain with one block per second this is
    ts_s + 0.5. A reconstruction for measurement only — see paper §3.4.
    """
    n = hi - lo + 1
    k = block - lo
    if not (0 <= k < n):
        raise ValueError("block outside its second's block range")
    return int(round((ts_s + (k + 0.5) / n) * 1_000_000))


def block_time_us(df: pd.DataFrame):
    """Block instant in µs: the sub-second reconstruction where the chain
    needed one (L2s; column block_ts_us), else block_ts (mainnet: the slot
    timestamp, exact to the second and sufficient at 12s blocks)."""
    import numpy as np
    if "block_ts_us" in df.columns and df["block_ts_us"].notna().all():
        return df["block_ts_us"].to_numpy(np.int64)
    return df["block_ts"].to_numpy(np.int64) * 1_000_000
