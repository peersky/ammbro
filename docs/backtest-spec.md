# Backtest spec — implementation-binding extract

Binds the pipeline to two sources:

- **`§`** = REP-AMM master doc v0.2 (lives with the research author).
- **`P§`** = `paper.md` at repo root (abstract, §1–§4). Where the two
  disagree on the *mechanism*, the paper wins — it is what the results
  will be written up against. Revised 2026-09-30 after an alignment
  review against paper §1–§4.

This file tracks what the code must satisfy.

## Studies and gates (§17.1, §17.8, P§4)

| Study | Computation | Primary output | Gate |
|---|---|---|---|
| A | ROC of `q_LP` (sign+magnitude) vs. independent labels | AUC + overlaid q_LP histograms per class, sliced by trade size & block position | AUC > 0.75 on high-confidence labels |
| B | **Ceiling:** perfect-information per-swap *cash* fee `F(q_LP, cap)` sweep incl. fixed-fee baseline | Net LP surplus, gross LVR captured, residual extraction (§12.2), benign overcharge (bps), arb survival | Ceiling, not a mechanism result — see below |
| C | The P§4 mechanism under 4 conditions: (1) fixed 5bp / (2) P§4 curve + **cash bond** / (3) P§4 + **soulbound** REP / (4) P§4 + **transferable** REP | Per-condition net LP, captured, residual, **share of B ceiling**, benign effective fee, arb survival, REP concentration, unstaked-volume share | Keep REP only if (4) beats (2); keep transferability only if (4) ≥ (3) |
| D | Directional benchmark: bid/ask proxy vs trade-price vs mid (P§3.6) | `q_LP` under each benchmark; A and B(h0) re-run under directional | informational — quantifies leniency of P§3.6 rule |
| E | Timestamp sensitivity: point read vs kernel average over the virtual-time window (P§3.4, P§4.2) | `q_LP` spread per reconstruction; noise floor on the control pool | Sets `ε` for C |
| F | Competitor baselines (abstract: "existing solution incompleteness") | Capture / net LP for MEV tax, volatility-scaled fee, 0.05% vs 0.30% fee tier | informational — must be reported beside C |
| G | L1 viability (title, P§4.6) | Per-swap execution `gasUsed` vs estimated reconciliation gas | Reconciliation ≤ execution per swap |
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

So Study B's +$4.07M (h0) is the most **any** per-swap, `q_LP`-keyed
cash fee could recapture with perfect information. It stays in the
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
f(r))·V`.

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

**q_LP input.** Directional benchmark (Study D) is primary per P§4.2,
`arb_exit` convention (the paper's stated intent) until open item 8 is
resolved; `paper_literal` and trade-price reported beside it. Columns in
`data/onchain/scored_directional/`.

## Study D — directional benchmark proxy (P§3.6)

The paper scores against Chainlink Data Streams LWBA: ask when the pool
sells the asset, bid when it buys. Until Layer-1 LWBA arrives, build a
bid/ask proxy from Binance `aggTrades` using the `isBuyerMaker` flag
(last buyer-initiated trade ≈ ask, last seller-initiated ≈ bid), with
the numeraire correction applied to each side. Report trade-price,
proxy-mid and directional `q_LP` side by side.

Two conventions, because the paper's text and its stated intent
disagree (open item 8):
- **`arb_exit`** — pool sends ETH → bid, pool receives ETH → ask. The
  price an arb can exit at; a no-flag band `[bid, ask]` that widens with
  the spread. Matches the intent in P§3.6 ("not penalized during
  volatile periods", "permissive").
- **`paper_literal`** — pool sends ETH → ask, receives → bid, as the
  sentences in P§3.6/P§4.2 read. Flags MORE flow as the spread widens.

## Study E — timestamp sensitivity (P§3.4, P§4.2)

Compare `q_LP` from (a) block timestamp, (b) virtual-time point read
(`t_norm_us`, current), (c) kernel average of the price path over the
swap's plausible execution window. On the USDC/USDT control pool the
spread between reconstructions is the noise floor; `ε` is set from it.

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

## Scoring metric (§17.2, P§4.2 — q_LP, NOT the §5 price ratio)

```
LP_markout_i(h) = oracle_value(Δin_received) − oracle_value(Δout_sent)   # at benchmark price t_i + h
q_LP_i(h)       = LP_markout_i(h) / notional_i
```

Direction-free: overpayment in EITHER direction must come out LP-positive
without per-side negation (unit-tested). Pool-perspective raw deltas.
Under the directional benchmark `oracle_value` follows the `arb_exit`
convention by default (Study D; open item 8).

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
8. **Bid/ask assignment is reversed relative to its stated purpose.**
   P§3.6/P§4.2 value the pool's asset leg at the ask when the pool sells
   and the bid when it buys. Under that rule a wider spread makes LP
   markout more negative, so MORE flow is flagged in volatile markets —
   the opposite of P§3.6's stated aim ("legitimate trading flow is not
   penalized during volatile periods") and of P§3.6's own description of
   the rule as "permissive". The intent needs bid-when-pool-sells /
   ask-when-pool-buys (`arb_exit`). Study D measures both.
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

     Net-surplus gate PASSES at every horizon, and the headline schedule stays best at every h. Surplus GROWS with h rather than decaying. Checked it is not an asymmetric-fee noise tax: benign-labeled capture is ≤$0.06M at every h, and the growth lands on toxic-labeled flow (2.15→5.76M, 53%→65% of capture). Reading: toxic markout keeps deepening for ~60s after execution (informed flow), matching baseline LP loss deepening −1.93→−3.20M. Unlabeled middle carries 34–47% of capture, composition unknown.
     The cost of longer horizons is on the survival side, not surplus: survival ratio falls 0.958→0.821 at $10 gas. **h0 stays the headline** — smallest claim, fastest settlement, best arb survival. Longer-horizon surplus must not be cited as upside without the survival cost beside it.
   - Gas sensitivity (survival ratio headline/baseline): h0 holds ≥0.85 across flat $2–$50 and the base-fee model (0.996). Fragile corner is long horizon × high gas: h60 at $50 → 0.509, h30 at $50 → 0.588 — roughly half of profitable arbs killed. Base-fee model (base fee × 250k gas) is a LOWER bound on cost: omits priority fees and coinbase-transfer builder payments; true cost sits between it and the flat sweep.
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
9. ☐ Study E — timestamp sensitivity → `ε`. Before C: C's burn tolerance depends on it.
10. ☐ Study C + Supp-2 (depends on 8, 9). Bootstrap Mar–May, evaluate Jun–Aug.
11. ☐ Study F — competitor baselines (needs 0.30% ETH/USDC pool extraction).
12. ☐ Study G — L1 gas viability (receipts).
13. ☐ Layer-1 signed-feed ingestion + §17.5 equivalence test (when dump arrives; do not block). Replaces D's proxy with real LWBA.
14. ☐ Replication pair Study A (BTC/USDC or WBTC/ETH), after gates clear.
