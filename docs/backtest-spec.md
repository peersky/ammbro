# Backtest spec — implementation-binding extract (REP-AMM master doc v0.2)

Extract of sections that bind this pipeline. Master doc lives with the
research author; this file tracks what the code must satisfy.

## Studies and gates (§17.1, §17.8)

| Study | Computation | Primary output | Gate |
|---|---|---|---|
| A | ROC of `q_LP` (sign+magnitude) vs. independent labels | AUC + overlaid q_LP histograms per class, sliced by trade size & block position | AUC > 0.75 on high-confidence labels |
| B | Simulate `final_fee = F(q_LP, cap)` sweep incl. fixed-fee baseline | Net LP surplus, gross LVR captured, **residual extraction (what arbs kept — §12.2, added v0.2)**, benign overcharge (bps), arb survival rate | Net LP surplus > fixed-fee baseline AND most price-correcting arb stays profitable |
| C | B under 4 conditions: fixed fee / markout+bond / +soulbound REP / +transferable concave REP | Per-condition surplus + benign false-positive rate | Keep REP only if (4) beats (2) |
| Supp-1 | position↔q_LP correlation, pre/post normalization | Correlation + quartile plots | informational |
| Supp-2 | Σmint vs Σburn | Supply drift | informational |

All at horizons {0, +12, +30, +60}s. Horizon fragility reported, never hidden.

## Scoring metric (§17.2 — q_LP, NOT the §5 price ratio)

```
LP_markout_i(h) = oracle_value(Δin_received) − oracle_value(Δout_sent)   # at benchmark price t_i + h
q_LP_i(h)       = LP_markout_i(h) / notional_i
```

Direction-free: overpayment in EITHER direction must come out LP-positive
without per-side negation (unit-tested). Pool-perspective raw deltas.

## v0.2 reporting requirement (§12.2)

Study B must report residual extraction — what arbs kept — alongside
captured LVR. The LP decision is comparative (`fees recaptured − residual
LVR` vs. vanilla pool vs. holding). Showing the residual voluntarily is
what makes the captured number credible. Honest ceiling: "LP pays only
the competitive price of rebalancing," never "LP pays nothing."

## Hard rules

- Labels must be independent of price deviation (privacy / position /
  identity / structure axes only) — circularity voids Study A (§14.2).
- USDC/USDT calm-period control gate (§17.3.2) must pass before ANY
  Study A/B/C result is read: calm-window |q_LP| on USDC/USDT must be
  consistent with the observable peg band (single-digit bps).
- Numeraire correction (ETHUSDT / USDCUSDT → ETH in USDC terms) applied
  everywhere, mandatory on tail days (§17.6).
- Layer 1 (signed oracle month) = signed truth; Layers 2–3 (Binance
  archive) = reproducible but unsigned. Never blur.
- Every Dune query committed; every input sha256 recorded; `make all`
  reproduces every figure.

## Order of construction (§17.9) — status

1. ✅ Binance downloader + checksum manifest + benchmark `price_at(t,h)` (ETHUSDT + USDCUSDT, 2026-03→2026-08, 72 files verified)
2. ✅ Swap extraction via Chainstack RPC (990,555 ETH/USDC + 221,708 USDC/USDT swaps, per-month parquet). Envio self-hosted indexer (indexer/) syncing in parallel as the durable/live source; tx meta (from/to/priority fee) comes with it.
3. ✅ q_LP join at horizons {0,12,30,60}s — full window scored.
3b. ✅ Control gate PASS (2026-09-02): |q_LP| median 0.80 bps / P95 2.09 bps on 221,708 control swaps vs 38.4 bps ceiling (3× peg P99 12.8 bps). First-look ETH/USDC (pre-label): size gradient <10k +3.41 bps (16% neg) → >100k −2.40 bps (78% neg); big-swap top-3-position 83.2% neg vs 58.4% mid-block; gross LP-negative markout ≈ $9.9M/6mo.
4. ✅ Labels join — DEVIATION: ZeroMEV API is dead (origin DNS gone, 2026-09-02) and Flashbots Dune mev_summary is stale; replaced with committed price-independent detectors (pipeline/labels.py): router-origin benign list, pool-local sandwich detector, searcher heuristic (first-in-direction + top-3 + non-router + repeat actor). 175,410 toxic / 119,114 benign / 665,000 unlabeled middle. Sandwich attacker labels near-zero (~100 victims/6mo) — same-actor sandwiches effectively extinct on this pool; toxic set is searcher-driven.
5. ✅ Study A (2026-09-02): **AUC(h=0) = 0.867 — gate (>0.75) PASSED.** Size slices: <10k 0.65, 10k–100k 0.91, >100k **0.978** (size is not a label input → clean evidence). Horizon decay 0.87→0.68 (h=0→60s): score at execution-instant truth. CAVEAT: position-sliced AUC is confounded (toxic label conditions on tx_index) — do not cite it as evidence; size slices are the defensible ones. Labels conservative → AUC is a lower-bound estimate. results/study_a/.
6. ✅ Supp-1 (results/supp1/): top-3 raw positions carry ~60% of extraction (83% LP-neg on >100k swaps) but $2.1M (21%) sits at index 10+ — un-raced adverse flow invisible to priority-keyed taxes. Toxic priority-fee spend ≈783 ETH (~$1.9M) vs $9.9M extracted; CAVEAT: builder payments via coinbase-transfer bundles are invisible to maxPriorityFeePerGas, so this understates builder revenue. Position-label confound noted (toxic label conditions on tx_index; use label-free position aggregates only).
7. ✅ Study B (results/study_b/, INCREMENTAL accounting — v3 swap deltas already embed the 5bp fee; q_LP is net of it):
   - Baseline as lived: **LP net −$1.93M/6mo** (external validity: matches "major pools net-unprofitable after LVR").
   - Best schedule (α=1.0, cap=100bp, f_benign=5bp): **LP net +$2.14M** (+$4.07M vs baseline), incremental capture 41% of LVR, residual extraction $5.84M (§12.2 reported), benign overcharge 0.05bp (negligible), arb survival 22.8% vs 23.8% baseline (96% of profitable arbs preserved).
   - Cutting f_benign to 1bp always loses money — benign flow is the revenue base; capture fraction ≈40% max matches §12's "tens of percent" expectation.
   - GATE: net-surplus PASS; survival read as relative (22.8/23.8 = most price-correcting arb stays profitable). CAVEAT: static replay, no behavioral response — capture is an upper bound on this schedule.
8. ☐ Study C ablation + Supp-2
9. ☐ Layer-1 signed-feed ingestion + §17.5 equivalence test (when dump arrives; do not block)
10. ☐ Replication pair Study A (BTC/USDC or WBTC/ETH), after gates clear
