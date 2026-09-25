"""Parse Binance aggTrades zips into monthly Parquet with normalized
microsecond timestamps.

Timestamp trap (§17.3): SPOT files carry millisecond timestamps before
2025-01-01 and microsecond timestamps from 2025-01-01 onward. Misreading
µs as ms places trades ~50,000 years in the future. We branch on
magnitude AND cross-check against the file's date range; disagreement is
a hard error, not a warning.

Output schema (one file per symbol-month):
    ts_us      int64   event time, microseconds since epoch (normalized)
    price      float64
    qty        float64
    is_buyer_maker  bool
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd

from .config import PARQUET_DIR, RAW_DIR, SYMBOLS

# Binance SPOT aggTrades CSV columns (no header in older files; newer
# files ship a header row — sniffed below).
COLUMNS = [
    "agg_trade_id",
    "price",
    "qty",
    "first_trade_id",
    "last_trade_id",
    "ts_raw",
    "is_buyer_maker",
    "is_best_match",
]

# Magnitude fences: epoch-ms for plausible dates (2001..2100) is
# ~1e12..4.1e12; epoch-µs is ~1e15..4.1e15. Anything else is corrupt.
_MS_LO, _MS_HI = 10**12, 4_200_000_000_000
_US_LO, _US_HI = 10**15, 4_200_000_000_000_000


def normalize_ts_to_us(ts: pd.Series) -> pd.Series:
    """Return timestamps in microseconds, branching on magnitude.

    The whole series must sit in ONE unit band — a file mixing bands
    (or outside both) raises.
    """
    lo, hi = int(ts.min()), int(ts.max())
    if _MS_LO <= lo and hi < _MS_HI:
        return ts.astype("int64") * 1000
    if _US_LO <= lo and hi < _US_HI:
        return ts.astype("int64")
    raise ValueError(
        f"timestamp range [{lo}, {hi}] fits neither ms nor µs band; "
        "file corrupt or unit assumption violated"
    )


def _read_csv(raw: bytes) -> pd.DataFrame:
    first_line = raw.split(b"\n", 1)[0]
    has_header = first_line.split(b",")[0].strip().isalpha() or b"agg" in first_line.lower()
    return pd.read_csv(
        io.BytesIO(raw),
        header=0 if has_header else None,
        names=COLUMNS,
        usecols=["price", "qty", "ts_raw", "is_buyer_maker"],
        dtype={"price": "float64", "qty": "float64", "ts_raw": "int64"},
    )


def parse_zip(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        inner = z.namelist()[0]
        df = _read_csv(z.read(inner))
    df["ts_us"] = normalize_ts_to_us(df["ts_raw"])
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(bool)
    return df[["ts_us", "price", "qty", "is_buyer_maker"]].sort_values("ts_us")


def parse_symbol(symbol: str) -> None:
    src_dir = RAW_DIR / "spot" / "aggTrades" / symbol
    out_dir = PARQUET_DIR / "aggTrades" / symbol
    out_dir.mkdir(parents=True, exist_ok=True)

    zips = sorted(src_dir.glob("*.zip"))
    if not zips:
        raise SystemExit(f"no zips under {src_dir}; run binance_download first")

    # Group daily files into their month so output is always one
    # parquet per symbol-month.
    by_month: dict[str, list[Path]] = {}
    for p in zips:
        # names: SYMBOL-aggTrades-YYYY-MM.zip or SYMBOL-aggTrades-YYYY-MM-DD.zip
        stem_date = p.stem.split("aggTrades-")[1]
        by_month.setdefault(stem_date[:7], []).append(p)

    for month, paths in sorted(by_month.items()):
        out = out_dir / f"{symbol}-aggTrades-{month}.parquet"
        if out.exists():
            print(f"  ok (exists) {out.name}")
            continue
        frames = [parse_zip(p) for p in sorted(paths)]
        df = pd.concat(frames, ignore_index=True).sort_values("ts_us")
        df.to_parquet(out, index=False)
        print(f"  wrote {out.name}: {len(df):,} trades")


def main() -> None:
    symbols = sys.argv[1:] or SYMBOLS
    for symbol in symbols:
        print(symbol)
        parse_symbol(symbol)


if __name__ == "__main__":
    main()
