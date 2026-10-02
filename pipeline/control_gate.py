"""USDC/USDT calm-period control gate (§17.3.2, §17.9) — MUST pass
before any study result is read. Reads the canonical control-pool q_LP
Study E writes (arb_exit, 1s window centred on block_ts + L).

Logic: on calm windows, legitimate divergence on the stable-stable pool
is bounded by the externally-observable peg band. If scored |q_LP| on
USDC/USDT materially exceeds what the USDCUSDT benchmark peg deviation
can explain, the metric is manufacturing signal — stop and debug.

Pass criterion (conservative):
  P95(|q_LP_h0|) on calm-window control swaps <= PEG_MULTIPLE ×
  P99(|USDCUSDT − 1|) over the same window, and median |q_LP| in
  single-digit bps.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .benchmark import PriceSeries
from .config import DATA_DIR, ONCHAIN_DIR
from .pools import CONTROL_POOL

Q_C = ONCHAIN_DIR / "scored_timing" / CONTROL_POOL.name / "q_c.parquet"
PEG_MULTIPLE = 3.0          # slack for pool fee + microstructure noise
MEDIAN_BPS_CEILING = 10.0   # "single-digit bps" per spec


def run_gate() -> bool:
    if not Q_C.exists():
        raise SystemExit(f"no canonical control q ({Q_C}); run study_e first")
    df = pd.read_parquet(Q_C, columns=["q_c_h0"]).dropna()

    peg = PriceSeries(CONTROL_POOL.bench)
    peg_dev = np.abs(peg.px - 1.0)
    peg_p99_bps = np.quantile(peg_dev, 0.99) * 1e4

    q_abs_bps = np.abs(df["q_c_h0"].to_numpy()) * 1e4
    p95_bps = float(np.quantile(q_abs_bps, 0.95))
    med_bps = float(np.median(q_abs_bps))

    ceiling = PEG_MULTIPLE * peg_p99_bps
    ok = p95_bps <= ceiling and med_bps <= MEDIAN_BPS_CEILING

    print(f"control swaps scored:      {len(df):,}")
    print(f"peg P99 deviation:         {peg_p99_bps:.2f} bps")
    print(f"|q_LP| median / P95:       {med_bps:.2f} / {p95_bps:.2f} bps")
    print(f"gate ceiling (×{PEG_MULTIPLE:.0f} peg P99): {ceiling:.2f} bps")
    print(f"GATE: {'PASS' if ok else 'FAIL — metric may be manufacturing signal; debug before reading any study result'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run_gate() else 1)
