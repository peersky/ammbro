"""Study I re-run for the concept review (paper §4.3–4.4, §5.4).

Point 1 — fresh unstaked accounts: every arbitrageur may instead trade from an
unstaked account, paying f_max + c·|own ln-price move| and keeping its whole
edge. Sweep f_max ∈ {30, 100, 200, 500} bp, c ∈ {0, 0.5}.
Point 2 — staleness by outcome: a correctable block is left stale only if no
point of the block brings the pool within f + m + ε (the first-swap rule could
be gamed with a dust swap); compared with the first-swap rule.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_review   → results/[<chain>/]study_i/review.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

UNSTAKED_GRID = [(f, c) for f in (30e-4, 100e-4, 200e-4, 500e-4) for c in (0.0, 0.5)]


def runs() -> list:
    ctls = ["ctl_feasible", "ctl_div"] if ACTIVE.ordering == "fcfs" else ["ctl_feasible"]
    out = []
    for sc in I.SCENARIOS:
        out.append(("today", None, sc, 0.0, "open", False, 0.0, {}))
        for ctl in ctls:
            out.append(("marginal_cap", ctl, sc, 0.0, "open", False, 0.0, {"stale_rule": "first_swap"}))
            out.append(("marginal_cap", ctl, sc, 0.0, "open", False, 0.0, {"stale_rule": "outcome"}))
            for u in UNSTAKED_GRID:
                out.append(("marginal_cap", ctl, sc, 0.0, "open", False, 0.0, {"stale_rule": "outcome", "unstaked": u}))
    return out


def summarise(res: list) -> dict:
    today = {r["scenario"]: r for r in res if r["rule"] == "today"}
    rows = []
    for r in res:
        if r["rule"] == "today":
            continue
        t = today[r["scenario"]]
        rows.append({
            "controller": r["param"], "scenario": r["scenario"], "stale_rule": r["stale_rule"],
            "unstaked_fmax_bps": None if r["unstaked"]["setting"] is None else round(r["unstaked"]["setting"][0] * 1e4),
            "unstaked_c": None if r["unstaked"]["setting"] is None else r["unstaked"]["setting"][1],
            "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
            "builder_payments_m": r["builder_payments_m"], "builder_today_m": t["builder_payments_m"],
            "unstaked_trades": r["unstaked"]["trades"], "unstaked_volume_b": r["unstaked"]["volume_b"],
            "arb_volume_b": r["arb_volume_b"],
            "keeps_rebalanced": I.keeps_rebalanced(r, t),
            "uncorrected_hours": r["uncorrected_hours"],
        })
    worst = {}
    for row in rows:
        k = (row["controller"], row["stale_rule"], row["unstaked_fmax_bps"], row["unstaked_c"])
        w = worst.setdefault(k, {"worst_lp_gain_m": 1e18, "all_rebalanced": True})
        w["worst_lp_gain_m"] = min(w["worst_lp_gain_m"], row["lp_gain_vs_today_m"])
        w["all_rebalanced"] &= row["keeps_rebalanced"]
    return {"chain": ACTIVE.name, "rows": rows,
            "worst_case": [{"controller": k[0], "stale_rule": k[1], "unstaked_fmax_bps": k[2], "unstaked_c": k[3], **v}
                           for k, v in worst.items()]}


def main() -> dict:
    res = I.main(runs())
    out = summarise(res)
    path = I.OUT / "review.json"
    path.write_text(json.dumps(out, indent=1))
    for w in out["worst_case"]:
        print(w)
    return out


if __name__ == "__main__":
    main()
