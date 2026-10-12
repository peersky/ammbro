"""Study I: per-gap reverse auction ("ramp") against the final controllers, for retail's price.

Each standing gap's allowance starts at m0 and rises with the gap's age (time since it opened beyond
f + ε or was last corrected) up to a cap; the first profitable corrector takes it at the current level,
so correctors compete on the price they will work for, gap by gap. The objective is the cheapest
price for retail — the lowest all-in cost and the freshest price users trade at — subject to LPs
being at least as well off as today and the pool as rebalanced as today.

Ordering: arrival-ordered chains keep the first-come race among profitable arbitrageurs; auction
chains use the position model (late-fix penalty included). A one-arbitrageur population is run with a
myopic arbitrageur, with one that waits for the cap (the bound on what waiting extracts), and under
the final controller.

Every run charges users' correcting swaps as well as arbitrageurs' (the mechanism charges any
correcting swap); part 'baseline' reruns the final controllers that way for a fair comparison.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_ramp [baseline|main|monopoly|timeboost|robust|steep|fee4] → results/[<chain>/]study_i/ramp_<part>.json
"""
from __future__ import annotations

import json
import sys

from . import study_i as I
from .chains import ACTIVE
from .study_i_position import POS

FEES_BPS = [5.0, 3.0]
RAMPS = {"from 0.5 bp, +1 bp/s": {"m0_bps": 0.5, "slope_bps_per_s": 1.0, "cap_bps": 5.0},
         "from 1 bp, +0.5 bp/s": {"m0_bps": 1.0, "slope_bps_per_s": 0.5, "cap_bps": 5.0}}
CHARGE = {"charge_users": True}   # every correcting swap pays (3b), users included


def chain_settings() -> tuple[str, dict]:
    if ACTIVE.ordering == "fcfs":
        return "ctl_red4", {"fcfs": True, **CHARGE}
    return "ctl_urgm", {"position_model": POS, **CHARGE}


def row(x: dict, t: dict, **kw) -> dict:
    allin = lambda y: round(y["lp_from_users_m"] / max(y["user_volume_b"], 1e-9) / 1e3 * 1e4, 3)
    return {**kw, "lp_net_m": x["lp_net_m"], "today_lp_net_m": t["lp_net_m"],
            "lp_gain_vs_today_m": round(x["lp_net_m"] - t["lp_net_m"], 3),
            "user_all_in_bps": allin(x), "today_user_all_in_bps": allin(t),
            "user_staleness_bps": x["user_pretrade_staleness_bps_vw"], "today_user_staleness_bps": t["user_pretrade_staleness_bps_vw"],
            "lp_from_arbs_m": x["lp_from_arbs_m"], "lp_recapture_m": x["lp_recapture_m"], "arb_margin_m": x["arb_margin_m"],
            "builder_payments_m": x["builder_payments_m"], "arb_volume_b": x["arb_volume_b"], "user_charges_m": x["user_charges_m"],
            "rebalanced_block_share": x["rebalanced_block_share"], "today_rebalanced_block_share": t["rebalanced_block_share"],
            "keeps_rebalanced": I.keeps_rebalanced(x, t), "uncorrected_hours": x["uncorrected_hours"]}


