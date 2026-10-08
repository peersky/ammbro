"""Study I: today against the final design, the headline comparison of paper §5.4 (Table 3).

Final design: urgency measured by block position under the position model on auction chains, the
K_d >= 4 sender rule on arrival-ordered chains; outcome staleness. Each cost scenario is run for
today's pool and for BRO-AMM, recording who ends up with the value: LPs (net, from arbitrage, from
users, recaptured), arbitrageurs (margin after costs and payments for position), builders or
sequencers (payments for position), and users (volume-weighted staleness of the price they trade at).

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_headline → results/[<chain>/]study_i/headline.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE
from .study_i_position import POS

KEYS = ("lp_net_m", "lp_from_arbs_m", "lp_from_users_m", "lp_recapture_m", "builder_payments_m", "arb_margin_m",
        "arb_volume_b", "user_pretrade_staleness_bps_vw", "rebalanced_block_share", "uncorrected_hours", "m_bps_final")


def main() -> dict:
    fcfs = ACTIVE.ordering == "fcfs"
    ctl, st = ("ctl_red4", {}) if fcfs else ("ctl_urgm", {"position_model": POS})
    runs = []
    for sc in I.SCENARIOS:
        runs += [("today", None, sc, 0.0, "open", False, 0.0, {}),
                 ("marginal_cap", ctl, sc, 0.0, "open", False, 0.0, {"stale_rule": "outcome", **st})]
    res = I.main(runs, workers=6)
    rows = []
    for t, x in zip(res[0::2], res[1::2]):
        rows.append({"scenario": t["scenario"], "controller": ctl,
                     "today": {k: t.get(k) for k in KEYS}, "bro_amm": {k: x.get(k) for k in KEYS},
                     "keeps_rebalanced": I.keeps_rebalanced(x, t)})
    out = {"chain": ACTIVE.name, "rows": rows}
    (I.OUT / "headline.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in main()["rows"]:
        print(r)
