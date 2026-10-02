"""Export swaps from the self-hosted envio indexer's postgres into the
same monthly parquet schema extract_swaps.py produces, so q_LP scoring
is source-agnostic. Adds tx meta (from/to/priority fee) that the RPC
extractor defers to extract_txs.py.

Missing vs the RPC path: per-block tx_count / next_block_ts / base_fee —
joined from the RPC block-meta already present in the extractor output,
or fetched via fetch_block_meta when absent.

Usage: python -m pipeline.export_indexer   (indexer must have synced the window)
"""
from __future__ import annotations

import pandas as pd
import sqlalchemy as sa

from .config import DATA_DIR, ONCHAIN_DIR
from .extract_swaps import fetch_block_meta
from .pools import POOLS

PG_URL = "postgresql://postgres:testing@localhost:5433/envio-dev"
OUT_DIR = ONCHAIN_DIR / "swaps_indexer"


def export_tx_meta() -> None:
    """Write the .txs.parquet files labels.py expects (tx_from/tx_to/
    priority fee per tx_hash) from the indexer's postgres — replaces the
    RPC extract_txs stage entirely."""
    eng = sa.create_engine(PG_URL)
    for pool in POOLS:
        out_dir = ONCHAIN_DIR / "txs" / pool.name
        out_dir.mkdir(parents=True, exist_ok=True)
        df = pd.read_sql(
            sa.text(
                'SELECT DISTINCT ON ("txHash") "txHash" AS tx_hash, "txFrom" AS tx_from, '
                '"txTo" AS tx_to, "blockTimestamp" AS block_ts, '
                '"maxPriorityFeePerGas", "maxFeePerGas", "gasPrice" '
                'FROM "public"."Swap" WHERE pool = :p'
            ),
            eng,
            params={"p": pool.address.lower()},
        )
        if df.empty:
            print(f"{pool.name}: no rows")
            continue
        df["month"] = pd.to_datetime(df["block_ts"], unit="s", utc=True).dt.strftime("%Y-%m")
        for month, g in df.groupby("month"):
            out = out_dir / f"{pool.name}-{month}.txs.parquet"
            cols = ["tx_hash", "tx_from", "tx_to", "maxPriorityFeePerGas", "maxFeePerGas", "gasPrice"]
            gg = g[cols].copy()
            for c in cols[3:]:
                gg[c] = gg[c].astype("float64")
            gg.to_parquet(out, index=False)
            print(f"  wrote {out.name}: {len(gg):,} txs")


def main() -> None:
    import sys
    if "--txs-only" in sys.argv:
        export_tx_meta()
        return
    eng = sa.create_engine(PG_URL)
    for pool in POOLS:
        out_dir = OUT_DIR / pool.name
        out_dir.mkdir(parents=True, exist_ok=True)
        df = pd.read_sql(
            sa.text('SELECT * FROM "public"."Swap" WHERE pool = :p ORDER BY "blockNumber", "logIndex"'),
            eng,
            params={"p": pool.address.lower()},
        )
        if df.empty:
            print(f"{pool.name}: no rows yet")
            continue
        df = df.rename(
            columns={
                "blockNumber": "block_number",
                "blockTimestamp": "block_ts",
                "txIndex": "tx_index",
                "logIndex": "log_index",
                "txHash": "tx_hash",
                "txFrom": "tx_from",
                "txTo": "tx_to",
                "amount0": "amount0_raw",
                "amount1": "amount1_raw",
            }
        )
        blocks = fetch_block_meta(df["block_number"].unique().tolist())
        df = df.merge(
            blocks[["block_number", "tx_count", "next_block_ts", "base_fee_wei"]],
            on="block_number",
            how="left",
        )
        prio = df[["maxPriorityFeePerGas", "maxFeePerGas", "gasPrice", "base_fee_wei"]].astype("float64")
        df["priority_fee_wei"] = (
            prio["maxPriorityFeePerGas"]
            .combine(prio["maxFeePerGas"] - prio["base_fee_wei"], min)
            .fillna(prio["gasPrice"] - prio["base_fee_wei"])
            .clip(lower=0)
        )
        df["amount0_raw"] = df["amount0_raw"].astype(str)
        df["amount1_raw"] = df["amount1_raw"].astype(str)
        df["month"] = pd.to_datetime(df["block_ts"], unit="s", utc=True).dt.strftime("%Y-%m")
        for month, g in df.groupby("month"):
            out = out_dir / f"{pool.name}-{month}.parquet"
            g.drop(columns=["month"]).to_parquet(out, index=False)
            print(f"  wrote {out.name}: {len(g):,} swaps")


if __name__ == "__main__":
    main()
