# BRO-AMM

**A Bonded Reconciliation Oracle AMM as a Low-Risk DeFi Primitive**: paper, measurement pipeline,
simulations and gas benchmarks.

BRO-AMM is a Uniswap v4 hook that executes swaps synchronously and reconciles each one after the
block against signed oracle prices. A price-correcting swap keeps an allowance per unit of volume,
discovered on-chain; extraction beyond it is recaptured for liquidity providers from stake posted
before trading. This repository holds the paper and everything behind its numbers: six months
(March–August 2026) of Ethereum mainnet and Arbitrum ETH/USDC data, the block-level simulation, and
Foundry benchmarks of the hook and settlement layer.

- **Paper:** [`paper.rendered.md`](paper.rendered.md) to read here; [`paper.md`](paper.md) is the
  source, with citations from [`references.bib`](references.bib). `make preprint` builds the PDF.
- **Author:** Tims Pecerskis (tim@peeramid.xyz)

## Results at a glance

Ethereum mainnet ETH/USDC, simulated over the six months against today's 5 bp pool, with BRO-AMM
charging 3 bp (paper §5.3, Table 3; stable costs):

| | Today, 5 bp | BRO-AMM, 3 bp |
|---|---|---|
| LPs' net | −\$3.15 M | \$3.37 M |
| Retail's price, all-in | 5.00 bp | 3.31 bp |
| Arbitrageurs' payments to block builders | \$6.57 M | \$1.09 M |
| Arbitrageurs' margin | \$0.38 M | \$0.51 M |

Across the three cost scenarios LPs end ahead of today by \$5.8–6.5 M, users trade at fresher prices,
and the pool stays as well rebalanced as today. Settlement costs 0.18× the execution gas of the swaps
it settles. Rollups need their own competition signal: Appendix I adapts the design to Arbitrum's
arrival-ordered sequencer, where a 4 bp pool leaves LPs \$0.4–0.6 M ahead of today's 5 bp pool.

## Reproducing

Every table and figure is generated from JSON committed under `results/`, so the paper and its
figures rebuild without downloading any data. Recomputing the results needs the raw data.

