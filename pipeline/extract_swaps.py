"""Extract Uniswap v3 Swap events for the study pools via RPC getLogs,
then enrich with block context (timestamp, tx count, next-block
timestamp, base fee) and tx context (from, to, priority fee).

Output: data/onchain/swaps/<pool>/<pool>-YYYY-MM.parquet with
pool-perspective raw token deltas (needed for q_LP, §17.2) and the
fields the normalization module (§17.7) and label stage consume.

Deterministic given the window in config.py; re-runnable (skips months
whose parquet already exists).

Chain-aware (pipeline/chains.py): endpoint, log chunk size and pools come
from the ACTIVE chain. Pools with flip=True (on-chain order risky/stable)
are stored in canonical (stable, risky) order: amounts swapped, tick
negated. A non-zero `blockTimestamp` in logs is cross-checked against the
header (Arbitrum's endpoint fills it on only ~80% of logs, 0x0 on the rest, so headers are always used); L2 chains (header_successors=False) fetch headers only for swap
blocks (tx count, base fee) and set next_block_ts = block_ts + 1s (their
blocks are <= 1s; timestamps have 1s resolution).
"""
from __future__ import annotations

import datetime as dt
import sys

import pandas as pd

from . import rpc
from .config import DATA_DIR, months_in_window, ONCHAIN_DIR
from .chains import ACTIVE
from .pools import POOLS, SWAP_TOPIC, Pool

ONCHAIN_DIR = ONCHAIN_DIR / "swaps"
LOG_CHUNK = ACTIVE.log_chunk   # blocks per getLogs call (endpoint limit per chain)
BLOCK_BATCH = 200     # blocks per JSON-RPC batch
TX_BATCH = 200        # txs per JSON-RPC batch (endpoint token bucket ~450/s)


def _int256(hex32: str) -> int:
    v = int(hex32, 16)
    return v - (1 << 256) if v >= (1 << 255) else v


def _decode_log(log: dict, pool: Pool | None = None) -> dict:
    data = log["data"][2:]
    words = [data[i : i + 64] for i in range(0, len(data), 64)]
    a0, a1, tick = _int256(words[0]), _int256(words[1]), _int256(words[4])
    if pool is not None and pool.flip:          # store canonical (stable, risky) order
        a0, a1, tick = a1, a0, -tick
    out = {
        "block_number": rpc.hex_int(log["blockNumber"]),
        "tx_hash": log["transactionHash"],
        "tx_index": rpc.hex_int(log["transactionIndex"]),
        "log_index": rpc.hex_int(log["logIndex"]),
        "sender": "0x" + log["topics"][1][-40:],
        "recipient": "0x" + log["topics"][2][-40:],
        "amount0_raw": a0,
        "amount1_raw": a1,
        "tick": tick,
    }
    lts = rpc.hex_int(log.get("blockTimestamp")) if log.get("blockTimestamp") else 0
    if lts:                       # Arbitrum's endpoint returns the field as 0x0 — treat as absent
        out["log_block_ts"] = lts
    return out


def fetch_logs(pool: Pool, from_block: int, to_block: int) -> list[dict]:
    out = []
    for start in range(from_block, to_block + 1, LOG_CHUNK):
        end = min(start + LOG_CHUNK - 1, to_block)
        logs = rpc.call(
            "eth_getLogs",
            [{
                "address": pool.address,
                "topics": [SWAP_TOPIC],
                "fromBlock": hex(start),
                "toBlock": hex(end),
            }],
        )
        out.extend(_decode_log(l, pool) for l in logs)
        if (start - from_block) % (LOG_CHUNK * 40) == 0:
            print(f"  logs {pool.name}: block {start:,}/{to_block:,} ({len(out):,} swaps)")
    return out


