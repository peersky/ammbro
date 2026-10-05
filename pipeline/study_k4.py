"""Study K4 — gas-tank solvency (docs/settlement-keepers.md §5).

Every swap prepays settlement gas: withholding = G × block.basefee, in the
chain's gas token. Keepers are paid from the tank at each epoch's close:
settlement gas × the next hour's median base fee × (1+μ), plus an off-chain
bounty (assumed USD per epoch, converted to gas token at the day's ETH price —
an analyst's conversion of an assumed cost, not a mechanism price).

The tank never goes negative iff, for every epoch h,
    G·W_h ≥ C_h,   W_h = Σ_{swaps ≤ h} basefee (ETH per gas unit),
                   C_h = Σ_{epochs ≤ h} keeper payout (ETH)
so the minimum G is max_h C_h / W_h — exact, no search. Reported also: the
break-even G (C_end / W_end) and the cost to swappers as a share of a swap's
own gas.

Settlement designs (Study G constants): on-chain (one signed price batch,
charges computed on-chain) and zk (one Groth16 proof); per-epoch gas =
fixed + per-account writes (+ per-swap charge computation, on-chain).
Tanks: per pool (standalone settlement) or shared across pools (bundled: one
fixed cost per epoch for all pools). Charging: uniform per swap, or
per-account-per-epoch (an account's first swap of the epoch prepays its own
14.3k write ×(1+μ)) plus a per-swap remainder. Epochs: 1h, and 24h for a
pool that prefers daily settlement. Base fee at settlement: the next hour's
median (real); the highest of the next 24h (forced into a spike — pessimistic);
the lowest of the next 24h (a long deadline lets keepers wait for a cheap
block). Solvency from a zero tank and from a tank seeded with the first day's
payouts (launch funding, P§4.8).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .census import OUT as CENSUS, POOLS as CENSUS_POOLS
from .chains import ACTIVE
from .config import ONCHAIN_DIR, RESULTS_DIR
from .pools import STUDY_POOL

OUT = RESULTS_DIR / "study_k"
MU = 0.10
OFFCHAIN_USD = {"onchain": 0.01, "zk": 0.05}
EXEC_GAS = {"mainnet": 188_705, "arbitrum": 136_171}     # Study G1 single-swap tx median


def pools() -> tuple[dict[str, pd.DataFrame], pd.Series, pd.Series]:
    """Swaps per pool (block, ts, account) + hourly median base fee (wei) and daily ETH (USD)."""
    sw = pd.concat(pd.read_parquet(p, columns=["tx_hash", "block_number", "block_ts", "base_fee_wei", "amount0_raw", "amount1_raw"])
                   for p in sorted((ONCHAIN_DIR / "swaps" / STUDY_POOL.name).glob("*.parquet")))
    tx = pd.concat(pd.read_parquet(p, columns=["tx_hash", "tx_from"])
                   for p in sorted((ONCHAIN_DIR / "txs" / STUDY_POOL.name).glob("*.parquet"))).drop_duplicates("tx_hash")
    sw = sw.merge(tx, on="tx_hash", how="left")
    a0 = sw["amount0_raw"].astype(float).abs() / 10**STUDY_POOL.dec0
    a1 = sw["amount1_raw"].astype(float).abs() / 10**STUDY_POOL.dec1
    eth = (a0 / a1).where(a1 > 1e-6).groupby(sw["block_ts"] // 86400).median()
    bf_h = sw.groupby(sw["block_ts"] // 3600)["base_fee_wei"].median()
    out = {STUDY_POOL.name: sw[["block_number", "block_ts", "tx_from"]]}
    if ACTIVE.name == "mainnet":
        for pool, _ in CENSUS_POOLS:
            path = CENSUS / f"{pool.name}.parquet"
            if path.exists():
                out[pool.name] = pd.read_parquet(path, columns=["block_number", "block_ts", "tx_from"])
    return out, bf_h, eth


def epoch_gas(t: pd.DataFrame, g: dict, design: str, with_fixed: bool) -> pd.Series:
    fixed = (g["onchain_fixed"] if design == "onchain" else g["zk_fixed"]) + 3_000
    var = g["per_account"] * t["accts"] + (512 * t["blocks"] + g["per_swap"] * t["swaps"] if design == "onchain" else 0)
    return var + (fixed if with_fixed else 0)


SEED_HOURS = 24


def solve(withhold_w: pd.Series, cost: pd.Series, pre: pd.Series | None = None) -> dict:
    """withhold_w: per epoch Σ basefee (ETH/gas) of its swaps; cost: per epoch payout (ETH);
    pre: per epoch ETH already prepaid by a fixed per-account charge."""
    idx = withhold_w.index.union(cost.index)
    W = withhold_w.reindex(idx, fill_value=0).cumsum()
    C = cost.reindex(idx, fill_value=0).cumsum()
    if pre is not None:
        C = C - pre.reindex(idx, fill_value=0).cumsum()
    g_min = float(max((C / W.replace(0, np.nan)).max(), 0.0))
    seed = float(cost.reindex(idx, fill_value=0).iloc[:SEED_HOURS].sum())     # first day's payouts prefunded
    g_seed = float(max(((C - seed) / W.replace(0, np.nan)).max(), 0.0))
    g_even = float(max(C.iloc[-1] / W.iloc[-1], 0.0))
    return {"G_min_solvent": int(np.ceil(g_min)), "G_min_seeded_1day": int(np.ceil(g_seed)),
            "G_breakeven": int(np.ceil(g_even))}


def run() -> dict:
    fr, bf_h, eth = pools()
    meas = json.loads((RESULTS_DIR / "study_g" / "measured.json").read_text())
    p, f = meas["settlement_layer"], meas["foundry"]
    g = {"onchain_fixed": f["reconcile_fixed_gas_per_tx"], "zk_fixed": p["groth16_verify_tx"] + p["epoch_fixed"],
         "per_account": p["epoch_per_account"], "per_swap": f["reconcile_gas_per_swap"]}
    bf_next = bf_h.shift(-1).fillna(bf_h.iloc[-1]) / 1e18             # ETH per gas at settlement
    bf_spike = bf_h[::-1].rolling(24, min_periods=1).max()[::-1].shift(-1).fillna(bf_h.iloc[-1]) / 1e18
    bf_flex = bf_h[::-1].rolling(24, min_periods=1).min()[::-1].shift(-1).fillna(bf_h.iloc[-1]) / 1e18
    eth_h = pd.Series({h: eth.get(h // 24, eth.median()) for h in bf_h.index})
    out = {"chain": ACTIVE.name, "exec_gas_per_swap": EXEC_GAS[ACTIVE.name], "pools": {}, "shared": {}}
    tabs = {}
    for name, df in fr.items():
        df = df.copy()
        df["hour"] = df["block_ts"] // 3600
        df["bf"] = df["hour"].map(bf_h).fillna(bf_h.median()) / 1e18
        tabs[name] = df
    def epochs(df, hours):
        e = df["hour"] // hours
        t = df.groupby(e).agg(swaps=("bf", "size"), accts=("tx_from", "nunique"), blocks=("block_number", "nunique"),
                              w=("bf", "sum"), hour=("hour", "max"))
        first = df.drop_duplicates(["tx_from", e.name if e.name else "hour"]) if False else None
        acc_bf = df.assign(e=e).drop_duplicates(["tx_from", "e"]).groupby("e")["bf"].sum()   # Σ basefee at each account's first swap
        t["acc_w"] = acc_bf
        return t
    for design in ("onchain", "zk"):
        for hours in (1, 24):
            for name, df in tabs.items():
                t = epochs(df, hours)
                gas = epoch_gas(t, g, design, with_fixed=True)
                for stress, bfs in (("real", bf_next), ("spike24h", bf_spike), ("flex24h", bf_flex)):
                    sb = t["hour"].map(bfs).fillna(bfs.median())
                    bounty = OFFCHAIN_USD[design] / t["hour"].map(eth_h).fillna(eth.median())
                    cost = gas * sb * (1 + MU) + bounty
                    uni = solve(t["w"], cost)
                    pre = t["acc_w"] * g["per_account"] * (1 + MU)          # per-account charge prepays its write
                    split = solve(t["w"], cost, pre)
                    key = f"{design}/{hours}h/{stress}"
                    row = out["pools"].setdefault(name, {})
                    row[key] = {"uniform_G_per_swap": uni, "per_account_charge_gas": int(g["per_account"] * (1 + MU)),
                                "split_G_per_swap": split,
                                "uniform_share_of_swap_gas": round(uni["G_min_solvent"] / EXEC_GAS[ACTIVE.name], 4),
                                "uniform_usd_per_swap_median": round(float(uni["G_min_solvent"] * df["bf"].median() * eth.median()), 5)}
        # shared tank, bundled: one fixed cost per hour for all pools
        if len(tabs) > 1:
          for hours in (1, 24):
            for stress, bfs in (("real", bf_next), ("spike24h", bf_spike), ("flex24h", bf_flex)):
                allt = pd.concat({n: epochs(df, hours) for n, df in tabs.items()}, names=["pool", "e"]).reset_index()
                hourly = allt.groupby("e").agg(accts=("accts", "sum"), swaps=("swaps", "sum"), blocks=("blocks", "sum"),
                                               w=("w", "sum"), acc_w=("acc_w", "sum"), hour=("hour", "max"))
                gas = epoch_gas(hourly, g, design, with_fixed=True)
                sb = hourly["hour"].map(bfs).fillna(bfs.median())
                bounty = OFFCHAIN_USD[design] / hourly["hour"].map(eth_h).fillna(eth.median())
                cost = gas * sb * (1 + MU) + bounty
                uni = solve(hourly["w"], cost)
                split = solve(hourly["w"], cost, hourly["acc_w"] * g["per_account"] * (1 + MU))
                out["shared"][f"{design}/{hours}h/{stress}"] = {
                    "uniform_G_per_swap": uni, "split_G_per_swap": split,
                    "uniform_share_of_swap_gas": round(uni["G_min_solvent"] / EXEC_GAS[ACTIVE.name], 4)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gas_tank.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    for name, row in res["pools"].items():
        for k in ("onchain/1h/real", "zk/1h/real", "zk/24h/real", "zk/24h/flex24h"):
            u = row[k]["uniform_G_per_swap"]
            print(f"{res['chain']:8s} {name:14s} {k:16s} G seeded {u['G_min_seeded_1day']:>7,}  break-even {u['G_breakeven']:>7,}  from-zero {u['G_min_solvent']:>7,}")
    for k, r in res["shared"].items():
        u = r["uniform_G_per_swap"]
        print(f"{res['chain']:8s} SHARED 7 pools  {k:16s} G seeded {u['G_min_seeded_1day']:>7,}  break-even {u['G_breakeven']:>7,}  from-zero {u['G_min_solvent']:>7,}")
