# Backtest spec — implementation-binding extract

Binds the pipeline to two sources:

- **`§`** = REP-AMM master doc v0.2 (lives with the research author).
- **`P§`** = `paper.md` at repo root (abstract, §1–§4). Where the two
  disagree on the *mechanism*, the paper wins — it is what the results
  will be written up against. Revised 2026-09-30 after an alignment
  review against paper §1–§4.

This file tracks what the code must satisfy.

## Design objective (P§3.2) — binding on every mechanism study

> **Paying builders for inclusion or position must be useless.** A
> searcher's net payoff after reconciliation must not increase with what
> it pays for inclusion or block position. Competition then bids nothing
> to builders, and the value stays in the pool for LPs.

Arbs pay builders to be first because being first wins whatever
extraction they keep after reconciliation. That kept amount — §12.2
residual extraction net of real costs — is the pot MEV extras are paid
from. Two conditions, both necessary:

1. **Position-invariant scoring.** If the score depends on block position,
   position is worth buying. Study E: a single per-block anchor at
   `block_ts + L` is the only rule tested with nothing to buy; every
   position- or pool-order-dependent clock was gameable (one dust swap at
   $0.03 bought $11.31 of forgiveness per arb).
2. **Contestable rent ≈ competitive cost.** The charge must take
   extraction beyond an allowance `m` that covers the arb's real cost
   (base-fee gas + CEX hedge cost `h`). Real gas is 0.31% of LVR, so
   ~99.7% of today's LVR is rent. `m` must sit just above `h`: at
   `m ≤ h` arbs cannot cover costs and rebalancing stops (Study B hedge
   grid). `h` is private (CEX fee tiers) and changes over time, so no
   fixed `m` works: `m` is discovered by the allowance controller (Study
   C design, evidence in Study H).

**Test, reported by every schedule in Study B and every condition in
Study C:**

```
builder_bid_ceiling = Σ over LP-negative swaps of max(residual_i − gas_i − h·V_i, 0)
```

— the most rational arbs would pay builders in aggregate. Reported beside
today's value (baseline: full extraction net of real costs) and beside
arb survival on real costs, since driving the ceiling to 0 by killing
rebalancing is failure, not success.

## Studies and gates (§17.1, §17.8, P§4)

| Study | Computation | Primary output | Gate |
|---|---|---|---|
| A | ROC of `q_LP` (sign+magnitude) vs. independent labels | AUC + overlaid q_LP histograms per class, sliced by trade size & block position | AUC > 0.75 on high-confidence labels |
| B | **Ceiling:** perfect-information per-swap *cash* fee `F(q_LP, cap)` sweep incl. fixed-fee baseline | Net LP surplus, gross LVR captured, residual extraction (§12.2), **builder-bid ceiling**, benign overcharge (bps), arb survival (flat $10 and real cost) | Ceiling, not a mechanism result — see below |
| C | The P§4 mechanism under 4 conditions: (1) fixed 5bp / (2) P§4 curve + **cash bond** / (3) P§4 + **soulbound** REP / (4) P§4 + **transferable** REP | Per-condition net LP, captured, residual, **share of B ceiling**, **builder-bid ceiling**, benign effective fee, arb survival (real cost), REP concentration, unstaked-volume share | Keep REP only if (4) beats (2); keep transferability only if (4) ≥ (3) |
| D | Directional benchmark: bid/ask proxy vs trade-price vs mid (P§3.6) | `q_LP` under each benchmark; A and B(h0) re-run under directional | informational — quantifies leniency of P§3.6 rule |
| E | Timestamp sensitivity: point read vs kernel average over the virtual-time window (P§3.4, P§4.2) | `q_LP` spread per reconstruction; noise floor on the control pool | Sets `ε` for C |
| F | Competitor baselines (abstract: "existing solution incompleteness") | Capture / net LP for MEV tax, volatility-scaled fee, 0.05% vs 0.30% fee tier | informational — must be reported beside C |
| G | L1 viability (title, P§4.6) | Per-swap execution `gasUsed` vs estimated reconciliation gas | Reconciliation ≤ execution per swap |
| H | Allowance `m` controller: signal evidence, position-cutoff scoring, agent simulation on real gap-taking opportunities | Controller signals; cutoff TPR/FPR; per-controller LP recapture, builder payments, uncorrected gaps, `m` vs cheapest arb cost | informational — sets the Study C controller |
| Supp-1 | position↔q_LP correlation, pre/post normalization | Correlation + quartile plots | informational |
| Supp-2 | Σmint vs Σburn from the C replay; pool income vs θ* per epoch | Supply drift; distance from target | informational — static replay cannot test convergence |

Horizons: **h=0 is the definition** (P§4.2). +12s and +30s are the
paper's robustness cross-checks; +60s is kept as an extra. Horizon
fragility reported, never hidden.

## Why Study B is a ceiling, not the mechanism

