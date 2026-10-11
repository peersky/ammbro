"""Study R1: fee headroom — how far BRO-AMM can cut the fee routers quote and still leave LPs ahead.

Under BRO-AMM, LPs recover most of what arbitrage takes, so the pool can charge users less than
today's 5 bp and remain better for LPs than today's pool. This sweeps the pool fee f_min (paid by
users, who reach the pool fully covered through intermediaries, and by staked arbitrageurs) under
the final design, and compares LPs' net and users' all-in cost with today's 5 bp pool. The users'
all-in cost is what LPs earn from them per unit of user volume: the fee plus the markout of trading
against a stale price. The within-band test keeps today's band (5 + 1 bp) at every fee, so
rebalancing is compared on the same footing.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_routing → results/[<chain>/]study_i/routing.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE
from .study_i_position import POS

FEES_BPS = [5.0, 3.0, 2.0, 1.0, 0.5]


def main() -> dict:
    fcfs = ACTIVE.ordering == "fcfs"
    ctl, st = ("ctl_red4", {}) if fcfs else ("ctl_urgm", {"position_model": POS})
    runs, cfg = [], []
    for sc in I.SCENARIOS:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None))
        for f in FEES_BPS:
            runs.append(("marginal_cap", ctl, sc, 0.0, "open", False, 0.0,
                         {"stale_rule": "outcome", "pool_fee": f / 1e4, **st}))
            cfg.append((sc, f))
    res = I.main(runs, workers=6)
    today = {c[0]: x for c, x in zip(cfg, res) if c[1] is None}
    cost = lambda x: round(x["lp_from_users_m"] / max(x["user_volume_b"], 1e-9) / 1e3 * 1e4, 3)   # bp of user volume
    rows = []
    for c, x in zip(cfg, res):
        if c[1] is None:
            continue
        t = today[c[0]]
        rows.append({"scenario": c[0], "fee_bps": c[1], "controller": ctl,
                     "lp_net_m": x["lp_net_m"], "today_lp_net_m": t["lp_net_m"],
                     "lp_gain_vs_today_m": round(x["lp_net_m"] - t["lp_net_m"], 3),
                     "user_all_in_bps": cost(x), "today_user_all_in_bps": cost(t),
                     "lp_from_users_m": x["lp_from_users_m"], "lp_from_arbs_m": x["lp_from_arbs_m"],
                     "lp_recapture_m": x["lp_recapture_m"], "builder_payments_m": x["builder_payments_m"],
                     "arb_margin_m": x["arb_margin_m"], "user_volume_b": x["user_volume_b"],
                     "user_staleness_bps": x["user_pretrade_staleness_bps_vw"],
                     "today_user_staleness_bps": t["user_pretrade_staleness_bps_vw"],
                     "rebalanced_block_share": x["rebalanced_block_share"],
                     "today_rebalanced_block_share": t["rebalanced_block_share"],
                     "keeps_rebalanced": I.keeps_rebalanced(x, t), "uncorrected_hours": x["uncorrected_hours"]})
    out = {"chain": ACTIVE.name, "controller": ctl, "fees_bps": FEES_BPS, "rows": rows}
    (I.OUT / "routing.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in main()["rows"]:
        print(r["scenario"], r["fee_bps"], "LP", r["lp_net_m"], "vs", r["today_lp_net_m"], "user all-in", r["user_all_in_bps"], "vs", r["today_user_all_in_bps"], r["keeps_rebalanced"])
