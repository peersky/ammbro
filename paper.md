# REP-AMM: Oracle-Reconciled, L1-Viable LVR Capture with a Tokenized Reputation Layer

## Abstract

REP-AMM is a dynamic-fee redistribution design with an oracle-reconciled, ex-post scoring layer and a reputation market as the price-discrimination substrate. In this work we present a Uniswap v4 hook that prices every swap at execution and reconciles it after the block against trusted, signed oracle data. Arbitrage is treated as a paid job: the trader keeps a small, market-discovered allowance per unit of price correction that covers its costs, gas included, and extraction beyond that allowance is recaptured for liquidity providers from collateral posted before trading — so that paying block builders for position becomes useless — while those who consistently trade below real-time oracle prices lose reputation and, with it, their future fee discounts. We introduce these fees as counterparty-free tokenization: a new token is derived from each swap pair to create a Reputation (or Reparation, lol) asset, staking which grants fee discounts, and which itself represents the capitalized value of the adverse-selection spread that the holder's future benign volume avoids paying — a per-pair, slashable trading license whose price is sustained by the pool's expected extraction pressure. All value is settled in each pool's own pair — no external numeraire — and the work of settling it is paid in gas from a tank that every swap prefunds. We further conduct data analysis and backtest to demonstrate existing solution incompletness and how REP-AMM solves it.     

## 1. Problem statement

Loss-Versus-Rebalancing (LVR) is cost heavy for AMM liquidity providers (LPs) when informed arbitrageurs pick off stale on-chain quotes against a fresher external (CEX) price. It is a *permanent*, non-mean-reverting drain, distinct from impermanent loss, and it is large: commonly cited at **5–7% of liquidity value annually**, enough that many major pools are net-unprofitable for LPs after accounting for it. While arbitrage is useful in principle and needed, the disproportional arbitrager gains and competition for block position creates situation where AMM LPs are losing, eventually killing initial dream of DeFi where AMM LPs can make money by simply allocating capital in passive manner. 

Moreover, attempts to create optimal market fees have led to many discrete pools with diferent fees, which we believe is suboptimal.

Proposed design goal is to shift as much of the arbitrage surplus as possible from the arbitrageur back to the LP, while charging honest/uninformed flow as little as possible. Ensure that in long term, a passive LP that does not active position management can be profitable with low-risk on-chain investment. Additional goal is to introduce dynamic pool fee curve, which moves question of how much LPs should charge for swaps from fee hardcoding to being a useful dynamic variable within the system.

---

## 2. Literature review

There are two major directions found in literature:

**LVR minimization / elimination** — remove the information asymmetry at the root.
- *Oracle-priced AMMs*: quote against a low-latency oracle so there is no stale price to pick off (proposed in Milionis et al. 2022 as a direction; the only peer-reviewed oracle-based LVR-protection design predates us).
- *Liquidity-shaping*: Diamond / V0LVER reduce liquidity **only for arbitrageurs** (equivalently, an arbitrageur-specific fee), preserving normal UX for honest users.

**LVR redistribution** — let arbitrage happen, but capture and return the surplus.
- *Auction models*: am-AMM, McAMM, Angstrom auction the **right to arbitrage** (or to manage the pool) each block; proceeds go to LPs.
- *Dynamic-fee models*: price-discriminate informed vs. uninformed flow via fees that scale with volatility or with behavioral pattern recognition.


### 2.1 Milionis, Moallemi, Roughgarden, Zhang (2022) — "Automated Market Making and LVR"
The foundational paper. Defines LVR, gives a closed-form ("Black-Scholes for AMMs"), and proposes two of our building blocks as future directions**: (a) fees set by comparing LVR vs. fee income in a backward-looking window, raising fees when income < LVR; and (b) "selling special rights to arbitrage to special wallets to capture expected LVR and redistribute it."
Our backward-looking oracle reconciliation is a concrete instance of their (a). Our arb-rights-market intuition is their (b). They propose these as directions, not mechanisms. Neither is specified, implemented, or made Sybil-/farming-robust. 

### 2.2 am-AMM (Adams, Moallemi, Reynolds — Paradigm/Columbia, 2024)
Runs a censorship-resistant on-chain Harberger-lease auction for the right to be "pool manager" for a window of blocks. Manager sets the fee, collects fees, and can arb the pool at zero fee. Surplus accrues to LPs. Anything we say about "auctioning the right to arbitrage" in our work is downstream of this.
The paper *explicitly states* am-AMM provides **even fewer sandwich protections** than a fixed-fee AMM, because the manager can trade at zero fee. It also has a manager-concentration/censorship dependency (the K-block delay parameter). Our concave discount curve (§4.3) is, in part, an argument against the single-manager winner-take-all structure.

### 2.3 Diamond / V0LVER (McMenamin et al., 2022–2023)
Redistribution + minimization hybrid. Reduces liquidity *only* for arbitrageurs, rebating a (1−β) fraction of LVR to LPs. V0LVER extends toward protecting against both LVR and user-level MEV.
Diamond's authors argue *against* oracle-based designs as an "unsatisfactory dependency" as sub-block oracle prices need centralized/manipulable sources. Our proposed system **is** reliying on trusted oracle, however we belive it is acceptible due to nature of proposed protocol (see §7).**

### 2.4 Angstrom / Sorella Labs (live Uniswap v4 hook)
Runs an off-chain (mainnet) or on-chain (L2) arbitrage auction every block; the highest arb bid is sequenced first, bid proceeds distributed pro-rata to in-range LPs; all other orders clear at a **uniform clearing price** (batch), which structurally removes the front/back positions a sandwich needs. Explicitly targets LVR **and** sandwich mitigation, and has been through Spearbit/Cantina audits.
Angstrom already does arb-rights auctioning + LP redistribution + sandwich mitigation via uniform-price batching.
However, angstrom relies on **app-specific sequencing** - a decentralized operator set with sequencing rights. This is heavier trust assumption than a plain hook. This is distinct design we propose as ours needs *no* sequencer and works as a vanilla v4 hook has a real integration-simplicity argument. 

### 2.5 zScore (2025) — decentralized reputation for DeFi
Proposes Uniswap v4 hooks with **dynamic fee tiers keyed to a behavioral reputation score**, giving high-score users reduced fees (e.g. 0.1% vs 0.3%) and *explicitly names "minimal sandwich attacks" as a scoring input.*
zScore is a general-purpose reputation framework; it does not specify the *LVR-accurate, oracle-reconciled, per-swap* scoring rule, nor the anti-farming curve, nor the retroactive-bootstrap means. Our contribution, if any, is the *precise scoring function and its economic robustness*, not the idea of reputation-fees.

### 2.6 Orvex / Karma (Status Network)
A live DEX using **Karma, a soulbound non-transferable reputation token**, for reputation-based access control and rate-limiting (via Rate-Limiting Nullifiers).
Soulbound reputation gating. Karma governs spam/access, not LVR-specific fee discrimination. Also in our work that "soulbound" is the design is exactly the kind of thing our transferable-market approach deliberately rejects.

### 2.7 Optimal dynamic fees (Ghasemlu 2026; Nezlobin/Tassy 2025)
Stochastic-control and generalized-block-time treatments deriving the *optimal fee* as a function of volatility. Relevant because our concave discount-curve theorem (§6.4) is, mathematically, a cousin of this optimal-fee work. The "derive the optimal fee/curve given the divergence distribution" program is already underway for fees.
They optimize a *scalar fee*, not a *reputation-eligibility curve* that also has to resist cornering. The anti-concentration constraint is genuinely not in their objective.