Study B charges each swap a cash fee *after the fact* from its realized
`q_LP`. P§4.1 rules that out: the fee is final at execution, "no money
moves at reconciliation", and "cash cannot be recalled from a
counterparty who has departed". Extraction is punished by burning
staked REP, not by a cash charge.

So Study B is the most **any** per-swap, `q_LP`-keyed cash fee could
recapture with perfect information — per schedule form. Three forms are
swept: `clip(α|q|, f_benign, cap)` (original; exempts extraction below
f_benign, so capture tops out near 41–56%), `additive`
(`f_benign + α|q|`), and `margin` (`f_benign + max(|q| − m, 0)`, the
form that serves the design objective). It stays in the
pipeline as the yardstick: Study C results are reported as a share of
the B ceiling at the same horizon. **Never cite Study B numbers as the
REP-AMM result.**

## Study C — binding design (P§4.1–§4.5)

Replay all swaps in time order through the P§4 mechanism.

**Actor.** `tx.from` (the EOA). A v4 hook sees the router as `sender`,
so the paper must say how the hook identifies the trader (hookData /
`tx.origin`) — open item below. Until then `tx.from` is the assumption,
stated in every C output.

**Epoch.** Parameter; sweep {1 block, 1h, 1d}. Settlement is on the
actor's epoch aggregate, `q_agg = Σmarkout / Σnotional`, never per swap
(P§4.3).

**Fee at execution (final).** Coverage curve on the actor's **active**
stake `r`:

```
f(r, V) = f_min + (f_max − f_min) · exp(−r / (ρ·V))
```

`V` = actor's cumulative epoch volume including this swap. Capacity
`C = r/ρ` per epoch; volume beyond capacity pays `f_max`. Unstaked flow
pays `f_max`. Reference band `f_min = 1bp`, `f_max = 5%`.

**In-flight stake (P§4.5).** A trade moves `ρ·V` of stake from ACTIVE to
IN-FLIGHT until its epoch settles, so a second trade in the window sits
lower on the curve. Burns hit only the in-flight tranche. New stake
activates after an activation delay; exit needs an exit delay longer
than worst-case settlement with no flights pending.

**Burn (P§4.3).** If `q_agg < −ε`: burn `min(tranche, λ·|q_agg|^γ·V)`,
`γ ≥ 1` (convex, so splitting an extraction is strictly costlier).
Design condition to check, not assume: `λ·|q|·V·P_annuity ≥ (f_max −
f(r))·V`. **Sizing target (design objective):** the burn's value should
equal extraction beyond the allowance `m`, i.e. the Study B `margin`
schedule expressed in REP — so the rent left to bid to builders is
≈ `(m − h)·V`, not the full extraction.

**Allowance `m` controller (design objective; Study H).** `m` is set per
epoch (1 day) by a feedback loop, not fixed:

```
staleness(e) = share of correctable gaps left uncorrected in epoch e
             (correctable: some arb would profit at m = ∞; measured at
              reconciliation against the signed oracle)

if   staleness(e) > S*   (2%)     → m ← m × 2      rebalancing failing: raise fast
elif staleness(e) ≥ S_low (0.5%)  → m unchanged    near the cost cliff: hold
elif flag(e) > τ                  → m ← m × 0.8    visible rent: lower
else                              → m ← m × 0.95   default decay
```

- **Raise signal = staleness,** the direct measure of P§3.2's goal. It is
  the only signal that still works when `m` is below cost: arbs vanish,
  so their position and fees carry no information.
- **Lower signal = share of gap-takers at `tx_index ≤ 2`** (best rent
  signal in Study H, Youden J 0.329). `τ` = midpoint of today's rates for
  rent / no-rent gap-takers (0.64). Priority fee is readable at execution
  (`tx.gasprice − block.basefee`) but weaker (J ≤ 0.25) and ~45% of
  gap-takers hide their bid in coinbase transfers; index still sees them.
- **Tx index on-chain:** the EVM cannot read it at execution, but
  reconciliation can. Keepers post indices optimistically; any can be
  challenged inside the oracle retention window with a Merkle-Patricia
  proof against the block's `transactionsRoot`, the header authenticated
  via `BLOCKHASH` / EIP-2935. The pool-internal swap ordinal is free
  (hook counter). Coinbase transfers cannot be attributed per tx on-chain.
- **Asymmetric steps.** Fast up (×2) restores rebalancing within a day or
  two after a cost shock; slow down (×0.8 / ×0.95) avoids oscillating
  across the cost cliff. Symmetric ×2 / ÷2 oscillates (Study H: 7.6–12%
  uncorrected vs 1.0–1.8%).
- **Evasion bounds.** Hiding rent (index ≥ 3 and zero priority) only
  removes the faster lowering; it cannot raise `m`. Faking staleness
  means leaving gaps a competitor takes; only a dominant builder in its
  own blocks can, bounded by its block share through the epoch median.
- **Required in C:** agent simulation with behavioural response (x shrinks
  as staleness falls; arbs re-enter as `m` rises), and a joint stability
  check with the θ* mint valve — two feedback loops on the same flow.

