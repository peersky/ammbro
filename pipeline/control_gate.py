"""USDC/USDT calm-period control gate (§17.3.2, §17.9) — MUST pass
before any Study A/B/C result is read.

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
from .config import DATA_DIR
from .pools import USDC_USDT

SCORED_DIR = DATA_DIR / "onchain" / "scored" / USDC_USDT.name
PEG_MULTIPLE = 3.0          # slack for pool fee + microstructure noise
MEDIAN_BPS_CEILING = 10.0   # "single-digit bps" per spec


def run_gate() -> bool:
    src = sorted(SCORED_DIR.glob("*.scored.parquet"))
    if not src:
        raise SystemExit("no scored USDC/USDT swaps; run qlp first")
    df = pd.concat(pd.read_parquet(p, columns=["t_norm_us", "q_lp_h0"]) for p in src)
    df = df.dropna(subset=["q_lp_h0"])

    peg = PriceSeries("USDCUSDT")
    peg_dev = np.abs(peg.px - 1.0)
    peg_p99_bps = np.quantile(peg_dev, 0.99) * 1e4

    q_abs_bps = np.abs(df["q_lp_h0"].to_numpy()) * 1e4
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
