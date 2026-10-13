"""Study I: does REP cost feed back into staleness? Stake under volatility, and the price of stake.

Quantity channel: arbitrageurs hold stake sized for normal markets (25 × ρ × mean daily arbitrage
volume, pooled), and the market's shocks are scaled by two and four; a coverage curve on the epoch's
own volume then raises their fee exactly when gaps are largest. With and without the correction lane.
Price channel: fully staked arbitrageurs carry an extra cost of 0.25–1 bp of volume, as if REP were
dearer; the allowance controller should pass it to LPs as a higher allowance rather than staleness.
Mainnet, decay without a signal (§5.5 convention), users' corrections uncharged.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.study_i_rep_loop → results/study_i/rep_loop.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

LANE = {"mode": "sync", "fmax": 500e-4, "hold_s": float("inf"), "proof_gas_frac": 0.24}


def main() -> dict:
    stake_json = json.loads((I.OUT / "stake.json").read_text())
    unit = stake_json["stake_unit_usd"]
    c = "ctl_feasible"
    runs, cfg = [], []
    for sc in ("stable", "vol_x2", "vol_x4"):
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, "today"))
        runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0, {"stale_rule": "outcome"})); cfg.append((sc, "fully staked"))
        runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0,
                     {"stake": 25 * unit, "alloc": "pooled", "fmax": 500e-4})); cfg.append((sc, "stake for normal markets"))
        runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0,
                     {"stake": 25 * unit, "alloc": "pooled", "fmax": 500e-4, "relief": LANE})); cfg.append((sc, "stake for normal markets + lane"))
    for x in (0.25, 0.5, 1.0):
        runs.append(("marginal_cap", c, "stable", 0.0, "open", False, x, {"stale_rule": "outcome"})); cfg.append(("stable", f"stake costs +{x:g} bp"))
    res = I.main(runs, workers=6)
    today = {s: r for (s, d), r in zip(cfg, res) if d == "today"}
    rows = []
    for (s, d), r in zip(cfg, res):
        if d == "today":
            continue
        t = today[s]
        rows.append({"scenario": s, "design": d, "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
                     "uncorrected_hours": r["uncorrected_hours"], "keeps_rebalanced": I.keeps_rebalanced(r, t),
                     "m_end_bps": r.get("m_bps_final"), "lp_from_arbs_m": r["lp_from_arbs_m"],
                     "arb_margin_m": r["arb_margin_m"], "user_staleness_bps": r["user_pretrade_staleness_bps_vw"],
                     "today_user_staleness_bps": t["user_pretrade_staleness_bps_vw"]})
    out = {"chain": ACTIVE.name, "stake_unit_usd": unit, "rows": rows}
    (I.OUT / "rep_loop.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in main()["rows"]:
        print(r)
