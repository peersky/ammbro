"""Chain registry — the single place where chains differ.

Every pipeline stage reads the ACTIVE chain, chosen by the environment
variable AMMBRO_CHAIN (default "mainnet", so the original pipeline and its
committed results are unchanged). Run any stage for another chain with:

    AMMBRO_CHAIN=arbitrum make extract     # or: uv run python -m pipeline.<stage>

Canonical pool orientation. All stored swap data uses (stable, risky) as
(token0, token1) — mainnet's USDC/WETH order — so every downstream study
works unchanged. Pools whose on-chain order is (risky, stable) set
flip=True; the extractor swaps the two amounts and negates the tick, which
maps on-chain price 1.0001^tick (stable per risky, raw units) onto the
mainnet convention 10^(dec1-dec0) / 1.0001^tick.

Benchmarks. `bench` is the Binance symbol for the risky asset in USDT and
`numeraire` the USDC/USDT symbol (§17.6 numeraire correction). A "_UM"
suffix means Binance USD-M perpetual futures instead of spot (HYPE has no
Binance spot archive; the perp adds a few bp of basis/funding noise —
stated wherever HyperEVM results are cited).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"


@dataclass(frozen=True)
class Pool:
    name: str
    address: str
    token0: str            # canonical order: stable first
    token1: str
    dec0: int
    dec1: int
    flip: bool = False     # on-chain order is (risky, stable)
    kind: str = "risky"    # "risky": token1 priced via bench/numeraire; "stable": token1 = USDT via 1/numeraire
    bench: str = "ETHUSDT"
    numeraire: str = "USDCUSDT"
    big_usd: float = 1e5   # "large swap" cut; per chain = notional of mainnet's top 4.55% of swaps ($100k)

    @property
    def big_tag(self) -> str:
        return f"gt{self.big_usd / 1e3:g}k"

    def size_buckets(self) -> list[tuple[float, float, str]]:
        b = self.big_usd
        return [(0, b / 10, f"lt{b / 1e4:g}k"), (b / 10, b, f"{b / 1e4:g}k_{b / 1e3:g}k"), (b, 1e12, self.big_tag)]


@dataclass(frozen=True)
class Chain:
    name: str
    rpc_env: str
    block_time_s: float
    slot_s: int | None              # fixed slot grid (mainnet 12s); None on L2s
    study_pool: Pool
    control_pool: Pool
    log_chunk: int = 5_000          # max blocks per eth_getLogs the endpoint accepts
    header_successors: bool = True  # fetch block N+1 headers for next_block_ts (mainnet); L2s use ts + block time
    resolve_subsecond: bool = False # split same-timestamp blocks across their second (needs neighbour headers)
    layout: str | None = None       # None: legacy mainnet paths; else data/onchain/<layout>, results/<layout>
    system_txs: int = 0             # leading protocol txs per block (Arbitrum: ArbOS startBlock at index 0)
    notes: tuple = field(default_factory=tuple)


MAINNET = Chain(
    name="mainnet", rpc_env="ETH_RPC_URL", block_time_s=12.0, slot_s=12,
    study_pool=Pool("eth_usdc_005", "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640", "USDC", "WETH", 6, 18),
    control_pool=Pool("usdc_usdt_001", "0x3416cf6c708da44db2624d63ea0aaef7113527c6", "USDC", "USDT", 6, 6,
                      kind="stable", bench="USDCUSDT"),
)

ARBITRUM = Chain(
    name="arbitrum", rpc_env="ARB_RPC_URL", block_time_s=0.25, slot_s=None,
    study_pool=Pool("eth_usdc_005", "0xC6962004f452bE9203591991D15f6b388e09E8D0", "USDC", "WETH", 6, 18, flip=True,
                    big_usd=7_000),  # top 4.55% of Arbitrum swaps (26% of notional): flow is chopped into small fills
    control_pool=Pool("usdc_usdt_001", "0xbE3aD6a5669Dc0B8b12FeBC03608860C31E2eef6", "USDC", "USDT0", 6, 6,
                      kind="stable", bench="USDCUSDT"),
    log_chunk=10_000, header_successors=False, resolve_subsecond=True, layout="arbitrum", system_txs=1,
    notes=("sequencer ordering (FCFS + Timeboost express lane), not PBS",),
)

HYPEREVM = Chain(
    name="hyperevm", rpc_env="HYPEREVM_RPC_URL", block_time_s=1.0, slot_s=None,
    study_pool=Pool("hype_usdc_005", "0x6c9a33e3b592c0d65b3ba59355d5be0d38259285", "USDC", "WHYPE", 6, 18,
                    flip=True, bench="HYPEUSDT_UM"),
    control_pool=Pool("usdc_usdt0", "0x46abbdfc675ffa9ddf032c64fee363745204e63e", "USDC", "USDT0", 6, 6,
                      kind="stable", bench="USDCUSDT"),
    log_chunk=10_000, header_successors=False, layout="hyperevm",
    # resolve_subsecond=False: 97% of seconds hold exactly one block, so the split would place
    # almost every block at mid-second anyway; skipping it saves ~2/3 of header calls under the
    # shared 400 rps budget and moves ~3% of block times by up to 0.5s (big blocks).
    notes=("HyperBFT; ~1s small blocks (3M gas) + ~1/min big blocks (30M gas)",
           "HYPE benchmark is the Binance USD-M perp (no spot archive)"),
)

CHAINS = {c.name: c for c in (MAINNET, ARBITRUM, HYPEREVM)}
ACTIVE = CHAINS[os.environ.get("AMMBRO_CHAIN", "mainnet")]
