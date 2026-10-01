"""High-volume L2 pools: gas constraints for a REP-AMM hook (Study G input).

Mainnet ETH/USDC is a light load (median 1 swap per block with a swap).
This samples the main WETH/USDC v3 pools on Base and Arbitrum and the
busiest WHYPE/USDC v3 pool on HyperEVM (found by ranking all v3-style Swap
events over the latest hour), over the latest hour. Endpoints come from .env
(ARB_RPC_URL, HYPEREVM_RPC_URL — URLs embed auth keys) with Base on its
public endpoint:

  - block time, swaps per block / per hour, USDC volume per hour
  - depth in USD per bp from swap-event liquidity (same formula as v4_probe)
  - gas per swap transaction and its price: L2 execution gas, effective gas
    price, and the L1 data component (OP-stack `l1Fee`; Arbitrum
    `gasUsedForL1`), on a sample of swap receipts
  - block gas used, the block gas-limit mix (HyperEVM runs ~1s small blocks
    at 3M gas plus ~1/min big blocks at 30M), and the pool's share of gas

Pools are confirmed on-chain (factory.getPool / token symbols) before use.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import requests

from .config import REPO_ROOT


def _env(key: str, default: str | None = None) -> str:
    v = os.environ.get(key)
    if not v and (REPO_ROOT / ".env").exists():
        for line in (REPO_ROOT / ".env").read_text().splitlines():
            if line.startswith(key + "="):
                v = line.split("=", 1)[1].strip()
    if not v and default is None:
        raise RuntimeError(f"{key} not set (.env)")
    return v or default

OUT = REPO_ROOT / "results" / "l2_probe"
V3_SWAP = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
CHAINS = {
    "base": {"rpc": "https://mainnet.base.org", "block_s": 2.0, "chunk": 500,
             "pools": {"v3 WETH/USDC 0.05%": "0xd0b53D9277642d899DF5C87A3966A349A798F224",
                       "v3 WETH/USDC 0.01%": "0xb4CB800910B228ED3d0834cF79D697127BBB00e5",
                       "v3 WETH/USDC 0.30%": "0x6c561B446416E1A00E8E93E221854d6eA4171372"}},
    "arbitrum": {"rpc_env": "ARB_RPC_URL", "block_s": 0.25, "chunk": 2000,
                 "pools": {"v3 WETH/USDC 0.05%": "0xC6962004f452bE9203591991D15f6b388e09E8D0"}},
    "hyperevm": {"rpc_env": "HYPEREVM_RPC_URL", "block_s": 1.0, "chunk": 1000,
                 "pools": {"v3 WHYPE/USDC (busiest)": "0x6c9a33e3b592c0d65b3ba59355d5be0d38259285"}},
}
SESSION = requests.Session()


def call(rpc: str, method: str, params: list, retries: int = 6):
    for k in range(retries):
        try:
            r = SESSION.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=60).json()
            if "error" in r:
                raise RuntimeError(r["error"])
            return r["result"]
        except Exception as e:
            if k == retries - 1:
                raise
            time.sleep(1.5 * (k + 1))


def word(d: str, i: int, signed: bool) -> int:
    v = int(d[2 + 64 * i: 2 + 64 * (i + 1)], 16)
    return v - (1 << 256) if signed and v >= 1 << 255 else v


def probe_chain(name: str, cfg: dict, hours: float = 1.0) -> dict:
    rpc = cfg.get("rpc") or _env(cfg["rpc_env"])
    head = int(call(rpc, "eth_blockNumber", []), 16)
    n_blocks = int(hours * 3600 / cfg["block_s"])
    lo = head - n_blocks
    t_lo = int(call(rpc, "eth_getBlockByNumber", [hex(lo), False])["timestamp"], 16)
    t_hi = int(call(rpc, "eth_getBlockByNumber", [hex(head), False])["timestamp"], 16)
    out = {"head_block": head, "blocks_sampled": n_blocks, "seconds": t_hi - t_lo,
           "measured_block_time_s": round((t_hi - t_lo) / n_blocks, 3), "pools": {}}
    for pname, addr in cfg["pools"].items():
        logs = []
        for a in range(lo, head + 1, cfg["chunk"]):
            logs += call(rpc, "eth_getLogs", [{"address": addr, "topics": [V3_SWAP],
                                               "fromBlock": hex(a), "toBlock": hex(min(a + cfg["chunk"] - 1, head))}])
            time.sleep(0.2)
        if not logs:
            out["pools"][pname] = {"swaps": 0}
            continue
        blocks = np.array([int(l["blockNumber"], 16) for l in logs])
        usdc = np.array([abs(word(l["data"], 1, True)) / 1e6 for l in logs])            # token1 = USDC
        sqrtp = np.array([word(l["data"], 2, False) / 2**96 for l in logs])
        liq = np.array([word(l["data"], 3, False) for l in logs], dtype=float)
        _, per_block = np.unique(blocks, return_counts=True)
        hours_s = (t_hi - t_lo) / 3600
        # receipts: gas and fees on a sample of distinct swap transactions
        txs = list(dict.fromkeys(l["transactionHash"] for l in logs))
        sample = txs[:: max(1, len(txs) // 60)][:60]
        gas, price, l1fee_eth, l1gas = [], [], [], []
        for h in sample:
            rc = call(rpc, "eth_getTransactionReceipt", [h]); time.sleep(0.1)
            gas.append(int(rc["gasUsed"], 16)); price.append(int(rc["effectiveGasPrice"], 16))
            if "l1Fee" in rc and rc["l1Fee"]:
                l1fee_eth.append(int(rc["l1Fee"], 16) / 1e18)
            if "gasUsedForL1" in rc and rc["gasUsedForL1"]:
                l1gas.append(int(rc["gasUsedForL1"], 16))
        eth_usd = float(np.median((sqrtp ** 2) * 1e12))     # USDC per token0 (WETH / WHYPE, 18 decimals)
        gas, price = np.array(gas), np.array(price)
        exec_cost_usd = gas * price / 1e18 * eth_usd
        # block gas: sample blocks that contain a pool swap
        bsample = list(dict.fromkeys(blocks.tolist()))[:: max(1, len(set(blocks)) // 30)][:30]
        bgas, blim, lims = [], [], {}
        for b in bsample:
            blk = call(rpc, "eth_getBlockByNumber", [hex(b), False]); time.sleep(0.1)
            bgas.append(int(blk["gasUsed"], 16)); blim.append(int(blk["gasLimit"], 16))
            lims[int(blk["gasLimit"], 16)] = lims.get(int(blk["gasLimit"], 16), 0) + 1
        out["pools"][pname] = {
            "swaps": len(logs), "swaps_per_hour": round(len(logs) / hours_s, 0),
            "share_of_blocks_with_a_swap": round(len(per_block) / n_blocks, 4),
            "swaps_per_active_block": {"p50": float(np.median(per_block)), "p99": float(np.percentile(per_block, 99)),
                                       "max": int(per_block.max())},
            "volume_usd_per_hour_m": round(float(usdc.sum()) / hours_s / 1e6, 2),
            "depth_usd_per_bp_median": round(float(np.median(liq * sqrtp * 1e-4 / 2) / 1e6), 0),
            "eth_usd": round(eth_usd, 0),
            "swap_tx_gas_used": {"p50": int(np.median(gas)), "p90": int(np.percentile(gas, 90))},
            "effective_gas_price_gwei_p50": round(float(np.median(price)) / 1e9, 5),
            "swap_tx_l2_execution_cost_usd_p50": round(float(np.median(exec_cost_usd)), 5),
            "swap_tx_l1_data_fee_usd_p50": round(float(np.median(l1fee_eth)) * eth_usd, 5) if l1fee_eth else None,
            "swap_tx_gas_used_for_l1_p50": int(np.median(l1gas)) if l1gas else None,
            "block_gas_used_p50": int(np.median(bgas)), "block_gas_limit": int(np.median(blim)),
            "block_gas_limits_seen": {str(k): v for k, v in lims.items()},
            "token0_price_usd": round(eth_usd, 2),
            "pool_swap_gas_per_hour_m": round(len(logs) / hours_s * float(np.median(gas)) / 1e6, 1),
            "chain_gas_per_hour_m": round(float(np.median(bgas)) * 3600 / out["measured_block_time_s"] / 1e6, 0),
        }
        print(name, pname, out["pools"][pname], flush=True)
    return out


def run() -> dict:
    res = {k: probe_chain(k, v) for k, v in CHAINS.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    run()
