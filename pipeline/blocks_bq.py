"""Block metadata via BigQuery public dataset (bigquery-public-data.
crypto_ethereum.blocks) — replaces ~1M paced RPC header fetches with one
query per month. Requires `gcloud auth login` once.

Output: data/onchain/blocks/blocks.parquet covering the whole window,
with next_block_ts precomputed (contiguous block series → shift).
extract_swaps auto-uses this file when present; RPC is the fallback.
"""
from __future__ import annotations

import io
import subprocess

import pandas as pd

from .config import DATA_DIR, months_in_window

BLOCKS_PARQUET = DATA_DIR / "onchain" / "blocks" / "blocks.parquet"

_SQL = """
SELECT
  number,
  UNIX_SECONDS(timestamp) AS block_ts,
  transaction_count       AS tx_count,
  CAST(COALESCE(base_fee_per_gas, 0) AS INT64) AS base_fee_wei
FROM `bigquery-public-data.crypto_ethereum.blocks`
WHERE timestamp >= "{start}" AND timestamp < "{end}"
ORDER BY number
"""


def _month_range(month: str) -> tuple[str, str]:
    y, m = map(int, month.split("-"))
    nxt = f"{y + (m == 12):04d}-{m % 12 + 1:02d}-01"
    return f"{month}-01", nxt


def fetch_month(month: str) -> pd.DataFrame:
    start, end = _month_range(month)
    sql = _SQL.format(start=start, end=end)
    out = subprocess.run(
        ["bq", "query", "--nouse_legacy_sql", "--format=csv", "--max_rows=10000000", sql],
        capture_output=True, text=True, check=True,
    )
    return pd.read_csv(io.StringIO(out.stdout))


def main() -> None:
    frames = []
    for month in months_in_window():
        df = fetch_month(month)
        print(f"{month}: {len(df):,} blocks")
        frames.append(df)
    all_blocks = pd.concat(frames).sort_values("number").reset_index(drop=True)
    all_blocks = all_blocks.rename(columns={"number": "block_number"})
    all_blocks["next_block_ts"] = all_blocks["block_ts"].shift(-1)
    BLOCKS_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    all_blocks.to_parquet(BLOCKS_PARQUET, index=False)
    print(f"wrote {BLOCKS_PARQUET}: {len(all_blocks):,} blocks")


if __name__ == "__main__":
    main()
