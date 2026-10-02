"""Supp-1 — position↔extraction structure and the §12.1 redirection test.

Measures (informational, calibrates Study B):
1. Extraction (share LP-negative, median q_LP, dollar extraction) by raw
   tx_index bucket — the literal top-of-block advantage.
2. Same by normalized intra-block position decile (§17.7) — does the
   advantage survive normalization?
3. Priority-fee rates paid by toxic vs benign flow (gwei) and estimated
   spend — the money currently leaking to builders (§12.1). Spend uses an
   assumed 250k gas/swap (receipts not fetched); stated as an estimate.

All position tables are produced at every horizon in HORIZONS_S (§17.1).
The headline check is whether the share of extraction at raw index 10+
(un-raced flow, invisible to priority-keyed taxes) holds across horizons.

Caveat carried to the writeup: the toxic label conditions on tx_index,
so per-label position comparisons are partially label-induced; the
by-position aggregates over ALL swaps (1,2) are label-free.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import canonical
from .config import DATA_DIR, HORIZONS_S, REPO_ROOT, ONCHAIN_DIR, RESULTS_DIR
from .pools import STUDY_POOL

SCORED_DIR = ONCHAIN_DIR / "scored" / STUDY_POOL.name
LABELS_DIR = ONCHAIN_DIR / "labels" / STUDY_POOL.name
TXS_DIR = ONCHAIN_DIR / "txs" / STUDY_POOL.name
OUT = RESULTS_DIR / "supp1"

GAS_PER_SWAP_EST = 250_000


def load() -> pd.DataFrame:
    scored = pd.concat(pd.read_parquet(p) for p in sorted(SCORED_DIR.glob("*")))
    labels = pd.concat(pd.read_parquet(p) for p in sorted(LABELS_DIR.glob("*")))
    txs = pd.concat(pd.read_parquet(p) for p in sorted(TXS_DIR.glob("*")))
    df = scored.merge(labels[["tx_hash", "log_index", "label"]], on=["tx_hash", "log_index"], how="left")
    df = df.merge(
        txs[["tx_hash", "priority_fee_wei"]].drop_duplicates("tx_hash"),
        on="tx_hash", how="left",
    )
    df["prio_gwei"] = df["priority_fee_wei"].astype("float64") / 1e9
    return df


def by_bucket(df: pd.DataFrame, key: pd.Series, edges: list, col: str = "q_lp_h0") -> list[dict]:
    out = []
    for lo, hi, name in edges:
        s = df[(key >= lo) & (key < hi)]
        q = s[col].dropna()
        neg = s[s[col] < 0]
        out.append({
            "bucket": name,
            "n": len(s),
            "share_lp_negative": round(float((q < 0).mean()), 4) if len(q) else None,
            "median_q_bps": round(float(q.median() * 1e4), 2) if len(q) else None,
            "extraction_usd_m": round(float(-(neg[col] * neg.notional_token0).sum() / 1e6), 2),
        })
    return out


def run() -> dict:
    base = load()
    res = {"timeline": canonical.DESCRIPTION, **compute(canonical.apply(base))}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(res, indent=2))
    return res


def compute(df: pd.DataFrame) -> dict:
    big = df[df.notional_token0 > STUDY_POOL.big_usd]

    res: dict = {"idx10plus_by_horizon": [], "by_horizon": {}}
    idx_edges = [(0, 1, "idx0"), (1, 2, "idx1"), (2, 3, "idx2"), (3, 10, "idx3-9"), (10, 10_000, "idx10+")]
    frac = df["tx_index"] / df["tx_count"].clip(lower=1)
    fb = big["tx_index"] / big["tx_count"].clip(lower=1)
    dec_edges = [(i / 10, (i + 1) / 10, f"pos_{i*10}-{(i+1)*10}%") for i in range(10)]

    for h in HORIZONS_S:
        col = f"q_lp_h{h}"
        t = {
            "by_raw_tx_index_all": by_bucket(df, df["tx_index"], idx_edges, col),
            "by_raw_tx_index_big": by_bucket(big, big["tx_index"], idx_edges, col),
            "by_norm_position_all": by_bucket(df, frac, dec_edges, col),
            "by_norm_position_big": by_bucket(big, fb, dec_edges, col),
        }
        res["by_horizon"][f"h{h}"] = t
        rows = t["by_raw_tx_index_all"]
        total = sum(r["extraction_usd_m"] for r in rows)
        top3 = sum(r["extraction_usd_m"] for r in rows[:3])
        tail = rows[-1]["extraction_usd_m"]
        res["idx10plus_by_horizon"].append({
            "horizon_s": h,
            "total_extraction_usd_m": round(total, 2),
            "top3_share": round(top3 / total, 3),
            "idx10plus_usd_m": tail,
            "idx10plus_share": round(tail / total, 3),
        })

    for lbl in ["toxic", "benign"]:
        s = df[df.label == lbl]
        spend = (s["prio_gwei"] * GAS_PER_SWAP_EST / 1e9).sum()  # ETH
        res[f"priority_fee_{lbl}"] = {
            "median_gwei": round(float(s["prio_gwei"].median()), 3),
            "p90_gwei": round(float(s["prio_gwei"].quantile(0.9)), 3),
            "est_total_spend_eth_at_250k_gas": round(float(spend), 1),
        }
    return res


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