def load_block_meta(block_numbers: list[int]) -> pd.DataFrame:
    """Prefer the BigQuery-sourced local blocks table (blocks_bq.py);
    fall back to paced RPC header fetches when it is absent or does not
    cover the requested range."""
    from .blocks_bq import BLOCKS_PARQUET

    if BLOCKS_PARQUET.exists():
        blocks = pd.read_parquet(BLOCKS_PARQUET)
        need = pd.Series(sorted(set(block_numbers)))
        covered = need.isin(blocks["block_number"])
        if covered.all():
            out = blocks[blocks["block_number"].isin(need)].copy()
            print(f"  blocks: {len(out):,} from local BigQuery table")
            return out[["block_number", "block_ts", "tx_count", "base_fee_wei", "next_block_ts"]]
        print(f"  blocks table missing {(~covered).sum():,} blocks; falling back to RPC")
    return fetch_block_meta(block_numbers)


def fetch_block_meta(block_numbers: list[int]) -> pd.DataFrame:
    """Header-only blocks: timestamp, tx count, base fee. On mainnet also
    each block's successor so next_block_time is available for §17.7; L2
    chains skip successors (next_block_ts = block_ts + 1s)."""
    if ACTIVE.header_successors:
        need = sorted(set(block_numbers) | {b + 1 for b in block_numbers})
    else:
        need = sorted(set(block_numbers))
    rows = {}
    for i in range(0, len(need), BLOCK_BATCH):
        chunk = need[i : i + BLOCK_BATCH]
        res = rpc.batch([("eth_getBlockByNumber", [hex(n), False]) for n in chunk])
        for n, blk in zip(chunk, res):
            rows[n] = {
                "block_ts": rpc.hex_int(blk["timestamp"]),
                "tx_count": len(blk["transactions"]),
                "base_fee_wei": rpc.hex_int(blk.get("baseFeePerGas")) or 0,
            }
        if i % (BLOCK_BATCH * 25) == 0:
            print(f"  blocks: {i:,}/{len(need):,}")
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "block_number"
    df = df.reset_index()
    if ACTIVE.header_successors:
        nxt = df.set_index("block_number")["block_ts"]
        df["next_block_ts"] = df["block_number"].map(lambda n: nxt.get(n + 1))
    else:
        df["next_block_ts"] = df["block_ts"] + 1
        df = df.merge(resolve_seconds(df.set_index("block_number")["block_ts"].to_dict()), on="block_number")
    return df


MAX_SECOND_ROUNDS = 12   # Arbitrum makes ~4 blocks/s; give up (and fall back to mid-second) beyond this


def resolve_seconds(ts: dict[int, int]) -> pd.DataFrame:
    """For every block in `ts` (known header timestamps, 1s resolution),
    find the first and last block sharing its timestamp by fetching
    neighbouring headers in batched rounds, then place it at the midpoint
    of its slice of the second (normalization.subsecond_split)."""
    from .normalization import subsecond_split
    known = dict(ts)
    lo = {b: b for b in ts}; hi = {b: b for b in ts}
    open_lo, open_hi = set(ts), set(ts)
    for _ in range(MAX_SECOND_ROUNDS):
        want = sorted({lo[b] - 1 for b in open_lo} | {hi[b] + 1 for b in open_hi})
        want = [n for n in want if n not in known]
        for i in range(0, len(want), BLOCK_BATCH):
            chunk = want[i : i + BLOCK_BATCH]
            res = rpc.batch([("eth_getBlockByNumber", [hex(n), False]) for n in chunk])
            for n, blk in zip(chunk, res):
                if blk is not None:
                    known[n] = rpc.hex_int(blk["timestamp"])
        for b in list(open_lo):
            if known.get(lo[b] - 1) == ts[b]:
                lo[b] -= 1
            else:
                open_lo.discard(b)
        for b in list(open_hi):
            if known.get(hi[b] + 1) == ts[b]:
                hi[b] += 1
            else:
                open_hi.discard(b)
        if not open_lo and not open_hi:
            break
    rows = []
    for b, s in ts.items():
        resolved = b not in open_lo and b not in open_hi
        rows.append({"block_number": b,
                     "block_ts_us": subsecond_split(b, lo[b], hi[b], s) if resolved else s * 1_000_000 + 500_000,
                     "blocks_in_second": hi[b] - lo[b] + 1 if resolved else -1})
    return pd.DataFrame(rows)


