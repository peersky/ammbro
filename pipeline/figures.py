"""Figures for paper.md — every figure is built from committed results/*.json
(and, for the score distributions, the canonical q and labels on disk).

    uv run python -m pipeline.figures        → figures/*.png

Palette: Okabe–Ito (colour-blind safe), assigned in fixed order; one y-axis
per panel; series identified by legend and direct labels, never colour alone.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from .config import REPO_ROOT

FIG = REPO_ROOT / "figures"
R = REPO_ROOT / "results"
C = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#56B4E9", "#CC79A7", "#000000"]   # Okabe–Ito
INK, MUTED = "#222222", "#777777"
plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 200, "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": "#e6e6e6", "grid.linewidth": 0.6,
    "legend.frameon": False, "lines.linewidth": 1.8, "font.family": "DejaVu Sans",
})
CHAINS = {"Ethereum mainnet": R, "Arbitrum One": R / "arbitrum"}


def j(path: Path) -> dict:
    return json.loads(path.read_text())


def save(fig, name: str) -> None:
    FIG.mkdir(exist_ok=True)
    fig.tight_layout()
    fig.savefig(FIG / f"{name}.png", bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


# ---------------------------------------------------------------- theory
def coverage_curve() -> None:
    x = np.linspace(0, 8, 400)                      # coverage ratio r / (ρ·V)
    fig, ax = plt.subplots(figsize=(4.6, 2.8))
    for i, (fmin, fmax) in enumerate([(1, 500), (1, 100), (5, 100)]):
        f = fmin + (fmax - fmin) * np.exp(-x)
        ax.plot(x, f, color=C[i], label=f"f_min = {fmin} bp, f_max = {fmax} bp")
    ax.set_yscale("log")
    ax.set_xlabel("coverage ratio  r / (ρ·V)")
    ax.set_ylabel("fee on covered volume (bp, log)")
    ax.set_title("Coverage curve  f = f_min + (f_max − f_min)·exp(−r/ρV)")
    ax.legend(loc="upper right")
    save(fig, "fig_coverage_curve")


def payout_rule() -> None:
    """Edge along the price path for a correction of a gap a; per-unit cap vs average-edge cap."""
    a, m, D = 6.0, 2.0, 1.0                          # bp gap beyond fee, allowance, depth (bp per unit)
    fig, ax1 = plt.subplots(figsize=(4.6, 2.9))
    u = np.linspace(0, a + 3, 400)
    edge = a - u / D
    ax1.plot(u, edge, color=INK, lw=1.2, label="marginal edge  a − u/D")
    kept = np.clip(np.minimum(edge, m), 0, None)
    ax1.fill_between(u, 0, kept, where=edge > 0, color=C[0], alpha=0.35, label="kept by the arbitrageur (≤ m per unit)")
    ax1.fill_between(u, m, edge, where=edge > m, color=C[1], alpha=0.45, label="recaptured for LPs")
    ax1.axhline(m, color=C[0], lw=1, ls="--")
    ax1.text(a + 2.6, m + 0.15, "m", color=C[0], ha="right")
    ax1.axvline(a * D, color=MUTED, lw=0.8)
    ax1.text(a * D + 0.1, 0.4, "pool reaches\nthe band", color=MUTED, fontsize=7.5)
    ax1.set_ylim(-0.2, a + 0.5)
    ax1.set_xlabel("corrected volume u"); ax1.set_ylabel("edge (bp)")
    ax1.set_title("Per-unit cap: rent bounded along the path")
    ax1.legend(loc="upper right", fontsize=7, bbox_to_anchor=(1.0, 1.0))
    ax1.set_xlim(0, a + 5)
    save(fig, "fig_payout_rule")
    fig, ax2 = plt.subplots(figsize=(4.6, 2.9))
    V = np.linspace(0.01, 2 * a * D, 400)
    per_unit = np.where(V <= (a - m) * D, m * V, m * (a - m) * D + (a * (V - (a - m) * D) - (V**2 - ((a - m) * D) ** 2) / (2 * D)))
    per_unit = np.minimum.accumulate(per_unit[::-1])[::-1] * 0 + np.maximum.accumulate(per_unit)   # kept is flat past the stop
    stop = a * D
    per_unit = np.where(V > stop, per_unit[np.searchsorted(V, stop)], per_unit)
    avg = np.minimum(a - V / (2 * D), m) * V
    ax2.plot(V, per_unit, color=C[0], label="per-unit cap: kept stops growing at the band")
    ax2.plot(V, avg, color=C[3], label="average-edge cap: kept grows past the oracle")
    ax2.axvline(stop, color=MUTED, lw=0.8)
    ax2.text(stop + 0.15, ax2.get_ylim()[1] * 0.95 if False else 15.5, "oracle reached", color=MUTED, fontsize=7.5, va="top")
    ax2.set_xlabel("trade size v"); ax2.set_ylabel("arbitrageur's kept rent")
    ax2.set_title("Why the average-edge cap invites overshoot")
    ax2.legend(loc="lower left", fontsize=7, bbox_to_anchor=(0.0, -0.02))
    save(fig, "fig_cap_comparison")


def latency_profile() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 2.7), sharey=False)
    for ax, (name, base) in zip(axes, CHAINS.items()):
        e = j(base / "study_e" / "metrics.json")
        off = np.array(e["decision_time_profile"]["offsets_s"])
        keep = (off >= -6) & (off <= 6)
        for i, (key, lab) in enumerate((("decision_time_profile", "last quote (biased late)"),
                                         ("decision_time_profile_next_print", "next quote (biased early)"))):
            c = np.array(e[key]["by_group"]["toxic_top3"]["curve_bps"])
            ax.plot(off[keep], c[keep], color=C[i], label=lab)
        L = e["decision_latency_L_s"]
        ax.axvline(L, color=INK, lw=1, ls="--")
        ax.text(L + 0.15, ax.get_ylim()[1] * 0.98, f"L = {L:g} s", va="top", fontsize=8)
        ax.set_title(name); ax.set_xlabel("offset from block timestamp (s)")
        ax.set_ylabel("median |residual| (bp)")
    axes[0].legend(loc="lower left", fontsize=7)
    save(fig, "fig_decision_latency")


def score_distributions() -> None:
    from .config import DATA_DIR
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 2.7), sharey=True)
    for ax, (name, sub) in zip(axes, (("Ethereum mainnet", ""), ("Arbitrum One", "arbitrum"))):
        on = DATA_DIR / "onchain" / sub if sub else DATA_DIR / "onchain"
        qc = pd.read_parquet(on / "scored_timing" / "eth_usdc_005" / "q_c.parquet", columns=["tx_hash", "log_index", "q_c_h0"])
        lab = pd.concat(pd.read_parquet(p, columns=["tx_hash", "log_index", "label"]) for p in sorted((on / "labels" / "eth_usdc_005").glob("*")))
        d = qc.merge(lab, on=["tx_hash", "log_index"])
        bins = np.linspace(-20, 20, 161)
        for i, (lbl, txt) in enumerate((("benign", "benign (routers)"), ("toxic", "toxic (top-of-block searchers)"))):
            q = d.loc[d.label == lbl, "q_c_h0"].dropna().to_numpy() * 1e4
            ax.hist(q, bins=bins, density=True, histtype="step", color=C[i], lw=1.6, label=txt)
        auc = j((R if not sub else R / "arbitrum") / "study_a" / "metrics.json")["auc_h0"]
        ax.axvline(0, color=MUTED, lw=0.8)
        ax.set_title(f"{name}  (AUC {auc:.3f})"); ax.set_xlabel("q_LP at h = 0 (bp; tails beyond ±20 not shown)")
    axes[0].set_ylabel("density"); axes[0].legend(loc="upper left", fontsize=7)
    save(fig, "fig_score_distributions")


def extraction_by_position() -> None:
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.8, 2.9), gridspec_kw={"width_ratios": [1, 1.25]})
    w = 0.38
    for i, (name, base) in enumerate(CHAINS.items()):
        rows = j(base / "supp1" / "metrics.json")["by_horizon"]["h0"]["by_raw_tx_index_all"]
        tot = sum(r["extraction_usd_m"] for r in rows)
        x = np.arange(len(rows))
        ax.bar(x + (i - 0.5) * w, [r["extraction_usd_m"] / tot * 100 for r in rows], w * 0.92, color=C[i], label=name)
    ax.set_xticks(np.arange(len(rows)), ["0", "1", "2", "3–9", "≥ 10"])
    ax.set_xlabel("user transaction position in the block"); ax.set_ylabel("share of extraction (%)")
    ax.set_title("(a) Extraction by position", loc="left", fontsize=9)
    ax.legend(fontsize=7, frameon=False)
    kap = np.log(2.0)
    bx.axvspan(-5, 0, color=C[1], alpha=0.12, lw=0)
    bx.axvspan(0, kap, color=C[2], alpha=0.18, lw=0)
    bx.axvspan(kap, 7, color=C[3], alpha=0.10, lw=0)
    top = 0
    for i, (name, base) in enumerate(CHAINS.items()):
        b = j(base / "study_i" / "block_index.json")
        e = np.array(b["z_bin_edges"]); h = np.array(b["z_hist"], float); h /= h.sum()
        bx.step((e[:-1] + e[1:]) / 2, h * 100, where="mid", color=C[i], lw=1.6, label=name)
        top = max(top, h.max() * 100)
    for x, t in ((-2.5, "late"), (kap / 2, "timely"), (3.8, "urgent")):
        bx.text(x, top * 1.05, t, ha="center", fontsize=7.5, color=INK)
    bx.set_xlim(-5, 7); bx.set_ylim(0, top * 1.18)
    bx.set_xlabel(r"block-position index $z_b$ (4), $\kappa = 2$"); bx.set_ylabel("share of blocks (%)")
    bx.set_title("(b) Corrections relative to retail", loc="left", fontsize=9)
    save(fig, "fig_extraction_by_position")


def recapture_frontier() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 2.8), sharey=True)
    forms = {"clip": C[4], "additive": C[1], "margin": C[0]}
    for ax, (name, base) in zip(axes, CHAINS.items()):
        b = j(base / "study_b" / "metrics.json")
        sw = b["by_horizon"]["h0"]["sweep_all"]
        base_s = b["by_horizon"]["h0"]["baseline"]["arb_survival"]
        for form, col in forms.items():
            pts = [(s["arb_survival"] / base_s, s["capture_fraction"] * 100) for s in sw if s["form"] == form]
            ax.scatter(*zip(*pts), s=14, color=col, alpha=0.75, label=f"{form} schedules", edgecolor="white", lw=0.4)
        obj = [s for s in sw if s["form"] == "margin" and s["m_bps"] == 2.0 and s["cap_bps"] == 500.0][0]
        ax.scatter([obj["arb_survival"] / base_s], [obj["capture_fraction"] * 100], s=70, facecolor="none", edgecolor=INK, lw=1.4)
        ax.annotate("chosen a priori\n(m = 2 bp, cap = f_max)", (obj["arb_survival"] / base_s, obj["capture_fraction"] * 100),
                    xytext=(0.36, 0.86), textcoords="axes fraction", fontsize=7.5, arrowprops=dict(arrowstyle="-", color=INK, lw=0.7))
        ax.set_title(name); ax.set_xlabel("profitable arbitrage preserved (× today)")
    axes[0].set_ylabel("extraction recaptured (%)")
    axes[0].legend(loc="lower left", fontsize=7)
    save(fig, "fig_recapture_frontier")


def controller_paths() -> None:
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.1), sharey=True)
    styles = [("no signal", "decay without a signal", C[3]), ("urgency by position", "urgency by position", C[0]),
              ("blind decay", "decay without a signal", C[3]), ("K_d >= 4", r"$K_d \geq 4$", C[0])]
    for ax, (title, base) in zip(axes, (("(a) Ethereum mainnet", R), ("(b) Arbitrum One", R / "arbitrum"))):
        paths = j(base / "study_i" / "paths.json")["paths"]
        for key, lab, col in styles:
            if key in paths:
                d = np.array(paths[key], dtype=float)
                ax.plot(pd.to_datetime(d[:, 0] * 86400, unit="s"), d[:, 1], color=col, lw=1.4, label=lab)
        ax.axvline(pd.Timestamp("2026-06-01"), color=INK, lw=0.8, ls="--")
        ax.set_title(title, loc="left", fontsize=9)
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(FixedLocator([0.3, 0.5, 1, 2, 5]))
        ax.yaxis.set_minor_locator(NullLocator())
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=7, frameon=False)
    axes[0].set_ylabel("job allowance m (bp, log)")
    save(fig, "fig_controller_paths")


def oracle_error() -> None:
    v = {(r["variant"], r["eps_bps"]): r for r in j(R / "study_j" / "metrics.json")["variants"]}
    eps = [0.0, 1.0, 2.0, 4.0]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.4, 2.7))
    for i, var in enumerate(("noise 2bp/block", "bias +1bp", "bias -3bp", "delay 1s")):
        ax1.plot(eps, [v[(var, e)]["overcharge_share_of_charged"] * 100 for e in eps], marker="o", ms=3.5, color=C[i], label=var)
        ax2.plot(eps, [v[(var, e)]["capture_fraction"] * 100 for e in eps], marker="o", ms=3.5, color=C[i], label=var)
    ax2.plot(eps, [v[("truth (canonical)", e)]["capture_fraction"] * 100 for e in eps], color=INK, lw=1, ls="--", label="exact oracle")
    ax1.set_xlabel("tolerance ε (bp)"); ax1.set_ylabel("unjustified share of charges (%)")
    ax1.set_title("(a) error removed by tolerance"); ax1.legend(fontsize=7)
    ax2.set_xlabel("tolerance ε (bp)"); ax2.set_ylabel("extraction recaptured (%)")
    ax2.set_title("(b) recapture given up"); ax2.legend(fontsize=7)
    save(fig, "fig_oracle_error")


def settlement_cost() -> None:
    labels = {"keeper on-chain, per block (Data Streams report per block)": "keeper, every block",
              "keeper on-chain, hourly (one signed price batch)": "keeper, hourly, batch-signed prices",
              "keeper zk, hourly (one Groth16 proof)": "keeper, hourly, succinct proof",
              "every account self-settles hourly (on-chain)": "every account self-settles hourly"}
    fig, ax = plt.subplots(figsize=(6.2, 2.7))
    y = np.arange(len(labels))
    w = 0.38
    for i, (name, base) in enumerate(CHAINS.items()):
        d = j(base / "study_g" / "measured.json")["settlement_budget"]["designs"]
        vals = [d[k]["ratio_to_execution"] for k in labels]
        ax.barh(y + (i - 0.5) * w, vals, w * 0.92, color=C[i], label=name)
        for yy, vv in zip(y + (i - 0.5) * w, vals):
            ax.text(vv + 0.01, yy, f"{vv:.2f}", va="center", fontsize=7, color=INK)
    ax.axvline(1, color=INK, lw=0.8, ls="--")
    ax.text(0.98, 3.0, "bound:\nsettlement ≤ execution", ha="right", va="center", fontsize=7.5)
    ax.set_yticks(y, list(labels.values())); ax.invert_yaxis()
    ax.set_xlabel("settlement gas ÷ execution gas of the settled swaps"); ax.set_xlim(0, 1.05)
    ax.set_title("Measured cost of settlement, including the hook on every swap")
    ax.legend(loc="center right", fontsize=7.5)
    save(fig, "fig_settlement_cost")


def gas_tank() -> None:
    g = j(R / "study_k" / "gas_tank.json")
    ga = j(R / "arbitrum" / "study_k" / "gas_tank.json")
    cases = [("1h/real", "hourly"), ("24h/real", "daily"), ("24h/flex24h", "daily, keeper picks block")]
    G = lambda d, c: d[f"zk/{c}"]["uniform_G_per_swap"]["G_min_seeded_1day"]
    series = [("ETH/USDC pool alone ($19.6 B)", lambda c: G(g["pools"]["eth_usdc_005"], c), C[0]),
              ("PEPE/WETH pool alone ($13 M)", lambda c: G(g["pools"]["pepe_weth_030"], c), C[3]),
              ("shared tank, 7 mainnet pools", lambda c: G(g["shared"], c), C[1]),
              ("Arbitrum ETH/USDC", lambda c: G(ga["pools"]["eth_usdc_005"], c), C[2])]
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    x = np.arange(len(cases)); w = 0.2
    for i, (lab, f, col) in enumerate(series):
        ax.bar(x + (i - 1.5) * w, [f(c) for c, _ in cases], w * 0.92, color=col, label=lab)
    ax.set_yscale("log"); ax.set_ylabel("gas withheld per swap (log)")
    ax.set_xticks(x, [c[1] for c in cases])
    ax.set_title("Gas-tank contribution that keeps settlement solvent (proven settlement)")
    ax.legend(fontsize=7, ncol=2)
    save(fig, "fig_gas_tank")


def stake_and_shocks() -> None:
    chains = [("Ethereum mainnet", R / "study_i" / "stake.json"), ("Arbitrum One", R / "arbitrum" / "study_i" / "stake.json")]
    chains = [(n, p) for n, p in chains if p.exists()]
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.1))
    ax = axes[0]
    for ci, (name, path) in enumerate(chains):
        d = j(path)
        for alloc, ls in (("pooled", "-"), ("equal", "--")):
            pts = sorted((r["stake_mult"], r["uncorrected_hours"]) for r in d["rows"]
                         if r["scenario"] == "stable" and r["alloc"] == alloc and not r["ramp_days"] and r["stake_mult"])
            base = next(r["uncorrected_hours"] for r in d["rows"] if r["scenario"] == "stable" and r["stake_mult"] is None
                        and r["unstaked_fmax_bps"] is None)
            ax.plot([x for x, _ in pts], [max(y, 0.1) for _, y in pts], ls, color=C[ci], marker="o", ms=3,
                    label=f"{name}, {'pooled' if alloc == 'pooled' else 'held separately'}")
            if alloc == "pooled":
                ax.axhline(max(base, 0.1), color=C[ci], lw=0.8, ls=":", label=f"{name}, fully covered")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("arbitrageurs' stake (multiples of ρ × mean daily arbitrage volume)")
    ax.set_ylabel("uncorrected hours in six months")
    ax.set_title("(a) stake needed to keep the pool corrected")
    ax.legend(fontsize=6, loc="upper right")
    ax = axes[1]
    vols = [("stable", "shocks ×1"), ("vol_x2", "shocks ×2"), ("vol_x4", "shocks ×4")]
    for ci, (name, path) in enumerate(chains):
        d = j(path)
        for vi, (sc, lab) in enumerate(vols):
            ref = next(r["lp_gain_vs_today_m"] for r in d["rows"] if r["scenario"] == sc and r["stake_mult"] is None
                       and r["unstaked_fmax_bps"] is None)
            pts = sorted((r["unstaked_fmax_bps"], 100 * (ref - r["lp_gain_vs_today_m"]) / ref) for r in d["rows"]
                         if r["scenario"] == sc and r["stake_mult"] is None and r["unstaked_fmax_bps"])
            ax.plot([x for x, _ in pts], [y for _, y in pts], ["-", "--", ":"][vi], color=C[ci], marker="o", ms=3,
                    label=f"{name}, {lab}")
    ax.set_xscale("log"); ax.set_ylim(bottom=0)
    ax.set_xlabel("$f_{max}$ (bp)"); ax.set_ylabel("LP gain lost to fresh accounts (%)")
    ax.set_title("(b) leakage to unstaked accounts")
    ax.legend(fontsize=6.5)
    save(fig, "fig_stake_shocks")


def urgency_block_space() -> None:
    lv = np.round(np.linspace(0.01, 0.99, 99), 2)
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 4.6), sharex=True)
    for ax, (title, base) in zip(axes, (("(a) Ethereum mainnet", R), ("(b) Arbitrum One", R / "arbitrum"))):
        b = j(base / "study_i" / "block_index.json")
        edges = np.array(b["pos_bin_edges"]); mid = np.sqrt(edges[:-1] * edges[1:])
        series = ((b["pos_hist_retail"], b["pos_quantiles_retail"], C[0], "earliest retail (non-correcting) swap", -0.10),
                  (b["pos_hist_correction"], b["pos_quantiles_correction"], C[3], "first correcting swap", -0.20))
        top = max(max(np.array(h) / sum(h)) for h, *_ in series)
        for h, qq, col, lab, yb in series:
            d = np.array(h) / sum(h)
            ax.fill_between(mid, d, step="mid", color=col, alpha=0.18, lw=0)
            ax.step(mid, d, where="mid", color=col, lw=1.6, label=lab)
            q25, q50, q75 = (float(np.interp(p_, lv, qq)) for p_ in (0.25, 0.5, 0.75))
            ax.plot([q25, q75], [yb * top] * 2, color=col, lw=4, solid_capstyle="butt")
            ax.plot([q50], [yb * top], marker="|", ms=12, mew=2, color=INK)
        ax.set_xscale("log"); ax.set_xlim(edges[0], 1); ax.set_ylim(-0.27 * top, 1.12 * top)
        ax.axhline(0, color=INK, lw=0.6)
        ax.set_title(title, loc="left", fontsize=9); ax.set_ylabel("share of blocks")
    axes[0].legend(fontsize=7.5, loc="upper left", frameon=False)
    axes[-1].set_xlabel("position in block: share of the block's transactions ordered before the swap (log)")
    save(fig, "fig_urgency_block_space")


def value_split() -> None:
    bars = []
    for chain, base in (("Mainnet", R), ("Arbitrum", R / "arbitrum")):
        row = next(r for r in j(base / "study_i" / "headline.json")["rows"] if r["scenario"] == "stable")
        for key, lab in (("today", "today"), ("bro_amm", "BRO-AMM")):
            x = row[key]
            loss = -x["lp_from_arbs_m"]
            parts = [x["lp_recapture_m"], x["builder_payments_m"], x["arb_margin_m"],
                     loss - x["builder_payments_m"] - x["arb_margin_m"]]
            bars.append((f"{chain}, {lab}", parts, x["lp_net_m"]))
    segs = [("recaptured for LPs", C[0]), ("payments for position", C[3]),
            ("arbitrageurs' margin", C[1]), ("arbitrageurs' costs (hedge, gas)", MUTED)]
    fig, ax = plt.subplots(figsize=(7.4, 2.6))
    for k, (lab, parts, net) in enumerate(bars):
        y = len(bars) - 1 - k + (0.25 if k < 2 else 0)
        tot = sum(parts); left = 0.0
        for (name, col), v in zip(segs, parts):
            ax.barh(y, v / tot * 100, left=left, height=0.62, color=col, edgecolor="white", lw=1.5,
                    label=name if k == 1 else None)
            left += v / tot * 100
        sg = "\u2212" if net < 0 else "+"
        ax.text(101.5, y, f"\\${tot:.2f} M; LPs' net {sg}\\${abs(net):.2f} M", va="center", fontsize=7.5, color=INK)
    ax.set_yticks([len(bars) - 1 - k + (0.25 if k < 2 else 0) for k in range(len(bars))])
    ax.set_yticklabels([b[0] for b in bars], fontsize=8)
    ax.set_xlim(0, 100); ax.set_xlabel("share of the value taken by arbitrage (%)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=4, fontsize=7, frameon=False)
    save(fig, "fig_value_split")


def main() -> None:
    for f in (coverage_curve, payout_rule, latency_profile, score_distributions, extraction_by_position,
              recapture_frontier, controller_paths, oracle_error, settlement_cost, gas_tank, stake_and_shocks, urgency_block_space, value_split):
        f()


if __name__ == "__main__":
    main()
