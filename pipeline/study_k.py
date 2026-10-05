"""Study K1 — settlement and keeper economics (docs/settlement-keepers.md §2–3).

Real swaps, real accounts, real base fees; gas constants measured in Study G
(G-park). Hourly epochs.

1. Self-settlement choice. Each account picks the cadence c ∈ CADENCES that
   minimises its own cost over the window:
       gas(c)   = Σ settlements × (fixed + per-swap gas) × that hour's $/gas
       stake(c) = ρ × peak volume in one window of length c   (capacity it must hold)
       cost(c)  = gas(c) + r × stake(c) × window length (years)
   "keeper" = never self-settle: the account waits for the hourly keeper and
   holds stake for an hour plus the settlement delay. r — the cost of holding
   REP stake — is unknown (REP is a risky asset), so it is swept.
2. Keeper load. Accounts left to the keeper are settled once per epoch; the
   epoch's gas is either the on-chain design (one signed price batch + charges
   computed on-chain) or the zk design (one Groth16 proof); both write one
   entry per account (Study G settlement_budget).
3. Funding. Keepers are paid from the protocol take τ applied to recapture:
   each swap's charge under Study B's objective schedule on its canonical h0 q.
   A per-pool reserve absorbs quiet hours: reserve_h = reserve_{h−1} + τ·R_h −
   K_h. Reported: break-even τ (Σ K / Σ R) and the τ that keeps the reserve ≥ 0
   from a zero start, at real gas and with a ×10 gas spike scenario.
4. Open-race bounty. Keepers k with off-chain cost c_k per epoch wait until an
   escalating bounty (gas reimbursed × (1+μ) plus β $/min since the epoch
   closed) covers their cost; the cheapest claims first. Reported: settlement
   delay and overpayment vs the cheapest keeper's cost.

HONESTY: accounts are tx senders (a router's users share its sender); one pool
only, so per-account stake is the stake this pool needs; capacity is valued at
a flat rate r; keeper off-chain costs are assumed (GPU time is cents per epoch
for zk, zero for the on-chain design beyond operations).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import canonical
from .chains import ACTIVE
from .config import ONCHAIN_DIR, RESULTS_DIR
from .pools import STUDY_POOL
from .study_b import BASELINE_FEE, OBJECTIVE, fee_rates

OUT = RESULTS_DIR / "study_k"
RHO = 5e-4                          # base parking rate
CADENCES = {"block": None, "1min": 60, "1h": 3600}     # self-settlement windows; "keeper" is the default
R_GRID = [0.05, 0.20, 0.50]         # annual cost of holding REP stake
TAU_GRID = [0.001, 0.0025, 0.005, 0.01, 0.025]
KEEPER_OFFCHAIN_USD = {"onchain": [0.0, 0.01, 0.05], "zk": [0.02, 0.05, 0.20]}   # per epoch, by keeper
MU = 0.10                           # gas reimbursed at (1 + μ)
BETA_USD_PER_MIN = 0.01             # escalating bounty slope
GAS_SPIKE = 10.0
WINDOW_YEARS = 183 / 365


def load() -> pd.DataFrame:
    sc = pd.concat(pd.read_parquet(p) for p in sorted((ONCHAIN_DIR / "scored" / STUDY_POOL.name).glob("*.parquet")))
    sc = canonical.apply(sc)
    tx = pd.concat(pd.read_parquet(p, columns=["tx_hash", "tx_from"])
                   for p in sorted((ONCHAIN_DIR / "txs" / STUDY_POOL.name).glob("*.parquet"))).drop_duplicates("tx_hash")
    d = sc.merge(tx, on="tx_hash", how="left")
    a0 = d["amount0_raw"].astype(float).abs() / 10**STUDY_POOL.dec0
    a1 = d["amount1_raw"].astype(float).abs() / 10**STUDY_POOL.dec1
    d["day"] = d["block_ts"] // 86400
    d["eth"] = d["day"].map((a0 / a1).where(a1 > 1e-6).groupby(d["day"]).median())
    d["usd_gas"] = d["base_fee_wei"].astype(float) / 1e18 * d["eth"]
    d["hour"] = d["block_ts"] // 3600
    q = d["q_lp_h0"].fillna(0.0).to_numpy()
    v = d["notional_token0"].fillna(0.0).to_numpy()
    delta = fee_rates(q, **OBJECTIVE) - BASELINE_FEE
    d["recapture"] = np.where(q < 0, np.maximum(delta, 0.0) * v, 0.0)
    d["v"] = v
    return d


def account_choice(d: pd.DataFrame, g: dict, r: float) -> pd.DataFrame:
    """Per account: cost of each cadence; the chosen one."""
    usd_gas_h = d.groupby("hour")["usd_gas"].median()
    rows = {}
    for name, w in {**CADENCES, "keeper": 3600}.items():
        key = d["block_number"] if w is None else d["block_ts"] // w
        grp = d.groupby(["tx_from", key])
        win = grp.agg(v=("v", "sum"), n=("v", "size"), hour=("hour", "first"))
        peak = win.groupby(level=0)["v"].max() * RHO
        if name == "keeper":
            gas = pd.Series(0.0, index=peak.index)
        else:
            per = (g["self_settle_fixed"] + win["n"] * g["self_settle_per_swap"]) * win["hour"].map(usd_gas_h).to_numpy()
            gas = per.groupby(level=0).sum()
        rows[name] = pd.DataFrame({"gas": gas, "stake": peak, "cost": gas + r * peak * WINDOW_YEARS})
    cost = pd.DataFrame({k: v["cost"] for k, v in rows.items()})
    choice = cost.idxmin(axis=1)
    stake = pd.Series({a: rows[c].at[a, "stake"] for a, c in choice.items()})
    gas = pd.Series({a: rows[c].at[a, "gas"] for a, c in choice.items()})
    return pd.DataFrame({"choice": choice, "stake": stake, "gas": gas, "stake_keeper": rows["keeper"]["stake"]})


def keeper_epochs(d: pd.DataFrame, keeper_accts: set, g: dict, design: str) -> pd.DataFrame:
    k = d[d["tx_from"].isin(keeper_accts)]
    hr = d.groupby("hour").agg(recapture=("recapture", "sum"), usd_gas=("usd_gas", "median"),
                               blocks=("block_number", "nunique"))
    kh = k.groupby("hour").agg(accts=("tx_from", "nunique"), swaps=("v", "size"))
    hr = hr.join(kh, how="left").fillna({"accts": 0, "swaps": 0})
    if design == "onchain":
        gas = 3_000 + 16 * 32 * hr["blocks"] + g["reconcile_fixed"] + hr["swaps"] * g["reconcile_per_swap"] + hr["accts"] * g["epoch_per_account"]
    else:
        gas = g["groth16"] + g["epoch_fixed"] + hr["accts"] * g["epoch_per_account"]
    hr["gas"] = np.where(hr["accts"] > 0, gas, 0.0)
    hr["gas_usd"] = hr["gas"] * hr["usd_gas"]
    return hr


def funding(hr: pd.DataFrame, offchain_usd: float, spike: float = 1.0) -> dict:
    cost = hr["gas_usd"] * spike * (1 + MU) + np.where(hr["gas"] > 0, offchain_usd, 0.0)
    R = hr["recapture"].to_numpy()
    out = {"keeper_cost_usd": round(float(cost.sum()), 0), "recapture_usd": round(float(R.sum()), 0),
           "breakeven_tau": round(float(cost.sum() / R.sum()), 5) if R.sum() else None}
    for tau in TAU_GRID:
        res = np.cumsum(tau * R - cost.to_numpy())
        out[f"tau_{tau:g}"] = {"reserve_min_usd": round(float(res.min()), 0), "reserve_end_usd": round(float(res[-1]), 0),
                               "hours_negative": int((res < 0).sum())}
    return out


def bounty(hr: pd.DataFrame, offchain: list[float]) -> dict:
    """Open race: cheapest keeper claims once gas×(1+μ) + β·minutes ≥ its cost."""
    act = hr[hr["gas"] > 0]
    c_min = min(offchain)
    minutes = np.full(len(act), c_min / BETA_USD_PER_MIN)          # gas is reimbursed, so only the off-chain cost waits
    paid = act["gas_usd"].to_numpy() * (1 + MU) + BETA_USD_PER_MIN * minutes
    floor = act["gas_usd"].to_numpy() + c_min
    return {"settlement_delay_min": round(float(np.median(minutes)), 1),
            "overpay_vs_cheapest_cost": round(float(paid.sum() / floor.sum() - 1), 4)}


def run() -> dict:
    d = load()
    meas = json.loads((RESULTS_DIR / "study_g" / "measured.json").read_text())
    p = meas["settlement_layer"]
    f = meas["foundry"]
    g = {"self_settle_fixed": p["self_settle_fixed"], "self_settle_per_swap": p["self_settle_per_swap"],
         "epoch_fixed": p["epoch_fixed"], "epoch_per_account": p["epoch_per_account"], "groth16": p["groth16_verify_tx"],
         "reconcile_fixed": f["reconcile_fixed_gas_per_tx"], "reconcile_per_swap": f["reconcile_gas_per_swap"]}
    out = {"chain": ACTIVE.name, "gas": g, "rho": RHO, "accounts": int(d["tx_from"].nunique()),
           "volume_usd": round(float(d["v"].sum()), 0), "recapture_usd": round(float(d["recapture"].sum()), 0),
           "by_r": {}}
    vol = d.groupby("tx_from")["v"].sum()
    for r in R_GRID:
        ch = account_choice(d, g, r)
        keeper_accts = set(ch.index[ch["choice"] == "keeper"])
        res = {"choice_share_accounts": ch["choice"].value_counts(normalize=True).round(4).to_dict(),
               "choice_share_volume": (vol.groupby(ch["choice"]).sum() / vol.sum()).round(4).to_dict(),
               "stake_needed_usd": round(float(ch["stake"].sum()), 0),
               "stake_if_all_keeper_usd": round(float(ch["stake_keeper"].sum()), 0),
               "self_settle_gas_usd": round(float(ch["gas"].sum()), 0), "designs": {}}
        for design in ("onchain", "zk"):
            hr = keeper_epochs(d, keeper_accts, g, design)
            q = lambda s: [round(float(np.percentile(s, x)), 3) for x in (50, 95, 99)]
            act = hr[hr["gas"] > 0]
            res["designs"][design] = {
                "epoch_gas_p50_p95_p99": q(act["gas"]), "epoch_usd_p50_p95_p99": q(act["gas_usd"]),
                "accounts_per_epoch_p50_p95_p99": q(act["accts"]),
                "funding_real_gas": {f"offchain_{c:g}usd": funding(hr, c) for c in KEEPER_OFFCHAIN_USD[design]},
                "funding_gas_x10": funding(hr, max(KEEPER_OFFCHAIN_USD[design]), GAS_SPIKE),
                "open_race": bounty(hr, KEEPER_OFFCHAIN_USD[design]),
            }
        out["by_r"][f"{r:g}"] = res
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    print(json.dumps({k: res[k] for k in ("chain", "accounts", "volume_usd", "recapture_usd")}))
    for r, x in res["by_r"].items():
        print(f"r={r}: accounts {x['choice_share_accounts']}  volume {x['choice_share_volume']}  "
              f"stake ${x['stake_needed_usd']:,.0f} (all-keeper ${x['stake_if_all_keeper_usd']:,.0f})  self-gas ${x['self_settle_gas_usd']:,.0f}")
        for dn, y in x["designs"].items():
            fr = y["funding_real_gas"]
            first = next(iter(fr.values()))
            print(f"   {dn}: epoch $ p50/95/99 {y['epoch_usd_p50_p95_p99']}  breakeven tau {first['breakeven_tau']}  "
                  f"x10 gas breakeven {y['funding_gas_x10']['breakeven_tau']}  race {y['open_race']}")