### 2.8 MEV taxes (Robinson & White, Paradigm, June 2024) — "Priority Is All You Need"
A smart contract charges a fee that is an increasing **function of the transaction's priority fee**. Under *competitive priority ordering* (proposers sort strictly by priority fee, no censoring/peeking/delaying), searchers competing for a top-of-block opportunity bid up their priority fee; taxing that priority fee lets the application skim the competitive MEV. A tax of ~$99 per $1 of priority fee captures ~99% of the competitive MEV for that transaction. Paradigm names **exactly our three target applications**: DEX routers optimizing swapper price, **AMMs minimizing LVR for LPs**, and wallets capturing backrun MEV.
The "fee scales with block position / with how much LVR is available top-of-block" mechanism developed mid-project is substantially this. Priority fee is the market's own encoding of "what is this position worth," which is the LVR proxy.
MEV taxes **only work if block proposers honestly follow competitive priority ordering.** That holds on OP-Stack L2 sequencers (Base, OP Mainnet, Blast) but **may not work on Ethereum L1**, where builder auctions maximize proposer revenue and can evade the tax. Moreover, this by design cannot capture any LP lossess accuring in block mid sections. Our ex-post oracle reconciliation does *not* need honest ordering — it scores realized execution against signed external truth after finalization — so it can target L1. That, and only that, is the defensible edge (see §7, §12).


---

## 3. Methodology

We define our system from a system level goals & constraints for a theoretically optimal AMM protocol.

### 3.1 Timings & reconciliation 
First, we acknowledge that the very nature of blockchain consensus with its constraints on decentralisation and finalisation would likely never be as fast and precise as faster, centralised systems, which however inherit other kinds of risks on their own;
Thus, no matter how fast a DEX protocol substrate is, there always **will be lag** between what a high speed market orderbook sees and what distributed consensus will eventually finalize. This lag, applies not only for block times, but also for attempts to use digitally signed oracle price feeds as real time price anchor submitted as part of transaction payload - even in such a case, there still always will be some **exploitable** lag that any protocol will have to allow betwen price feed signed timstamp and actual transaction execution within the block space.

Thus, first first-principle based conclusion is that in blockchain protocol, only **a retroactive reconciliation step** against external pool(s) data is possible to provide ground truth in principle.   
This implies, that such theoretically optimal on-chain protocol should have it own finalization time, **which takes at least 2 blocks of underlying blockchain protocol** - (1) the swap, (2) the reconcilliation acting as self-correcting loop.

### 3.2 Fees & Value extraction
In ideal protocol fees for swap should approach as little as possible value as long as passive LPs stay profitable. Arbitragers in this context are required for balancing the pool, they are workers that are tasked to balance on-chain, smart contract logic secured transparent market with efficient solution that costs LPs as little as possible while keeping incentive high ehough that for any given block time, the protocol pool follows overall market trend; Protocol task is keep arbtiragers enough profitable to keep pool promptly balanced yet avoid arbitragers to pay for mempool and block builder infrastructure, as this is additional expense that LPs and protocol users eventually must bear, two means are used to achive this in game-theoretic fashion - reducing arbitrager earnings that market makes the demand for arbitrage, and on another side - reducing means that block builders can affect pool performance. 

##### 3.2.1 Arbitrage and swap Quality factor 
To address this, we introduce a parameter `q_LP`  that stands for "quality for LPs" which is a measurable objective ground truth for any swap happened in the past. This parameter is tasked to answer whether the swap at transaction time did useful and timely balance correction of pool, rather than simply extract value from LPs. 

### 3.3 LP traction
We assume that under normal conditions, LPs who have to operate active pool rebalancing today have to spend increased energy that results in their operational costs, which eventually create traction not only for passive LPs, but also for active hedging and position management to use system that would allow to count these expenses and optimise by design.


### 3.4 Execution time on a discrete ledger

As discussed in §3.1, any blockchain's discrete time stays coarser than a high-frequency observer of centralised order books; a ledger is only a rough discretisation of that process. Two facts make the discretisation sharper than it first appears. First, a block executes as one instant: its transactions run in sequence, but no time passes between them, so a transaction's index records the builder's ordering, not a moment. Second, a block's timestamp is the label of its slot, not the moment its content was decided: under proposer–builder separation the block is assembled and published into the slot, and arbitrageurs keep repricing until the final bid is taken.

We therefore *measure* when swaps are priced instead of assuming it. An arbitrage that closes a gap stops where the pool price net of the fee meets the external price it can hedge at; minimising that residual over offsets from the block timestamp gives the instant at which gap-closing flow priced its trades. On ETH/USDC (March–August 2026) this decision latency is `L` ≈ 1–1.5 s after the block timestamp (§5; bracketed against quote staleness), consistent with blocks published one to two seconds into the slot. On Arbitrum, where the sequencer orders transactions first-come-first-served and there is no slot to wait through, the same measurement gives `L` ≈ 0.75 s (§5.2).

The protocol scores every swap in a block against the same instant, `t* = block_ts + L`. A per-block anchor is **position-invariant**: no position in the block maps to a different benchmark, so position cannot be bought for a more lenient score — a direct requirement of the design aim that paying for position must be useless (§3.2).

The finer alternative — normalising transaction index into intra-block time increments of `T/N_mean_txs` (≈ 40 ms at ~300 transactions per block) — is attractive as a fairness standard but unsafe on today's chains. Index is sold to the highest bidder, and whoever controls position can then choose its benchmark time. Ordering the plane by arrival hands the top slot, which the best-informed traders buy, the oldest price and forgives ~72% of top-of-block extraction; reversing the orientation only moves the purchase to the cheap bottom of the block; clocks that count only swaps on the pool itself are bought with one's own dust swaps (in our data, $0.03 of gas buys $11 of forgiveness per arbitrage) (§5). We therefore retain the virtual time plane as a proposal for the base layer: it is safe only where ordering is enforced by time — first-come-first-served sequencing or an encrypted mempool — so that position cannot be bought.

**Chains with blocks shorter than their timestamps.** On rollups and fast chains the problem inverts. Arbitrum produces a block roughly every 250 ms but stamps blocks to the second, so three to four consecutive blocks share one timestamp; HyperEVM produces one small block per second plus a large block about once a minute, which occasionally shares a second with a small one. No block header on either chain carries a sub-second time. Here a block's timestamp is an interval of one second, not an instant, and treating it as an instant would score swaps against prices up to a second away. We reconstruct sub-second block times with the normalisation of this section applied to whole blocks: the `N` blocks sharing timestamp `S` are spread uniformly across that second, and the `k`-th is placed at the midpoint of its slice, `S + (k + ½)/N`. This differs from the index-based plane in two respects that make it defensible. It orders *blocks*, not transactions inside a block; and on these chains block order is set by the sequencer's arrival order — first-come-first-served on Arbitrum, apart from the Timeboost express lane's ~200 ms priority — rather than by an auction for position, so a block's place within its second tracks real time. It is used only to *measure* the benchmark instant; the protocol's scoring rule stays position-invariant within a block. The reconstruction is an approximation: it assumes blocks are evenly spaced inside a second, its error is bounded by ±1/(2N) of a second (≈ ±125 ms on Arbitrum, ±0.5 s on HyperEVM, where `N` is usually 1), and the residual is absorbed by the decision-latency fit and the ≈ 1 s scoring window (§4.2), both measured separately for each chain (§5).

### 3.5 Using digitally signed price oracles

Chainlink Data Streams or Pyth oracles provide digitally signed price oracles, that allow to have high-fidelity retrospective, by taking nearest data point or sliding average over grain window allow to reference grain in #3.4 to actual protocol behaviour; 

### 3.6 Pool vs Oracle liquidy depth

Price reconciliation must account for reference market depth and, as liquidity grows, the impact of the pool itself on reference prices. Mid-prices are theoretical constructs rather than executable levels; actual trades execute against open bid and ask orders. Consequently, a swap is considered arbitrage-extractive only if its execution price beats the executable reference price for that trade direction.

