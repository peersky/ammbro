"""Study I: allowance controllers under a position model (paper §4.3–4.4, §5.4).

Builders order transactions by payment per gas; ordinary (retail) swaps draw tips from the pool's
measured retail distribution; an arbitrageur chooses its payment for position, and competing
arbitrageurs bid it up. 45% of corrections pay builders directly, outside the tip (Study H), so their
tip is invisible while their position is not. The part of a correction executed after protected retail
(tip <= retail p90) has traded at the stale price keeps 25% less allowance, pro rata by volume.

Controllers: no competition signal (decay when calm), urgency measured from block position (a
correction is urgent if it sits more than κ = 2 times closer to the top than the earliest protected
retail swap), and the ideal flag (a rival could also profit). Each raises m hourly on staleness.
Stress: cost shocks, dropout of the cheapest arbitrageur for 7 days, withholding by the two cheapest
for 3 days, with idle arbitrageurs redeploying 1 h or 24 h after the pool is left uncorrected.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.study_i_position   → results/study_i/position.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

GRID = [0.0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 25.0, 100.0]
POS = {"penalty": 0.25, "pay_grid": GRID, "protect_q": 0.9, "vol_weight": True, "kappa": 2.0,
       "urgency_by": "index", "hidden_bribe_share": 0.45}
CTLS = {"no signal": "ctl_feasible", "urgency by index": "ctl_urgm", "ideal flag": "ctl_urg2"}
EVENTS = {"none": [], "dropout": [[0, 60, 7]], "withhold": [[0, 60, 3], [1, 60, 3]]}


def main() -> dict:
    runs, cfg = [], []
    for sc in I.SCENARIOS:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append(("today", sc, None, None))
        for name, c in CTLS.items():
            runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0, {"position_model": POS})); cfg.append((name, sc, None, "none"))
            for wk in (3600, 86400):
                for ev, ab in EVENTS.items():
                    runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0,
                                 {"position_model": POS, "dormant_after_s": 7 * 86400, "wake_s": wk, "absent": ab}))
                    cfg.append((name, sc, wk, ev))
    res = I.main(runs)
    today = {c[1]: x for c, x in zip(cfg, res) if c[0] == "today"}
    rows = []
    for c, x in zip(cfg, res):
        if c[0] == "today":
            continue
        t = today[c[1]]
        rows.append({"controller": c[0], "scenario": c[1], "redeploy_s": c[2], "event": c[3],
                     "lp_gain_vs_today_m": round(x["lp_net_m"] - t["lp_net_m"], 3), "lp_net_m": x["lp_net_m"],
                     "keeps_rebalanced": I.keeps_rebalanced(x, t),
                     "user_staleness_bps": x["user_pretrade_staleness_bps_vw"], "today_user_staleness_bps": t["user_pretrade_staleness_bps_vw"],
                     "within_band": x["rebalanced_block_share"], "today_within_band": t["rebalanced_block_share"],
                     "builder_payments_m": x["builder_payments_m"], "uncorrected_hours": x["uncorrected_hours"],
                     "top2_income_m": round(sum(x["income_by_arb_m"][:2]), 4), "m_end_bps": x["m_end_bps"]})
    out = {"chain": ACTIVE.name, "position_model": POS, "rows": rows}
    (I.OUT / "position.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()
