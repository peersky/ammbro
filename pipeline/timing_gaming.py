"""Position-gaming tests for Study E (spec: design objective, condition 1).

Can a transactor buy a more lenient benchmark by choosing where its swap
lands? Committed port of the 2026-09-30 analyses the spec cites:

  orientation   block-index time planes (paper orientation on the current
                and arrival-aligned windows, reversed) vs a single anchor
  pool clocks   pool-internal clocks (swap count, volume, opposite-
                direction volume), honest scoring and the cheapest attack
                on each: own dust swaps, self-splitting, a round trip
  post-distance the alternative metric "did the swap move the pool away
                from the oracle" — shown inverted (price correction IS
                arbitrage)

All scores: arb_exit q_LP, point read, h0. Attacks are static what-ifs
on gap-takers (toxic, pool-first); costs are fee + base-fee gas only, so
"profitable" is a lower bound on attack cost.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .study_a import mann_whitney_auc
from .study_b import base_fee_gas_usd

DUST_GAS_UNITS = 130_000


def run_gaming(df: pd.DataFrame, lab: np.ndarray, a0, a1, v, L: float, price) -> dict:
    """df/lab/a0/a1/v aligned; price(t_us) -> (bid, ask)."""
    from .study_e import q_at

    o = np.lexsort((df["log_index"].to_numpy(), df["tx_index"].to_numpy(), df["block_number"].to_numpy()))
    d = df.iloc[o].reset_index(drop=True)
    lab, a0, a1, v = lab[o], a0[o], a1[o], v[o]
    bt = d["block_ts"].to_numpy(np.int64) * 1_000_000
    T = d["dur_s"].to_numpy(); frac = d["frac"].to_numpy(); idx = d["tx_index"].to_numpy()
    g = d.groupby("block_number")
    k = g.cumcount().to_numpy(); K = g["tx_index"].transform("size").to_numpy()
    cumv = (g["notional_token0"].cumsum() - d["notional_token0"]).to_numpy()
    totv = g["notional_token0"].transform("sum").to_numpy()
    tox, ben = lab == "toxic", lab == "benign"
    Lus = int(round(L * 1e6))

    def us(sec):
        return (np.asarray(sec) * 1e6).astype(np.int64)

    def score(t):
        q = q_at(a0, a1, *price(t)); ok = ~np.isnan(q)
        return {"auc": round(mann_whitney_auc(-q[ok & tox], -q[ok & ben]), 4),
                "baseline_net_lp_m": round(float((q[ok] * v[ok]).sum()) / 1e6, 2)}

    out: dict = {"L_s": L}

    # --- orientation of a block-index time plane ---
    planes = {
        "paper_orientation_arrival_window: bt+L-T+frac*T": bt + us(L - T + frac * T),
        "paper_orientation_current_window: bt+frac*T": bt + us(frac * T),
        "reversed: bt+L-frac*T": bt + us(L - frac * T),
        "single_anchor: bt+L": bt + Lus,
    }
    out["orientation"] = {name: score(t) for name, t in planes.items()}
    top = tox & (idx < 3)
    tops = {}
    for name, off in [("idx0 at bt+L-T (paper orientation, arrival window)", L - T[top]),
                      ("idx0 at bt (paper orientation, current window)", np.zeros(top.sum())),
                      ("idx0 at bt+L (reversed / anchor)", np.full(top.sum(), L))]:
        q = q_at(a0[top], a1[top], *price(bt[top] + us(off))); ok = ~np.isnan(q); qq, w = q[ok], v[top][ok]
        tops[name] = {"toxic_top3_lp_negative": round(float((qq < 0).mean()), 4),
                      "extraction_m": round(float(-(qq[qq < 0] * w[qq < 0]).sum()) / 1e6, 2),
                      "net_markout_m": round(float((qq * w).sum()) / 1e6, 2)}
    out["orientation_toxic_top3"] = tops

    # --- pool-internal clocks, honest ---
    sgn = np.sign(a1)
    vb = np.where(sgn > 0, v, 0.0); vs = np.where(sgn < 0, v, 0.0)
    cb = pd.Series(vb).groupby(d["block_number"].to_numpy()).cumsum().to_numpy() - vb
    cs = pd.Series(vs).groupby(d["block_number"].to_numpy()).cumsum().to_numpy() - vs
    opp = np.where(sgn > 0, cs, cb)
    clocks = {
        "pool_count: bt+L-(k/K)T": bt + us(L - T * k / K),
        "pool_volume: bt+L-(cumV/V)T": bt + us(L - T * cumv / totv),
        "opposite_volume: bt+L-(oppV/V)T": bt + us(L - T * opp / totv),
    }
    out["pool_clocks_honest"] = {name: score(t) for name, t in clocks.items()}
    out["pool_structure"] = {
        "share_swaps_in_blocks_with_2plus_pool_swaps": round(float((K >= 2).mean()), 4),
        "toxic_share_pool_first": round(float((tox & (k == 0)).sum() / tox.sum()), 4),
    }

    # --- attacks on gap-takers (toxic, pool-first) ---
    m = tox & (k == 0)
    vm, Tm, Km, tm = v[m], T[m], K[m], totv[m]

    def extraction(off_s, share=1.0):
        q = q_at(a0[m], a1[m], *price(bt[m] + us(off_s)))
        return float(np.nansum(np.where(q < 0, -q * vm * share, 0.0)))

    base = extraction(np.full(m.sum(), L))
    att = {"n_gap_takers": int(m.sum()), "extraction_at_anchor_m": round(base / 1e6, 2)}
    for dust in (1, 3, 10):
        e = extraction(L - Tm * dust / (Km + dust))
        att[f"count_clock_{dust}_dust_forgiven"] = round(1 - e / base, 3)
    e_split = extraction(np.full(m.sum(), L), 0.5) + extraction(L - Tm * 0.5 * vm / tm, 0.5)
    att["volume_clock_self_split_forgiven"] = round(1 - e_split / base, 3)
    rt = []
    for xr in (0.25, 1.0, 4.0):
        X = xr * vm
        gain = base - extraction(L - Tm * X / (X + tm))
        for fee_bp in (1, 5):
            cost = 2 * fee_bp / 1e4 * X.sum()
            rt.append({"x_over_arb": xr, "fee_bps": fee_bp, "forgiven_m": round(gain / 1e6, 2),
                       "round_trip_fee_cost_m": round(cost / 1e6, 2), "profitable": bool(gain > cost)})
    att["opposite_volume_round_trip"] = rt
    dust_gas = base_fee_gas_usd(d[m]) * DUST_GAS_UNITS / 250_000
    att["dust_swap_cost_usd"] = {"median": round(float(np.nanmedian(dust_gas)), 3),
                                 "p90": round(float(np.nanpercentile(dust_gas, 90)), 3)}
    att["mean_forgiven_per_gap_taker_1_dust_usd"] = round(
        (base - extraction(L - Tm / (Km + 1))) / m.sum(), 2)
    out["attacks"] = att

    # --- alternative metric: distance of the pool from the oracle ---
    ln_post = (18 - 6) * np.log(10.0) - d["tick"].to_numpy(float) * np.log(1.0001)
    ln_pre = np.r_[np.nan, ln_post[:-1]]

    def auc(score_arr):
        ok = ~np.isnan(score_arr)
        return round(mann_whitney_auc(score_arr[ok & tox], score_arr[ok & ben]), 4)

    pd_rows = {}
    for name, off in [("bt+L-10.5s", L - 10.5), ("block_ts", 0.0), ("bt+L", L)]:
        bid, ask = price(bt + us(off))
        ln_o = np.log((bid + ask) / 2)
        q = q_at(a0, a1, bid, ask)
        d_post = np.abs(ln_post - ln_o) * 1e4
        dd = d_post - np.abs(ln_pre - ln_o) * 1e4
        pd_rows[name] = {"auc_markout": auc(-q), "auc_post_distance": auc(d_post), "auc_moved_away": auc(dd),
                         "toxic_moved_toward": round(float(np.nanmean(dd[tox] < 0)), 4),
                         "benign_moved_toward": round(float(np.nanmean(dd[ben] < 0)), 4)}
    out["post_distance_metric"] = pd_rows
    return out
