"""Study J — oracle-error stress (P§3.5, P§4.2).

Every charge the protocol levies is computed against an oracle report. This
study asks what happens when that report is wrong in the three ways real
feeds are wrong, holding everything else at the canonical design:

  truth      canonical q (arb_exit bid/ask, 1s window centred on
             block_ts + L — Study E), the q the protocol SHOULD charge on
  delay d    the protocol reads the window centred on block_ts + L − d: a
             report d seconds staler than the decision instant
  noise σ    one lognormal error per BLOCK on both sides of the quote (one
             report per block, shared by every swap in it)
  bias b     a constant error on both sides (a feed that sits off the
             market, e.g. a venue basis)

Rule stressed: Study B's objective schedule (margin, m = 2bp, cap 500bp,
f_benign 5bp), the cash ceiling the REP mechanism approximates. Charge per
swap = fee delta over the pool's 5bp, from the q the protocol computes.

Reported per variant, against truth:
  overcharge_m       Σ max(charge(q') − charge(q), 0)·V — levied beyond what
                     the true price justifies (the user-facing risk)
  overcharge_benign  the same on router-origin (benign-labeled) flow, in bp
                     of that flow's volume
  wrongful_swaps     swaps charged although their true extraction is ≤ m
  missed_m           Σ max(charge(q) − charge(q'), 0)·V — recapture lost
  capture_fraction   recaptured / gross extraction, as Study B reports it

Tolerance sweep: the paper's ε (P§4.2) is the protocol's answer to oracle
error — charge only extraction beyond m + ε. For each error variant and
ε ∈ EPS_BPS, the protocol charges with m + ε while truth stays at m; the
trade-off is overcharge removed vs recapture given up.

HONESTY: Binance bid/ask stands in for both the truth and the feed; real
Data Streams reports differ from Binance by a venue basis this study models
only as bias/noise. Delay is applied to the whole kernel window.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .canonical import Q_C
from .config import RESULTS_DIR
from .directional import SidedSeries, compose_eth_usdc
from .normalization import block_time_us
from .pools import STUDY_POOL
from .study_b import BASELINE_FEE, OBJECTIVE, fee_rates
from .study_e import C_WIDTH_S, KERNEL_STEP_S, LABELS_DIR, _frame, kernel_q

OUT = RESULTS_DIR / "study_j"
DELAYS_S = [0.5, 1.0, 2.0, 5.0]
NOISE_BPS = [1.0, 2.0, 5.0]
BIAS_BPS = [-3.0, -1.0, 1.0, 3.0]
SEED = 11
EPS_BPS = [0.0, 1.0, 2.0, 4.0]


def charge(q: np.ndarray, v: np.ndarray, eps: float = 0.0) -> np.ndarray:
    """USD charged per swap under the objective schedule with allowance
    m + eps: fee delta over the pool's actual 5bp, on LP-negative q only."""
    delta = fee_rates(np.nan_to_num(q, nan=0.0), **{**OBJECTIVE, "m": OBJECTIVE["m"] + eps}) - BASELINE_FEE
    return np.maximum(delta, 0.0) * v


def compare(name: str, q_true, q_prot, v, benign, eps: float = 0.0) -> dict:
    ok = ~np.isnan(q_true) & ~np.isnan(q_prot)
    qt, qp, vv, bn = q_true[ok], q_prot[ok], v[ok], benign[ok]
    ct, cp = charge(qt, vv), charge(qp, vv, eps)
    over = np.maximum(cp - ct, 0.0)
    miss = np.maximum(ct - cp, 0.0)
    gross = float(-(qt[qt < 0] * vv[qt < 0]).sum())
    m = OBJECTIVE["m"]
    return {
        "variant": name, "eps_bps": round(eps * 1e4, 2), "n": int(ok.sum()),
        "charged_m": round(float(cp.sum()) / 1e6, 3),
        "overcharge_m": round(float(over.sum()) / 1e6, 3),
        "overcharge_share_of_charged": round(float(over.sum() / max(cp.sum(), 1)), 4),
        "overcharge_benign_bps": round(float(over[bn].sum() / max(vv[bn].sum(), 1) * 1e4), 4),
        "wrongful_swaps": int(((cp > 0) & (-qt <= m)).sum()),
        "wrongful_swap_share_of_charged": round(float(((cp > 0) & (-qt <= m)).sum() / max((cp > 0).sum(), 1)), 4),
        "missed_m": round(float(miss.sum()) / 1e6, 3),
        "capture_fraction": round(float(cp.sum() / gross), 4) if gross else None,
    }