To capture this execution dynamic, we evaluate swaps directionally: pool sales are benchmarked against the liquidity-weighted bid price, whereas pool purchases are benchmarked against the liquidity-weighted ask price — the price at which the counterparty could unwind the trade on the reference market. Swaps priced inside the bid–ask band are therefore never scored as extractive. We utilize Chainlink Data Streams v3 reports https://docs.chain.link/data-streams/concepts/liquidity-weighted-prices, which natively supply mid, bid, and ask (LWBA) metrics, eliminating the need for supplementary price feeds. A key advantage of this model is that the LWBA spread dynamically expands during high volatility and narrows during market calm. The threshold for fair execution thus adjusts to prevailing market structure rather than relying on hardcoded parameters, ensuring that legitimate trading flow is not penalized during volatile periods.

While conservative by design, this benchmark has a known bias. Because LWBA aggregates across overall order book depth, it provides an accurate counterfactual for large, size-bearing trades; however, it can be overly permissive toward small extractions during volatile moments, where top-of-book (touch) prices represent the true counterfactual. We quantify this leniency in our benchmark-equivalence study (§N), which compares trade-price, LWBA-mid, and directional-LWBA benchmarks. Standard report LWBA is sufficient during the initial bootstrap phase. As pool liquidity approaches reference-book depth, LWBA components can be extended off-chain with the pool's on-chain liquidity data. This yields a size-aware effective price that interpolates between top-of-book and depth-weighted levels based on swap notional volume, establishing a unified liquidity baseline across off-chain and on-chain venues.
 
## 4. System design 
# §4. System Design *(draft for the REP-AMM paper — sketch, in paper voice; cross-references use the paper's numbering)*

> Drafting notes, delete before submission: (1) This section is the paper-prose port of spec §12A + §5 + §17.2/17.7, built on the constructs the paper's §3 established (two-block finalization, `q_LP`, the measured per-block decision instant, signed feeds, directional LWBA). (2) Cross-refs assume: §3.1 timings, §3.2.1 q_LP, §3.4 execution time / decision instant, §3.5 signed oracles, §3.6 depth/LWBA, §5 empirical studies. (3) The title/abstract decision on REP's billing is still open; §4.4–§4.6 are written so they can be framed either as "the second layer of the system" or "an optional layer under evaluation" with only intro-sentence changes.

## 4.1 Protocol lifecycle: execute, then reconcile

Following §3.1, the protocol's unit of operation spans two phases of the underlying chain, and the two phases settle **different things**. In the **execution phase** (block *N*), the pool's hook intercepts each swap, reads the trader's **active reputation stake** (§4.5), and charges the fee determined by that stake through the coverage curve (§4.3) — **the fee is final at this moment**. Unstaked flow pays `f_max` outright. The swap executes normally and the hook logs the raw pool-perspective token deltas (Δ₀, Δ₁), the transaction's index, and the block metadata. No oracle is consulted at execution: trading remains permissionless, synchronous, single-transaction, and unaffected by feed latency or liveness.

In the **reconciliation phase** (any later block), a swap's account is settled against the signed prices for its blocks — a price batch signed once by the oracle — either by the account itself, at any time, or by a keeper at the end of the epoch (§4.6). Settlement computes each swap's quality factor `q_LP` against the directional benchmark (§4.2) and acts **against stake only**: benign aggregates mint REP (§4.4); extraction beyond the job allowance (§4.3) is debited from the trader's stake, in the order of §4.5. No new funds are requested at reconciliation — it settles only against collateral locked at execution. Keepers are paid in gas from a tank that every swap prefunds, with a bounty that escalates with delay, so prolonged stalls are self-healing (§4.6).

This division follows from §3.1 by one further step: since a swap's true quality is knowable only retroactively, and cash cannot be recalled from a counterparty who has departed, the protocol prices execution-time fees off the only thing it can still reach afterward — the trader's locked stake. Staked reputation is thereby simultaneously the fee determinant and the collateral. Reconciliation timing becomes a pure keeper-economics choice (next-block vs. batched), costing users nothing in locked capital; the scoring instant is pinned regardless, since a late reconciliation still scores each swap against the signed price at its block's decision instant.

## 4.2 The scoring rule: pair-native, directional, instantaneous

All economic quantities settle in the pool's own pair; the single external input to the system is the signed oracle pair price. For a swap with pool-perspective deltas (Δ₀, Δ₁) in a block with decision instant *t* (§3.4):

```
markout = Δ₀ + P_dir(t)·Δ₁          (token0 terms)
q_LP    = markout / notional         (dimensionless)
```

where `P_dir(t)` is the **directional** benchmark of §3.6: the liquidity-weighted bid when the pool sells the asset, the liquidity-weighted ask when the pool buys, evaluated at the block's decision instant `t*` (h = 0). Where the pair price must be composed from two single-asset feeds, each side is composed as the round trip it represents: the pair ask is buy-leg-ask over sell-leg-bid, and the pair bid is sell-leg-bid over buy-leg-ask.

Three properties carry the section's weight. *Numeraire symmetry:* re-denominating in token1 rescales markout and notional identically; `q_LP` is unchanged, so the numeraire is bookkeeping, not economics. *Direction-freedom:* the delta formulation needs no per-side sign conventions; benign overpayment is `q_LP > 0` for buys and sells alike. *Instantaneity:* scoring at h = 0 measures the extraction where it occurs — against the executable reference price at the moment of the trade — rather than against later prices that mix extraction with market drift. Forward-horizon markouts (+12s, +30s) are retained as robustness cross-checks, not alternative definitions: they bound reconstruction and feed-latency noise and close the surface against horizon-aware adversaries.

Because the decision instant is measured rather than observed per transaction (§3.4), `q_LP` is evaluated as an average of the signed price path over a narrow window centred on `t*` (≈ 1 s), rather than a point read. The window must be centred on the decision instant: a window trailing the block timestamp scores arbitrageurs against prices from before the move they trade on and erases most measured extraction — over a 12 s trailing window the measured LP loss turns into a profit (§5). The residual tolerance ε — the timing noise left inside the window, ≈ 1 bp at the 90th percentile — is calibrated in §5 and sits alongside the endogenous tolerance the LWBA spread already provides. ε also absorbs the oracle's own error against the market. A bias `b` is cancelled exactly by `ε = |b|`, and per-report noise σ needs `ε ≈ 2σ`; each basis point of ε gives up roughly 8% of the recapture, so the rule is `ε ≈ max(|b|, 2σ)` for the feed in use, and ε ≈ 1 bp presumes a feed within about a basis point of the market (§5.7). Charges on ordinary (router) flow stay below 0.3 bp under every oracle error we tested; oracle error lands on arbitrage-sized trades.

## 4.3 The fee system: coverage curve and extraction charge

The fee a trader pays has two components: the coverage curve, settled on the trader's **per-epoch aggregate** rather than per swap — a choice forced by a structural argument developed below (§4.6) — and the job charge on arbitrage, computed **per price-correcting swap** (§4.8).

**The coverage curve** prices ordinary flow. Staked reputation `r` grants discounted-volume capacity `C = r/ρ` per epoch, and the fee on covered volume follows

```
f(r, V) = f_min + (f_max − f_min) · exp(−r / (ρ·V))
```

The curve is decreasing and convex in `r` (diminishing returns per marginal unit of reputation — the anti-concentration property), increasing in `V` (larger flow requires proportionally more stake), asymptotic to `f_min` (liquidity providers always earn a floor, approached but never reached), and homogeneous of degree zero (doubling stake and volume together leaves the rate unchanged: the curve prices *coverage ratio*, not wealth, so a proportionally staked institution pays what a proportionally staked retail trader pays). Volume beyond capacity pays `f_max` on the excess. Reference band: `f_min` = 1 bp, `f_max` = 5%.

