"""Where does ETH/USDC liquidity live in 2026? v3 vs v4 probe.

Study I is calibrated on the v3 0.05% pool, which turned out thin in 2026
($12k per bp). REP-AMM would deploy as a v4 hook, so this measures, over
the backtest window and from the RPC endpoint only:

  - swap count and USDC volume of the four hook-less v4 ETH/USDC pools
    (native ETH / USDC, fee & tick spacing 100/1, 500/10, 3000/60,
    10000/200), the v3 0.05% study pool and the v3 0.30% pool;
  - depth in USD per bp from each swap event's own liquidity and price,
    the same formula for every pool: dUSDC/dln P = L·sqrtP/2 (raw units),
    so 1bp = L·sqrtP·1e-4/2 / 1e6 USD.

Hooked v4 pools have unknown ids (the hook address is part of the id);
a one-hour unfiltered sample of all v4 swaps ranks the busiest pool ids
so any large hooked ETH/USDC pool would show up as an unexplained id.
"""
from __future__ import annotations

import json
import subprocess

import numpy as np
import pandas as pd

from . import rpc
from .config import REPO_ROOT

OUT = REPO_ROOT / "results" / "v4_probe"
PM = "0x000000000004444c5dc75cB358380D2e3dE08A90"
V4_SWAP = "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"
V3_SWAP = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
V4_IDS = {
    "v4 ETH/USDC 0.01%": "0x00b9edc1583bf6ef09ff3a09f6c23ecb57fd7d0bb75625717ec81eed181e22d7",
    "v4 ETH/USDC 0.05%": "0x21c67e77068de97969ba93d4aab21826d33ca12bb9f565d8496e8fda8a82ca27",
    "v4 ETH/USDC 0.30%": "0xdce6394339af00981949f5f3baf27e3610c76326a700af57e4b3e3ae4977f78d",
    "v4 ETH/USDC 1.00%": "0xd934712639fede326a3ff8d2a9c2f73749bac510c23fb33443cea7f3c9aca6f3",
}
V3_POOLS = {
    "v3 USDC/WETH 0.05% (study pool)": "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640",
    "v3 USDC/WETH 0.30%": "0x8ad599c3a0ff1de082011efddc58f1908eb6e6d8",
}
LO, HI = 24558868, 25878704          # backtest window (2026-03-01 .. 2026-08-31)
CHUNK = 5000


def _word(data: str, i: int, signed: bool) -> int:
    v = int(data[2 + 64 * i: 2 + 64 * (i + 1)], 16)
    return v - (1 << 256) if signed and v >= 1 << 255 else v


def _logs(filt: dict) -> list:
    ranges = [(b, min(b + CHUNK - 1, HI)) for b in range(LO, HI + 1, CHUNK)]
    out = []
    for i in range(0, len(ranges), 20):
        res = rpc.batch([("eth_getLogs", [{**filt, "fromBlock": hex(a), "toBlock": hex(b)}]) for a, b in ranges[i:i + 20]])
        for r in res:
            out.extend(r)
    return out


def _frame(logs: list, kind: str) -> pd.DataFrame:
    rows = []
    for l in logs:
        d = l["data"]
        if kind == "v4":      # amount0 (ETH), amount1 (USDC), sqrtP, liquidity, tick, fee
            usdc_raw, sqrtp, liq = _word(d, 1, True), _word(d, 2, False), _word(d, 3, False)
        else:                 # v3 USDC/WETH: amount0 (USDC), amount1 (WETH), sqrtP, liquidity, tick
            usdc_raw, sqrtp, liq = _word(d, 0, True), _word(d, 2, False), _word(d, 3, False)
        rows.append((int(l["blockNumber"], 16), abs(usdc_raw) / 1e6, sqrtp / 2**96, liq))
    return pd.DataFrame(rows, columns=["block", "usdc", "sqrtp_raw", "liq"])


def depth_usd_per_bp(df: pd.DataFrame, kind: str) -> float:
    """USDC per 1bp move of ln price. v4 pool: token1 = USDC, so
    dUSDC = L·d(sqrtP). v3 pool: token0 = USDC, so dUSDC = L·d(1/sqrtP)."""
    if df.empty:
        return float("nan")
    if kind == "v4":
        d = df.liq * df.sqrtp_raw * 1e-4 / 2
    else:
        d = df.liq / df.sqrtp_raw * 1e-4 / 2
    return float(np.median(d) / 1e6)


def run() -> dict:
    out = {"window_blocks": [LO, HI], "pools": {}}
    for name, pid in V4_IDS.items():
        df = _frame(_logs({"address": PM, "topics": [V4_SWAP, pid]}), "v4")
        out["pools"][name] = _summ(df, "v4")
        print(name, out["pools"][name], flush=True)
    for name, addr in V3_POOLS.items():
        df = _frame(_logs({"address": addr, "topics": [V3_SWAP]}), "v3")
        out["pools"][name] = _summ(df, "v3")
        print(name, out["pools"][name], flush=True)

    # one-hour unfiltered sample of all v4 swaps: busiest pool ids
    lo = HI - 300
    res = rpc.call("eth_getLogs", [{"address": PM, "topics": [V4_SWAP], "fromBlock": hex(lo), "toBlock": hex(HI)}])
    ids = pd.Series([l["topics"][1] for l in res]).value_counts()
    known = {v: k for k, v in V4_IDS.items()}
    out["v4_busiest_ids_last_300_blocks"] = [
        {"pool_id": i, "swaps": int(c), "known_as": known.get(i)} for i, c in ids.head(10).items()]
    out["v4_total_swaps_last_300_blocks"] = int(len(res))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=2))
    return out


def _summ(df: pd.DataFrame, kind: str) -> dict:
    if df.empty:
        return {"swaps": 0}
    df = df.assign(month=pd.cut(df.block, bins=[LO, 24781027, 24996374, 25218801, 25433939, 25656296, HI + 1],
                                labels=["03", "04", "05", "06", "07", "08"], right=False))
    return {
        "swaps": int(len(df)), "volume_usd_b": round(float(df.usdc.sum()) / 1e9, 3),
        "volume_by_month_usd_b": {str(k): round(float(v) / 1e9, 3) for k, v in df.groupby("month", observed=True).usdc.sum().items()},
        "depth_usd_per_bp_median": round(depth_usd_per_bp(df, kind), 0),
        "depth_usd_per_bp_last_month": round(depth_usd_per_bp(df[df.block >= 25656296], kind), 0),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
