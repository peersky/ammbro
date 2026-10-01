# REP-AMM: Oracle-Reconciled, L1-Viable LVR Capture with a Tokenized Reputation Layer

## Abstract

REP-AMM is a dynamic-fee redistribution design with an oracle-reconciled, ex-post scoring layer and a reputation market as the price-discrimination substrate. In this work we present a Uniswap v4 hook that prices every swap at execution and reconciles it after the block against trusted, signed oracle data. Arbitrage is treated as a paid job: the trader keeps a small, market-discovered allowance per unit of price correction plus its gas, and extraction beyond that allowance is recaptured for liquidity providers from collateral posted before trading — so that paying block builders for position becomes useless — while those who consistently trade below real-time oracle prices lose reputation and, with it, their future fee discounts. We introduce these fees as counterparty-free tokenization: a new token is derived from each swap pair to create a Reputation (or Reparation, lol) asset, staking which grants fee discounts, and which itself represents the capitalized value of the adverse-selection spread that the holder's future benign volume avoids paying — a per-pair, slashable trading license whose price is sustained by the pool's expected extraction pressure. We further conduct data analysis and backtest to demonstrate existing solution incompletness and how REP-AMM solves it.     

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

We therefore *measure* when swaps are priced instead of assuming it. An arbitrage that closes a gap stops where the pool price net of the fee meets the external price it can hedge at; minimising that residual over offsets from the block timestamp gives the instant at which gap-closing flow priced its trades. On ETH/USDC (March–August 2026) this decision latency is `L` ≈ 1–1.5 s after the block timestamp (§5; bracketed against quote staleness), consistent with blocks published one to two seconds into the slot.

The protocol scores every swap in a block against the same instant, `t* = block_ts + L`. A per-block anchor is **position-invariant**: no position in the block maps to a different benchmark, so position cannot be bought for a more lenient score — a direct requirement of the design aim that paying for position must be useless (§3.2).

The finer alternative — normalising transaction index into intra-block time increments of `T/N_mean_txs` (≈ 40 ms at ~300 transactions per block) — is attractive as a fairness standard but unsafe on today's chains. Index is sold to the highest bidder, and whoever controls position can then choose its benchmark time. Ordering the plane by arrival hands the top slot, which the best-informed traders buy, the oldest price and forgives ~72% of top-of-block extraction; reversing the orientation only moves the purchase to the cheap bottom of the block; clocks that count only swaps on the pool itself are bought with one's own dust swaps (in our data, $0.03 of gas buys $11 of forgiveness per arbitrage) (§5). We therefore retain the virtual time plane as a proposal for the base layer: it is safe only where ordering is enforced by time — first-come-first-served sequencing or an encrypted mempool — so that position cannot be bought.

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

In the **reconciliation phase** (block *N+1* or a later batch), a keeper submits the signed oracle report for the block's decision instant `t*` (§3.4). The hook verifies signatures, computes each swap's quality factor `q_LP` against the directional benchmark (§4.2), and settles **against stake only**: benign aggregates mint REP (§4.4); extraction beyond the job allowance (§4.3) is debited from the trader's stake, in the order of §4.5. No new funds are requested at reconciliation — it settles only against collateral locked at execution; the keeper's bounty is funded from a slice of collected fee revenue and escalates with stall duration, so prolonged stalls are self-healing.

This division follows from §3.1 by one further step: since a swap's true quality is knowable only retroactively, and cash cannot be recalled from a counterparty who has departed, the protocol prices execution-time fees off the only thing it can still reach afterward — the trader's locked stake. Staked reputation is thereby simultaneously the fee determinant and the collateral. Reconciliation timing becomes a pure keeper-economics choice (next-block vs. batched), costing users nothing in locked capital; the scoring instant is pinned regardless, since a late reconciliation still scores each swap against the signed price at its block's decision instant.

## 4.2 The scoring rule: pair-native, directional, instantaneous

All economic quantities settle in the pool's own pair; the single external input to the system is the signed oracle pair price. For a swap with pool-perspective deltas (Δ₀, Δ₁) in a block with decision instant *t* (§3.4):

```
markout = Δ₀ + P_dir(t)·Δ₁          (token0 terms)
q_LP    = markout / notional         (dimensionless)
```

where `P_dir(t)` is the **directional** benchmark of §3.6: the liquidity-weighted bid when the pool sells the asset, the liquidity-weighted ask when the pool buys, evaluated at the block's decision instant `t*` (h = 0). Where the pair price must be composed from two single-asset feeds, each side is composed as the round trip it represents: the pair ask is buy-leg-ask over sell-leg-bid, and the pair bid is sell-leg-bid over buy-leg-ask.

