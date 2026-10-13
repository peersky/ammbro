"""Study I: sensitivity of the final design to the arbitrage population and pool depth (paper Appendix C).

Final design on each chain, every correcting swap charged: on mainnet urgency measured by block position
at 3 bp, against decay without a signal; on Arbitrum the sender rule K_min = 3 at 4 bp. Populations: a
monopolist, two arbitrageurs, ten, all costs halved, all costs doubled; depth halved and doubled.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_sensitivity → results/[<chain>/]study_i/sensitivity_final.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE
from .study_i_position import POS

SCEN = ("stable",) + I.SENSITIVITY


def designs():
    if ACTIVE.ordering == "fcfs":
        return {"sender rule, K_min = 3, 4 bp": ("ctl_red3", {"stale_rule": "outcome", "pool_fee": 4e-4, "fcfs": True, "charge_users": True})}
    return {"urgency by position, 3 bp": ("ctl_urgm", {"stale_rule": "outcome", "pool_fee": 3e-4, "position_model": POS, "charge_users": True}),
            "decay without a signal, 3 bp": ("ctl_feasible", {"stale_rule": "outcome", "pool_fee": 3e-4, "position_model": POS, "charge_users": True})}


def main() -> dict:
    runs, cfg = [], []
    for sc in SCEN:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None))
        for name, (ctl, st) in designs().items():
            runs.append(("marginal_cap", ctl, sc, 0.0, "open", False, 0.0, st)); cfg.append((sc, name))
    res = I.main(runs, workers=6)
    today = {c[0]: r for c, r in zip(cfg, res) if c[1] is None}
    rows = [{"scenario": c[0], "design": c[1], "lp_gain_vs_today_m": round(r["lp_net_m"] - today[c[0]]["lp_net_m"], 3),
             "keeps_rebalanced": I.keeps_rebalanced(r, today[c[0]]), "uncorrected_hours": r["uncorrected_hours"],
             "builder_payments_m": r["builder_payments_m"], "today_builder_payments_m": today[c[0]]["builder_payments_m"],
             "m_end_bps": r["m_bps_final"]} for c, r in zip(cfg, res) if c[1] is not None]
    out = {"chain": ACTIVE.name, "populations_bps": I.POPULATIONS, "rows": rows}
    (I.OUT / "sensitivity_final.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in main()["rows"]:
        print(r)
