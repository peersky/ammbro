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
| I | Block-level simulation of arb payout rules (all 1.32M blocks, real oracle path, real user flow, optimizing arbs) | Per rule: LP net P&L, builder payments, share of blocks within fee + 1bp, user-side staleness, uncorrected hours, overshoot | Choose the rule: best worst-case LP gain among rules that keep the pool rebalanced in every scenario (within-band share ≥ today − 0.5pp and user staleness ≤ today + 0.1bp; block-time-neutral, revised 2026-10-02) |
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

**Charge granularity (P§4.3/§4.8, 2026-10-01).** The job charge is computed **per price-correcting swap**, not gated on an account's epoch aggregate: an aggregate gate lets an intermediary net its customers' overpayments against its own extraction (laundering). Non-correcting swaps are never charged. Benign-labelled correcting swaps took at most ~$0.01M over the window, so the cost to ordinary users is negligible. Arbitrage is a role carried by a swap, not an identity.

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

**Payout rule (Study I).** The arb keeps, per trade,

```
kept = ∫ min(marginal edge, m) dV  +  min(base-fee gas of the trade, remaining extraction)
```

i.e. rent capped **per unit along the trade's price path** (not on the
trade's average edge), plus reimbursement of the trade's actual base-fee
gas. Everything else is recaptured for the LP. The reconciler knows the
pre/post pool price, the oracle and the receipt, so both terms are
computable ex-post. The average-edge form (`min(x̄, m)·V`, used in Study
B/H) is REJECTED: it pays `m` per unit while the average stays above `m`,
so arbs trade past the oracle to inflate volume (Study I: 2× volume,
30k overshoot blocks, users trade against a 40% staler pool). A position
premium is REJECTED: it buys no rebalancing and is bid away to builders
(~$0.13M per 0.1bp over the window).

**Feasibility (binding: every component must be implementable as a v4
hook + reconciliation on L1).**

| component | needs | feasible how | status |
|---|---|---|---|
| recapture `E − kept` after the fact | money from a counterparty who has left | NOT as cash (P§4.1). Only against stake locked before trading, collected in order: the trade's parked stake → the rest of the same account's stake (exit blocked while flights pend) → a per-pool reserve funded by an explicit protocol take (P§4.5, adopted 2026-10-01). Never from other traders' stake. | adopted |
| per-unit cap `∫ min(edge, m)` | the trade's price path | afterSwap records pre/post sqrtPrice + liquidity; closed form for constant liquidity (most arb trades move < one tick spacing); tick-crossing trades recomputed off-chain from pool state, posted optimistically, challengeable | feasible |
| gas reimbursement | gas cost of the tx | `block.basefee × fixed gas units` (readable at execution) instead of the receipt's gasUsed | feasible |
| oracle at `block_ts + L` | signed price at the decision instant | Data Streams report per block with a swap, verified once per block and amortized over its swaps | feasible |
| staleness (raise) | whether profitable corrections were skipped | **self-referential, no arb-cost knowledge:** among blocks whose resting gap exceeds `f + m + ε`, share where the first swap did not move the pool toward the oracle — needs only resting price, report, first swap's direction | feasible (`ctl_feasible`) |
| "contested" (lower) | whether a second arb could also profit | not observable. Proxies: top-slot share (tx index, optimistic Merkle proof; J 0.33) or priority fee (readable at execution; J ≤ 0.25) | proxy only |
| correctable-block staleness, arb costs | private arb costs | not observable | simulation-only yardstick |

Study I's `ctl_fast` uses the two unobservable signals and is an UPPER
BOUND. **Chosen design = `ctl_feasible`** (hourly ×2 raise on the
self-referential signal when ≥ 5 stale blocks and > 2%; daily ×0.95 decay
when the signal < 1%; nothing else): LP +$2.26M stable / +$1.81M after
×4 / +$1.38M after ×8, rebalancing within 0.07% / 0.28% / 0.43% of today.
Worst-case gain vs today +$5.07M — first among implementable designs; the
best fixed `m` that survives all three scenarios (5bp) reaches only
+$3.68M, and 2bp breaks at ×8 (84% uncorrected). Any fixed `m` is a bet
on how high arb costs can go. The ~$0.55–0.9M gap to `ctl_fast` is the
value of a competition signal; Study C tests the feasible proxies.

**Allowance `m` controller (design objective; Studies H, I).** Study I
supersedes the Study H design below on two points: (1) no blind decay —
lower `m` **only while the slot is contested** (a second arb could also
profit), otherwise hold; blind decay walks `m` into the cost cliff and
loses a whole epoch of rebalancing each cycle; (2) **asymmetric timing** —
staleness checked every ~300 blocks (~1h) and `m` doubled immediately;
lowering stays daily. Staleness = share of *correctable* blocks (cheapest
arb would profit with no charge) left uncorrected — never a fixed price
band. Resulting target: `m` settles between the cheapest and the
second-cheapest arb's cost, where exactly one arb can do the job and
nothing is left to bid for the slot. Original Study H design, kept for
reference:

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
  signal in Study H, Youden J 0.329). Top slots are sold block-wide, so
  the rate is confounded by block busyness: quiet blocks give free top
  slots (no-rent flag rate 0.55 in the lowest base-fee quintile), busy
  ones displace our pool's arb (rent flag rate 0.74 in the highest).
  **`τ` is busyness-normalised:** per epoch, the midpoint of the rent /
  no-rent flag rates expected for that epoch's base-fee mix (base fee is
  on-chain; the rate map is calibrated from history and must be
  refreshed). The flag only sets how fast `m` falls; staleness is the
  safety — under-reporting leaves some rent, over-reporting is caught by
  the ×2 raise within an epoch. Priority fee is readable at execution
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

