"""Studies R2 and R4: winning order flow with a lower fee, and the risk LPs bear doing so.

R4 (risk): today's pool and BRO-AMM at pool fees of 5, 3 and 1 bp, in the three cost scenarios, with
LPs' daily net P&L summarised (mean, volatility, 1st percentile, worst day, worst 7 days, share of
losing days) alongside users' all-in cost and rebalancing.

R2 (capture): if the lower fee wins routing, the pool draws flow from other venues and LPs follow
with liquidity. At 3 and 1 bp, user flow and depth are both scaled by k (stable costs; the depth
scenario carries stable costs). LPs' net is reported in total and per unit of liquidity (net / k),
so that a larger pool is not mistaken for a better return.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_capture → results/[<chain>/]study_i/capture.json
"""
from __future__ import annotations

import json

import numpy as np

from . import study_i as I
from .chains import ACTIVE
from .study_i_position import POS

RISK_FEES_BPS = [5.0, 3.0, 1.0]
CAPTURE_FEES_BPS = [3.0, 1.0]
CAPTURE_K = [1.5, 2.0, 3.0]


def daily_stats(x: dict) -> dict:
    d = np.array([v for _, v in x["daily_lp_net_m"]], dtype=float)
    w7 = np.convolve(d, np.ones(7), "valid") if len(d) >= 7 else d
    return {"daily_mean_m": round(float(d.mean()), 4), "daily_sd_m": round(float(d.std()), 4),
            "daily_p01_m": round(float(np.quantile(d, 0.01)), 4), "worst_day_m": round(float(d.min()), 4),
            "worst_7d_m": round(float(w7.min()), 4), "losing_day_share": round(float((d < 0).mean()), 4)}


def summary(x: dict) -> dict:
    return {"lp_net_m": x["lp_net_m"], "lp_from_users_m": x["lp_from_users_m"], "lp_from_arbs_m": x["lp_from_arbs_m"],
            "lp_recapture_m": x["lp_recapture_m"], "builder_payments_m": x["builder_payments_m"],
            "user_volume_b": x["user_volume_b"],
            "user_all_in_bps": round(x["lp_from_users_m"] / max(x["user_volume_b"], 1e-9) / 1e3 * 1e4, 3),
            "user_staleness_bps": x["user_pretrade_staleness_bps_vw"],
            "rebalanced_block_share": x["rebalanced_block_share"], "uncorrected_hours": x["uncorrected_hours"],
            **daily_stats(x)}


def main() -> dict:
    fcfs = ACTIVE.ordering == "fcfs"
    ctl, st = ("ctl_red4", {}) if fcfs else ("ctl_urgm", {"position_model": POS})
    runs, cfg = [], []
    for sc in I.SCENARIOS:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append(("risk", sc, None, 1.0))
        for f in RISK_FEES_BPS:
            runs.append(("marginal_cap", ctl, sc, 0.0, "open", False, 0.0, {"stale_rule": "outcome", "pool_fee": f / 1e4, **st}))
            cfg.append(("risk", sc, f, 1.0))
    for f in CAPTURE_FEES_BPS:
        for k in CAPTURE_K:
            runs.append(("marginal_cap", ctl, f"depth_x{k:g}", 0.0, "open", False, 0.0,
                         {"stale_rule": "outcome", "pool_fee": f / 1e4, "user_scale": k, **st}))
            cfg.append(("capture", "stable", f, k))
    res = I.main(runs, workers=6)
    today = {c[1]: x for c, x in zip(cfg, res) if c[0] == "risk" and c[2] is None}
    rows = []
    for c, x in zip(cfg, res):
        t = today[c[1]]
        row = {"study": c[0], "scenario": c[1], "fee_bps": c[2], "scale_k": c[3], "controller": None if c[2] is None else ctl,
               **summary(x), "today_lp_net_m": t["lp_net_m"],
               "today_user_all_in_bps": round(t["lp_from_users_m"] / max(t["user_volume_b"], 1e-9) / 1e3 * 1e4, 3)}
        row["lp_net_per_liquidity_m"] = round(x["lp_net_m"] / c[3], 3)
        if c[2] is not None and c[0] == "risk":
            row["keeps_rebalanced"] = I.keeps_rebalanced(x, t)
        rows.append(row)
    out = {"chain": ACTIVE.name, "controller": ctl, "rows": rows}
    (I.OUT / "capture.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in main()["rows"]:
        print(r["study"], r["scenario"], r["fee_bps"], r["scale_k"], "LP", r["lp_net_m"], "per-liq", r["lp_net_per_liquidity_m"],
              "worst day", r["worst_day_m"], "worst 7d", r["worst_7d_m"], "losing", r["losing_day_share"], "all-in", r["user_all_in_bps"])
