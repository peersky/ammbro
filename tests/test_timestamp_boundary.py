"""§17.9 mandatory test: ms/µs timestamp boundary (2025-01-01).

Misreading µs as ms places trades ~50,000 years out; ms as µs places
them in 1970. Both must be impossible by construction.
"""
import pandas as pd
import pytest

from pipeline.binance_parse import normalize_ts_to_us

# 2024-12-31 23:59:59 UTC in ms; 2025-01-01 00:00:00 UTC in µs
MS_PRE_BOUNDARY = 1_735_689_599_000
US_POST_BOUNDARY = 1_735_689_600_000_000


def test_ms_era_scaled_to_us():
    s = pd.Series([MS_PRE_BOUNDARY - 1000, MS_PRE_BOUNDARY])
    out = normalize_ts_to_us(s)
    assert out.iloc[-1] == MS_PRE_BOUNDARY * 1000


def test_us_era_passthrough():
    s = pd.Series([US_POST_BOUNDARY, US_POST_BOUNDARY + 50_000])
    out = normalize_ts_to_us(s)
    assert (out == s).all()


def test_normalized_boundary_is_contiguous():
    # Last ms-era instant and first µs-era instant must normalize to
    # adjacent times, not diverge by 1000x.
    ms = normalize_ts_to_us(pd.Series([MS_PRE_BOUNDARY, MS_PRE_BOUNDARY])).iloc[0]
    us = normalize_ts_to_us(pd.Series([US_POST_BOUNDARY, US_POST_BOUNDARY])).iloc[0]
    assert us - ms == 1_000_000  # exactly one second apart


def test_garbage_units_rejected():
    with pytest.raises(ValueError):
        normalize_ts_to_us(pd.Series([12345, 67890]))  # seconds-scale
    with pytest.raises(ValueError):
        # mixed ms and µs in one file
        normalize_ts_to_us(pd.Series([MS_PRE_BOUNDARY, US_POST_BOUNDARY]))
