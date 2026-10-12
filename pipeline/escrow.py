"""Escrowed REP backing (paper §4.5, Appendix E): inputs from the simulator, then offline analysis.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.escrow inputs   → results/study_i/escrow_inputs.json
    uv run python -m pipeline.escrow analyse                        → results/escrow.json

`inputs` runs the final mainnet design (urgency by block position, 3 bp, every correcting swap
charged) in the three cost scenarios and keeps its daily series: LPs' net, volume, charges and the
closing oracle price. `analyse` (below) models the escrow on those series.
"""
from __future__ import annotations

import json
import sys

import numpy as np

from .config import REPO_ROOT, RESULTS_DIR


def inputs() -> dict:
    from . import study_i as I
    from .chains import ACTIVE
    from .study_i_position import POS
    st = {"stale_rule": "outcome", "pool_fee": 3.0 / 1e4, "position_model": POS, "charge_users": True}
    runs = [("marginal_cap", "ctl_urgm", sc, 0.0, "open", False, 0.0, dict(st)) for sc in I.SCENARIOS]
    res = I.main(runs, workers=3)
    out = {"chain": ACTIVE.name, "design": "ctl_urgm, 3 bp, users charged",
           "fields": res[0]["daily_series_fields"],
           "series": {sc: r["daily_series"] for sc, r in zip(I.SCENARIOS, res)},
           "lp_net_m": {sc: r["lp_net_m"] for sc, r in zip(I.SCENARIOS, res)}}
    (I.OUT / "escrow_inputs.json").write_text(json.dumps(out))
    return out


TAU = 0.025
THETAS_BPS = [0.5, 1.0, 1.5, 2.0]
LAUNCH_STOCK_M = 0.91      # REP sold at launch to arbitrageurs, at par (§5.5), in \$M


def attack_threshold(f_bps: float, theta_bps: float, v: float) -> float:
    """LP share above which washing at fee f mints REP worth more than it costs, without escrow."""
    return 1 - v * (1 - TAU) * (1 - theta_bps / f_bps)


def simulate(series: list, depth: dict, theta_bps: float, scenario: str, high_water: bool) -> dict:
    """Daily epochs, values in $M at par. scenario: 'none' (surplus stays with LPs, REP unbacked), 'escrow'
    (surplus behind minted REP held idle), 'pol_retain' / 'pol_donate' (escrow held as a full-range position
    in the pool, its earnings retained as backing or donated to LPs). Charges are paid by burning REP, taken
    from overpayers' minted stock first and otherwise bought from the reserve at par (proceeds to the LPs'
    side). With high_water, REP mints only from cumulative income above the cumulative target."""
    th = theta_bps / 1e4
    E = Q = LAUNCH_STOCK_M                                   # launch sale: escrow (or reserve) and REP at par
    lp_assets = reserve = minted = sold = burned = 0.0
    reserve += 0.0 if scenario != "none" else LAUNCH_STOCK_M
    if scenario == "none":
        E = 0.0
    cum = hw = 0.0
    ratio_min, share_max, prev_p = 1.0, 0.0, None
    for day, N, V, C, lnp in series:
        A = N - C                                            # LPs' gain in assets; charges are paid in REP
        if high_water:
            cum += N - th * V
            S = max(cum - hw, 0.0); hw = max(hw, cum)
        else:
            S = max(N - th * V, 0.0)
        M = (1 - TAU) * S
        share = 0.0
        if scenario.startswith("pol"):
            if prev_p is not None and lnp is not None:
                E *= float(np.exp((lnp - prev_p) / 2))       # full-range value moves with sqrt(price)
            D = depth.get(day, np.median(list(depth.values())))
            share = (E / 4) / (D / 1e6 + E / 4)              # escrow's share of the pool's depth
            earn = share * A
            if scenario == "pol_retain":
                E += earn
            else:
                lp_assets += earn
            share_max = max(share_max, share)
        prev_p = lnp if lnp is not None else prev_p
        A *= (1 - share)
        reserve += TAU * S
        Q += M; minted += M
        if scenario == "none":
            lp_assets += A - TAU * S                         # LPs keep the surplus; the REP minted is unbacked
        else:
            lp_assets += A - S                               # surplus behind the REP goes to escrow
            E += M
        if Q < C:                                            # arbitrageurs buy the REP they still need, at par
            buy = C - Q; sold += buy; Q = C
            if scenario == "none":
                reserve += buy
            else:
                E += buy
        Q -= C; burned += C
        if scenario != "none":
            E -= C; lp_assets += C                           # escrow released to LPs (donate) as charges are covered
            ratio_min = min(ratio_min, E / Q) if Q > 1e-9 else ratio_min
    lp_side = lp_assets + reserve + (E if scenario != "none" else 0.0)
    return {"theta_bps": theta_bps, "scenario": scenario, "high_water": high_water,
            "lp_side_value_m": round(lp_side, 3), "rebate_to_overpayers_m": round(minted, 3),
            "rep_sold_m": round(sold, 3), "rep_burned_m": round(burned, 3), "rep_outstanding_end_m": round(Q, 3),
            "unbacked_rep_end_m": round(Q, 3) if scenario == "none" else 0.0,
            "escrow_end_m": round(E, 3) if scenario != "none" else None,
            "backing_ratio_min": round(ratio_min, 3) if scenario != "none" else None,
            "escrow_depth_share_max": round(share_max, 5), "reserve_m": round(reserve, 3)}


def analyse() -> dict:
    import pandas as pd
    inp = json.loads((RESULTS_DIR / "study_i" / "escrow_inputs.json").read_text())
    b = pd.read_parquet(REPO_ROOT / "data" / "onchain" / "sim" / "blocks.parquet", columns=["day", "D"])
    depth = b.groupby("day").D.median().to_dict()
    rows = []
    for sc, ser in inp["series"].items():
        for th in THETAS_BPS:
            for hw in (False, True):
                for scen in ("none", "escrow", "pol_retain", "pol_donate"):
                    rows.append({"cost_scenario": sc, **simulate(ser, depth, th, scen, hw)})
    attack = [{"wash_fee_bps": f, "rep_value": v, "share_threshold": round(attack_threshold(f, 2.0, v), 4)}
              for f in (5.0, 1000.0) for v in (1.0, 0.8, 0.5)]
    out = {"design": inp["design"], "lp_net_simulated_m": inp["lp_net_m"], "tau": TAU, "launch_stock_m": LAUNCH_STOCK_M, "attack_without_escrow": attack,
           "attack_with_escrow": "profit = -tau (f - theta*) V - (1 - s) theta* V < 0 for every share s", "rows": rows}
    (RESULTS_DIR / "escrow.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    {"inputs": inputs, "analyse": analyse}[sys.argv[1]]()
