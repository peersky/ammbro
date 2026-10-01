"""Study C, part 1 — collateral for the stake-backed charge.

The feasibility audit (spec) established that the reconciliation charge
— extraction beyond the job allowance — is only collectable from stake
the trader locked BEFORE trading (P§4.5 in-flight tranche). Questions:

  1. How large is the charge per trade relative to trade size? A tranche
     of ρ·V per trade covers it only if charge/V <= ρ; anything above is
     uncollected (leak).
  2. How much capital does ρ lock? Each $ of arb volume locks ρ$ until its
     settlement window τ closes (one block, an hour, an epoch, a week).
  3. What does that capital cost the arb (ρ·r·τ per $ traded, r = cost of
     capital), and does adding that cost to every arb's cost change the
     Study I result?

Trades come from the Study I simulation of the chosen design
(gas-reimbursed marginal cap + feasible controller), stable and ×4 costs.

Findings drive two alternatives to a flat per-trade ρ, both feasible:
  impact-scaled tranche  ρ_trade = k·Δp + c, Δp = the swap's own price move
                         (afterSwap sees pre/post price; no oracle needed).
                         An arb closing a gap moves the price by ~ the gap and
                         earns ~Δp/2 on average along the path, so this tracks
                         the charge. Big benign trades lock collateral too
                         (released at reconciliation, never charged).
  last-oracle tranche    ρ_trade = max(|path midpoint − last posted oracle| − f, 0)
                         + buffer: the gap to the oracle price the previous
                         reconciliation already stored on-chain (12s+ old,
                         readable at execution). Splitting a big gap into small
                         trades does not shrink it — each piece still sees the
                         gap. (The impact-scaled tranche covers 100% in this
                         simulation only because simulated arbs correct in one
                         trade; it is gameable by splitting and is rejected.)
  account bond           a standing per-trader collateral account that
                         charges are debited from, sized to the trader's worst
                         epoch rather than its worst trade.

Size-based lock schedules (author proposal: lock grows exponentially with
swap size, tunable) are tested against an adversarial arb that splits each
correction into 10 pieces in one block, and costed on real user swaps.
Any lock driven by a quantity the trader controls (size, count, accounts)
is gameable; the charge is driven by the gap, which the market sets.

Block-speed lock (author proposal): lock rate = c + k x the pool's
cumulative price move so far in the block, so many small trades in one
block grow the lock. Tested per piece and with an account's in-flight
locks pooled, for a correction split x10 in one block and across 10
blocks (the in-block move resets each block).

HONESTY: r is assumed (5%/yr); the arb population is Study I's assumed
one; leak assumes a uniform ρ per trade (the hook cannot see the oracle at
execution, so it cannot size the tranche to the trade's actual edge).
"""
from __future__ import annotations

import json

import numpy as np

from .config import REPO_ROOT, RESULTS_DIR
from .blocksim import load
from .study_i import run_one

OUT = RESULTS_DIR / "study_c"
RHO_BPS = [2, 5, 10, 20, 50, 100]
R_ANNUAL = 0.05
WINDOWS_S = {"1 block": 12, "1 hour": 3600, "1 day (epoch)": 86400, "7 days": 7 * 86400}
DESIGN = ("marginal_cap_gas", "ctl_feasible")


