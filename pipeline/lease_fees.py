"""Lease fees: what REP holders earn by lending REP to arbitrageurs, and what it costs correction (paper §4.7).

REP holders supply S of REP to a lending pool. Each epoch arbitrageurs lease the REP they need
(results/study_i/lease_series.json, hourly epochs, no owned stake), depositing P_int per unit, and pay
a rate per unit per epoch set by utilisation u = min(L / S, 1). Demand beyond S is met by the protocol,
which mints the lease against the deposit at a backstop rate that caps the market rate, the fee going to
the reserve. An arbitrageur's best lease leaves its fee phi * rho / s above f_min, so arbitrage hardly
responds to the rate, and the analysis runs offline on the simulated lease series.

    uv run python -m pipeline.lease_fees → results/lease_fees.json
"""
from __future__ import annotations

import json

import numpy as np

from .config import RESULTS_DIR

HOURS_PER_YEAR = 8760.0
RHO_BPS = 5.0
SUPPLY_M = [0.25, 0.5, 1.0, 2.0]
BACKSTOP_APR = 10.0                     # 1,000% a year: the rate at which the protocol mints leases itself
RATES = {
    "flat 10%": lambda u: 0.10,
    "flat 50%": lambda u: 0.50,
    "flat 200%": lambda u: 2.0,
    "flat 1,000%": lambda u: 10.0,
    "kinked: 5% + 45% * u to u = 0.8, then to 1,000%": lambda u: np.where(u <= 0.8, 0.05 + 0.45 * u / 0.8,
                                                                         0.50 + (BACKSTOP_APR - 0.50) * (u - 0.8) / 0.2),
}


def analyse() -> dict:
    d = json.loads((RESULTS_DIR / "study_i" / "lease_series.json").read_text())
    rows = []
    for sc, v in d["scenarios"].items():
        L = np.array(v["lease_k"]) * 1e3
        years = len(L) / HOURS_PER_YEAR
        vol = v["arb_volume_b"] * 1e9
        for S in SUPPLY_M:
            s = S * 1e6
            lent = np.minimum(L, s); minted = np.maximum(L - s, 0.0)
            u = lent / s
            for name, rate in RATES.items():
                apr = np.broadcast_to(np.asarray(rate(u), dtype=float), u.shape)
                lender = float((apr / HOURS_PER_YEAR * lent).sum())
                backstop = float((BACKSTOP_APR / HOURS_PER_YEAR * minted).sum())
                rows.append({"scenario": sc, "supply_m": S, "rate": name,
                             "lender_income_k": round(lender / 1e3, 1),
                             "lender_yield_annual": round(lender / s / years, 4),
                             "mean_utilisation": round(float(u.mean()), 4),
                             "backstop_hours": int((minted > 0).sum()), "backstop_income_k": round(backstop / 1e3, 1),
                             "arb_cost_bps_of_volume": round((lender + backstop) / vol * 1e4, 4),
                             "max_fee_premium_bps": round(float(max(apr.max(), BACKSTOP_APR if minted.any() else 0.0)) / HOURS_PER_YEAR * RHO_BPS, 5)})
    # supply holders would lend at a flat rate if they require a 10% yearly return on the REP they lend
    eq = []
    for sc, v in d["scenarios"].items():
        L = np.array(v["lease_k"]) * 1e3; years = len(L) / HOURS_PER_YEAR; vol = v["arb_volume_b"] * 1e9
        for apr in (2.0, 5.0, 10.0):
            grid = np.geomspace(1e3, 5e6, 400)
            yld = np.array([apr / HOURS_PER_YEAR * np.minimum(L, s).sum() / s / years for s in grid])
            ok = grid[yld >= 0.10]
            S = float(ok.max()) if ok.size else 0.0
            minted = np.maximum(L - S, 0.0)
            eq.append({"scenario": sc, "rate_apr": apr, "supply_at_10pct_yield_m": round(S / 1e6, 3),
                       "backstop_hours": int((minted > 0).sum()),
                       "arb_cost_bps_of_volume": round(apr / HOURS_PER_YEAR * L.sum() / vol * 1e4, 4)})
    out = {"supply_at_required_yield": eq, "source": "results/study_i/lease_series.json", "backstop_apr": BACKSTOP_APR, "rows": rows}
    (RESULTS_DIR / "lease_fees.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in analyse()["rows"]:
        print(r)
