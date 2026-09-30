"""Study I — block-level comparison of arb payout rules.

Goal (user): the rule with the best overall LP outcome while the pool
stays rebalanced every block.

Model. Every block in the window (1.32M) in order:
  1. Arb phase (pool-first). Gap G = ln oracle − ln pool at block_ts + L.
     Each arb j (hedge cost h_j) picks the trade size maximizing its
     profit under the payout rule; the most profitable wins and pays the
     builder the runner-up's profit (second-price auction for the slot).
  2. Exogenous flow: the block's real non-arb swaps, replayed in order
     with real notional and direction; they move the pool and trade
     against whatever price the arb phase left.
Pool price moves linearly in ln price with depth D (USD per unit ln
price, per day, blocksim). Arb extraction on a trade of size V closing
edge a = |G| − f: E(V) = (a − V/2D)·V; the LP loses E and recaptures the
rule's charge. Exogenous LP markout: V·(f + s·(avg ln price − ln oracle)).

Payout rules (what the arb keeps; the LP recaptures E − kept):
  today        keeps E. No reconciliation.
  avg_margin   keeps min(x̄, m)·V, x̄ = average edge. The Study B/H form.
               Pays m per unit volume while the AVERAGE stays above m, so
               the arb is paid to keep trading past the oracle (overshoot)
               — tested, not assumed.
  job_cap      keeps min(x̄, m)·V_job, only for trading exactly to the band
               B (V_job = D(|G| − B)); any other size earns nothing.
  marginal_cap keeps ∫ min(marginal edge, m) over the trade. Rent is capped
               per unit along the price path, so the arb stops where the
               marginal edge equals its cost — the natural stopping point —
               and cannot be paid for overshoot. Computable ex-post: the
               reconciler knows pre/post pool price and the oracle.
  marginal_cap_gas  marginal_cap plus reimbursement of the trade's actual
               base-fee gas out of the extraction (the reconciler knows it
               from the receipt): a job reward = cost + small per-unit margin.
  + premium p  position premium (user proposal: m higher for top slots):
               every arb can buy the slot, so it is bid away to builders.

Parameter m: static grid, or a controller per UTC day:
  ctl        Study H design: raise x2 if staleness > S*, hold in [S_low,
             S*], else x0.8 if the slot was contested in > half of arb
             blocks, else blind decay x0.95. Decays into the cost cliff:
             when m falls below the cheapest arb's cost nobody arbs for a
             whole epoch.
  ctl_comp   competition-targeting: raise x2 if staleness > S*, lower x0.8
             only while the slot is contested (a second arb could also
             profit), otherwise HOLD. Settles where only the cheapest arb
             can do the job — between the cheapest and second-cheapest
             cost — and never approaches the cliff unless costs rise.
  ctl_fast   ctl_comp with asymmetric timing: staleness checked every
             RAISE_BLOCKS (~1h) and raised x2 immediately; lowering stays
             on the daily competition signal. Recovers from a cost shock
             within hours instead of days. Staleness = share of
CORRECTABLE blocks left uncorrected, where correctable means the cheapest
arb would profit with no charge at all — a fixed price band would demand
corrections no arb can afford when costs rise.

Rebalancing is reported two ways: uncorrected share of correctable blocks
(the binding constraint), and the share of blocks within fee + 1bp after
the arb phase. Runs that leave more correctable blocks uncorrected than
`today` does are FAILURES whatever their LP number: with the arb gone
the pool freezes, and replayed user flow trades against a price no real
router would route to, which inflates LP P&L artificially.

HONESTY (bind to writeup): linear depth; exogenous flow replayed with
fixed size/direction (no routing response to pool quality); one arb
action per block; assumed arb cost population; second-price slot
auction. Calibrated against the real pool under the `today` rule.
"""
from __future__ import annotations

import json
import math
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from .blocksim import CACHE, load
from .config import REPO_ROOT

OUT = REPO_ROOT / "results" / "study_i"
F = 0.0005
REB = F + 1e-4
B_JOB = F + 0.5e-4
ARB_COSTS_BPS = [0.3, 0.6, 1.0, 1.5, 2.5]
ARB_GAS_UNITS = 250_000
SHIFT_DAY = pd.Timestamp("2026-06-01").value // 10**9 // 86400
S_STAR, S_LOW, TAU_C = 0.02, 0.005, 0.5
RAISE_BLOCKS = 300              # ~1 hour

