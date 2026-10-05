"""Study G — L1 viability: is reconciliation cheaper than execution? (P§4.6)

Every input is measured on the chain itself, nothing is assumed:

  G1 execution   gasUsed of real swap transactions on the study pool (receipts,
                 sampled uniformly over the window).
  G2 report      gas of real Chainlink Data Streams verifications: historical
                 transactions that emitted ReportVerified, traced with
                 callTracer; the VerifierProxy.verify call's own gasUsed
                 (signature checks + fee manager) and the signed report's
                 calldata size. Real signed reports, no credentials needed.
  G3 reconcile   contracts/src/Reconciler.sol: per swap re-hash the hook's
                 record, closed-form charge beyond the allowance, stake debit;
                 batches of 1/10/50/200 swaps, each call its own transaction
                 (`forge test --isolate`). Fixed + per-swap gas by least squares.
  G4 hook        contracts/src/Recorders.sol: full record in storage, event
                 only, rolling hash; marginal gas = call − a no-op call with
                 the same calldata (the intrinsic cost a hook inside a swap
                 does not pay again).
  G5 v4 hook     contracts/src/RepHook.sol on a real Uniswap v4 PoolManager
                 (v4-core, local deployment): median swap gas with the event /
                 rolling-hash afterSwap hook minus a hookless pool, every
                 swap its own transaction — the hook's real overhead incl.
                 PoolManager dispatch and state reads. The budget uses it.
  G-park         contracts/src/RepHookAccount.sol (v4 hook with the parking lock
                 ℓ = ρ + k·Δ_block, collateral check and per-account record chain,
                 plus selfSettle / applyEpoch, docs/settlement-keepers.md):
                 swap gas vs a hookless pool; steady-state self-settlement and
                 keeper-epoch gas (accounts settled before), fixed + slope.
  G-zk           zk/contracts: one real SP1 v6.0.0 Groth16 proof verified on-chain.
  Settlement     budget of four settlement designs over the window, all with the
                 measured per-swap hook (parking + record), priced at real base fees.
  Budget         reconciliation gas vs execution gas over the real window,
                 priced block by block at the real base fee and ETH price:
                 per-block regime (one reconciliation tx per block with a
                 swap) and epoch regime (one tx per EPOCH_BLOCKS, reports
                 after the first verified at the measured in-tx rate).

The VerifierProxy addresses were confirmed on-chain (typeAndVersion() =
"VerifierProxy 2.0.0"). RPC use is light (a few hundred calls) and goes
through rpc.py's paced client.
"""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
import pandas as pd

from .chains import ACTIVE
from .config import ONCHAIN_DIR, REPO_ROOT, RESULTS_DIR
from .pools import STUDY_POOL
from .rpc import batch as batch_call

OUT = RESULTS_DIR / "study_g"
VERIFIER_PROXY = {"mainnet": "0x5a1634a86e9b7bfef33f0f3f3ea3b1abbc4cc85f",
                  "arbitrum": "0x478aa2ac9f6d65f84e09d9185d126c3a17c2a93c"}
REPORT_VERIFIED = "0x58ca9502e98a536e06e72d680fcc251e5d10b72291a281665a2c2dc0ac30fcc5"  # ReportVerified(bytes32,address)
VERIFY_SEL = "0xf7e83aee"     # VerifierProxy.verify(bytes,bytes)
N_SWAP_SAMPLE = 400
N_VERIFY_TX = 40
SEED = 5


def _calls(tree: dict):
    yield tree
    for c in tree.get("calls", []) or []:
        yield from _calls(c)


