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

DEFAULT_BLOCK_S = 12


def uniform_normalized_position_s(
    tx_index: pd.Series, tx_count: pd.Series, block_duration_s: pd.Series
) -> pd.Series:
    """Seconds into the block under the uniform-time assumption."""
    frac = tx_index / tx_count.clip(lower=1)
    return frac * block_duration_s


def normalized_time_us(df: pd.DataFrame) -> pd.Series:
    """t_norm in µs epoch from a swaps frame with block_ts, next_block_ts,
    tx_index, tx_count columns."""
    dur = (df["next_block_ts"] - df["block_ts"]).fillna(DEFAULT_BLOCK_S).clip(1, 60)
    pos = uniform_normalized_position_s(df["tx_index"], df["tx_count"], dur)
    return ((df["block_ts"] + pos) * 1_000_000).astype("int64")
