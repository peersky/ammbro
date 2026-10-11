"""Study I: retail retention (S1) — how much non-arbitrage flow BRO-AMM must keep to beat today.

The simulation holds user flow fixed; if users route away from a pool whose quotes they cannot
reach, the pool keeps only a share k of it. Every non-arbitrage swap is scaled by k (volume, fees and
price impact alike), under the final design (urgency by block position on auction chains, the
K_d >= 4 sender rule on arrival-ordered chains), and LPs' net is compared with today's pool at full
flow. k is a share of volume, not a model of routing; S2 would make it depend on the quote.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_retention → results/[<chain>/]study_i/retention.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE
from .study_i_position import POS

KS = [0.0, 0.25, 0.5, 0.75, 1.0]


def main() -> dict:
    fcfs = ACTIVE.ordering == "fcfs"
    ctl, st = ("ctl_red4", {}) if fcfs else ("ctl_urgm", {"position_model": POS})
    runs, cfg = [], []
    for sc in I.SCENARIOS:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, "today", 1.0))
        for k in KS:
            runs.append(("marginal_cap", ctl, sc, 0.0, "open", False, 0.0, {"stale_rule": "outcome", "user_scale": k, **st}))
            cfg.append((sc, "bro_amm", k))
    res = I.main(runs, workers=6)
    today = {c[0]: x for c, x in zip(cfg, res) if c[1] == "today"}
    rows = []
    for c, x in zip(cfg, res):
        if c[1] == "today":
            continue
        t = today[c[0]]
        rows.append({"scenario": c[0], "retention": c[2], "controller": ctl,
                     "lp_net_m": x["lp_net_m"], "today_lp_net_m": t["lp_net_m"],
                     "lp_gain_vs_today_m": round(x["lp_net_m"] - t["lp_net_m"], 3),
                     "lp_from_users_m": x["lp_from_users_m"], "lp_from_arbs_m": x["lp_from_arbs_m"],
                     "lp_recapture_m": x["lp_recapture_m"], "builder_payments_m": x["builder_payments_m"],
                     "arb_volume_b": x["arb_volume_b"], "rebalanced_block_share": x["rebalanced_block_share"],
                     "today_rebalanced_block_share": t["rebalanced_block_share"]})
    out = {"chain": ACTIVE.name, "controller": ctl, "retention_levels": KS, "rows": rows}
    (I.OUT / "retention.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in main()["rows"]:
        print(r["scenario"], r["retention"], r["lp_net_m"], "vs today", r["today_lp_net_m"])
