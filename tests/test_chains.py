"""Chain registry and canonical (stable, risky) orientation."""
import numpy as np

from pipeline.chains import ARBITRUM, CHAINS, HYPEREVM, MAINNET
from pipeline.extract_swaps import _decode_log


def _word(v: int) -> str:
    return format(v % (1 << 256), "064x")


def _log(a0: int, a1: int, tick: int) -> dict:
    return {"blockNumber": "0x1", "transactionHash": "0xab", "transactionIndex": "0x0", "logIndex": "0x0",
            "blockTimestamp": "0x10", "topics": ["0x", "0x" + "0" * 24 + "11" * 20, "0x" + "0" * 24 + "22" * 20],
            "data": "0x" + _word(a0) + _word(a1) + _word(0) + _word(0) + _word(tick)}


def test_flip_maps_onchain_risky_first_to_canonical_stable_first():
    # on-chain (WETH, USDC): pool sends 2 WETH, receives 5000 USDC
    d = _decode_log(_log(-2 * 10**18, 5000 * 10**6, -197000), ARBITRUM.study_pool)
    assert d["amount0_raw"] == 5000 * 10**6 and d["amount1_raw"] == -2 * 10**18
    # canonical price formula (mainnet convention) equals the on-chain price
    assert np.isclose(10**12 / 1.0001 ** d["tick"], 1.0001 ** (-197000) * 10**12)
    assert d["log_block_ts"] == 16


def test_no_flip_on_mainnet_pools():
    d = _decode_log(_log(5000 * 10**6, -2 * 10**18, 197000), MAINNET.study_pool)
    assert d["amount0_raw"] == 5000 * 10**6 and d["tick"] == 197000


def test_registry_consistency():
    for c in CHAINS.values():
        for p in (c.study_pool, c.control_pool):
            assert p.dec0 == 6, "canonical token0 is the 6-decimal stablecoin"
        assert c.study_pool.kind == "risky" and c.control_pool.kind == "stable"
    assert HYPEREVM.study_pool.bench.endswith("_UM")      # perp benchmark, stated as such
    assert MAINNET.layout is None                          # legacy paths preserved
