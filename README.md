# REP-AMM backtest — data pipeline

Data layer for REP-AMM backtest (spec §17). Layer 2/3 benchmark: Binance
public archive (free, reproducible-but-unsigned). Layer 1 signed-oracle
month ingested separately when dump arrives.

## Current scope

- Symbols: **ETHUSDT** (primary benchmark), **USDCUSDT** (numeraire
  correction, §17.6 — mandatory on depeg/tail days).
- Window: **2026-03-01 → 2026-08-31** (past 6 months). Monthly zips
  Mar–Jul; daily zips for Aug (monthly not yet published). Extend toward
  post-Merge era later per §17.3 — do NOT drag pre-Merge regime in.
- Granularity: **native aggTrades ticks (canonical)** — event-level,
  µs timestamps, finer than 50ms. Derived **50ms and 250ms last-price
  bars** built as convenience layer. Scoring must consume ticks via
  `price_at(t, h)`, never bars.

## Pipeline order (§17.9)

```
make data      # download + checksum-verify Binance zips, parse to Parquet, derive bars
make onchain   # swap extraction, tx meta, q_LP scoring, control gate, labels
make studies   # Study A, Study B, Supp-1, Study D, Study E, Study H, Study I
make all       # all three, in order
make test      # mandatory unit tests (timestamp boundary, price_at, numeraire, labels)
```

`make gate` (inside `onchain`) is the USDC/USDT calm-period control
(§17.3.2). It exits non-zero on failure, so no study target can run
against a pool that failed it.

Remaining per §17.9: Study C ablation + Supp-2, Layer-1 signed-feed
ingestion, replication pair. Status tracked in `docs/backtest-spec.md`.

## Reproducibility rules

- `data/checksums/CHECKSUMS.sha256` is committed; raw zips are not
  (Binance data terms — never re-host).
- Honest framing: Binance archive data is **byte-reproducible, not
  cryptographically signed truth**. Only the Layer-1 signed-oracle month
  is signed. Never blur this in the writeup (§17.10).
- Timestamp trap: Binance SPOT timestamps are ms before 2025-01-01,
  µs after. `binance_parse.normalize_ts_to_us` branches on magnitude and
  hard-errors on ambiguity; tested in `tests/test_timestamp_boundary.py`.

## Layout

```
pipeline/
  config.py             window, symbols, horizons, paths — single source of truth
  binance_download.py   archive fetch + checksum verification + manifest
  binance_parse.py      zip → Parquet, timestamp normalization
  benchmark.py          PriceSeries.price_at(t_us, h), numeraire correction, bars
  pools.py  rpc.py      pool defs; batched JSON-RPC client (Chainstack)
  extract_swaps.py      v3 Swap logs → per-month Parquet
  extract_txs.py        tx meta (from/to/priority fee) for the extracted swaps
  qlp.py                q_LP join at horizons {0,12,30,60}s
  control_gate.py       §17.3.2 USDC/USDT calm-period gate
  labels.py  routers.py price-independent labels (§14.2); router-origin list
  study_a.py            ROC of q_LP vs labels
  study_b.py            fee-schedule ceiling (clip/additive/margin), residual (§12.2), builder-bid ceiling
  supp1.py              position ↔ q_LP correlation
  directional.py        bid/ask proxy from aggTrades aggressor flag (P§3.6)
  study_d.py            directional-benchmark re-score of A and B
  study_e.py            timestamp sensitivity, decision latency, ε; writes Study C input
  timing_gaming.py      position-gaming tests (orientation, pool clocks, attacks) for Study E
  study_h.py            allowance-m controller: signals, cutoffs, agent simulation
  blocksim.py           block-level inputs from data on disk: oracle per block, depth, user flow
  study_i.py            block-level payout-rule comparison (rebalanced every block, LP P&L)
  v4_probe.py           v3 vs v4 ETH/USDC volume and depth over the window (RPC only)
  l2_probe.py           Base / Arbitrum / HyperEVM pool load, gas per swap, block gas limits (latest hour)
  export_indexer.py     read the Envio postgres (durable/live source)
indexer/                self-hosted Envio indexer (TypeScript)
sql/                    committed queries
data/
  raw/binance/...       zips (gitignored)
  parquet/aggTrades/    ticks, one file per symbol-month (gitignored)
  bars/{50ms,250ms}/    derived bars (gitignored)
  onchain/              swaps, txs, scored, labels (gitignored)
  checksums/CHECKSUMS.sha256   committed manifest
results/                committed metrics.json + figures
tests/                  §17.9 mandatory unit tests
docs/backtest-spec.md   implementation-binding spec extract + build status
```