_DATA = {}


def _init():
    blocks, exo = load()
    _DATA["o"] = blocks["ln_o"].to_numpy()
    _DATA["D"] = blocks["D"].to_numpy()
    _DATA["gas"] = (blocks["base_fee_wei"].to_numpy() / 1e18 * ARB_GAS_UNITS * np.exp(blocks["ln_o"].to_numpy()))
    _DATA["day"] = blocks["day"].to_numpy()
    _DATA["bn"] = blocks["block_number"].to_numpy()
    idx = np.searchsorted(_DATA["bn"], exo["block_number"].to_numpy())
    _DATA["exo_start"] = np.searchsorted(idx, np.arange(len(blocks)), side="left")
    _DATA["exo_end"] = np.searchsorted(idx, np.arange(len(blocks)), side="right")
    _DATA["exo_s"] = exo["s"].to_numpy()
    _DATA["exo_v"] = exo["v"].to_numpy()


def arb_choice(rule: str, a: float, D: float, h: float, g: float, m: float, gap_abs: float):
    """(profit, V, kept) for one arb; V = 0 means no trade."""
    best = (0.0, 0.0, 0.0)
    if a <= 0:
        return best

    def ev(V, kept):
        return (kept - h * V - g, V, kept)

    if rule == "today":
        V = D * (a - h)
        if V > 0:
            best = max(best, ev(V, (a - V / (2 * D)) * V))
    elif rule == "avg_margin":
        for V in (2 * D * (a - m), D * (a - h)):
            if V > 0:
                x = a - V / (2 * D)
                best = max(best, ev(V, min(x, m) * V))
    elif rule == "job_cap":
        V = D * (gap_abs - B_JOB)
        if V > 0:
            x = a - V / (2 * D)
            best = max(best, ev(V, min(x, m) * V))
    elif rule in ("marginal_cap", "marginal_cap_gas"):
        if h < m or a <= m or rule == "marginal_cap_gas":
            V = D * (a - h)
            if V > 0:
                V1 = max(D * (a - m), 0.0)
                V1 = min(V1, V)
                kept = m * V1 + a * (V - V1) - (V * V - V1 * V1) / (2 * D)
                if rule == "marginal_cap_gas":
                    kept += min(g, (a - V / (2 * D)) * V - kept)
                best = max(best, ev(V, kept))
    return best