def report_verification() -> dict:
    """G2: recent verify() calls on this chain's VerifierProxy."""
    proxy = VERIFIER_PROXY[ACTIVE.name]
    head = int(batch_call([("eth_blockNumber", [])])[0], 16)
    span = 2_000 if ACTIVE.slot_s else 10_000          # Chainstack getLogs range cap on L2
    txs = []
    lo = head
    while len(txs) < N_VERIFY_TX and lo > head - 20 * span:
        hi, lo = lo, lo - span
        logs = batch_call([("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi), "topics": [REPORT_VERIFIED]}])])[0]
        txs += [l["transactionHash"] for l in logs if l["transactionHash"] not in txs]
    txs = txs[:N_VERIFY_TX]
    traces = batch_call([("debug_traceTransaction", [h, {"tracer": "callTracer"}]) for h in txs])
    rows = []
    for h, tr in zip(txs, traces):
        calls = [c for c in _calls(tr) if (c.get("to") or "").lower() == proxy and c.get("input", "").startswith(VERIFY_SEL)]
        for k, c in enumerate(calls):
            rows.append({"tx": h, "nth_in_tx": k, "gas": int(c["gasUsed"], 16),
                         "calldata_bytes": (len(c["input"]) - 2) // 2})
    df = pd.DataFrame(rows)
    first, later = df[df.nth_in_tx == 0], df[df.nth_in_tx > 0]
    q = lambda s: {p: int(np.percentile(s, p)) for p in (10, 50, 90)} if len(s) else None
    return {"verifier_proxy": proxy, "n_tx": len(txs), "n_verify_calls": len(df),
            "gas_first_in_tx": q(first.gas), "gas_later_in_same_tx": q(later.gas),
            "calldata_bytes": q(df.calldata_bytes)}


def execution_gas() -> dict:
    """G1: gasUsed of real study-pool swap transactions, sampled over the window."""
    swaps = pd.concat(pd.read_parquet(p, columns=["tx_hash", "block_number"])
                      for p in sorted((ONCHAIN_DIR / "swaps" / STUDY_POOL.name).glob("*.parquet")))
    hashes = swaps.drop_duplicates("tx_hash").sample(N_SWAP_SAMPLE, random_state=SEED)["tx_hash"].tolist()
    recs = batch_call([("eth_getTransactionReceipt", [h]) for h in hashes])
    gas = np.array([int(r["gasUsed"], 16) for r in recs if r])
    swaps_in_tx = np.array([sum(1 for l in r["logs"] if l["topics"] and l["topics"][0] == STUDY_POOL_SWAP_TOPIC) for r in recs if r])
    single = gas[swaps_in_tx == 1]
    q = lambda s: {p: int(np.percentile(s, p)) for p in (10, 50, 90)}
    return {"n_receipts": int(len(gas)), "gas_per_swap_tx": q(gas), "gas_single_swap_tx": q(single),
            "share_multi_swap_tx": round(float((swaps_in_tx > 1).mean()), 3)}


STUDY_POOL_SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
CONTRACTS = REPO_ROOT / "contracts"
EPOCH_BLOCKS = {"mainnet": 300, "arbitrum": 14_400}   # ~1 hour of blocks per reconciliation tx


def _forge(match: str) -> dict:
    out = subprocess.run(["forge", "test", "--isolate", "--gas-report", "--json", "--mt", match],
                         cwd=CONTRACTS, capture_output=True, text=True, check=True).stdout
    return {c["contract"].split(":")[1]: {f.split("(")[0]: v["median"] for f, v in c["functions"].items()}
            for c in json.loads(out)}


def foundry() -> dict:
    """G3/G4 from Foundry (chain-independent EVM gas)."""
    rec = _forge("test_record_variants")
    base = rec["RecordNoop"]["record"]
    hook = {k: rec[c]["record"] - base for k, c in
            (("store", "RecordStore"), ("event", "RecordEvent"), ("rolling_hash", "RecordChain"))}
    sizes = [1, 10, 50, 200]          # tests test_reconcile_n001 … n200 (no name is a prefix of another)
    gas = [_forge(f"test_reconcile_n{n:03d}")["Reconciler"]["reconcile"] for n in sizes]
    slope, fixed = np.polyfit(sizes, gas, 1)
    v4 = {}
    for name in ("none", "event", "chain"):
        d = _forge(f"test_swap_{name}")
        v4[name] = d["PoolSwapTest"]["swap"]
    return {"v4_swap_gas": v4,
            "v4_hook_overhead_gas": {"event": v4["event"] - v4["none"], "rolling_hash": v4["chain"] - v4["none"]},
            "hook_marginal_gas_per_swap": hook, "noop_call_gas": base,
            "reconcile_gas_by_batch": dict(zip(map(str, sizes), gas)),
            "reconcile_fixed_gas_per_tx": int(round(fixed)), "reconcile_gas_per_swap": int(round(slope))}


ZK_CONTRACTS = REPO_ROOT / "zk" / "contracts"


def _forge_at(root, match: str) -> dict:
    out = subprocess.run(["forge", "test", "--isolate", "--gas-report", "--json", "--mt", match],
                         cwd=root, capture_output=True, text=True, check=True).stdout
    res = {}
    for c in json.loads(out):
        for f, v in c["functions"].items():
            name = f"{c['contract'].split(':')[1]}.{f.split('(')[0]}"
            res[f"{c['contract'].split(':')[1]}.{f}"] = v          # full signature (overloads)
            res.setdefault(name, v)                                 # short name: first overload listed
    return res


def foundry_park() -> dict:
    """G-park and G-zk: steady-state gas of the settlement layer."""
    base = _forge_at(CONTRACTS, "test_park_baseline")["PoolSwapTest.swap"]["median"]
    park = _forge_at(CONTRACTS, "test_park_swap")["PoolSwapTest.swap"]["median"]
    # self-settle: each test settles once (1 swap, fresh slot) then n swaps; the n-swap call is the steady one
    self_n = {1: _forge_at(CONTRACTS, "test_self_n001")["RepHookAccount.selfSettle"]["min"]}
    for n in (10, 50):
        self_n[n] = _forge_at(CONTRACTS, f"test_self_n{n:03d}")["RepHookAccount.selfSettle"]["max"]
    s_slope, s_fixed = np.polyfit(list(self_n), list(self_n.values()), 1)
    epoch_n = {n: _forge_at(CONTRACTS, f"test_epoch_n{n:04d}")["RepHookAccount.applyEpoch"]["median"] for n in (10, 100, 400)}
    e_slope, e_fixed = np.polyfit(list(epoch_n), list(epoch_n.values()), 1)
    skip = _forge_at(CONTRACTS, "test_epoch_skip_n0100")["RepHookAccount.applyEpoch"]["median"]
    groth = _forge_at(ZK_CONTRACTS, "test_verify_groth16")["SP1Verifier.verifyProof(bytes32,bytes,bytes)"]["median"]
    return {"swap_hookless": base, "swap_with_park_hook": park, "hook_park_overhead_per_swap": park - base,
            "self_settle_by_n": self_n, "self_settle_fixed": int(s_fixed), "self_settle_per_swap": int(s_slope),
            "epoch_by_accounts": epoch_n, "epoch_fixed": int(e_fixed), "epoch_per_account": int(e_slope),
            "epoch_skipped_per_entry": int(skip / 100), "groth16_verify_tx": groth}


def settlement_budget(meas: dict, park: dict, fnd: dict) -> dict:
    """Four settlement designs over the window (docs/settlement-keepers.md §2)."""
    sw = pd.concat(pd.read_parquet(p, columns=["tx_hash", "block_number", "block_ts", "base_fee_wei", "amount0_raw", "amount1_raw"])
                   for p in sorted((ONCHAIN_DIR / "swaps" / STUDY_POOL.name).glob("*.parquet")))
    tx = pd.concat(pd.read_parquet(p, columns=["tx_hash", "tx_from"])
                   for p in sorted((ONCHAIN_DIR / "txs" / STUDY_POOL.name).glob("*.parquet"))).drop_duplicates("tx_hash")
    sw = sw.merge(tx, on="tx_hash", how="left")
    a0 = sw["amount0_raw"].astype(float).abs() / 10**STUDY_POOL.dec0
    a1 = sw["amount1_raw"].astype(float).abs() / 10**STUDY_POOL.dec1
    sw["day"] = sw["block_ts"] // 86400
    sw["eth"] = sw["day"].map((a0 / a1).where(a1 > 1e-6).groupby(sw["day"]).median())
    sw["usd_gas"] = sw["base_fee_wei"].astype(float) / 1e18 * sw["eth"]
    sw["hour"] = sw["block_ts"] // 3600
    blk = sw.groupby("block_number").agg(swaps=("tx_hash", "size"), accts=("tx_from", "nunique"), usd_gas=("usd_gas", "first"))
    hr = sw.groupby("hour").agg(swaps=("tx_hash", "size"), accts=("tx_from", "nunique"), blocks=("block_number", "nunique"),
                                usd_gas=("usd_gas", "median"))
    rv = meas["report_verification"]
    report = rv["gas_first_in_tx"][50] + calldata_gas(rv["calldata_bytes"][50])
    hook = park["hook_park_overhead_per_swap"]
    rec_fixed, rec_swap = fnd["reconcile_fixed_gas_per_tx"], fnd["reconcile_gas_per_swap"]
    e_fixed, e_acct = park["epoch_fixed"], park["epoch_per_account"]
    ecrecover_batch = 3_000                # one signature per price batch (ecrecover precompile)
    designs = {
        "keeper on-chain, per block (Data Streams report per block)":
            (blk, report + rec_fixed + blk.swaps * rec_swap + blk.accts * e_acct),
        "keeper on-chain, hourly (one signed price batch)":
            (hr, ecrecover_batch + calldata_gas(32) * hr.blocks + rec_fixed + hr.swaps * rec_swap + hr.accts * e_acct),
        "keeper zk, hourly (one Groth16 proof)":
            (hr, park["groth16_verify_tx"] + e_fixed + hr.accts * e_acct),
        "every account self-settles hourly (on-chain)":
            (hr, hr.accts * park["self_settle_fixed"] + hr.swaps * park["self_settle_per_swap"]),
    }
    exec_gas = meas["execution"]["gas_single_swap_tx"][50]
    n_swaps = int(sw.shape[0])
    hook_usd = float((hook * sw["usd_gas"]).sum())
    rows = {}
    for name, (frame, gas) in designs.items():
        settle_gas = float(gas.sum())
        total = settle_gas + hook * n_swaps
        rows[name] = {"settlement_gas_per_swap": int(settle_gas / n_swaps),
                      "total_gas_per_swap_incl_hook": int(total / n_swaps),
                      "ratio_to_execution": round(total / n_swaps / exec_gas, 3),
                      "usd_window": round(float((gas * frame.usd_gas).sum()) + hook_usd, 0)}
    q = lambda s: [int(np.percentile(s, p)) for p in (50, 95, 99)]
    return {"hook_per_swap_gas": hook, "accounts_per_hour_p50_p95_p99": q(hr.accts),
            "swaps_per_hour_p50_p95_p99": q(hr.swaps), "designs": rows}


def calldata_gas(n_bytes: int) -> int:
    return 16 * n_bytes        # upper bound: every byte non-zero (EIP-2028)


def budget(meas: dict, fnd: dict) -> dict:
    """Reconciliation vs execution over the window at real base fees."""
    sw = pd.concat(pd.read_parquet(p, columns=["block_number", "block_ts", "base_fee_wei", "amount0_raw", "amount1_raw"])
                   for p in sorted((ONCHAIN_DIR / "swaps" / STUDY_POOL.name).glob("*.parquet")))
    a0 = sw["amount0_raw"].astype(float).abs() / 10**STUDY_POOL.dec0
    a1 = sw["amount1_raw"].astype(float).abs() / 10**STUDY_POOL.dec1
    # ETH price per UTC day: median over the day's swaps (a dust swap's own ratio is meaningless)
    sw["day"] = sw["block_ts"] // 86400
    eth_day = (a0 / a1).where(a1 > 1e-6).groupby(sw["day"]).median()
    sw["eth_usd"] = sw["day"].map(eth_day)
    blk = sw.groupby("block_number").agg(n=("block_number", "size"), fee=("base_fee_wei", "first"),
                                         eth=("eth_usd", "first"))
    usd_per_gas = blk["fee"].to_numpy(float) / 1e18 * blk["eth"].to_numpy()
    n = blk["n"].to_numpy()
    rv = meas["report_verification"]
    verify_first = rv["gas_first_in_tx"][50] + calldata_gas(rv["calldata_bytes"][50])
    verify_later = (rv["gas_later_in_same_tx"] or rv["gas_first_in_tx"])[50] + calldata_gas(rv["calldata_bytes"][50])
    exec_per_swap = meas["execution"]["gas_single_swap_tx"][50]
    per_swap = fnd["reconcile_gas_per_swap"]
    fixed = fnd["reconcile_fixed_gas_per_tx"]
    epoch = EPOCH_BLOCKS[ACTIVE.name]
    rows = {}
    for hook_name in ("event", "rolling_hash"):
        hook = fnd["v4_hook_overhead_gas"][hook_name]      # real v4 dispatch + record
        for regime in ("per_block", "epoch"):
            if regime == "per_block":      # one reconciliation tx per block with a swap
                blk_gas = verify_first + fixed + n * (per_swap + hook)
                extra_gas = extra_usd = 0.0
            else:   # one tx per `epoch` blocks: one fixed cost and one first-report surcharge per tx
                n_tx = int(np.ceil((blk.index.max() - blk.index.min() + 1) / epoch))
                blk_gas = verify_later + n * (per_swap + hook)
                extra_gas = n_tx * (fixed + verify_first - verify_later)
                extra_usd = extra_gas * float(np.median(usd_per_gas))
            gas_total = float(np.sum(blk_gas)) + extra_gas
            rows[f"{hook_name}/{regime}"] = {
                "reconciliation_gas_per_swap": int(gas_total / n.sum()),
                "ratio_to_execution": round(gas_total / n.sum() / exec_per_swap, 3),
                "usd_window": round(float(np.sum(blk_gas * usd_per_gas)) + extra_usd, 0),
            }
    return {"swaps": int(n.sum()), "blocks_with_swap": len(blk), "swaps_per_block_mean": round(float(n.mean()), 2),
            "execution_gas_per_swap_median": exec_per_swap,
            "execution_usd_window": round(float(np.sum(n * exec_per_swap * usd_per_gas)), 0),
            "verify_gas_first_incl_calldata": verify_first, "verify_gas_later_incl_calldata": verify_later,
            "base_fee_gwei_median": round(float(np.median(blk["fee"]) / 1e9), 4),
            "epoch_blocks": epoch, "by_design": rows}


def run() -> dict:
    out = {"chain": ACTIVE.name, "execution": execution_gas(), "report_verification": report_verification(),
           "foundry": foundry()}
    out["budget"] = budget(out, out["foundry"])
    out["settlement_layer"] = foundry_park()
    out["settlement_budget"] = settlement_budget(out, out["settlement_layer"], out["foundry"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "measured.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
