"""Study B — ex-post markout fee simulation (§17.1/§17.8/§12.2).

Static replay of the fee mechanism over the historical window:

    fee_rate(swap) = f_benign                     if q_LP(h0) >= 0
                     clip(alpha·|q_LP|, f_benign, f_cap)   otherwise

The mechanism sees only realized q_LP (ex-post oracle reconciliation) —
labels are NEVER an input; they are used only to report benign
overcharge afterwards.

Outputs per schedule (all USD over the window):
  lp_fee_revenue, gross_lvr (LP-negative markout), captured_from_toxic
  (fee charged on LP-negative swaps), RESIDUAL EXTRACTION (what the
  extractors kept — §12.2 mandatory), net_lp_pnl (markout + fees),
  benign_overcharge_bps (fee above baseline paid by benign-labeled flow),
  arb_survival (share of LP-negative swaps still profitable after fee+gas).

HONESTY (bind to writeup): static replay — no behavioral response. Fees
change arb behavior in reality; captured numbers are upper bounds on this
schedule, arb-survival is the constraint proxy. Baseline = the pool's
actual 5bp fixed fee.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import DATA_DIR, REPO_ROOT
from .pools import ETH_USDC

SCORED_DIR = DATA_DIR / "onchain" / "scored" / ETH_USDC.name
LABELS_DIR = DATA_DIR / "onchain" / "labels" / ETH_USDC.name
OUT = REPO_ROOT / "results" / "study_b"

BASELINE_FEE = 0.0005          # the pool's actual fixed 5 bps
GAS_COST_USD = 10.0            # est. arb execution cost per swap
ALPHAS = [0.25, 0.5, 0.75, 1.0]
CAPS_BPS = [10, 25, 50, 100]
F_BENIGN_BPS = [1, 5]


def load() -> pd.DataFrame:
    scored = pd.concat(pd.read_parquet(p) for p in sorted(SCORED_DIR.glob("*")))
    labels = pd.concat(pd.read_parquet(p) for p in sorted(LABELS_DIR.glob("*")))
    df = scored.merge(labels[["tx_hash", "log_index", "label"]], on=["tx_hash", "log_index"], how="left")
    return df.dropna(subset=["q_lp_h0", "notional_token0"])


def simulate(df: pd.DataFrame, alpha: float, cap: float, f_benign: float) -> dict:
    """INCREMENTAL accounting: v3 Swap deltas already embed the pool's
    actual 5bp fee, so q_LP is net of it. A schedule's effect on LP P&L
    is only the fee DELTA vs the 5bp baseline; the arb's realized edge is
    -q (already net of the 5bp) minus the incremental fee."""
    q = df["q_lp_h0"].to_numpy()
    v = df["notional_token0"].to_numpy()
    neg = q < 0

    fee_rate = np.full(len(df), f_benign)
    fee_rate[neg] = np.clip(alpha * (-q[neg]), f_benign, cap)
    delta = fee_rate - BASELINE_FEE          # incremental vs actual 5bp
    inc_fees = delta * v

    gross_lvr = float(-(q[neg] * v[neg]).sum())   # net of actual fee
    captured = float(np.maximum(delta[neg], 0.0) @ v[neg])
    residual = float(np.maximum((-q[neg]) - delta[neg], 0.0) @ v[neg])
    net_lp = float((q * v).sum() + inc_fees.sum())

    benign_mask = (df["label"] == "benign").to_numpy()
    benign_overcharge_bps = (
        float(np.average(delta[benign_mask], weights=v[benign_mask]) * 1e4)
        if benign_mask.any() else None
    )

    arb_pnl = (-q[neg] - delta[neg]) * v[neg] - GAS_COST_USD
    survival = float((arb_pnl > 0).mean())

    return {
        "alpha": alpha, "cap_bps": cap * 1e4, "f_benign_bps": f_benign * 1e4,
        "incremental_fee_revenue_m": round(inc_fees.sum() / 1e6, 2),
        "gross_lvr_m": round(gross_lvr / 1e6, 2),
        "captured_from_toxic_m": round(captured / 1e6, 2),
        "residual_extraction_m": round(residual / 1e6, 2),
        "capture_fraction": round(captured / gross_lvr, 3),
        "net_lp_pnl_m": round(net_lp / 1e6, 2),
        "benign_overcharge_bps": round(benign_overcharge_bps, 2),
        "arb_survival": round(survival, 3),
    }


def run() -> dict:
    df = load()
    q = df["q_lp_h0"].to_numpy(); v = df["notional_token0"].to_numpy()
    neg = q < 0
    baseline = {
        "schedule": "fixed_5bp_baseline (as lived; markout already nets the fee)",
        "gross_lvr_m": round(float(-(q[neg] * v[neg]).sum()) / 1e6, 2),
        "net_lp_pnl_m": round(float((q * v).sum()) / 1e6, 2),
        "residual_extraction_m": round(float(-(q[neg] * v[neg]).sum()) / 1e6, 2),
        "arb_survival": round(float(((-q[neg]) * v[neg] - GAS_COST_USD > 0).mean()), 3),
    }
    sweep = [
        simulate(df, a, c / 1e4, fb / 1e4)
        for a in ALPHAS for c in CAPS_BPS for fb in F_BENIGN_BPS
        if a * 1 >= 0  # keep all
    ]
    sweep.sort(key=lambda r: -r["net_lp_pnl_m"])
    out = {"n_swaps": len(df), "baseline": baseline, "sweep_top10": sweep[:10], "sweep_all": sweep}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    print(json.dumps({k: res[k] for k in ["n_swaps", "baseline", "sweep_top10"]}, indent=2))
