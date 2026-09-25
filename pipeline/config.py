"""Central config for the REP-AMM backtest data pipeline.

Window and pair scoping per spec §17.3. All values here are the single
source of truth — scripts must not hardcode dates/symbols.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw" / "binance"
PARQUET_DIR = DATA_DIR / "parquet"
BARS_DIR = DATA_DIR / "bars"
CHECKSUM_MANIFEST = DATA_DIR / "checksums" / "CHECKSUMS.sha256"

BINANCE_BASE = "https://data.binance.vision/data/spot"

# Benchmark symbols: ETHUSDT primary, USDCUSDT numeraire correction (§17.6)
SYMBOLS = ["ETHUSDT", "USDCUSDT"]

# Backtest window (inclusive). Past 6 months at scaffold time (2026-09-01).
# Extend backward toward post-Merge era (late-2022) per §17.3 once the
# 6-month pipeline gates clear.
WINDOW_START = dt.date(2026, 3, 1)
WINDOW_END = dt.date(2026, 8, 31)

# Binance SPOT timestamp unit boundary (§17.3 trap): ms before this date,
# microseconds from it onward.
US_TIMESTAMP_BOUNDARY = dt.date(2025, 1, 1)

# Markout horizons in seconds (§17.2). t0 = block timestamp.
HORIZONS_S = [0, 12, 30, 60]

# Derived bar resolutions (ms) for the resampled benchmark layer.
# Native ticks remain canonical; bars are convenience/inspection layers.
BAR_RESOLUTIONS_MS = [50, 250]


def months_in_window() -> list[str]:
    """Return YYYY-MM strings covering the window."""
    out = []
    y, m = WINDOW_START.year, WINDOW_START.month
    while (y, m) <= (WINDOW_END.year, WINDOW_END.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out