def run_one(args) -> dict:
    rule, param, scenario, premium = args
    if not _DATA:
        _init()
    o, Dd, gas, day = _DATA["o"], _DATA["D"], _DATA["gas"], _DATA["day"]
    es, ee, xs, xv = _DATA["exo_start"], _DATA["exo_end"], _DATA["exo_s"], _DATA["exo_v"]
    controlled = isinstance(param, str) and param.startswith("ctl")
    comp_only = param in ("ctl_comp", "ctl_fast")
    fast = param == "ctl_fast"
    w_corr = w_uncorr = w_n = 0
    s_star, s_low = (0.005, 0.001) if param == "ctl_tight" else (S_STAR, S_LOW)
    m = 5e-4 if controlled else (param / 1e4 if param is not None else 0.0)
    costs_base = [c / 1e4 for c in ARB_COSTS_BPS]
    shift = 4.0 if scenario == "costs_x4" else 1.0

    p = o[0]
    lp_arb = lp_exo = builder = margin = charge_tot = arb_vol = 0.0
    exo_gap_w = exo_vol = 0.0
    reb = n = overshoot = 0
    pre_gaps = []
    stale_run = persist2 = 0
    post_gaps = []
    daily = []
    d_cur = day[0]; d_stale = d_n = d_arb = d_cont = 0; d_m = m
    n_corr = n_uncorr = 0
    for i in range(len(o)):
        if day[i] != d_cur:
            st = d_stale / max(d_n, 1); ct = d_cont / max(d_arb, 1)
            daily.append((int(d_cur), round(d_m * 1e4, 4), round(st, 4), round(ct, 4)))
            if controlled:
                if st > s_star and not fast:
                    m *= 2.0
                elif st >= s_low:
                    pass
                elif ct > TAU_C:
                    m *= 0.8
                elif not comp_only:
                    m *= 0.95
                m = min(max(m, 0.02e-4), 50e-4)
            d_cur = day[i]; d_stale = d_n = d_arb = d_cont = 0; d_m = m
        oi = o[i]; D = Dd[i]
        G = oi - p; gab = abs(G); a = gab - F
        if es[i] < ee[i] and i % 10 == 0:
            pre_gaps.append(gab)
        if a > 0:
            costs = [c * (shift if day[i] >= SHIFT_DAY else 1.0) for c in costs_base]
            correctable = arb_choice("today", a, D, costs[0], gas[i], 0.0, gab)[0] > 0
            res = sorted((arb_choice(rule, a, D, h, gas[i], m, gab) for h in costs), reverse=True)
            w, r2 = res[0], res[1]
            traded = w[0] > 0 and w[1] > 0
            if correctable:
                n_corr += 1; d_n += 1; w_corr += 1
                if not traded:
                    n_uncorr += 1; d_stale += 1; w_uncorr += 1
            if traded:
                V, kept = w[1], w[2]
                E = (a - V / (2 * D)) * V
                bid = max(r2[0], 0.0) + premium / 1e4 * V
                lp_arb -= kept + premium / 1e4 * V
                charge_tot += E - kept
                builder += bid
                margin += w[0] - max(r2[0], 0.0)
                arb_vol += V
                p += math.copysign(V / D, G)
                if (oi - p) * G < 0 and abs(oi - p) > 0.5e-4:
                    overshoot += 1
                d_arb += 1
                if r2[0] > 0:
                    d_cont += 1
        if fast:
            w_n += 1
            if w_n >= RAISE_BLOCKS:
                if w_corr >= 20 and w_uncorr / w_corr > s_star:
                    m = min(m * 2.0, 50e-4)
                w_n = w_corr = w_uncorr = 0
        post = abs(oi - p)
        n += 1
        if post <= REB:
            reb += 1; stale_run = 0
        else:
            stale_run += 1
            if stale_run >= 2:
                persist2 += 1
        if i % 50 == 0:
            post_gaps.append(post)
        for k in range(es[i], ee[i]):
            s = xs[k]; V = xv[k]
            pav = p + s * V / (2 * D)
            lp_exo += V * (F + s * (pav - oi))
            exo_gap_w += V * abs(p - oi); exo_vol += V
            p += s * V / D
    pg = np.array(post_gaps) * 1e4
    pre = np.array(pre_gaps) * 1e4
    return {
        "rule": rule, "param": param, "scenario": scenario, "premium_bps": premium,
        "lp_net_m": round((lp_arb + lp_exo) / 1e6, 3),
        "lp_from_arbs_m": round(lp_arb / 1e6, 3), "lp_from_users_m": round(lp_exo / 1e6, 3),
        "lp_recapture_m": round(charge_tot / 1e6, 3),
        "builder_payments_m": round(builder / 1e6, 3), "arb_margin_m": round(margin / 1e6, 3),
        "arb_volume_b": round(arb_vol / 1e9, 3),
        "uncorrected_share_of_correctable": round(n_uncorr / max(n_corr, 1), 5),
        "correctable_blocks": n_corr,
        "rebalanced_block_share": round(reb / n, 5),
        "blocks_stale_2plus": persist2,
        "overshoot_blocks": overshoot,
        "pre_arb_gap_bps_active_blocks": {"p50": round(float(np.median(pre)), 2), "p90": round(float(np.percentile(pre, 90)), 2),
                                          "p99": round(float(np.percentile(pre, 99)), 2)},
        "post_arb_gap_bps": {"p50": round(float(np.median(pg)), 2), "p90": round(float(np.percentile(pg, 90)), 2),
                             "p99": round(float(np.percentile(pg, 99)), 2)},
        "user_pretrade_staleness_bps_vw": round(exo_gap_w / max(exo_vol, 1) * 1e4, 3),
        "m_bps_final": round(m * 1e4, 4),
        "daily": daily if controlled else None,
    }


def main(runs: list, workers: int = 8) -> list:
    with ProcessPoolExecutor(max_workers=workers, initializer=_init) as ex:
        return list(ex.map(run_one, runs))


GRID_M = [0.5, 1.0, 2.0, 5.0]
RULES = ["avg_margin", "job_cap", "marginal_cap", "marginal_cap_gas"]


def grid() -> list:
    runs = []
    for sc in ("stable", "costs_x4"):
        runs.append(("today", None, sc, 0.0))
        for r in RULES:
            runs += [(r, mm, sc, 0.0) for mm in GRID_M] + [(r, c, sc, 0.0) for c in ("ctl", "ctl_tight", "ctl_comp", "ctl_fast")]
        runs += [("marginal_cap_gas", "ctl_fast", sc, pr) for pr in (0.1, 0.5)]
    return runs


