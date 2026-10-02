"""Canonical q_LP (spec item 9b) — one scoring timeline for every study.

    arb_exit directional q (Study D, P§3.6/P§4.2), averaged over a 1s
    window centred on block_ts + L + h (Study E: L = measured decision
    latency, 1.5s on mainnet). Written by Study E to
    data/onchain/scored_timing/.

Studies load their prepared swap frame and pass it through `apply`, which
joins q as columns q_lp_h{h}.
"""
from __future__ import annotations

import pandas as pd

from .config import DATA_DIR, HORIZONS_S, ONCHAIN_DIR
from .pools import STUDY_POOL

Q_C = ONCHAIN_DIR / "scored_timing" / STUDY_POOL.name / "q_c.parquet"
DESCRIPTION = "arb_exit q, 1s window centred on block_ts + L + h (Study E)"


def apply(df: pd.DataFrame) -> pd.DataFrame:
    qc = pd.read_parquet(Q_C)
    missing = [h for h in HORIZONS_S if f"q_c_h{h}" not in qc.columns]
    if missing:
        raise SystemExit(f"q_c.parquet lacks horizons {missing}; re-run `make study-e`")
    df = df.drop(columns=[c for c in df.columns if c.startswith("q_lp_h")])
    df = df.merge(qc, on=["tx_hash", "log_index"], how="left")
    return df.rename(columns={f"q_c_h{h}": f"q_lp_h{h}" for h in HORIZONS_S})
