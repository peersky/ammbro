"""Study I: REP leased against capital, and BRO, an account-bound score that steepens the curve (paper §4.7).

No owned arbitrage stake. Each arbitrageur deposits capital at P_int per unit and leases, for the
epoch, enough REP to hold its fee within 0.1 bp of f_min on its epoch volume so far. Charges are paid
from the leased REP; anything beyond is credit. With BRO, an account earns a score from the correction
volume it settled, decaying with a 30-day half-life, and its curve steepens towards s_max, so it needs
less REP (capital) for the same fee, at the price of charges that can exceed its lease. The bust-out
bound is the largest single-epoch charge beyond an account's lease: what that account could leave
unpaid by walking away once.

Mainnet, decay without a signal (§5.4 convention), f_max = 500 bp, users' corrections uncharged.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.study_i_lease [series] → results/study_i/lease[_series].json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

SCENARIOS = ("stable", "costs_x4", "costs_x8", "vol_x2", "vol_x4")
HOUR, DAY = 3600.0, 0.0
BRO = {"half_life_epochs": 720, "b0_usd": 5e8}
CONFIGS = {
    "lease, hourly": (HOUR, {}),
    "lease, daily": (DAY, {}),
    "lease + BRO, hourly, s_max = 4": (HOUR, {"bro": {**BRO, "s_max": 4.0}}),
    "lease + BRO, hourly, s_max = 8": (HOUR, {"bro": {**BRO, "s_max": 8.0}}),
    "lease + BRO, hourly, s_max = 4, B0 = $100 M": (HOUR, {"bro": {**BRO, "s_max": 4.0, "b0_usd": 1e8}}),
}


def series() -> dict:
    """Per-epoch leased capital, hourly epochs, s = 1, for the lease-fee analysis (pipeline.lease_fees)."""
    runs = [("marginal_cap", "ctl_feasible", sc, 0.0, "open", False, 0.0,
             {"stake": 0.0, "alloc": "equal", "fmax": 500e-4, "stake_epoch_s": HOUR, "lease": {"slack_bps": 0.1, "series": True}})
            for sc in SCENARIOS]
    res = I.main(runs, workers=5)
    out = {"chain": ACTIVE.name, "epoch_s": HOUR,
           "scenarios": {sc: {"lease_k": r["lease"]["per_epoch_lease_k"], "charges_k": r["lease"]["per_epoch_charges_k"],
                         "arb_volume_b": r["arb_volume_b"], "recapture_m": r["lp_recapture_m"]} for sc, r in zip(SCENARIOS, res)}}
    (I.OUT / "lease_series.json").write_text(json.dumps(out))
    return out


def main() -> dict:
    runs, cfg = [], []
    for sc in SCENARIOS:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None))
        for name, (ep, lease) in CONFIGS.items():
            st = {"stake": 0.0, "alloc": "equal", "fmax": 500e-4, "lease": {"slack_bps": 0.1, **lease}}
            if ep:
                st["stake_epoch_s"] = ep
            runs.append(("marginal_cap", "ctl_feasible", sc, 0.0, "open", False, 0.0, st)); cfg.append((sc, name))
    res = I.main(runs, workers=6)
    today = {c[0]: r for c, r in zip(cfg, res) if c[1] is None}
    rows = []
    for (sc, name), r in zip(cfg, res):
        if name is None:
            continue
        t = today[sc]
        rows.append({"scenario": sc, "config": name, "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
                     "keeps_rebalanced": I.keeps_rebalanced(r, t), "uncorrected_hours": r["uncorrected_hours"],
                     "lease": r["lease"], "recapture_m": r["lp_recapture_m"], "arb_volume_b": r["arb_volume_b"],
                     "unstaked_volume_b": r["unstaked"]["volume_b"]})
    out = {"chain": ACTIVE.name, "configs": {k: list(v) for k, v in CONFIGS.items()}, "rows": rows}
    (I.OUT / "lease.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["series"]:
        series(); raise SystemExit
    for r in main()["rows"]:
        ls = r["lease"]
        print(r["scenario"], "|", r["config"], "| gain", r["lp_gain_vs_today_m"], "| reb", r["keeps_rebalanced"], "| unc h", r["uncorrected_hours"],
              "| lease peak/p99/mean", ls["peak_epoch_lease_m"], ls["p99_epoch_lease_m"], ls["mean_epoch_lease_m"],
              "| credit tot/epmax", ls["credit_total_m"], ls["credit_epoch_max_m"], "| bust-out", ls["bust_out_bound_by_arb_m"], "| s", ls["s_end"])
