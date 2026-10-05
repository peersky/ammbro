"""Pool census for Study K3 (small pools): swaps, accounts and USD volume for a
set of Uniswap v3 mainnet pools spanning sizes, over the study window.

Per pool: Swap logs (batched eth_getLogs), each swap's sender account (tx.from,
batched eth_getTransactionByHash) and USD notional through the pool's stable or
WETH leg (WETH at the daily median ETH price of the study pool). Block times
are interpolated on the 12s slot grid from the study pool's ~595k known
blocks (blocksim's method) — no header calls.

RPC use: ~265 getLogs per pool + one call per unique tx, paced by rpc.py.
Mainnet only (Chain registry: mainnet).
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from . import rpc
from .chains import ACTIVE, Pool
from .config import ONCHAIN_DIR
from .extract_swaps import LOG_CHUNK, SWAP_TOPIC, _decode_log, fetch_tx_meta
from .pools import STUDY_POOL

OUT = ONCHAIN_DIR / "census"
POOLS = [   # verified on-chain 2026-10-05: token0/token1/fee/decimals
    (Pool("usdc_weth_030", "0x8ad599c3a0ff1de082011efddc58f1908eb6e6d8", "USDC", "WETH", 6, 18), "usd0"),
    (Pool("wbtc_weth_005", "0x4585fe77225b41b697c938b018e2ac67ac5a20c0", "WBTC", "WETH", 8, 18), "weth1"),
    (Pool("link_weth_030", "0xa6cc3c2531fdaa6ae1a3ca84c2855806728693e8", "LINK", "WETH", 18, 18), "weth1"),
    (Pool("uni_weth_030", "0x1d42064fc4beb5f8aaf85f4617ae8b3b5b8bd801", "UNI", "WETH", 18, 18), "weth1"),
    (Pool("pepe_weth_030", "0x11950d141ecb863f01007add7d1a342041227b58", "PEPE", "WETH", 18, 18), "weth1"),
    (Pool("dai_usdc_001", "0x5777d92f208679db4b9778590fa3cab3ac9e2168", "DAI", "USDC", 18, 6), "usd1"),
]
BATCH = 20
TX_CHUNK = 20_000           # sender lookups saved every this many txs


def study_pool_clock() -> tuple[np.ndarray, np.ndarray, pd.Series]:
    """(known blocks, their timestamps, daily ETH price) from the study pool."""
    sw = pd.concat(pd.read_parquet(p, columns=["block_number", "block_ts", "amount0_raw", "amount1_raw"])
                   for p in sorted((ONCHAIN_DIR / "swaps" / STUDY_POOL.name).glob("*.parquet")))
    kb = sw.drop_duplicates("block_number").sort_values("block_number")
    a0 = sw["amount0_raw"].astype(float).abs() / 10**STUDY_POOL.dec0
    a1 = sw["amount1_raw"].astype(float).abs() / 10**STUDY_POOL.dec1
    eth = (a0 / a1).where(a1 > 1e-6).groupby(sw["block_ts"] // 86400).median()
    return kb["block_number"].to_numpy(), kb["block_ts"].to_numpy(), eth


def logs(pool: Pool, lo: int, hi: int) -> list[dict]:
    chunks = [(s, min(s + LOG_CHUNK - 1, hi)) for s in range(lo, hi + 1, LOG_CHUNK)]
    out = []
    for i in range(0, len(chunks), BATCH):
        reqs = [("eth_getLogs", [{"address": pool.address, "topics": [SWAP_TOPIC], "fromBlock": hex(a), "toBlock": hex(b)}])
                for a, b in chunks[i:i + BATCH]]
        for res in rpc.batch(reqs):
            out.extend(_decode_log(l, pool) for l in res)
        print(f"  {pool.name}: block {chunks[min(i + BATCH, len(chunks)) - 1][1]:,}/{hi:,} ({len(out):,} swaps)", flush=True)
    return out


def census_pool(pool: Pool, leg: str, clock) -> pd.DataFrame:
    """Checkpointed: swap logs saved first, sender lookups saved in chunks and
    resumed; the final file is written once both are complete."""
    path = OUT / f"{pool.name}.parquet"
    if path.exists():
        print(f"ok (exists) {path.name}")
        return pd.read_parquet(path)
    OUT.mkdir(parents=True, exist_ok=True)
    kb, kts, eth = clock
    logs_path = OUT / f"{pool.name}.logs.parquet"
    if logs_path.exists():
        df = pd.read_parquet(logs_path)
    else:
        df = pd.DataFrame(logs(pool, int(kb[0]), int(kb[-1])))     # the study pool's window
        if df.empty:
            return df
        for c in df.columns:      # 256-bit integers (amounts, sqrtPrice, liquidity) do not fit int64
            if df[c].dtype == object or df[c].map(lambda x: isinstance(x, int) and abs(x) >= 2**63).any():
                df[c] = df[c].astype(str)
        df.to_parquet(logs_path, index=False)
    parts = sorted(OUT.glob(f"{pool.name}.txs.*.parquet"))
    done = pd.concat([pd.read_parquet(p) for p in parts]) if parts else pd.DataFrame(columns=["tx_hash", "tx_from"])
    todo = sorted(set(df["tx_hash"]) - set(done["tx_hash"]))
    for i in range(0, len(todo), TX_CHUNK):
        meta = fetch_tx_meta(todo[i:i + TX_CHUNK], {})[["tx_hash", "tx_from"]]
        meta.to_parquet(OUT / f"{pool.name}.txs.{len(parts) + i // TX_CHUNK:04d}.parquet", index=False)
        print(f"  {pool.name}: tx senders {len(done) + i + len(meta):,}/{len(done) + len(todo):,}", flush=True)
    parts = sorted(OUT.glob(f"{pool.name}.txs.*.parquet"))
    tx = pd.concat(pd.read_parquet(p) for p in parts).drop_duplicates("tx_hash")
    ts = np.interp(df["block_number"].to_numpy(), kb, kts.astype(float))
    phase = int(kts[0]) % 12
    df["block_ts"] = (np.round((ts - phase) / 12) * 12 + phase).astype(np.int64)
    df = df.merge(tx, on="tx_hash", how="left")
    a0 = df["amount0_raw"].astype(float).abs() / 10**pool.dec0
    a1 = df["amount1_raw"].astype(float).abs() / 10**pool.dec1
    px = (df["block_ts"] // 86400).map(eth).to_numpy()
    df["usd"] = {"usd0": a0, "usd1": a1, "weth1": a1 * px}[leg]
    df.to_parquet(path, index=False)
    print(f"wrote {path.name}: {len(df):,} swaps, ${df['usd'].sum() / 1e9:.2f}B", flush=True)
    return df


def main() -> None:
    if ACTIVE.name != "mainnet":
        raise SystemExit("census: mainnet only")
    clock = study_pool_clock()
    names = sys.argv[1:]
    for pool, leg in POOLS:
        if names and pool.name not in names:
            continue
        census_pool(pool, leg, clock)


if __name__ == "__main__":
    main()
