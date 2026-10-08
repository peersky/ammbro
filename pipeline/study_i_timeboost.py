"""Study I: Timeboost express-lane use by today's Arbitrum corrections (paper §4.4).

Arbitrum's sequencer orders by arrival; its paid priority is the Timeboost express lane, and every
receipt carries a `timeboosted` flag. For a random sample of blocks, this reads the receipts of the
first correcting swap and of the non-correcting swaps in the pool, and compares the express-lane share
of corrections that earned rent today (a proxy for contested slots) with those that did not, and
with retail. Uses Arbitrum's public RPC (no keyed endpoint), rate-limited.

    AMMBRO_CHAIN=arbitrum uv run python -m pipeline.study_i_timeboost → results/arbitrum/study_i/timeboost.json
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

from . import study_h as H
from .config import RESULTS_DIR

RPC = "https://arb1.arbitrum.io/rpc"
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (ammbro research)"}   # default urllib agent is refused
N_BLOCKS = 3000
BATCH = 25
SEED = 11


def receipts(hashes: list[str]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for i in range(0, len(hashes), BATCH):
        chunk = hashes[i:i + BATCH]
        body = json.dumps([{"jsonrpc": "2.0", "id": k, "method": "eth_getTransactionReceipt", "params": [h]}
                           for k, h in enumerate(chunk)]).encode()
        for attempt in range(6):
            try:
                req = urllib.request.Request(RPC, body, HEADERS)
                res = json.loads(urllib.request.urlopen(req, timeout=30).read())
                for r in res:
                    rec = r.get("result")
                    if rec is not None and "timeboosted" in rec:
                        out[chunk[r["id"]]] = bool(rec["timeboosted"])
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise
                time.sleep(2 ** attempt)
            except Exception:
                time.sleep(2 ** attempt)
        time.sleep(0.3)
    return out


def main() -> dict:
    df, _ = H.prepare()
    rng = np.random.default_rng(SEED)
    corr = df[df["correcting"] & df["q_c_h0"].notna()].groupby("block_number").head(1)
    blocks = rng.choice(corr.block_number.unique(), N_BLOCKS, replace=False)
    c = corr[corr.block_number.isin(blocks)][["tx_hash", "rent_today", "block_ts"]]
    r = df[df.block_number.isin(blocks) & ~df["correcting"]].drop_duplicates("tx_hash")[["tx_hash"]]
    tb = receipts(sorted(set(c.tx_hash) | set(r.tx_hash)))
    c = c.assign(tb=c.tx_hash.map(tb)).dropna(subset=["tb"])
    r = r.assign(tb=r.tx_hash.map(tb)).dropna(subset=["tb"])
    y = c.rent_today > 0
    share = lambda s: round(float(s.astype(float).mean()), 4)
    out = {"rpc": "public arb1", "sample_blocks": N_BLOCKS,
           "window": [str(pd.to_datetime(c.block_ts.min(), unit="s")), str(pd.to_datetime(c.block_ts.max(), unit="s"))],
           "n_corrections": int(len(c)), "n_retail": int(len(r)),
           "timeboosted_corrections": share(c.tb), "timeboosted_contested": share(c.tb[y]),
           "timeboosted_uncontested": share(c.tb[~y]), "timeboosted_retail": share(r.tb),
           "n_contested": int(y.sum())}
    p = RESULTS_DIR / "study_i" / "timeboost.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(main())