**Mint (P§4.4).** Per epoch, `N = Σfees + Σmarkouts`,
`S = N − θ*·ΣV`. If `S > 0`, mint `σ·S` pro-rata to actors whose
`fees + benign markout > θ*·V_actor`. `σ` is a fixed protocol scalar;
no REP market price enters any internal formula. Minted REP auto-stakes
into the activation delay.

**Conditions (2)–(4) differ only in the collateral.**
- (2) cash bond: deposit valued at the same capital as the REP stake,
  same curve, slashed to LPs instead of burned.
- (3) soulbound: REP cannot move between actors.
- (4) transferable: REP can be bought at `P_REP` = capitalized value of
  the discount (abstract). Model an adversary with a budget to buy up to
  X% of supply and test cornering — P§2.2/§4.3 claim the curve's
  convexity makes that uneconomic; C must measure it.

**Bootstrap (no lookahead).** At launch nobody holds REP, so everyone
pays `f_max` = 100× today's fee. Seed REP by replaying the mint rule
over **2026-03→05** at the as-lived 5bp fee, then evaluate on
**2026-06→08**. The seed window strictly precedes the evaluation window.

**Elasticity.** Static replay at `f_max` = 5% is not credible: unstaked
flow would route elsewhere. Parameter `η` = fraction of unstaked volume
retained; sweep {0, 0.25, 1.0}. `η = 1` is the static upper bound and
must be labelled so. Also run `f_max ∈ {30bp, 5%}` as sensitivity.

**Parameter sweep (P§4.7).** θ*, f_min, f_max, ρ, σ, λ, γ, epoch,
activation/exit delay. `ε` comes from Study E, not a guess. `κ` is
listed in P§4.7 but undefined in P§4.3 — excluded until defined.

**q_LP input.** `arb_exit` directional q (Study D, P§4.2) on the Study E
timeline: kernel centered on `block_ts + L + h`, width 1s, L = 1.5s
measured. Columns `q_c_h{0,12,30}` in
`data/onchain/scored_timing/eth_usdc_005/q_c.parquet`. Forward-timeline
`q_LP` and `paper_literal` reported beside it as sensitivities.

**ε.** 1bp (Study E: per-swap timing noise P90 0.80bp at the chosen
1s kernel, notional-weighted 0.49bp; epoch aggregates average it down,
so 1bp is conservative). Sweep {0.5, 1, 2}bp. Sits on top of the
arb_exit bid/ask band, not instead of it.

## Study D — directional benchmark proxy (P§3.6)

The paper scores against Chainlink Data Streams LWBA: ask when the pool
sells the asset, bid when it buys. Until Layer-1 LWBA arrives, build a
bid/ask proxy from Binance `aggTrades` using the `isBuyerMaker` flag
(last buyer-initiated trade ≈ ask, last seller-initiated ≈ bid), with
the numeraire correction applied to each side. Report trade-price,
proxy-mid and directional `q_LP` side by side.

Two conventions (open item 8, resolved in favour of `arb_exit`):
- **`arb_exit`** — pool sends ETH → bid, pool receives ETH → ask. The
  price an arb can exit at; a no-flag band `[bid, ask]` that widens with
  the spread. The paper's rule since the P§3.6/P§4.2 fix.
- **`paper_literal`** — pool sends ETH → ask, receives → bid, as
  P§3.6/P§4.2 read before the fix. Flags MORE flow as the spread widens.
  Kept as a sensitivity only.

## Study E — timestamp sensitivity (P§3.4, P§4.2)

Compare `q_LP` from (a) block timestamp, (b) virtual-time point read
(`t_norm_us`, current), (c) kernel average of the price path over the
swap's plausible execution window. Measure when swaps were actually
priced (decision-time profile) and set `ε` from the timing noise at the
chosen kernel. The USDC/USDT control barely moves inside a slot, so it
bounds peg noise only and cannot calibrate timing noise.

## Study F — competitor baselines

Each on the same window and horizon, reported beside C:

- **MEV tax (P§2.8).** Counterfactual capture from a priority-fee tax.
  Only raced positions are reachable; Supp-1 already shows $2.1M (21%)
  of extraction at index 10+ that no priority race touches. Caveat: L1
  builder payments via coinbase transfer evade it — state as upper bound.
- **Volatility-scaled dynamic fee (P§2.7).** Fee as a function of
  benchmark realized volatility over a trailing window.
- **Fee tiers (P§1).** ETH/USDC 0.05% vs 0.30% pool
  (`0x8ad599c3a0ff1de082011efddc58f1908eb6e6d8`), LP net per $ of
  liquidity. Needs a second extraction.

## Study G — L1 viability (P§4.6)

Per-swap `gasUsed` from receipts on the ETH/USDC pool vs an estimated
reconciliation cost (one markout multiply-add, one tolerance compare,
one state write, signature verification amortized over the report's
validity window). The paper's bound is reconciliation ≤ execution.

## Study H — allowance `m` controller (design objective)

