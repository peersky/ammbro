"""Deferred tx-meta stage: from/to/priority fee for every swap tx.

Separate from extract_swaps because these fields feed only the labels
join and the §12.1 redirection test (priority-fee spend), not q_LP —
and they double the RPC call count. Run after scoring/gate work starts.

Output: data/onchain/txs/<pool>/<pool>-YYYY-MM.txs.parquet keyed by tx_hash.
"""
from __future__ import annotations

import sys

import pandas as pd

from .config import DATA_DIR, ONCHAIN_DIR
from .extract_swaps import SWAPS_DIR, fetch_tx_meta
from .pools import POOLS

TXS_DIR = ONCHAIN_DIR / "txs"


def main() -> None:
    names = sys.argv[1:]
    for pool in POOLS:
        if names and pool.name not in names:
            continue
        out_dir = TXS_DIR / pool.name
        out_dir.mkdir(parents=True, exist_ok=True)
        for p in sorted((SWAPS_DIR / pool.name).glob("*.parquet")):
            out = out_dir / p.name.replace(".parquet", ".txs.parquet")
            if out.exists():
                print(f"  ok (exists) {out.name}")
                continue
            swaps = pd.read_parquet(p, columns=["tx_hash", "block_number", "base_fee_wei"])
            base = dict(zip(swaps["block_number"], swaps["base_fee_wei"]))
            txs = fetch_tx_meta(swaps["tx_hash"].tolist(), base)
            txs.to_parquet(out, index=False)
            print(f"  wrote {out.name}: {len(txs):,} txs")


if __name__ == "__main__":
    main()
