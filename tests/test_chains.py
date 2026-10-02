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


def test_subsecond_split_spreads_blocks_across_their_second():
    from pipeline.normalization import subsecond_split
    # four blocks 100..103 share second 1000: midpoints at .125 .375 .625 .875
    assert [subsecond_split(b, 100, 103, 1000) for b in range(100, 104)] == \
        [1000_125_000, 1000_375_000, 1000_625_000, 1000_875_000]
    assert subsecond_split(7, 7, 7, 5) == 5_500_000            # one block per second -> mid-second
    import pytest
    with pytest.raises(ValueError):
        subsecond_split(99, 100, 103, 1000)


def test_block_time_us_falls_back_to_slot_timestamp_on_mainnet():
    import pandas as pd
    from pipeline.normalization import block_time_us
    df = pd.DataFrame({"block_ts": [1, 2]})
    assert list(block_time_us(df)) == [1_000_000, 2_000_000]
    df["block_ts_us"] = [1_250_000, 2_750_000]
    assert list(block_time_us(df)) == [1_250_000, 2_750_000]


def test_normalized_time_spreads_txs_over_the_block_slice_on_l2():
    import pandas as pd
    from pipeline.normalization import normalized_time_us
    # block is 2nd of 4 in second 1000 -> slice [1000.25, 1000.5), midpoint 1000.375
    df = pd.DataFrame({"block_ts": [1000, 1000], "next_block_ts": [1001, 1001], "tx_index": [0, 5], "tx_count": [10, 10],
                       "block_ts_us": [1000_375_000, 1000_375_000], "blocks_in_second": [4, 4]})
    assert list(normalized_time_us(df)) == [1000_250_000, 1000_375_000]


def test_stage_directories_follow_the_active_chain():
    """Module-level paths are fixed at import, so check each chain in a
    fresh interpreter. Guards against a stage rebinding the shared
    ONCHAIN_DIR name (a refactor once sent L2 tx files to swaps/txs/)."""
    import os, subprocess, sys
    code = ("import pipeline.config as c, pipeline.extract_swaps as s, pipeline.extract_txs as t, pipeline.labels as l;"
            "assert s.SWAPS_DIR == c.ONCHAIN_DIR / 'swaps';"
            "assert t.TXS_DIR == c.ONCHAIN_DIR / 'txs';"
            "assert l.TXS_DIR == t.TXS_DIR and l.SWAPS_DIR == s.SWAPS_DIR;"
            "print(c.ONCHAIN_DIR)")
    for chain, tail in (("mainnet", "data/onchain"), ("arbitrum", "data/onchain/arbitrum"), ("hyperevm", "data/onchain/hyperevm")):
        out = subprocess.run([sys.executable, "-c", code], env={**os.environ, "AMMBRO_CHAIN": chain},
                             capture_output=True, text=True, check=True).stdout.strip()
        assert out.endswith(tail), (chain, out)
