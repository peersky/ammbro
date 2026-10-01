"""Canonical q_LP (spec item 9b) — one scoring timeline for every study.

    canonical        arb_exit directional q (Study D, P§3.6/P§4.2), averaged
                     over a 1s window centred on block_ts + L + h (Study E:
                     L = measured decision latency, 1.5s). Written by Study E
                     to data/onchain/scored_timing/.
    legacy_forward   trade-price q at the forward virtual time
                     t_norm = block_ts + (tx_index/tx_count)·T (§17.7). Prices
                     mid-block swaps against prints from after the block was
                     sealed (lookahead, Study E). Kept only for comparison.

Studies load their scored frame and pass it through `apply`; the q columns
keep their historical names (q_lp_h{h}) so study code is timeline-agnostic.
"""
from __future__ import annotations

import pandas as pd

from .config import DATA_DIR, HORIZONS_S
from .pools import ETH_USDC

Q_C = DATA_DIR / "onchain" / "scored_timing" / ETH_USDC.name / "q_c.parquet"
DESCRIPTION = {
    "canonical": "arb_exit q, 1s window centred on block_ts + L + h (Study E)",
    "legacy_forward": "trade-price q at forward t_norm (pre-Study-E pipeline)",
}


def apply(df: pd.DataFrame, timeline: str = "canonical") -> pd.DataFrame:
    if timeline == "legacy_forward":
        return df
    if timeline != "canonical":
        raise ValueError(timeline)
    qc = pd.read_parquet(Q_C)
    missing = [h for h in HORIZONS_S if f"q_c_h{h}" not in qc.columns]
    if missing:
        raise SystemExit(f"q_c.parquet lacks horizons {missing}; re-run `make study-e`")
    df = df.drop(columns=[c for c in df.columns if c.startswith("q_lp_h")])
    df = df.merge(qc, on=["tx_hash", "log_index"], how="left")
    return df.rename(columns={f"q_c_h{h}": f"q_lp_h{h}" for h in HORIZONS_S})