Three properties carry the section's weight. *Numeraire symmetry:* re-denominating in token1 rescales markout and notional identically; `q_LP` is unchanged, so the numeraire is bookkeeping, not economics. *Direction-freedom:* the delta formulation needs no per-side sign conventions; benign overpayment is `q_LP > 0` for buys and sells alike. *Instantaneity:* scoring at h = 0 measures the extraction where it occurs — against the executable reference price at the moment of the trade — rather than against later prices that mix extraction with market drift. Forward-horizon markouts (+12s, +30s) are retained as robustness cross-checks, not alternative definitions: they bound reconstruction and feed-latency noise and close the surface against horizon-aware adversaries.

Because the decision instant is measured rather than observed per transaction (§3.4), `q_LP` is evaluated as an average of the signed price path over a narrow window centred on `t*` (≈ 1 s), rather than a point read. The window must be centred on the decision instant: a window trailing the block timestamp scores arbitrageurs against prices from before the move they trade on and erases most measured extraction — over a 12 s trailing window the measured LP loss turns into a profit (§5). The residual tolerance ε — the timing noise left inside the window, ≈ 1 bp at the 90th percentile — is calibrated in §5 and sits alongside the endogenous tolerance the LWBA spread already provides.

## 4.3 The fee system: coverage curve and extraction charge

The fee a trader pays has two components: the coverage curve, settled on the trader's **per-epoch aggregate** rather than per swap — a choice forced by a structural argument developed below (§4.6) — and the job charge on arbitrage, computed **per price-correcting swap** (§4.8).

**The coverage curve** prices ordinary flow. Staked reputation `r` grants discounted-volume capacity `C = r/ρ` per epoch, and the fee on covered volume follows

```
f(r, V) = f_min + (f_max − f_min) · exp(−r / (ρ·V))
```

The curve is decreasing and convex in `r` (diminishing returns per marginal unit of reputation — the anti-concentration property), increasing in `V` (larger flow requires proportionally more stake), asymptotic to `f_min` (liquidity providers always earn a floor, approached but never reached), and homogeneous of degree zero (doubling stake and volume together leaves the rate unchanged: the curve prices *coverage ratio*, not wealth, so a proportionally staked institution pays what a proportionally staked retail trader pays). Volume beyond capacity pays `f_max` on the excess. Reference band: `f_min` = 1 bp, `f_max` = 5%.

**Arbitrage as a paid job.** Rebalancing is a service the pool needs (§3.2); extraction beyond its competitive cost is what the pool should not pay. At reconciliation each swap keeps

```
kept = ∫ min(edge(u), m) du  +  min(G·basefee,  E − ∫ min(edge(u), m) du)
```

where `edge(u)` is the marginal gap between the oracle and the pool price, beyond the pool fee, at each point `u` along the trade's price path; `E` is the swap's total extraction; `m` is the **job allowance** per unit of corrected volume; and `G·basefee` is a gas allowance at a fixed gas budget (`block.basefee` is readable at execution). For every swap that moves the pool toward the oracle, everything beyond `kept` is recaptured for liquidity providers by debiting the stake that backs the swap, in the order of §4.5. Swaps that move the pool away from the oracle cannot extract and are never charged. The charge is computed per correcting swap rather than on an account's aggregate, so that no account can net other traders' overpayments against its own extraction (§4.8).

Capping rent *per unit along the price path*, rather than on the trade's average edge, gives three properties. The arbitrageur stops where its marginal edge equals its own cost, so the pool is corrected to the competitive band and never past it; an average-edge cap pays the allowance on every unit while the average stays above it, and arbitrageurs then push the pool past the oracle to inflate volume (§5). The rule is split-invariant — the integral over a price path is additive, so dividing a trade gains nothing, without needing a convex schedule. And it is position-invariant: it pays any correcting swap, whether it opens the block or restores the pool after other users' trades.

When the collateral is REP, the charge is burned at the inverse of the mint scalar (§4.4): REP is minted and burned at the same internal rate per unit of pool value, so no market price of REP enters either formula. Whether that rate keeps the collateral sufficient when REP trades below it is evaluated in §5, against a plain bond.

**The allowance is discovered, not set.** The competitive cost of rebalancing is private and moves (exchange fee tiers, hedging, capital), so no fixed `m` is safe: set too low, rebalancing stops; set too high, the surplus is bid to block builders for position. `m` is set by a feedback loop on information the reconciler already holds:

