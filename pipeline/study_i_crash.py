"""Study I: tail events — a crash far larger than f_max, against bonded and speed-scaled collateral (paper App. G.2).

The external price is made to fall by 30% over an hour, by 30% within one block, or by 50% over an hour,
from day 90 of the sample, and stays there; the same path is replayed against today's pool and against
BRO-AMM. Arbitrageurs hold a pooled bond of 25 units (about $0.91 M), hourly epochs, and charges beyond
the bond are left unpaid and lost to LPs; fresh accounts at f_max remain available. With speed-scaled
collateral the capacity scale rises with the pool's own price move over the last hour,
rho_eff = rho (1 + k |move| / 50 bp), so the bond covers less volume in a fast market.

The crash's cost to LPs is LPs' net without the crash minus with it, for each design.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.study_i_crash → results/study_i/crash.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

CRASHES = {"none": None, "30% over an hour": {"pct": 0.30, "dur_s": 3600.0},
           "30% in one block": {"pct": 0.30, "dur_s": 12.0}, "50% over an hour": {"pct": 0.50, "dur_s": 3600.0}}
DESIGNS = {"f_max 1,000 bp": (1000e-4, None), "f_max 1,000 bp, speed-scaled, k = 2": (1000e-4, 2.0),
           "f_max 1,000 bp, speed-scaled, k = 8": (1000e-4, 8.0), "f_max 2,000 bp": (2000e-4, None)}


def main() -> dict:
    unit = json.loads((I.OUT / "stake.json").read_text())["stake_unit_usd"]
    runs, cfg = [], []
    for cname, cr in CRASHES.items():
        base = {"crash": cr} if cr else {}
        runs.append(("today", None, "stable", 0.0, "open", False, 0.0, dict(base))); cfg.append((cname, "today"))
        for dname, (fmax, k) in DESIGNS.items():
            st = {**base, "stake": 25 * unit, "alloc": "pooled", "fmax": fmax, "collateral": True, "stake_epoch_s": 3600.0}
            if k is not None:
                st["vol_collateral"] = {"k": k, "ref_bps": 50.0, "window_s": 3600.0}
            runs.append(("marginal_cap", "ctl_feasible", "stable", 0.0, "open", False, 0.0, st)); cfg.append((cname, dname))
    res = I.main(runs, workers=6)
    R = {c: r for c, r in zip(cfg, res)}
    rows = []
    for cname in CRASHES:
        if cname == "none":
            continue
        t_cost = R[("none", "today")]["lp_net_m"] - R[(cname, "today")]["lp_net_m"]
        rows.append({"crash": cname, "design": "today", "crash_cost_to_lps_m": round(t_cost, 3)})
        for dname in DESIGNS:
            a, b = R[("none", dname)], R[(cname, dname)]
            cost = a["lp_net_m"] - b["lp_net_m"]
            rows.append({"crash": cname, "design": dname, "crash_cost_to_lps_m": round(cost, 3),
                         "share_of_todays_cost": round(cost / t_cost, 3) if t_cost else None,
                         "lp_gain_vs_today_m": round(b["lp_net_m"] - R[(cname, "today")]["lp_net_m"], 3),
                         "extra_uncovered_charges_m": round(b["stake"]["uncovered_charges_m"] - a["stake"]["uncovered_charges_m"], 3),
                         "extra_fresh_volume_b": round(b["unstaked"]["volume_b"] - a["unstaked"]["volume_b"], 3),
                         "uncorrected_hours": b["uncorrected_hours"], "uncorrected_hours_no_crash": a["uncorrected_hours"]})
    out = {"chain": ACTIVE.name, "stake_unit_usd": unit, "crashes": CRASHES, "rows": rows,
           "no_crash_lp_net_m": {d: R[("none", d)]["lp_net_m"] for d in ["today", *DESIGNS]}}
    (I.OUT / "crash.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    o = main()
    print(o["no_crash_lp_net_m"])
    for r in o["rows"]:
        print(r)