**Collateral (P§4.5, adopted 2026-10-01).** A trade parks `ℓ·V` of active stake, `ℓ = ρ + k·Δ_block` (`Δ_block` = the pool's cumulative price move so far in the block; `k` per pool). Charges are collected from the trade's parked stake, then the rest of the same account's stake, then a per-pool reserve funded by an explicit protocol take; never from other traders. Study C must report: collection share, reserve draws, stake parked per $ of benign volume, and the discount lost to parking.

**Protocol take (P§4.4, adopted 2026-10-01).** REP is minted slightly below the surplus it claims; the withheld share `τ` pays the reconciling bots and funds the per-pool reserve (safety margin). Required by design: reconciliation has a cost no trader pays directly. Estimate at real window base fees (median 0.134 gwei, ETH ≈ $2,031): one report verification per block with a swap (~300k gas, 595,030 blocks) + one state write per swap (~10k gas, 990,555 swaps) ≈ **$0.13M per window ≈ 2.5% of the ~$5.4M recaptured** — gas-unit budgets are assumptions; Study G measures them. Study C reports `τ` needed for reconciliation and the reserve's balance path.

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
`data/onchain/scored_timing/eth_usdc_005/q_c.parquet`. `paper_literal`
reported beside it as a sensitivity (Study D).

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

Compare `q_LP` from (a) block timestamp, (b) the backward index plane,
(c) kernel average of the price path over the swap's plausible execution
window. The forward virtual-time plane (`t_norm_us`) was measured here,
found to be lookahead (status 9), and removed from the code on 2026-10-02. Measure when swaps were actually
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

## Study I — block-level payout-rule comparison

`pipeline/blocksim.py` (inputs, all from data on disk), `pipeline/study_i.py`,
`results/study_i/metrics.json`. Every block 2026-03..08 in order: arb
phase at `block_ts + L` (optimizing arbs, costs {0.3, 0.6, 1.0, 1.5,
2.5}bp, second-price for the slot), then the block's real non-arb swaps
replayed. Linear depth per day (median $12.3k per bp — this v3 pool is
thin in 2026; three estimators agree). Calibration vs the real pool with
the same markout formula: LP net −$3.15M simulated vs −$2.63M real, arb
flow −$7.39M vs −$6.18M, user flow +$4.24M vs +$3.55M, arb volume
$13.4B vs $14.8B. Scenarios: stable costs, costs ×4 from 2026-06-01.

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

Paper synced with Studies D–I on 2026-10-01; still open: 4 (horizon set), 5 (actor identity in a v4 hook), 6 (bootstrap / launch at `f_max`), 7 (number the §5 cross-references once §5 exists).

1. ~~**Abstract vs P§4.1.**~~ RESOLVED 2026-10-01: abstract now says swaps are priced at execution and reconciled after; extraction beyond the job allowance is recaptured from posted collateral; reputation loss raises future fees.
2. ~~**Concave vs convex.**~~ RESOLVED 2026-10-01: P§2.2/§2.7 now say "concave discount curve"; P§4.3's fee stays "decreasing and convex in r".
3. ~~**`κ`**~~ RESOLVED 2026-10-01: removed; replaced by the job allowance `m` (P§4.3), which the controller discovers and P§4.7 lists as not-a-parameter.
4. **Horizons.** Paper: +12s/+30s. Pipeline also runs +60s. Align.
5. **Actor identity in a v4 hook.** Partly addressed 2026-10-01 (P§4.8): the stake backing a swap is the submitting account's, named in hook data; intermediaries back their routed flow with their own stake. Still to specify: how hook data authenticates the account (signature or allowlist of routers).
6. **Bootstrap.** Partly addressed 2026-10-01 (P§4.8): initial supply sold (proceeds seed the per-pool reserve), priced slightly below the discount it confers; ≈ $16k of active REP per bp of ρ serves all ETH/USDC user flow ($26M/day) near the fee floor; intermediaries (cashiers) as an illustration of how supply reaches users. Still open: how many users stay at `f_max` before supply reaches them (Study C elasticity).
9. ~~**Virtual time plane (P§3.4).**~~ RESOLVED 2026-10-01: P§3.4 rewritten — measured decision latency, single per-block anchor `t* = block_ts + L`, index-based plane kept as a base-layer proposal conditional on time-enforced ordering, with the measured attacks.
10. ~~**Kernel window (P§4.2).**~~ RESOLVED 2026-10-01: P§4.2 now centres a ≈1s window on `t*` and cites ε ≈ 1bp.
11. ~~**Allowance `m` and its controller.**~~ RESOLVED 2026-10-01: P§4.3 "Arbitrage as a paid job" (per-unit path cap + gas allowance, stake-debited, charged per price-correcting swap since 2026-10-01 — see P§4.8) and "The allowance is discovered, not set" (feasible controller); P§4.4 burn at the inverse mint scalar; P§4.5 tranche sizing; P§4.6 what reconciliation computes.
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
3. ✅ Swap preparation (`qlp.py`): user positions and notional at block time. Since 9b the q_LP itself is written by Study E on the canonical timeline; the original trade-price q columns at forward `t_norm` were removed on 2026-10-02.
3b. ✅ Control gate PASS — canonical q (2026-10-02): |q_LP| median 0.93 bps / P95 2.25 bps (original timeline, 2026-09-02: 0.80 / 2.09 bps) on 221,708 control swaps vs 38.4 bps ceiling (3× peg P99 12.8 bps). First-look ETH/USDC (pre-label): size gradient <10k +3.41 bps (16% neg) → >100k −2.40 bps (78% neg); big-swap top-3-position 83.2% neg vs 58.4% mid-block; gross LP-negative markout ≈ $9.9M/6mo.
4. ✅ Labels join — DEVIATION: ZeroMEV API is dead (origin DNS gone, 2026-09-02) and Flashbots Dune mev_summary is stale; replaced with committed price-independent detectors (pipeline/labels.py): router-origin benign list, pool-local sandwich detector, searcher heuristic (first-in-direction + top-3 + non-router + repeat actor). 175,410 toxic / 119,114 benign / 665,000 unlabeled middle. Sandwich attacker labels near-zero (~100 victims/6mo) — same-actor sandwiches effectively extinct on this pool; toxic set is searcher-driven.
5. ✅ Study A (2026-09-02): **AUC(h=0) = 0.867 — gate (>0.75) PASSED.** Size slices: <10k 0.65, 10k–100k 0.91, >100k **0.978** (size is not a label input → clean evidence). Horizon decay 0.87→0.68 (h=0→60s): score at execution-instant truth. CAVEAT: position-sliced AUC is confounded (toxic label conditions on tx_index) — do not cite it as evidence; size slices are the defensible ones. Labels conservative → AUC is a lower-bound estimate. results/study_a/.
6. ✅ Supp-1 (results/supp1/): top-3 raw positions carry ~60% of extraction (83% LP-neg on >100k swaps) but $2.1M (21%) sits at index 10+ — un-raced adverse flow invisible to priority-keyed taxes. Toxic priority-fee spend ≈783 ETH (~$1.9M) vs $9.9M extracted; CAVEAT: builder payments via coinbase-transfer bundles are invisible to maxPriorityFeePerGas, so this understates builder revenue. Position-label confound noted (toxic label conditions on tx_index; use label-free position aggregates only).
7. ✅ Study B — **reframed 2026-09-30 as the perfect-information cash-fee ceiling** (see above; not the P§4 mechanism). results/study_b/, INCREMENTAL accounting — v3 swap deltas already embed the 5bp fee; q_LP is net of it:
   - Baseline as lived: **LP net −$1.93M/6mo** (external validity: matches "major pools net-unprofitable after LVR").
   - Best schedule (α=1.0, cap=100bp, f_benign=5bp): **LP net +$2.14M** (+$4.07M vs baseline), incremental capture 41% of LVR, residual extraction $5.84M (§12.2 reported), benign overcharge 0.05bp (negligible), arb survival 22.8% vs 23.8% baseline (96% of profitable arbs preserved).
   - Cutting f_benign to 1bp always loses money — benign flow is the revenue base; capture fraction ≈40% max matches §12's "tens of percent" expectation.
   - GATE: net-surplus PASS; survival read as relative (22.8/23.8 = most price-correcting arb stays profitable). CAVEAT: static replay, no behavioral response — capture is an upper bound on this schedule.
   - Horizon sweep (2026-09-30, headline schedule held fixed, all 990,555 swaps scored at every h):

     | h | baseline net | headline net | Δ vs baseline | capture | residual | benign overcharge | survival ratio (flat $10 gas†) |
     |---|---|---|---|---|---|---|---|
     | 0s | −$1.93M | +$2.14M | +$4.07M | 41% | $5.84M | 0.05bp | 0.958 |
     | 12s | −$2.96M | +$2.70M | +$5.66M | 48% | $6.20M | 0.17bp | 0.920 |
     | 30s | −$3.04M | +$4.10M | +$7.14M | 53% | $6.36M | 0.40bp | 0.871 |
     | 60s | −$3.20M | +$5.63M | +$8.83M | 57% | $6.55M | 0.77bp | 0.821 |

     Net-surplus gate PASSES at every horizon, and the headline schedule stays best at every h *within the original clip grid (caps ≤ 100bp)*; the 2026-10-01 grid below adds forms that beat it. Surplus GROWS with h rather than decaying. Checked it is not an asymmetric-fee noise tax: benign-labeled capture is ≤$0.06M at every h, and the growth lands on toxic-labeled flow (2.15→5.76M, 53%→65% of capture). Reading: toxic markout keeps deepening for ~60s after execution (informed flow), matching baseline LP loss deepening −1.93→−3.20M. Unlabeled middle carries 34–47% of capture, composition unknown.
     † Flat $10-per-swap gas was the first survival proxy; it overstates real cost ~100× (2026 mainnet base-fee gas per swap: P50 $0.07, P90 $0.38) and was removed from the code on 2026-10-02. Survival is now reported only at real cost (base fee × 250k gas + 1bp hedge) — see the design-objective sweep below and 9b.
     The cost of longer horizons is on the survival side, not surplus (real-cost survival of the objective schedule 0.96 → 0.88 at h60, below). **h0 stays the headline** — smallest claim, fastest settlement, best arb survival. Longer-horizon surplus must not be cited as upside without the survival cost beside it.
   - Gas cost model: base fee × 250k gas per arb, valued at the swap's price. A lower bound on cost — it omits priority fees and coinbase-transfer builder payments, which are the extras being measured, not costs. (A flat $2–$50 sweep was run against it and removed with the flat proxy, 2026-10-02.)
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

     | benchmark (h0) | LP-neg share | gross LVR | baseline net | headline net | Δ vs baseline | capture | survival ratio (flat $10 gas†) | AUC | AUC >100k |
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
     | **centered on +1.5s, w=1s (C input)** | — | — | −$1.58M | +$4.02M | **0.889** | **0.983** |
     | trailing [bt−12s, bt] (pitfall) | 10.8% | $5.59M | **+$5.26M** | +$2.51M | 0.753 | 0.931 |

   - **Forward timeline (all studies so far) is lookahead for mid-block swaps** and scores slightly worse than a single per-block anchor. Anchoring at the decision instant raises AUC 0.852 → 0.889 and deepens baseline LP loss −$0.77M → −$1.58M; the Study B recapture is stable (+$3.88M → +$4.02M).
   - **ε = 1bp.** Per-swap timing noise at the chosen kernel: P50 0.0bp, P90 0.80bp, notional-weighted 0.49bp (>$100k P50 0.15bp). Wider kernels add noise (w=4s: P90 1.67bp).
   - Control pool |q| P95 2.25bp under every reconstruction — peg noise, not timing noise.
   - Position-gaming tests committed (`pipeline/timing_gaming.py`, `position_gaming` in results/study_e): orientation of index time planes, pool-internal clocks and their attacks, and the post-swap-distance metric — source of the figures cited in the design objective.
   - CAVEATS: touch proxy (Study D caveat applies); L measured on gap-closing flow only — mid-block swaps show no pool↔CEX relation, so their decision times are not identified and they share the block anchor by assumption.
9b. ✅ Re-base on one timeline (2026-10-01). `pipeline/canonical.py`: every study now scores with the **canonical q_LP** — arb_exit, 1s window centred on `block_ts + L + h` (L = 1.5s), written by Study E for h ∈ {0, 12, 30, 60}. The original timeline (trade price at forward `t_norm`) was compared once — table below — and removed from the code on 2026-10-02: no study, the scorer or the control gate (which now reads the canonical control-pool q Study E writes) carries it; Study D runs its whole benchmark comparison on the canonical window (its arb_exit row equals Study B's canonical baseline, −$1.58M — checked). **Status entries 5–8 above are on the legacy timeline; cite the canonical numbers below.**

     | metric (h0 unless stated) | legacy (forward, trade price) | **canonical** |
     |---|---|---|
     | Study A AUC | 0.867 | **0.889** |
     | Study A AUC, swaps > $100k / $10–100k / < $10k | 0.978 / 0.909 / 0.648 | **0.983 / 0.931 / 0.662** |
     | Study A AUC h12 / h30 / h60 | 0.798 / 0.732 / 0.683 | 0.799 / 0.732 / 0.683 |
     | Study B baseline LP net / gross LVR | −$1.93M / $9.91M | **−$1.58M / $9.68M** |
     | Study B headline (clip α1 cap100): Δ / capture | +$4.07M / 41% | +$4.02M / 41% |
     | Study B objective (margin m2 cap500): Δ / capture | +$7.25M / 73% | +$7.10M / 73% |
     | builder-bid ceiling today | $8.68M | $8.51M |
     | Supp-1 index-10+ extraction / share | $2.11M / 21.3% | $1.98M / 20.5% |
     | Study D, trade price / mid / arb_exit / literal: baseline LP net | −$1.93 / −1.80 / −0.77 / −2.84M | −$2.66 / −2.62 / **−1.58** / −3.65M |
     | Study D AUC (same order) | 0.867 / 0.860 / 0.852 / 0.861 | 0.900 / 0.895 / **0.889** / 0.895 |

   - Every conclusion holds; the canonical timeline sharpens Study A (no lookahead noise on mid-block swaps) and slightly shrinks measured extraction. Longer horizons are unaffected (timing matters less once h ≫ L).
   - On the canonical window the plain trade price separates toxic from benign slightly better (0.900) than arb_exit (0.889), while arb_exit reports the smallest LP loss — consistent with it being the most tolerant rule. arb_exit stays the scoring rule (P§3.6); trade price is the sensitivity.
   - Study B's tracked schedules are per-swap cash ceilings with the AVERAGE-edge margin form; Study I rejected that form (overshoot) — read B as the ceiling, Study I for the mechanism.
10. ◐ Study C + Supp-2. Bootstrap Mar–May, evaluate Jun–Aug.
   - **C1 collateral ✅ (2026-10-01, `pipeline/study_c_collateral.py`, results/study_c/collateral.json).** The reconciliation charge (extraction beyond the job allowance) is collectable only from stake locked before trading. On the chosen design's simulated trades ($13.4B arb volume, $5.41M charge): the charge is **heavy-tailed** — per trade P50 0.17bp, P99 8.4bp, P99.9 21bp, max 358bp of notional; 27% of all charge comes from trades above 50bp.

     | collateral structure | charge collected | notes |
     |---|---|---|
     | flat per-trade tranche ρ = 20bp / 100bp | 73% / 87% | leaks the tail |
     | per-trade tranche ∝ the trade's own price move | 100% in sim | **rejected**: an identity of the model (sim arbs correct in one trade); splitting a big gap into small trades shrinks the tranche but not the charge |
     | per-trade tranche = gap to the last oracle posted on-chain + buffer, 1-block lag, 3–5bp | 98.4–99.3% | needs a report posted every block (~$0.27M/window at real 2026 base fees, median 0.13 gwei; an earlier $0.7M figure assumed 0.5 gwei); 5-block lag → 75–91% |
     | **standing per-account bond, debited by charges** | **100%** with a ~$1M bond | dominant arb's daily charge: median $13k, P99 $197k, max $809k; splitting-proof; leak bounded by the bond |

   - **Size-based lock schedules are gameable** (author proposal: lock grows exponentially with swap size, tunable). Exponential 2bp·e^(V/$100k), cap 5%: 98.9% collected against honest single-trade arbs, but **51.5% when each correction is split into 10 pieces** (each piece small → tiny lock, while early pieces carry the full edge), and it locks $50k of stake on an ordinary $1M user swap ($194k/day across users). Impact-proportional: 100% → 32.9% under splitting. A flat 20bp lock barely notices splitting (72.7% → 69.3%). Rule: any lock driven by a quantity the trader controls (size, trade count, accounts) is gameable; the charge is driven by the gap, which the market sets. Use the whole-stake burn rule, or tune a lock on the gap to the last posted oracle — never on size.
   - **Block-speed lock** (author proposal: lock rate = 2bp + k × the pool's cumulative price move so far in the block). Fixes same-block splitting: at k = 1 with an account's in-flight locks pooled for burns, a correction split ×10 in one block is 100% collected (67% per piece without pooling). Does NOT fix splitting across blocks — the in-block move resets each block, and the gap comes from the market moving while the pool stands still: 49% pooled at k = 1 (67% at k = 2). How realistic is cross-block splitting? Competition usually forbids it — under the feasible controller a second arb could also profit in 69.5% of arb blocks (stable) / 51.6% (costs ×4) — but on 35 / 61 of 183 days the slot is essentially uncontested (<5%), and there the single profitable arb can spread a correction across blocks without losing the gap. The better the controller squeezes rent from builders, the less competition is left to deter splitting; the whole-stake backstop removes the dependence. Cost: an ordinary $1M user swap locks $8.4k at k = 1 (flat 20bp: $2k).
   - **Adopted (P§4.5, 2026-10-01):** parking rate `ℓ = ρ + k·Δ_block` with `k` a per-pool parameter (≈ 1); charges collected from the trade's parked stake, then the rest of the same account's stake, then a per-pool reserve funded by an explicit protocol take — never from other traders' parked stake. Pooling collateral across traders was considered (amortizes risk, one pool-level computation) and rejected: honest users would pay the extractor's bill (~$1.5M of their parked REP over the window at a flat 20bp lock) while the extractor's own remaining stake stays untouched. The reserve keeps the amortization only for the residual risk after an account is exhausted.
   - **Capital cost is negligible:** even a 100bp tranche locked 7 days adds 0.096bp per $ traded; fed back into Study I as extra arb cost, LP $2.258M → $2.205M and rebalancing unchanged. A 20bp / 1-day stake changes nothing measurable.
   - **Design implication (paper P§4.5).** Withholding and multi-account gaming are already closed by the lock: stake cannot leave before its trades reconcile, unreconciled flights burn in full at the deadline, and every account locks its own REP. The open problem is **sizing**, not gaming: P§4.5 caps a burn at the trade's own in-flight tranche ρ·V, and the charge's tail exceeds any ρ that benign users could afford (73% collected at 20bp, 87% at 100bp, full only near 360bp). **Resolved by the adopted three-layer rule above:** the burn reaches the rest of the account's stake (exit is blocked while flights pend), so collection is complete once the account's stake covers its worst epoch (~$1M for the dominant arb in this data); an account with no stake pays `f_max` at execution.
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
     | **staleness 3-zone + top-slot flag, ×2 up / ×0.8 / 0.95** (flag confounded by block busyness) | **4.58** | **0.37** | 0.32 | **1.8%** | **0.04** | **0.62 → 2.62** | **0.59 → 2.31** |
     | same, busyness-normalised τ | 4.59 | 0.36 | 0.32 | 1.8% | 0.04 | 0.62 → 2.24 | 0.59 → 2.05 |
     | staleness 3-zone only, decay 0.95 | 3.99 | 0.82 | 0.39 | 1.9% | 0.13 | 0.85 → 2.60 | — |
     | staleness 3-zone only, decay 0.90 | 4.30 | 0.54 | — | 4.0% | 0.18 | 0.98 → 2.05 | — |
     | staleness 3-zone only, decay 0.85 | 4.17 | 0.42 | — | 6.7% | 0.49 | 0.70 → 1.88 | — |

     ×2 scenario: proposed 4.85 / 0.36 / 1.0% uncorrected vs today 0 / 5.11; static 1bp is best in hindsight (4.94 / 0.23 / 0.9%) only because the cheapest arb's cost stayed below 1bp.
   - **Market-driven payouts.** The controller never sees arb costs, yet `m` settles just above the cheapest arb's cost (0.3 → 0.62bp; 1.2 → 2.2–2.6bp after ×4) and what arbs keep tracks it (0.59 → 2.05–2.31bp). Builder payments fall from $4.81M to $0.36–0.37M (−92%); LP recapture $4.58–4.59M.
   - **Block-busyness confound on the top-slot flag** (2026-10-01): real at the block level — no-rent flag rate 0.55 → 0.34 and rent flag rate 0.87 → 0.74 from quietest to busiest base-fee quintile — but it largely averages out over a daily epoch (~800 opportunities across blocks of every busyness): confounded vs unconfounded 4.58 vs 4.59 LP, 0.37 vs 0.36 builder; settled `m` after the shift 2.62 vs 2.24bp. Busyness-normalised τ restores the unconfounded result exactly. **The flag earns its place:** staleness-only controllers trade builder rent against staleness at every decay speed (table), while the flag lowers `m` fast only when rent is visible. The arb payout is set by competition among arbs, not by a hardcoded parameter.
   - **No fixed `m` survives a regime change:** 1bp kills rebalancing after the shift (100% uncorrected, $1.78M of gaps); 2bp survives but leaves builders 2× the controller's payments; 5bp leaves 5.5×.
   - **The thirds rule collapses:** almost every epoch reads "first third", `m` halves to the floor within days, rebalancing stops, and the first swap in each block becomes user flow that also sits high — so no raise signal ever fires.
   - **Why asymmetric + hold band:** symmetric ×2 / ÷2 oscillates across the cost cliff (7.6% uncorrected); slow symmetric steps recover slowly after a shock ($0.39M gaps); the 0.5–2% hold band stops decay before the cliff and ×2 up recovers in ~2 epochs ($0.04M).
   - CAVEATS: assumed arb cost population and second-price auction; static opportunity set (no behavioural response); signal rates from today's cross-section; builder payments are model output (11b measures reality). Residual hunting remains — single 100% days when decay crosses the cliff (visible in the figure).
11d. ✅ Study I (2026-10-01, `make study-i`). Block-level payout-rule comparison; goal: best LP outcome while keeping the pool rebalanced every block.

     | rule / m (stable costs) | LP net | vs today | builder | correctable blocks uncorrected | blocks within fee+1bp | overshoot blocks | arb volume | user-side staleness |
     |---|---|---|---|---|---|---|---|---|
     | today, no reconciliation | −$3.15M | — | $6.57M | 0.00% | 99.54% | 0 | $13.4B | 12.75bp |
     | avg-edge margin, m = 1bp | +$2.40M | +$5.55M | $0.93M | 0.22% | 98.87% | **24,092** | **$24.5B** | **17.73bp** |
     | marginal cap, m = 1bp (no gas) | +$3.00M | +$6.15M | $0.42M | **1.42%** | 99.26% | 0 | $13.4B | 12.78bp |
     | **marginal cap + gas, controller (hourly raise)** | **+$3.15M** | **+$6.30M** | **$0.33M** | **0.00%** | **99.54%** | 0 | $13.4B | **12.75bp** |
     | same + 0.5bp position premium | +$2.48M | +$5.63M | $1.00M | 0.00% | 99.54% | 0 | $13.4B | 12.75bp |

     Costs ×4 shock: winner +$2.52M (+$5.94M vs today), builder $0.33M vs $6.16M, uncorrected 0.15%, within-band 88.07% vs today 88.09%. Robust ranking (rebalanced in every scenario, worst-case LP gain): **marginal cap + gas, controller +$5.94M** > same + 0.1bp premium +$5.81M > marginal cap (no gas), controller +$5.44M > static m = 2bp +$5.22–5.25M > avg-edge margin, controller +$4.98M.
   - **Rebalancing test revised (2026-10-02).** The constraint was "uncorrected share of correctable blocks ≤ today + 0.5pp". It counts a standing gap once per block — one stalled hour weighs 300 blocks on mainnet and 14,400 on Arbitrum — so the same controller passed on mainnet and failed on Arbitrum, and it missed price quality entirely. It is now judged on quantities with the same meaning at any block time: share of blocks within fee + 1bp after the arb phase ≥ today − 0.5pp, and the volume-weighted gap users trade against ≤ today + 0.1bp. Uncorrected hours and the old share are still reported. Mainnet verdicts that flip, all for visible reasons: **avg-edge margin now fails** (pays arbs to overshoot — 16–23k overshoot blocks, users trade 4.7–5.0bp further from the oracle; the old test could not see overshoot); **closing-phase correction now fails** (users trade before the arb, 14.78 vs 12.75bp); job-cap and plain marginal-cap controllers now pass (their leftover gaps are sub-bp: within-band −0.02…−0.2pp, users +0.04…+0.095bp). New mainnet robust ranking (worst-case LP gain vs today): marginal cap + gas, `ctl_fast` +$5.62M > same, open+close +$5.61M > same + 0.1bp premium +$5.50M > marginal cap, `ctl_fast` +$5.11M > **marginal cap + gas, `ctl_feasible` +$5.07M** > … > static m = 5bp +$3.67M. The top is unchanged.
   - **The winner keeps the pool exactly as rebalanced as today** (same within-band share, same user-side staleness) and moves ~$6M from builders to LPs.
   - **Gas reimbursement is what keeps every block rebalanced:** without it, per-unit rent capped at `m` cannot cover gas on small corrections (1.4% of correctable blocks lost at m = 1bp).
   - **Controller evolution:** blind decay walks into the cost cliff (26% uncorrected — a full lost day every ~2 weeks); competition-targeting settles at m ≈ 0.54bp between the cheapest (0.3) and second-cheapest (0.6) arb cost; daily raises need two lost days after a ×4 shock (5.5% uncorrected), hourly raises fix it (0.15%).
   - **Hindsight static m is not a design:** m = 0.5bp is best in stable costs (+$6.69M) but loses 84% of rebalancing after the ×4 shock.
   - **Runs that stop rebalancing show absurd LP "gains" (+$193M)**: the pool freezes and replayed user flow trades against a price thousands of bp wrong, which no router would route. They are failures; the constraint filters them.
   - **Feasibility pass (2026-10-01).** Every component audited against "implementable as a v4 hook + L1 reconciliation" (table in the Study C design). Two signals of `ctl_fast` are not observable on-chain (arb costs; whether a second arb could profit). Replaced by a self-referential staleness signal (resting gap beyond f + m + 0.5bp not corrected by the block's first swap). First attempt (post-first-swap gap) ran away to m ≈ 47bp — large user first swaps are noise; hourly raises on tiny samples also ratcheted m up until a ≥ 5-stale-block minimum was added. Scenario ×8 (cheapest arb 2.4bp) added. Robust ranking over stable / ×4 / ×8: `ctl_fast` +$5.62M (upper bound) > **`ctl_feasible` +$5.07M** > static 5bp +$3.68M; static 0.5 / 1 / 2bp all break in at least one scenario. Closing pass fired in 14,532 blocks (1.1%, $0.70B) — only when user flow pushed the pool beyond what an arb can profitably correct; real share lower (needs the user swap to be visible for a same-block backrun).
   - **Opening vs closing correction** (stable, winner rule): open +$3.15M / users see 12.75bp staleness / 98.69% of blocks END within fee+1bp; close-only +$2.99M / 14.78bp (+16% staler — users trade against a price 12s out of date) / 99.53%; both +$3.14M / 12.73bp / 99.55%. No time passes inside a block, so a closing trade only undoes users' own in-block impact; it matters for the pool's RESTING price between blocks (TWAP-style readers, lending protocols, next-block routers). Do not REQUIRE a closing trade (a position requirement, and "pool-last" is unknowable at execution); the winner rule already pays any correcting trade, so a restoring backrun earns the same job reward and the pool gets both.
   - `job_cap` (allowance only for trading exactly to a 5.5bp band) has a structural uncorrected floor (~5.7%): gaps between the arb's natural stop and the band are "correctable" but not a job under the rule. Not pursued.
   - CAVEATS: linear depth; replayed user flow does not respond to pool quality; one arb action per block; assumed cost population; the controller's "contested" signal is observed ideally here — in practice it is the top-slot proxy (Study H, J 0.33, busyness-normalised); Study C must re-test with the proxy and with behavioural response.
11h. ✅ Study J — oracle-error stress (2026-10-02, `pipeline/study_j.py`, results/study_j and results/arbitrum/study_j). The mechanism charges against an oracle report; the study scores the Study B objective schedule (margin m = 2bp, cap 500bp) with a protocol oracle that is delayed (0.5–5s), noisy (one lognormal error per block, 1–5bp) or biased (±1–3bp), against the canonical q as truth, and sweeps the tolerance ε (charge only beyond m + ε).

     | protocol oracle (ε = 0) | mainnet: overcharge share / benign bp / capture | Arbitrum: overcharge share / benign bp / capture |
     |---|---|---|
     | truth | 0 / 0 / 73.4% | 0 / 0 / 69.9% |
     | delay 1s | 5.2% / 0.004 / 70.1% | 1.4% / 0.003 / **37.3%** |
     | noise 2bp per block | 11.4% / 0.027 / 77.6% | 19.3% / 0.028 / 80.4% |
     | bias +1bp | 6.4% / 0.005 / 74.9% | 8.0% / 0.008 / 72.1% |
     | bias −3bp | 20.7% / 0.060 / 81.3% | 34.6% / 0.059 / 92.8% |

   - **Benign flow is safe under every error tested** (≤ 0.26bp overcharge even at 5bp noise). Oracle error lands on arb-sized flow: charges the true price does not justify, growing fast past 1bp.
   - **ε is the protocol's lever, and it has a price.** ε = |bias| removes bias overcharge exactly (bias +1bp, ε = 1bp → $0); noise needs ε ≈ 2σ (2bp noise: ε = 2bp → 2.7% mainnet / 4.3% Arbitrum, ε = 4bp → 0.3%). Each bp of ε gives up ~$0.5–0.7M of mainnet recapture (~8% of what the mechanism recaptures). Design rule for P§4.2/§4.7: **set ε ≈ max(|feed bias|, 2·σ_feed)**; ε = 1bp presumes a feed within ~1bp of the market.
   - **On a fast chain delay is the binding error:** a 1s-stale feed halves Arbitrum capture (70% → 37%) because Arbitrum's decision latency is 0.75s — a heartbeat-style feed cannot work there; a sub-second pull oracle (Data Streams class) is a requirement, not an option. On mainnet a 1s delay costs 3 points of capture.
   - CAVEAT: Binance bid/ask stands in for both truth and feed; a real feed's error against the market is modelled only as bias/noise. Measuring Data Streams vs Binance directly needs Data Streams reports (Layer-1 data, pending).
11i. ✅ Out-of-sample check (2026-10-02, Study B `out_of_sample_h0`). Fit on 2026-03..05, test on 2026-06..08; selection = max net LP among schedules keeping real-cost arb survival ≥ 0.95× baseline (unconstrained, the pick is the additive max-capture schedule that kills every arb — survival 0 — which is not the design). **The a-priori objective schedule (margin m = 2bp, cap 500bp — set by reasoning: m = hedge cost + 1bp, cap = f_max) is the hindsight-best schedule on the test half on both chains:** mainnet +$2.47M vs test baseline −$0.28M, capture 76%, benign 0.05bp, survival 0.97 (the fitted pick IS the objective schedule); Arbitrum +$0.63M, capture 80%, benign 0.10bp, survival 0.98 (the fitted pick, margin cap 100bp, undershoots at +$0.40M). The old clip headline: +$1.56M / +$0.31M. Study I's controller constants were set on mainnet and applied to Arbitrum unchanged — Arbitrum is itself an out-of-sample test of them.
11e. ✅ v3 vs v4 venue probe (2026-10-01, `pipeline/v4_probe.py`, RPC only). Mar–Aug 2026 Uniswap ETH/USDC volume: **v3 0.05% (study pool) $19.6B**, v3 0.30% $0.67B, v4 hook-less 0.30% $0.66B, 0.01% $0.63B, 0.05% $0.41B, 1.00% ~$0 — the study pool carries 89% of $22.0B. Depth from each pool's own swap-event liquidity: study pool **$12.1k/bp** (matches Study I's swap-based estimate, $12.3k/bp — estimator validated), next deepest $2.9k/bp. Busiest v4 pool ids in a 300-block sample identified from swap receipts: ETH/USDT (hooked), a long-tail token, stable/stable pairs, multi-hop routes — **no large hooked ETH/USDC pool**. Study I's calibration is representative: Uniswap ETH/USDC is thin in 2026 as a venue, not just this pool. The RPC caps eth_getLogs below 50k blocks even when topic-filtered.
11f. ✅ L2 gas-constraint probe (2026-10-01, `pipeline/l2_probe.py`; latest hour per chain; Base via public RPC, Arbitrum and HyperEVM via Chainstack URLs in `.env`).

     | pool | block time | swaps/hour | blocks with a swap | swaps per active block p99 / max | volume/hour | depth/bp | gas per swap tx p50 | cost per swap tx |
     |---|---|---|---|---|---|---|---|---|
     | mainnet v3 WETH/USDC 0.05% (window) | 12s | 194 (median hour) | 45% | 7 / 214 | — | $12.1k | — | — |
     | Base v3 0.01% | 2s | 1,863 | 46% | 12 / 37 | $0.22M | $191 | 250k | $0.007 |
     | Base v3 0.05% | 2s | 581 | 22% | 4 / 7 | $0.68M | $3.7k | 182k | $0.010 |
     | Base v3 0.30% | 2s | 236 | 6% | 10 / 11 | $6.53M | $116k | 132k | $0.068 |
     | Arbitrum v3 0.05% | 0.285s | 527 | 2% | 15 / 17 | $1.66M | $9.7k | 133k | $0.008 |
     | HyperEVM v3 WHYPE/USDC (busiest) | 0.98s | 676 | 16% | 3 / 5 | $1.91M | $4.6k | 134k | $0.033 |

   - Even the busiest L2 pools see ~1 swap per active block; per-block reconciliation amortizes nothing anywhere — epoch-batched proofs are the right architecture on every chain.
   - Gas cost per swap is cents; L1 data fees ~0 (blobs). Block space binds nowhere for one pool: Base fills ~10% of a 400M-gas block; Arbitrum's chain is near its ~7M gas/s target but the pool is ~0.3% of it.
   - **HyperEVM is the tight case:** ~1s small blocks capped at 3M gas (590/600 blocks; fill p50 9%, p99 83%) plus ~1/min big blocks at 30M. One v3 swap ≈ 134k gas → ~20 swaps per small block chain-wide; a hook's per-swap overhead and an epoch proof (~300–400k gas ≈ 10–13% of a small block, or post it in a big block) must be budgeted against that cap.
11g. ◐ Horizontal scaling to Arbitrum and HyperEVM (2026-10-01).
   - **Refactor ✅** (`pipeline/chains.py`, commit 9e9e41d): one registry per chain (RPC env var, study/control pools, benchmark, log chunk, header strategy, layout `data/onchain/<chain>`, `results/<chain>`), selected by `AMMBRO_CHAIN`. L2 pools are risky-first on-chain and stored in canonical (stable, risky) order (amounts swapped, tick negated; unit-tested against on-chain price). HYPE benchmark = Binance USD-M **perp** HYPEUSDT (no spot archive; a few bp basis/funding noise — state wherever HyperEVM results are cited). Mainnet results reproduce byte-identically after the refactor.
   - Pools: Arbitrum v3 WETH/USDC 0.05% `0xC696…E8D0` (control: v3 USDC/USDT0 0.01% `0xbE3a…eef6`); HyperEVM v3 WHYPE/USDC `0x6c9a…9285` (control: USDC/USDT0 `0x46ab…e63e`). Window blocks: Arbitrum 437,025,052 → 500,455,224; HyperEVM 28,536,726 → 44,697,309. Chainstack caps eth_getLogs at 10k blocks on both.
   - **Sub-second block times.** Neither chain has sub-second timestamps in headers (verified): Arbitrum stamps ~3–4 blocks per second (sample: 67% of seconds hold 4 blocks, 32% hold 3), HyperEVM one small block per second plus ~1/min big blocks (sample: 97% of seconds hold 1 block, 3% hold 2). Extraction resolves each swap block's second by fetching neighbouring headers in batched rounds and stores `block_ts_us = S + (k + ½)/N` (author's proposal: apply the normalisation to the N same-timestamp blocks); every timing study reads it via `normalization.block_time_us`, falling back to the slot timestamp on mainnet. Framed in paper P§3.4 (blocks, not transactions; sequencer arrival order; measurement only; error ≤ ±1/(2N) s). Decision latency L and the scoring window must be re-measured per chain (Study E) — mainnet's +1.5s comes from PBS and does not transfer.
   - **Arbitrum March 2026 extracted ✅:** 1,038,436 swaps in 422,730 blocks; WETH $1,909–2,385; 98.7% of swap blocks sit in 4-block seconds (the 250 ms cadence), 0.2% in sequencer bursts of 5–19 blocks sharing one timestamp. 145 blocks (0.03%) exceeded the then 12-round limit and fell back to mid-second (≤ 0.5 s off; the only cause of 17 out-of-order block times — header timestamps are monotonic). Limit raised to 30 and `extract_swaps.repair_unresolved()` re-resolves fallback blocks in written months after the run.
   - **Arbitrum extraction complete ✅ (2026-10-02).** Study pool 5,237,793 swaps (Mar 1,038,436 · Apr 669,202 · May 575,631 · Jun 1,405,733 · Jul 783,198 · Aug 765,593 — 5.3× mainnet); control pool 188,668. `repair_unresolved` re-placed 893 of 908 fallback blocks; 15 swaps in bursts beyond 30 rounds stay at mid-second; block times strictly increasing in all 12 files. RPC throughput ~333 calls/s, ~2.2 h per month; pauses for the author's calls via SIGSTOP/SIGCONT.
   - **Arbitrum q_LP scored; control gate PASS:** USDC/USDT0 |q_LP| median 0.85 bp / P95 2.08 bp vs 38.4 bp ceiling (mainnet 0.80 / 2.09) — benchmark and canonical orientation behave. (Original timeline; superseded by the canonical gate re-run.)
   - **Labels on L2 (decided 2026-10-02).** Router list = curated mainnet routers that also exist on Arbitrum at the same address (11 of 14; 9 with identical bytecode length — hashes differ because routers embed chain-specific WETH/factory immutables — plus 0x and ParaSwap v5 in different builds; MetaMask router and UniswapX reactors absent) ∪ contracts detected from Arbitrum's own swaps (≥ 300 distinct senders and ≤ 20 swaps per sender), persisted to `results/arbitrum/routers_*.json`. The detection rule was validated on mainnet first: it recovers 6/11 curated routers and covers 32% of swaps (curated: 12%); it misses solver-settled intents and bot-heavy routers, and a looser rule admits multi-wallet searchers — hence the union. Report a curated-only sensitivity beside Arbitrum Study A. Mainnet labels unchanged. "Top of block" (tx_index ≤ 3) is kept: Arbitrum swap blocks hold a median 14 txs (mainnet 272) and 19.6% of swaps sit at index ≤ 3 (mainnet 24.7%), but on Arbitrum position means sequencer arrival order plus Timeboost, not a builder auction — state it.
   - Next: tx metadata (~5M txs at ~333/s ≈ 4 h, running detached), labels, then Studies E (re-measure L), A, B, D, Supp-1, C1, I.
   - **Arbitrum labels complete ✅ (2026-10-02).** 19 routers detected (incl. Uniswap's Arbitrum Universal Router `0xa51afafe…`) ∪ 11 cross-chain curated. Study pool Mar–Aug (user positions, see next item): toxic 840,519 (16.0%; 676,026 before the index re-base), benign 277,812 (5.3%), unlabeled 78.6%; sandwich victims 4 in six months (FCFS sequencer — no builder to sell ordering). Benign share is low because three bot contracts send ~83% of March swaps (`0x2792…1a70` 504k, `0x96da…ab73` 254k, `0xee2e…c7ba` 104k): Arbitrum flow is bot-dominated, not router-dominated — state it beside Study A, and give the curated-only sensitivity.
   - **Positions and sizes re-based per chain (2026-10-02, found by Study E's first Arbitrum run).** (1) Every Arbitrum block opens with an ArbOS internal tx (type 0x6a, from `0x…A4B05`) at index 0, so no swap ever sits at raw index 0; `Chain.system_txs = 1` and `normalization.to_user_positions` re-base `tx_index`/`tx_count` onto user txs in the scorer and the labeller (raw kept as `tx_index_raw`). Every position rule — top of block (≤ 3), index buckets, intra-block fraction — now means user position on every chain. Arbitrum scores and labels were rebuilt; the pre-fix set is archived under `data/onchain/arbitrum/pre_offset/`. (2) Arbitrum flow is chopped into small fills: median $1.3k (mainnet $1.5k) but only 629 swaps (0.01%) exceed $100k versus 4.55% on mainnet, where they carry 49% of notional. The "large swap" cut is per pool (`Pool.big_usd`), set to the notional of each chain's top 4.55% of swaps: mainnet $100k (unchanged), Arbitrum $7k (26% of notional); size buckets scale with it (lt0.7k / 0.7k_7k / gt7k). (3) Supp-1's in-block fraction uses `tx_index / tx_count` on L2 (on mainnet it is the same quantity via `t_norm`). Mainnet A, D, Supp-1 outputs byte-identical after the change.
   - **Arbitrum Study E ✅ (2026-10-02, results/arbitrum/study_e).** Decision latency **L = 0.75s**, bracket [+0.0s next print, +1.5s last print] on 676,022 toxic top-of-block swaps — wider than mainnet's [1.25, 1.75] because the proxy's staleness dominates at sub-second block times; the next-print estimator puts the pool↔CEX match at block time itself, consistent with FCFS sequencing (no slot to wait through). Results flat inside the bracket: AUC 0.812 at L = 1.0–1.75s (0.783 at L = 0), AUC for swaps > $7k 0.893. Canonical input (1s window centred on block_ts + 0.75s): AUC 0.815 / > $7k 0.897; LP-negative share 24%; **LP net positive +$0.86M** over six months (mainnet −$1.58M) — on Arbitrum fees outrun extraction at h0 on this pool; gross LVR $1.6M vs mainnet $9.7M on 5.3× the swaps, because fills are small (median $1.3k). Timing noise P90 1.72bp at the 1s kernel (mainnet 0.80bp). **Control gate PASS on canonical q:** |q_LP| median 1.06 bp / P95 2.31 bp (mainnet 0.93 / 2.25).
   - **Arbitrum A, B, Supp-1, D ✅ (2026-10-02, canonical h0, results/arbitrum/).** Headline numbers are q_LP-only (labels serve the AUC check alone).

     | h0 | Arbitrum | mainnet |
     |---|---|---|
     | gross LVR / baseline LP net | $1.34M / **+$0.86M** | $9.68M / −$1.58M |
     | headline (clip α1 cap100): Δ / capture / LP net | +$0.48M / 35% / +$1.34M | +$4.02M / 41% / +$2.44M |
     | objective (margin m2 cap500): Δ / capture / LP net | +$0.94M / 70% / +$1.80M | +$7.10M / 73% / +$5.52M |
     | ordering-rent ceiling today → objective | $1.09M → $0.15M | $8.51M → $1.41M |
     | arb survival at real cost (objective / baseline) | 0.989 | 0.971 |
     | benign overcharge (objective) | 0.07bp | 0.06bp |
     | Study A AUC h0 / large swaps / h60 | 0.814 / 0.897 (> $7k) / 0.622 | 0.889 / 0.983 (> $100k) / 0.683 |
     | Supp-1: extraction share top-3 / index 10+ | **6% / 69%** | 61% / 21% |
     | Study D baseline LP net: trade / mid / arb_exit / literal | −$0.04 / +0.16 / **+0.86** / −0.54M | −$2.66 / −2.62 / −1.58 / −3.65M |

     - The mechanism recaptures the same *share* of extraction on Arbitrum as on mainnet (objective 70% vs 73%) at the same benign overcharge (≤ 0.07bp) and arb survival; the dollar base is 7× smaller.
     - **Position inverts under FCFS.** Mainnet extraction is top-of-block (61% in the first three user slots — bought position); on Arbitrum it sits deep in the block (69% at index 10+; LP-negative share rises with index, 14% at index 0 → 29% at 10+). There is no position auction, so the arb arrives when the CEX moves, wherever the block happens to be. The position-invariant per-block anchor is what makes the score indifferent to this.
     - "Ordering-rent ceiling" on Arbitrum is what Timeboost express-lane bids and priority fees could at most capture — the analogue of mainnet's builder bids.
     - Bid/ask matters more relative to Arbitrum's small edges: the sign of LP net flips between trade price (−$0.04M) and arb_exit (+$0.86M).
     - Arb survival is at real cost on both chains (base fee × 250k gas + 1bp hedge; Arbitrum gas P50 $0.01/swap). The flat $10 proxy, which reported 0.4% survival on Arbitrum, was removed 2026-10-02.
   - **Arbitrum H, I, C1 (2026-10-02, results/arbitrum/).** Study I runs on every one of Arbitrum's 63.4M blocks: the 1.87M with a pool swap at their sub-second reconstruction (P§3.4), the rest interpolated linearly in block number between them (~34 blocks apart, steady 0.2506s cadence); oracle read at each block's own time + L. The fast controllers' hourly check counts blocks from the measured interval (~14.4k on Arbitrum, 300 on mainnet). Mainnet Study I byte-identical after the change.
     - Calibration: simulated "today" LP net +$1.38M (real, mid-at-L: +$0.11M; canonical bid/ask +$0.86M).
     - Study H (signals + controller agent model) runs unchanged; its base-fee quintiles fall back to rank-based splits because Arbitrum's base fee sits at its floor in most blocks.
     - **Controller on 250ms blocks (investigated 2026-10-02).** Under the original block-count test `ctl_feasible` failed every Arbitrum scenario (9.8–18% of correctable blocks uncorrected). Diagnosis: the failures are a sawtooth, not a spread — daily ×0.95 decay walks m below the cheapest arb's cost (0.3bp) about every two weeks; under marginal caps an arb then keeps at most m < its cost per unit, so **arbitrage stops at every gap size** (a supply cliff) until the hourly raise catches it; stalls lasted ~1.4–2.8h, in calm markets with small gaps, and each 250ms block of a stall was counted as a separate failure. Economic cost is small: users trade +0.009bp (stable) to +0.058bp (×8) staler than today (≈ $7–46k on $7.9B of user volume) against +$0.71–0.86M LP gain; uncorrected time 4.7–7.1h in six months (0.1–0.16%). Two fixes were tested and rejected: (1) staleness as the share of time the resting gap exceeds f + m + ε over every block — worse on Arbitrum (5.8–15.6%) and on mainnet the 12s of fresh drift at each block start reads as staleness, so m runs away to 21–31bp and LP gain falls to +$1.5–1.9M; (2) an allowance growing with the standing gap, m_eff = m + κ·max(gap − f − m − 1bp, 0) (κ = 0.1–0.5) — paying for large gaps silences the very signal that raises m, so m stays below cost longer (uncorrected 20–61h on Arbitrum, 5.5–16h on mainnet) and LP gain drops (Arbitrum −$0.14…−0.57M, mainnet −$0.9…−3.8M vs plain). **Resolution:** keep `ctl_feasible`; judge rebalancing by the block-time-neutral test (Study I). Under it `ctl_feasible` passes every scenario on both chains: Arbitrum +$0.86 / +$0.77 / +$0.71M (stable / ×4 / ×8), within-band 99.90 / 97.51 / 93.80% vs today 100.0 / 97.65 / 93.94%. Arbitrum robust ranking: marginal cap `ctl_fast` +$0.75M ≈ marginal cap + gas `ctl_fast` +$0.75M > **marginal cap + gas `ctl_feasible` +$0.71M** > static m = 5bp +$0.42M. Open item: the controller still finds the cost cliff by crossing it; a cliff-memory variant (hold m ≥ ~1.2× the last stalled m for a period) would cut the number of probes — untested.
   - Data caveats found while testing: Arbitrum's endpoint returns `blockTimestamp` in logs on only ~80% of logs (0x0 otherwise) — headers are always used, non-zero log values are cross-checked (all matched); HyperEVM fills it consistently.
   - **RPC budget:** the Chainstack plan allows 400 requests/s in total, shared by every chain's endpoint and every concurrent job; `rpc.py` now starts at 300 and is capped at 380 (parallel jobs must split it). Arbitrum is far busier than the one-hour probe suggested — March alone has 1,038,436 swaps (≈6× mainnet's monthly count) — so its header + sub-second resolution (~6 header calls per swap block) is the dominant cost, on the order of a day at 380 rps. HyperEVM skips sub-second resolution (`resolve_subsecond=False`): 97% of its seconds hold one block, so the split would place almost every block at mid-second anyway; skipping it saves ~2/3 of its header calls and moves ~3% of block times by up to 0.5 s. Arbitrum keeps the split.
11b. ☐ Measure today's actual builder payments by gap-takers: priority fee × gasUsed (receipts) + coinbase transfers (traces or fee-recipient balance deltas). The "before" number the design objective drives toward 0; Supp-1 sees only the priority part (~$1.9M, estimated).
12. ☐ Study G — L1 gas viability (receipts).
13. ☐ Layer-1 signed-feed ingestion + §17.5 equivalence test (when dump arrives; do not block). Replaces D's proxy with real LWBA.
14. ☐ Replication pair Study A (BTC/USDC or WBTC/ETH), after gates clear.
