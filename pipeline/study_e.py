"""Study E — timestamp sensitivity and ε calibration (P§3.4, P§4.2).

Ethereum L1 has no per-tx timestamps, so every q_LP depends on a
reconstructed execution instant. Reconstructions compared:

    block     t = block_ts                        (all swaps at slot start)
    forward   t = block_ts + frac·dur             (current t_norm_us, §17.7)
    backward  t = block_ts − frac·dur             (index 0 latest, deeper txs earlier)
    kernel_w  mean q over t ∈ [block_ts − w, block_ts], 0.25s grid (P§4.2),
              swept over window widths w — the kernel width, not just its
              existence, decides how stale the scoring price is

    *_L       the same, anchored at block_ts + L instead of block_ts, where
              L is the measured decision latency (profile below)
    centered_w mean q over [block_ts + L − w/2, block_ts + L + w/2]

with frac = tx_index / tx_count, dur = next_block_ts − block_ts.

Forward places mid-block swaps AFTER block_ts, but a mainnet block is
built during the previous slot and sealed around block_ts — so forward
prices mid-block swaps against CEX prints the swapper could not have
seen (lookahead).

Decision-time profile. An arb that closes the gap stops where the pool
price net of the 5bp fee equals the CEX price it can hedge at:

    pool sends ETH:    ln P_post = ln bid(t) − ln(1+f)
    pool receives ETH: ln P_post = ln ask(t) − ln(1−f)

For offsets −24s..+6s around block_ts, the median |residual| of that
relation per group; the argmin is when the group priced its trades.
The bid/ask proxy is ~0.75s stale at the median, which biases the argmin
LATER (a lagging quote matches the arb's reference later than the true
book did). So the profile is run twice: last print at or before t (lags,
biases late) and next print at or after t (leads, biases early). The
true latency sits between; L = midpoint of the bracket on toxic_top3.
Measured 2026-03..08: bracket [+1.25s, +1.75s], fresh-quotes-only
cross-check +1.0s. Blocks are published into the slot (MEV-Boost timing
games) and arbs quote until the final bid is taken. L is never hardcoded;
anchored results are also reported across L_SWEEP_S. Only
meaningful for gap-closing flow (toxic, top-of-block, large); benign is
the no-relation reference. A raw |pool − mid| gap is biased toward
earlier offsets in trending markets (the pool trails CEX by the fee) and
must not be used. P_post comes from the Swap event tick.

The trailing kernel [block_ts − w, block_ts] looks AWAY from the decision
instant, so widening it scores arbs against pre-move prices and erases
extraction; it is kept in the output as the documented pitfall.

Timing noise: per-swap std of q_LP over the kernel window — how much q
moves purely because the instant is unknown. ε candidates are its
quantiles at the chosen width. The USDC/USDT control barely moves inside
a slot, so it bounds peg noise only and cannot calibrate timing noise.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import DATA_DIR, REPO_ROOT
from .directional import SidedSeries, compose_eth_usdc, directional_price
from .pools import ETH_USDC, USDC_USDT
from .qlp import q_lp
from .study_a import mann_whitney_auc
from .study_b import GAS_COST_USD, HEADLINE, baseline, simulate

SCORED = DATA_DIR / "onchain" / "scored"
LABELS_DIR = DATA_DIR / "onchain" / "labels" / ETH_USDC.name
OUT = REPO_ROOT / "results" / "study_e"

KERNEL_STEP_S = 0.25
KERNEL_WIDTHS_S = [0.5, 1.0, 2.0, 4.0, 8.0, 12.0]      # trailing (pitfall)
CENTERED_WIDTHS_S = [0.5, 1.0, 2.0, 4.0]                # around block_ts + L
PROFILE_OFFSETS_S = np.round(np.arange(-24.0, 6.0 + 1e-9, 0.25), 2)
POOL_FEE = 0.0005
L_SWEEP_S = [0.0, 1.0, 1.25, 1.5, 1.75]

# Chosen scoring timeline for Study C (P§4.2): arb_exit q, kernel centered
# on block_ts + L + h, width C_WIDTH_S. Written per swap for C to consume.
C_WIDTH_S = 1.0
C_HORIZONS_S = [0, 12, 30]
C_OUT = DATA_DIR / "onchain" / "scored_timing" / ETH_USDC.name


def _frame(pool) -> pd.DataFrame:
    df = pd.concat(pd.read_parquet(p) for p in sorted((SCORED / pool.name).glob("*.scored.parquet")))
    df["dur_s"] = (df["next_block_ts"] - df["block_ts"]).fillna(12).clip(1, 60)
    df["frac"] = df["tx_index"] / df["tx_count"].clip(lower=1)
    return df.reset_index(drop=True)


def reconstruction_times(df: pd.DataFrame) -> dict[str, np.ndarray]:
    bt = df["block_ts"].to_numpy(dtype=np.int64) * 1_000_000
    shift = (df["frac"] * df["dur_s"] * 1e6).to_numpy().astype(np.int64)
    return {"block": bt, "forward": df["t_norm_us"].to_numpy(dtype=np.int64), "backward": bt - shift}


def eth_quotes(eth, usdc, t_us, nxt: bool = False):
    if nxt:
        return compose_eth_usdc(eth.next_quotes(t_us), usdc.next_quotes(t_us))
    return compose_eth_usdc(eth.quotes(t_us), usdc.quotes(t_us))


def q_at(a0, a1, bid, ask, conv="arb_exit"):
    return q_lp(a0, a1, directional_price(a1, bid, ask, conv))[0]


def kernel_q(a0, a1, bt_us, price_fn, lo_s: float, hi_s: float, conv="arb_exit"):
    """Mean and std of q over t ∈ [block_ts + lo_s, block_ts + hi_s]."""
    offs = np.arange(lo_s, hi_s + 1e-9, KERNEL_STEP_S)
    s = np.zeros(len(a0)); ss = np.zeros(len(a0)); n = np.zeros(len(a0))
    for off in offs:
        bid, ask = price_fn(bt_us + int(round(off * 1e6)))
        q = q_at(a0, a1, bid, ask, conv)
        m = ~np.isnan(q)
        s[m] += q[m]; ss[m] += q[m] ** 2; n[m] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s / n
        std = np.sqrt(np.maximum(ss / n - mean ** 2, 0))
    return mean, std


def kernel_row(label: str, width: float, mean, std, v, lab) -> dict:
    sd = std * 1e4
    ok = ~np.isnan(sd)
    return {
        "kernel": label, "width_s": width,
        **evaluate(mean, v, lab),
        "timing_noise_std_bps_p50": round(float(np.median(sd[ok])), 3),
        "timing_noise_std_bps_p90": round(float(np.percentile(sd[ok], 90)), 3),
        "timing_noise_std_bps_p50_gt100k": round(float(np.median(sd[ok & (v > 1e5)])), 3),
        "timing_noise_std_bps_notional_weighted": round(float(np.average(sd[ok], weights=v[ok])), 3),
    }


def evaluate(q, v, lab) -> dict:
    ok = ~np.isnan(q)
    q, v, lab = q[ok], v[ok], lab[ok]
    neg = q < 0
    base = baseline(q, v, GAS_COST_USD)
    head = simulate(q, v, lab == "benign", GAS_COST_USD, **HEADLINE)
    big = v > 1e5
    return {
        "n": int(ok.sum()),
        "share_lp_negative": round(float(neg.mean()), 4),
        "gross_lvr_m": round(float(-(q[neg] * v[neg]).sum()) / 1e6, 2),
        "baseline_net_lp_m": base["net_lp_pnl_m"],
        "headline_delta_m": round(head["net_lp_pnl_m"] - base["net_lp_pnl_m"], 2),
        "headline_capture_fraction": head["capture_fraction"],
        "auc": round(mann_whitney_auc(-q[lab == "toxic"], -q[lab == "benign"]), 4),
        "auc_gt100k": round(mann_whitney_auc(-q[big & (lab == "toxic")], -q[big & (lab == "benign")]), 4),
    }


def decision_time_profile(df, eth, usdc, lab, a1, nxt: bool = False) -> dict:
    """Median |fee-adjusted residual| between the pool's post-swap price
    and the CEX side an arb hedges at, per offset from block_ts."""
    # tick -> token1/token0 raw; USDC per WETH = 10^(dec1-dec0) / 1.0001^tick
    lp = (ETH_USDC.dec1 - ETH_USDC.dec0) * np.log(10.0) - df["tick"].to_numpy(dtype=float) * np.log(1.0001)
    sent = a1 < 0
    expected = np.where(sent, -np.log1p(POOL_FEE), -np.log1p(-POOL_FEE))
    bt = df["block_ts"].to_numpy(dtype=np.int64) * 1_000_000
    idx = df["tx_index"].to_numpy()
    big = df["notional_token0"].to_numpy() > 1e5
    tox = lab == "toxic"
    groups = {
        "toxic_all": tox,
        "toxic_top3": tox & (idx < 3),
        "idx0_gt100k": (idx == 0) & big,
        "idx1-2_gt100k": (idx >= 1) & (idx < 3) & big,
        "idx3-9_gt100k": (idx >= 3) & (idx < 10) & big,
        "idx10+_gt100k": (idx >= 10) & big,
        "benign_all (no-relation reference)": lab == "benign",
    }
    curves = {g: [] for g in groups}
    for off in PROFILE_OFFSETS_S:
        bid, ask = eth_quotes(eth, usdc, bt + int(off * 1e6), nxt)
        ref = np.where(sent, bid, ask)
        res = np.abs(lp - np.log(ref) - expected) * 1e4
        for g, m in groups.items():
            curves[g].append(float(np.nanmedian(res[m])))
    offs = PROFILE_OFFSETS_S.tolist()
    by_group = {}
    for g, c in curves.items():
        c = np.array(c)
        i = int(np.nanargmin(c))
        by_group[g] = {
            "n": int(groups[g].sum()),
            "best_offset_s": float(PROFILE_OFFSETS_S[i]),
            "at_grid_edge": i in (0, len(c) - 1),
            "resid_at_best_bps": round(float(c[i]), 3),
            **{f"resid_at_{o:+g}s_bps": round(float(c[offs.index(o)]), 3)
               for o in (-12.0, -4.0, -2.0, -1.0, 0.0, 1.0, 2.0, 6.0)},
            "curve_bps": [round(float(x), 3) for x in c],
        }
    return {"offsets_s": offs, "by_group": by_group}


def control(usdc) -> dict:
    df = _frame(USDC_USDT)
    a0 = df["amount0_raw"].astype(float).to_numpy() / 10**USDC_USDT.dec0
    a1 = df["amount1_raw"].astype(float).to_numpy() / 10**USDC_USDT.dec1

    def px(t):
        q = usdc.quotes(t)
        return 1.0 / q["ask"], 1.0 / q["bid"]

    res = {}
    for name, t in reconstruction_times(df).items():
        aq = np.abs(q_at(a0, a1, *px(t)))
        aq = aq[~np.isnan(aq)] * 1e4
        res[name] = {"abs_q_median_bps": round(float(np.median(aq)), 3),
                     "abs_q_p95_bps": round(float(np.percentile(aq, 95)), 3)}
    return res


def run() -> dict:
    eth, usdc = SidedSeries.load("ETHUSDT"), SidedSeries.load("USDCUSDT")
    df = _frame(ETH_USDC)
    labels = pd.concat(pd.read_parquet(p) for p in sorted(LABELS_DIR.glob("*")))
    df = df.merge(labels[["tx_hash", "log_index", "label"]], on=["tx_hash", "log_index"], how="left")
    lab = df["label"].to_numpy()
    a0 = df["amount0_raw"].astype(float).to_numpy() / 10**ETH_USDC.dec0
    a1 = df["amount1_raw"].astype(float).to_numpy() / 10**ETH_USDC.dec1
    v = df["notional_token0"].to_numpy()

    profile = decision_time_profile(df, eth, usdc, lab, a1)
    profile_next = decision_time_profile(df, eth, usdc, lab, a1, nxt=True)
    L_late = profile["by_group"]["toxic_top3"]["best_offset_s"]
    L_early = profile_next["by_group"]["toxic_top3"]["best_offset_s"]
    L = round((L_late + L_early) / 2 / 0.25) * 0.25
    Lus = int(round(L * 1e6))
    price = lambda t: eth_quotes(eth, usdc, t)

    recon = {}
    for name, t in reconstruction_times(df).items():
        recon[name] = evaluate(q_at(a0, a1, *price(t)), v, lab)
        if name != "forward":
            recon[f"{name}_L"] = evaluate(q_at(a0, a1, *price(t + Lus)), v, lab)

    bt = df["block_ts"].to_numpy(dtype=np.int64) * 1_000_000
    latency_sweep = [{"L_s": x, **evaluate(q_at(a0, a1, *price(bt + int(round(x * 1e6)))), v, lab)}
                     for x in L_SWEEP_S]
    kernels = []
    for w in KERNEL_WIDTHS_S:
        kernels.append(kernel_row("trailing [bt-w, bt]", w, *kernel_q(a0, a1, bt, price, -w, 0.0), v, lab))
    for w in CENTERED_WIDTHS_S:
        kernels.append(kernel_row("centered [bt+L-w/2, bt+L+w/2]", w,
                                  *kernel_q(a0, a1, bt, price, L - w / 2, L + w / 2), v, lab))

    c_cols = {"tx_hash": df["tx_hash"], "log_index": df["log_index"]}
    for h in C_HORIZONS_S:
        c = L + h
        c_cols[f"q_c_h{h}"] = kernel_q(a0, a1, bt, price, c - C_WIDTH_S / 2, c + C_WIDTH_S / 2)[0]
    C_OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(c_cols).to_parquet(C_OUT / "q_c.parquet", index=False)

    out = {
        "n_swaps": len(df),
        "study_c_input": {"file": str(C_OUT.relative_to(REPO_ROOT) / "q_c.parquet"),
                          "convention": "arb_exit", "anchor": "block_ts + L + h",
                          "kernel_width_s": C_WIDTH_S, "horizons_s": C_HORIZONS_S},
        "q_convention": "arb_exit (P§3.6/P§4.2)",
        "decision_latency_L_s": L,
        "decision_latency_bracket_s": {"next_print_early_bias": L_early, "last_print_late_bias": L_late},
        "kernel_grid_s": KERNEL_STEP_S,
        "by_reconstruction": recon,
        "kernel_width_sweep": kernels,
        "control_pool": control(usdc),
        "latency_sweep_block_anchor": latency_sweep,
        "decision_time_profile": profile,
        "decision_time_profile_next_print": profile_next,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    prof = {f"{tag}:{g}": {k: x for k, x in d.items() if k != "curve_bps"}
            for tag, key in (("last", "decision_time_profile"), ("next", "decision_time_profile_next_print"))
            for g, d in res[key]["by_group"].items()}
    print(json.dumps({"L": res["decision_latency_L_s"], "bracket": res["decision_latency_bracket_s"],
                      "latency_sweep": res["latency_sweep_block_anchor"],
                      "by_reconstruction": res["by_reconstruction"], "kernel_width_sweep": res["kernel_width_sweep"],
                      "control_pool": res["control_pool"], "decision_time": prof}, indent=2))