`pipeline/study_h.py`, `results/study_h/` (metrics + `m_controller.png`).

1. **Signals.** Gap-takers = the block's first pool swap, moved the pool
   toward the oracle at `block_ts + L`. Today's rent = extraction −
   base-fee gas − 1bp hedge.
2. **Cutoffs.** Every position / fee rule scored as a rent detector
   (TPR on rent-bearing gap-takers, FPR on no-rent ones, Youden J).
3. **Agent simulation.** 150,582 real LP-negative gap-taking
   opportunities, 184 daily epochs. Assumed arb population with hedge
   costs {0.3, 0.6, 1.0, 1.5, 2.5}bp; cheapest wins, pays the builder the
   second-best net (second-price for the top slot). Costs ×2 or ×4 from
   2026-06-01 to test tracking. Controller signals resampled from (1).
   Assumed cost population, static opportunity set, today's signal
   rates — shows controller dynamics, not a dollar forecast.

## Scoring metric (§17.2, P§4.2 — q_LP, NOT the §5 price ratio)

```
LP_markout_i(h) = oracle_value(Δin_received) − oracle_value(Δout_sent)   # at benchmark price t_i + h
q_LP_i(h)       = LP_markout_i(h) / notional_i
```

Direction-free: overpayment in EITHER direction must come out LP-positive
without per-side negation (unit-tested). Pool-perspective raw deltas.
Under the directional benchmark `oracle_value` follows the `arb_exit`
convention (Study D; P§3.6/P§4.2).

## v0.2 reporting requirement (§12.2)

Study B and Study C must report residual extraction — what arbs kept —
alongside captured LVR. The LP decision is comparative (`fees recaptured
− residual LVR` vs. vanilla pool vs. holding). Showing the residual
voluntarily is what makes the captured number credible. Honest ceiling:
"LP pays only the competitive price of rebalancing," never "LP pays
nothing."

## Hard rules

- Labels must be independent of price deviation (privacy / position /
  identity / structure axes only) — circularity voids Study A (§14.2).
- USDC/USDT calm-period control gate (§17.3.2) must pass before ANY
  study result is read: calm-window |q_LP| on USDC/USDT must be
  consistent with the observable peg band (single-digit bps).
- Numeraire correction (ETHUSDT / USDCUSDT → ETH in USDC terms) applied
  everywhere, mandatory on tail days (§17.6).
- Layer 1 (signed oracle month) = signed truth; Layers 2–3 (Binance
  archive) = reproducible but unsigned. Never blur.
- Study B is a ceiling. Never cite it as the REP-AMM mechanism result.
- Every Study B schedule and Study C condition reports the builder-bid
  ceiling and real-cost arb survival together.
- Study C bootstrap: seed window strictly precedes evaluation window.
- Every Study C output states its actor definition, `η`, and `f_max`.
- Every Dune query committed; every input sha256 recorded; `make all`
  reproduces every figure.

## Open items for the paper (resolve in `paper.md`, not in code)

1. **Abstract vs P§4.1.** Abstract says arbitrageurs "face increased
   fees" via retroactive reconciliation; P§4 makes the fee final at
   execution and punishes via REP burn (higher *future* fees). Abstract
   should say so.
2. **Concave vs convex.** Spec and P§2.2/§2.7 say "concave curve"; P§4.3
   says the fee is "decreasing and convex in r". Both hold for different
   quantities (discount concave, fee convex) — pick one term.
3. **`κ`** is listed in P§4.7 but never defined in P§4.3.
4. **Horizons.** Paper: +12s/+30s. Pipeline also runs +60s. Align.
5. **Actor identity in a v4 hook.** `sender` is the router; the paper
   must say how the trader is identified.
6. **Bootstrap.** `f_max` = 5% for unstaked flow needs a launch story
   (retroactive seeding from history?) — P§2.5 mentions a
   "retroactive-bootstrap means" without specifying it.
9. **Virtual time plane (P§3.4) is not supported by the data.** P§3.4
   spreads a block's txs across the block interval by index. Study E
   finds index is not time: top-of-block arbs price at ≈ block_ts + 1.5s
   (after the slot label, because blocks are published into the slot),
   and mapping deeper txs forward in time is lookahead — it prices them
   against prints from after the block was sealed. A single per-block
   anchor at `block_ts + L` scores as well as any index spread
   (block_L AUC 0.886 = backward_L 0.886 > forward 0.852). Suggest
   rewriting P§3.4 around a measured per-block decision latency.
10. **Kernel window (P§4.2) must be centered on the decision instant and
   narrow.** A trailing window `[block_ts − w, block_ts]` scores arbs
   against pre-move prices: at w = 12s the baseline LP P&L flips from
   −$0.58M to +$5.26M and AUC drops to 0.753. Centered on `block_ts + L`
   at w = 1s it is stable (AUC 0.889). P§4.2 should state both the
   anchor and the width, and cite ε ≈ 1bp from Study E.
