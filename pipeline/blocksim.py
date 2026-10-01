"""Block-level pool simulation inputs (Study I).

Everything is derived from data already on disk — no extra chain fetches:

  blocks     every block in the window. Timestamps for blocks without a
             pool swap are interpolated on the 12s slot grid from the
             ~595k blocks that have one (missed slots inside a gap are
             spread uniformly — a few seconds of error on ~1% of blocks).
             Base fee forward-filled (it moves <= 12.5% per block).
  oracle     ln ETH/USDC mid at block_ts + L (Study E decision latency),
             composed from ETHUSDT / USDCUSDT touch quotes (Study D).
  depth      D = USD notional per unit ln-price move, per UTC day: median
             of V / |Δ ln price| over real swaps that moved the pool >= 3bp
             (tick resolution is 1bp).
  exogenous  the real swaps that are NOT arbitrage — excludes toxic-labeled
             swaps and the block's first price-correcting swap — replayed
             in order with their real notional and direction. The
             simulation's own arbs replace the rest.
"""
from __future__ import annotations

from .normalization import block_time_us

import json

import numpy as np
import pandas as pd

from .config import DATA_DIR, REPO_ROOT, ONCHAIN_DIR, RESULTS_DIR
from .directional import SidedSeries, compose_eth_usdc
from .chains import ACTIVE
from .pools import STUDY_POOL
from .study_e import LABELS_DIR, _frame

CACHE = ONCHAIN_DIR / "sim"


def build() -> dict:
    L = json.loads((RESULTS_DIR / "study_e" / "metrics.json").read_text())["decision_latency_L_s"]
    eth, usdc = SidedSeries.load(STUDY_POOL.bench), SidedSeries.load(STUDY_POOL.numeraire)
    df = _frame(STUDY_POOL)
    labels = pd.concat(pd.read_parquet(p) for p in sorted(LABELS_DIR.glob("*")))
    df = df.merge(labels[["tx_hash", "log_index", "label"]], on=["tx_hash", "log_index"], how="left")
    df = df.sort_values(["block_number", "tx_index", "log_index"]).reset_index(drop=True)

    # --- blocks: interpolate ts on the slot grid, forward-fill base fee ---
    kb = df.drop_duplicates("block_number")[["block_number", "block_ts", "base_fee_wei"]]
    b0, b1 = int(kb.block_number.min()), int(kb.block_number.max())
    num = np.arange(b0, b1 + 1)
    ts = np.interp(num, kb.block_number.to_numpy(), kb.block_ts.to_numpy().astype(float))
    if ACTIVE.slot_s:                      # mainnet: snap to the fixed slot grid
        phase = int(kb.block_ts.iloc[0]) % ACTIVE.slot_s
        ts = (np.round((ts - phase) / ACTIVE.slot_s) * ACTIVE.slot_s + phase).astype(np.int64)
    else:
        ts = np.round(ts).astype(np.int64)
    bf = pd.Series(kb.base_fee_wei.to_numpy(float), index=kb.block_number.to_numpy()).reindex(num).ffill().to_numpy()
    t_us = ts * 1_000_000 + int(round(L * 1e6))
    bid, ask = compose_eth_usdc(eth.quotes(t_us), usdc.quotes(t_us))
    blocks = pd.DataFrame({"block_number": num, "ts": ts, "base_fee_wei": bf, "ln_o": np.log((bid + ask) / 2)})
    blocks["day"] = blocks.ts // 86400

    # --- depth per day ---
    ln_post = (STUDY_POOL.dec1 - STUDY_POOL.dec0) * np.log(10.0) - df["tick"].to_numpy(float) * np.log(1.0001)
    ln_pre = np.r_[np.nan, ln_post[:-1]]
    dln = np.abs(ln_post - ln_pre)
    v = df["notional_token0"].to_numpy()
    ok = (dln >= 3e-4) & (v >= 1e4)
    dd = pd.DataFrame({"day": df["block_ts"].to_numpy()[ok] // 86400, "D": v[ok] / dln[ok]})
    depth = dd.groupby("day")["D"].median()
    blocks["D"] = blocks["day"].map(depth).ffill().bfill()

    # --- exogenous flow ---
    o_at = np.log((lambda b, a: (b + a) / 2)(*compose_eth_usdc(
        eth.quotes(block_time_us(df) + int(round(L * 1e6))),
        usdc.quotes(block_time_us(df) + int(round(L * 1e6))))))
    correcting = (np.abs(ln_post - o_at) - np.abs(ln_pre - o_at)) < 0
    first = df.groupby("block_number").cumcount().to_numpy() == 0
    arb_like = (df["label"].to_numpy() == "toxic") | (first & correcting)
    a1 = df["amount1_raw"].astype(float).to_numpy()
    exo = pd.DataFrame({
        "block_number": df["block_number"].to_numpy()[~arb_like],
        "s": -np.sign(a1[~arb_like]),          # +1 trader buys ETH (pool sends ETH): pool price up
        "v": v[~arb_like],
    })

    CACHE.mkdir(parents=True, exist_ok=True)
    blocks.to_parquet(CACHE / "blocks.parquet", index=False)
    exo.to_parquet(CACHE / "exogenous.parquet", index=False)
    real = {
        "L_s": L, "n_blocks": len(blocks), "blocks_with_pool_swap": int(len(kb)),
        "n_swaps": len(df), "n_exogenous": len(exo), "n_arb_like": int(arb_like.sum()),
        "arb_like_volume_b": round(float(v[arb_like].sum()) / 1e9, 2),
        "exogenous_volume_b": round(float(v[~arb_like].sum()) / 1e9, 2),
        "depth_usd_per_bp_median": round(float(depth.median()) / 1e4, 0),
        "depth_usd_per_bp_p10_p90": [round(float(depth.quantile(.1)) / 1e4, 0), round(float(depth.quantile(.9)) / 1e4, 0)],
        "real_pre_first_swap_gap_bps": {q: round(float(np.nanquantile(np.abs(ln_pre - o_at)[first] * 1e4, p)), 2)
                                        for q, p in (("p50", .5), ("p90", .9), ("p99", .99))},
        "real_lp_markout_m": _real_lp(ln_pre, ln_post, o_at, a1, v, arb_like),
        "real_post_swap_gap_bps_all": {q: round(float(np.nanquantile(np.abs(ln_post - o_at) * 1e4, p)), 2)
                                       for q, p in (("p50", .5), ("p90", .9))},
    }
    (CACHE / "calibration_inputs.json").write_text(json.dumps(real, indent=2))
    return real


POOL_FEE = 0.0005


def _real_lp(ln_pre, ln_post, o, a1, v, arb_like) -> dict:
    """Real LP markout with the simulation's own formula, so the model can
    be calibrated like-for-like: V·(f + s·(avg ln price − ln oracle))."""
    s = -np.sign(a1)
    m = v * (POOL_FEE + s * ((ln_pre + ln_post) / 2 - o))
    ok = ~np.isnan(m)
    return {"total": round(float(m[ok].sum()) / 1e6, 2),
            "arb_like": round(float(m[ok & arb_like].sum()) / 1e6, 2),
            "exogenous": round(float(m[ok & ~arb_like].sum()) / 1e6, 2)}


def load():
    return pd.read_parquet(CACHE / "blocks.parquet"), pd.read_parquet(CACHE / "exogenous.parquet")


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