**Arbitrage as a paid job.** Rebalancing is a service the pool needs (§3.2); extraction beyond its competitive cost is what the pool should not pay. At reconciliation each swap keeps

```
kept = ∫ min(edge(u), m) du
```

where `edge(u)` is the marginal gap between the oracle and the pool price, beyond the pool fee, at each point `u` along the trade's price path, and `m` is the **job allowance** per unit of corrected volume. The allowance covers all of the arbitrageur's costs — hedging, capital and gas alike. The pool does not reimburse gas separately: doing so would value the chain's gas token in the pool's own units, a price the protocol never takes (§4.6). Since `m` is discovered rather than set (below), gas is absorbed into it like any other cost; on our data this gives up 5% of the worst-case LP gain on mainnet and nothing on Arbitrum (§5.5). For every swap that moves the pool toward the oracle, everything beyond `kept` is recaptured for liquidity providers by debiting the stake that backs the swap, in the order of §4.5. Swaps that move the pool away from the oracle cannot extract and are never charged. The charge is computed per correcting swap rather than on an account's aggregate, so that no account can net other traders' overpayments against its own extraction (§4.8).

Capping rent *per unit along the price path*, rather than on the trade's average edge, gives three properties. The arbitrageur stops where its marginal edge equals its own cost, so the pool is corrected to the competitive band and never past it; an average-edge cap pays the allowance on every unit while the average stays above it, and arbitrageurs then push the pool past the oracle to inflate volume (§5). The rule is split-invariant — the integral over a price path is additive, so dividing a trade gains nothing, without needing a convex schedule. And it is position-invariant: it pays any correcting swap, whether it opens the block or restores the pool after other users' trades.

When the collateral is REP, the charge is burned at the inverse of the mint scalar (§4.4): REP is minted and burned at the same internal rate per unit of pool value, so no market price of REP enters either formula. Whether that rate keeps the collateral sufficient when REP trades below it is evaluated in §5, against a plain bond.

**The allowance is discovered, not set.** The competitive cost of rebalancing is private and moves (exchange fee tiers, hedging, capital), so no fixed `m` is safe: set too low, rebalancing stops; set too high, the surplus is bid to block builders for position. `m` is set by a feedback loop on information the reconciler already holds:

```
every ~1 hour : if at least 5 blocks began with a gap beyond f + m + ε that the block's first
                swap did not correct, and they are more than 2% of such blocks      →  m ← 2m
every epoch   : lower m ← 0.95·m only if competition is observed (below); otherwise hold
```

Any arbitrageur whose cost is below `m` profits from correcting a gap beyond `f + m`, so in a healthy pool such blocks almost never occur; once `m` falls below every arbitrageur's cost they occur every time. Raises are fast, so a shock in arbitrage costs costs hours of rebalancing rather than days.

Lowering needs more care. Under a per-unit cap, an arbitrageur keeps at most `m` per unit, so when `m` falls below the cheapest arbitrageur's cost no correction is profitable at any gap size: arbitrage supply has a cliff, not a slope. A controller that lowers `m` blindly finds the cost only by crossing that cliff, and pays for each crossing with a stall in rebalancing (in our data, one to three hours roughly every two weeks, §5.5). The controller therefore lowers `m` only on evidence that more than one arbitrageur could still do the job. On a chain that orders transactions first-come-first-served, any arbitrageur that would profit can arrive first, so while several can profit the correcting swaps come from several senders, and as `m` nears the cheapest cost they come from one. The reconciler sees every correcting swap's sender; the epoch's decay is applied only if more than a quarter of its correcting swaps came from senders other than its top one. The loop then settles between the cheapest and the second-cheapest arbitrageur's cost — where one can do the job and nothing is left to bid for position — without crossing the cliff. The signal is costly to fake in the direction that matters: an arbitrageur posing as several only lowers its own allowance, and suppressing it requires a cartel that any arbitrageur with cost below `m` can break. Under a builder auction, the cheapest arbitrageur outbids the rest and wins every block it can profit from, so sender diversity under-reports competition; there the controller falls back to blind decay and accepts the periodic stall (§5.5). Either way the arbitrageur's payout is set by competition between arbitrageurs, not by a protocol constant.

## 4.4 The reputation asset: minting as surplus sharing

Reputation (REP) enters the system in exactly one way: as a claim on realized surplus above the liquidity providers' target. Per epoch, with `θ*` the target take-rate:

```
N = Σ fees + Σ markouts        (pool net income, token0 terms)
S = N − θ*·ΣV                  (surplus over target)
```

When `S > 0`, REP is minted pro-rata to accounts whose fees-plus-benign-markout exceeded the target on their own volume — the traders who overpaid relative to what the pool needed. Minting is a fixed protocol scalar per unit of surplus share; no market price of REP enters any internal formula.

**Protocol take.** REP is minted slightly below the surplus it claims: a share `τ` of each epoch's surplus is withheld by the protocol. The take is required by design, not a convenience: the per-pool reserve (§4.5) must be funded from something other than unbacked minting, and REP must be minted below the surplus it claims so that the reserve carries a safety margin. `τ` funds the reserve and nothing else — it is denominated in the pool's own pair, like every other quantity of value in the protocol. The gas spent settling the pool is a different economy and is paid differently: every swap prefunds its share of settlement gas into a gas tank (§4.6), so settlement never draws on the pool's value and never needs a price between gas and the pool's assets. Measured on ETH/USDC, keepers' settlement costs would be 0.1–0.24% of the value recaptured from arbitrage if they were paid from τ instead (§5.9) — small either way, but the separation keeps the mechanism pair-native. This yields two properties at once. The mint is **self-funding**: total minted claims are a share of surplus actually collected in fees, so wash-trading mints nothing net — a wash trader's claim was prepaid out of their own overpayment, converting cash fees into future-discount rights and nothing more. And the target is **self-enforcing**: over-earning mints capacity, which grows discounted volume and pulls income back toward the target; under-earning halts minting while burns (§4.5) shrink capacity and push income back up. The liquidity providers' "asymptotic profit target" of §1 is not imposed anywhere — it is the fixed point of the mint valve, with the mint scalar as the damping knob under a standard stability bound.

Extraction has the mirrored consequence: extraction beyond the job allowance (§4.3) is burned from the trader's stake (§4.5) at the same internal rate at which surplus mints, and the capacity consumed by the offending volume is destroyed rather than renewed.

Reputation-denominated settlement is a deliberate choice over holding fees in escrow and refunding them. Financially, staked REP is a slashable trading license — the capitalized value of the adverse-selection spread the holder's future benign volume avoids paying. This is strictly better than locked cash on three counts. First, capital efficiency: escrowed fees are dead capital awaiting refunds, while REP is productive collateral — it earns its holder the discount continuously and never needs to be returned, so money settles once and no user funds ever wait on a keeper. Second, credibility: a cash deposit is worth the same to honest and toxic flow alike and so separates nothing, whereas REP is differentially costly — cheap to hold for benign flow, ruinous for extractors (the burn destroys an annuity to dodge one epoch's fee) — which is precisely what makes the discount tier credible. Third, the collateral appreciates with the pool: locked cash is inert, while REP's value grows with the pool's benign volume, aligning its holders with the pool's health instead of merely parking their money against it.

## 4.5 Staking, settlement-hold, and exit

Reputation influences fees only when **staked**; balance-at-execution reads are excluded by design, since they would permit flash-rental of the discount (borrow, swap at tier, return, within one block). Staked REP moves through three states:

