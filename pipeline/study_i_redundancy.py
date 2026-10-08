"""Study I follow-up: allowance controller robustness to arbitrageur dropout and withholding (paper §4.4, §5.4).

Arbitrageurs with no win for 7 days go dormant (infrastructure down) and re-enter 24 h after a
gap they could have closed was left uncorrected. Events: the cheapest arbitrageur absent for
7 days from day 60 (dropout); the two cheapest absent for 3 days from day 60 (withholding).
Controllers: blind decay (ctl_feasible), sender diversity (ctl_div: decay if the top sender won
< 75% of the day's corrections) and redundancy (ctl_redK: decay only if at least K senders each
won >= 5%). Reported: stall hours, LP gain, payments for position, winner concentration (HHI)
and each arbitrageur's income — a withholder's gain is its income against the no-event run.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_redundancy   → results/[<chain>/]study_i/redundancy.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

CTLS = ["ctl_feasible", "ctl_div", "ctl_red4", "ctl_red5"]
DORM = {"dormant_after_s": 7 * 86400, "wake_s": 86400}
EVENTS = {"none": [], "dropout": [[0, 60, 7]], "withhold": [[0, 60, 3], [1, 60, 3]]}


def main() -> dict:
    runs = []
    for sc in I.SCENARIOS + ("pop_duo", "pop_monopoly"):
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {}))
        for c in CTLS:
            evs = EVENTS if sc in I.SCENARIOS else {"none": []}
            for ev, ab in evs.items():
                runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0, dict(DORM, absent=ab, event=ev)))
    res = I.main(runs)
    today = {r["scenario"]: r for r in res if r["rule"] == "today"}
    base = {(r["param"], r["scenario"]): r for r in res if r["rule"] != "today" and not r["absent"]}
    rows = []
    for r in res:
        if r["rule"] == "today":
            continue
        t = today[r["scenario"]]; b0 = base[(r["param"], r["scenario"])]
        ev = "none" if not r["absent"] else ("dropout" if len(r["absent"]) == 1 else "withhold")
        wh = [a[0] for a in r["absent"]]
        rows.append({
            "scenario": r["scenario"], "controller": r["param"], "event": ev,
            "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
            "keeps_rebalanced": I.keeps_rebalanced(r, t), "uncorrected_hours": r["uncorrected_hours"],
            "builder_payments_m": r["builder_payments_m"], "winner_hhi": r["winner_hhi"],
            "income_by_arb_m": r["income_by_arb_m"], "m_end_bps": r["m_end_bps"],
            "absent_income_vs_no_event_m": round(sum(r["income_by_arb_m"][j] - b0["income_by_arb_m"][j] for j in wh), 4) if wh else None,
        })
    out = {"chain": ACTIVE.name, "rows": rows}
    (I.OUT / "redundancy.json").write_text(json.dumps(out, indent=1))
    for row in rows:
        print({k: row[k] for k in ("scenario", "controller", "event", "lp_gain_vs_today_m", "keeps_rebalanced", "uncorrected_hours", "absent_income_vs_no_event_m")})
    return out


if __name__ == "__main__":
    main()
