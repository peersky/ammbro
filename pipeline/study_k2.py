"""Study K2 — keeper market: open race vs designated leader
(docs/settlement-keepers.md §3).

Epochs are K1's real hourly keeper epochs (accounts left to the keeper at
r = 20%), with their real gas cost, for both settlement designs.

Keepers k = 1..K have an off-chain cost c_k per epoch (operations; for zk also
proving) and are online in a given epoch with probability p_k (independent).

Open race. The bounty for an epoch is gas reimbursed × (1+μ) plus β $/min
since the epoch closed. A keeper starts once it is online and the escalating
part covers its off-chain cost. Settling takes T (zk: proving time; on-chain:
one block). The first to finish wins and is paid the bounty at its start time;
every keeper that started before the winner finished has wasted its
off-chain cost (zk: duplicated proving) and, on-chain, a reverted submission
(REVERT_GAS).

Designated leader. Per term (TERM epochs) a second-price reverse auction:
each keeper bids its expected cost per epoch, c_k + (1 − p_k)·SLASH (expected
slashing); the lowest bid wins and is paid the second-lowest bid per epoch on
top of gas × (1+μ). If the leader is offline it is slashed SLASH and the epoch
goes to the open race after DEADLINE minutes.

Reported per chain × design × mechanism: protocol cost (what τ pays),
social cost (protocol cost of real resources: gas + off-chain cost of every
keeper that worked, incl. waste), waste, settlement delay (p50/p95/p99),
slashing collected.

Collusion (analytic, docs §3.1): a leader that delays or omits an account's
entry cannot change the account's charge — charges are fixed by the hook's
record chain and the signed prices, and an omitted account self-settles or
stays locked (§2.3). What a bribe can buy is delay of the LP credit, whose
value at r_LP for one epoch is reported as an upper bound on collusion gain.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .chains import ACTIVE
from .config import RESULTS_DIR
from .study_k import KEEPER_OFFCHAIN_USD, MU, account_choice, keeper_epochs, load

OUT = RESULTS_DIR / "study_k"
R_STAKE = 0.20                       # K1 scenario defining who self-settles
KEEPER_SETS = {   # off-chain cost per epoch (USD) and availability, by design
    "diverse": {"onchain": {"cost": [0.0, 0.005, 0.01, 0.02, 0.05], "p": [0.99, 0.98, 0.95, 0.90, 0.80]},
                "zk": {"cost": [0.02, 0.03, 0.05, 0.10, 0.20], "p": [0.99, 0.98, 0.95, 0.90, 0.80]}},
    # the race's worst case: similar keepers start together and duplicate work
    "homogeneous": {"onchain": {"cost": [0.01] * 5, "p": [0.95] * 5},
                    "zk": {"cost": [0.05] * 5, "p": [0.95] * 5}},
}
BETA_GRID = [0.001, 0.01, 0.1]
SETTLE_MIN = {"onchain": 0.2, "zk": 2.0}   # time to settle once started (on-chain: one block; zk: proving)
BETA = 0.01                          # $/min escalating bounty
REVERT_GAS = 30_000                  # a losing on-chain submission that reverts early
TERM = 168                           # epochs per leader term (one week)
SLASH = 5.0                          # USD slashed per missed epoch
DEADLINE = 15.0                      # minutes before the open race takes over from a missing leader
R_LP = 0.05                          # LP's annual time value, for the collusion bound
SEED = 3


def race(gas_usd: float, usd_gas: float, cost, online, design: str, start_min: float = 0.0, beta: float = BETA, rng=None):
    """One open-race epoch → (paid, social, waste, delay_min)."""
    cost = np.asarray(cost)[online]
    if len(cost) == 0:
        return None
    t_start = start_min + cost / beta                 # when the escalating part covers each keeper's cost
    if rng is not None:                               # reaction jitter, so equal-cost keepers do not tie exactly
        t_start = t_start + rng.random(len(t_start)) * 0.1
    order = np.argsort(t_start)
    t_win_start = t_start[order[0]]
    t_done = t_win_start + SETTLE_MIN[design]
    started = t_start < t_done
    waste = float(cost[started].sum() - cost[order[0]])
    if design == "onchain":
        waste += float((started.sum() - 1) * REVERT_GAS * usd_gas)
    paid = gas_usd * (1 + MU) + beta * t_win_start
    social = gas_usd + float(cost[order[0]]) + waste
    return paid, social, waste, t_done


def simulate(hr: pd.DataFrame, design: str, mechanism: str, rng, keepers: dict, beta: float = BETA) -> dict:
    act = hr[hr["gas"] > 0]
    gas_usd, usd_gas = act["gas_usd"].to_numpy(), act["usd_gas"].to_numpy()
    k = keepers[design]
    cost, p = np.array(k["cost"]), np.array(k["p"])
    online = rng.random((len(act), len(cost))) < p
    paid = np.zeros(len(act)); social = np.zeros(len(act)); waste = np.zeros(len(act)); delay = np.zeros(len(act))
    slashed = 0.0
    if mechanism == "leader":
        bids = cost + (1 - p) * SLASH
    for i in range(len(act)):
        if mechanism == "leader":
            term = i // TERM
            if i % TERM == 0:
                live = np.arange(len(cost))           # all keepers bid at the term's auction
                o = np.argsort(bids[live])
                leader, fee = live[o[0]], bids[live[o[1]]]
            if online[i, leader]:
                paid[i] = gas_usd[i] * (1 + MU) + fee
                social[i] = gas_usd[i] + cost[leader]
                delay[i] = SETTLE_MIN[design]
                continue
            slashed += SLASH
            others = online[i].copy(); others[leader] = False
            r = race(gas_usd[i], usd_gas[i], cost, others, design, start_min=DEADLINE, beta=beta, rng=rng)
        else:
            r = race(gas_usd[i], usd_gas[i], cost, online[i], design, beta=beta, rng=rng)
        if r is None:                                   # nobody online: next epoch's keeper settles both (delay one hour)
            paid[i] = gas_usd[i] * (1 + MU); social[i] = gas_usd[i]; delay[i] = 60.0
            continue
        paid[i], social[i], waste[i], delay[i] = r
    q = lambda s: [round(float(np.percentile(s, x)), 2) for x in (50, 95, 99)]
    return {"epochs": int(len(act)), "protocol_paid_usd": round(float(paid.sum()), 0),
            "social_cost_usd": round(float(social.sum()), 0), "waste_usd": round(float(waste.sum()), 0),
            "gas_usd": round(float(gas_usd.sum()), 0), "slashed_usd": round(slashed, 0),
            "delay_min_p50_p95_p99": q(delay), "delay_min_max": round(float(delay.max()), 1),
            "epochs_late_over_10min": int((delay > 10).sum()),
            "paid_over_social": round(float(paid.sum() / social.sum()), 3)}


def run() -> dict:
    d = load()
    meas = json.loads((RESULTS_DIR / "study_g" / "measured.json").read_text())
    p, f = meas["settlement_layer"], meas["foundry"]
    g = {"self_settle_fixed": p["self_settle_fixed"], "self_settle_per_swap": p["self_settle_per_swap"],
         "epoch_fixed": p["epoch_fixed"], "epoch_per_account": p["epoch_per_account"], "groth16": p["groth16_verify_tx"],
         "reconcile_fixed": f["reconcile_fixed_gas_per_tx"], "reconcile_per_swap": f["reconcile_gas_per_swap"]}
    ch = account_choice(d, g, R_STAKE)
    keeper_accts = set(ch.index[ch["choice"] == "keeper"])
    out = {"chain": ACTIVE.name, "keeper_sets": KEEPER_SETS, "beta_grid": BETA_GRID, "term_epochs": TERM,
           "slash_usd": SLASH, "deadline_min": DEADLINE, "results": {}}
    for design in ("onchain", "zk"):
        hr = keeper_epochs(d, keeper_accts, g, design)
        for kset, keepers in KEEPER_SETS.items():
            for beta in BETA_GRID:
                for mech in ("race", "leader"):
                    out["results"][f"{design}/{kset}/beta{beta:g}/{mech}"] = simulate(
                        hr, design, mech, np.random.default_rng(SEED), keepers, beta)
    hourly_charge = float(d["recapture"].sum()) / d["hour"].nunique()
    out["collusion_bound_usd_per_epoch_delayed"] = round(hourly_charge * R_LP / (365 * 24), 4)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "keeper_market.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    for k, v in res["results"].items():
        print(f"{res['chain']:8s} {k:15s} {v}")
    print("collusion bound per delayed epoch $", res["collusion_bound_usd_per_epoch_delayed"])