```
ACTIVE ──(trade: ℓ·V held)──► IN-FLIGHT ──(settle, benign)──► ACTIVE
                                         ──(settle, extractive)──► BURNED
ACTIVE ──(unstake)──► EXITING ──(delay, no pending flights)──► WITHDRAWN
```

The fee curve reads **active** stake only. When a trade consumes capacity, `ℓ·V` of the trader's active stake is held in flight until that epoch reconciles: a second trade inside the window faces a worse point on the curve, so intra-settlement throughput is metered by reputation itself — a dynamic rate limit priced by the curve rather than a hard lock, leaving honest multi-hop routing within capacity unaffected. Newly staked REP activates only after a delay of several epochs, and exit requires a delay exceeding worst-case settlement with no flights pending — so none of an account's stake can leave while any of its trades awaits reconciliation.

**How much is parked.** The charge a trade can incur scales with how far the pool was from the market when it traded — a quantity the hook cannot see at execution — while any parking rule must use what the hook can see. The rule is

```
ℓ = ρ + k · Δ_block
```

where `Δ_block` is the pool's cumulative price move so far in the block, including this trade, and `k` is a per-pool parameter. In calm markets the pool barely moves and `ℓ ≈ ρ`; after a jump in the external price, corrections move the pool fast and park correspondingly more. A trader cannot shrink `Δ_block` by splitting a correction into many small trades or across accounts within the block: the pool's motion is shared. Rules keyed to the trade's own size or count — e.g. parking growing exponentially with swap size — are not used: the trader controls those quantities, and splitting one correction into ten pieces halves what they collect while large honest swaps are over-charged (§5).

**Who pays a charge.** Charges are collected in a fixed order:

1. the trade's own parked stake `ℓ·V`;
2. the **rest of the same account's stake** — reachable because exit is blocked while flights are pending;
3. a **per-pool reserve**, only if the account is exhausted (an abandoned or drained account), funded by the protocol take — REP minted slightly below the surplus it claims (§4.4).

A charge is never collected from other traders' parked stake. Pooling collateral across traders would make honest users pay for an extractor's bill while leaving the extractor's own remaining stake untouched — the incentive pointing the wrong way. The reserve amortizes only the residual risk that remains once the extractor's whole stake is gone, and it costs one pool-level balance. The parking rule therefore sets how much of an account's stake stops earning discounts while in flight, not how much can be collected: collection is bounded by the account's whole stake plus the reserve. On ETH/USDC the charge is heavy-tailed — its 99.9th percentile is 21 bp of notional, its maximum 358 bp, and 27% of all charge comes from trades above 50 bp — so a parking rate alone would collect between 70% and 90%; with the whole account stake behind it, collection is complete for an account staking its worst epoch's charges (about $1M for the dominant arbitrageur in our window) (§5). An account with no stake cannot be charged after the fact and pays `f_max` at execution.

## 4.6 Feasibility of on-chain reconciliation

Reconciliation is viable by a capacity argument. Whatever set of swaps block *N−1* accommodated, scoring them requires per-swap work strictly smaller than executing them: a markout is one multiply-add against an already-verified report price, a tolerance comparison, and one reputation-state write, with the report's signature verification amortized across every swap scored in its validity window. If per-swap reconciliation gas is bounded by per-swap execution gas, the protocol's steady-state footprint is at most twice its own swap footprint — bounded by construction, scaling only with the pool's own usage, never beyond what the chain has already demonstrated it can process; lazy settlement (below) smooths it further.

Settlement is organised around the account rather than the pool. At every swap the hook extends the swapper's own record — the post-trade price, the active liquidity and the swap's token deltas, chained by hash in the account's storage, which the parking lock of §4.5 writes in any case. The unsettled swaps of an account therefore form a complete and self-contained segment that can be settled independently of every other account. Two paths settle such a segment, and both advance the same settlement pointer, so that no swap can be settled twice. An account may settle itself at any time by submitting its records together with the signed prices for their blocks; the charges are computed and its stake is updated in a single transaction, at the account's own expense. Frequent traders have a reason to do so, because settlement releases their parked stake: in our sample it reduced the stake they required by 15–24% (§5.9). Every account that is still in flight at the end of an epoch is settled by a keeper, whose batch consists of one result per account. An entry for an account that has settled itself in the meantime is skipped rather than reverted, so that self-settlement cannot be used to invalidate a keeper's batch.

Negative settlement therefore does not depend on the trader's cooperation: the keeper settles every account that an epoch leaves behind, and charges reach the account's whole stake (§4.5), not only its parked part. A default rule remains as a liveness backstop, exploiting the flight mechanism of §4.5: **an in-flight tranche that remains unreconciled when the signed-data retention window (on the order of a month) expires is burned in full**, and the account's remaining stake stays frozen until its flights are settled.

Keepers are paid without recourse to any numeraire. Every swap prefunds its share of settlement gas, `G × block.basefee`, into a gas tank: a fixed number of gas units multiplied by a quantity the chain exposes at execution, so that no price is involved. Keepers are reimbursed from the tank for the gas their settlement consumed, together with a bounty that escalates with delay; alternatively, an ERC-4337 paymaster funded by the tank sponsors the keeper's settlement transaction, so that keepers need hold no gas at all. Because every pool's contribution is denominated in the same unit, a single tank can serve many pools, and the settlement of small pools can be supported by the swaps of large ones without an exchange rate. Two further rules keep the tank inexpensive. Settlement is never required in the current block, since a long deadline allows keepers to wait for low base fees; and the length of an epoch is a per-pool parameter, so that a pool with little flow can settle daily rather than hourly. On our data, a tank shared by seven mainnet pools remained solvent with 1,400–2,300 gas per swap at daily epochs, less than 1.2% of a swap's own gas, and 640 gas per swap on Arbitrum (§5.9).

The appropriate market for keepers depends on how settlement is computed. When the charges are computed on-chain, keepers do no off-chain work and an open race with an escalating bounty is efficient. When settlement is proven off-chain, keepers of similar cost racing one another duplicate the proving, and a designated settlement leader per term — selected by auction or by a random draw among staked keepers, with a bond slashed for each missed epoch — removes the duplication; the open race remains as a fallback after a deadline. A leader cannot alter any charge, since charges follow from the account's record chain and the signed prices; collusion can therefore only delay an epoch's credit to liquidity providers, which in our sample was worth less than one cent per epoch (§5.9).

What reconciliation computes is bounded and local. The hook records each swap's post-trade price, active liquidity and token deltas, from which the pre-trade price follows within a single liquidity range. Within such a range the job allowance has a closed form, and most corrections move the price by less than one tick spacing; trades that cross a range boundary are recomputed off-chain from pool state and posted optimistically, subject to challenge within the retention window. The allowance controller of §4.3 requires only quantities that reconciliation already holds — each block's resting price, its signed report, the direction of its first swap and the sender of each correcting swap — and no transaction indices.

The measured cost supports the capacity argument (§5.8). On a Uniswap v4 pool the hook — the parking lock, the collateral check and the account's record — adds 17,000 gas to a swap; self-settlement costs 46,000 gas plus 6,000 per swap; a keeper's epoch costs 26,000 gas plus 14,300 per account settled; and a batch of prices signed once requires a single signature check. Hourly settlement with the charges computed on-chain then costs 0.18 of the swaps' own execution gas on mainnet and 0.19 on Arbitrum, including the hook, which satisfies the bound by a factor of about five. A succinct proof of an epoch's charges, verified for 227,000 gas, lowers the cost only to 0.14–0.15: once prices arrive in a single signed batch, the per-swap hook and the per-account writes dominate, and a proof removes neither. The viability of the mechanism therefore does not depend on proofs.

## 4.7 Parameters

