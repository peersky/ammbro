import pandas as pd

from pipeline.normalization import normalized_time_us


def test_uniform_normalization():
    df = pd.DataFrame(
        {
            "block_ts": [1_750_000_000, 1_750_000_000],
            "next_block_ts": [1_750_000_012, 1_750_000_012],
            "tx_index": [0, 50],
            "tx_count": [100, 100],
        }
    )
    t = normalized_time_us(df)
    assert t.iloc[0] == 1_750_000_000_000_000          # top-of-block = block ts
    assert t.iloc[1] == 1_750_000_006_000_000          # mid-block = +6s of 12s


def test_missing_next_block_defaults_12s():
    df = pd.DataFrame(
        {
            "block_ts": [1_750_000_000],
            "next_block_ts": [None],
            "tx_index": [100],
            "tx_count": [200],
        }
    )
    t = normalized_time_us(df)
    assert t.iloc[0] == 1_750_000_006_000_000