def main(part: str = "main") -> dict:
    ctl, st = chain_settings()
    runs, cfg = [], []
    if part == "baseline":                 # final controllers with users charged, for a fair comparison
        for sc in I.SCENARIOS:
            runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None, None))
            for f in FEES_BPS:
                runs.append(("marginal_cap", ctl, sc, 0.0, "open", False, 0.0, {"stale_rule": "outcome", "pool_fee": f / 1e4, **st}))
                cfg.append((sc, f, ctl))
    elif part == "timeboost":              # express lane: one of three holders wins each minute's corrections
        tb = {"timeboost": {"holders": [0, 1, 2], "round_s": 60.0}}
        for sc in I.SCENARIOS:
            runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None, None))
            for c in ("ctl_red4", "ctl_red3"):
                runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0, {"stale_rule": "outcome", **st, **tb}))
                cfg.append((sc, 5.0, f"{c}, Timeboost"))
    elif part == "robust":                 # strict clock reset, and arbitrageurs demanding a margin above cost
        best = next(iter(RAMPS.values()))
        for sc in I.SCENARIOS:
            runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None, None))
            for margin in (0.0, 0.25, 0.5):
                runs.append(("marginal_cap", 0.0, sc, 0.0, "open", False, margin,
                             {"stale_rule": "outcome", "pool_fee": 3.0 / 1e4, "ramp": {**best, "strict_reset": True}, **st}))
                cfg.append((sc, 3.0, f"strict reset, margin {margin:g} bp"))
    elif part == "steep":                  # a steeper ramp makes a shading margin cheap in time
        steep = {"m0_bps": 0.5, "slope_bps_per_s": 4.0, "cap_bps": 5.0, "strict_reset": True}
        for sc in I.SCENARIOS:
            runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None, None))
            for margin in (0.0, 0.25, 0.5):
                runs.append(("marginal_cap", 0.0, sc, 0.0, "open", False, margin,
                             {"stale_rule": "outcome", "pool_fee": 3.0 / 1e4, "ramp": steep, **st}))
                cfg.append((sc, 3.0, f"+4 bp/s, strict reset, margin {margin:g} bp"))
    elif part == "fee4":                   # one unit below today's fee: sender rules and the ramp with shading
        best = {**next(iter(RAMPS.values())), "strict_reset": True}
        for sc in I.SCENARIOS:
            runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None, None))
            for c in ("ctl_red4", "ctl_red3"):
                runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0, {"stale_rule": "outcome", "pool_fee": 4.0 / 1e4, **st}))
                cfg.append((sc, 4.0, c))
            for margin in (0.0, 0.25):
                runs.append(("marginal_cap", 0.0, sc, 0.0, "open", False, margin,
                             {"stale_rule": "outcome", "pool_fee": 4.0 / 1e4, "ramp": best, **st}))
                cfg.append((sc, 4.0, f"ramp +1 bp/s, strict reset, margin {margin:g} bp"))
    elif part == "main":
        scen = list(I.SCENARIOS)
        for sc in scen:
            runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None, None))
            for f in FEES_BPS:
                for name, r in RAMPS.items():
                    runs.append(("marginal_cap", 0.0, sc, 0.0, "open", False, 0.0,
                                 {"stale_rule": "outcome", "pool_fee": f / 1e4, "ramp": r, **st}))
                    cfg.append((sc, f, name))
    else:
        sc = "pop_monopoly"
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None, None))
        for f in FEES_BPS:
            runs.append(("marginal_cap", 0.0, sc, 0.0, "open", False, 0.0,
                         {"stale_rule": "outcome", "pool_fee": f / 1e4, "ramp": next(iter(RAMPS.values())), **st}))
            cfg.append((sc, f, "ramp"))
            runs.append(("marginal_cap", 0.0, sc, 0.0, "open", False, 0.0,
                         {"stale_rule": "outcome", "pool_fee": f / 1e4, "ramp": {**next(iter(RAMPS.values())), "wait": True}, **st}))
            cfg.append((sc, f, "ramp, waits for cap"))
            runs.append(("marginal_cap", ctl, sc, 0.0, "open", False, 0.0,
                         {"stale_rule": "outcome", "pool_fee": f / 1e4, **st}))
            cfg.append((sc, f, ctl))
    res = I.main(runs, workers=6)
    today = {c[0]: x for c, x in zip(cfg, res) if c[1] is None}
    rows = [row(x, today[c[0]], scenario=c[0], fee_bps=c[1], design=c[2]) for c, x in zip(cfg, res) if c[1] is not None]
    out = {"chain": ACTIVE.name, "part": part, "ramps": RAMPS, "rows": rows}
    (I.OUT / f"ramp_{part}.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in main(sys.argv[1] if len(sys.argv) > 1 else "main")["rows"]:
        print(r["scenario"], r["fee_bps"], r["design"], "LP", r["lp_net_m"], "gain", r["lp_gain_vs_today_m"], "all-in", r["user_all_in_bps"],
              "vs", r["today_user_all_in_bps"], "stale", r["user_staleness_bps"], "vs", r["today_user_staleness_bps"], r["keeps_rebalanced"], r["uncorrected_hours"])
