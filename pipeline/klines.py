"""Binance 1-second klines for the census pairs (Study K5 benchmarks).

Lighter than aggTrades: one close per second. Used only to score the census
pools approximately (mid-price q at the block's second) for the cross-pool REP
simulation — not for the paper's headline scoring, which uses aggTrades bid/ask.

    uv run python -m pipeline.klines            → data/parquet/klines1s/<SYMBOL>.parquet

Monthly archives with their published SHA-256 verified; timestamps normalised
to µs (Binance switched spot timestamps from ms to µs on 2025-01-01).
"""
from __future__ import annotations

import hashlib
import io
import sys
import zipfile

import pandas as pd
import requests

from .binance_parse import normalize_ts_to_us
from .config import DATA_DIR

BASE = "https://data.binance.vision/data/spot/monthly/klines"
SYMBOLS = ["BTCUSDT", "LINKUSDT", "UNIUSDT", "PEPEUSDT"]
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
OUT = DATA_DIR / "parquet" / "klines1s"


def fetch_month(symbol: str, month: str) -> pd.DataFrame:
    name = f"{symbol}-1s-{month}.zip"
    url = f"{BASE}/{symbol}/1s/{name}"
    blob = requests.get(url, timeout=600).content
    want = requests.get(url + ".CHECKSUM", timeout=60).text.split()[0]
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise SystemExit(f"checksum mismatch {name}: {got} != {want}")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(f, header=None, usecols=[0, 4], names=["open_time", "close"])
    if not str(df["open_time"].iloc[0]).isdigit():          # some archives carry a header row
        df = df.iloc[1:].astype({"open_time": "int64", "close": "float64"})
    df["ts_us"] = normalize_ts_to_us(df["open_time"].astype("int64"))
    return df[["ts_us", "close"]]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for symbol in sys.argv[1:] or SYMBOLS:
        path = OUT / f"{symbol}.parquet"
        if path.exists():
            print(f"ok (exists) {path.name}")
            continue
        parts = []
        for m in MONTHS:
            parts.append(fetch_month(symbol, m))
            print(f"  {symbol} {m}: {len(parts[-1]):,} seconds", flush=True)
        df = pd.concat(parts).sort_values("ts_us").drop_duplicates("ts_us")
        df.to_parquet(path, index=False)
        print(f"wrote {path.name}: {len(df):,} rows")


if __name__ == "__main__":
    main()