```
every ~1 hour : if at least 5 blocks began with a gap beyond f + m + ε that the block's first
                swap did not correct, and they are more than 2% of such blocks      →  m ← 2m
every epoch   : if that share stayed below 1%                                        →  m ← 0.95·m
```

Any arbitrageur whose cost is below `m` profits from correcting a gap beyond `f + m`, so in a healthy pool such blocks almost never occur; once `m` falls below every arbitrageur's cost they occur every time. The loop therefore settles just above the cheapest active arbitrageur's cost — where exactly one can do the job and nothing is left to bid for position — and follows that cost when it moves. Raises are fast and decay is slow, so a shock in arbitrage costs costs hours of rebalancing rather than days. The arbitrageur's payout is set by competition between arbitrageurs, not by a protocol constant.

## 4.4 The reputation asset: minting as surplus sharing

Reputation (REP) enters the system in exactly one way: as a claim on realized surplus above the liquidity providers' target. Per epoch, with `θ*` the target take-rate:

```
N = Σ fees + Σ markouts        (pool net income, token0 terms)
S = N − θ*·ΣV                  (surplus over target)
```

When `S > 0`, REP is minted pro-rata to accounts whose fees-plus-benign-markout exceeded the target on their own volume — the traders who overpaid relative to what the pool needed. Minting is a fixed protocol scalar per unit of surplus share; no market price of REP enters any internal formula. This yields two properties at once. The mint is **self-funding**: total minted claims are a share of surplus actually collected in fees, so wash-trading mints nothing net — a wash trader's claim was prepaid out of their own overpayment, converting cash fees into future-discount rights and nothing more. And the target is **self-enforcing**: over-earning mints capacity, which grows discounted volume and pulls income back toward the target; under-earning halts minting while burns (§4.5) shrink capacity and push income back up. The liquidity providers' "asymptotic profit target" of §1 is not imposed anywhere — it is the fixed point of the mint valve, with the mint scalar as the damping knob under a standard stability bound.

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
3. a **per-pool reserve**, only if the account is exhausted (an abandoned or drained account), funded by an explicit protocol take on pool income — equivalently, REP issued slightly below the surplus it claims (§4.4).

A charge is never collected from other traders' parked stake. Pooling collateral across traders would make honest users pay for an extractor's bill while leaving the extractor's own remaining stake untouched — the incentive pointing the wrong way. The reserve amortizes only the residual risk that remains once the extractor's whole stake is gone, and it costs one pool-level balance. The parking rule therefore sets how much of an account's stake stops earning discounts while in flight, not how much can be collected: collection is bounded by the account's whole stake plus the reserve. On ETH/USDC the charge is heavy-tailed — its 99.9th percentile is 21 bp of notional, its maximum 358 bp, and 27% of all charge comes from trades above 50 bp — so a parking rate alone would collect between 70% and 90%; with the whole account stake behind it, collection is complete for an account staking its worst epoch's charges (about $1M for the dominant arbitrageur in our window) (§5). An account with no stake cannot be charged after the fact and pays `f_max` at execution.

## 4.6 Feasibility of on-chain reconciliation

Reconciliation is viable by a capacity argument. Whatever set of swaps block *N−1* accommodated, scoring them requires per-swap work strictly smaller than executing them: a markout is one multiply-add against an already-verified report price, a tolerance comparison, and one reputation-state write, with the report's signature verification amortized across every swap scored in its validity window. If per-swap reconciliation gas is bounded by per-swap execution gas, the protocol's steady-state footprint is at most twice its own swap footprint — bounded by construction, scaling only with the pool's own usage, never beyond what the chain has already demonstrated it can process; lazy settlement (below) smooths it further.

Most reconciliation, moreover, needs no keeper at all. The curve is shared but every position on it is individual, so settlement is pull-based and federated: a trader claims their own past epochs at their next interaction, attaching the signed report for their timestamp; benign aggregates mint (auto-staked, entering the activation delay), and the claimer bears their own gas inside a transaction they wanted anyway. Negative settlement does not depend on the trader's cooperation: the protocol's post-block bots reconcile every pool, so an extractor cannot avoid its charge by not claiming, and charges reach the account's whole stake (§4.5), not only the parked part. One default rule remains as a liveness backstop, exploiting the flight mechanism of §4.5: **an in-flight tranche that remains unreconciled when the signed-data retention window (on the order of a month) expires is burned in full**, and the account's remaining stake stays frozen until its flights are settled. Mildly negative traders therefore prefer reconciliation to the default, and benign traders self-claim for their mints; the oracle's short retention window becomes the protocol's challenge window rather than a liveness liability.

