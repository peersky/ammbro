"""Minimal batched JSON-RPC client for the mainnet execution endpoint.

Endpoint comes from ETH_RPC_URL in the environment (or .env at repo
root) — the URL embeds the auth key, so it never appears in code.
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

from .config import REPO_ROOT

_SESSION = requests.Session()

# Chainstack counts every JSON-RPC call inside a batch toward the RPS
# quota, so batches must be paced: after a batch of N calls we sleep
# N / rps before the next one. The rate is adaptive (AIMD): start at
# ETH_RPC_RPS (default 300), multiply by 0.7 on every rate-limit error,
# creep back up 2% per clean batch, floor 15. The Chainstack plan allows
# 400 requests/s in total, shared by every chain's endpoint and every
# concurrent job — the ceiling defaults to 380 and must be lowered when
# jobs run in parallel (their ETH_RPC_RPS_MAX values must sum to <= 380).
_rps = float(os.environ.get("ETH_RPC_RPS", "300"))
_RPS_FLOOR = 15.0
_RPS_CEIL = float(os.environ.get("ETH_RPC_RPS_MAX", "380"))
_last_debt = 0.0  # seconds of quota consumed by the previous batch
_last_time = 0.0


def rpc_url() -> str:
    """Endpoint of the ACTIVE chain (pipeline/chains.py), from the
    environment or .env — URLs embed auth keys and never appear in code."""
    from .chains import ACTIVE
    key = ACTIVE.rpc_env
    url = os.environ.get(key)
    if not url:
        env = REPO_ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith(key + "="):
                    url = line.split("=", 1)[1].strip()
    if not url:
        raise RuntimeError(f"{key} not set (env or .env)")
    return url


def call(method: str, params: list, retries: int = 5) -> Any:
    return batch([(method, params)], retries=retries)[0]


def _pace(n_calls: int) -> None:
    """Sleep off the quota debt of the previous batch before sending the
    next one, then record this batch's debt."""
    global _last_debt, _last_time
    wait = _last_debt - (time.monotonic() - _last_time)
    if wait > 0:
        time.sleep(wait)
    _last_time = time.monotonic()
    _last_debt = n_calls / _rps


def _on_rate_limit() -> None:
    global _rps
    _rps = max(_RPS_FLOOR, _rps * 0.7)
    print(f"  [rpc] rate-limited, rps -> {_rps:.0f}")


def _on_clean_batch() -> None:
    global _rps
    _rps = min(_RPS_CEIL, _rps * 1.02)


def _rate_limited(err: dict) -> float | None:
    """Return suggested wait seconds if this is an RPS-limit error."""
    if err.get("code") != -32005:
        return None
    if "paused" in str(err.get("message", "")).lower():   # account suspended, not a rate limit: fail fast
        raise RuntimeError(f"rpc endpoint paused: {err.get('message')}")
    hint = str(err.get("data", {}).get("try_again_in", "1s"))
    try:
        return float(hint.replace("ms", "e-3").replace("s", "")) + 0.25
    except ValueError:
        return 1.5


def batch(reqs: list[tuple[str, list]], retries: int = 8) -> list[Any]:
    """Execute a JSON-RPC batch; returns results ordered like reqs.
    Paced against RPS_LIMIT; retries rate-limit and transient errors."""
    payload = [
        {"jsonrpc": "2.0", "id": i, "method": m, "params": p}
        for i, (m, p) in enumerate(reqs)
    ]
    results: dict[int, Any] = {}
    pending = list(range(len(reqs)))
    delay = 1.0
    attempt = 0
    rl_hits = 0
    while pending:
        try:
            _pace(len(pending))
            r = _SESSION.post(
                rpc_url(), json=[payload[i] for i in pending], timeout=120
            )
            r.raise_for_status()
            body = r.json()
            if isinstance(body, dict):  # single-item batch may unwrap
                body = [body]
            still_pending = []
            wait = 0.0
            for item in body:
                if "error" in item:
                    w = _rate_limited(item["error"])
                    if w is None:
                        raise RuntimeError(f"rpc error: {item['error']}")
                    # Partial rate-limit: token bucket clipped this item;
                    # keep the successes, retry only the clipped ones.
                    wait = max(wait, w)
                    still_pending.append(item["id"])
                else:
                    results[item["id"]] = item["result"]
            pending = still_pending
            if pending:
                rl_hits += 1
                if rl_hits > 500:
                    raise RuntimeError("rate-limited persistently for ~500 retries")
                _on_rate_limit()
                time.sleep(wait)
            else:
                _on_clean_batch()
        except RuntimeError:
            raise
        except Exception:
            attempt += 1
            if attempt >= retries:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30)
    return [results[i] for i in range(len(reqs))]


def hex_int(x: str | None) -> int | None:
    return None if x is None else int(x, 16)


def block_by_number(n: int, full_txs: bool = False) -> dict:
    return call("eth_getBlockByNumber", [hex(n), full_txs])


def latest_block_number() -> int:
    return hex_int(call("eth_blockNumber", []))


def find_block_at_or_after(ts: int) -> int:
    """Binary-search the first block with timestamp >= ts."""
    lo, hi = 1, latest_block_number()
    while lo < hi:
        mid = (lo + hi) // 2
        if hex_int(block_by_number(mid)["timestamp"]) < ts:
            lo = mid + 1
        else:
            hi = mid
    return lo
