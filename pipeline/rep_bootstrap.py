"""Bootstrapping REP under constant demand: pre-mint, vesting and prepayment (paper §4.7–4.8).

REP is issued only by swaps — rebates to overpayers and arbitrageurs' declared prepayments, minted at
P_int / (1 - tau_p) with P_int to escrow — plus a pre-mint at launch. Hourly, on the simulated run with
no owned arbitrage stake (results/study_i/lease_series.json): arbitrageurs must hold the epoch's bond L_t
plus the REP its charges C_t will burn; they buy any shortfall from the float (vested pre-mint, rebates
not needed by routers) at the prepayment price, which caps the market, and prepay for the rest.

Pre-mint designs: sold to arbitrageurs at launch at P_int (backed); held by the reserve and released
linearly over six months, sold at the market price with P_int to escrow (backed); granted to a team and
vesting over six months, sold without backing. Burns are drawn pro rata from backed and unbacked REP; an
unbacked unit burned for a charge releases no escrow, so its charge is lost to LPs.

    uv run python -m pipeline.rep_bootstrap → results/rep_bootstrap.json
"""
from __future__ import annotations

import json

import numpy as np

from .config import RESULTS_DIR

HOURS = 4399
PREMINT_M = [0.0, 1.0, 5.0, 20.0]
DESIGNS = ["sold at launch", "reserve, vested", "granted, vested"]
TAUS_P = [0.0, 0.01]
REBATE_M = 0.30                       # rebates minted to overpayers over six months, theta* = 2 bp (Appendix E)
ROUTER_BOND_M = 0.034                 # routers' own bond: 0.75% of hourly retail volume, held, not burned


def simulate(L, C, premint, design, tau_p):
    n = len(L)
    price = 1.0 / (1 - tau_p)                       # the prepayment price caps the market; demand is constant
    H = premint * 1e6 if design == "sold at launch" else 0.0
    locked = 0.0 if design == "sold at launch" else premint * 1e6
    release_h = locked / n
    backed = H; unbacked = 0.0                       # outstanding REP by backing
    float_ = 0.0; router_need = ROUTER_BOND_M * 1e6
    prepaid = from_float = vest_revenue = reserve_rev = lp_loss = 0.0
    exhausted_h = None
    for t in range(n):
        rel = min(release_h, locked); locked -= rel
        if design == "granted, vested":
            unbacked += rel
        else:
            backed += rel
        float_ += rel
        reb = REBATE_M * 1e6 / n; backed += reb
        if router_need > 0:                           # routers keep their bond first, then sell rebates on
            k = min(reb, router_need); router_need -= k; reb -= k
        float_ += reb
        need = L[t] + C[t]
        if H < need:
            d = need - H
            f = min(d, float_); float_ -= f; from_float += f; H += f; d -= f
            if design != "sold at launch" and premint > 0:
                vest_revenue += f * (price - (0.0 if design == "granted, vested" else 1.0))
            if d > 0:
                prepaid += d; reserve_rev += d * (price - 1.0); backed += d; H += d
                if exhausted_h is None and premint > 0 and locked <= 0 and float_ <= 0:
                    exhausted_h = t
        burn = min(C[t], H); H -= burn
        tot = backed + unbacked
        ub = burn * (unbacked / tot) if tot > 0 else 0.0
        unbacked -= ub; backed -= burn - ub; lp_loss += ub
    return {"prepaid_m": round(prepaid / 1e6, 3), "bought_from_float_m": round(from_float / 1e6, 3),
            "tau_paid_m": round(reserve_rev / 1e6, 3), "vesting_revenue_above_backing_m": round(vest_revenue / 1e6, 3),
            "lp_loss_unbacked_m": round(lp_loss / 1e6, 3), "pre_mint_left_m": round((locked + float_) / 1e6, 3),
            "pre_mint_exhausted_day": None if exhausted_h is None else round(exhausted_h / 24, 1),
            "unbacked_outstanding_end_m": round(unbacked / 1e6, 3)}


def analyse() -> dict:
    d = json.loads((RESULTS_DIR / "study_i" / "lease_series.json").read_text())
    rows = []
    for sc, v in d["scenarios"].items():
        L = np.array(v["lease_k"]) * 1e3; C = np.array(v["charges_k"]) * 1e3
        for tau_p in TAUS_P:
            for premint in PREMINT_M:
                for design in (DESIGNS if premint > 0 else ["sold at launch"]):
                    rows.append({"scenario": sc, "tau_prepay": tau_p, "pre_mint_m": premint, "design": design,
                                 "charges_m": round(float(C.sum()) / 1e6, 3), "bond_peak_m": round(float(L.max()) / 1e6, 3),
                                 **simulate(L, C, premint, design, tau_p)})
    out = {"source": "results/study_i/lease_series.json", "rebate_m": REBATE_M, "router_bond_m": ROUTER_BOND_M, "rows": rows}
    (RESULTS_DIR / "rep_bootstrap.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in analyse()["rows"]:
        if r["scenario"] in ("stable", "vol_x4"):
            print(r)
