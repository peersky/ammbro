"""R3: what carrying retail flow costs a router's stake under the per-unit cap (paper §4.8, Appendix G.5).

Every price-correcting swap (one that moves the pool toward the benchmark) is charged on its edge beyond fee + ε + m (3b),
whoever sends it; a router's REP is therefore at risk exactly when its users happen to trade into a
stale pool. On today's swaps, each swap's edge falls linearly in log price from its pre-trade gap x0
to its post-trade gap x1 (both signed toward the benchmark), so its charge per unit of notional is
the mean of max(x − f − ε − m, 0) over that segment, in closed form. The benchmark is the mid at the
decision instant; the paper scores against the directional bid/ask, which charges less, so these
charges are upper bounds.

Reported by label (retail aggregators as benign, top-of-block repeat searchers as toxic, the rest),
for allowances m of 1, 2 and 3 bp: the share of volume charged, the charge per unit of volume, and
the daily charge per unit of daily volume (median, 99th percentile, worst day).

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.router_risk → results/[<chain>/]router_risk.json
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import study_h as H
from .chains import ACTIVE
from .config import RESULTS_DIR

EPS_BPS = 0.5
FEE_BPS = 5.0                      # pool fee; `python -m pipeline.router_risk 3` writes router_risk_fee3.json
M_BPS = [1.0, 2.0, 3.0]


def charge_per_unit(x0: np.ndarray, x1: np.ndarray, c: float) -> np.ndarray:
    a, b = x0 - c, x1 - c
    out = np.zeros_like(a)
    both = (a > 0) & (b > 0)
    out[both] = (a[both] + b[both]) / 2
    one = (a > 0) & (b <= 0)
    out[one] = a[one] ** 2 / (2 * (a[one] - b[one]))
    return out


def main() -> dict:
    df, L = H.prepare()
    bt = H.block_time_us(df)
    bid, ask = H.eth_quotes(H.SidedSeries.load(H.STUDY_POOL.bench), H.SidedSeries.load(H.STUDY_POOL.numeraire),
                            bt + int(round(L * 1e6)))
    ln_o = np.log((bid + ask) / 2)
    ln_post = (18 - 6) * np.log(10.0) - df["tick"].to_numpy(float) * np.log(1.0001)
    ln_pre = np.r_[np.nan, ln_post[:-1]]
    s = np.sign(ln_o - ln_pre)
    x0, x1 = s * (ln_o - ln_pre) * 1e4, s * (ln_o - ln_post) * 1e4          # signed gaps toward the benchmark, bp
    ok = np.isfinite(x0) & np.isfinite(x1) & df["v"].notna().to_numpy() & (x1 < x0)   # only price-correcting swaps are charged
    lab = df["label"].fillna("other").to_numpy()
    v = df["v"].to_numpy(float)
    day = df["day"].to_numpy()
    out = {"chain": ACTIVE.name, "fee_bps": FEE_BPS, "eps_bps": EPS_BPS, "benchmark": "mid at block_ts + L",
           "by_label": {}}
    for m in M_BPS:
        cpu = np.where(ok, charge_per_unit(x0, x1, FEE_BPS + EPS_BPS + m), 0.0)       # bp of notional
        ch = cpu * 1e-4 * v
        for name in ("benign", "toxic", "other"):
            sel = ok & (lab == name)
            if not sel.any():
                continue
            d = pd.DataFrame({"day": day[sel], "ch": ch[sel], "v": v[sel]}).groupby("day").sum()
            daily = (d["ch"] / d["v"] * 1e4).to_numpy()
            out["by_label"].setdefault(name, {})[f"m_{m:g}bp"] = {
                "volume_b": round(float(v[sel].sum()) / 1e9, 3),
                "share_of_volume_charged": round(float(v[sel & (cpu > 0)].sum() / v[sel].sum()), 4),
                "charge_bps_of_volume": round(float(ch[sel].sum() / v[sel].sum() * 1e4), 4),
                "daily_charge_bps_median": round(float(np.median(daily)), 4),
                "daily_charge_bps_p99": round(float(np.quantile(daily, 0.99)), 4),
                "daily_charge_bps_max": round(float(daily.max()), 4),
                "charge_usd_m": round(float(ch[sel].sum()) / 1e6, 4)}
    p = RESULTS_DIR / ("router_risk.json" if FEE_BPS == 5.0 else f"router_risk_fee{FEE_BPS:g}.json")
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        FEE_BPS = float(sys.argv[1])
    print(json.dumps(main()["by_label"], indent=1))
