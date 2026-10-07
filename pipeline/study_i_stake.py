"""Study I follow-up: stake-limited arbitrage and shock volatility (paper §4.4, §4.8, §5.4).

A. Stake capacity. The arbitrage market holds REP worth K; a staked arbitrageur
   pays the coverage-curve fee F + (f_max − F)·exp(−r/(ρ·v)) on its UTC-day volume
   v so far (ρ = 5 bp, f_max = 500 bp, F = the pool fee as floor); fresh unstaked
   accounts at f_max remain available. K is set as a multiple s of ρ times the
   chain's mean daily arbitrage volume, s ∈ {0, 10, 25, 50, 100}, held either in
   equal shares by the arbitrageurs or pooled by one staker (an intermediary);
   plus a launch in which pooled stake grows from 0 to s = 50 over 30 days.
B. Shock volatility. The oracle's deviations from its start are scaled by 1, 2
   and 4; fresh-account leakage is measured for f_max ∈ {100 … 2000} bp, with
   staked arbitrageurs fully covered.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_stake   → results/[<chain>/]study_i/stake.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

S_MULT = [0, 10, 25, 50, 100]
FMAX_STRESS = [100e-4, 200e-4, 500e-4, 1000e-4, 2000e-4]
VOLS = ["stable", "vol_x2", "vol_x4"]


def ctl() -> str:
    return "ctl_div" if ACTIVE.ordering == "fcfs" else "ctl_feasible"


def base(sc):
    return ("marginal_cap", ctl(), sc, 0.0, "open", False, 0.0)


def main() -> dict:
    c = ctl()
    ref = I.main([base("stable") + ({"stale_rule": "outcome"},)], workers=1)[0]
    vbar = ref["arb_volume_b"] * 1e9 / 184                       # mean daily arbitrage volume
    unit = I.RHO * vbar
    runs = []
    for sc in I.SCENARIOS:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {}))
        runs.append(base(sc) + ({"stale_rule": "outcome"},))
        for sm in S_MULT:
            for alloc in ("equal", "pooled"):
                runs.append(base(sc) + ({"stake": sm * unit, "alloc": alloc, "fmax": 500e-4},))
        runs.append(base(sc) + ({"stake": 50 * unit, "alloc": "pooled", "fmax": 500e-4, "stake_ramp_days": 30},))
    for sc in VOLS[1:]:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {}))
    for sc in VOLS:
        runs.append(base(sc) + ({"stale_rule": "outcome"},))
        for f in FMAX_STRESS:
            runs.append(base(sc) + ({"stale_rule": "outcome", "unstaked": (f, 0.0)},))
    res = I.main(runs)
    today = {r["scenario"]: r for r in res if r["rule"] == "today"}
    rows = []
    for r in res:
        if r["rule"] == "today":
            continue
        t = today[r["scenario"]]
        st = r["stake"]
        rows.append({
            "scenario": r["scenario"], "controller": c,
            "stake_mult": None if st["usd"] is None else round(st["usd"] / unit, 1),
            "stake_usd_m": None if st["usd"] is None else round(st["usd"] / 1e6, 3),
            "alloc": st["alloc"] if st["usd"] is not None else None, "ramp_days": st["ramp_days"],
            "unstaked_fmax_bps": None if r["unstaked"]["setting"] is None else round(r["unstaked"]["setting"][0] * 1e4),
            "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
            "keeps_rebalanced": I.keeps_rebalanced(r, t),
            "rebalanced_block_share": r["rebalanced_block_share"], "today_rebalanced_share": t["rebalanced_block_share"],
            "user_staleness_bps": r["user_pretrade_staleness_bps_vw"], "today_user_staleness_bps": t["user_pretrade_staleness_bps_vw"],
            "uncorrected_hours": r["uncorrected_hours"], "fee_premium_to_lps_m": st["fee_premium_to_lps_m"],
            "unstaked_trades": r["unstaked"]["trades"], "builder_payments_m": r["builder_payments_m"],
        })
    out = {"chain": ACTIVE.name, "controller": c, "mean_daily_arb_volume_m": round(vbar / 1e6, 2),
           "stake_unit_usd": round(unit), "rows": rows}
    (I.OUT / "stake.json").write_text(json.dumps(out, indent=1))
    for row in rows:
        print(row)
    return out


if __name__ == "__main__":
    main()
