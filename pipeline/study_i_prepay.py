"""Study I: REP issued only by swaps — prepaid charges, bond tuning and a supply that charges burn (paper §4.7).

B  prepay: charges are paid in REP minted by declared prepayment at P_int / (1 - tau); arbitrageurs weigh
   the surcharge tau / (1 - tau) on each charge and the controller responds. REP for the bond is leased
   so that bond supply does not bind (it is studied in C and in pipeline.rep_bootstrap).
C  bond: the bond REP needed per epoch, and the charges beyond it, at steepness s, hourly epochs.
D  burn: no prepayment; pooled arbitrage stake starts at the launch issuance, charges burn it at each
   settlement and rebates add to it.

Mainnet, decay without a signal (§5.4 convention), f_max = 500 bp, users' corrections uncharged.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.study_i_prepay → results/study_i/prepay.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

SCENARIOS = ("stable", "costs_x4", "costs_x8", "vol_x2", "vol_x4")
HOUR = 3600.0
LEASE = {"slack_bps": 0.1, "series": True}
H_6M = 4399.0
CONFIGS = {
    **{f"B prepay, tau = {t:g}%": {"stake": 0.0, "lease": LEASE, "charge_surcharge": t / 100 / (1 - t / 100)} for t in (1.0, 2.5, 5.0)},
    **{f"C bond, s = {s:g}": {"stake": 0.0, "lease": {**LEASE, "s": s}} for s in (0.5, 1.0, 2.0, 4.0)},
    **{f"D burn, launch $0.91 M, rebates {name}": {"stake": 0.91e6, "alloc": "pooled", "collateral": True,
                                                   "rep_supply": {"launch_usd": 0.91e6, "rebate_usd_per_h": r * 1e6 / H_6M}}
       for name, r in (("theta 2 bp", 0.30), ("theta 1 bp", 1.31))},
}


def main() -> dict:
    runs, cfg = [], []
    for sc in SCENARIOS:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None))
        for name, st in CONFIGS.items():
            runs.append(("marginal_cap", "ctl_feasible", sc, 0.0, "open", False, 0.0,
                         {"alloc": "equal", "fmax": 500e-4, "stake_epoch_s": HOUR, **st})); cfg.append((sc, name))
    res = I.main(runs, workers=6)
    today = {c[0]: r for c, r in zip(cfg, res) if c[1] is None}
    rows = []
    for (sc, name), r in zip(cfg, res):
        if name is None:
            continue
        t = today[sc]
        ls = r.get("lease") or {}
        rows.append({"scenario": sc, "config": name, "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
                     "keeps_rebalanced": I.keeps_rebalanced(r, t), "uncorrected_hours": r["uncorrected_hours"],
                     "recapture_m": r["lp_recapture_m"], "arb_margin_m": r["arb_margin_m"], "m_end_bps": r["m_bps_final"],
                     "arb_volume_b": r["arb_volume_b"], "surcharge": r["charge_surcharge"], "rep_supply": r["rep_supply"],
                     "uncovered_charges_m": r["stake"]["uncovered_charges_m"],
                     "bond_peak_m": ls.get("peak_epoch_lease_m"), "bond_mean_m": ls.get("mean_epoch_lease_m"),
                     "charges_beyond_bond_m": ls.get("credit_total_m"), "charges_beyond_bond_epoch_max_m": ls.get("credit_epoch_max_m"),
                     "series": {"bond_k": ls.get("per_epoch_lease_k"), "charges_k": ls.get("per_epoch_charges_k")} if name.startswith("C bond, s = 1") else None})
    out = {"chain": ACTIVE.name, "configs": CONFIGS, "rows": rows}
    (I.OUT / "prepay.json").write_text(json.dumps(out))
    return out


if __name__ == "__main__":
    for r in main()["rows"]:
        print(r["scenario"], "|", r["config"], "| gain", r["lp_gain_vs_today_m"], "| reb", r["keeps_rebalanced"], "| unc h", r["uncorrected_hours"],
              "| recap", r["recapture_m"], "| margin", r["arb_margin_m"], "| m", r["m_end_bps"], "| sur", r["surcharge"],
              "| supply", r["rep_supply"], "| bond", r["bond_peak_m"], r["charges_beyond_bond_m"], r["charges_beyond_bond_epoch_max_m"])
