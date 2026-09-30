"""Study D — directional benchmark proxy (P§3.6, spec Study D).

Re-scores every ETH/USDC swap against a touch-level bid/ask proxy
(pipeline/directional.py) under three conventions — mid, arb_exit,
paper_literal — beside the existing trade-price q_LP, then re-runs:

  - share LP-negative, gross LVR, LP net at every horizon
  - Study A AUC (all h; size slices at h0)
  - Study B baseline + headline schedule (all h)
  - the control-pool |q_LP| check under each convention (h0)

Notional is held at the trade-price value for every benchmark, so dollar
figures differ only through the markout.

Writes directional q columns to data/onchain/scored_directional/ for
Study C, whose primary q_LP is directional (P§4.2).

HONESTY (bind to writeup): touch proxy, not LWBA. Depth-weighted spreads
are wider for size, so this understates how far the directional rule
relaxes scoring on large trades. Layer-1 LWBA replaces it (spec item 13).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import DATA_DIR, HORIZONS_S, REPO_ROOT
from .directional import SidedSeries, compose_eth_usdc, directional_price
from .pools import ETH_USDC, USDC_USDT
from .qlp import q_lp
from .study_a import mann_whitney_auc
from .study_b import GAS_COST_USD, HEADLINE, baseline, simulate

SCORED = DATA_DIR / "onchain" / "scored"
LABELS_DIR = DATA_DIR / "onchain" / "labels" / ETH_USDC.name
DIR_OUT = DATA_DIR / "onchain" / "scored_directional" / ETH_USDC.name
OUT = REPO_ROOT / "results" / "study_d"

CONVENTIONS = ["mid", "arb_exit", "paper_literal"]
BENCHMARKS = ["trade"] + CONVENTIONS
GATE_CEILING_BPS = 38.4        # control gate ceiling (spec 3b)


def _col(bench: str, h: int) -> str:
    return f"q_lp_h{h}" if bench == "trade" else f"q_{bench}_h{h}"


def score_eth_usdc(eth: SidedSeries, usdc: SidedSeries) -> tuple[pd.DataFrame, dict]:
    DIR_OUT.mkdir(parents=True, exist_ok=True)
    parts, diag = [], {}
    for p in sorted((SCORED / ETH_USDC.name).glob("*.scored.parquet")):
        df = pd.read_parquet(p)
        a0 = df["amount0_raw"].astype(float).to_numpy() / 10**ETH_USDC.dec0
        a1 = df["amount1_raw"].astype(float).to_numpy() / 10**ETH_USDC.dec1
        t = df["t_norm_us"].to_numpy()
        v = df["notional_token0"].to_numpy()
        for h in HORIZONS_S:
            qe, qu = eth.quotes(t, h), usdc.quotes(t, h)
            bid, ask = compose_eth_usdc(qe, qu)
            for c in CONVENTIONS:
                markout = a0 + a1 * directional_price(a1, bid, ask, c)
                with np.errstate(invalid="ignore", divide="ignore"):
                    df[_col(c, h)] = np.where(v > 0, markout / v, np.nan)
            if h == 0:
                mid = (bid + ask) / 2
                df["_spread_bps"] = (ask - bid) / mid * 1e4
                df["_stale_eth_s"] = np.maximum(qe["stale_bid_s"], qe["stale_ask_s"])
                df["_stale_usdc_s"] = np.maximum(qu["stale_bid_s"], qu["stale_ask_s"])
                df["_crossed_eth"] = qe["crossed_raw"]
                df["_crossed_usdc"] = qu["crossed_raw"]
        keep = ["tx_hash", "log_index"] + [_col(c, h) for c in CONVENTIONS for h in HORIZONS_S]
        df[keep].to_parquet(DIR_OUT / p.name.replace(".scored.", ".dir."), index=False)
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)

    sp = df["_spread_bps"].dropna()
    diag = {
        "proxy": "touch (last bid-side / ask-side aggTrades print, bounded by last print)",
        "spread_bps_median": round(float(sp.median()), 3),
        "spread_bps_p90": round(float(sp.quantile(0.9)), 3),
        "spread_bps_p99": round(float(sp.quantile(0.99)), 3),
        "stale_gt1s_share_eth": round(float((df["_stale_eth_s"] > 1).mean()), 4),
        "stale_gt1s_share_usdc": round(float((df["_stale_usdc_s"] > 1).mean()), 4),
        "stale_median_s_usdc": round(float(df["_stale_usdc_s"].median()), 3),
        "crossed_raw_share_eth": round(float(df["_crossed_eth"].mean()), 4),
        "crossed_raw_share_usdc": round(float(df["_crossed_usdc"].mean()), 4),
    }
    return df.drop(columns=[c for c in df.columns if c.startswith("_")]), diag


def control_check(usdc: SidedSeries) -> list[dict]:
    """USDC/USDT pool at h0: USDT priced in USDC from the USDCUSDT book
    (buy USDT with USDC at 1/USDC_bid, sell at 1/USDC_ask)."""
    df = pd.concat(pd.read_parquet(p) for p in sorted((SCORED / USDC_USDT.name).glob("*.scored.parquet")))
    a0 = df["amount0_raw"].astype(float).to_numpy() / 10**USDC_USDT.dec0
    a1 = df["amount1_raw"].astype(float).to_numpy() / 10**USDC_USDT.dec1
    qu = usdc.quotes(df["t_norm_us"].to_numpy(), 0)
    bid, ask = 1.0 / qu["ask"], 1.0 / qu["bid"]
    out = []
    for bench in BENCHMARKS:
        if bench == "trade":
            q = df["q_lp_h0"].to_numpy()
        else:
            q, _ = q_lp(a0, a1, directional_price(a1, bid, ask, bench))
        aq = np.abs(q[~np.isnan(q)]) * 1e4
        out.append({
            "benchmark": bench,
            "abs_q_median_bps": round(float(np.median(aq)), 2),
            "abs_q_p95_bps": round(float(np.percentile(aq, 95)), 2),
            "share_lp_negative": round(float((q[~np.isnan(q)] < 0).mean()), 4),
            "gate_pass": bool(np.percentile(aq, 95) < GATE_CEILING_BPS),
        })
    return out


def evaluate(df: pd.DataFrame) -> dict:
    labels = pd.concat(pd.read_parquet(p) for p in sorted(LABELS_DIR.glob("*")))
    df = df.merge(labels[["tx_hash", "log_index", "label"]], on=["tx_hash", "log_index"], how="left")
    df = df.dropna(subset=["notional_token0"])
    v_all = df["notional_token0"].to_numpy()
    lab = df["label"].to_numpy()
    benign_all = lab == "benign"

    rows, auc_slices = [], {}
    for bench in BENCHMARKS:
        for h in HORIZONS_S:
            q_all = df[_col(bench, h)].to_numpy()
            ok = ~np.isnan(q_all)
            q, v, benign = q_all[ok], v_all[ok], benign_all[ok]
            neg = q < 0
            base = baseline(q, v, GAS_COST_USD)
            head = simulate(q, v, benign, GAS_COST_USD, **HEADLINE)
            l = lab[ok]
            rows.append({
                "benchmark": bench, "horizon_s": h, "n": int(ok.sum()),
                "share_lp_negative": round(float(neg.mean()), 4),
                "gross_lvr_m": round(float(-(q[neg] * v[neg]).sum()) / 1e6, 2),
                "baseline_net_lp_m": base["net_lp_pnl_m"],
                "headline_net_lp_m": head["net_lp_pnl_m"],
                "headline_delta_m": round(head["net_lp_pnl_m"] - base["net_lp_pnl_m"], 2),
                "headline_capture_fraction": head["capture_fraction"],
                "headline_residual_m": head["residual_extraction_m"],
                "headline_benign_overcharge_bps": head["benign_overcharge_bps"],
                "headline_survival_ratio": round(head["arb_survival"] / base["arb_survival"], 3),
                "auc": round(mann_whitney_auc(-q[l == "toxic"], -q[l == "benign"]), 4),
            })
        q0 = df[_col(bench, 0)].to_numpy()
        for lo, hi, name in [(0, 1e4, "lt10k"), (1e4, 1e5, "10k_100k"), (1e5, 1e12, "gt100k")]:
            m = (v_all >= lo) & (v_all < hi) & ~np.isnan(q0)
            auc_slices[f"{bench}_h0_{name}"] = round(
                mann_whitney_auc(-q0[m & (lab == "toxic")], -q0[m & (lab == "benign")]), 4)
    return {"by_benchmark_horizon": rows, "auc_h0_size_slices": auc_slices}


def run() -> dict:
    eth, usdc = SidedSeries.load("ETHUSDT"), SidedSeries.load("USDCUSDT")
    df, diag = score_eth_usdc(eth, usdc)
    out = {
        "n_swaps": len(df),
        "proxy_diagnostics_h0": diag,
        "control_pool_h0": control_check(usdc),
        **evaluate(df),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    print(json.dumps({k: res[k] for k in ["n_swaps", "proxy_diagnostics_h0", "control_pool_h0"]}, indent=2))
