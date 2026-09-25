"""§17.9 mandatory: label-independence assertion + sandwich detector
on hand-constructed blocks."""
import pandas as pd
import pytest

from pipeline.labels import assert_price_independent, detect_sandwiches


def make_block(rows):
    return pd.DataFrame(
        rows,
        columns=["block_number", "log_index", "tx_from", "amount1_raw"],
    )


def test_price_columns_rejected():
    with pytest.raises(AssertionError):
        assert_price_independent(["tx_hash", "q_lp_h0"])
    with pytest.raises(AssertionError):
        assert_price_independent(["sqrtPriceX96"])
    assert_price_independent(["tx_hash", "tx_from", "amount0_raw"])  # ok


def test_classic_sandwich_detected():
    # attacker buys, victim buys, attacker sells same size
    df = make_block([
        (100, 0, "0xattacker", +10_000),
        (100, 1, "0xvictim", +5_000),
        (100, 2, "0xattacker", -10_000),
    ])
    att, vic = detect_sandwiches(df)
    assert att.tolist() == [True, False, True]
    assert vic.tolist() == [False, True, False]


def test_unbalanced_legs_not_sandwich():
    df = make_block([
        (100, 0, "0xa", +10_000),
        (100, 1, "0xv", +5_000),
        (100, 2, "0xa", -2_000),   # only 20% offset — not a rebalance
    ])
    att, _ = detect_sandwiches(df)
    assert not att.any()


def test_no_victim_between_legs_not_sandwich():
    df = make_block([
        (100, 0, "0xa", +10_000),
        (100, 1, "0xother", -3_000),  # opposite direction — not a victim
        (100, 2, "0xa", -10_000),
    ])
    att, _ = detect_sandwiches(df)
    assert not att.any()


def test_cross_block_legs_not_sandwich():
    df = make_block([
        (100, 0, "0xa", +10_000),
        (100, 1, "0xv", +5_000),
        (101, 0, "0xa", -10_000),
    ])
    att, _ = detect_sandwiches(df)
    assert not att.any()
