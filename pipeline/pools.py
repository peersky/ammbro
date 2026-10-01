"""Pool definitions for the ACTIVE chain (see pipeline/chains.py).

STUDY_POOL is the chain's risky/USDC study pool (mainnet: Uniswap v3
USDC/WETH 0.05%); CONTROL_POOL its USDC/USDT calm-period control pool
(§17.3.2). Data for every pool is stored in canonical (stable, risky)
order — see chains.py.
"""
from __future__ import annotations

from .chains import ACTIVE, SWAP_TOPIC, Pool  # noqa: F401  (re-exported)

STUDY_POOL = ACTIVE.study_pool
CONTROL_POOL = ACTIVE.control_pool
POOLS = [STUDY_POOL, CONTROL_POOL]
