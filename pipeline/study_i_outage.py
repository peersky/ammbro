"""Keeper liveness under a base-fee spike: the gas tank, and what a settlement pause does to the pool.

Part 1 (gas tank, offline on the real hourly base fees of the study pool, hourly on-chain settlement): the
base fee is multiplied by 100 for H hours from day 90. Swaps during the spike prefund at the spiked fee.
Keepers either settle every epoch anyway, at the next hour's (spiked) fee, or wait until the fee is back
within twice its median of the day before and then settle the backlog. The tank is sized as today, with
the uniform G that keeps it solvent from a one-day seed (results/study_k/gas_tank.json).

Part 2 (simulation): keepers wait, so no epoch settles for H hours: parked REP is not released, coverage
and charges accumulate, and the controller does not move. REP issued only by swaps (initial $1 M,
rebates at theta* = 1 bp, no redemption), charges paid in tokens, hourly epochs, calm and shocks x4.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.study_i_outage → results/study_i/outage.json
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import study_i as I
from . import study_k4 as K
from .chains import ACTIVE
from .config import RESULTS_DIR
from .pools import STUDY_POOL

SPIKE_X = 100.0
HOURS = [6, 24, 72]
START_DAY = 90


def tank() -> list:
    fr, bf_h, eth = K.pools()
    meas = json.loads((RESULTS_DIR / "study_g" / "measured.json").read_text())
    p, f = meas["settlement_layer"], meas["foundry"]
    g = {"onchain_fixed": f["reconcile_fixed_gas_per_tx"], "zk_fixed": p["groth16_verify_tx"] + p["epoch_fixed"],
         "per_account": p["epoch_per_account"], "per_swap": f["reconcile_gas_per_swap"]}
    G = json.loads((K.OUT / "gas_tank.json").read_text())["pools"][STUDY_POOL.name]["onchain/1h/real"]["uniform_G_per_swap"]["G_min_seeded_1day"]
    df = fr[STUDY_POOL.name].copy()
    df["hour"] = df["block_ts"] // 3600
    eth_h = pd.Series({h: eth.get(h // 24, eth.median()) for h in bf_h.index})
    h0 = int(bf_h.index.min() + START_DAY * 24)
    rows = []
    for H in [0] + HOURS:
        bf = bf_h.copy().astype(float)
        spike = (bf.index >= h0) & (bf.index < h0 + H)
        bf[spike] *= SPIKE_X
        d = df.assign(bf=df["hour"].map(bf).fillna(bf.median()) / 1e18)
        t = d.groupby("hour").agg(swaps=("bf", "size"), accts=("tx_from", "nunique"), blocks=("block_number", "nunique"), w=("bf", "sum"))
        t["hour"] = t.index
        gas = K.epoch_gas(t, g, "onchain", with_fixed=True)
        bounty = K.OFFCHAIN_USD["onchain"] / t["hour"].map(eth_h).fillna(eth.median())
        nxt = (bf.shift(-1).fillna(bf.iloc[-1]) / 1e18)
        base = float(bf_h[(bf_h.index >= h0 - 24) & (bf_h.index < h0)].median())
        for policy in ("settle anyway", "wait for the fee"):
            settle_h = t["hour"].copy()
            if policy == "wait for the fee" and H:
                ok = bf.index[(bf.index > h0) & (bf <= 2 * base)]
                resume = int(ok[0]) if len(ok) else int(bf.index[-1])
                settle_h = settle_h.where(~((settle_h >= h0 - 1) & (settle_h < resume)), resume)
            sb = settle_h.map(nxt).fillna(nxt.median())
            cost = gas * sb * (1 + K.MU) + bounty
            inflow = G * t["w"]
            seed = float(cost.iloc[:K.SEED_HOURS].sum())
            bal = seed + (inflow.groupby(t["hour"]).sum().cumsum()) - cost.groupby(settle_h).sum().reindex(t["hour"], fill_value=0).cumsum()
            delay = float((settle_h - t["hour"]).max())
            typical = float(cost.median())
            before = float(bal[bal.index < h0].iloc[-1])
            after = bal[(bal.index >= h0) & (bal.index < h0 + H + 24 * 7)]
            drop = before - float(after.min())
            rows.append({"spike_hours": H, "policy": policy, "balance_before_eth": round(before, 3),
                         "largest_drop_eth": round(drop, 3), "drop_share_of_balance": round(drop / before, 3) if before > 0 else None,
                         "drop_in_typical_epochs": round(drop / typical, 1), "insolvent": bool(bal.min() < 0),
                         "max_settlement_delay_h": delay})
    return rows


def sim() -> list:
    reb = 1.31e6 / 4399.0
    runs, cfg = [], []
    for sc in ("stable", "vol_x4"):
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None))
        for H in [0] + HOURS:
            st = {"stake": 1e6, "alloc": "pooled", "fmax": 500e-4, "stake_epoch_s": 3600.0,
                  "rep_supply": {"launch_usd": 1e6, "rebate_usd_per_h": reb, "burn": False, "router_hold_usd": 34e3}}
            if H:
                st["settle_pause"] = {"start_day": START_DAY, "hours": H}
            runs.append(("marginal_cap", "ctl_feasible", sc, 0.0, "open", False, 0.0, st)); cfg.append((sc, H))
    res = I.main(runs, workers=6)
    today = {c[0]: r for c, r in zip(cfg, res) if c[1] is None}
    base = {c[0]: r for c, r in zip(cfg, res) if c[1] == 0}
    return [{"scenario": c[0], "pause_hours": c[1], "lp_gain_vs_today_m": round(r["lp_net_m"] - today[c[0]]["lp_net_m"], 3),
             "lp_cost_of_pause_m": round(base[c[0]]["lp_net_m"] - r["lp_net_m"], 3),
             "keeps_rebalanced": I.keeps_rebalanced(r, today[c[0]]), "uncorrected_hours": r["uncorrected_hours"],
             "uncorrected_hours_no_pause": base[c[0]]["uncorrected_hours"]}
            for c, r in zip(cfg, res) if c[1] is not None]


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["tank"]:
        out = json.loads((I.OUT / "outage.json").read_text()); out["tank"] = tank()
    else:
        out = {"chain": ACTIVE.name, "spike_x": SPIKE_X, "start_day": START_DAY, "tank": tank(), "simulation": sim()}
    (I.OUT / "outage.json").write_text(json.dumps(out, indent=1))
    for r in out["tank"]:
        print(r)
    for r in out["simulation"]:
        print(r)
