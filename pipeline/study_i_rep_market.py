"""Study I: REP as a transferable bond issued only by swaps, charges paid in tokens (paper §4.6–4.8).

Charges are an ex-post fee paid in tokens; REP is burned only on default (none here). REP supply starts
at a backed initial issuance and grows by rebates to overpayers (spread evenly, at the six-month totals
of Appendix E); holders may redeem idle REP at par. Routers keep enough REP to quote retail near f_min,
and arbitrageurs bond, by owning or leasing, from the rest, pooled, hourly epochs.

Layer 1 (simulation): rebalancing, uncorrected hours and LPs' gain when arbitrageurs' bond is limited to
the REP available. Layer 2 (offline, same supply path): if arbitrageurs instead outbid routers for REP
in a swing, routers keep only what is left after arbitrageurs' bond need (results/study_i/lease_series.json),
and retail's fee rises along the coverage curve; reported as hours and volume-weighted premium.

Mainnet, decay without a signal (§5.4 convention), f_max = 500 bp, users' corrections uncharged.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.study_i_rep_market → results/study_i/rep_market.json
"""
from __future__ import annotations

import json
import math

import numpy as np

from . import study_i as I
from .chains import ACTIVE

SCENARIOS = ("stable", "costs_x4", "costs_x8", "vol_x2", "vol_x4")
H_6M = 4399.0
ROUTER_HOLD = 34e3
RETAIL_PER_H = 19.6e9 / H_6M          # mainnet user volume per hour
CONFIGS = {}
for r0 in (0.0, 0.5, 1.0):
    for theta, reb in (("theta 2 bp", 0.30), ("theta 1 bp", 1.31)):
        for red in (0.0, 0.02):
            if r0 == 0.0 and (theta == "theta 2 bp" or red):
                continue
            CONFIGS[f"initial ${r0:g}M, rebates {theta}, redeem {red * 100:g}%/day"] = (r0, reb, red)


def retail_premium(S, L, fmax=500e-4, f=5e-4):
    """Arbitrageurs first: routers keep min(hold, S - L); retail's premium over f_min on the curve (3)."""
    n = min(len(S), len(L))
    S, L = np.asarray(S[:n]) * 1e3, np.asarray(L[:n]) * 1e3
    rR = np.clip(S - L, 0.0, ROUTER_HOLD)
    prem = (fmax - f) * np.exp(-rR / (I.RHO * RETAIL_PER_H))
    return {"hours_premium_over_0.5bp": int((prem > 0.5e-4).sum()), "hours_premium_over_5bp": int((prem > 5e-4).sum()),
            "mean_premium_bps": round(float(prem.mean()) * 1e4, 3), "max_premium_bps": round(float(prem.max()) * 1e4, 1)}


def main() -> dict:
    lease = json.loads((I.OUT / "lease_series.json").read_text())["scenarios"]
    runs, cfg = [], []
    for sc in SCENARIOS:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None))
        for name, (r0, reb, red) in CONFIGS.items():
            st = {"stake": r0 * 1e6, "alloc": "pooled", "fmax": 500e-4, "stake_epoch_s": 3600.0,
                  "rep_supply": {"launch_usd": r0 * 1e6, "rebate_usd_per_h": reb * 1e6 / H_6M, "burn": False,
                                 "router_hold_usd": ROUTER_HOLD, "redeem_per_day": red, "series": True}}
            runs.append(("marginal_cap", "ctl_feasible", sc, 0.0, "open", False, 0.0, st)); cfg.append((sc, name))
    res = I.main(runs, workers=6)
    today = {c[0]: r for c, r in zip(cfg, res) if c[1] is None}
    rows = []
    for (sc, name), r in zip(cfg, res):
        if name is None:
            continue
        t = today[sc]; rs = r["rep_supply"]
        rows.append({"scenario": sc, "config": name, "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
                     "keeps_rebalanced": I.keeps_rebalanced(r, t), "uncorrected_hours": r["uncorrected_hours"],
                     "user_staleness_bps": r["user_pretrade_staleness_bps_vw"], "today_user_staleness_bps": t["user_pretrade_staleness_bps_vw"],
                     "supply_end_m": round(rs["end_usd"] / 1e6 + ROUTER_HOLD / 1e6, 3), "supply_min_m": round(rs["min_usd"] / 1e6, 3),
                     "redeemed_m": rs["redeemed_m"], "arbs_first_retail": retail_premium(rs["supply_k_by_epoch"], lease[sc]["lease_k"])})
    out = {"chain": ACTIVE.name, "router_hold_usd": ROUTER_HOLD, "configs": {k: list(v) for k, v in CONFIGS.items()}, "rows": rows}
    (I.OUT / "rep_market.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in main()["rows"]:
        print(r["scenario"], "|", r["config"], "| gain", r["lp_gain_vs_today_m"], "| reb", r["keeps_rebalanced"], "| unc h", r["uncorrected_hours"],
              "| stale", r["user_staleness_bps"], "/", r["today_user_staleness_bps"], "| supply min/end", r["supply_min_m"], r["supply_end_m"],
              "| redeemed", r["redeemed_m"], "| retail", r["arbs_first_retail"])