def run() -> dict:
    L = json.loads((RESULTS_DIR / "study_e" / "metrics.json").read_text())["decision_latency_L_s"]
    eth, usdc = SidedSeries.load(STUDY_POOL.bench), SidedSeries.load(STUDY_POOL.numeraire)
    df = _frame(STUDY_POOL)
    labels = pd.concat(pd.read_parquet(p) for p in sorted(LABELS_DIR.glob("*")))
    df = (df.merge(labels[["tx_hash", "log_index", "label"]], on=["tx_hash", "log_index"], how="left")
            .merge(pd.read_parquet(Q_C)[["tx_hash", "log_index", "q_c_h0"]], on=["tx_hash", "log_index"], how="left"))
    a0 = df["amount0_raw"].astype(float).to_numpy() / 10**STUDY_POOL.dec0
    a1 = df["amount1_raw"].astype(float).to_numpy() / 10**STUDY_POOL.dec1
    v = df["notional_token0"].to_numpy()
    benign = (df["label"] == "benign").to_numpy()
    bt = block_time_us(df)
    q_true = df["q_c_h0"].to_numpy()

    def window(price_fn, lo, hi):
        return kernel_q(a0, a1, bt, price_fn, lo, hi)[0]

    base = lambda t: compose_eth_usdc(eth.quotes(t), usdc.quotes(t))
    variants = {"truth (canonical)": q_true}
    for d in DELAYS_S:
        c = L - d
        variants[f"delay {d:g}s"] = window(base, c - C_WIDTH_S / 2, c + C_WIDTH_S / 2)
    rng = np.random.default_rng(SEED)
    blocks, inv = np.unique(df["block_number"].to_numpy(), return_inverse=True)
    for s in NOISE_BPS:
        z = np.exp(rng.normal(0.0, s / 1e4, len(blocks)))[inv]     # one report error per block

        def noisy(t, z=z):
            bid, ask = base(t)
            return bid * z, ask * z
        variants[f"noise {s:g}bp/block"] = window(noisy, L - C_WIDTH_S / 2, L + C_WIDTH_S / 2)
    for b in BIAS_BPS:
        f = np.exp(b / 1e4)

        def biased(t, f=f):
            bid, ask = base(t)
            return bid * f, ask * f
        variants[f"bias {b:+g}bp"] = window(biased, L - C_WIDTH_S / 2, L + C_WIDTH_S / 2)

    rows = [compare(name, q_true, qp, v, benign, e / 1e4) for name, qp in variants.items() for e in EPS_BPS]
    out = {"L_s": L, "rule": "Study B objective: margin m=2bp, cap 500bp, f_benign 5bp",
           "kernel": f"{C_WIDTH_S:g}s window, {KERNEL_STEP_S:g}s grid", "variants": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    for r in res["variants"]:
        print(f"{r['variant']:22s} eps {r['eps_bps']:3g}bp charged ${r['charged_m']:6.3f}M  over ${r['overcharge_m']:6.3f}M ({r['overcharge_share_of_charged']*100:5.1f}%)  "
              f"benign over {r['overcharge_benign_bps']:6.3f}bp  wrongful {r['wrongful_swap_share_of_charged']*100:5.1f}%  "
              f"missed ${r['missed_m']:6.3f}M  capture {r['capture_fraction']}")
