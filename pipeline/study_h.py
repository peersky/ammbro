"""Study H — auto-balancing allowance m (spec: design objective).

The margin schedule charges extraction beyond an allowance m left to the
arb for its costs. m must sit just above the competitive cost of
rebalancing, which is private (CEX fee tiers), so m has to be discovered.
This study (1) commits the evidence for which on-chain signals can drive
it, (2) scores position cutoffs, including block thirds, as rent signals,
and (3) demonstrates controllers in an agent simulation on the real
gap-taking opportunities.

1. Signals (today, 2026-03..08). Gap-takers = the block's first swap on
   the pool, price-correcting (moved the pool toward the oracle at
   block_ts + L). Today's rent = extraction − base-fee gas − h·V, h = 1bp.
2. Cutoffs. Positive class = gap-takers with rent > 0. TPR, FPR, Youden J
   for index / block-fraction / priority rules; AUC of each raw signal.
3. Simulation. Each real LP-negative gap-taking opportunity (extraction
   x, notional V, gas g) is contested by an arb population with hedge
   costs h_j. Under allowance m an arb keeps min(x, m)·V and nets
   min(x, m)·V − g − h_j·V. Cheapest arb wins; it pays the builder the
   second-best net (second-price auction for the top slot) and keeps the
   difference. The LP recaptures max(x − m, 0)·V. If no arb nets ≥ 0 the
   opportunity is left uncorrected (staleness). Arb costs double halfway
   through the window (x2 and x4 scenarios) to test whether m tracks the
   market and whether any fixed m survives the change. One epoch = one
   UTC day.
   Signals feeding the controllers are resampled from (1): a contested
   win (bid > 0) takes the flag rate and block position of today's
   rent-bearing gap-takers, an uncontested win those of no-rent
   gap-takers, and an uncorrected block the position of today's
   non-correcting first swaps. Top slots are sold block-wide, so the flag
   rate depends on how busy the block is (quiet blocks give free top
   slots; busy ones displace our pool's arb). Flag probabilities are
   therefore drawn per opportunity from its own block's base-fee quintile
   ("confounded"); a pooled-rate variant is kept as the optimistic
   reference, and a busyness-normalised threshold is tested as the fix.

HONESTY (bind to writeup): the arb cost population is ASSUMED; the
opportunity set is static (x does not shrink as the pool gets less
stale); the auction ignores latency; signal rates come from today's
cross-section, not an equilibrium under REP-AMM; builder payments here
are model output, not measurement (spec item 11b). The simulation shows
controller dynamics, not a forecast of dollar outcomes.
"""
from __future__ import annotations

from .normalization import block_time_us

import json

import numpy as np
import pandas as pd

from .config import DATA_DIR, REPO_ROOT, ONCHAIN_DIR, RESULTS_DIR
from .directional import SidedSeries
from .pools import STUDY_POOL
from .study_a import mann_whitney_auc
from .study_b import base_fee_gas_usd
from .study_e import LABELS_DIR, _frame, eth_quotes

OUT = RESULTS_DIR / "study_h"
Q_C = ONCHAIN_DIR / "scored_timing" / STUDY_POOL.name / "q_c.parquet"
TXS_DIR = ONCHAIN_DIR / "txs" / STUDY_POOL.name

HEDGE_BPS = 1.0                 # rent classification in (1)/(2)
FLAG_IDX, FLAG_PRIO_GWEI = 2, 2.0   # controller flag = idx <= FLAG_IDX (best Youden J, section 2)
RENT_EDGES = [(-np.inf, 0, "no rent (< cost)"), (0, 10, "$0-10"), (10, 100, "$10-100"),
              (100, 1000, "$100-1k"), (1000, np.inf, ">$1k")]

ARB_COSTS_BPS = np.array([0.3, 0.6, 1.0, 1.5, 2.5])   # assumed population
COST_SHIFTS = {"costs_x2": 2.0, "costs_x4": 4.0}        # second half of window
PLOT_SCENARIO = "costs_x4"
M0_BPS, M_MIN_BPS, M_MAX_BPS = 5.0, 0.05, 50.0
S_STAR = 0.02                   # uncorrected share of correctable opportunities: raise above
S_LOW = 0.005                   # three-zone variant: lower below, hold between S_LOW and S_STAR
# Flag threshold tau: midpoint of today's flag rates for rent / no-rent gap-takers (data-derived).
SEED = 7


