"""Study I: the final design on each chain — urgency-accelerated decay on auction chains, the K_d >= 4
distinct-winner rule on arrival-ordered chains; outcome staleness; fresh unstaked accounts at f_max = 500 bp.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_final   → results/[<chain>/]study_i/final_design.json
"""
import json, sys
from . import study_i as I
from .chains import ACTIVE
ctl = "ctl_red4" if ACTIVE.ordering == "fcfs" else "ctl_urg2"
st = {"stale_rule": "outcome", "unstaked": (500e-4, 0.0)}
runs = []
for sc in I.SCENARIOS:
    runs += [("today", None, sc, 0.0, "open", False, 0.0, {}), ("marginal_cap", ctl, sc, 0.0, "open", False, 0.0, dict(st))]
r = I.main(runs, workers=6)
out = []
for t, x in zip(r[0::2], r[1::2]):
    out.append({"scenario": x["scenario"], "controller": ctl,
        "lp_net_today_m": t["lp_net_m"], "lp_net_m": x["lp_net_m"], "gain_m": round(x["lp_net_m"] - t["lp_net_m"], 3),
        "lp_recapture_m": x["lp_recapture_m"], "builder_today_m": t["builder_payments_m"], "builder_m": x["builder_payments_m"],
        "rebalanced": I.keeps_rebalanced(x, t), "within_band": x["rebalanced_block_share"], "within_band_today": t["rebalanced_block_share"],
        "user_stale": x["user_pretrade_staleness_bps_vw"], "user_stale_today": t["user_pretrade_staleness_bps_vw"],
        "uncorrected_hours": x["uncorrected_hours"], "arb_volume_b": x["arb_volume_b"], "lp_from_arbs_m": x["lp_from_arbs_m"],
        "lp_from_users_m": x["lp_from_users_m"], "unstaked_trades": x["unstaked"]["trades"], "m_end_bps": x["m_end_bps"]})
(I.OUT / "final_design.json").write_text(json.dumps({"chain": ACTIVE.name, "rows": out}, indent=1))
for o in out: print(o)