The complete parameter set: `θ*` (LP target take-rate), `f_min`/`f_max` (fee band), `ρ` (capacity scale and base parking rate), `k` (per-pool parking speed, §4.5), the protocol take `τ` (§4.4; funds the reserve), the mint scalar (stability-bounded; its inverse is the burn rate), `L` (decision latency, measured) and the scoring-window width, `ε` (residual tolerance, bound to the measured timing-noise floor and to the feed's error, `ε ≈ max(|bias|, 2σ)`), the gas withholding per swap `G` and each pool's epoch length (§4.6), the keeper bounty's slope and the settlement deadline, the job-allowance controller (raise and decay steps, the 2% raise threshold, the minimum count of uncorrected blocks, the sender-diversity share that permits decay, and the starting allowance `m₀`, which bounds the allowance when only one arbitrageur is active), the settlement window, the activation delay, and the exit delay. The job allowance `m` itself is not a parameter: the controller discovers it. Consistency conditions — that `f_min` clears reconciliation economics, that the fee spread simultaneously prices REP and sizes the parked stake, and that account stake plus the reserve cover the tail of extraction — are evaluated in §5.


## 4.8 Initial supply, intermediaries, and who the arbitrageur is

At launch no account holds REP, so every swap would pay `f_max` and ordinary flow would route elsewhere. The protocol therefore issues an **initial supply**, sold rather than granted: its proceeds seed the per-pool reserve (§4.5), so pre-minted REP is backed at issuance just as minted REP is backed by collected surplus (§4.4). Issuance is priced slightly below the discount it confers — the same protocol take `τ` as ongoing minting (§4.4) — so that from the first block the reserve carries a safety margin while REP's price is discovered. Part of the proceeds seeds the gas tank (§4.6), which a launch needs: from an empty tank, the first epochs' settlements would need up to twice the steady-state withholding (§5.9).

The supply needed is small relative to the flow it serves. Bringing a fee within δ of `f_min` requires `r ≥ ρ·V·ln((f_max − f_min)/δ)` (§4.3); with the reference band and δ = 1 bp this is ≈ 6.2·ρ·V. On ETH/USDC, non-arbitrage user flow averaged $26 M per day over our window, so a daily-epoch pool needs about $16 k of active REP per basis point of `ρ` to offer near-floor fees to all of it.

Users need not hold REP themselves. Intermediaries that already route user orders — solvers, fillers, RFQ desks; *cashiers* — can hold the stake, quote users discounted fills, and sell the REP their customers' overpayment mints; competition between them passes the discount on. Intermediaries also answer the question of whose stake backs a swap when the hook sees only a router: the stake that backs a swap is the submitting account's, named in the swap's hook data. The protocol is agnostic to this structure; it is one way the initial supply reaches users.

This raises the question of who the arbitrageur is. **By design the protocol never identifies arbitrageurs: arbitrage is a role carried by a swap, not an identity.** Any swap that moves the pool toward the oracle is doing the rebalancing job and is paid the job allowance on it (§4.3); every other swap is scored as ordinary flow. An intermediary that routes its customers' orders and also corrects the pool is an arbitrageur for its correcting swaps and a router for the rest. This is why the charge is computed per correcting swap rather than on an account's aggregate: under an aggregate rule an intermediary could net its customers' small overpayments against its own extraction and leave the latter uncharged — extraction laundered through other people's flow. Per-swap charging removes that incentive at negligible cost to ordinary users: a user whose swap happens to correct a stale pool still pays no more than the market price plus fees, and loses only the windfall beyond the allowance — on benign-labelled flow in our window, at most about $0.01 M.

## 5. Empirical evaluation

This section evaluates the mechanism of §4 against six months of on-chain data. We first describe the data, the benchmark and the scoring procedure (§5.1). We then measure when swaps are priced (§5.2), test whether the scoring rule separates informed from uninformed flow (§5.3), bound the surplus that can be recaptured (§5.4), and compare payout rules for arbitrage in a block-level simulation (§5.5). The remaining subsections examine the adequacy of collateral (§5.6), the sensitivity of the mechanism to oracle error (§5.7), the on-chain cost of settlement (§5.8) and the economics of the settlement layer (§5.9). §5.10 states the limitations of the evidence. All monetary figures are reported in US dollars for comparability; this is a unit of reporting only, and the mechanism itself uses no numeraire beyond each pool's own pair (§4.4, §4.6).

### 5.1 Data and methodology

**Venues and sample.** We study two pools over 1 March – 31 August 2026: the Uniswap v3 ETH/USDC pool with a 5 bp fee on Ethereum mainnet, and the corresponding WETH/USDC pool on Arbitrum One. The mainnet pool carried 89% of Uniswap's ETH/USDC volume in the window. We extract every swap from the chain's event logs through a commercial RPC endpoint, together with block timestamps and the sending account of each transaction. Table 1 summarises the sample. Arbitrum produces roughly four blocks per second but stamps them to the second; we place the *N* blocks that share a timestamp *S* at *S* + (*k* + ½)/*N* (§3.4), and we count transaction positions over user transactions only, since every Arbitrum block opens with a system transaction.

| | Ethereum mainnet | Arbitrum One |
|---|---|---|
| Pool (fee) | ETH/USDC (5 bp) | WETH/USDC (5 bp) |
| Swaps | 990,555 | 5,237,793 |
| Blocks in window | 1.32 M (12 s slots) | 63.4 M (≈ 0.25 s) |
| Blocks containing a pool swap | 595,030 | 1,868,277 |
| Median swap notional | $1.5 k | $1.3 k |
| Six-month volume | $19.6 B | $11.2 B |

*Table 1. Sample.*

**Benchmark.** The external reference is the Binance spot price of ETH in USDT, divided by the USDC/USDT rate to express it in the pool's quote asset. Because the protocol is designed to score against a signed liquidity-weighted bid and ask (§3.6), we construct a bid/ask proxy from Binance's aggressor-flagged trades: the most recent seller-initiated trade approximates the bid, and the most recent buyer-initiated trade approximates the ask. The proxy is a touch-level quote and understates the depth-weighted spread that a large trade faces.

**Scoring.** Each swap is scored with the directional benchmark of §4.2 — the bid when the pool sells the risky asset and the ask when it buys it — averaged over a one-second window centred on the block's decision instant *t\** = block timestamp + *L*, where *L* is the decision latency measured in §5.2. The quality factor is the liquidity provider's markout per unit of notional, `q_LP` = (Δ₀ + P·Δ₁)/notional, evaluated at horizon zero. Negative values indicate that the swap extracted value from liquidity providers.

**Control.** A stable–stable pool (USDC/USDT) on each chain serves as a negative control: since neither leg moves materially against the other, any systematic score on that pool would indicate an artefact of the benchmark rather than economic extraction. The absolute score on the control pools had a median of 0.93 bp and a 95th percentile of 2.25 bp on mainnet (1.06 bp and 2.31 bp on Arbitrum), well below the ceiling of 38.4 bp implied by three times the 99th percentile of the USDC/USDT peg deviation. We therefore treat the benchmark as fit for scoring.

**Simulation.** Payout rules and the allowance controller cannot be observed on existing pools, so §5.5 replays every block in the window with its real oracle path and its real non-arbitrage swaps, and lets a population of optimising arbitrageurs with hedging costs between 0.3 and 2.5 bp correct the pool under each rule. To test adaptation, arbitrage costs are multiplied by four or by eight from 1 June onwards. The simulation models the pool with linear depth estimated per day from real swaps and replays user flow at its observed size and direction.

### 5.2 Decision latency

A swap that closes a price gap stops where the pool price, net of the fee, equals the external price at which the arbitrageur can hedge. Minimising the residual of that relation over offsets from the block timestamp therefore identifies the instant at which gap-closing flow priced its trades. Because the bid/ask proxy is itself slightly stale, we estimate the offset twice — once with the last quote before each instant, which biases the estimate late, and once with the next quote after it, which biases it early — and take the midpoint.

On mainnet the decision latency is *L* = 1.5 s, bracketed between 1.25 s and 1.75 s. This is consistent with blocks being assembled and published one to two seconds into their slot under proposer–builder separation. On Arbitrum *L* = 0.75 s; the bracket is wider (0 to 1.5 s) because at sub-second block times the staleness of the proxy dominates the estimate, but the separation results of §5.3 are insensitive to the choice within the bracket. The window must be centred on *t\**: a window that trails the block timestamp by twelve seconds scores arbitrageurs against prices from before the move on which they trade, and turns the measured mainnet loss of $1.58 M into an apparent gain of $5.26 M. The timing noise that remains inside the centred one-second window is 0.80 bp at the 90th percentile on mainnet and 1.72 bp on Arbitrum.

### 5.3 Validity of the scoring rule

We test whether `q_LP` distinguishes informed from uninformed flow using labels that do not depend on price. Swaps routed through retail aggregators are labelled benign; the attacking legs of sandwich attacks and top-of-block swaps by repeat non-router senders are labelled toxic. The labels serve only as an external check — the mechanism itself scores every swap. Table 2 reports the area under the receiver operating characteristic curve (AUC), the probability that a randomly drawn toxic swap scores below a randomly drawn benign one.

| | Ethereum mainnet | Arbitrum One |
|---|---|---|
| AUC, all labelled swaps | 0.889 | 0.814 |
| AUC, largest 4.55% of swaps by notional | 0.983 (> $100 k) | 0.897 (> $7 k) |
| Gross LP loss to extraction | $9.68 M | $1.34 M |
| LP net position after fees | −$1.58 M | +$0.86 M |
| Extraction in user positions 0–2 / ≥ 10 | 61% / 21% | 6% / 69% |

*Table 2. Separation of labelled flow and the scale of extraction at horizon zero.*

The score separates the two classes well on both chains, and best for large swaps, where informed trading concentrates. Two contrasts between the venues are informative. First, extraction on Arbitrum is real but small relative to fees: liquidity providers lost $1.34 M to extraction over 5.3 times as many swaps as on mainnet, and ended net positive, because fills on the sequencer are small. The sign of that net result depends on the benchmark — it is −$0.04 M at the last trade price and +$0.86 M at the directional bid/ask — which shows that the directional benchmark matters most where edges are thin. Second, the position of extraction within the block follows the ordering regime. On mainnet, where position is sold by builders, 61% of extraction occurs in the first three user positions; on Arbitrum, whose sequencer orders transactions by arrival, 69% occurs at position ten or later, because an arbitrageur lands wherever the block happens to be when the external price moves. A per-block anchor scores both regimes identically.

### 5.4 The recapture ceiling

Before introducing the payout rule of §4.3, we bound what any charge on extraction could recover. We apply, with perfect information, a margin schedule that charges extraction beyond an allowance of 2 bp and caps the charge at `f_max`. The allowance was set by reasoning — the assumed hedging cost of 1 bp plus a buffer of 1 bp — and not fitted to the data. The schedule recaptures 73% of gross extraction on mainnet, raising liquidity providers' net position from −$1.58 M to +$5.52 M over the window, and 70% on Arbitrum. The overcharge on benign flow is 0.06–0.07 bp, and between 97% and 99% of the arbitrage that covers its real costs (base-fee gas plus a 1 bp hedge) remains profitable. The rent available for bidding for transaction order falls from $8.51 M to $1.41 M on mainnet and from $1.09 M to $0.15 M on Arbitrum.

To check that this result is not an artefact of choosing the schedule on the same data, we select the best schedule on March–May, subject to preserving 95% of profitable arbitrage, and evaluate it on June–August. On mainnet the selected schedule is the one fixed a priori; on both chains the a-priori schedule is also the best schedule in hindsight on the test period.

### 5.5 The arbitrage payout rule and allowance discovery

The simulation of §5.1 compares payout rules under the constraint that the pool remain as well rebalanced as it is today. Because Arbitrum blocks are fifty times shorter than mainnet slots, the constraint is stated in quantities that do not depend on block time: the share of blocks whose resting price lies within the fee plus 1 bp of the oracle may not fall by more than 0.5 percentage points, and the volume-weighted distance between the pool price and the oracle at which users trade may not rise by more than 0.1 bp. Rules that violate the constraint are discarded regardless of their effect on liquidity providers, since a pool that is no longer rebalanced would lose the flow that the simulation replays as fixed.

Table 3 reports the worst-case gain to liquidity providers across the three cost scenarios. The per-unit cap of §4.3, with its allowance discovered on-chain, raises liquidity providers' net position by $4.81 M on mainnet and by $0.66–0.71 M on Arbitrum, and transfers most of the $6.57 M that arbitrageurs pay for transaction order today to liquidity providers. Reimbursing gas in addition to the allowance would add $0.26 M on mainnet and nothing on Arbitrum; we forgo it because it would require valuing the chain's gas token in the pool's units. An allowance capped on the trade's average edge rather than per unit fails the constraint: it pays arbitrageurs to push the pool past the oracle, producing 23,079 overshooting blocks, and users then trade about 5 bp further from the market.

| Payout rule and controller | Mainnet | Arbitrum |
|---|---|---|
| Per-unit cap, allowance by controller observing competition (not feasible on-chain) | +$5.11 M | +$0.75 M |
| Per-unit cap, blind decay of the allowance | **+$4.81 M** | **+$0.71 M** |
| Per-unit cap, decay gated on sender diversity | — † | **+$0.66 M** |
| Per-unit cap, fixed allowance of 5 bp | +$3.68 M | +$0.42 M |
| Average-edge cap | fails constraint | fails constraint |

*Table 3. Worst-case gain to liquidity providers over the three cost scenarios, relative to today. † Sender diversity presumes a first-come-first-served race; under a builder auction the blind-decay controller is the feasible choice (§4.3).*

The controller deserves separate comment. A controller that lowers the allowance blindly finds the cheapest arbitrageur's cost only by crossing it, and each crossing stops arbitrage until the allowance is raised again: rebalancing stalled for 0.6–3.1 hours in total over the window on mainnet and 4.7–7.1 hours on Arbitrum, concentrated in episodes of one to three hours roughly every two weeks. Gating the decay on evidence that more than one arbitrageur is winning eliminates the stalls when costs are stable; what remains is the recovery from the cost shock itself (1.7 and 2.7 hours on Arbitrum under the fourfold and eightfold shocks), at a cost of 7–8% of the worst-case gain. The conclusions are robust to the assumed arbitrage population (a monopolist, two arbitrageurs or ten; all costs halved or doubled) and to pool depth (halved or doubled): every variant keeps the pool rebalanced on both chains. A monopolist never reveals competition, so the allowance remains at its starting value; the rent is then bounded by that value rather than discovered.

### 5.6 Collateral adequacy

Charges must be collectable from stake locked before the trade (§4.5). In the simulated settlement of the chosen design, the charge per trade is small at the median (0.17 bp of notional) but heavy-tailed: its 99th percentile is 8.4 bp, its 99.9th percentile 21 bp and its maximum 358 bp, and trades charged above 50 bp account for 27% of the total charge. A parking rate sized to the typical trade therefore cannot collect the tail on its own; parking alone collects between 70% and 90% of the charge, depending on its rate. The remainder is collected from the rest of the account's stake, which cannot leave while charges are pending, and in the last resort from the per-pool reserve. Parking keyed to the pool's price movement within the block is unaffected by splitting a correction into smaller trades, whereas parking keyed to trade size is not: splitting a correction into ten trades halves what it collects.

### 5.7 Robustness to oracle error

Every charge rests on a signed report, so we score the recapture schedule of §5.4 with a deliberately degraded oracle — delayed by up to five seconds, perturbed by independent noise of 1–5 bp per report, or biased by ±1–3 bp — and compare its charges with those computed from the true benchmark. Table 4 summarises the results.

| Oracle error (tolerance ε = 0) | Unjustified share of charges, mainnet / Arbitrum | Recapture, mainnet / Arbitrum |
|---|---|---|
| None | 0 / 0 | 73% / 70% |
| Delay of 1 s | 5.2% / 1.4% | 70% / 37% |
| Noise of 2 bp per report | 11% / 19% | 78% / 80% |
| Bias of +1 bp | 6.4% / 8.0% | 75% / 72% |
| Bias of −3 bp | 21% / 35% | 81% / 93% |

*Table 4. Effect of oracle error on the recapture schedule.*

Three findings follow. First, ordinary flow is protected: the overcharge on benign-labelled swaps remained below 0.3 bp under every error considered, because oracle error is small relative to the fee for swaps that do not extract. Second, the tolerance ε of §4.2 is the protocol's instrument against oracle error, at a measurable price: a tolerance equal to the bias removes a bias exactly, a tolerance of about twice the noise removes most of a random error, and each basis point of tolerance gives up about 8% of the recapture. This yields the rule ε ≈ max(|bias|, 2σ) for a feed with bias and noise σ. Third, staleness is the binding error on a fast chain. A feed one second old halves the recapture on Arbitrum, where swaps are priced 0.75 s after their block, while it costs three points of recapture on mainnet. A rollup deployment therefore requires a sub-second pull oracle rather than a periodic feed.

### 5.8 Cost of settlement

The capacity argument of §4.6 requires that settling a swap cost less than executing it. We measure each component directly. The median single-swap transaction on the study pools uses 188,705 gas on mainnet and 136,171 on Arbitrum (400 receipts each). Verifying a real Chainlink Data Streams report, obtained by tracing historical verification calls, costs 55,879 gas on mainnet and 62,544 on Arbitrum, or 37,544 for each further report in the same transaction; no fee is transferred on-chain. Under the assumption that the oracle signs each batch of prices once, verification reduces to a single signature check per batch.

The remaining components were measured in Foundry on a Uniswap v4 pool manager, executing each call as a separate transaction. The hook — the parking lock, the collateral check and the account's record — adds 17,112 gas to a swap (140,801 against 123,689 without a hook). Self-settlement costs 46,000 gas plus 6,000 per swap settled; a keeper's epoch costs 26,000 gas plus 14,300 per account settled, or 4,400 for an entry skipped because the account had already settled itself. Verifying a succinct (Groth16) proof costs 227,226 gas, and sponsoring the keeper's transaction through an ERC-4337 paymaster adds 87,000–98,000 gas per settlement transaction.

Table 5 prices these components block by block at the window's base fees, including the hook on every swap.

| Settlement design | Mainnet, six months (× execution) | Arbitrum (× execution) |
|---|---|---|
| Keeper settles every block, one report per block | $96.7 k (0.72) | $21.2 k (0.72) |
| Keeper settles hourly, prices signed once per batch | $24.9 k (0.18) | $5.7 k (0.19) |
| Keeper settles hourly with a succinct proof | $20.5 k (0.14) | $4.3 k (0.15) |
| Every account settles itself hourly | $38.7 k (0.28) | $6.8 k (0.23) |
| *Execution of the swaps themselves* | $148 k | $30 k |

*Table 5. Cost of settlement relative to the execution of the settled swaps.*

Settlement stays within its bound in every design, and by a factor of about five when prices are signed in batches and settled hourly. A succinct proof reduces the cost by a fifth at most. Once prices arrive in a single signed batch, the costs that remain — the hook on every swap and one storage write per settled account — are incurred whether or not settlement is proven, so the viability of the mechanism does not depend on proofs.

### 5.9 Settlement economics and keeper incentives

**Self-settlement.** We let each account in the sample choose between waiting for the keeper and settling itself every hour, every minute or every block, minimising the sum of its own settlement gas and the cost of the stake it must hold at its peak. With the cost of holding stake between 5% and 50% a year, 2–8% of accounts chose to settle themselves. These accounts carried 7–51% of mainnet volume, and self-settlement reduced the stake they required by 15–24%. In total, $1.11 M of stake sufficed to back $19.6 B of six-month volume on mainnet.

**Funding the keepers.** An hourly keeper epoch cost between $0.12 and $0.68 at the median ($24–38 at the 99th percentile on mainnet). Paid from the protocol take, keepers would require 0.1–0.24% of the value recaptured at observed gas prices and 0.8–2.2% under a sustained tenfold rise in gas prices, well within a take of 2.5%. Under the design of §4.6, they are instead paid from a gas tank to which every swap contributes a fixed number of gas units at the prevailing base fee. Table 6 reports the smallest contribution that keeps a tank shared by seven mainnet pools solvent throughout the window, with the tank seeded with one day of payments.

| Gas withheld per swap (share of the swap's own gas) | Hourly epochs | Daily epochs | Daily, keeper chooses the block |
|---|---|---|---|
| Mainnet, shared tank, proven settlement | 11.7 k (6.2%) | 2.3 k (1.2%) | 1.4 k (0.7%) |
| Mainnet, shared tank, on-chain settlement | 18.9 k (10%) | 4.9 k (2.6%) | 3.1 k (1.6%) |
| Arbitrum, proven settlement | 4.8 k (3.5%) | 0.64 k (0.5%) | 0.64 k (0.5%) |

*Table 6. Smallest per-swap gas contribution that keeps the gas tank solvent.*

The shared tank removes the disadvantage of small pools without any exchange rate: the smallest pool in our census, with $13 M of six-month volume, would need 80,000 gas per swap on its own at hourly epochs, but pays the common rate in the shared tank. Daily epochs reduce the contribution about fivefold, because each account is written once a day rather than once an hour; accounts that need their stake released sooner settle themselves. The timing of settlement matters as much as its frequency: requiring settlement at the highest base fee of the following day would raise the required contribution about fivefold, whereas a deadline long enough for keepers to choose an inexpensive block lowers it by 35–60%.

**Choice of keeper.** We simulated five keepers with differing costs and availability over every hourly epoch of the window. When the charges are computed on-chain, an open race with an escalating bounty settled each epoch within 1.3 minutes and wasted no effort, and appointing a single leader only added cost. When settlement is proven, keepers of similar cost that race one another duplicate the proving; on Arbitrum the duplicated effort exceeded the gas spent on settlement itself. A designated leader removed this waste at a higher payment per epoch, with missed epochs falling back to the open race after a deadline. Because a leader cannot alter any charge, collusion between a leader and an account can only delay the credit to liquidity providers, which was worth less than one cent per epoch.

### 5.10 Limitations

The evidence has several limitations. The external price is a Binance touch-level proxy rather than the signed liquidity-weighted quote the protocol would use, so the effect of oracle error in §5.7 is modelled rather than measured. The simulation of §5.5 approximates the pool's depth as linear within each day, replays user flow at its observed size and direction — whereas a pool quoting closer to the market would likely attract additional flow — assumes a population of arbitrage costs, and models the competition for transaction order as a second-price auction; the sender-diversity signal presumes a first-come-first-served race. The labels used in §5.3 are conservative heuristics. The gas measurements of §5.8 were taken on a locally deployed Uniswap v4 pool manager with mock tokens, and swaps that cross a liquidity boundary are not covered by the closed-form charge. The keeper simulations assume keeper costs and availability, and the seven-pool census applies the study pool's recapture rate to the other pairs. Finally, the sufficiency of REP as collateral when it trades below its mint rate has not yet been evaluated against a plain bond.
