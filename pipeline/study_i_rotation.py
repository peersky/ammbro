"""Study I follow-up: rotating designated correctors as a readiness signal (paper §4.4, §5.4).

Registered arbitrageurs take turns: each hour a pseudo-random draw designates one, who earns the
allowance m; the others earn m·(1 − φ). If correctable gaps stay open for `grace` blocks the
window opens to all at full m and the designee fails it. The controller lowers m by 5% a day only
if at least k = 4 arbitrageurs passed a window in the last 24 h and failed none; it doubles m on
staleness as before. Dormancy and events as in study_i_redundancy (dropout of the cheapest for
7 days; the two cheapest withholding for 3 days).

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_rotation   → results/[<chain>/]study_i/rotation.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

DORM = {"dormant_after_s": 7 * 86400, "wake_s": 86400}
EVENTS = {"none": [], "dropout": [[0, 60, 7]], "withhold": [[0, 60, 3], [1, 60, 3]]}
VARIANTS = {"no rotation": None,
            "phi=0.25 grace=1": {"phi": 0.25, "grace_blocks": 1, "k": 4},
            "phi=0.25 grace=3": {"phi": 0.25, "grace_blocks": 3, "k": 4},
            "phi=0.5 grace=1": {"phi": 0.5, "grace_blocks": 1, "k": 4},
            "exclusive grace=1": {"phi": 1.0, "grace_blocks": 1, "k": 4}}


def main() -> dict:
    ctl = "ctl_div" if ACTIVE.ordering == "fcfs" else "ctl_feasible"
    runs = []
    for sc in I.SCENARIOS:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {}))
        for name, rot in VARIANTS.items():
            for ev, ab in EVENTS.items():
                st = dict(DORM, absent=ab, variant=name)
                if rot:
                    st["rotation"] = rot
                runs.append(("marginal_cap", "ctl_div" if rot else ctl, sc, 0.0, "open", False, 0.0, st))
    res = I.main(runs)
    today = {r["scenario"]: r for r in res if r["rule"] == "today"}
    def key(r):
        ro = r.get("rotation")
        return None if not ro else (ro["phi"], ro["grace_blocks"])
    base = {(key(r), r["scenario"]): r for r in res if r["rule"] != "today" and not r["absent"]}
    rows = []
    for r in res:
        if r["rule"] == "today":
            continue
        t = today[r["scenario"]]; b0 = base[(key(r), r["scenario"])]
        ev = "none" if not r["absent"] else ("dropout" if len(r["absent"]) == 1 else "withhold")
        wh = [a[0] for a in r["absent"]]
        ro = r.get("rotation")
        rows.append({
            "scenario": r["scenario"], "variant": "no rotation (" + r["param"] + ")" if not ro else f"phi={ro['phi']:g} grace={ro['grace_blocks']}",
            "event": ev, "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
            "keeps_rebalanced": I.keeps_rebalanced(r, t), "uncorrected_hours": r["uncorrected_hours"],
            "builder_payments_m": r["builder_payments_m"], "winner_hhi": r["winner_hhi"],
            "income_by_arb_m": r["income_by_arb_m"], "failed_windows": r["rotation_failed_windows"],
            "m_end_bps": r["m_end_bps"],
            "absent_income_vs_no_event_m": round(sum(r["income_by_arb_m"][j] - b0["income_by_arb_m"][j] for j in wh), 4) if wh else None,
        })
    out = {"chain": ACTIVE.name, "rows": rows}
    (I.OUT / "rotation.json").write_text(json.dumps(out, indent=1))
    for row in rows:
        print({k: row[k] for k in ("scenario", "variant", "event", "lp_gain_vs_today_m", "keeps_rebalanced", "uncorrected_hours", "builder_payments_m")})
    return out


if __name__ == "__main__":
    main()
