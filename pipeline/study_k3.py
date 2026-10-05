"""Study K3 — small pools, bundling, a joint keeper token and the curator
share (docs/settlement-keepers.md §3.2, §4). Mainnet.

Pools: the study pool (ETH/USDC 0.05%) and the census pools (pipeline/census.py),
spanning sizes. Per pool and hour: swaps, distinct accounts, USD volume.
Recapture per pool = volume × RATE (bp of volume), RATE swept around the study
pool's measured rate (Study B objective schedule: $7.10M on $19.59B ≈ 3.6bp);
other pairs' toxicity is not measured here — the band says how much it matters.

Keeper cost per pool-epoch (Study G constants, real hourly base fee):
  on-chain : 3k + 512·blocks + reconcile_fixed + reconcile_per_swap·swaps + epoch_per_account·accounts
  zk       : groth16 + epoch_fixed + epoch_per_account·accounts
Designs compared:
  standalone   each pool settles its own epoch (fixed cost per pool)
  bundled      one transaction / proof per epoch for all pools: the fixed part
               (on-chain: reconcile_fixed; zk: groth16) paid once and split by
               accounts settled
  long epochs  a pool with little flow settles every 6h or 24h instead of 1h
               (fixed cost amortised; stake locked longer — reported)
Funding: per-pool τ needed = keeper cost / recapture. Joint τ (what a protocol
-level keeper token pooling τ across pools would need) = Σ cost / Σ recapture;
the cross-subsidy is what large pools' τ pays for small pools' keepers.

Curator share (analytic): a curator earning share s of a pool's metric is
safe from wash growth iff faking one unit of the metric costs more than s.
  metric = volume      : a wash swap pays the pool fee f per unit → safe iff s_vol < f
  metric = recapture   : a unit of recapture is a charge the trader paid → safe iff s < 1
                         (only extraction beyond the allowance creates it, and
                         the faker pays it in full plus the fee)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .census import OUT as CENSUS, POOLS as CENSUS_POOLS
from .config import ONCHAIN_DIR, RESULTS_DIR
from .pools import STUDY_POOL

OUT = RESULTS_DIR / "study_k"
RATES_BP = [1.0, 3.6, 10.0]
EPOCHS_H = [1, 6, 24]
TAU = 0.025                          # the paper's protocol take
FEE_BY_POOL = {"eth_usdc_005": 5e-4, "usdc_weth_030": 3e-3, "wbtc_weth_005": 5e-4, "link_weth_030": 3e-3,
               "uni_weth_030": 3e-3, "pepe_weth_030": 3e-3, "dai_usdc_001": 1e-4}


def frames() -> dict[str, pd.DataFrame]:
    sc = pd.concat(pd.read_parquet(p, columns=["tx_hash", "block_number", "block_ts", "notional_token0", "base_fee_wei",
                                               "amount0_raw", "amount1_raw"])
                   for p in sorted((ONCHAIN_DIR / "scored" / STUDY_POOL.name).glob("*.parquet")))
    tx = pd.concat(pd.read_parquet(p, columns=["tx_hash", "tx_from"])
                   for p in sorted((ONCHAIN_DIR / "txs" / STUDY_POOL.name).glob("*.parquet"))).drop_duplicates("tx_hash")
    main = sc.merge(tx, on="tx_hash", how="left").rename(columns={"notional_token0": "usd"})
    out = {STUDY_POOL.name: main[["block_number", "block_ts", "tx_from", "usd"]]}
    for pool, _ in CENSUS_POOLS:
        path = CENSUS / f"{pool.name}.parquet"
        if path.exists():
            out[pool.name] = pd.read_parquet(path, columns=["block_number", "block_ts", "tx_from", "usd"])
    # $/gas per hour from the study pool (mainnet base fee × daily ETH price)
    a0 = sc["amount0_raw"].astype(float).abs() / 10**STUDY_POOL.dec0
    a1 = sc["amount1_raw"].astype(float).abs() / 10**STUDY_POOL.dec1
    eth = (a0 / a1).where(a1 > 1e-6).groupby(sc["block_ts"] // 86400).median()
    usd_gas = sc["base_fee_wei"].astype(float) / 1e18 * (sc["block_ts"] // 86400).map(eth).to_numpy()
    out["_usd_gas_h"] = usd_gas.groupby(sc["block_ts"] // 3600).median()
    return out


def epoch_table(df: pd.DataFrame, hours: int) -> pd.DataFrame:
    e = df["block_ts"] // (3600 * hours)
    return df.groupby(e).agg(swaps=("usd", "size"), accts=("tx_from", "nunique"), blocks=("block_number", "nunique"),
                             usd=("usd", "sum"), hour=("block_ts", lambda s: int(s.iloc[0] // 3600)))


def run() -> dict:
    fr = frames()
    usd_gas_h = fr.pop("_usd_gas_h")
    g = json.loads((RESULTS_DIR / "study_g" / "measured.json").read_text())
    p, f = g["settlement_layer"], g["foundry"]
    fixed = {"onchain": f["reconcile_fixed_gas_per_tx"], "zk": p["groth16_verify_tx"] + p["epoch_fixed"]}
    out = {"pools": {}, "joint": {}, "curator": {}, "rates_bp": RATES_BP, "tau": TAU}
    eps = {name: {h: epoch_table(df, h) for h in EPOCHS_H} for name, df in fr.items()}
    for name, df in fr.items():
        hours = df["block_ts"].max() / 3600 - df["block_ts"].min() / 3600
        row = {"swaps": int(len(df)), "volume_usd": round(float(df["usd"].sum()), 0),
               "accounts": int(df["tx_from"].nunique()), "fee": FEE_BY_POOL[name],
               "swaps_per_hour": round(len(df) / hours, 2), "designs": {}}
        for design in ("onchain", "zk"):
            for h in EPOCHS_H:
                t = eps[name][h]
                var = (512 * t["blocks"] + f["reconcile_gas_per_swap"] * t["swaps"] if design == "onchain" else 0) + p["epoch_per_account"] * t["accts"]
                usd = t["hour"].map(usd_gas_h).fillna(usd_gas_h.median()).to_numpy()
                standalone = float(((fixed[design] + 3_000 + var) * usd).sum())
                row["designs"][f"{design}/{h}h"] = {
                    "keeper_cost_standalone_usd": round(standalone, 0),
                    "variable_cost_usd": round(float((var * usd).sum()), 0),
                    "epochs": int(len(t)),
                    "tau_needed_by_rate_bp": {f"{r:g}": round(standalone / (row["volume_usd"] * r / 1e4), 4) for r in RATES_BP},
                }
        out["pools"][name] = row
    # bundling and the joint take: hourly epochs, one fixed cost per hour for all pools
    for design in ("onchain", "zk"):
        hours = sorted(set().union(*[set(eps[n][1]["hour"]) for n in fr]))
        usd = usd_gas_h.reindex(hours).fillna(usd_gas_h.median())
        bundle_fixed = float(((fixed[design] + 3_000) * usd).sum())
        var_total = sum(out["pools"][n]["designs"][f"{design}/1h"]["variable_cost_usd"] for n in fr)
        stand_total = sum(out["pools"][n]["designs"][f"{design}/1h"]["keeper_cost_standalone_usd"] for n in fr)
        vol_total = sum(out["pools"][n]["volume_usd"] for n in fr)
        small = [n for n in fr if n != STUDY_POOL.name]
        # each pool's share when bundled: its own variable cost + the hour's fixed cost split by accounts
        acc = pd.DataFrame({n: eps[n][1].set_index("hour")["accts"] for n in fr}).reindex(hours).fillna(0)
        share = acc.div(acc.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
        fixed_h = (fixed[design] + 3_000) * usd
        for n in fr:
            own = out["pools"][n]["designs"][f"{design}/1h"]["variable_cost_usd"] + float((share[n] * fixed_h).sum())
            out["pools"][n]["designs"][f"{design}/1h"]["keeper_cost_bundled_usd"] = round(own, 0)
            out["pools"][n]["designs"][f"{design}/1h"]["tau_bundled_by_rate_bp"] = {
                f"{r:g}": round(own / (out["pools"][n]["volume_usd"] * r / 1e4), 4) for r in RATES_BP}
        out["joint"][design] = {
            "standalone_total_usd": round(stand_total, 0), "bundled_total_usd": round(bundle_fixed + var_total, 0),
            "bundling_saving": round(1 - (bundle_fixed + var_total) / stand_total, 4),
            "joint_tau_by_rate_bp": {f"{r:g}": round((bundle_fixed + var_total) / (vol_total * r / 1e4), 5) for r in RATES_BP},
            "small_pools_cost_usd": round(sum(out["pools"][n]["designs"][f"{design}/1h"]["keeper_cost_standalone_usd"] for n in small), 0),
            "small_pools_recapture_usd_at_3.6bp": round(sum(out["pools"][n]["volume_usd"] for n in small) * 3.6e-4, 0),
        }
    for name, row in out["pools"].items():
        fee = row["fee"]
        out["curator"][name] = {"fee": fee, "volume_metric_safe_if_share_below": fee,
                                "recapture_metric_safe_if_share_below": 1.0}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "small_pools.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    for name, row in res["pools"].items():
        d = row["designs"]
        print(f"{name:14s} swaps/h {row['swaps_per_hour']:8.1f} vol ${row['volume_usd']/1e6:9.1f}M  "
              + "  ".join(f"{k} tau@3.6bp={v['tau_needed_by_rate_bp']['3.6']:.4f}" for k, v in d.items())
              + "  | bundled 1h tau@3.6bp on/zk "
              + f"{d['onchain/1h']['tau_bundled_by_rate_bp']['3.6']:.4f}/{d['zk/1h']['tau_bundled_by_rate_bp']['3.6']:.4f}")
    print(json.dumps(res["joint"], indent=1))