Reconciliation runs per pool: the post-block bots that reconcile a pool compute every account's epoch aggregate and charges off-chain and post them with the signed reports, so the on-chain cost per account is a single stake update, and the per-pool reserve is a single balance touched only when an account is exhausted.

Keepers therefore reduce to a completeness role: accelerating settlement for dormant accounts so aggregate supply stays current, rewarded by a bounty escalating with reconciliation delay and funded from the fee slice or a bounded allocation of the surplus valve — never unbacked minting, preserving the self-funding invariant.

What reconciliation computes is bounded and local. The hook records each swap's pre- and post-trade price and active liquidity; for a trade within one liquidity range — most corrections move the price by less than one tick spacing — the job allowance has a closed form in those values, and tick-crossing trades are recomputed off-chain from pool state and posted optimistically, challengeable within the retention window. The gas allowance uses `block.basefee`. The allowance controller (§4.3) needs only quantities already reconciled — each block's resting price, its signed report and the direction of its first swap — and no transaction indices.

Batching keeps verification sub-linear. One signature check covers every swap scored against that report, and epoch-level settlement can be compressed further into a single succinct proof attesting that all claimed `q_LP` values follow from validly signed reports — the zk-coprocessor pattern, already deployed commercially for verifiable computation over historical data — leaving per-swap marginal cost at roughly one state update. Viability does not depend on this optimization; the amortized-signature path alone satisfies the gas bound.

## 4.7 Parameters

The complete parameter set: `θ*` (LP target take-rate), `f_min`/`f_max` (fee band), `ρ` (capacity scale and base parking rate), `k` (per-pool parking speed, §4.5), the reserve take, the mint scalar (stability-bounded; its inverse is the burn rate), `L` (decision latency, measured) and the scoring-window width, `ε` (residual tolerance, bound to the measured timing-noise floor), `G` (gas budget of the gas allowance), the job-allowance controller (raise and decay steps, the 2% / 1% thresholds, the minimum count of uncorrected blocks), the settlement window, the activation delay, and the exit delay. The job allowance `m` itself is not a parameter: the controller discovers it. Consistency conditions — that `f_min` clears reconciliation economics, that the fee spread simultaneously prices REP and sizes the parked stake, and that account stake plus the reserve cover the tail of extraction — are evaluated in §5.


## 4.8 Initial supply, intermediaries, and who the arbitrageur is

At launch no account holds REP, so every swap would pay `f_max` and ordinary flow would route elsewhere. The protocol therefore issues an **initial supply**, sold rather than granted: its proceeds seed the per-pool reserve (§4.5), so pre-minted REP is backed at issuance just as minted REP is backed by collected surplus (§4.4). Issuance is priced slightly below the discount it confers — the reserve take of §4.5 — compensating early liquidity risk while REP's price is discovered.

The supply needed is small relative to the flow it serves. Bringing a fee within δ of `f_min` requires `r ≥ ρ·V·ln((f_max − f_min)/δ)` (§4.3); with the reference band and δ = 1 bp this is ≈ 6.2·ρ·V. On ETH/USDC, non-arbitrage user flow averaged $26 M per day over our window, so a daily-epoch pool needs about $16 k of active REP per basis point of `ρ` to offer near-floor fees to all of it.

Users need not hold REP themselves. Intermediaries that already route user orders — solvers, fillers, RFQ desks; *cashiers* — can hold the stake, quote users discounted fills, and sell the REP their customers' overpayment mints; competition between them passes the discount on. Intermediaries also answer the question of whose stake backs a swap when the hook sees only a router: the stake that backs a swap is the submitting account's, named in the swap's hook data. The protocol is agnostic to this structure; it is one way the initial supply reaches users.

This raises the question of who the arbitrageur is. **By design the protocol never identifies arbitrageurs: arbitrage is a role carried by a swap, not an identity.** Any swap that moves the pool toward the oracle is doing the rebalancing job and is paid the job allowance on it (§4.3); every other swap is scored as ordinary flow. An intermediary that routes its customers' orders and also corrects the pool is an arbitrageur for its correcting swaps and a router for the rest. This is why the charge is computed per correcting swap rather than on an account's aggregate: under an aggregate rule an intermediary could net its customers' small overpayments against its own extraction and leave the latter uncharged — extraction laundered through other people's flow. Per-swap charging removes that incentive at negligible cost to ordinary users: a user whose swap happens to correct a stale pool still pays no more than the market price plus fees, and loses only the windfall beyond the allowance — on benign-labelled flow in our window, at most about $0.01 M.