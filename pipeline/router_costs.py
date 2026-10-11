"""S4: what an intermediary pays to quote near f_min (paper §4.8, Appendix G.5). Analytic, no data.

A router holding REP stake r against its volume V per settlement epoch has coverage c = r / (ρ V)
and pays the coverage-curve premium (f_max − f_min) e^{−c} on its volume (2). Holding the stake costs
its cost of capital and REP's price risk, both on (c + 1) ρ V for each epoch of volume. Per unit of volume
over a year, with epochs of length T (in days):

    premium(c) = (f_max − f_min) e^{−c},   holding(c) = (k + d) (c + 1) ρ T / 365,

where k is the annual cost of capital and d the expected annual loss from REP's price. The total is
minimised at c* = ln((f_max − f_min) · 365 / ((k + d) ρ T)). The extra ρ V is the stake parked by
the epoch's own trades (ℓ ≥ ρ, §4.6), conservatively assumed not to count toward coverage until it is
released at settlement. The router's own flow is assumed benign; extraction beyond the allowance is
charged regardless.

    uv run python -m pipeline.router_costs → results/router_costs.json
"""
from __future__ import annotations

import json
import math

from .config import RESULTS_DIR

RHO_BPS = 5.0
F_MIN_BPS = 1.0
F_MAX_BPS = [500.0, 1000.0, 2000.0]
EPOCH_DAYS = {"hourly": 1 / 24, "daily": 1.0}
CAPITAL = 0.10                 # annual cost of capital
REP_LOSS = [0.0, 0.5]          # expected annual fraction of REP value lost to price moves


def costs(fmax: float, epoch: float, k: float, d: float) -> dict:
    span = fmax - F_MIN_BPS
    c = math.log(span * 365 / ((k + d) * RHO_BPS * epoch))
    prem = span * math.exp(-c)
    hold = (k + d) * (c + 1) * RHO_BPS * epoch / 365
    return {"coverage": round(c, 2), "stake_bps_of_epoch_volume": round((c + 1) * RHO_BPS, 1),
            "stake_usd_per_10m_daily": round((c + 1) * RHO_BPS * 1e-4 * 1e7 * epoch),
            "premium_bps": round(prem, 4), "holding_bps": round(hold, 4), "total_bps": round(prem + hold, 4)}


def main() -> dict:
    rows = []
    for fmax in F_MAX_BPS:
        for name, epoch in EPOCH_DAYS.items():
            for d in REP_LOSS:
                rows.append({"f_max_bps": fmax, "epoch": name, "capital": CAPITAL, "rep_loss": d,
                             **costs(fmax, epoch, CAPITAL, d)})
    out = {"rho_bps": RHO_BPS, "f_min_bps": F_MIN_BPS, "rows": rows}
    (RESULTS_DIR / "router_costs.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in main()["rows"]:
        print(r)
