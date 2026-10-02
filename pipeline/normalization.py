"""Block instants and positions on every chain.

    block_time_us      the instant a swap is scored at (canonical.py): the
                       slot timestamp on mainnet, a sub-second reconstruction
                       on L2s whose blocks are shorter than their timestamps
    subsecond_split    that reconstruction: the N blocks sharing a second
                       placed at S + (k + ½)/N (paper §3.4)
    to_user_positions  tx_index / tx_count counted over user transactions

Every swap in a block is scored at one instant (position-invariant,
P§3.4); intra-block position is only used to describe ordering.
"""
from __future__ import annotations

import pandas as pd

from .chains import ACTIVE


def to_user_positions(df: pd.DataFrame) -> pd.DataFrame:
    """Re-base tx_index / tx_count onto user transactions. Arbitrum puts
    an ArbOS internal tx (type 0x6a, from 0x…A4B05) at index 0 of every
    block, so its first user tx sits at index 1; every position rule
    (top of block, index buckets, intra-block fraction) means user
    position. Raw index kept as tx_index_raw. No-op on mainnet."""
    k = ACTIVE.system_txs
    if not k or "tx_index_raw" in df.columns:
        return df
    df = df.copy()
    df["tx_index_raw"] = df["tx_index"]
    df["tx_index"] = df["tx_index"] - k
    if "tx_count" in df.columns:
        df["tx_count"] = (df["tx_count"] - k).clip(lower=1)
    return df


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
