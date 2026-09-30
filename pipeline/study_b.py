"""Study B — ex-post markout fee simulation (§17.1/§17.8/§12.2).

CEILING, not the P§4 mechanism: a perfect-information per-swap cash fee
charged from realized q_LP. Study C results are reported as a share of it.

Schedule forms (fee on LP-negative swaps; every other swap pays f_benign):

    clip      clip(alpha·|q|, f_benign, cap)         original form; charges
              nothing extra until |q| exceeds f_benign, so small extractions
              are exempt and capture tops out well below 100%
    additive  min(f_benign + alpha·|q|, cap)          charge on top of f_benign
    margin    min(f_benign + max(|q| − m, 0), cap)    charge everything beyond an
              allowance m left to the arb for its costs

q_LP is measured net of the pool's as-lived 5bp fee, so a schedule's
effect is its INCREMENTAL fee over 5bp.

DESIGN OBJECTIVE (spec): paying builders for inclusion or position must
be useless. The most a rational arb pays a builder to be first is what it
keeps after reconciliation minus its real costs:

    builder_bid_ceiling = Σ max(residual_i − gas_i − h·V_i, 0)

with gas_i the swap's real base-fee cost and h the CEX hedge cost (an
assumption, CEX fee tiers are private; grid over h reported). Every
schedule reports it beside the baseline's, which is today's full rent.

Survival is reported two ways: against a flat $10 per-swap cost (the
original, pessimistic proxy) and against real costs (base-fee gas + h).

Run at every horizon in HORIZONS_S (§17.1). At horizon h both the fee
signal and the LP markout use q_LP(h).

HONESTY (bind to writeup): static replay — no behavioral response. Fees
change arb behavior in reality; captured numbers are upper bounds on each
schedule. Base-fee gas omits priority fees and builder payments — those
are the extras the objective targets, not costs of rebalancing.
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
GAS_COST_USD = 10.0            # flat per-swap cost: original survival proxy
ARB_GAS_UNITS = 250_000        # real-gas model: base fee × this (same as supp1)
HEDGE_COST_BPS = 1.0           # assumed CEX hedge cost for real-cost metrics
HEDGE_GRID_BPS = [0.0, 1.0, 2.0]

ALPHAS = [0.25, 0.5, 0.75, 1.0]
CAPS_BPS = [10, 25, 50, 100, 500]      # 500bp = paper's f_max
F_BENIGN_BPS = [1, 5]
ADDITIVE_ALPHAS = [0.5, 0.75, 0.9, 1.0]
MARGINS_BPS = [0.5, 1.0, 2.0, 5.0]
FORM_CAPS_BPS = [100, 500]

# Tracked schedules, held fixed across horizons and gas models.
# HEADLINE: best net LP of the original clip grid (caps ≤ 100bp) — kept for
# continuity with earlier results. OBJECTIVE: margin schedule serving the
# design objective, m = assumed hedge cost + 1bp buffer, cap = f_max.
HEADLINE = {"alpha": 1.0, "cap": 100 / 1e4, "f_benign": 5 / 1e4}
OBJECTIVE = {"alpha": 1.0, "cap": 500 / 1e4, "f_benign": 5 / 1e4, "form": "margin", "m": 2 / 1e4}

GAS_FLAT_USD = [2.0, 10.0, 25.0, 50.0]


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


def fee_rates(q, alpha: float, cap: float, f_benign: float, form: str = "clip", m: float = 0.0) -> np.ndarray:
    neg = q < 0
    x = -q[neg]
    fee = np.full(len(q), f_benign)
    if form == "clip":
        fee[neg] = np.clip(alpha * x, f_benign, cap)
    elif form == "additive":
        fee[neg] = np.minimum(f_benign + alpha * x, cap)
    elif form == "margin":
        fee[neg] = np.minimum(f_benign + np.maximum(x - m, 0.0), cap)
    else:
        raise ValueError(form)
    return fee


def rent(residual_usd, v, real_gas, hedge_bps: float) -> tuple[float, float]:
    """(builder bid ceiling in USD, share of arbs covering real costs)."""
    net = residual_usd - real_gas - hedge_bps / 1e4 * v
    return float(np.maximum(net, 0.0).sum()), float((net >= 0).mean())


def simulate(q, v, benign_mask, gas_usd, alpha: float, cap: float, f_benign: float,
             form: str = "clip", m: float = 0.0, real_gas=None) -> dict:
    """INCREMENTAL accounting: v3 Swap deltas already embed the pool's
    actual 5bp fee, so q_LP is net of it. A schedule's effect on LP P&L
    is only the fee DELTA vs the 5bp baseline; the arb's realized edge is
    -q (already net of the 5bp) minus the incremental fee."""
    neg = q < 0
    delta = fee_rates(q, alpha, cap, f_benign, form, m) - BASELINE_FEE
    inc_fees = delta * v

    gross_lvr = float(-(q[neg] * v[neg]).sum())   # net of actual fee
    captured = float(np.maximum(delta[neg], 0.0) @ v[neg])
    resid_i = np.maximum((-q[neg]) - delta[neg], 0.0) * v[neg]
    net_lp = float((q * v).sum() + inc_fees.sum())

    benign_overcharge_bps = (
        float(np.average(delta[benign_mask], weights=v[benign_mask]) * 1e4)
        if benign_mask.any() else None
    )

    gas = gas_usd[neg] if np.ndim(gas_usd) else gas_usd
    arb_pnl = (-q[neg] - delta[neg]) * v[neg] - gas
    out = {
        "form": form, "alpha": alpha, "m_bps": round(m * 1e4, 2),
        "cap_bps": cap * 1e4, "f_benign_bps": f_benign * 1e4,
        "incremental_fee_revenue_m": round(inc_fees.sum() / 1e6, 2),
        "gross_lvr_m": round(gross_lvr / 1e6, 2),
        "captured_from_toxic_m": round(captured / 1e6, 2),
        "residual_extraction_m": round(resid_i.sum() / 1e6, 2),
        "capture_fraction": round(captured / gross_lvr, 3),
        "net_lp_pnl_m": round(net_lp / 1e6, 2),
        "benign_overcharge_bps": round(benign_overcharge_bps, 2),
        "arb_survival": round(float((arb_pnl > 0).mean()), 3),
    }
    if real_gas is not None:
        bid, surv = rent(resid_i, v[neg], real_gas[neg], HEDGE_COST_BPS)
        out["builder_bid_ceiling_m"] = round(bid / 1e6, 2)
        out["arb_survival_real_cost"] = round(surv, 3)
    return out


def captured_by_label(q, v, label, alpha: float, cap: float, f_benign: float,
                      form: str = "clip", m: float = 0.0) -> dict:
    """Split captured_from_toxic by independent label. At longer horizons
    q_LP carries more post-trade noise; an asymmetric fee (charged on
    q<0, never refunded on q>0) then monetizes noise. Capture landing on
    benign-labeled flow is that noise tax, not recaptured LVR."""
    neg = q < 0
    delta = fee_rates(q, alpha, cap, f_benign, form, m)[neg] - BASELINE_FEE
    cap_usd = np.maximum(delta, 0.0) * v[neg]
    lab = np.where(pd.isna(label[neg]), "unlabeled", label[neg])
    return {k: round(float(cap_usd[lab == k].sum()) / 1e6, 2) for k in ("toxic", "benign", "unlabeled")}


def baseline(q, v, gas_usd, real_gas=None) -> dict:
    neg = q < 0
    gas = gas_usd[neg] if np.ndim(gas_usd) else gas_usd
    out = {
        "schedule": "fixed_5bp_baseline (as lived; markout already nets the fee)",
        "gross_lvr_m": round(float(-(q[neg] * v[neg]).sum()) / 1e6, 2),
        "net_lp_pnl_m": round(float((q * v).sum()) / 1e6, 2),
        "residual_extraction_m": round(float(-(q[neg] * v[neg]).sum()) / 1e6, 2),
        "arb_survival": round(float(((-q[neg]) * v[neg] - gas > 0).mean()), 3),
    }
    if real_gas is not None:
        bid, surv = rent(-q[neg] * v[neg], v[neg], real_gas[neg], HEDGE_COST_BPS)
        out["builder_bid_ceiling_m"] = round(bid / 1e6, 2)
        out["arb_survival_real_cost"] = round(surv, 3)
    return out


def schedule_grid() -> list[dict]:
    grid = [{"alpha": a, "cap": c / 1e4, "f_benign": fb / 1e4, "form": "clip", "m": 0.0}
            for a in ALPHAS for c in CAPS_BPS for fb in F_BENIGN_BPS if c >= fb]
    grid += [{"alpha": a, "cap": c / 1e4, "f_benign": 5 / 1e4, "form": "additive", "m": 0.0}
             for a in ADDITIVE_ALPHAS for c in FORM_CAPS_BPS]
    grid += [{"alpha": 1.0, "cap": c / 1e4, "f_benign": 5 / 1e4, "form": "margin", "m": mb / 1e4}
             for mb in MARGINS_BPS for c in FORM_CAPS_BPS]
    return grid


def hedge_sensitivity(q, v, real_gas) -> list[dict]:
    """Margin schedules × assumed hedge cost h: the rule is m just above h."""
    neg = q < 0
    base_bid = {h: rent(-q[neg] * v[neg], v[neg], real_gas[neg], h) for h in HEDGE_GRID_BPS}
    rows = []
    for mb in MARGINS_BPS:
        delta = fee_rates(q, 1.0, 500 / 1e4, 5 / 1e4, "margin", mb / 1e4)[neg] - BASELINE_FEE
        resid_i = np.maximum(-q[neg] - delta, 0.0) * v[neg]
        for h in HEDGE_GRID_BPS:
            bid, surv = rent(resid_i, v[neg], real_gas[neg], h)
            b_bid, b_surv = base_bid[h]
            rows.append({
                "m_bps": mb, "hedge_bps": h,
                "builder_bid_ceiling_m": round(bid / 1e6, 2),
                "bid_ceiling_vs_today": round(bid / b_bid, 3) if b_bid else None,
                "arb_survival_real_cost": round(surv, 3),
                "survival_vs_today": round(surv / b_surv, 3) if b_surv else None,
            })
    return rows


def run() -> dict:
    df = load()
    gas_models = {f"flat_{g:g}usd": g for g in GAS_FLAT_USD}
    tracked = {"headline": HEADLINE, "objective": OBJECTIVE}

    by_horizon, tracked_by_h, gas_sens, hedge_by_h = {}, [], [], {}
    for h in HORIZONS_S:
        sub = df.dropna(subset=[f"q_lp_h{h}"])
        q = sub[f"q_lp_h{h}"].to_numpy()
        v = sub["notional_token0"].to_numpy()
        benign = (sub["label"] == "benign").to_numpy()
        real_gas = base_fee_gas_usd(sub)

        sweep = [simulate(q, v, benign, GAS_COST_USD, real_gas=real_gas, **s) for s in schedule_grid()]
        sweep.sort(key=lambda r: -r["net_lp_pnl_m"])
        base = baseline(q, v, GAS_COST_USD, real_gas)
        by_horizon[f"h{h}"] = {
            "n_swaps": len(sub), "baseline": base,
            "sweep_top10": sweep[:10],
            "lowest_builder_bid_top10": sorted(sweep, key=lambda r: r["builder_bid_ceiling_m"])[:10],
            "sweep_all": sweep,
        }
        hedge_by_h[f"h{h}"] = hedge_sensitivity(q, v, real_gas)

        for name, sched in tracked.items():
            s = simulate(q, v, benign, GAS_COST_USD, real_gas=real_gas, **sched)
            s["captured_by_label_m"] = captured_by_label(q, v, sub["label"].to_numpy(), **sched)
            tracked_by_h.append({
                "schedule": name, "horizon_s": h,
                "baseline_net_lp_pnl_m": base["net_lp_pnl_m"],
                "baseline_builder_bid_ceiling_m": base["builder_bid_ceiling_m"],
                **s,
                "net_vs_baseline_m": round(s["net_lp_pnl_m"] - base["net_lp_pnl_m"], 2),
                "survival_ratio": round(s["arb_survival"] / base["arb_survival"], 3),
                "survival_ratio_real_cost": round(s["arb_survival_real_cost"] / base["arb_survival_real_cost"], 3),
                "bid_ceiling_vs_today": round(s["builder_bid_ceiling_m"] / base["builder_bid_ceiling_m"], 3),
            })

            models = dict(gas_models, base_fee_x250k_gas=real_gas)
            for gname, gas in models.items():
                b = baseline(q, v, gas)
                t = simulate(q, v, benign, gas, **sched)
                gas_sens.append({
                    "schedule": name, "horizon_s": h, "gas_model": gname,
                    "baseline_survival": b["arb_survival"],
                    "schedule_survival": t["arb_survival"],
                    "survival_ratio": round(t["arb_survival"] / b["arb_survival"], 3) if b["arb_survival"] else None,
                })

    out = {
        "n_swaps_total": len(df),
        "assumptions": {"flat_gas_usd": GAS_COST_USD, "real_gas": f"base fee x {ARB_GAS_UNITS:,} gas",
                        "hedge_cost_bps": HEDGE_COST_BPS},
        "tracked_schedules": {"headline": {"form": "clip", "alpha": 1.0, "cap_bps": 100.0, "f_benign_bps": 5.0},
                              "objective": {"form": "margin", "m_bps": 2.0, "cap_bps": 500.0, "f_benign_bps": 5.0}},
        "tracked_by_horizon": tracked_by_h,
        "hedge_sensitivity_margin_cap500": hedge_by_h,
        "gas_sensitivity": gas_sens,
        "by_horizon": by_horizon,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    print(json.dumps({k: res[k] for k in ["n_swaps_total", "tracked_by_horizon"]}, indent=2))