def analyse(scenario: str) -> dict:
    r = run_one((*DESIGN, scenario, 0.0, "open", True))
    t = r["_trades"]
    V, E, kept = t[:, 2], t[:, 3], t[:, 4]
    charge = np.maximum(E - kept, 0.0)
    cbp = charge / V * 1e4
    n_days = len(np.unique(t[:, 1]))
    vol_day = V.sum() / n_days
    q = lambda x: round(float(np.percentile(cbp, x)), 2)
    rows = []
    for rho in RHO_BPS:
        cover = np.minimum(charge, rho / 1e4 * V)
        rows.append({
            "rho_bps": rho,
            "charge_collected_share": round(float(cover.sum() / charge.sum()), 4),
            "leak_m": round(float((charge - cover).sum()) / 1e6, 3),
            "trades_fully_covered": round(float((charge <= rho / 1e4 * V).mean()), 4),
            "locked_capital_usd_by_window": {w: round(rho / 1e4 * vol_day * s / 86400, 0) for w, s in WINDOWS_S.items()},
            "capital_cost_bps_per_dollar_traded": {w: round(rho / 1e4 * R_ANNUAL * s / (365 * 86400) * 1e4, 5)
                                                   for w, s in WINDOWS_S.items()},
        })
    # impact-scaled tranche: needs each trade's own price move dp = V / D
    D = load()[0]["D"].to_numpy()[t[:, 0].astype(int)]
    dp_bps = V / D * 1e4
    impact = []
    for k in (0.5, 0.75, 1.0):
        for c in (0.0, 1.0, 2.0):
            tranche = (k * dp_bps + c) / 1e4 * V
            cover = np.minimum(charge, tranche)
            impact.append({"k": k, "c_bps": c,
                           "charge_collected_share": round(float(cover.sum() / charge.sum()), 4),
                           "leak_m": round(float((charge - cover).sum()) / 1e6, 3),
                           "trades_fully_covered": round(float((charge <= tranche).mean()), 4),
                           "mean_tranche_bps": round(float(tranche.sum() / V.sum() * 1e4), 2),
                           "locked_capital_usd_1day": round(float(tranche.sum() / n_days), 0)})
    # last-oracle tranche: gap of the trade's path midpoint to an oracle k blocks old
    o_all = load()[0]["ln_o"].to_numpy()
    idx = t[:, 0].astype(int)
    p_post, G = t[:, 7], t[:, 8]
    p_mid = p_post - np.sign(G) * dp_bps / 1e4 / 2
    F = 0.0005
    last_oracle = []
    for lag in (1, 5, 25):
        o_lag = o_all[np.maximum(idx - lag, 0)]
        edge_lag_bps = np.maximum(np.abs(p_mid - o_lag) - F, 0.0) * 1e4
        for buf in (1.0, 3.0, 5.0):
            tranche = (edge_lag_bps + buf) / 1e4 * V
            cover = np.minimum(charge, tranche)
            last_oracle.append({"oracle_lag_blocks": lag, "buffer_bps": buf,
                                "charge_collected_share": round(float(cover.sum() / charge.sum()), 4),
                                "leak_m": round(float((charge - cover).sum()) / 1e6, 3),
                                "trades_fully_covered": round(float((charge <= tranche).mean()), 4),
                                "mean_tranche_bps": round(float(tranche.sum() / V.sum() * 1e4), 2)})
    # size-based schedules vs a 10-way splitting attack, and their cost to users
    a_edge = np.abs(G) - F
    m_t = t[:, 6]
    blocks, exo = load()
    Dblk = blocks["D"].to_numpy()
    ev = exo["v"].to_numpy()
    eD = Dblk[np.searchsorted(blocks["block_number"].to_numpy(), exo["block_number"].to_numpy())]
    schedules = {
        "flat 20bp": lambda v, d: np.full_like(v, 20e-4),
        "exp 2bp*e^(V/$100k), cap 5%": lambda v, d: np.minimum(2e-4 * np.exp(v / 1e5), 0.05),
        "exp 2bp*e^(V/$250k), cap 5%": lambda v, d: np.minimum(2e-4 * np.exp(v / 2.5e5), 0.05),
        "exp 2bp*e^(V/$500k), cap 5%": lambda v, d: np.minimum(2e-4 * np.exp(v / 5e5), 0.05),
        "impact 2bp + 0.5*V/D": lambda v, d: 2e-4 + 0.5 * v / d,
    }
    size_rows = []
    for name, sch in schedules.items():
        coll = float(np.minimum(charge, sch(V, D) * V).sum() / charge.sum())
        c10 = l10 = 0.0
        for k in range(1, 11):
            vk = V / 10
            ch_k = np.maximum(a_edge - (k - 0.5) * V / (10 * D) - m_t, 0.0) * vk
            lk = sch(vk, D) * vk
            c10 += np.minimum(ch_k, lk).sum(); l10 += np.maximum(ch_k - lk, 0.0).sum()
        size_rows.append({"schedule": name, "collected_share": round(coll, 4),
                          "collected_share_split_x10": round(float(c10 / (c10 + l10)), 4),
                          "user_lock_per_day_usd": round(float((sch(ev, eD) * ev).sum() / n_days), 0),
                          "lock_on_1m_user_swap_usd": round(float(sch(np.array([1e6]), np.array([np.median(Dblk)]))[0] * 1e6), 0)})
    # block-speed lock: c + k * block-cumulative move; split x10 same block vs across blocks
    dP = V / D
    speed_rows = []
    for kc in (0.5, 1.0, 2.0):
        lr = lambda move: 2e-4 + kc * move
        ch1 = np.maximum(a_edge - dP / 2 - m_t, 0.0) * V
        row = {"k": kc, "honest_one_trade": round(float(np.minimum(ch1, lr(dP) * V).sum() / ch1.sum()), 4)}
        for label, same_block in (("same_block", True), ("across_blocks", False)):
            tc = np.zeros_like(V); tl = np.zeros_like(V); pp = tot = 0.0
            for k in range(1, 11):
                vk = V / 10
                ch = np.maximum(a_edge - (k - 0.5) * dP / 10 - m_t, 0.0) * vk
                lk = lr(k * dP / 10 if same_block else dP / 10) * vk
                pp += np.minimum(ch, lk).sum(); tot += ch.sum(); tc += ch; tl += lk
            row[f"split_x10_{label}_per_piece"] = round(float(pp / tot), 4)
            row[f"split_x10_{label}_pooled"] = round(float(np.minimum(tc, tl).sum() / tc.sum()), 4)
        row["lock_on_1m_user_swap_usd"] = round(float(lr(1e6 / np.median(Dblk)) * 1e6), 0)
        speed_rows.append(row)
    # account bond: charges per winning arb (cost type) per epoch
    arb_day = {}
    for h, d, c in zip(t[:, 5], t[:, 1], charge):
        arb_day[(round(h * 1e4, 3), int(d))] = arb_day.get((round(h * 1e4, 3), int(d)), 0.0) + c
    by_arb = {}
    for (h, d), c in arb_day.items():
        by_arb.setdefault(h, []).append(c)
    bond = {f"arb cost {h}bp": {"days_active": len(v), "charge_m": round(sum(v) / 1e6, 3),
                                "median_day_usd": round(float(np.median(v)), 0),
                                "p99_day_usd": round(float(np.percentile(v, 99)), 0),
                                "max_day_usd": round(float(max(v)), 0)}
            for h, v in sorted(by_arb.items())}
    return {
        "scenario": scenario, "n_trades": len(t),
        "impact_scaled_tranche_rejected_gameable": impact,
        "last_oracle_tranche": last_oracle,
        "size_based_schedules_vs_splitting": size_rows,
        "block_speed_lock": speed_rows,
        "account_bond_by_arb": bond, "arb_volume_b": round(float(V.sum()) / 1e9, 3),
        "arb_volume_per_day_m": round(vol_day / 1e6, 2),
        "total_charge_m": round(float(charge.sum()) / 1e6, 3),
        "lp_net_m": r["lp_net_m"],
        "charge_per_trade_bps": {"p50": q(50), "p90": q(90), "p99": q(99), "p99.9": q(99.9), "max": round(float(cbp.max()), 1)},
        "share_of_charge_from_trades_above_bps": {f">{b}bp": round(float(charge[cbp > b].sum() / charge.sum()), 4) for b in (5, 10, 20, 50)},
        "by_rho": rows,
    }


