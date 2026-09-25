"""Uniswap v3 mainnet pool definitions for the backtest (§17.3)."""
from __future__ import annotations

from dataclasses import dataclass

SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"


@dataclass(frozen=True)
class Pool:
    name: str
    address: str
    token0: str
    token1: str
    dec0: int
    dec1: int


# Primary study pool: full pipeline, all studies.
ETH_USDC = Pool(
    name="eth_usdc_005",
    address="0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640",
    token0="USDC",
    token1="WETH",
    dec0=6,
    dec1=18,
)

# Calm-period control pool (§17.3.2): q_LP magnitudes must match the
# observable peg band. Never used for fee sweep or REP ablation.
USDC_USDT = Pool(
    name="usdc_usdt_001",
    address="0x3416cf6c708da44db2624d63ea0aaef7113527c6",
    token0="USDC",
    token1="USDT",
    dec0=6,
    dec1=6,
)

POOLS = [ETH_USDC, USDC_USDT]