def prepare() -> tuple[pd.DataFrame, float]:
    L = json.loads((RESULTS_DIR / "study_e" / "metrics.json").read_text())["decision_latency_L_s"]
    eth, usdc = SidedSeries.load(STUDY_POOL.bench), SidedSeries.load(STUDY_POOL.numeraire)
    df = _frame(STUDY_POOL)
    labels = pd.concat(pd.read_parquet(p) for p in sorted(LABELS_DIR.glob("*")))
    txs = pd.concat(pd.read_parquet(p) for p in sorted(TXS_DIR.glob("*")))
    df = (df.merge(labels[["tx_hash", "log_index", "label"]], on=["tx_hash", "log_index"], how="left")
            .merge(pd.read_parquet(Q_C)[["tx_hash", "log_index", "q_c_h0"]], on=["tx_hash", "log_index"], how="left")
            .merge(txs[["tx_hash", "priority_fee_wei"]].drop_duplicates("tx_hash"), on="tx_hash", how="left"))
    df = df.sort_values(["block_number", "tx_index", "log_index"]).reset_index(drop=True)
    df["k"] = df.groupby("block_number").cumcount()
    bt = block_time_us(df)
    bid, ask = eth_quotes(eth, usdc, bt + int(round(L * 1e6)))
    ln_o = np.log((bid + ask) / 2)
    ln_post = (18 - 6) * np.log(10.0) - df["tick"].to_numpy(float) * np.log(1.0001)
    ln_pre = np.r_[np.nan, ln_post[:-1]]
    df["correcting"] = (np.abs(ln_post - ln_o) - np.abs(ln_pre - ln_o)) < 0
    df["pre_gap_bps"] = np.abs(ln_pre - ln_o) * 1e4
    df["x"] = np.maximum(-df["q_c_h0"].to_numpy(), 0.0)
    df["gas"] = base_fee_gas_usd(df)
    df["prio_gwei"] = df["priority_fee_wei"].astype(float) / 1e9
    df["day"] = (df["block_ts"] // 86400).astype(int)
    df["v"] = df["notional_token0"]
    df["rent_today"] = df["x"] * df["v"] - df["gas"] - HEDGE_BPS / 1e4 * df["v"]
    df["flag"] = df["tx_index"] <= FLAG_IDX
    df["first"] = df["k"] == 0
    df["gt"] = df["first"] & df["correcting"] & df["q_c_h0"].notna()
    return df, L


def signals(df: pd.DataFrame) -> dict:
    gt = df[df["gt"]]
    rows = []
    for lo, hi, name in RENT_EDGES:
        s = gt[(gt.rent_today >= lo) & (gt.rent_today < hi)]
        hid = s[s.prio_gwei < 0.05]
        rows.append({
            "rent_bucket": name, "n": len(s),
            "first_third": round(float((s.frac < 1 / 3).mean()), 4),
            "last_third": round(float((s.frac >= 2 / 3).mean()), 4),
            "median_tx_index": float(s.tx_index.median()),
            "priority_gwei_median": round(float(s.prio_gwei.median()), 2),
            "priority_gwei_p90": round(float(s.prio_gwei.quantile(0.9)), 2),
            "hidden_bid_share": round(float(len(hid) / len(s)), 4),
            "hidden_bid_idx_le2": round(float((hid.tx_index <= 2).mean()), 4) if len(hid) else None,
            "flag_idx_le2": round(float((s.tx_index <= 2).mean()), 4),
            "flag_priority_gt2": round(float((s.prio_gwei > 2).mean()), 4),
            "flag_either": round(float(((s.tx_index <= FLAG_IDX) | (s.prio_gwei > FLAG_PRIO_GWEI)).mean()), 4),
        })
    fp = df[df["first"] & df["pre_gap_bps"].notna()]
    return {
        "gap_taker_definition": "first pool swap in block, moved pool toward oracle at block_ts+L",
        "first_swap_price_correcting_share": round(float(df.loc[df["first"], "correcting"].mean()), 4),
        "by_rent": rows,
        "non_correcting_first_swaps": {
            "first_third": round(float((df.loc[df["first"] & ~df["correcting"], "frac"] < 1 / 3).mean()), 4),
            "last_third": round(float((df.loc[df["first"] & ~df["correcting"], "frac"] >= 2 / 3).mean()), 4),
            "priority_gwei_median": round(float(df.loc[df["first"] & ~df["correcting"], "prio_gwei"].median()), 2)},
        "staleness_before_first_swap_bps": {q: round(float(fp.pre_gap_bps.quantile(p)), 2)
                                            for q, p in (("p50", .5), ("p75", .75), ("p90", .9), ("p99", .99))},
    }


def cutoffs(df: pd.DataFrame) -> dict:
    gt = df[df["gt"]]
    pos = (gt.rent_today > 0).to_numpy()
    idx, frac, prio = gt.tx_index.to_numpy(), gt.frac.to_numpy(), gt.prio_gwei.to_numpy()
    rules = {f"idx <= {c}": idx <= c for c in (0, 1, 2, 3, 5, 10)}
    rules |= {f"block fraction < {f:g}": frac < f for f in (0.02, 0.05, 0.1)}
    rules["block fraction < 1/3 (thirds)"] = frac < 1 / 3
    rules |= {f"priority > {p:g} gwei": prio > p for p in (1, 2, 5)}
    rules["idx <= 2 OR priority > 2 gwei"] = (idx <= 2) | (prio > 2)
    rules["idx <= 1 OR priority > 2 gwei"] = (idx <= 1) | (prio > 2)
    rows = []
    for name, r in rules.items():
        tpr, fpr = float(r[pos].mean()), float(r[~pos].mean())
        rows.append({"rule": name, "tpr_rent": round(tpr, 4), "fpr_no_rent": round(fpr, 4), "youden_j": round(tpr - fpr, 4)})
    rows.sort(key=lambda r: -r["youden_j"])
    ok = ~np.isnan(prio)
    return {
        "positive_class": f"gap-takers with rent > 0 today (hedge {HEDGE_BPS}bp)",
        "n_pos": int(pos.sum()), "n_neg": int((~pos).sum()),
        "auc_lower_index": round(mann_whitney_auc(-idx[pos], -idx[~pos]), 4),
        "auc_lower_block_fraction": round(mann_whitney_auc(-frac[pos], -frac[~pos]), 4),
        "auc_priority_fee": round(mann_whitney_auc(prio[pos & ok], prio[~pos & ok]), 4),
        "raise_zone_last_third": {"rent": round(float((frac[pos] >= 2 / 3).mean()), 4),
                                  "no_rent": round(float((frac[~pos] >= 2 / 3).mean()), 4)},
        "rules_by_youden_j": rows,
    }


N_BUSY = 5                      # base-fee quintiles for the block-busyness confound

CONTROLLERS = [
    "today (no reconciliation)", "static m=1bp", "static m=2bp", "static m=5bp",
    "thirds rule, x2 / /2", "staleness + flag, x2 / /2", "staleness + flag, x1.25 / x0.8 / decay 0.95",
    "staleness 3-zone + flag, x1.25 / x0.8 / decay 0.95",
    "staleness 3-zone + flag, asymmetric x2 up / x0.8 / decay 0.95",
    "staleness 3-zone + flag (pooled rates, no confound), asymmetric x2 up / x0.8 / decay 0.95",
    "staleness 3-zone + flag (busyness-normalised tau), asymmetric x2 up / x0.8 / decay 0.95",
    "staleness 3-zone only, asymmetric x2 up / decay 0.95",
    "staleness 3-zone only, asymmetric x2 up / decay 0.9",
    "staleness 3-zone only, asymmetric x2 up / decay 0.85",
]


def simulate(df: pd.DataFrame, cost_shift: float) -> dict:
    gt = df[df["gt"]]
    pool_rent = gt.loc[gt.rent_today > 0, "frac"].to_numpy()
    pool_norent = gt.loc[gt.rent_today <= 0, "frac"].to_numpy()
    pool_noncorr = df.loc[df["first"] & ~df["correcting"], "frac"].to_numpy()
    p_flag_rent = float(gt.loc[gt.rent_today > 0, "flag"].mean())
    p_flag_norent = float(gt.loc[gt.rent_today <= 0, "flag"].mean())
    tau = (p_flag_rent + p_flag_norent) / 2
    bf = gt["base_fee_wei"].astype(float)
    try:
        busy = pd.qcut(bf, N_BUSY, labels=False).to_numpy()
    except ValueError:   # L2: base fee sits at its floor in most blocks -> tied edges; split by rank
        busy = pd.qcut(bf.rank(method="first"), N_BUSY, labels=False).to_numpy()
    gt = gt.assign(busy=busy)
    pr_q = np.array([gt.loc[(gt.busy == b) & (gt.rent_today > 0), "flag"].mean() for b in range(N_BUSY)])
    pn_q = np.array([gt.loc[(gt.busy == b) & (gt.rent_today <= 0), "flag"].mean() for b in range(N_BUSY)])

    opp = gt[gt.x > 0].sort_values("day")
    days = np.sort(opp["day"].unique())
    shift_day = days[len(days) // 2]
    groups = {d: (g.x.to_numpy(), g.v.to_numpy(), g.gas.to_numpy(), g.busy.to_numpy()) for d, g in opp.groupby("day")}

    results = {}
    for ctl in CONTROLLERS:
        rng = np.random.default_rng(SEED)
        m = {"static m=1bp": 1.0, "static m=2bp": 2.0, "static m=5bp": 5.0}.get(ctl, M0_BPS)
        daily = []
        for d in days:
            xs, vs, gs, bq = groups[d]
            costs = ARB_COSTS_BPS * (cost_shift if d >= shift_day else 1.0) / 1e4
            kept = xs if ctl.startswith("today") else np.minimum(xs, m / 1e4)
            net = kept[:, None] * vs[:, None] - gs[:, None] - costs[None, :] * vs[:, None]
            srt = np.sort(net, axis=1)
            best, second = srt[:, -1], srt[:, -2]
            corrected = best >= 0
            correctable = xs * vs - gs - costs.min() * vs >= 0
            bid = np.where(corrected, np.maximum(second, 0.0), 0.0)
            lp = 0.0 if ctl.startswith("today") else float(np.where(corrected, np.maximum(xs - m / 1e4, 0) * vs, 0).sum())
            miss = correctable & ~corrected
            stale = float(miss.sum() / max(correctable.sum(), 1))
            comp = corrected & (bid > 0)
            n = len(xs)
            u = rng.random(n)
            if "pooled rates" in ctl:
                flag = corrected & np.where(comp, u < p_flag_rent, u < p_flag_norent)
            else:
                flag = corrected & np.where(comp, u < pr_q[bq], u < pn_q[bq])
            flagged = float(flag.sum() / max(corrected.sum(), 1))
            tau_d = float((pr_q[bq[corrected]].mean() + pn_q[bq[corrected]].mean()) / 2) if corrected.any() else tau
            frac = np.empty(n)
            frac[comp] = rng.choice(pool_rent, comp.sum())
            frac[corrected & ~comp] = rng.choice(pool_norent, (corrected & ~comp).sum())
            frac[~corrected] = rng.choice(pool_noncorr, (~corrected).sum())
            cw = corrected
            daily.append({
                "day": int(d), "m_bps": round(m, 4), "h1_bps": round(costs.min() * 1e4, 3),
                "lp_recapture": lp, "builder_payments": float(bid.sum()),
                "winner_margin": float((best[cw] - bid[cw]).sum()),
                "arb_kept_bps_vw": round(float((kept[cw] * vs[cw]).sum() / max(vs[cw].sum(), 1) * 1e4), 3),
                "uncorrected_share": round(stale, 4), "uncorrected_usd": float((xs * vs)[miss].sum()),
                "flagged_share": round(flagged, 4), "mean_block_fraction": round(float(frac.mean()), 4),
            })
            if ctl.startswith("thirds"):
                mf = frac.mean()
                m = m / 2 if mf < 1 / 3 else (m * 2 if mf >= 2 / 3 else m)
            elif ctl.startswith("staleness + flag, x2"):
                m = m * 2 if stale > S_STAR else (m / 2 if flagged > tau else m)
            elif ctl.startswith("staleness + flag, x1.25"):
                m = m * 1.25 if stale > S_STAR else (m * 0.8 if flagged > tau else m * 0.95)
            elif ctl.startswith("staleness 3-zone"):
                if stale > S_STAR:
                    m *= 2.0 if "asymmetric" in ctl else 1.25
                elif stale >= S_LOW:
                    pass
                else:
                    thr = tau_d if "normalised" in ctl else tau
                    decay = float(ctl.rsplit("decay ", 1)[1])
                    m *= 0.8 if ("+ flag" in ctl and flagged > thr) else decay
            m = float(np.clip(m, M_MIN_BPS, M_MAX_BPS))
        results[ctl] = daily

    def summarize(daily, lo, hi):
        rows = [r for r in daily if lo <= r["day"] < hi]
        tail = rows[-14:]
        return {
            "lp_recapture_m": round(sum(r["lp_recapture"] for r in rows) / 1e6, 2),
            "builder_payments_m": round(sum(r["builder_payments"] for r in rows) / 1e6, 2),
            "winner_margin_m": round(sum(r["winner_margin"] for r in rows) / 1e6, 2),
            "uncorrected_extraction_m": round(sum(r["uncorrected_usd"] for r in rows) / 1e6, 2),
            "mean_uncorrected_share": round(float(np.mean([r["uncorrected_share"] for r in rows])), 4),
            "days_over_s_star": int(sum(r["uncorrected_share"] > S_STAR for r in rows)),
            "m_bps_last14d_mean": round(float(np.mean([r["m_bps"] for r in tail])), 3),
            "m_bps_last14d_min_max": [round(min(r["m_bps"] for r in tail), 3), round(max(r["m_bps"] for r in tail), 3)],
            "arb_kept_bps_last14d": round(float(np.mean([r["arb_kept_bps_vw"] for r in tail])), 3),
        }

    first, last = int(days[0]), int(days[-1]) + 1
    summary = {ctl: {"window": summarize(d, first, last),
                     "before_cost_shift": summarize(d, first, int(shift_day)),
                     "after_cost_shift": summarize(d, int(shift_day), last)} for ctl, d in results.items()}
    vw_gas = float((opp.gas / opp.v).median() * 1e4)
    return {
        "assumptions": {
            "arb_costs_bps": ARB_COSTS_BPS.tolist(), "cost_shift_factor": cost_shift,
            "cost_shift_day": pd.to_datetime(int(shift_day) * 86400, unit="s").strftime("%Y-%m-%d"),
            "epoch": "1 UTC day", "m0_bps": M0_BPS, "s_star": S_STAR, "s_low": S_LOW, "flag_rule": f"tx_index <= {FLAG_IDX}",
            "flag_tau": round(tau, 4),
            "flag_rate_by_base_fee_quintile": {"rent": [round(x, 4) for x in pr_q], "no_rent": [round(x, 4) for x in pn_q]},
            "p_flag_contested": round(p_flag_rent, 4), "p_flag_uncontested": round(p_flag_norent, 4),
            "median_gas_over_notional_bps": round(vw_gas, 4),
            "cheapest_two_arbs_bps": {"before": ARB_COSTS_BPS[:2].tolist(),
                                      "after": (ARB_COSTS_BPS[:2] * cost_shift).tolist()},
        },
        "n_opportunities": len(opp), "n_days": len(days),
        "summary": summary,
        "daily": results,
    }


def plot(sim: dict, path) -> None:
    """Primary figure: m discovered by the proposed controller vs the thirds
    rule against the cheapest arb's cost, and the staleness each leaves."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.ticker
    import matplotlib.pyplot as plt

    surface, ink, ink2, grid, ref = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1", "#8a8983"
    series = [("staleness 3-zone + flag, asymmetric x2 up / x0.8 / decay 0.95", "#2a78d6", "Proposed controller"),
              ("thirds rule, x2 / /2", "#eb6834", "Thirds rule")]
    daily = sim["daily"]
    dates = [pd.to_datetime(r["day"] * 86400, unit="s") for r in daily[series[0][0]]]
    h1 = [r["h1_bps"] for r in daily[series[0][0]]]
    shift = pd.to_datetime(sim["assumptions"]["cost_shift_day"])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6.4), sharex=True, facecolor=surface,
                                   gridspec_kw={"height_ratios": [3, 2], "hspace": 0.28})
    for ax in (ax1, ax2):
        ax.set_facecolor(surface)
        ax.grid(True, axis="y", color=grid, linewidth=0.8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(grid)
        ax.tick_params(colors=ink2, labelsize=9)
        ax.axvline(shift, color=ref, linewidth=1, linestyle=":")

    ax1.step(dates, h1, where="post", color=ref, linewidth=1.5, linestyle="--")
    ax1.annotate("cheapest arb's cost", (dates[-1], h1[-1]), xytext=(6, -9), textcoords="offset points",
                 color=ink2, fontsize=9, va="center")
    for key, color, label in series:
        y = [r["m_bps"] for r in daily[key]]
        ax1.plot(dates, y, color=color, linewidth=2)
        ax1.annotate(label, (dates[-1], y[-1]), xytext=(6, 7 if y[-1] >= h1[-1] else 0), textcoords="offset points",
                     color=ink, fontsize=9, va="center")
    ax1.set_yscale("log")
    ax1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y:g}"))
    ax1.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax1.set_ylabel("allowance m (bp, log)", color=ink2, fontsize=9)
    ax1.set_title("Allowance m discovered by each controller", loc="left", color=ink, fontsize=11, pad=24)
    ax1.annotate(f"arb costs x{sim['assumptions']['cost_shift_factor']:g}", (shift, ax1.get_ylim()[1]), xytext=(4, -12), textcoords="offset points",
                 color=ink2, fontsize=8)

    for key, color, label in series:
        y = [r["uncorrected_share"] * 100 for r in daily[key]]
        ax2.plot(dates, y, color=color, linewidth=2, label=label)
    ax2.axhline(S_STAR * 100, color=ref, linewidth=1, linestyle="--")
    ax2.annotate("S* = 2%", (dates[len(dates) // 6], S_STAR * 100), xytext=(0, 6), textcoords="offset points", color=ink2, fontsize=8)
    ax2.set_ylabel("uncorrected (%)", color=ink2, fontsize=9)
    ax2.set_title("Correctable price gaps nobody corrected", loc="left", color=ink, fontsize=11)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    leg = ax1.legend([plt.Line2D([], [], color=c, linewidth=2) for _, c, _ in series] +
                     [plt.Line2D([], [], color=ref, linewidth=1.5, linestyle="--")],
                     [lab for _, _, lab in series] + ["Cheapest arb's cost"],
                     loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, frameon=False, fontsize=8, labelcolor=ink2)
    fig.subplots_adjust(right=0.8)
    fig.savefig(path, dpi=150, facecolor=surface)
    plt.close(fig)


def run() -> dict:
    df, L = prepare()
    sims = {name: simulate(df, f) for name, f in COST_SHIFTS.items()}
    out = {"L_s": L, "signals": signals(df), "cutoffs": cutoffs(df), "simulation": sims}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=2))
    plot(sims[PLOT_SCENARIO], OUT / "m_controller.png")
    return out


if __name__ == "__main__":
    res = run()
    print(json.dumps({"cutoffs": {k: v for k, v in res["cutoffs"].items() if k != "rules_by_youden_j"},
                      "top_rules": res["cutoffs"]["rules_by_youden_j"][:6],
                      "thirds": [r for r in res["cutoffs"]["rules_by_youden_j"] if "thirds" in r["rule"]],
                      "summary": {k: v["summary"] for k, v in res["simulation"].items()}}, indent=1))
