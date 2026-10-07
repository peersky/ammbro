"""Study I follow-up: premium mint with a shock bonus (paper §4.4, §4.6, §5.4).

Arbitrageurs start with no REP. A correcting swap's fee premium above F, net of its
charge, mints REP to it at par (no take); arbs value that REP at v of par, so an
under-covered correction bears the hurdle (1 − v)·(fee − F) as a cost. The allowance
in a block is m + κ·shock, with shock the benchmark's move across the block ("jump",
use it or lose it) or, as the rejected contrast, the standing gap ("gap").

  A. v ∈ {1, 0.95} × f_max ∈ {500, 1000, 2000} bp × κ ∈ {0, 0.1, 0.2} (jump)
  B. contrast: κ = 0.1 keyed to the standing gap, v = 0.95, f_max = 1000 bp
  C. rent: κ ∈ {0.1, 0.2} (jump) with arbitrageurs fully covered (no hurdle)

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_bonus   → results/[<chain>/]study_i/bonus.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE


def ctl() -> str:
    return "ctl_div" if ACTIVE.ordering == "fcfs" else "ctl_feasible"


def main() -> dict:
    c = ctl()
    runs = []
    for sc in I.SCENARIOS:
        b = ("marginal_cap", c, sc, 0.0, "open", False, 0.0)
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {}))
        runs.append(b + ({"stale_rule": "outcome"},))
        for v in (1.0, 0.95):
            for f in (500e-4, 1000e-4, 2000e-4):
                for k in (0.0, 0.1, 0.2):
                    runs.append(b + ({"premium_mint": v, "fmax": f, "shock_k": k, "shock_key": "jump"},))
        runs.append(b + ({"premium_mint": 0.95, "fmax": 1000e-4, "shock_k": 0.1, "shock_key": "gap"},))
        for k in (0.1, 0.2):
            runs.append(b + ({"stale_rule": "outcome", "shock_k": k, "shock_key": "jump"},))
    res = I.main(runs)
    today = {r["scenario"]: r for r in res if r["rule"] == "today"}
    rows = []
    for r in res:
        if r["rule"] == "today":
            continue
        t = today[r["scenario"]]; st = r["stake"]
        rows.append({
            "scenario": r["scenario"], "controller": c,
            "premium_mint_v": st["premium_mint_v"], "fmax_bps": st["fmax_bps"] if st["premium_mint_v"] is not None else None,
            "shock_k": st["shock_k"], "shock_key": st["shock_key"],
            "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
            "builder_payments_m": r["builder_payments_m"], "builder_today_m": t["builder_payments_m"],
            "keeps_rebalanced": I.keeps_rebalanced(r, t),
            "rebalanced_block_share": r["rebalanced_block_share"], "today_rebalanced_share": t["rebalanced_block_share"],
            "user_staleness_bps": r["user_pretrade_staleness_bps_vw"], "today_user_staleness_bps": t["user_pretrade_staleness_bps_vw"],
            "uncorrected_hours": r["uncorrected_hours"], "rep_minted_to_arbs_m": st["rep_minted_to_arbs_m"],
            "uncovered_charges_m": st["uncovered_charges_m"], "arb_stake_end_m": st["arb_stake_end_m"],
        })
    out = {"chain": ACTIVE.name, "controller": c, "rows": rows}
    (I.OUT / "bonus.json").write_text(json.dumps(out, indent=1))
    for row in rows:
        print(row)
    return out


if __name__ == "__main__":
    main()
