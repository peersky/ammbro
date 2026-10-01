"""Study-A labels — price-independent by construction (§14.2).

Axes used: identity (router list, repeat actors), structure (sandwich
leg pattern), position (first-in-direction, tx index). NO price, oracle,
or q_LP column is ever read here; `assert_price_independent` enforces it.

ZeroMEV deviation note (2026-09-02): the spec's primary atomic-MEV label
source (ZeroMEV API) is offline — origin DNS dead, host serves a stub.
Flashbots' Dune mev_summary is stale. Labels below are our committed,
reproducible replacements on the same independence axes.

Labels emitted per swap (nullable):
  benign_router    tx_to in curated retail router list
  toxic_sandwich   attacker leg of a pool-local sandwich pattern
  sandwich_victim  swap between the legs (excluded from toxic set)
  toxic_searcher   first-in-direction, top-of-block, non-router repeat actor
  label            consolidated: 'benign' | 'toxic' | None (unlabeled middle)
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from .config import DATA_DIR, ONCHAIN_DIR
from .pools import POOLS
from .routers import ROUTER_SET

SWAPS_DIR = ONCHAIN_DIR / "swaps"
TXS_DIR = ONCHAIN_DIR / "txs"
LABELS_DIR = ONCHAIN_DIR / "labels"

# Structure/identity/position columns only. Guard against future edits
# accidentally leaking a price column into labeling.
ALLOWED_COLUMNS = {
    "block_number", "tx_hash", "tx_index", "log_index", "tx_from", "tx_to",
    "sender", "recipient", "amount0_raw", "amount1_raw", "tx_count",
}
_PRICE_COLUMNS = {"q_lp", "price", "sqrt", "notional", "markout"}

TOP_OF_BLOCK_MAX_INDEX = 3
REPEAT_ACTOR_MIN_SWAPS = 100
SANDWICH_REBALANCE_TOL = 0.10  # legs must offset within 10% (token1)


def assert_price_independent(columns) -> None:
    leaked = [c for c in columns for bad in _PRICE_COLUMNS if bad in c.lower()]
    if leaked:
        raise AssertionError(f"price-derived columns in label input: {leaked}")


def detect_sandwiches(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Pool-local sandwich detector. Within one block, in pool-event
    order: attacker swap (dir d), >=1 other-actor swaps (dir d), attacker
    swap (dir -d) roughly offsetting the first leg. Returns (attacker,
    victim) boolean series aligned to df."""
    attacker = pd.Series(False, index=df.index)
    victim = pd.Series(False, index=df.index)
    a1 = df["amount1_raw"].astype("float64")
    direction = np.sign(a1)

    for _, g in df.groupby("block_number", sort=False):
        if len(g) < 3:
            continue
        idx = g.sort_values("log_index").index.to_numpy()
        for i_pos in range(len(idx) - 2):
            i = idx[i_pos]
            d = direction[i]
            if d == 0:
                continue
            for k_pos in range(i_pos + 2, len(idx)):
                k = idx[k_pos]
                if df.at[k, "tx_from"] != df.at[i, "tx_from"]:
                    continue
                if direction[k] != -d:
                    continue
                if abs(a1[i] + a1[k]) > SANDWICH_REBALANCE_TOL * abs(a1[i]):
                    continue
                mids = [m for m in idx[i_pos + 1 : k_pos]
                        if df.at[m, "tx_from"] != df.at[i, "tx_from"]
                        and direction[m] == d]
                if not mids:
                    continue
                attacker[i] = attacker[k] = True
                for m in mids:
                    victim[m] = True
                break
            if attacker[i]:
                continue
    return attacker, victim


def detect_searchers(df: pd.DataFrame) -> pd.Series:
    """First-in-direction in block + top-of-block + non-router tx_to +
    repeat actor. Position/identity axes only."""
    d = np.sign(df["amount1_raw"].astype("float64"))
    first_in_dir = ~df.assign(d=d).duplicated(["block_number", "d"], keep="first")
    top = df["tx_index"] <= TOP_OF_BLOCK_MAX_INDEX
    non_router = ~df["tx_to"].fillna("").str.lower().isin(ROUTER_SET)
    actor_counts = df["tx_from"].str.lower().map(df["tx_from"].str.lower().value_counts())
    repeat = actor_counts >= REPEAT_ACTOR_MIN_SWAPS
    return first_in_dir & top & non_router & repeat


def label_pool(pool_name: str) -> None:
    out_dir = LABELS_DIR / pool_name
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in sorted((SWAPS_DIR / pool_name).glob("*.parquet")):
        out = out_dir / p.name.replace(".parquet", ".labels.parquet")
        if out.exists():
            print(f"  ok (exists) {out.name}")
            continue
        df = pd.read_parquet(p)
        txp = TXS_DIR / pool_name / p.name.replace(".parquet", ".txs.parquet")
        if "tx_from" not in df.columns:
            if not txp.exists():
                raise SystemExit(f"tx meta missing for {p.name}; run extract_txs or export_indexer")
            df = df.merge(pd.read_parquet(txp), on="tx_hash", how="left")
        df = df[[c for c in df.columns if c in ALLOWED_COLUMNS]]
        assert_price_independent(df.columns)

        df["tx_from"] = df["tx_from"].fillna("").str.lower()
        df["tx_to"] = df["tx_to"].fillna("").str.lower()
        benign = df["tx_to"].isin(ROUTER_SET)
        sand_att, sand_vic = detect_sandwiches(df)
        searcher = detect_searchers(df)

        lab = pd.DataFrame({
            "tx_hash": df["tx_hash"],
            "block_number": df["block_number"],
            "log_index": df["log_index"],
            "benign_router": benign,
            "toxic_sandwich": sand_att,
            "sandwich_victim": sand_vic,
            "toxic_searcher": searcher & ~sand_att & ~benign,
        })
        toxic = lab["toxic_sandwich"] | lab["toxic_searcher"]
        lab["label"] = np.select(
            [toxic, benign & ~toxic & ~sand_vic], ["toxic", "benign"], default=None
        )
        lab.to_parquet(out, index=False)
        n = lab["label"].value_counts()
        print(f"  wrote {out.name}: toxic {n.get('toxic', 0):,} benign {n.get('benign', 0):,} "
              f"victims {int(sand_vic.sum()):,} unlabeled {lab['label'].isna().sum():,}")


def main() -> None:
    names = sys.argv[1:] or [p.name for p in POOLS]
    for name in names:
        print(name)
        label_pool(name)


if __name__ == "__main__":
    main()