def fetch_tx_meta(tx_hashes: list[str], base_fee_by_block: dict[int, int]) -> pd.DataFrame:
    rows = []
    hashes = sorted(set(tx_hashes))
    for i in range(0, len(hashes), TX_BATCH):
        chunk = hashes[i : i + TX_BATCH]
        res = rpc.batch([("eth_getTransactionByHash", [h]) for h in chunk])
        for h, tx in zip(chunk, res):
            bn = rpc.hex_int(tx["blockNumber"])
            base = base_fee_by_block.get(bn, 0)
            max_fee = rpc.hex_int(tx.get("maxFeePerGas"))
            max_prio = rpc.hex_int(tx.get("maxPriorityFeePerGas"))
            if max_prio is not None and max_fee is not None:
                prio = min(max_prio, max_fee - base)
            else:  # legacy tx
                prio = (rpc.hex_int(tx.get("gasPrice")) or 0) - base
            rows.append({
                "tx_hash": h,
                "tx_from": tx["from"],
                "tx_to": tx.get("to"),
                "priority_fee_wei": max(prio, 0),
            })
        if i % (TX_BATCH * 20) == 0:
            print(f"  txs: {i:,}/{len(hashes):,}")
    return pd.DataFrame(rows)


def _month_bounds(month: str) -> tuple[int, int]:
    y, m = map(int, month.split("-"))
    start = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=dt.timezone.utc)
    return int(start.timestamp()), int(end.timestamp())


def extract_pool_month(pool: Pool, month: str) -> None:
    out_dir = ONCHAIN_DIR / pool.name
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{pool.name}-{month}.parquet"
    if out.exists():
        print(f"{pool.name} {month}: exists, skipping")
        return

    start_ts, end_ts = _month_bounds(month)
    b0 = rpc.find_block_at_or_after(start_ts)
    b1 = rpc.find_block_at_or_after(end_ts) - 1
    print(f"{pool.name} {month}: blocks {b0:,}..{b1:,}")

    swaps = pd.DataFrame(fetch_logs(pool, b0, b1))
    print(f"{pool.name} {month}: {len(swaps):,} swaps")
    if swaps.empty:
        return

    # Tx-level meta (from/to/priority fee) is fetched later by
    # extract_txs.py — it is only needed at the labels/redirection stage
    # and would double the RPC call count on the q_LP critical path.
    blocks = load_block_meta(swaps["block_number"].unique().tolist())
    df = swaps.merge(blocks, on="block_number")
    if "log_block_ts" in df.columns:          # endpoint-provided timestamps must agree with headers
        has = df["log_block_ts"].notna()      # Arbitrum fills the field on only some logs
        bad = (df.loc[has, "log_block_ts"] != df.loc[has, "block_ts"]).sum()
        if bad:
            raise RuntimeError(f"{bad} swaps whose log blockTimestamp disagrees with the header")
        df = df.drop(columns=["log_block_ts"])
    # int256 token deltas overflow parquet int64 (any swap > 9.2 WETH in
    # wei) — persist as lossless strings; consumers cast to float.
    df["amount0_raw"] = df["amount0_raw"].astype(str)
    df["amount1_raw"] = df["amount1_raw"].astype(str)
    df.sort_values(["block_number", "log_index"]).to_parquet(out, index=False)
    print(f"  wrote {out.name}: {len(df):,} swaps")


def main() -> None:
    names = sys.argv[1:]
    # Months outer so the USDC/USDT control pool gets data early — the
    # calm-period gate (§17.9 step 3b) must run before study results.
    for month in months_in_window():
        for pool in POOLS:
            if names and pool.name not in names:
                continue
            extract_pool_month(pool, month)


if __name__ == "__main__":
    main()
