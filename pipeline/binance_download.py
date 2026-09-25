"""Download Binance public-archive SPOT aggTrades for the backtest window.

Strategy: monthly zips where published, daily zips for the trailing
incomplete month. Every file's sha256 is verified against Binance's
published .CHECKSUM and recorded in data/checksums/CHECKSUMS.sha256 —
that manifest is the reproducibility guarantee (§17.9). Raw zips are
never committed or re-hosted (Binance data terms).

Usage:
    python -m pipeline.binance_download            # download whole window
    python -m pipeline.binance_download ETHUSDT    # one symbol
"""
from __future__ import annotations

import datetime as dt
import hashlib
import sys
from pathlib import Path

import requests

from .config import (
    BINANCE_BASE,
    CHECKSUM_MANIFEST,
    RAW_DIR,
    SYMBOLS,
    WINDOW_END,
    WINDOW_START,
    months_in_window,
)

SESSION = requests.Session()


def _monthly_available(symbol: str, month: str) -> bool:
    url = f"{BINANCE_BASE}/monthly/aggTrades/{symbol}/{symbol}-aggTrades-{month}.zip"
    return SESSION.head(url, timeout=30).status_code == 200


def _urls_for(symbol: str) -> list[str]:
    """Monthly zips where they exist; daily zips otherwise."""
    urls = []
    for month in months_in_window():
        if _monthly_available(symbol, month):
            urls.append(
                f"{BINANCE_BASE}/monthly/aggTrades/{symbol}/{symbol}-aggTrades-{month}.zip"
            )
        else:
            y, m = map(int, month.split("-"))
            day = dt.date(y, m, 1)
            while day.month == m and WINDOW_START <= day <= WINDOW_END:
                urls.append(
                    f"{BINANCE_BASE}/daily/aggTrades/{symbol}/{symbol}-aggTrades-{day.isoformat()}.zip"
                )
                day += dt.timedelta(days=1)
    return urls


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_checksum(url: str) -> str:
    """Binance publishes '<sha256>  <filename>' next to each zip."""
    r = SESSION.get(url + ".CHECKSUM", timeout=60)
    r.raise_for_status()
    return r.text.split()[0].strip().lower()


def _record_checksum(digest: str, rel_name: str) -> None:
    CHECKSUM_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    line = f"{digest}  {rel_name}\n"
    existing = (
        CHECKSUM_MANIFEST.read_text() if CHECKSUM_MANIFEST.exists() else ""
    )
    if line not in existing:
        with CHECKSUM_MANIFEST.open("a") as f:
            f.write(line)


def download_symbol(symbol: str) -> None:
    dest_dir = RAW_DIR / "spot" / "aggTrades" / symbol
    dest_dir.mkdir(parents=True, exist_ok=True)
    urls = _urls_for(symbol)
    print(f"{symbol}: {len(urls)} files")
    for url in urls:
        name = url.rsplit("/", 1)[1]
        dest = dest_dir / name
        expected = _fetch_checksum(url)
        if dest.exists() and _sha256(dest) == expected:
            print(f"  ok (cached) {name}")
            _record_checksum(expected, f"{symbol}/{name}")
            continue
        print(f"  downloading {name}")
        with SESSION.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        actual = _sha256(tmp)
        if actual != expected:
            tmp.unlink()
            raise RuntimeError(
                f"checksum mismatch {name}: expected {expected}, got {actual}"
            )
        tmp.rename(dest)
        _record_checksum(expected, f"{symbol}/{name}")
        print(f"  verified {name}")


def main() -> None:
    symbols = sys.argv[1:] or SYMBOLS
    for symbol in symbols:
        download_symbol(symbol)


if __name__ == "__main__":
    main()
