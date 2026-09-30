"""Study B — ex-post markout fee simulation (§17.1/§17.8/§12.2).

Static replay of the fee mechanism over the historical window:

    fee_rate(swap) = f_benign                     if q_LP(h) >= 0
                     clip(alpha·|q_LP(h)|, f_benign, f_cap)   otherwise

The mechanism sees only realized q_LP (ex-post oracle reconciliation) —
labels are NEVER an input; they are used only to report benign
overcharge afterwards.

Run at every horizon in HORIZONS_S (§17.1: horizon fragility reported,
never hidden). At horizon h both the fee signal and the LP markout use
q_LP(h) — the whole study is re-run per horizon, not h0 fees scored at h.

Outputs per horizon and schedule (all USD over the window):
  lp_fee_revenue, gross_lvr (LP-negative markout), captured_from_toxic
  (fee charged on LP-negative swaps), RESIDUAL EXTRACTION (what the
  extractors kept — §12.2 mandatory), net_lp_pnl (markout + fees),
  benign_overcharge_bps (fee above baseline paid by benign-labeled flow),
  arb_survival (share of LP-negative swaps still profitable after fee+gas).

Gas sensitivity: arb_survival is the gate's constraint proxy and depends
on the assumed arb execution cost, so the headline schedule is re-scored
under flat costs and a per-swap base-fee model. The base-fee model is a
LOWER bound on cost: it omits priority fees and coinbase-transfer builder
payments, both of which searchers pay on top.

HONESTY (bind to writeup): static replay — no behavioral response. Fees
change arb behavior in reality; captured numbers are upper bounds on this
schedule, arb-survival is the constraint proxy. Baseline = the pool's
actual 5bp fixed fee.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import DATA_DIR, HORIZONS_S, REPO_ROOT
from .pools import ETH_USDC

SCORED_DIR = DATA_DIR / "onchain" / "scored" / ETH_USDC.name
LABELS_DIR = DATA_DIR / "onchain" / "labels" / ETH_USDC.name
OUT = REPO_ROOT / "results" / "study_b"

BASELINE_FEE = 0.0005          # the pool's actual fixed 5 bps
GAS_COST_USD = 10.0            # sweep-ranking arb execution cost per swap
ALPHAS = [0.25, 0.5, 0.75, 1.0]
CAPS_BPS = [10, 25, 50, 100]
F_BENIGN_BPS = [1, 5]

# Schedule the writeup cites (best net LP at h0). Held fixed across
# horizons and gas models so fragility is measured on one mechanism.
HEADLINE = {"alpha": 1.0, "cap": 100 / 1e4, "f_benign": 5 / 1e4}

GAS_FLAT_USD = [2.0, 10.0, 25.0, 50.0]
ARB_GAS_UNITS = 250_000        # same assumption as supp1 priority-fee spend


def load() -> pd.DataFrame:
    scored = pd.concat(pd.read_parquet(p) for p in sorted(SCORED_DIR.glob("*")))
    labels = pd.concat(pd.read_parquet(p) for p in sorted(LABELS_DIR.glob("*")))
    df = scored.merge(labels[["tx_hash", "log_index", "label"]], on=["tx_hash", "log_index"], how="left")
    return df.dropna(subset=["notional_token0"])


def base_fee_gas_usd(df: pd.DataFrame) -> np.ndarray:
    """Per-swap arb cost = base fee × ARB_GAS_UNITS, valued at the swap's
    own execution price (USDC per WETH from the pool deltas)."""
    a0 = df["amount0_raw"].astype(float).abs() / 10**ETH_USDC.dec0
    a1 = df["amount1_raw"].astype(float).abs() / 10**ETH_USDC.dec1
    with np.errstate(invalid="ignore", divide="ignore"):
        eth_usd = (a0 / a1).to_numpy()
    eth_usd = np.where(np.isfinite(eth_usd), eth_usd, np.nanmedian(eth_usd))
    return df["base_fee_wei"].astype(float).to_numpy() / 1e18 * ARB_GAS_UNITS * eth_usd


def simulate(q, v, benign_mask, gas_usd, alpha: float, cap: float, f_benign: float) -> dict:
    """INCREMENTAL accounting: v3 Swap deltas already embed the pool's
    actual 5bp fee, so q_LP is net of it. A schedule's effect on LP P&L
    is only the fee DELTA vs the 5bp baseline; the arb's realized edge is
    -q (already net of the 5bp) minus the incremental fee."""
    neg = q < 0

    fee_rate = np.full(len(q), f_benign)
    fee_rate[neg] = np.clip(alpha * (-q[neg]), f_benign, cap)
    delta = fee_rate - BASELINE_FEE          # incremental vs actual 5bp
    inc_fees = delta * v

    gross_lvr = float(-(q[neg] * v[neg]).sum())   # net of actual fee
    captured = float(np.maximum(delta[neg], 0.0) @ v[neg])
    residual = float(np.maximum((-q[neg]) - delta[neg], 0.0) @ v[neg])
    net_lp = float((q * v).sum() + inc_fees.sum())

    benign_overcharge_bps = (
        float(np.average(delta[benign_mask], weights=v[benign_mask]) * 1e4)
        if benign_mask.any() else None
    )

    gas = gas_usd[neg] if np.ndim(gas_usd) else gas_usd
    arb_pnl = (-q[neg] - delta[neg]) * v[neg] - gas
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


def captured_by_label(q, v, label, alpha: float, cap: float, f_benign: float) -> dict:
    """Split captured_from_toxic by independent label. At longer horizons
    q_LP carries more post-trade noise; an asymmetric fee (charged on
    q<0, never refunded on q>0) then monetizes noise. Capture landing on
    benign-labeled flow is that noise tax, not recaptured LVR."""
    neg = q < 0
    delta = np.clip(alpha * (-q[neg]), f_benign, cap) - BASELINE_FEE
    cap_usd = np.maximum(delta, 0.0) * v[neg]
    lab = np.where(pd.isna(label[neg]), "unlabeled", label[neg])
    return {k: round(float(cap_usd[lab == k].sum()) / 1e6, 2) for k in ("toxic", "benign", "unlabeled")}


def baseline(q, v, gas_usd) -> dict:
    neg = q < 0
    gas = gas_usd[neg] if np.ndim(gas_usd) else gas_usd
    return {
        "schedule": "fixed_5bp_baseline (as lived; markout already nets the fee)",
        "gross_lvr_m": round(float(-(q[neg] * v[neg]).sum()) / 1e6, 2),
        "net_lp_pnl_m": round(float((q * v).sum()) / 1e6, 2),
        "residual_extraction_m": round(float(-(q[neg] * v[neg]).sum()) / 1e6, 2),
        "arb_survival": round(float(((-q[neg]) * v[neg] - gas > 0).mean()), 3),
    }


def run() -> dict:
    df = load()
    gas_models = {f"flat_{g:g}usd": g for g in GAS_FLAT_USD}

    by_horizon, headline_by_h, gas_sens = {}, [], []
    for h in HORIZONS_S:
        sub = df.dropna(subset=[f"q_lp_h{h}"])
        q = sub[f"q_lp_h{h}"].to_numpy()
        v = sub["notional_token0"].to_numpy()
        benign = (sub["label"] == "benign").to_numpy()

        sweep = [
            simulate(q, v, benign, GAS_COST_USD, a, c / 1e4, fb / 1e4)
            for a in ALPHAS for c in CAPS_BPS for fb in F_BENIGN_BPS
        ]
        sweep.sort(key=lambda r: -r["net_lp_pnl_m"])
        base = baseline(q, v, GAS_COST_USD)
        by_horizon[f"h{h}"] = {
            "n_swaps": len(sub), "baseline": base,
            "sweep_top10": sweep[:10], "sweep_all": sweep,
        }

        head = simulate(q, v, benign, GAS_COST_USD, **HEADLINE)
        head["captured_by_label_m"] = captured_by_label(q, v, sub["label"].to_numpy(), **HEADLINE)
        headline_by_h.append({
            "horizon_s": h,
            "baseline_net_lp_pnl_m": base["net_lp_pnl_m"],
            **head,
            "net_vs_baseline_m": round(head["net_lp_pnl_m"] - base["net_lp_pnl_m"], 2),
            "survival_ratio": round(head["arb_survival"] / base["arb_survival"], 3),
            "best_schedule_at_h": {k: sweep[0][k] for k in ("alpha", "cap_bps", "f_benign_bps", "net_lp_pnl_m")},
        })

        models = dict(gas_models, base_fee_x250k_gas=base_fee_gas_usd(sub))
        for name, gas in models.items():
            b = baseline(q, v, gas)
            s = simulate(q, v, benign, gas, **HEADLINE)
            gas_sens.append({
                "horizon_s": h, "gas_model": name,
                "baseline_survival": b["arb_survival"],
                "headline_survival": s["arb_survival"],
                "survival_ratio": round(s["arb_survival"] / b["arb_survival"], 3) if b["arb_survival"] else None,
            })

    out = {
        "n_swaps_total": len(df),
        "headline_schedule": {"alpha": 1.0, "cap_bps": 100.0, "f_benign_bps": 5.0},
        "headline_by_horizon": headline_by_h,
        "gas_sensitivity": gas_sens,
        "by_horizon": by_horizon,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    print(json.dumps({k: res[k] for k in ["n_swaps_total", "headline_by_horizon", "gas_sensitivity"]}, indent=2))