**Requirements.** [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11; for the paper, pandoc ≥ 3,
a TeX distribution with `xelatex`, and Graphviz; for the gas benchmarks,
[Foundry](https://getfoundry.sh); for the full pipeline, archive RPC endpoints for Ethereum and
Arbitrum in `.env` (`ETH_RPC_URL`, `ARB_RPC_URL`; never committed).

```sh
make setup             # virtualenv and dependencies
make test              # unit tests: timestamps, price_at, bid/ask proxy, labels, chains, q_LP

# 1. From committed results (no data needed)
make figures           # figures/*.png
make paper-rendered    # paper.rendered.md
make preprint          # dist/bro-amm-preprint.pdf (vector figures, article layout)

# 2. Studies from data on disk (after step 3 has run once)
make studies           # Studies A, B, Supp-1, D, H, I on the active chain
make paper-results     # the Study I runs behind §5 and Appendix F, on both chains
make settlement        # Study C (collateral) and K1–K4 (keepers, gas tank)
make study-g           # gas: receipts and traces over RPC, Foundry in contracts/ and zk/

# 3. Full pipeline from raw data
make all               # Binance archive → on-chain swaps → q_LP → control gate → studies
```

The chain is selected with `AMMBRO_CHAIN=mainnet|arbitrum` (default mainnet); per-chain results
are written under `results/` and `results/arbitrum/`. Every study scores swaps with one canonical
$Q_{\mathrm{LP}}$ (`pipeline/canonical.py`), and `make gate`, the USDC/USDT calm-period control,
must pass before any study runs against a pool.

## From the paper to the code

| Paper | Code | Results |
|---|---|---|
| §3.3 decision latency, Appendix B | `pipeline/study_e.py`, `timing_gaming.py` | `results/study_e/` |
| §5.2 score validity, extraction by position | `study_a.py`, `supp1.py`, `study_d.py`, `study_i_index.py` | `results/study_a/`, `supp1/`, `study_i/block_index.json` |
| §5.3 recapture under perfect information | `study_b.py` | `results/study_b/` |
| §5.3 Table 3 (lower fees, every correcting swap charged) | `study_i_ramp.py` (`baseline`, `fee4`), `router_risk.py` | `results/study_i/ramp_baseline.json`, `results/arbitrum/study_i/ramp_fee4.json`, `results/*router_risk*.json` |
| §5.3 Figure 4, Appendix C at today's fee | `study_i_headline.py`, `study_i_retention.py`, `study_i_routing.py`, `study_i_capture.py` | `results/study_i/{headline,retention,routing,capture}.json` |
| Appendix I (Arbitrum): sender rule, Timeboost, per-gap reverse auction | `study_i_ramp.py` (`timeboost`, `main`, `robust`, `steep`, `monopoly`, `fee4`) | `results/arbitrum/study_i/ramp_*.json` |
| Appendix G.5 router costs and charges | `router_costs.py`, `router_risk.py` | `results/router_costs.json`, `results/*router_risk*.json` |
| §4.4, §5.4 controllers, Appendix F.7 | `study_i.py`, `study_i_position.py`, `study_i_redundancy.py`, `study_i_paths.py`, `study_i_final.py` | `results/study_i/` |
| §4.4 Timeboost, Appendix B | `study_i_timeboost.py` (public Arbitrum RPC) | `results/arbitrum/study_i/timeboost.json` |
| §5.5 stake, fresh accounts, correction lane | `study_i_stake.py`, `study_i_relief.py` | `results/study_i/stake.json`, `relief.json` |
| Appendix F rejected designs | `study_i_review.py`, `study_i_bonus.py`, `study_i_rotation.py`, `study_i_relief.py` | `results/study_i/` |
| §5.6 collateral | `study_c_collateral.py` | `results/study_c/` |
| §5.7 oracle error | `study_j.py` | `results/study_j/` |
| §5.8 settlement gas, Appendix D | `study_g.py`, `contracts/`, `zk/` | `results/study_g/` |
| §5.8 keepers and gas tank | `study_k.py`–`study_k4.py`, `census.py` | `results/study_k/` |
| Figures | `pipeline/figures.py` | `figures/` |

`study_k5.py` and `klines.py` study a single REP shared across pools, which the
paper leaves to future work.

## Layout

```
paper.md, references.bib    paper source; paper.rendered.md is generated from them
pipeline/                   Python package: data ingestion, scoring, studies, figures
  config.py chains.py pools.py    window, symbols, chains and pools — single source of truth
  binance_*.py benchmark.py       Binance archive → ticks → price_at(t, h), bid/ask proxy (directional.py)
  extract_*.py rpc.py             swap logs and transaction metadata over paced JSON-RPC
  qlp.py canonical.py             the quality score Q_LP and its canonical per-chain variant
  labels.py routers.py            price-independent benign/toxic labels for validation
  blocksim.py study_i*.py         block-level simulation of payout rules and controllers
  study_*.py supp1.py             the studies above; figures.py draws every figure
contracts/                  Foundry: the v4 hook, record variants, reconciler, gas-tank paymaster
zk/                         Foundry: on-chain gas of one SP1 Groth16 verification
indexer/                    optional self-hosted Envio indexer for the pools (TypeScript)
tools/                      paper builds: pandoc filters, preprint template, diagram and Markdown renderers
tests/                      unit tests
results/                    committed study outputs (JSON), per chain
figures/                    committed figures (PNG)
docs/                       backtest specification and the settlement-layer design note
data/                       raw and derived data (gitignored); data/checksums/ is committed
```

## Data

- **Benchmark.** Binance public archive (aggTrades ticks for ETHUSDT and USDCUSDT), corrected to
  USDC and turned into a touch-level bid/ask proxy. Archive files are not redistributed;
  `data/checksums/CHECKSUMS.sha256` pins every file the pipeline uses. The archive is
  byte-reproducible but not signed, so oracle error is modelled (§5.7), not measured on a signed feed.
- **Timestamps.** Binance spot timestamps are milliseconds before 2025-01-01 and microseconds after;
  `binance_parse.normalize_ts_to_us` branches on magnitude and fails on ambiguity.
- **On-chain.** Uniswap v3 ETH/USDC 0.05% on mainnet and WETH/USDC on Arbitrum, with a USDC/USDT
  control pool on each chain, extracted over RPC. Raw extracts are gitignored.

## Citation

Pecerskis, T. (2026). *BRO-AMM: A Bonded Reconciliation Oracle AMM as a Low-Risk DeFi Primitive.*
Preprint. https://github.com/peersky/ammbro