def feedback(scenario: str, rho_bps: float, window: str) -> dict:
    """Add the stake's capital cost to every arb's cost and rerun."""
    extra = rho_bps / 1e4 * R_ANNUAL * WINDOWS_S[window] / (365 * 86400) * 1e4
    base = run_one((*DESIGN, scenario, 0.0, "open", False, 0.0))
    withc = run_one((*DESIGN, scenario, 0.0, "open", False, extra))
    pick = lambda r: {k: r[k] for k in ("lp_net_m", "builder_payments_m", "uncorrected_share_of_correctable",
                                        "rebalanced_block_share", "m_bps_final")}
    return {"scenario": scenario, "rho_bps": rho_bps, "window": window, "extra_cost_bps": round(extra, 5),
            "without": pick(base), "with": pick(withc)}


def run() -> dict:
    res = {"assumptions": {"design": "marginal_cap_gas + ctl_feasible (Study I)", "cost_of_capital_annual": R_ANNUAL},
           "by_scenario": {sc: analyse(sc) for sc in ("stable", "costs_x4")}}
    res["feedback"] = [feedback(sc, rho, w) for sc in ("stable", "costs_x4")
                       for rho, w in ((20, "1 day (epoch)"), (100, "7 days"))]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "collateral.json").write_text(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    out = run()
    for sc, a in out["by_scenario"].items():
        print(f"== {sc}: trades {a['n_trades']:,}, arb vol ${a['arb_volume_b']}B (${a['arb_volume_per_day_m']}M/day), charge ${a['total_charge_m']}M, LP {a['lp_net_m']}")
        print("   charge per trade (bp of notional):", a["charge_per_trade_bps"])
        print("   share of total charge from trades above:", a["share_of_charge_from_trades_above_bps"])
        for r in a["last_oracle_tranche"]:
            print(f"   last-oracle tranche lag {r['oracle_lag_blocks']:>2} blk buf {r['buffer_bps']}bp: collected {r['charge_collected_share']*100:6.2f}%  leak ${r['leak_m']}M  covered {r['trades_fully_covered']*100:6.2f}%  mean tranche {r['mean_tranche_bps']}bp")
        for r in a["impact_scaled_tranche_rejected_gameable"][:0]:
            print(f"   impact tranche k={r['k']} c={r['c_bps']}bp: collected {r['charge_collected_share']*100:6.2f}%  leak ${r['leak_m']}M  covered {r['trades_fully_covered']*100:6.2f}%  mean tranche {r['mean_tranche_bps']}bp  locked/day ${r['locked_capital_usd_1day']:,.0f}")
        for k, v in a["account_bond_by_arb"].items():
            print(f"   bond {k}: {v}")
        for r in a["by_rho"][:0]:
            print(f"   rho {r['rho_bps']:>3}bp: collected {r['charge_collected_share']*100:6.2f}%  leak ${r['leak_m']}M  covered trades {r['trades_fully_covered']*100:6.2f}%  "
                  f"locked $ by window {r['locked_capital_usd_by_window']}  cost bp/$ {r['capital_cost_bps_per_dollar_traded']}")
    for f in out["feedback"]:
        print("FEEDBACK", json.dumps(f))
