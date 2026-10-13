"""REP's market without leasing: arbitrageurs buy the REP they need and sell what they do not (paper §4.8).

Hourly, on the simulated no-owned-stake run (results/study_i/lease_series.json): in epoch t arbitrageurs
need L_t of REP staked to trade near f_min, and their charges C_t burn REP at the epoch's end. They start
with the launch sale and buy any shortfall first from holders' float (REP rebated to overpayers, offered
at par), then from the reserve, which mints and sells at (1 + delta) * P_int with P_int to escrow. They
sell any excess to the reserve's bid at (1 - delta) * P_int while the reserve has cash, which it gets
from the take on rebates and the premium on its sales; excess it cannot buy stays with them. Policies:
just in time (hold the epoch's need), or hold the largest need of the past day or week.

Each hour is classified by where the marginal trade cleared: at the reserve's ask (premium), at its bid
(discount), with excess held for later charges because the reserve had no cash to buy it (excess held), or at par.

    uv run python -m pipeline.rep_market → results/rep_market.json
"""
from __future__ import annotations

import json

import numpy as np

from .config import RESULTS_DIR

TAU = 0.025
LAUNCH_M = 0.91
CAPITAL_APR = 0.10
HOURS_PER_YEAR = 8760.0
REBATES_6M = {"theta 2 bp": 0.30, "theta 1 bp": 1.31}     # REP rebated to overpayers over six months (Appendix E)
DELTAS = [0.0025, 0.01]
POLICIES = {"just in time": 1, "hold a day's peak": 24, "hold a week's peak": 168}
MIN_TRADE = 1e3                       # an hour counts as trading at the ask or bid only above this


def simulate(L, C, delta, window, rebate_m):
    n = len(L)
    H, F, cash = LAUNCH_M * 1e6, 0.0, 0.0
    mint_h = rebate_m * 1e6 / n
    sold = bought_back = from_float = uncovered = hold_sum = 0.0
    regime = {"premium": 0, "discount": 0, "excess_held": 0, "par": 0}
    for t in range(n):
        F += mint_h; cash += TAU / (1 - TAU) * mint_h
        target = L[max(0, t - window + 1): t + 1].max()
        r = "par"
        if H < target:
            d = target - H
            f = min(d, F); F -= f; from_float += f; H += f; d -= f
            if d > 0:
                sold += d; cash += delta * d; H += d; r = "premium" if d > MIN_TRADE else r
        elif H > target:
            x = H - target
            b = min(x, cash / (1 - delta))
            if b > 0:
                bought_back += b; cash -= (1 - delta) * b; H -= b; r = "discount" if b > MIN_TRADE else r
            if x - b > MIN_TRADE:
                r = "excess_held" if r == "par" else r
        regime[r] += 1
        hold_sum += H
        burn = min(C[t], H); uncovered += C[t] - burn; H -= burn
    years = n / HOURS_PER_YEAR
    cost = delta * (sold + bought_back) + CAPITAL_APR * hold_sum / HOURS_PER_YEAR
    return {"reserve_sold_m": round(sold / 1e6, 3), "reserve_bought_back_m": round(bought_back / 1e6, 3),
            "bought_from_float_m": round(from_float / 1e6, 3), "reserve_cash_end_k": round(cash / 1e3, 1),
            "mean_holding_m": round(hold_sum / n / 1e6, 3), "charges_uncovered_m": round(uncovered / 1e6, 3),
            "hours_share": {k: round(v / n, 4) for k, v in regime.items()},
            "arb_cost_m": round(cost / 1e6, 4), "_years": years}


def analyse() -> dict:
    d = json.loads((RESULTS_DIR / "study_i" / "lease_series.json").read_text())
    rows = []
    for sc, v in d["scenarios"].items():
        L = np.array(v["lease_k"]) * 1e3; C = np.array(v["charges_k"]) * 1e3; vol = v["arb_volume_b"] * 1e9
        for delta in DELTAS:
            for pol, w in POLICIES.items():
                for rb, rm in REBATES_6M.items():
                    r = simulate(L, C, delta, w, rm)
                    r.pop("_years")
                    rows.append({"scenario": sc, "delta": delta, "policy": pol, "rebates": rb,
                                 "charges_m": round(C.sum() / 1e6, 3), **r,
                                 "arb_cost_bps_of_volume": round(r["arb_cost_m"] * 1e6 / vol * 1e4, 4)})
    out = {"source": "results/study_i/lease_series.json", "tau": TAU, "launch_m": LAUNCH_M, "capital_apr": CAPITAL_APR, "rows": rows}
    (RESULTS_DIR / "rep_market.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in analyse()["rows"]:
        if r["rebates"] == "theta 2 bp":
            print(r["scenario"], r["delta"], r["policy"], "| charges", r["charges_m"], "| sold", r["reserve_sold_m"], "bought back", r["reserve_bought_back_m"],
                  "float", r["bought_from_float_m"], "| hold", r["mean_holding_m"], "| hours", r["hours_share"], "| cost bp", r["arb_cost_bps_of_volume"],
                  "| cash", r["reserve_cash_end_k"])