def run() -> dict:
    res = main(grid())
    calib = json.loads((CACHE / "calibration_inputs.json").read_text())
    today = {r["scenario"]: r for r in res if r["rule"] == "today"}
    for r in res:
        t = today[r["scenario"]]
        r["lp_net_vs_today_m"] = round(r["lp_net_m"] - t["lp_net_m"], 3)
        # binding constraint: no worse rebalancing than today (+0.5pp tolerance)
        r["keeps_rebalanced"] = bool(r["uncorrected_share_of_correctable"] <= t["uncorrected_share_of_correctable"] + 0.005)
    for sc in ("stable", "costs_x4"):
        ok = [r for r in res if r["scenario"] == sc and r["keeps_rebalanced"]]
        best = max(ok, key=lambda r: r["lp_net_m"])
        out_best = {k: best[k] for k in ("rule", "param", "premium_bps", "lp_net_m", "lp_net_vs_today_m")}
        today[sc]["_best"] = out_best
    # Robust choice: must keep the pool rebalanced in EVERY scenario; ranked
    # by worst-case LP gain vs today. A static m that only works when you
    # already know arb costs is hindsight, not a design.
    key = lambda r: (r["rule"], str(r["param"]), r["premium_bps"])
    by = {}
    for r in res:
        by.setdefault(key(r), []).append(r)
    robust = []
    for k, rs in by.items():
        if k[0] == "today" or not all(r["keeps_rebalanced"] for r in rs):
            continue
        robust.append({"rule": k[0], "param": k[1], "premium_bps": k[2],
                       "worst_lp_vs_today_m": float(min(r["lp_net_vs_today_m"] for r in rs)),
                       "by_scenario": {r["scenario"]: float(r["lp_net_vs_today_m"]) for r in rs}})
    robust.sort(key=lambda x: -x["worst_lp_vs_today_m"])
    out = {
        "robust_ranking": robust,
        "assumptions": {"pool_fee": F, "rebalanced_band_bps": REB * 1e4, "job_band_bps": B_JOB * 1e4,
                        "arb_costs_bps": ARB_COSTS_BPS, "costs_x4_from": "2026-06-01",
                        "controller": {"s_star": S_STAR, "s_low": S_LOW, "tau_contested": TAU_C}},
        "calibration": {"real": {k: calib[k] for k in ("real_lp_markout_m", "real_pre_first_swap_gap_bps",
                                                       "arb_like_volume_b", "depth_usd_per_bp_median")},
                        "simulated_today_stable": {k: today["stable"][k] for k in (
                            "lp_net_m", "lp_from_arbs_m", "lp_from_users_m", "arb_volume_b",
                            "pre_arb_gap_bps_active_blocks")}},
        "best_keeping_rebalanced": {sc: today[sc].pop("_best") for sc in ("stable", "costs_x4")},
        "runs": res,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    import time
    t = time.time()
    out = run()
    print(json.dumps(out["calibration"], indent=1))
    for r in out["runs"]:
        print(f"{r['scenario']:8} {r['rule']:12} m={str(r['param']):4} prem={r['premium_bps']:<3} "
              f"LP {r['lp_net_m']:+6.2f} (vs today {r['lp_net_vs_today_m']:+5.2f}) recap {r['lp_recapture_m']:5.2f} "
              f"builder {r['builder_payments_m']:5.2f} arbmargin {r['arb_margin_m']:4.2f} vol {r['arb_volume_b']:5.2f}B "
              f"uncorr {r['uncorrected_share_of_correctable']*100:5.2f}% {'OK ' if r['keeps_rebalanced'] else 'BAD'} reb {r['rebalanced_block_share']*100:6.2f}% overshoot {r['overshoot_blocks']:>6} "
              f"user_stale {r['user_pretrade_staleness_bps_vw']:5.2f} post_p90 {r['post_arb_gap_bps']['p90']:5.2f} m_end {r['m_bps_final']}")
    print("BEST per scenario (hindsight):", json.dumps(out["best_keeping_rebalanced"]))
    print("ROBUST RANKING (rebalanced in every scenario, worst-case LP gain vs today):")
    for x in out["robust_ranking"]:
        print("  ", x)
    print(f"{time.time()-t:.0f}s")
