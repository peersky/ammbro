"""Study I: report-carrying corrections folded into the fee and collateral terms (paper §4.7).

A correcting swap may carry a signed report. Its charge is computed against the report at execution
and taken from its output; the true-up against the batch benchmark is owed at reconciliation, from a
margin mu_a * V. The margin is parked from REP stake, and the swap then counts mu_a / rho of its volume
against the account's coverage, or withheld from the output, and the swap counts none (fee f_min for
an account with no other volume). mu_a starts at mu_0 and follows the account's record: the 99th
percentile of its last true-ups per unit of volume. Reports are drawn on a Brownian bridge between
blocks, dated lag + U(0, window) before the decision instant; a picking corrector submits, of several,
the one proving the smallest gap.

Mainnet, decay without a signal (§5.4 convention), f_max = 500 bp, users' corrections uncharged,
charges collected from stake per epoch with uncovered charges counted as lost to LPs.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.study_i_report [mu] → results/study_i/report[_mu].json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

SCENARIOS = ("stable", "costs_x4", "costs_x8", "vol_x2", "vol_x4")
HOUR, DAY = 3600.0, 0.0
REP = {"mu0_bps": 5.0, "mu_min_bps": 0.25, "lag_s": 0.25}
CONFIGS = {
    "25 units, hourly, no reports": (25, HOUR, {**REP, "off": True}),
    "25 units, hourly, margin from stake": (25, HOUR, {**REP, "withheld": False}),
    "25 units, hourly, stake or withheld": (25, HOUR, REP),
    "25 units, daily, no reports": (25, DAY, {**REP, "off": True}),
    "25 units, daily, margin from stake": (25, DAY, {**REP, "withheld": False}),
    "2 units, hourly, margin from stake": (2, HOUR, {**REP, "withheld": False}),
    "2 units, hourly, stake or withheld": (2, HOUR, REP),
    "no stake, withheld": (0, HOUR, REP),
    "no stake, withheld, picking among 5 reports": (0, HOUR, {**REP, "pick": 5, "window_s": 1.0}),
    "no stake, withheld, reports 1 s old": (0, HOUR, {**REP, "lag_s": 1.0}),
}
# second pass: margin parked from stake pays only if mu_0 < rho (otherwise a report saves no coverage)
CONFIGS_MU = {
    "2 units, hourly, margin from stake, mu_0 = 2 bp": (2, HOUR, {**REP, "mu0_bps": 2.0, "withheld": False}),
    "2 units, hourly, margin from stake, mu_0 = 1 bp": (2, HOUR, {**REP, "mu0_bps": 1.0, "withheld": False}),
    "2 units, daily, margin from stake, mu_0 = 1 bp": (2, DAY, {**REP, "mu0_bps": 1.0, "withheld": False}),
    "25 units, daily, margin from stake, mu_0 = 1 bp": (25, DAY, {**REP, "mu0_bps": 1.0, "withheld": False}),
    "no stake, withheld, mu_0 = 10 bp": (0, HOUR, {**REP, "mu0_bps": 10.0}),
    "no stake, withheld, picking among 5 reports, mu_0 = 10 bp": (0, HOUR, {**REP, "mu0_bps": 10.0, "pick": 5, "window_s": 1.0}),
}


def main(part: str = "") -> dict:
    configs = CONFIGS_MU if part == "mu" else CONFIGS
    unit = json.loads((I.OUT / "stake.json").read_text())["stake_unit_usd"]
    runs, cfg = [], []
    for sc in SCENARIOS:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None))
        for name, (units, ep, rep) in configs.items():
            st = {"stake": units * unit, "alloc": "pooled", "fmax": 500e-4, "collateral": True, "report": rep}
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
                     "uncovered_charges_m": r["stake"]["uncovered_charges_m"], "report": r["report"],
                     "unstaked_volume_b": r["unstaked"]["volume_b"], "arb_volume_b": r["arb_volume_b"],
                     "user_staleness_bps": r["user_pretrade_staleness_bps_vw"], "today_user_staleness_bps": t["user_pretrade_staleness_bps_vw"]})
    out = {"chain": ACTIVE.name, "stake_unit_usd": unit, "configs": {k: list(v) for k, v in configs.items()}, "rows": rows}
    (I.OUT / f"report{'_' + part if part else ''}.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    import sys
    for r in main(sys.argv[1] if len(sys.argv) > 1 else "")["rows"]:
        rp = r["report"] or {}
        print(r["scenario"], "|", r["config"], "| gain", r["lp_gain_vs_today_m"], "| reb", r["keeps_rebalanced"], "| unc h", r["uncorrected_hours"],
              "| uncovered", r["uncovered_charges_m"], "| park/withheld/plain vol", rp.get("park_volume"), rp.get("withheld_volume"), rp.get("plain_volume"),
              "| mu", rp.get("mu_end_bps"))