11. **Allowance `m` and its controller belong in P§4.** P§4.7's
   undefined `κ` ("covers the divergence range where extraction
   empirically concentrates") is best defined as the allowance `m` of the
   margin schedule, and P§1's claim that the fee becomes "a useful
   dynamic variable" is substantiated by the Study H controller — a
   second feedback valve beside the θ* mint valve of P§4.4. Suggest a
   P§4.3 paragraph: burn sized to extraction beyond `m`; `m` set per
   epoch by staleness (raise) and top-slot share (lower).
8. ~~**Bid/ask assignment reversed relative to its stated purpose.**~~
   RESOLVED 2026-09-30: P§3.6/P§4.2 now read bid-when-pool-sells /
   ask-when-pool-buys, matching `arb_exit`. `arb_exit` is the paper's
   rule; `paper_literal` stays in Study D only as a sensitivity.
7. **Promised studies.** P§3.6 cites a benchmark-equivalence study
   ("§N") and P§4.2 a timestamp-sensitivity study (§5) — now Studies D
   and E; the paper's cross-refs need numbers.

## Order of construction (§17.9) — status

1. ✅ Binance downloader + checksum manifest + benchmark `price_at(t,h)` (ETHUSDT + USDCUSDT, 2026-03→2026-08, 72 files verified)
2. ✅ Swap extraction via Chainstack RPC (990,555 ETH/USDC + 221,708 USDC/USDT swaps, per-month parquet). Envio self-hosted indexer (indexer/) syncing in parallel as the durable/live source; tx meta (from/to/priority fee) comes with it.
3. ✅ q_LP join at horizons {0,12,30,60}s — full window scored.
3b. ✅ Control gate PASS (2026-09-02): |q_LP| median 0.80 bps / P95 2.09 bps on 221,708 control swaps vs 38.4 bps ceiling (3× peg P99 12.8 bps). First-look ETH/USDC (pre-label): size gradient <10k +3.41 bps (16% neg) → >100k −2.40 bps (78% neg); big-swap top-3-position 83.2% neg vs 58.4% mid-block; gross LP-negative markout ≈ $9.9M/6mo.
4. ✅ Labels join — DEVIATION: ZeroMEV API is dead (origin DNS gone, 2026-09-02) and Flashbots Dune mev_summary is stale; replaced with committed price-independent detectors (pipeline/labels.py): router-origin benign list, pool-local sandwich detector, searcher heuristic (first-in-direction + top-3 + non-router + repeat actor). 175,410 toxic / 119,114 benign / 665,000 unlabeled middle. Sandwich attacker labels near-zero (~100 victims/6mo) — same-actor sandwiches effectively extinct on this pool; toxic set is searcher-driven.
5. ✅ Study A (2026-09-02): **AUC(h=0) = 0.867 — gate (>0.75) PASSED.** Size slices: <10k 0.65, 10k–100k 0.91, >100k **0.978** (size is not a label input → clean evidence). Horizon decay 0.87→0.68 (h=0→60s): score at execution-instant truth. CAVEAT: position-sliced AUC is confounded (toxic label conditions on tx_index) — do not cite it as evidence; size slices are the defensible ones. Labels conservative → AUC is a lower-bound estimate. results/study_a/.
6. ✅ Supp-1 (results/supp1/): top-3 raw positions carry ~60% of extraction (83% LP-neg on >100k swaps) but $2.1M (21%) sits at index 10+ — un-raced adverse flow invisible to priority-keyed taxes. Toxic priority-fee spend ≈783 ETH (~$1.9M) vs $9.9M extracted; CAVEAT: builder payments via coinbase-transfer bundles are invisible to maxPriorityFeePerGas, so this understates builder revenue. Position-label confound noted (toxic label conditions on tx_index; use label-free position aggregates only).
7. ✅ Study B — **reframed 2026-09-30 as the perfect-information cash-fee ceiling** (see above; not the P§4 mechanism). results/study_b/, INCREMENTAL accounting — v3 swap deltas already embed the 5bp fee; q_LP is net of it:
   - Baseline as lived: **LP net −$1.93M/6mo** (external validity: matches "major pools net-unprofitable after LVR").
   - Best schedule (α=1.0, cap=100bp, f_benign=5bp): **LP net +$2.14M** (+$4.07M vs baseline), incremental capture 41% of LVR, residual extraction $5.84M (§12.2 reported), benign overcharge 0.05bp (negligible), arb survival 22.8% vs 23.8% baseline (96% of profitable arbs preserved).
   - Cutting f_benign to 1bp always loses money — benign flow is the revenue base; capture fraction ≈40% max matches §12's "tens of percent" expectation.
   - GATE: net-surplus PASS; survival read as relative (22.8/23.8 = most price-correcting arb stays profitable). CAVEAT: static replay, no behavioral response — capture is an upper bound on this schedule.
   - Horizon sweep (2026-09-30, headline schedule held fixed, all 990,555 swaps scored at every h):

     | h | baseline net | headline net | Δ vs baseline | capture | residual | benign overcharge | survival ratio ($10 gas) |
     |---|---|---|---|---|---|---|---|
     | 0s | −$1.93M | +$2.14M | +$4.07M | 41% | $5.84M | 0.05bp | 0.958 |
     | 12s | −$2.96M | +$2.70M | +$5.66M | 48% | $6.20M | 0.17bp | 0.920 |
     | 30s | −$3.04M | +$4.10M | +$7.14M | 53% | $6.36M | 0.40bp | 0.871 |
     | 60s | −$3.20M | +$5.63M | +$8.83M | 57% | $6.55M | 0.77bp | 0.821 |

     Net-surplus gate PASSES at every horizon, and the headline schedule stays best at every h *within the original clip grid (caps ≤ 100bp)*; the 2026-10-01 grid below adds forms that beat it. Surplus GROWS with h rather than decaying. Checked it is not an asymmetric-fee noise tax: benign-labeled capture is ≤$0.06M at every h, and the growth lands on toxic-labeled flow (2.15→5.76M, 53%→65% of capture). Reading: toxic markout keeps deepening for ~60s after execution (informed flow), matching baseline LP loss deepening −1.93→−3.20M. Unlabeled middle carries 34–47% of capture, composition unknown.
     The cost of longer horizons is on the survival side, not surplus: survival ratio falls 0.958→0.821 at $10 gas. **h0 stays the headline** — smallest claim, fastest settlement, best arb survival. Longer-horizon surplus must not be cited as upside without the survival cost beside it.
   - Gas sensitivity (survival ratio headline/baseline): h0 holds ≥0.85 across flat $2–$50 and the base-fee model (0.996). Fragile corner is long horizon × high gas: h60 at $50 → 0.509, h30 at $50 → 0.588 — roughly half of profitable arbs killed. Base-fee model (base fee × 250k gas) is a LOWER bound on cost: omits priority fees and coinbase-transfer builder payments; true cost sits between it and the flat sweep.
   - **Design-objective sweep (2026-10-01).** Forms `clip` / `additive` / `margin`, caps up to 500bp (= f_max), real-cost survival (base fee × 250k gas + hedge `h` = 1bp assumed), builder-bid ceiling. Today (baseline, h0): ceiling **$8.68M** of $9.91M LVR; 47.6% of LP-negative swaps cover real costs incl. a 1bp hedge (LP-negative ≠ arb — half are too small to be arbs).

     | h0 schedule | capture | LP net | builder-bid ceiling | vs today | survival (real cost) vs today |
     |---|---|---|---|---|---|
     | today, fixed 5bp | — | −$1.93M | $8.68M | 1.00 | 1.00 |
     | clip α1 cap100 (old headline) | 41% | +$2.14M | $4.62M | 0.53 | 0.99 |
     | **margin m=2bp cap500 (objective)** | **73%** | **+$5.32M** | **$1.44M** | **0.17** | **0.96** |
     | margin m=1bp cap500 | 83% | +$6.24M | $0.54M | 0.06 | 0.00 |
     | additive α1 cap500 (max capture) | 95% | +$7.44M | $0.54M | 0.06 | 0.00 |

     - Old headline leaves half the rent to bid; the objective schedule cuts it to 17% while keeping 96% of cost-covering arbs.
     - **`m` must sit above the hedge cost `h`.** Hedge grid (margin, cap 500): m=1bp is fine if h=0 (survival 0.965 of today, ceiling 0.17) and fatal if h=1bp (survival 0). m=2bp at h=1bp: 0.958 / 0.166. m=5bp is robust to h≤2bp but leaves 28–44% of rent. `h` is private, so `m` is the parameter the objective hinges on.
     - **$0.54M floor:** extraction beyond the 500bp cap. No cash schedule reaches it; in P§4 it is the part routed to REP burn.
     - Across horizons the objective schedule's ceiling is flat (~$1.4M) while today's rent grows ($8.68M → $14.34M at h60), so its share falls 0.17 → 0.10. Cost: real-cost survival 0.96 → 0.88 and benign overcharge 0.09 → 1.13bp at h60. h0 stays the reference.
     - CAVEATS: forward timeline, trade-price q (re-base pending 9b); static replay; `h` assumed; ceiling counts residual net of *base-fee* gas only — priority fees and builder payments are the extras being measured, not costs.
7b. ✅ Supp-1 at all horizons (2026-09-30). The P§2.8 claim holds at every h: index-10+ (un-raced) extraction $2.11M / $2.32M / $2.55M / $2.85M at h = 0/12/30/60s, share 21.3% / 19.5% / 18.9% / 18.5%. Top-3 share rises 59.9% → 64.8% — later-horizon deepening concentrates slightly in raced positions, but the un-raced floor never drops below ~19%.
8. ✅ Study D (2026-09-30, results/study_d/, `make study-d`). Touch proxy from `is_buyer_maker`, composed spread median 0.22bp / P90 1.9bp / P99 4.4bp; per-side staleness median ~0.75s (bursty prints — at a random instant the last print on a side is often ~1s old); raw ETH sides cross 4.4% before bounding.

     | benchmark (h0) | LP-neg share | gross LVR | baseline net | headline net | Δ vs baseline | capture | survival ratio | AUC | AUC >100k |
     |---|---|---|---|---|---|---|---|---|---|
     | trade | 29.0% | $9.91M | −$1.93M | +$2.14M | +$4.07M | 41% | 0.958 | 0.867 | 0.978 |
     | mid | 27.9% | $9.83M | −$1.80M | +$2.28M | +$4.08M | 41% | 0.958 | 0.860 | 0.977 |
     | arb_exit | 23.7% | $9.22M | −$0.77M | +$3.11M | +$3.88M | 42% | 0.955 | 0.852 | 0.975 |
     | paper_literal | 33.1% | $10.56M | −$2.84M | +$1.49M | +$4.33M | 41% | 0.962 | 0.861 | 0.977 |

   - **Robust to the benchmark:** Study A gate (AUC 0.852–0.867) and the Study B recapture (+$3.88M to +$4.33M, capture 41–42%, survival ratio 0.955–0.962). Same pattern at every horizon. Mid ≈ trade (0.22bp median spread), so trade-price was already a fair mid.
   - **Sensitive to the benchmark:** the size of the problem. Baseline LP net is −$0.77M under `arb_exit` vs −$1.93M trade vs −$2.84M literal; 5.3pp of swaps sit inside the bid/ask band. P§1's "net-unprofitable" still holds under every convention, but under the paper's intended rule the LP loss is 60% smaller than the trade-price figure. Cite the baseline with its convention, never bare.
   - Control gate passes under all four (|q| P95 1.92–2.25bp vs 38.4bp ceiling).
   - CAVEAT: touch proxy, not LWBA. Depth-weighted spreads are wider for size, so `arb_exit` under real LWBA would flag less still, mostly on large trades. Layer-1 LWBA replaces this (item 13).
9. ✅ Study E (2026-09-30, results/study_e/, `make study-e`). All figures arb_exit, h0.
   - **Decision latency L = +1.5s after block_ts.** Fee-adjusted residual between the pool's post-swap price (Swap tick) and the CEX side an arb hedges at, minimized over offsets −24s…+6s, on 154,899 toxic top-3 swaps. Bracketed against proxy staleness: last-print quote (lags, biases late) +1.75s, next-print quote (leads, biases early) +1.25s → L = 1.5s; fresh-quotes-only (<100ms, 3% of instants) +1.0s. Benign flow shows no relation (flat), as it should. Mechanism: `block_ts` is the slot label; blocks are published ~1–2s into the slot (MEV-Boost timing games) and arbs quote until the final bid is taken. Their own reaction time is milliseconds.
   - Results are insensitive inside the bracket and sensitive to leaving it:

     | anchor | LP-neg | gross LVR | baseline net | Δ headline | AUC | AUC >100k |
     |---|---|---|---|---|---|---|
     | block_ts (L=0) | 22.1% | $9.03M | −$0.58M | +$3.78M | 0.862 | 0.977 |
     | forward t_norm (current pipeline) | 23.7% | $9.22M | −$0.77M | +$3.88M | 0.852 | 0.975 |
     | block_ts + 1.0s | 23.4% | $9.55M | −$1.38M | +$3.96M | 0.882 | 0.983 |
     | block_ts + 1.5s | 23.9% | $9.72M | −$1.59M | +$4.05M | 0.886 | 0.982 |
     | block_ts + 1.75s | 24.2% | $9.82M | −$1.70M | +$4.12M | 0.886 | 0.982 |
     | **centered on +1.5s, w=1s (C input)** | — | — | −$1.58M | +$4.02M | **0.889** | **0.984** |
     | trailing [bt−12s, bt] (pitfall) | 10.8% | $5.59M | **+$5.26M** | +$2.51M | 0.753 | 0.931 |

   - **Forward timeline (all studies so far) is lookahead for mid-block swaps** and scores slightly worse than a single per-block anchor. Anchoring at the decision instant raises AUC 0.852 → 0.889 and deepens baseline LP loss −$0.77M → −$1.58M; the Study B recapture is stable (+$3.88M → +$4.02M).
   - **ε = 1bp.** Per-swap timing noise at the chosen kernel: P50 0.0bp, P90 0.80bp, notional-weighted 0.49bp (>$100k P50 0.15bp). Wider kernels add noise (w=4s: P90 1.67bp).
   - Control pool |q| P95 2.25bp under every reconstruction — peg noise, not timing noise.
   - Position-gaming tests committed (`pipeline/timing_gaming.py`, `position_gaming` in results/study_e): orientation of index time planes, pool-internal clocks and their attacks, and the post-swap-distance metric — source of the figures cited in the design objective.
   - CAVEATS: touch proxy (Study D caveat applies); L measured on gap-closing flow only — mid-block swaps show no pool↔CEX relation, so their decision times are not identified and they share the block anchor by assumption.
9b. ☐ Re-base Study A, Study B, Supp-1 and Study D on the Study E timeline (currently forward `t_norm_us`). Numbers above give the expected direction: AUC up, baseline LP loss deeper, recapture stable.
10. ☐ Study C + Supp-2 (depends on 8, 9). Bootstrap Mar–May, evaluate Jun–Aug.
11. ☐ Study F — competitor baselines (needs 0.30% ETH/USDC pool extraction).
11c. ✅ Study H (2026-10-01, `make study-h`). Allowance `m` controller.
   - **Block thirds are not a rent signal.** Thirds rule (first third → lower) flags 99.4% of rent-bearing gap-takers and 94.0% of no-rent ones (J 0.054). The raise zone (last third) almost never occurs: 0.2% / 2.1%. DEX flow sits high in blocks regardless of rent, and the *fraction* of a block is diluted by block size. The informative boundary is absolute: **`tx_index ≤ 2`** (TPR 0.806, FPR 0.477, J 0.329); `≤ 3` is equivalent (0.324). AUC: lower index 0.697, lower block fraction 0.661, priority fee 0.573.
   - **Simulation, arb costs ×4 on 2026-06-01** (window totals, $M):

     | controller | LP recapture | builder payments | arb margin | uncorrected (mean) | gaps left | `m` before → after (bp) | arb keeps (bp) |
     |---|---|---|---|---|---|---|---|
     | today, no reconciliation | 0.00 | **4.81** | 0.49 | 0.0% | 0.00 | — | 3.72 → 6.09 |
     | static m = 1bp | 3.47 | 0.23 | 0.19 | **50.5%** | **1.78** | 1.00 → 1.00 | 0.92 → **0.00** |
     | static m = 2bp | 4.18 | 0.72 | 0.40 | 0.1% | 0.00 | 2.00 → 2.00 | 1.54 → 1.91 |
     | static m = 5bp | 2.84 | 1.97 | 0.49 | 0.0% | 0.00 | 5.00 → 5.00 | 2.45 → 3.39 |
     | thirds rule, ×2 / ÷2 | 0.51 | 0.13 | 0.03 | **97.4%** | **5.16** | 0.05 → 0.05 | 0.00 → 0.00 |
     | staleness + flag, ×2 / ÷2 | 4.67 | 0.18 | 0.35 | 7.6% | 0.14 | 0.47 → 2.14 | 0.46 → 1.97 |
     | staleness + flag, ×1.25 / ×0.8 / 0.95 | 4.47 | 0.30 | 0.21 | 5.1% | 0.39 | 0.47 → 1.69 | 0.47 → 1.65 |
     | **staleness 3-zone, ×2 up / ×0.8 / 0.95** | **4.59** | **0.36** | 0.32 | **1.8%** | **0.04** | **0.62 → 2.24** | **0.59 → 2.05** |

     ×2 scenario: proposed 4.85 / 0.36 / 1.0% uncorrected vs today 0 / 5.11; static 1bp is best in hindsight (4.94 / 0.23 / 0.9%) only because the cheapest arb's cost stayed below 1bp.
   - **Market-driven payouts.** The controller never sees arb costs, yet `m` settles just above the cheapest arb's cost (0.3 → 0.62bp; 1.2 → 2.24bp after ×4) and what arbs keep tracks it (0.59 → 2.05bp). Builder payments fall from $4.81M to $0.36M (−93%); LP recapture $4.59M. The arb payout is set by competition among arbs, not by a hardcoded parameter.
   - **No fixed `m` survives a regime change:** 1bp kills rebalancing after the shift (100% uncorrected, $1.78M of gaps); 2bp survives but leaves builders 2× the controller's payments; 5bp leaves 5.5×.
   - **The thirds rule collapses:** almost every epoch reads "first third", `m` halves to the floor within days, rebalancing stops, and the first swap in each block becomes user flow that also sits high — so no raise signal ever fires.
   - **Why asymmetric + hold band:** symmetric ×2 / ÷2 oscillates across the cost cliff (7.6% uncorrected); slow symmetric steps recover slowly after a shock ($0.39M gaps); the 0.5–2% hold band stops decay before the cliff and ×2 up recovers in ~2 epochs ($0.04M).
   - CAVEATS: assumed arb cost population and second-price auction; static opportunity set (no behavioural response); signal rates from today's cross-section; builder payments are model output (11b measures reality). Residual hunting remains — single 100% days when decay crosses the cliff (visible in the figure).
11b. ☐ Measure today's actual builder payments by gap-takers: priority fee × gasUsed (receipts) + coinbase transfers (traces or fee-recipient balance deltas). The "before" number the design objective drives toward 0; Supp-1 sees only the priority part (~$1.9M, estimated).
12. ☐ Study G — L1 gas viability (receipts).
13. ☐ Layer-1 signed-feed ingestion + §17.5 equivalence test (when dump arrives; do not block). Replaces D's proxy with real LWBA.
14. ☐ Replication pair Study A (BTC/USDC or WBTC/ETH), after gates clear.
