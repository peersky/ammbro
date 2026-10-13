# BRO-AMM: A Bonded Reconciliation Oracle AMM as a Low-Risk DeFi Primitive

**Tims Pecerskis** · tim\@peeramid.xyz

## Abstract

Liquidity providers (LPs) in automated market makers lose value to arbitrageurs trading against stale on-chain prices, and no existing AMM bounds this loss by design, so passive liquidity is not yet a low-risk DeFi primitive. BRO-AMM (Bonded Reconciliation Oracle AMM) is a Uniswap v4 hook built on one principle: after a block, chain history and signed market prices establish what each swap did to LPs, and that record can settle it. A price-correcting swap keeps an allowance per unit of volume, discovered on-chain; extraction beyond it is recaptured for LPs from stake posted before trading, which also bounds what arbitrageurs can pay for block position. Traders who overpay mint a reputation token (REP) that lowers their fees. On six months of Ethereum ETH/USDC data, a pool charging 3 bp instead of 5 bp leaves LPs ahead of today in every simulated scenario, by \$5.8–6.5M, while retail pays about 3.3 bp all-in and arbitrageurs' payments to block builders fall by 83–86%; an appendix adapts the design to Arbitrum's sequencer. Settlement costs 0.18× the gas of the swaps it settles.

## 1. Introduction

LVR is a permanent, non-mean-reverting cost for liquidity providers (LPs). For a constant-product pool it accrues at $\sigma^2/8$ of the pool's value per unit of time, where $\sigma$ is the volatility of the external price over that unit [@milionis2022lvr], about 11% a year at a daily volatility of 5%; measured arbitrage losses exceed the fees LPs earn in many of the largest Uniswap pools [@fritsch2024arbitrage], and in our sample LPs of the mainnet ETH/USDC pool ended \$1.58 M down after fees (Appendix K.1). Arbitrage itself is necessary: it keeps the pool's price aligned with the market. The problem is its price. Arbitrageurs capture the full gap between pool and market, and on Ethereum they pass much of it to block builders in competition for position, a cost ultimately borne by LPs and by the wider blockchain community, since it keeps the AMM from being adopted at scale as a reliable, low-risk building block in which passive retail and institutional capital can be parked; fixed fee tiers, moreover, fragment liquidity without resolving the trade-off.

This matters beyond the returns of LPs. @buterin2025lowrisk argues that low-risk DeFi — payments and savings, well-understood tools such as synthetic assets and fully collateralised lending, "and the ability to exchange between these assets" — can be for Ethereum what search was for Google. Exchange is the primitive the others rely on, and it is low-risk only if supplying liquidity is: an LP who expects to lose a predictable share of liquidity to arbitrage each year is not holding a savings-grade position. We therefore design an exchange whose risks to LPs are bounded and stated. Execution stays synchronous and permissionless; nothing is lent or leveraged; all value settles in the pool's own pair, with no third asset or numeraire; extraction is collected from stake posted in advance; and the reputation asset is fully backed in escrow and redeemable at par (Theorem 1), so that it never draws on the pool's principal. The mechanism does add a dependency: a signed oracle, whose error we bound by a tolerance rather than eliminate (Appendix K.6). Oracle risk and contract risk are the very risks that Buterin names as having held low-risk DeFi back, and we list them explicitly among our assumptions (§4.10).

We pursue two goals: to return as much of the arbitrage surplus as possible to LPs while charging uninformed flow as little as possible, and to replace the hard-coded fee by a variable the system sets itself. The contributions are:

1. a per-swap quality score $Q_{\mathrm{LP}}$, measured against signed bid/ask prices at an empirically measured decision instant, and a method that prices every swap after finality, in hourly epochs (§4.1–4.2);
2. a payout rule for arbitrage — a per-unit cap with an allowance discovered on-chain — under which what an arbitrageur can bid for position is bounded by the allowance (§4.4–4.5);
3. a per-pair reputation asset whose rebates are netted by a high-water mark and fully backed in escrow, which closes minting by LPs against their own pool, and a collateral design that makes the charge collectable after the fact, with REP prepaid at par and redeemable at par once settled, so that collateral grows with a market swing (§4.6–4.8);
4. a settlement layer that is pair-native and costs a fraction of the swaps it settles (§4.9);
5. an evaluation on Ethereum covering scoring validity, recapture, payout rules, REP bonds, oracle error and settlement cost, which finds that a pool charging 3 bp instead of today's 5 bp leaves its LPs better off than today in every cost scenario while retail pays less (§5), with an arrival-ordered rollup, Arbitrum, in Appendix I.

## 2. Related work

Approaches to LVR either remove the information asymmetry or redistribute its surplus (Appendix A). @milionis2022lvr define LVR and suggest backward-looking fee adjustment and the sale of arbitrage rights as directions; BRO-AMM is a concrete, farming-resistant instance of the first.

Auction designs — am-AMM [@adams2024amamm], McAMM [@josojo2022mcamm] and Angstrom [@sorellaAngstrom] — sell the right to arbitrage or manage the pool and return the proceeds to LPs; Angstrom additionally clears ordinary orders at a uniform price, but relies on app-specific sequencing, whereas BRO-AMM is a plain hook. 

Diamond [@mcmenamin2022diamonds] and V0LVER [@mcmenamin2023amm] reduce liquidity for arbitrageurs only, and argue against oracle dependence; we accept a trusted signed oracle and quantify the consequences of its error (Appendix K.6). 

The closest design is Hindsight [@oojaeHindsight], a v4 hook that escrows each swap's output for about ten seconds and sets its fee afterwards from the realised markout against a volatility-adjusted threshold, refunding benign flow. BRO-AMM differs in keeping execution synchronous — the trader receives its output at once, and charges are collected from stake posted in advance — and in scoring at the decision instant rather than against later prices, which mix extraction with drift (§4.2). 

MEV taxes [@robinson2024priority] charge a fee increasing in the priority fee and capture competitive MEV under honest priority ordering; they do not hold under builder auctions on Ethereum and cannot reach extraction in the middle of a block. 

Reputation systems, zScore [@udupi2025zscore] and Karma [@statusKarma], and optimal dynamic fees [@baggiani2025fees; @ghasemlu2026fees] set fees or access by behaviour or market state but specify neither an oracle-reconciled scoring rule nor resistance to concentration of the discount.

## 3. Methodology

### 3.1 Approach

This is a quantitative design-science study: we specify a mechanism (§4) and evaluate it on six months of data from a production pool, with four methods. (i) *Measurement:* every historical swap is scored after the fact with the quality score (§4.2), to test whether it separates extraction from benign flow and to locate extraction within blocks. (ii) *Counterfactual simulation:* the observed blocks, external price path and non-arbitrage flow are replayed against today's pool and against BRO-AMM, with arbitrage supplied by profit-maximising agents, since arbitrage responds to the payout rule and cannot simply be rescored. (iii) *Stress tests:* the simulation is repeated under raised costs, scaled volatility, arbitrageurs that leave or withhold corrections, finite or absent stake, and oracle error. (iv) *Analysis and benchmarks:* properties that must hold on every path are proved (Theorem 1, Proposition 1), and the contracts' gas is measured in Foundry.

*Design stance: standing is transferable.* We treated every form of standing in the protocol as transferable. Accounts are free to create, and their keys, or a contract wallet that holds them, can be sold, so a reputation bound to an account is transferable outside the protocol's view and only harder to price, while a bad record is simply abandoned; no purely technological means makes standing non-transferable. REP is therefore an ordinary transferable token, and the mechanism was required to keep its guarantees whatever REP trades at and whoever holds it. A protocol that holds under an open market for its own standing does not rest on an assumption it cannot enforce, and is the more reliable for it. The evaluation follows from this stance: REP's price is bounded by the mechanism (11) rather than assumed, minting against one's own pool and default on charges are analysed for any holder (Proposition 1, Appendix K.4), and account-bound alternatives are rejected (§6.3).

Together these answer whether the score identifies extraction, whether a pool can charge less than today's and leave LPs and retail better off without being less rebalanced, how much arbitrage stake that needs, how sensitive charges are to oracle error, and whether settlement is viable; §5 summarises the answers and Appendix K details them.

### 3.2 Data

We study the Uniswap v3 ETH/USDC 5 bp pool on Ethereum mainnet from 1 March to 31 August 2026 (Table 1), chosen because its arbitrage is competitive and its block position is sold by builder auction. Swaps and their transactions were extracted from archive nodes over JSON-RPC; senders are grouped by labels that use no prices (Appendix B). The benchmark is Binance ETHUSDT corrected by USDCUSDT, from the exchange's public archive, with a touch-level bid/ask proxy built from aggressor-flagged trades; it stands in for a signed feed such as Chainlink Data Streams [@chainlinkDataStreams], whose error is therefore modelled rather than measured (Appendix K.6). A USDC/USDT pool, where no extraction is expected, is the negative control: it scored a median absolute $Q_{\mathrm{LP}}$ of 0.9–1.1 bp (95th percentile 2.3 bp), inside the band within which the peg itself moves (99th percentile 12.8 bp). Appendix I repeats the evaluation on Arbitrum's WETH/USDC pool, where ordering by arrival changes the competition signal (§4.5).

*Decision latency.* The latency $L$ of (2) was measured, not assumed. A correcting swap trades until the pool's price net of the fee meets the price at which it can hedge, at the instant it decides; the offset from the block timestamp that minimises this residual over correcting swaps is $L$. It is 1.5 s on mainnet, where arbitrageurs re-price bundles until the proposer takes the winning bid, and 0.75 s on Arbitrum (Figure 5 in Appendix B; Appendix G.1). A clock derived from a transaction's index within the block was rejected because whoever orders the block would set it, and could sell it (Appendix B).

| | Ethereum mainnet |
|---|---|
| Swaps | 990,555 |
| Blocks (with a pool swap) | 1.32 M (595 k) |
| Volume | \$19.6 B |

*Table 1. Sample, March–August 2026.*

### 3.3 Simulation and outcomes

The block-level simulator (Appendix C) replays every block in order: arbitrageurs with hedging costs from 0.3 to 2.5 bp choose the trade that maximises profit under the payout rule tested, the winner paying the runner-up's profit for position, and the block's real non-arbitrage swaps follow at their observed size and direction. Three *cost scenarios* hold costs fixed or multiply them by four or by eight from 1 June; stake is also tested under *volatility shocks* that scale the price path's deviation by two or four. A *worst-case* figure is the least favourable of the three cost scenarios.

The primary outcome is *LPs' gain*: the change from today's pool, on the same path, in *LPs' net* — fee income less losses to arbitrage over the six months — in the worst case. It counts only for designs that *keep the pool rebalanced*: relative to today, the share of blocks ending within the fee plus 1 bp of the benchmark falls by at most 0.5 percentage points, and the volume-weighted staleness of the price users trade against rises by at most 0.1 bp; otherwise a pool could raise LPs' income by stopping arbitrage at users' expense. Secondary outcomes are retail's all-in price, *payments to builders* (what arbitrageurs pay block builders, directly or through priority fees, to be ordered first — part of what LPs lose to arbitrage), arbitrageurs' margin, LPs' daily risk, and charges left uncovered by stake. Comparisons are paired replays of one realised path, so we report scenarios and worst cases rather than significance tests. Parameters were chosen by the same rule (Appendix J).

### 3.4 Reproducibility and ethics

Raw data are not redistributed; the repository pins checksums of every archive file, commits the results behind each table and figure, and gates every study on the negative control. The study uses only public blockchain records and a public exchange archive, involves no human participants or personal data beyond pseudonymous addresses, and reports senders only by label and in aggregate; no contract was deployed to a public network.

## 4. System design

BRO-AMM executes a swap at once and prices it after the block. Every rule of the mechanism is a term of one settlement equation; §4.1 states it, §4.2–4.8 expand its terms, and §4.9–4.10 cover settlement and the threat model. The values used in the evaluation are collected in Appendix J, and Appendix H follows two swaps through the mechanism with numbers.

### 4.1 The settlement equation

A swap's payment to the pool cannot be settled at once, because its three parts become known at different times (Figure 1). The fee depends only on the sender's stake, so it is paid at execution and needs no oracle. The charge depends on the external price at the swap's decision instant, which no chain finalises as fast as an order book observes it, so it is settled at reconciliation, once the signed prices for the swap's block are available and agreed; consensus protocols separate inclusion from finality in the same way [@garay2015backbone; @buterin2020gasper; @kalodner2018arbitrum]. The rebate depends on the whole epoch's income against the LPs' target, so it is settled when the epoch closes. Reconciliation runs in epochs of fixed length, after which parked stake is released.

![Timeline](figures/fig_timeline.png)

*Figure 1. When each part of the settlement equation (1) becomes known: the fee at execution, the charge at reconciliation against the signed price at the decision instant, and the rebate when the epoch closes.*

Let account $a$ send swaps $j \in \mathcal J_{a,i}$ in settlement epoch $i$, swap $j$ having notional $v_j$ in token 0, and let $V_{a,i} = \sum_{j \in \mathcal J_{a,i}} v_j$. What the account pays the pool for these swaps, beyond trading on the pool's curve, is

```math
\Pi_{a,i} \;=\; \sum_{j \in \mathcal J_{a,i}} \Big[\, \underbrace{f\big(r_a, V_{a,i}\big)\, v_j}_{\text{fee (3), at execution}} \;+\; \underbrace{C_j\big(\hat P_j,\, m,\, \lambda,\, \varepsilon\big)}_{\text{charge (4b), at reconciliation}} \Big] \;-\; \underbrace{P_{\mathrm{int}}\, M_{a,i}\big(\theta^*, W, \tau\big)}_{\text{rebate (7), at epoch end}} \tag{1}
```

where $f$ is the fee, set by the coverage curve (3) between a floor $f_{\min}$ and a ceiling $f_{\max}$ with a steepness $s$; $r_a$ is the account's staked reputation token (REP), valued at REP's internal mint and burn rate $P_{\mathrm{int}}$; $C_j$ is the charge for what swap $j$ extracts beyond an allowance $m$ per unit of volume, which the pool discovers on-chain (6); $\hat P_j$ is the signed external benchmark at the swap's decision instant (2); $\lambda$ is a penalty for correcting the pool after retail has traded at the stale price; $\varepsilon$ is a tolerance for oracle error; and $M_{a,i}$ is the REP minted to the account for paying more than the LPs' target take-rate $\theta^*$, netted over a window of $W$ epochs, after a protocol take $\tau$. The charge is collected from stake posted before the trade (9). Summed over all accounts, the LPs receive the pool's gain on every swap at the benchmark plus the charges, less the surplus placed in escrow behind minted REP (8).

### 4.2 The benchmark

Every swap in block $b$ is priced against the external price at one instant,

```math
t^*_b = T_b + L, \qquad Q_{\mathrm{LP},j} = \frac{\Delta_{0,j} + P_{\mathrm{dir}}(t^*_b)\,\Delta_{1,j}}{v_j} \tag{2}
```

where $T_b$ is the block's timestamp, $L$ is the pool's decision latency, measured from correcting swaps (§3.2), $\Delta_{0,j}$ and $\Delta_{1,j}$ are the amounts of tokens 0 and 1 the pool receives from swap $j$ (negative when it pays out), fees included, and $\hat P_j = P_{\mathrm{dir}}(t^*_b)$ is the price of token 1 in token 0 at the touch: the liquidity-weighted bid when the pool sells the risky asset, the ask when it buys it [@chainlinkDataStreams]. $Q_{\mathrm{LP},j}\, v_j$ is the swap's gain to LPs, negative for losses. One instant per block makes the score independent of position in the block. Where $N$ blocks share a timestamp $S$, the block of rank $j' = 0, \dots, N-1$ is placed at $S + (j' + \tfrac12)/N$ of the timestamp's resolution, and the error is absorbed by a scoring window of width $\Delta_{\mathrm w}$ around $t^*_b$.

### 4.3 The fee term

Stake buys coverage of volume within the epoch:

```math
f(r, V) = f_{\min} + (f_{\max} - f_{\min})\, e^{-s\, r/(\rho V)}, \qquad r^*(f) = \frac{\rho V}{s} \ln\frac{f_{\max} - f_{\min}}{f - f_{\min}} \tag{3}
```

where $\rho > 0$ is the capacity scale, which measures stake in units of volume and also sets the base parking rate (9); $s > 0$ is the curve's steepness, so that stake worth $\rho V / s$ cuts the premium above $f_{\min}$ by a factor $e$; and $r^*(f)$ is the stake needed to trade volume $V$ at fee $f$. The curve (Figure 2) is convex and decreasing in $r$, approaches $f_{\min}$, and depends only on the coverage ratio $r/(\rho V)$. Coverage renews when parked stake is released at each epoch's end.

A fresh account has $r = 0$ and pays $f_{\max}$; nothing it owes after the block can be collected. Against a gap $g$ in a pool of depth $D$ per unit of log price, with its own cost rate $h$, it takes

```math
x^{\mathrm{fresh}}(g) = \tfrac{1}{2} D\, \big(\max(g - f_{\max} - h,\ 0)\big)^2 ,
```

so $f_{\max}$ is sized to the largest shock the pool must withstand, and by (3) the stake needed to escape it grows only with $\ln f_{\max}$.

![Coverage curve](figures/fig_coverage_curve.png)

*Figure 2. The coverage curve (3): (a) for three fee bands at a fixed steepness; (b) for one band across steepnesses.*

### 4.4 The charge term

A correcting swap is paid an allowance $m$ per unit of volume and charged what it gains beyond it. For swap $j$ with fee $f_j$, let $p(u)$ be the pool's marginal price after its first $u \in [0, v_j]$ units, and $\eta_j = \operatorname{sgn} \ln(\hat P_j / p(0))$ the direction of mispricing; the swap is correcting if it moves $p$ in direction $\eta_j$. Its marginal edge is

```math
\mathrm{edge}_j(u) = \max\!\big(\eta_j \ln(\hat P_j / p(u)) - f_j - \varepsilon,\; 0\big) \tag{4a}
```

and its charge, and what it keeps, are

```math
C_j = \int_0^{v_j} \Big[\mathrm{edge}_j(u) - (1 - \lambda a_j)\,\min\big(\mathrm{edge}_j(u), m\big)\Big]\, du, \qquad K_j = \int_0^{v_j} \mathrm{edge}_j(u)\, du - C_j \tag{4b}
```

where $a_j \in [0, 1]$ is the share of the block's *protected* retail volume executed before swap $j$; protected swaps do not correct the pool and pay a priority fee at most the epoch's $q_{\mathrm p}$-quantile, so that protection cannot be bought by bidding. Each unit keeps at most $m$ of its own edge, so the corrector stops at the band of width $f_j + \varepsilon$ around the benchmark, and splitting a trade changes nothing (Figure 3). Since every swap in the block is scored at the same $t^*_b$, an arbitrageur with cost rate $h$ that pays $\beta_j$ for position earns $K_j - h v_j - \beta_j \ge 0$ only if

```math
\beta_j \;\le\; (m - h)\, v_j ,
```

so what it can bid for position is bounded by the allowance, which (6) drives toward $h$. The allowance includes the corrector's gas (Appendix F.2).

![Payout rule](figures/fig_payout_rule.png)

*Figure 3. Kept and recaptured value under (4b): the edge falls as the swap moves the pool, and each unit keeps at most $m$.*

### 4.5 The allowance

The allowance should equal the competitive cost of correction, which is private and changes over time; BRO-AMM discovers it by feedback from reconciliation, as EIP-1559 sets the base fee from demand for block space [@roughgarden2020eip1559]. A block $b$ is *correctable* if $\lvert\ln(\hat P_b/p_b)\rvert > f + m + \varepsilon$, where $p_b$ is the pool's price at the start of the block and $\hat P_b$ the block's benchmark. Let $\pi_b \in [0,1]$ be the share of its transactions ordered before the first swap that leaves the pool within $f + m + \varepsilon$ of $\hat P_b$, and $\pi^{\mathrm r}_b$ the same share for its earliest protected retail swap, or, if there is none, for a swap paying the epoch's $q_{\mathrm r}$-quantile retail priority fee. The block's index and class are

```math
z_b = \ln\big(\pi^{\mathrm r}_b / \pi_b\big), \qquad z_b = -\infty \text{ if no swap closes the gap;} \qquad
b \text{ is } \begin{cases} \text{stale} & z_b = -\infty \\ \text{late} & z_b < 0 \\ \text{timely} & 0 \le z_b \le \ln\kappa \\ \text{urgent} & z_b > \ln\kappa \end{cases} \tag{5}
```

where $\kappa > 1$ separates timely from urgent corrections. Stale blocks show that $m$ is below every active corrector's cost; urgent blocks show a margin that rivals bid for. Late blocks are charged by $\lambda$ in (4b) and do not move $m$. Let $n^{\mathrm c}$ and $n^{\mathrm s}$ count correctable and stale blocks over a raise window $H$ or a day $d$, and $u_d$ be the share of the day's corrected blocks that are urgent. The controller sets

```math
m \leftarrow \chi_{\uparrow}\, m \ \text{ after each window } H \text{ if } n^{\mathrm s}_H \ge n_{\min} \text{ and } n^{\mathrm s}_H > q_{\mathrm s}\, n^{\mathrm c}_H ; \qquad
m \leftarrow \begin{cases} \chi_{\mathrm u}\, m & \text{daily, if } u_d > \bar u \\ \chi_{\mathrm c}\, m & \text{daily, if } u_d \le \bar u \text{ and } n^{\mathrm s}_d < q_{\mathrm c}\, n^{\mathrm c}_d \end{cases} \tag{6}
```

with $\chi_{\uparrow} > 1 > \chi_{\mathrm c} > \chi_{\mathrm u}$, so that it raises fast and lowers slowly, minimum stale count $n_{\min}$, stale-share thresholds $q_{\mathrm s}$ and $q_{\mathrm c}$, urgent-share threshold $\bar u$, and $m$ kept within $[m_{\min}, m_{\max}]$ from a starting value $m_0$. Staleness is judged by a block's outcome, not its first swap, so an adversarial ordering cannot manufacture it (Appendix G.3). On a chain that orders transactions by arrival, the condition $u_d > \bar u$ becomes $K_d \ge K_{\min}$, where $K_d$ counts the senders with at least a share $q_{\mathrm k}$ of the day's corrections (Appendix I).

### 4.6 The rebate term

A rebate must not pay out what the LPs have not kept: rebating each epoch on its own would hand out the surplus of good epochs while the LPs absorb the shortfalls of bad ones, so income is netted cumulatively and only the part above its best recent level is rebated. The rebate is built up in four steps. An epoch's income to the LPs is the pool's gain on its swaps at the benchmark, fees included, plus the charges it recaptured:

```math
N_i = \sum_{j \in \text{epoch } i} \big(Q_{\mathrm{LP},j}\, v_j + C_j\big). \tag{7a}
```

Measured against the target $\theta^*$ on the epoch's volume $V_i$, income accumulates into a running excess $G_i$, whose best value over the last $W$ epochs is the high-water mark $H_{i-1}$:

```math
G_i = \sum_{k \le i} \big(N_k - \theta^* V_k\big), \qquad H_{i-1} = \max_{\max(0,\, i - W) \,\le\, k \,\le\, i-1} G_k, \qquad G_0 = 0. \tag{7b}
```

The epoch's surplus is the part of the running excess above that mark, so a shortfall must be recovered before new surplus mints, unless it is older than $W$ epochs:

```math
\Delta S_i = \max\big(G_i - H_{i-1},\ 0\big). \tag{7c}
```

Finally, each account's excess $O_{a,i}$ is what it paid above the target on its own volume, and it receives REP for it after the take $\tau$, scaled down pro rata when the surplus is smaller than all accounts' excess:

```math
O_{a,i} = \max\Big(\sum_{j \in \mathcal J_{a,i}} \big(Q_{\mathrm{LP},j}\, v_j + C_j\big) - \theta^* V_{a,i},\ 0\Big), \qquad
M_{a,i} = \frac{1 - \tau}{P_{\mathrm{int}}}\; O_{a,i}\, \min\!\Big(1,\ \frac{\Delta S_i}{\sum_{a'} O_{a',i}}\Big). \tag{7d}
```

Surplus beyond the accounts' excess, such as charges, stays with the LPs, and the take $\tau$ funds a per-pool reserve $\Omega_i$.

REP is issued in no other way than by swaps: as these rebates, and as prepayments, an overpayment an account declares in a swap to acquire REP at par (10). The backing of every unit is held in a per-pool escrow $E_i$, one balance per token. It is released to the LPs present when REP is burned for a charge, through the pool manager's `donate`, which credits in-range liquidity pro rata, or to the holder when REP is redeemed. With $M_i = \sum_a M_{a,i}$ the units rebated, $A_i$ the units prepaid, $B_i$ the units burned for charges, $\Xi_i$ the units redeemed, and $R_0$ an initial issuance at deployment backed by $P_{\mathrm{int}}$ per unit, the outstanding REP $R_i$ and the escrow evolve together:

```math
\begin{aligned}
R_i &= R_{i-1} + M_i + A_i - B_i - \Xi_i, \\
E_i &= E_{i-1} + P_{\mathrm{int}}\,\big(M_i + A_i - B_i - \Xi_i\big), \qquad E_0 = P_{\mathrm{int}}\, R_0,
\end{aligned} \tag{8}
```

so that $E_i = P_{\mathrm{int}}\, R_i$ in every epoch: outstanding REP is always fully backed, whatever its source (Theorem 1 in Appendix E). Escrow also makes minting against one's own pool unprofitable for an LP at any share of liquidity (Proposition 1).

### 4.7 Collateral and bonds

Only staked REP affects fees, which precludes flash-renting the discount. Swap $j$ parks part of its sender's stake until settled, and its charge is collected in a fixed order:

```math
\ell_j = \rho + k\,\Delta_{\mathrm{block}}, \qquad C_j \ \text{collected from} \ \underbrace{\ell_j v_j}_{\text{parked}} \;\to\; \underbrace{r_a - \textstyle\sum \ell v}_{\text{rest of stake}} \;\to\; \underbrace{\Omega_i}_{\text{reserve}} \tag{9}
```

where $\ell_j$ is the parked share of the swap's volume, $k \ge 0$ the parking speed and $\Delta_{\mathrm{block}}$ the pool's price move so far in the block, so corrections after a jump park more and splitting cannot reduce what is parked. Stake cannot be withdrawn while settlements are pending, and charges are never taken from other traders' stake. Parked stake returns at each epoch's end, so within an epoch an account's stake bounds both its discounted volume (3) and the charges it can absorb. A pool may also accept liquidity only in predefined ranges and lock it until its epoch is reconciled.

Staked REP is thus a performance bond: an honest corrector's stake is parked and returned every epoch, and only its charges burn it. An account tops up its bond by prepaying and takes back what it does not need by redeeming:

```math
\begin{aligned}
\text{prepay } X_a &:\quad R_a \leftarrow R_a + X_a / P_{\mathrm{int}}, \qquad E \leftarrow E + X_a, \\
\text{redeem } \xi \le R_a \text{ once no settlement of } a \text{ is pending} &:\quad R_a \leftarrow R_a - \xi, \qquad E \leftarrow E - P_{\mathrm{int}}\,\xi,
\end{aligned} \tag{10}
```

where $R_a$ is the REP the account holds, $X_a$ an overpayment in token 0 it declares in a swap, and $\xi$ the units it redeems. A prepayment mints at par: the account funds the whole backing, so neither the take $\tau$ nor the high-water mark applies, and (8) holds. Redemption waits until the account has no settlement pending, so REP cannot leave before the charges it bonds are settled. An arbitrageur prepays $r^*(f) - R_a$ of (3) for the fee it wants, so the bond outstanding grows with a market swing and contracts after it. REP is not a claim on the pool's surplus: a rebate goes to an account for its own excess (7d), not for REP held, and every unit is backed at par whatever its source (8), so prepaying while $G_i$ is below its high-water mark gains nothing from the shortfall's recovery and dilutes no holder.

Table 2 traces each kind of shock through (1).

| Shock | Effect on (1) | Absorbed by |
|:-----|:-------|:----------|
| Price jump | edge (4a) rises | charge (4b) above $m$; parking $\ell_j$ rises with $\Delta_{\mathrm{block}}$ (9) |
| Volume surge | coverage $r/(\rho V)$ falls, fee (3) rises toward $f_{\max}$ | bond topped up by prepayment at par (10); coverage renewed every epoch |
| Unstaked extraction | fee $f_{\max}$, charge uncollectable | $f_{\max}$ above the largest shock (3) |
| Corrector costs rise or correctors leave | stale blocks (5) | $m$ raised by $\chi_{\uparrow}$ (6) |
| Charges beyond stake | (9) exhausts stake | reserve $\Omega_i$, funded by $\tau$ |
| No arbitrage stake held in advance | every correction at $f_{\max}$ | bond prepaid at par (10) |
| Epochs below the LPs' target | $G_i$ falls | high-water mark: no minting until recovered (7c) |
| Demand for REP falls | holders want to exit | redemption at par from escrow (8), (10) |
| Oracle error | $\hat P_j$ off | tolerance $\varepsilon$ (4a); prices agreed after finality (§6.1) |

*Table 2. Shocks and the terms of (1) that absorb them.*

### 4.8 REP's price

Charges burn REP at $P_{\mathrm{int}}$, and prepayment and redemption convert REP to and from its backing at $P_{\mathrm{int}}$, so its market price $P_{\mathrm{mkt}}$ stays within their costs of par:

```math
P_{\mathrm{int}} - c_{\mathrm{r}} \;\le\; P_{\mathrm{mkt}} \;\le\; P_{\mathrm{int}} + c_{\mathrm{p}} \tag{11}
```

where $c_{\mathrm{p}}$ is the cost of a prepayment and $c_{\mathrm{r}}$ the cost of a redemption, including the wait until the holder's settlements are done. Above the band an account prepays rather than buying; below it a holder redeems rather than selling. The reserve covers charges beyond an account's stake (9) and the pool's maintenance.

### 4.9 Settlement and gas

The hook extends each swapper's record — post-trade price, active liquidity and token deltas, chained by hash — so that an account's unsettled swaps form a self-contained segment. An account may settle itself at any time, which releases its parked stake; at each epoch's end a keeper settles every account still in flight, and both paths advance the same pointer. Flights unsettled when the oracle's retention window expires are burned in full. Every swap prefunds $\gamma \times$ `block.basefee` into a gas tank, where $\gamma$ is a fixed number of gas units, in the native token and without any exchange rate; keepers are reimbursed from it with an escalating bounty, directly or through an ERC-4337 paymaster [@erc4337], and one tank can serve many pools. Settlement is never forced into the current block. Where charges are proven off-chain, a designated leader avoids duplicated proving; it cannot alter a charge, which the record and the signed prices fix. At deployment, a pool may make an initial issuance $R_0$ of REP, each unit backed by $P_{\mathrm{int}}$ in escrow; REP issued without backing would release nothing to the LPs when burned for a charge.

### 4.10 Assumptions and threat model

- **A1 (oracle).** Signed bid and ask prices exist for every block, are retained for longer than settlement takes, and are correct up to a bias and noise bounded by $\varepsilon$; a compromised oracle is outside the model. No swap reads the oracle at execution.
- **A2 (chain).** The hook executes atomically with the swap and the chain exposes its base fee; reorganisations beyond finality are not considered.
- **A3 (ordering).** No ordering is assumed to be honest. The only ordering property used is whether a chain runs builder auctions or a first-come-first-served sequencer (§4.5).
- **A4 (arbitrage).** Arbitrageurs are rational, with private, time-varying costs; at least one is active, and competition among them is not assumed.
- **A5 (liveness).** At least one keeper settles each epoch before its deadline.
- **A6 (operation).** Each pool has an operator that maintains its oracle relationship and signing, monitors its security, and may change $f_{\max}$, $\rho$, $\theta^*$, $\tau$, $\varepsilon$, $L$ and the controller's thresholds only within ranges fixed at deployment and after a delay long enough for LPs to exit; it cannot move funds, alter a recorded swap or charge, or mint REP outside (7) and (10).

The adversary may be any trader, LP, arbitrageur, builder, sequencer or keeper, or a coalition of them; it may create any number of accounts, split trades, buy position and trade REP, and an LP may trade against its own pool to mint REP and then withdraw. Accounts carry no identity and can be bought and sold with their keys, as can REP (§3.1), and a new account pays $f_{\max}$. The mechanism aims for five properties: a swap's score does not depend on its position in the block (G1, by (2)); splitting a trade reduces neither its charge nor its parked stake (G2, by (4b) and (9)); charges are collected from stake posted before the trade, otherwise from the reserve, never from another trader (G3, by (9)); outstanding REP is always backed in escrow (G4, by (8)); and no keeper can alter a charge (G5). Contract bugs and relational attacks such as sandwiches, which per-swap scoring cannot see, are outside the model.

## 5. Results

### 5.1 BRO-AMM against today's pool

| Six months, stable costs | Today, 5 bp | BRO-AMM, 3 bp |
|---|---|---|
| LPs' net | −\$3.15 M | \$3.37 M |
| LPs' gain over today, worst cost scenario | — | +\$5.76 M |
| Retail's price: fee + charges + REP holding | 5.00 bp | 3.31 bp |
| Staleness of the price users trade at | 12.75 bp | 11.54 bp |
| Arbitrageurs' payments to builders | \$6.57 M | \$1.09 M |
| Arbitrageurs' margin after costs | \$0.38 M | \$0.51 M |
| Recaptured from arbitrageurs | — | \$6.74 M |
| Charged to other correcting swaps | — | \$1.96 M |
| Blocks ending within the band | 99.54% | 99.96% |

*Table 3. Today's pool against BRO-AMM two fee units below it, Ethereum mainnet, urgency measured by block position, every correcting swap charged. Retail's price is the fee, plus the charges today's retail-aggregator flow would incur on its own accidental corrections (Appendix G.5), plus the router's cost of holding REP; both are upper bounds. LPs' net mints no REP; at $\theta^*$ = 2 bp, high-water minting would rebate \$0.30 M of it (Appendix E). The studies of Tables 7–12 leave users' corrections uncharged, which understates LPs' result by about \$1.9 M.*

![Value split](figures/fig_value_split.png)

*Figure 4. Division of the value taken by arbitrage at today's 5 bp fee, stable costs: recaptured for LPs, paid by arbitrageurs for position (to block builders on mainnet), kept by arbitrageurs as margin, or spent on their hedging and gas. Totals and LPs' net position at right.*

### 5.2 Summary of the studies

| Question | Answer | Key figure | Detail |
|:------------|:---------|:------------|:---|
| Does $Q_{\mathrm{LP}}$ identify extraction? | yes | AUC 0.889 (0.983, largest swaps) | K.1 |
| Can the fee fall below today's? | to 3 bp on mainnet, 4 bp on Arbitrum | LPs +\$5.76–6.52 M at 3 bp | §5.1, K.2, I |
| Is LPs' result riskier? | more variable, smaller losses | worst day −\$103 k (today −\$211 k) | K.2 |
| Does allowance discovery hold? | yes, under dropout and withholding | worst case +\$5.35–5.86 M | K.3 |
| How much REP do arbitrageurs need? | bonds prepaid at par, hourly epochs | peak \$1.12 M under shocks ×4 | K.4 |
| Can rebates alone supply REP? | no | exhausted within days | K.4 |
| Can prepayment carry a markup? | no | 1% fails the rebalancing test | K.4 |
| Is redemption at par safe? | yes, if locked while settlement is pending | no charge escapes beyond the bond | K.4 |
| Are charges collectable? | yes | parking collects 70–90% | K.5 |
| How costly is oracle error? | small, with a tolerance | about 8% of recapture per bp | K.6 |
| Is settlement affordable? | yes | 0.18× execution gas | K.7 |

*Table 4. Results of the studies, mainnet, March–August 2026. Detail refers to the subsections of Appendix K, to §5.1 and to Appendix I.*

## 6. Discussion

### 6.1 Principal findings

The results support the paper's central claim, that the value arbitrage takes from a pool is not fixed but depends on how arbitrage is paid. Most of what BRO-AMM returns to LPs comes not from users, who pay less, nor from arbitrageurs, whose margin is unchanged or slightly higher, but from what arbitrageurs paid block builders for position: once the allowance bounds what a correction can earn, position is worth little (§5.1). This is also why the design depends on the chain's ordering: on Ethereum the competition for position is visible in the block and can be used to discover the allowance, while on an arrival-ordered rollup it must be inferred from senders, and the headroom for a lower fee is narrower (Appendix I). The mechanism's binding requirements are operational rather than economic — REP bonds prepaid at par in a swing, about \$1.1 M under shocks four times the market's, signed prices with sub-second resolution where blocks are fast, and a tolerance matched to the oracle's error. Appendix G discusses the decision instant, fresh accounts, the controller, oracle attestation and intermediaries in more detail.

**Design choices.** The coverage curve's steepness trades two failures: a steeper curve lets each unit of stake back more volume, which attracts arbitrageurs to hold REP but lets their charges outrun the bond, and a milder one protects LPs with more stake per unit of volume but stalls correctors when volume rises; no steepness avoids both under shocks, while shorter epochs do (Appendix C), so the design keeps $s$ = 1 and settles hourly. Rebates are netted by a high-water mark because netting each daily epoch alone would rebate \$2.32 M over six months on mainnet at $\theta^*$ = 2 bp, against \$0.30 M with a 30-day mark, which leaves LPs within \$0.30 M of a pool that rebates nothing; a window longer than a few weeks changes little, and it stops an old shortfall from blocking rebates indefinitely (Appendix E). Prepayment is at par because the allowance controller drives correctors' margins toward zero, so any markup on prepayment taxes the largest corrections first (Appendix K.4). $f_{\max}$ is set by the shocks the pool must withstand rather than by benign flow, which reaches $f_{\min}$ through stake held directly or by an intermediary; because the curve is exponential, a router with benign flow minimises its cost at a stake of 0.6–0.9% of its volume per epoch, and its premium over $f_{\min}$, including a 10% cost of capital, stays below 0.12 bp for $f_{\max}$ between 500 and 2,000 bp (Appendix G.5). An intermediary cannot net its customers' overpayments against its own extraction, because the charge is computed per correcting swap; the protocol never identifies arbitrageurs, since arbitrage is a role carried by a swap.

**Oracle risk under finality.** Most oracle failures in DeFi happen at the instant of use: a lending market liquidates, or an oracle-priced exchange fills, against a price that was manipulated, stale or wrong for seconds, and the loss is final before anyone can check it. BRO-AMM never acts on the oracle at that instant. A swap executes on the pool's own curve, and the signed price enters only at reconciliation, after the block is final and the reports are retained, so a batch can be compared with other sources, co-signed by the parties it affects, or held through a challenge window before it settles (Appendix G.4). Moving a spot market for a block does not move a signed external benchmark, and a feed that is briefly wrong can be caught before it counts. A price that stays wrong through every check only misallocates charges and rebates within the stake posted: under-charging leaves LPs where today's AMMs leave them, and over-charging takes from stake, not from the pool.

### 6.2 Limitations

The benchmark is a Binance touch proxy, so oracle error is modelled rather than measured. The simulation assumes linear daily depth, fixed user flow, a population of arbitrage costs, one arbitrage action per block and, in Appendix K.4, arbitrage stake held at its level. Block position is modelled through priority fees and payments to builders rather than replayed, the urgency thresholds $\kappa$ and $\bar u$ are not calibrated on live data, and arbitrageurs' redeployment is a fixed delay. Collateral is checked against stake per epoch rather than parked per trade, and bonds are sized to hold fees within 0.1 bp of $f_{\min}$, with no limit on arbitrageurs' capital; prepayment, redemption and the initial issuance are evaluated on the simulated hourly series rather than within the simulation. Labels are heuristics. Gas was measured with mock tokens, and swaps crossing a liquidity boundary are outside the closed-form charge. Keeper costs are assumed, and the census applies the study pool's recapture rate to the other pairs. The REP market and intermediaries are analysed (§4.7–4.8, §6.1, Appendix G.5) but not simulated, and minting, rebates and escrow are evaluated on the simulated daily income rather than within the simulation; users are simulated as fully covered at the pool's fee, and retail's charges are measured on today's flow rather than simulated.

### 6.3 Future work

A single REP shared by all pools would let standing earned in one pool count in another. But an LP of its own pool can mint REP at the cost of the protocol take alone, and a shared token would let REP minted against one pool's surplus be charged against another's; we have not found a design that prevents this without giving up LPs' claim to their surplus or permissionless entry. A protocol-level score of useful work, earned from corrections settled in full and bound to the account, would not hold: accounts are free to create and their keys can be sold, so an account-bound score is transferable outside the protocol's view, and a bad record is simply abandoned. Letting such a score steepen its holder's curve also fails on incentives in simulation: the capital it saves an incumbent, about \$0.6 M for an hour, is worth far less than the charges it could leave unpaid in a single shock epoch, about \$1 M, and it accrued only to the cheapest arbitrageur. Standing in BRO-AMM is therefore staked REP alone: transferable, priced, and burned by charges (§3.1). Oracle error should be measured on a signed feed itself rather than on a proxy, and REP's price and the intermediaries that hold it can be observed only in a live market.

## 7. Conclusion

BRO-AMM is offered as a low-risk DeFi primitive for exchange. It shows that loss-versus-rebalancing can be recaptured by a plain Uniswap v4 hook [@uniswapV4core], without delaying execution, without consulting an oracle at trade time and without relying on honest ordering. Execution remains synchronous; pricing is completed after the block against signed prices, at a decision instant that is measured from the data and shared by every swap in the block, so that no position buys a more lenient benchmark. Arbitrage is retained as a paid job whose allowance is discovered on-chain, extraction beyond the allowance is collected from stake posted before trading, and benign traders earn the stake that lowers their fees.

On six months of Ethereum data, a fixed schedule applied with perfect information recaptured 73% of extraction while overcharging benign flow by less than 0.1 bp. With the allowance discovered on-chain, simulation shows the value that arbitrage takes moving from arbitrageurs' payments to builders to LPs, enough for a pool to undercut the one it replaces: at 3 bp against today's 5 bp, LPs end ahead of today in every cost scenario, by \$5.8–6.5 M over six months, retail pays about 3.3 bp all-in, users trade at fresher prices, arbitrageurs' payments to builders fall by 83–86%, and the pool stays as well rebalanced as today. On Arbitrum, where the sequencer orders by arrival, a count of competing senders replaces urgency and the pool undercuts today at 4 bp (Appendix I). REP prepaid at par and redeemable once settled removes the dependence on stake held in advance, at no risk to LPs and with at most \$1.12 M of bonds outstanding under shocks four times the market's, and settlement costs 0.18× the swaps' execution gas, paid from a tank that every swap prefunds. Its binding requirements are signed prices with sub-second resolution on fast chains and a tolerance matched to the feed's error. Its residual risks are the signed oracle, the contracts themselves and the market for REP; the last is held to par by prepayment and redemption but not yet observed. Oracle error measured on the signed feed itself, the behaviour of REP in a live market, and a reputation shared across pools remain open.

## Code and data availability

The hook contracts, the measurement and simulation pipeline, and the results behind every table and figure are available at <https://github.com/peersky/ammbro>. Raw chain and exchange data are not redistributed; the repository records their checksums and the pipeline that rebuilds them.

## Acknowledgements

We thank Chainstack for RPC infrastructure support, and the Chainlink team for consultations on the Data Streams report format and its capabilities.

## References

::: {#refs}
:::

---

## Appendix A. Related work in detail

**@milionis2022lvr.** Define LVR with a closed form and propose (a) fees set by comparing LVR with fee income over a backward-looking window and (b) the sale of arbitrage rights to capture LVR for LPs. Both are directions, not specified or farming-robust mechanisms; BRO-AMM's oracle reconciliation instantiates (a).

**am-AMM [@adams2024amamm].** A Harberger-lease auction for the role of pool manager, who sets the fee and may arbitrage at zero fee; surplus accrues to LPs. By its authors' account it offers fewer sandwich protections than a fixed-fee AMM and depends on a single manager; the convex coverage curve of §4.3 is in part an argument against winner-take-all structures.

**Diamond and V0LVER [@mcmenamin2022diamonds; @mcmenamin2023amm].** Reduce liquidity only for arbitrageurs and rebate a share of LVR; V0LVER extends protection to user-level MEV. The authors regard oracle dependence as unsatisfactory; BRO-AMM accepts a trusted signed oracle and bounds the effect of its error (Appendix K.6).

**Angstrom [@sorellaAngstrom].** A live v4 hook that auctions the top-of-block arbitrage right, distributes the proceeds to in-range LPs and clears other orders at a uniform price, which removes the positions a sandwich needs. It relies on app-specific sequencing by a decentralised operator set; BRO-AMM requires no sequencer.

**zScore [@udupi2025zscore] and Karma [@statusKarma].** zScore scores accounts' on-chain behaviour and points to v4 hooks as a vehicle for reputation-dependent fees; it does not specify an oracle-reconciled per-swap rule or an anti-farming curve. Karma is a soulbound token for access and rate limiting, not LVR-specific pricing; REP is deliberately transferable.

**Optimal dynamic fees [@baggiani2025fees; @ghasemlu2026fees].** Derive optimal fees as functions of the pool's state — inventory and external price moves, or volatility through a stochastic-control formulation; they set one fee for all flow and do not address a reputation-eligibility curve that must resist concentration.

**Hindsight [@oojaeHindsight].** A Uniswap v4 hook built for the UHI10 Hookathon and deployed on Unichain Sepolia. It escrows the swap's output delta as ERC-6909 claims for a maturity window of about ten seconds; permissionless keepers then settle, refunding a benign trade to about 5 bp and forfeiting the bond of an informed one to LPs, where informed means a realised markout above a threshold that grows with the volatility of a trailing window. A reputation multiplier discounts the bond for accounts with a benign history. It shares BRO-AMM's idea of settling the fee after the fact, but withholds the trader's proceeds and judges toxicity by subsequent prices rather than by the price at the decision instant.

**MEV taxes [@robinson2024priority].** A fee increasing in the priority fee captures competitive MEV under strict priority ordering — plausible on OP-Stack sequencers, not under Ethereum builder auctions — and cannot reach extraction in the middle of a block. BRO-AMM's ex-post reconciliation does not depend on honest ordering.

## Appendix B. Measurement details

**Benchmark composition.** Pair quotes composed from two single-asset feeds are taken as round trips: for ETH/USDC from ETH/USD and USDC/USD, the pair ask is $\mathrm{ETH}_{\mathrm{ask}} / \mathrm{USDC}_{\mathrm{bid}}$ and the pair bid is $\mathrm{ETH}_{\mathrm{bid}} / \mathrm{USDC}_{\mathrm{ask}}$. Liquidity-weighted quotes are conservative for large trades but lenient for small trades in volatile moments, when the touch is the true counterfactual; as pool liquidity approaches reference depth, the quotes can be extended with the pool's own liquidity into a size-aware price.

**Decision latency.** The bid/ask proxy is about 0.75 s stale at the median. Running the latency fit with the last quote before each instant biases it late, with the next quote after it biases it early; $L$ is the midpoint. Mainnet bracket: 1.25–1.75 s; Arbitrum: 0–1.5 s. Timing noise inside the centred 1 s window: 0.80 bp (mainnet) and 1.72 bp (Arbitrum) at the 90th percentile.

**Index-based clocks.** Normalising transaction index into intra-block time is unsafe where position is sold: ordering by arrival gives the best-informed top-of-block traders the oldest price and forgives about 72% of top-of-block extraction; reversing the orientation moves the purchase to the cheap bottom of the block; clocks counting only the pool's own swaps can be bought with dust swaps (\$0.03 of gas bought \$11 of forgiveness per arbitrage in our data). Such clocks are safe only where ordering is enforced by time.

**Labels.** Benign: transactions sent to a curated set of retail routers (on Arbitrum, the curated routers present there plus contracts used by at least 300 senders with at most 20 swaps each). Toxic: the first swap in a direction among a block's first four user transactions by a non-router sender with at least 100 swaps; position-free variant: any swap by a non-router sender with at least 100 swaps. Sandwich legs were labelled toxic in an earlier version; they number 50 swaps on mainnet and 2 on Arbitrum and do not affect the AUC, and a front-running leg pays above the market by construction (median $Q_{\mathrm{LP}}$ +9.3 bp on mainnet), so it would score as an overpayer. Arbitrum blocks open with a system transaction, so positions count user transactions. The "largest swaps" slice is the top 4.55% by notional on each chain (\$100 k on mainnet, \$7 k on Arbitrum).

![Decision latency](figures/fig_decision_latency.png)

*Figure 5. Median fee-adjusted residual between the pool's post-swap price and the hedgeable external quote, by offset from the block timestamp.*

![Score distributions](figures/fig_score_distributions.png)

*Figure 6. Distribution of $Q_{\mathrm{LP}}$ by label.*

![Extraction by position](figures/fig_extraction_by_position.png)

*Figure 7. (a) Share of extraction by transaction position in the block. (b) Distribution of the block-position index (5) of today's first correcting swap against the earliest non-correcting swap, among blocks containing both, with the late, timely and urgent ranges for $\kappa = 2$.*

![Block-position index](figures/fig_urgency_block_space.png)

*Figure 8. Positions in the block of the first correcting swap and of the earliest retail (non-correcting) swap, among blocks containing both, March–August 2026; position is the share of the block's transactions ordered before the swap. Bars below each panel span the quartiles, with a tick at the median: on mainnet the first correcting swap sits at a median position of 0.015 and the earliest retail swap at 0.13; on Arbitrum, where position follows arrival, at 0.30 and 0.21.*

![Oracle error](figures/fig_oracle_error.png)

*Figure 9. Mainnet: (a) unjustified share of charges and (b) recapture, as functions of the tolerance $\varepsilon$, for four oracle errors.*

## Appendix C. Simulation design

Every block is replayed in order — mainnet's 1.32 M, and all 63.4 M Arbitrum blocks at their reconstructed sub-second times, with the oracle read at each block's own time plus $L$. Pool depth is linear within a day, estimated from real swaps. In each block, arbitrageurs with hedging costs {0.3, 0.6, 1.0, 1.5, 2.5} bp choose the trade that maximises profit under the payout rule; the winner pays the runner-up's profit for position (second-price). The block's real non-arbitrage swaps are then replayed at observed size and direction. Costs are multiplied by four or eight from 1 June.

**Rebalancing constraint.** A rule is admissible only if, in every cost scenario, the share of blocks within the fee plus 1 bp of the oracle is at most 0.5 points below today's and the volume-weighted gap at which users trade is at most 0.1 bp above today's. This test is independent of block time; a count of uncorrected blocks is not, because a standing gap is counted once per block.

**Controller.** The rule of §4.5, with $\varepsilon$ = 0.5 bp; its variants under the position model, dropout and withholding are compared in Appendix F.7 and Appendix K.3.

**Sensitivity.** With a monopolist, two or ten arbitrageurs, all costs halved or doubled, and depth halved or doubled, every controller variant kept the pool rebalanced on both chains.

**At today's fee.** The final design at today's 5 bp fee, with users' corrections uncharged:

| Stable costs, six months | Mainnet today | Mainnet BRO-AMM | Arbitrum today | Arbitrum BRO-AMM |
|---|---|---|---|---|
| LPs' net | −\$3.15 M | \$2.70 M | \$1.38 M | \$2.05 M |
| Fees from users | \$4.24 M | \$4.27 M | \$2.61 M | \$2.61 M |
| Lost to arbitrage | \$7.39 M | \$1.57 M | \$1.23 M | \$0.56 M |
| Recaptured from arbitrage | — | \$5.87 M | — | \$0.67 M |
| Arbitrageurs' payments for position | \$6.57 M | \$0.77 M | \$0.94 M | \$0.27 M |
| Arbitrageurs' margin after costs | \$0.38 M | \$0.38 M | \$0.13 M | \$0.13 M |
| Users' price staleness, volume-weighted | 12.75 bp | 12.54 bp | 4.28 bp | 4.28 bp |
| Blocks ending within the band | 99.54% | 99.40% | 100.00% | 100.00% |

*Table 5. Today's pools against BRO-AMM at today's 5 bp fee, users' corrections not charged. LPs' net is fees from users less what is lost to arbitrage after recapture. Arbitrageurs' payments for position go to block builders on mainnet and to winning the race to be ordered first on Arbitrum.*

**Coverage curve and settlement epoch.** The steepness $s$ of the curve (3) scales the coverage a unit of stake buys, with $s$ = 1 the design value (Figure 2b). Arbitrageurs hold a pooled stake of 25 units, enough for normal markets with daily epochs, or 10 units, and the market's shocks are scaled by two and four; charges are taken from stake within each epoch, and those beyond it are uncovered (dollar amounts below):

| Steepness $s$ | Calm, 25 units | Shocks ×2, 25 units | Shocks ×4, 25 units | Shocks ×2, 10 units |
|---|---|---|---|---|
| 0.25 | fail, 224 h | fail, 1006 h | fail, 2119 h | fail, 2048 h |
| 0.5 | fail, 53 h | fail, 413 h | fail, 1303 h | fail, 1245 h |
| 1 | pass, 5.0 h | fail, 123 h | fail, 605 h, \$0.88 M | fail, 568 h, \$0.25 M |
| 2 | pass, 1.4 h | fail, 19 h | fail, 199 h, \$2.43 M | fail, 191 h, \$0.23 M |
| 4 | pass, 1.4 h | pass, 3.5 h, \$0.12 M | fail, 37 h, \$10.58 M | fail, 38 h, \$0.86 M |
| 8 | pass, 1.4 h | pass, 3.3 h, \$0.12 M | pass, 4.5 h, \$30.15 M | pass, 4.9 h, \$2.08 M |

*Table 6. Rebalancing test, hours of correctable blocks left uncorrected and uncovered charges, with daily epochs.*

A milder curve stalls arbitrageurs even in calm markets. A steeper one keeps them trading through shocks, but only by letting each unit of stake back more volume, so their charges outrun it: at $s$ = 8 and shocks ×4 the pool is rebalanced with \$30 M of charges uncovered. With each arbitrageur holding only a thin stake of its own, every steepness fails the rebalancing test and uncovered charges grow with $s$, to \$5.14 M–\$11.36 M under shocks ×4. No curve resolves the trade-off, because in a shock the charges arising within one epoch exceed a stake sized for calm markets. A shorter epoch does, since stake and coverage renew at each settlement:

| Epoch, stake | Calm | Shocks ×2 | Shocks ×4 |
|---|---|---|---|
| Daily, 25 units | pass, 5.0 h | fail, 123 h | fail, 605 h, \$0.88 M |
| 4-hour, 25 units | pass, 1.4 h | pass, 3.4 h | fail, 12 h, \$1.05 M |
| 4-hour, 10 units | pass, 1.5 h | fail, 15 h, \$0.21 M | fail, 156 h, \$2.55 M |
| 1-hour, 25 units | pass, 1.4 h | pass, 3.3 h | pass, 2.8 h, \$0.36 M |
| 1-hour, 10 units | pass, 1.4 h | pass, 3.3 h, \$0.22 M | pass, 2.4 h, \$1.99 M |

*Table 7. Same test with the design curve ($s$ = 1), varying the settlement epoch.*

**Retention of user flow.** Every non-arbitrage swap is scaled by the share of user flow the pool keeps, its volume, fees and price impact alike, under the final design; LPs' gain is measured against today's pool at full flow.

| User flow kept | Mainnet | Arbitrum |
|---|---|---|
| 0% | +\$1.24 M | −\$2.29 M |
| 25% | +\$1.89 M | −\$1.91 M |
| 50% | +\$2.73 M | −\$1.27 M |
| 75% | +\$3.97 M | −\$0.43 M |
| 100% | +\$5.38 M | +\$0.65 M |

*Table 8. LPs' worst-case gain over today's pool at full flow, across the three cost scenarios, when BRO-AMM keeps a share of user flow. On Arbitrum, removing user flow raises arbitrage volume from \$5.0 B to \$7.9 B, because users' own trades do part of the rebalancing.*

**Fee headroom.** The pool fee $f_{\min}$ is lowered for users, who reach the pool fully covered, and for staked arbitrageurs, under the final design; the within-band test keeps today's 6 bp band. Users' all-in cost is what LPs earn from users per unit of user volume: the fee plus the markout of trading at a stale price, which on Arbitrum favours users today. Ranges span the three cost scenarios; gains over today are worst cases. Today's pool costs users 8.7–8.8 bp on mainnet and 2.9–3.3 bp on Arbitrum.

| Fee | Mainnet: LPs' gain over today | Mainnet: LPs' net | Mainnet: users' all-in | Arbitrum: LPs' gain over today | Arbitrum: users' all-in |
|---|---|---|---|---|---|
| 5 bp | \$5.38 M | \$1.70 M to \$2.70 M | 8.7–8.9 bp | \$0.65 M | 2.9–3.3 bp |
| 3 bp | \$3.88 M | \$0.19 M to \$1.41 M | 7.2–7.4 bp | −\$0.50 M | 2.3–2.8 bp |
| 2 bp | \$2.99 M | −\$0.70 M to \$0.53 M | 6.4–6.6 bp | −\$1.22 M | 2.0–2.5 bp |
| 1 bp | \$1.81 M | −\$1.88 M to −\$0.57 M | 5.8–6.0 bp | −\$2.26 M | 1.7–2.2 bp |
| 0.5 bp | \$1.11 M | −\$2.57 M to −\$1.14 M | 5.5–5.8 bp | −\$2.98 M | 1.5–1.9 bp |

*Table 9. LPs' result and users' all-in cost at lower pool fees.*

**Capture and risk.** If the lower fee wins routing, the pool draws flow from other venues and LPs follow with liquidity: user flow and depth are both scaled (stable costs, mainnet). LPs' net per unit of liquidity divides by the scale.

| Fee | Flow and depth | LPs' net | Per unit of liquidity | Users' all-in | Worst week |
|---|---|---|---|---|---|
| 3 bp | ×1 | \$1.41 M | \$1.41 M | 7.4 bp | −\$324 k |
| 3 bp | ×1.5 | \$2.54 M | \$1.69 M | 7.5 bp | −\$486 k |
| 3 bp | ×2 | \$3.43 M | \$1.72 M | 7.4 bp | −\$668 k |
| 3 bp | ×3 | \$5.84 M | \$1.95 M | 7.5 bp | −\$1003 k |
| 1 bp | ×1 | −\$0.57 M | −\$0.57 M | 6.0 bp | −\$587 k |
| 1 bp | ×1.5 | −\$0.37 M | −\$0.24 M | 5.9 bp | −\$876 k |
| 1 bp | ×2 | \$0.00 M | \$0.00 M | 6.0 bp | −\$1202 k |
| 1 bp | ×3 | \$0.41 M | \$0.14 M | 5.6 bp | −\$1759 k |

*Table 10. Mainnet LPs' result when the pool takes a multiple of today's flow and liquidity.*

| Design | Daily mean | Daily s.d. | 1st percentile | Worst day | Worst week | Losing days |
|---|---|---|---|---|---|---|
| Today, 5 bp | −\$17 k | \$32 k | −\$146 k | −\$211 k | −\$722 k | 80% |
| BRO-AMM, 5 bp | \$15 k | \$66 k | −\$41 k | −\$71 k | −\$162 k | 10% |
| BRO-AMM, 3 bp | \$8 k | \$65 k | −\$76 k | −\$103 k | −\$324 k | 45% |
| BRO-AMM, 1 bp | −\$3 k | \$66 k | −\$129 k | −\$154 k | −\$587 k | 84% |

*Table 11. Mainnet LPs' daily net result over six months, stable costs. The worst day and week fall before the cost shift, so they are the same in all three cost scenarios.*

![Recapture frontier](figures/fig_recapture_frontier.png)

*Figure 10. Charging schedules evaluated statically with the benchmark known exactly, on every historical swap. Each dot is one schedule, a charge on each extracting swap set from its measured extraction. Vertical: share of extraction recaptured for LPs. Horizontal: arbitrage trades that would still be profitable after the charge, relative to today; at 0, corrections no longer pay and the pool would go stale. Charging all extraction recaptures most but leaves no arbitrage; charging only extraction above the benign fee keeps arbitrage but recaptures little, and the clip schedules near 2× also cut the benign fee to 1 bp; leaving an allowance $m$ and charging the rest, the static form of (4b), does both. The schedule fixed in advance, $m$ = 2 bp with charges capped at 500 bp, is circled.*

![Controller paths](figures/fig_controller_paths.png)

*Figure 11. Allowance over time with arbitrage costs quadrupled from June (dashed line). (a) Mainnet under the position model, decay without a signal against urgency measured by block position. (b) Arbitrum, decay without a signal against the sender rule $K_d \ge 4$. Each upward step is a staleness raise.*

![Stake and shocks](figures/fig_stake_shocks.png)

*Figure 12. (a) Hours of correctable blocks left uncorrected in the worst cost scenario, against arbitrageurs' stake held by one staker or by each separately, with hourly and daily settlement epochs. (b) LPs' gain lost to fresh unstaked accounts, in dollars, against $f_{\max}$, for the market's shocks scaled by one, two and four; zero is drawn at \$0.01 M. Larger shocks lose more dollars but a smaller share of LPs' gain, which grows faster with shock size.*

## Appendix D. Settlement measurements

**Components.**

| Component | Gas | Source |
|---|---|---|
| Single-swap transaction (median) | 188,705 mainnet / 136,171 Arbitrum | 400 receipts per chain |
| Data Streams report verification | 55,879 mainnet / 62,544 Arbitrum (37,544 each further in a tx) | traced historical calls; no on-chain fee |
| Hook: parking, collateral check, record | +17,112 per swap | v4 pool manager, Foundry, isolated transactions |
| Self-settlement | 46,000 + 6,000 per swap | Foundry |
| Keeper epoch | 26,000 + 14,300 per account (4,400 per skipped entry) | Foundry |
| Groth16 [@groth2016] proof verification, SP1 [@succinctSP1] | 227,226 | Foundry |
| ERC-4337 sponsorship overhead | +87,000–98,000 per settlement transaction | EntryPoint v0.7 |

**Settlement designs**, six months, including the hook on every swap:

| Design | Mainnet (× execution) | Arbitrum (× execution) |
|---|---|---|
| Keeper every block, one report per block | \$96.7 k (0.72) | \$21.2 k (0.72) |
| Keeper hourly, batch-signed prices | \$24.9 k (0.18) | \$5.7 k (0.19) |
| Keeper hourly, succinct proof | \$20.5 k (0.14) | \$4.3 k (0.15) |
| Every account self-settles hourly | \$38.7 k (0.28) | \$6.8 k (0.23) |
| Execution of the swaps | \$148 k | \$30 k |

**Keeper market.** Five keepers with differing costs and availability, over every hourly epoch. With on-chain settlement, an open race paid \$12.0 k on mainnet (no wasted work) against \$12.5 k for a designated leader. With proven settlement and similar keepers, a race wasted \$829 of duplicated proving — more than Arbitrum's settlement gas — whereas a leader wasted \$28 at a higher payment. A colluding leader can delay the LPs' credit by at most one epoch, worth under \$0.01.

**Small pools** (protocol take needed to fund keepers, hourly, at a recapture rate of 3.6 bp of volume): \$19.6 B pool 0.10–0.16%; \$0.24–0.67 B pools 0.5–1.2%; \$13 M pool 11–16%, falling to 1.5–2.5% at daily epochs. Funded jointly, all seven pools need 0.11–0.19%.

![Settlement cost](figures/fig_settlement_cost.png)

*Figure 13. Settlement gas relative to the execution gas of the settled swaps.*

![Gas tank](figures/fig_gas_tank.png)

*Figure 14. Smallest per-swap gas contribution that keeps the gas tank solvent.*

## Appendix E. REP's market price and escrow

Index epochs by $i = 1, 2, \dots$. In epoch $i$ let $V_i$ be the pool's volume, $N_i$ its net income (7), $X_i$ the charges covered by burning REP, $B_i = X_i / P_{\mathrm{int}}$ the units burned for them, $A_i$ the units prepaid and $\Xi_i$ the units redeemed (10). With $G_i$, $H_i$ and $\Delta S_i$ as in (7), write $S_t = \sum_{i \le t} \Delta S_i$ for the cumulative surplus and $U_t = S_t - G_t$ for the shortfall not recovered before minting resumed, which includes shortfalls older than $W$ epochs; $U_t \ge 0$, since by induction $S_t \ge \max_{j \le t} G_j$: each epoch mints at least the part of $G_i$ above every earlier value, and $X_t$, $A_t$, $\Xi_t$ for cumulative sums. Of each epoch's surplus only $\Delta S^{\mathrm r}_i = \min\big(\Delta S_i, \sum_a O_{a,i}\big) \le \Delta S_i$ is rebated by (7d), $(1 - \tau)$ of it minted and $\tau$ to the reserve, and the rest stays with the LPs; write $S^{\mathrm r}_t = \sum_{i \le t} \Delta S^{\mathrm r}_i \le S_t$. Let $R_t$ be the outstanding REP and $E_t$ the escrow after epoch $t$, valued in the numeraire, with an initial issuance $R_0$ and $E_0 = P_{\mathrm{int}} R_0$. The LPs receive each epoch's income less its rebated surplus, $N_i - \Delta S^{\mathrm r}_i$, in the pool's assets except for the charges, which are paid in REP and reach them as escrow released when the REP is burned; their cumulative income in the pool's assets is $\Lambda_t = \sum_{i \le t} (N_i - X_i) - S^{\mathrm r}_t + X_t$.

**Theorem 1 (backing and solvency at par).** For every $t$,

(i) $E_t = P_{\mathrm{int}}\, R_t = P_{\mathrm{int}} R_0 + (1 - \tau)\, S^{\mathrm r}_t + P_{\mathrm{int}}\,(A_t - \Xi_t) - X_t$, and hence $X_t \le P_{\mathrm{int}} R_0 + (1 - \tau)\, S^{\mathrm r}_t + P_{\mathrm{int}}\,(A_t - \Xi_t)$;

(ii) $\Lambda_t \ge \theta^* \sum_{i \le t} V_i - U_t$.

So outstanding REP is always fully backed in escrow, and if no shortfall has gone unrecovered ($U_t = 0$), LPs' income in the pool's assets is at least $\theta^* \sum_{i \le t} V_i$, even if every unit of REP ever issued is burned as collateral for extraction, and whatever is redeemed.

*Proof.* (i) Epoch $i$ rebates $(1 - \tau)\,\Delta S^{\mathrm r}_i / P_{\mathrm{int}}$ units and prepayments add $A_i$, each placing $P_{\mathrm{int}}$ per unit in escrow, and it burns $B_i$ and redeems $\Xi_i$ units, releasing $P_{\mathrm{int}}$ of escrow for each; no other operation changes $R$ or $E$. Summing gives both identities, and $R_t \ge 0$ gives the bound on $X_t$. (ii) Since $\sum_{i \le t} (N_i - \theta^* V_i) = G_t = S_t - U_t$ by definition, $\Lambda_t = \theta^* \sum_{i \le t} V_i + (S_t - S^{\mathrm r}_t) - U_t \ge \theta^* \sum_{i \le t} V_i - U_t$. $\blacksquare$

Prepayment and redemption move $P_{\mathrm{int}}$ per unit into and out of escrow with the REP itself, and the initial issuance is backed in the same way, so (i) holds whatever the mix of sources; REP issued without backing would break it. Because the backing stays in the pool, the guarantee holds for every cohort of LPs, not only for the pool as a whole: a charge covered by REP is paid in the pool's assets to the LPs present when it is covered, and an LP joining at any time inherits no outstanding REP without its backing. Extraction beyond an account's stake is covered by the reserve (§4.7), which restores the target only up to the reserve's balance.

**Proposition 1 (wash minting by an LP).** An LP holding a share $\phi$ of active liquidity that washes volume $V$ at fee $f > \theta^*$ through an account it controls receives REP worth $\nu$ times its internal rate. Without escrow, the surplus returns to the LPs, $\phi$ of it to the attacker, and the wash gains $\nu(1 - \tau)(f - \theta^*)V - (1 - \phi) f V$, which is positive whenever $\phi > 1 - \nu(1 - \tau)(1 - \theta^*/f)$: at $f = f_{\max}$ = 1,000 bp, $\theta^*$ = 2 bp and $\tau$ = 2.5%, above a share of 2.7% with REP at par and 51% with REP at half of it; at $f$ = 5 bp, above 42%. The gain is borne by the LPs present when the REP is later burned. With escrow, only the target share of the overpayment reaches the LPs, and the gain is $(\nu - 1)(1 - \tau)(f - \theta^*)V - \tau (f - \theta^*) V - (1 - \phi)\,\theta^* V$, negative for every $\phi$, since prepayment and redemption hold REP's price within their costs of $P_{\mathrm{int}}$ (11), so $\nu \le 1$ up to those costs.

Concentrated liquidity makes a large share of active liquidity cheap, which is why §4.7 lets a pool restrict liquidity to predefined ranges and lock it for an epoch; escrow is what removes the gain.

**Remark (raising the high-water mark).** An account cannot delay others' rebates through the mark. An overpayment $X$ raises $N_i$ and the cumulative $G_i$ by $X$. If $G_i$ was at or above its mark, the mark rises by $X$ as well, and the next epoch's surplus $G_{i+1} - H_i$ is measured from an unchanged base. If $G_i$ was below it, the first $H_{i-1} - G_i$ of $X$ fills the LPs' shortfall and only the rest is surplus; the mark then rises to the new $G_i$, so later epochs need not recover that shortfall and mint more, not less. Either way the overpayer recovers at most $(1 - \tau)$ of the part above the mark and nothing of the part that fills a shortfall, so moving the mark only subsidises other payers' rebates and the LPs' target, at the overpayer's cost. $G$ falls below its mark only when the LPs' income falls below the target, a real shortfall that (7) is meant to net, and a mark older than $W$ epochs leaves the window.

**Remark (excess is floored per epoch).** An account's excess $O_{a,i}$ in (7d) is floored at zero each epoch and not netted across epochs. Netting it per account would buy nothing, since an actor can route activity below the target through one account and overpayment through another (§3.1). The floor gives no profit: an account is rebated at most $(1 - \tau)$ of its own overpayment, so alternating below and above the target loses at least $\tau$ of what it overpays. Nor can an overpayment dilute others' rebates: when the surplus $\Delta S_i$ is smaller than $\sum_a O_{a,i}$, an overpayment $X$ above the mark raises both by $X$, so another account's share $O_{b,i}\,(\Delta S_i + X)/(\sum_a O_{a,i} + X)$ rises; below the mark, it first fills the LPs' shortfall.

**Remark (no account has a mark to recover).** The high-water mark is the pool's, not an account's, so an arbitrageur short of REP has no position to win back by trading harder. Under the per-unit cap (4b) a larger or more aggressive correction keeps no more than $m$ per unit and earns nothing past the band, and an overshoot opens a gap that the next corrector is paid to close; REP burned by charges is restored by prepayment (10), not by trading. The limited liability of a thinly staked account is bounded as for a fresh one: its fee approaches $f_{\max}$ by (3), parking (9) grows with the price move in the block, and with $f_{\max}$ sized to the shocks an unstaked account takes at most \$0.51 M at 500 bp and nothing at 1,000 bp under shocks two and four times the market's (Appendix K.4).

**Escrow in the simulation.** On the final mainnet design at 3 bp, with daily epochs and stable costs, charges burn \$8.71 M of REP over six months, several times what is rebated, so arbitrageurs prepay most of their REP at par and the escrow passes through rather than accumulating:

| Target $\theta^*$ | Minting | REP rebated to payers | LPs' total value | REP prepaid at par | REP burned for charges |
|---|---|---|---|---|---|
| 1 bp | per epoch | \$2.81 M | \$0.56 M | \$4.99 M | \$8.71 M |
| 1 bp | 30-epoch high-water (7) | \$1.31 M | \$2.06 M | \$6.48 M | \$8.71 M |
| 2 bp | per epoch | \$2.32 M | \$1.05 M | \$5.48 M | \$8.71 M |
| 2 bp | 30-epoch high-water (7) | \$0.30 M | \$3.07 M | \$7.49 M | \$8.71 M |

*Table 12. Mainnet, final design at 3 bp, stable costs, daily epochs, an initial issuance of \$0.91 M backed at par. LPs' total value counts their assets, the reserve and the escrow left; it is the same with and without escrow, which changes when and to whom the backing is paid, not its amount. The headline LP net of Table 3, \$3.37 M, mints no REP.*

What LPs give up is the rebate itself: REP minted to accounts that paid above the target. Minting per epoch rebates surplus from good days without netting the shortfalls of bad ones; the high-water mark of (7) nets them, and leaves LPs within \$0.30 M of an unminted pool at $\theta^*$ = 2 bp. Its window matters little beyond a few weeks:

| Netting of daily income | REP rebated, $\theta^*$ = 1 bp | REP rebated, $\theta^*$ = 2 bp |
|---|---|---|
| Each daily epoch alone | \$2.81 M | \$2.32 M |
| Weekly epochs | \$2.03 M | \$1.31 M |
| Monthly epochs | \$1.37 M | \$0.20 M |
| Daily epochs, 7-epoch high-water | \$2.07 M | \$1.35 M |
| Daily epochs, 30-epoch high-water | \$1.31 M | \$0.30 M |
| Daily epochs, all-time high-water | \$1.25 M | \$0.27 M |

*Table 13. REP rebated to payers above the target over six months, mainnet at 3 bp, stable costs. Monthly epochs would net as much as the window but delay settlement, unparking and escrow releases by a month.*

A pool should therefore set $\theta^*$ near its realised take-rate, which here is about 1.5 bp of volume.

The escrow can also work as capital: held as a full-range position in the pool, it earns its share of the pool's income and deepens the pool for traders. Here it never exceeds 0.07% of the pool's depth, adding about \$0.02 M, because a full-range position of value $W$ adds only $W/4$ of depth per unit of log price. Held in the pool's two tokens, its value moves with the square root of the price, while the REP it backs is fixed at $P_{\mathrm{int}}$, so the backing drifts above or below par; idle escrow in the numeraire keeps it exact. Escrow could come to own much of a pool only where little is extracted, so that REP is minted faster than it is burned, and its earnings are retained; a cap on escrow as a share of liquidity, or a slow decay of REP releasing escrow to LPs, prevents that.

**Price.** Prepayment adds a unit at $P_{\mathrm{int}}$ and redemption removes one at $P_{\mathrm{int}}$, so (11) holds without any market operation by the reserve. Because charges consume REP continuously, arbitrageurs are net prepayers in calm markets and in shocks alike; redemption mostly returns rebates to the overpayers who earned them, at par.

## Appendix F. Designs considered and rejected

**F.1 Average-edge cap.** A simpler rule would cap rent on the trade's *average* edge, $\bar e = \frac{1}{v}\int_0^v \mathrm{edge}(u)\,du$, letting the swap keep $\min(\bar e, m)$ on every unit, $\min(\bar e, m)\,v$ in total. The two rules differ most for a trade that continues past the band. Under the per-unit cap, a unit traded beyond the band has no edge and earns nothing, so the arbitrageur stops where the pool meets the band. Under the average-edge cap, the large edge of the first units keeps $\bar e$ above $m$ for a while after the band is crossed, so every further unit still earns $m$, even units that push the pool past the benchmark to a price that is wrong in the other direction. The arbitrageur is therefore paid to overshoot, until the average falls to $m$. In simulation an average-edge allowance of 1 bp raised LPs' net position by \$5.55 M on mainnet, against \$6.15 M for the per-unit cap at the same allowance, but overshot the benchmark in 24,092 blocks, nearly doubled arbitrage volume (\$24.5 B against \$13.4 B) and left users trading against prices 17.7 bp stale on average, against 12.75 bp today, failing the rebalancing constraint (Figure 15).

![Cap comparison](figures/fig_cap_comparison.png)

*Figure 15. Rent kept as a function of trade size under the per-unit cap and the average-edge cap: the first stops growing at the band, the second keeps growing past the benchmark.*

**F.2 Reimbursing gas separately.** The chain exposes its base fee at execution, so the arbitrageur's gas could be reimbursed on top of the allowance rather than folded into it. An allowance paid per unit of volume cannot cover the gas of the smallest corrections, so reimbursement helps: in an earlier version of the simulation, which judged staleness by a block's first swap, it raised LPs' worst-case gain from \$4.81 M to \$5.07 M on mainnet and left it unchanged on Arbitrum. We forgo it because crediting gas, paid in the native token, against a charge in the pool's tokens needs an exchange rate the pair does not contain; the gas tank of §4.9 needs none, since swappers fund it and keepers draw from it in the same native token (§4.4).

**F.3 Controller variants.** Measuring staleness as the share of time a gap is open, over every block, mistook mainnet's 12 s of fresh drift for staleness and drove $m$ to 21–31 bp. An allowance growing with the standing gap silenced the signal that raises $m$ and lengthened stalls (20–61 h on Arbitrum).

**F.4 The correction lane.** An earlier design kept the pool corrected without arbitrage stake through a lane: a correcting swap carried a signed report, paid $f_{\min}$, was charged against the report at execution and trued up against the batch benchmark at reconciliation from a margin. With reports exactly at the decision instant, it reproduced the fully staked result (\$4.90–4.93 M against \$5.01 M); with a report one second old the pool was no longer rebalanced (\$4.23 M). Drawing reports realistically, 0.25 s before the decision instant on a Brownian bridge between blocks, the lane without stake fails the rebalancing constraint in every scenario, leaving 26–35 hours of correctable blocks uncorrected in the cost scenarios and 177 under shocks ×4, because a report that old often cannot prove that a small gap exceeds the fee. A corrector picking the most favourable of five reports left \$0.12–2.21 M of true-ups beyond its margin. Setting the margin from the account's record of true-ups did not help in shocks, because that record measures volatility rather than conduct, and a margin parked from stake saved no coverage when it was needed. With 2 units of stake the lane kept the pool rebalanced through every shock, but bonds prepaid at par (§4.7) achieve this without stake held in advance and without reading an oracle at execution (`results/study_i/report*.json`). Before that, the lane was tested with reduced flat fees in place of the per-unit charge, and with the lane switched on and off. A flat fee $\varphi$ charged on the whole swap lets the arbitrageur trade only until the gap equals $\varphi$ plus its cost. Discounting to the plain pool fee therefore keeps the pool rebalanced but recaptures nothing: the pool behaves as it does today. A clearing fee $g - m$ fixed at the gap where the swap starts corrects only about $m$ of it. Discounts that grow with the gap leave small gaps facing fees near $f_{\max}$ and freeze the pool; discounts that shrink with the gap leave a residual fee at small gaps that the pool cannot cross. A hysteresis switch on the gap — the discount turned on once the gap exceeds a threshold and kept on until the pool returns to the band — behaves like the plain pool fee when its threshold is small and leaves the pool stale when it is larger. Opening the lane only for an hour after staleness is detected leaves the gaps that open while it is closed uncorrected on mainnet, though it passes on Arbitrum.

| No arbitrage stake, $f_{\max}$ = 500 bp | Mainnet | Arbitrum | Rebalanced |
|---|---|---|---|
| Flat fee discounted to $f_{\min}$ | \$0.00 M | \$0.00 M | yes |
| Flat clearing fee $g - m$ | \$3.26 M | \$0.39 M | no |
| Discount growing with the gap | frozen | frozen | no |
| Discount shrinking with the gap | frozen | −\$1.25 M | no |
| Hysteresis on the gap, threshold 2 bp | \$0.00 M | \$0.00 M | yes |
| Hysteresis on the gap, threshold 5 bp, clearing fee | \$0.87 M | −\$0.53 M | no |
| Per-unit charge, lane open only within an hour of staleness | \$3.91 M | \$0.64 M | mainnet no |

*Table 14. LPs' worst-case gain over today across the three cost scenarios, for rejected variants of the correction lane.*

**F.5 Allowance bonuses.** Raising the allowance beyond the arbitrageur's cost is rent, and rent is competed away for position. A flat premium of 0.5 bp tripled payments to builders in an early simulation. A bonus proportional to the market's jump within a block, paid only for corrections in that block so that waiting forfeits it, cost LPs 17–31% of their worst-case gain on mainnet and 11–17% on Arbitrum at REP's mint rate, while arbitrageurs' payments to builders roughly doubled; with REP valued below its mint rate it did not prevent stalls. Keying the bonus to the standing gap instead, which rewards waiting, did no better.

**F.6 Premium mint.** An arbitrageur without stake pays $f_{\max}$; minting it REP at the internal rate for the premium above $f_{\min}$, net of its charge, lets its first trades buy the stake that lowers its later fees. Valued at par, this bootstrapped a pool from zero stake at $f_{\max}$ up to 2,000 bp on both chains, matching the fully staked result. But an arbitrageur that values REP at a fraction $v$ of par bears a hurdle of about $(1 - v)(f_{\max} - f_{\min})$ per unit of volume, and the pool tolerated little discount: at $v$ = 0.99 it passed the rebalancing test only at $f_{\max}$ = 500 bp, losing 15% of LPs' gain; at $v$ = 0.98 it failed; and at $v$ = 0.95 it froze for $f_{\max} \ge$ 1,000 bp. Liveness would rest on REP trading at its mint rate; prepayment at par (§4.7) supplies the same bootstrap without that dependence.

**F.7 Controllers under dropout and withholding.** Arbitrageurs that win nothing for a week take their infrastructure down and return 24 hours after a gap they could have closed is left uncorrected. Events: the cheapest arbitrageur absent for seven days (dropout); the two cheapest absent for three days (withholding). Uncorrected hours over the three cost scenarios; LP gain is the worst case without events.

| Controller | Chain | LP gain | Uncorrected hours: none / dropout / withholding | Withholders' extra income |
|---|---|---|---|---|
| Decay without a signal | mainnet | \$5.01 M | 1–4 / 23–24 / 23–24 | \$0.43–0.51 M |
| Urgency-accelerated decay | mainnet | \$5.20 M | 2–3 / 24–25 / 23–24 | \$0.09–0.11 M |
| Most frequent sender below 75% | mainnet | \$4.69 M | 1–2 / 1–2 / 22 | \$0.06–0.18 M |
| $K_d \ge 4$ | mainnet | \$4.22 M | 0.1 / 0.1 / 0.1 | none |
| $K_d \ge 5$ | mainnet | \$3.98 M | 0.0 / 0.0 / 0.0 | none |
| Rotation, others earn 75% of $m$ | mainnet | \$5.27 M | 2–5 / 2–3 / 22–24 | \$0.11–0.15 M |
| Rotation, exclusive windows | mainnet | \$3.46 M | 12 / 12 / 12 | none |
| Decay without a signal | Arbitrum | \$0.71 M | 12–14 / 26–30 / 27–31 | \$0.05–0.14 M |
| Most frequent sender below 75% | Arbitrum | \$0.66 M | 0–2 / 0–3 / 19 | \$0.04–0.08 M |
| $K_d \ge 4$ | Arbitrum | \$0.65 M | 0–1 / 0–1 / 0–1 | none |
| $K_d \ge 5$ | Arbitrum | \$0.42 M | 0 / 0 / 0 | none |
| Rotation, others earn 75% of $m$ | Arbitrum | \$0.75 M | 0–3 / 19 / 19 | \$0.03–0.04 M |

*Table 15. On mainnet the sender-count rules assume arrival ordering, which builder auctions do not provide. With a one-hour redeploy, decay without a signal and urgency-accelerated decay both keep the pool rebalanced through both events.*

Rotation designates, each hour, one registered arbitrageur that earns the full allowance while others earn less; it requires registration, and unless its windows are exclusive, cheaper non-designated arbitrageurs still take the corrections and the others still leave. A rule that raises $m$ when too few corrections are contested does not help under builder auctions either: competitors that never win cannot be kept deployed.

**Urgency by block position.** The mainnet runs of Appendix K.3 add a position model to the simulation. Each block's ordinary swaps draw priority fees from the distribution measured on the pool (median 0.64 gwei), builders order transactions by payment per unit of gas, and each arbitrageur chooses its payment for position to maximise profit net of the late-fix penalty, paying the runner-up's margin when contested; 45% of arbitrageurs pay builders outside the transaction, in line with the 40–45% of today's mainnet corrections that pay builders other than through the priority fee. Ranges are over the three cost scenarios, redeploy delays of one hour and one day, and the events above.

| Controller | LP gain over today | Payments to builders | Users' price vs today | Worst drop in blocks within band | Rebalanced in every run |
|---|---|---|---|---|---|
| Decay without a signal | \$4.66–5.27 M | \$0.96–1.71 M | 0.02–0.13 bp fresher | 0.50 pp | yes |
| Urgency by position, $\kappa = 2$ | \$5.35–5.86 M | \$0.57–0.80 M | 0.14–0.23 bp fresher | 0.50 pp | yes |
| Urgency observed exactly | \$5.41–5.98 M | \$0.53–0.74 M | 0.01 bp staler to 0.12 bp fresher | 0.51 pp | no (withholding) |

*Table 16. Mainnet controllers under the position model.*

With the position model every controller leaves 35–47 hours of correctable blocks uncorrected over the six months, against 1–4 without it, because a correction must pay for position and keeps less allowance when late; the events add none. Urgency judged by priority fee alone, with no position, misses the 45% of payments made outside the transaction and was dropped. Targeting a fixed separation between corrections and retail through $m$ itself drove $m$ to its 50 bp ceiling and paid the excess to builders: timeliness belongs in the penalty, not in the allowance.

Lowering $m$ only while urgency is visible, with no default decay, leaves $m$ high whenever a single arbitrageur is deployed (\$4.63 M). On today's data, position within the block separates corrections that pay for position from those that do not only near the very top of a mainnet block (Youden's $J$ = 0.33 for the first three transactions, 0.07 for the first quarter, 0.17 for a priority fee above 2 gwei), because today nearly every correction is contested; under the mechanism, uncontested corrections have no reason to be early, and block-relative measures should separate better.


## Appendix G. Extended discussion

**G.1 The decision instant.** On Ethereum, a block's timestamp is the start of its slot, a label fixed before the block's content is chosen. Ordinary swaps are typically signed and broadcast through the public mempool seconds before inclusion. Arbitrage between centralised and decentralised exchanges is non-atomic: the arbitrageur hedges on the centralised exchange and sends its on-chain leg privately to block builders, and a few searchers closely tied to builders account for most of its volume [@heimbach2024nonatomic]. Builders bid for the block in the MEV-Boost auction, and arbitrageurs re-price their bundles as the external price moves until the proposer takes the winning header — which proposers delay into the slot to collect higher bids [@schwarzschilling2023timing; @oz2023time]. An arbitrageur's last decision therefore falls after the timestamp, by about the time the winning bid is taken.

By contrast, L2s such as Arbitrum have no public mempool. Arbitrum's sequencer orders transactions by arrival into blocks of about 250 ms whose timestamps have a resolution of one second. Since April 2025, a sealed-bid second-price auction held every minute sells an express lane, and all other transactions are delayed by 200 ms, the Timeboost design [@mamageishvili2023buyingtime]. Three entities won almost all of these auctions [@messias2025timeboost]. An arbitrageur reacting to an external move is sequenced within its network latency plus at most that delay, so its decision lies close to its inclusion, wherever in the block that happens to be.

Rather than assume a latency, we measure it. A swap that corrects the pool trades until the pool price net of the fee meets the external price at which it can hedge, at the instant it decides; the offset from the block timestamp that minimises this residual over correcting swaps therefore identifies the decision latency $L$, and we score at $t^* = \text{block timestamp} + L$ (Figure 5). The estimate is 1.5 s on mainnet (bracketed by 1.25–1.75 s), consistent with bids taken one to two seconds into the slot, and 0.75 s on Arbitrum (0–1.5 s), where the staleness of our price proxy dominates the bracket and its earliest estimate places the match at block time itself, as arrival ordering implies. Benign flow shows no relation to the offset: it is uninformed, so its decision instant does not affect its score. The anchor matters for informed flow: anchoring at the timestamp scores arbitrageurs against prices from before they traded (Appendix K.1). $L$ is a parameter of each pool, re-estimated periodically from reconciled correcting swaps and changed only within its bracket; scores are insensitive to $L$ inside the bracket (Appendix B), and an arbitrageur can shift the estimate only by stopping its trades away from the hedgeable price, at a loss to itself.

**G.2 Fresh accounts and $f_{\max}$.** An account that holds no stake has $r = 0$, so nothing it owes after the block can be collected, and the fee it pays at execution is all the pool ever receives from it. Consider two arbitrageurs facing the same gap $g$ between the pool and the benchmark. One holds enough stake to pay a fee near $f_{\min}$: it corrects the gap, keeps at most $m$ per unit of volume, and pays the rest as its charge (4b) after the block. The other trades from a fresh account: it pays $f_{\max}$, and with $r = 0$ none of the charge it owes can be collected, but it profits only while the remaining gap exceeds $f_{\max}$ plus its own cost rate $h$. In a pool of depth $D$ per unit of log price, each unit it trades moves the pool by $1/D$ toward the benchmark, so after volume $u$ its margin on the next unit is $g - u/D - f_{\max} - h$: the full excess $g - f_{\max} - h$ on the first unit, falling linearly to zero, where it stops after a volume of $D\,(g - f_{\max} - h)$. A margin that falls linearly to zero averages half its starting value, so the account's take is $D\,(g - f_{\max} - h)^2/2$, assuming depth is roughly constant over the range the trade moves the pool.

Two conclusions follow. For any gap smaller than $f_{\max} + h$, the fresh account cannot trade at a profit at all; only on larger dislocations can its uncharged take exceed what a staked arbitrageur keeps, and that take grows with the square of the excess. $f_{\max}$ is therefore best read as the size of dislocation the pool is designed to withstand without leakage, and it should be set above the largest shock the pool expects; Appendix K.4 measures the leakage as a function of $f_{\max}$ and shock size. A high $f_{\max}$ does not burden ordinary flow, which pays close to $f_{\min}$ through stake held directly or by an intermediary that trades on its behalf (§6.1), and escaping it takes little stake: because the curve is exponential, a coverage ratio of $\ln\big((f_{\max} - f_{\min})/\delta_f\big)$ brings the fee within $\delta_f$ of $f_{\min}$, a requirement that grows only with the logarithm of $f_{\max}$.

**G.3 The allowance controller.** A correctable block is one any arbitrageur whose cost is below $m$ would profit from correcting. In a pool whose allowance covers some arbitrageur's cost, correctable blocks are almost never left stale; when $m$ lies below every arbitrageur's cost, they always are. Staleness is defined by outcome rather than by the block's first swap because ordering is adversarial (A3): a builder could otherwise place a dust swap in the wrong direction ahead of each correction, make every block look stale and ratchet $m$ upward at the cost of dust; under the outcome rule it would have to keep every correcting swap out of the block, forgoing what those swaps pay for inclusion. A gap that persists through blocks without swaps is observed at the pool's next swap. The competition signal resists manipulation: an arbitrageur that fakes competition with extra addresses only lowers its own allowance, and hiding competition requires a cartel that any arbitrageur with a cost below $m$ can break. The controller's inputs — the resting price at the start of each block, the pool's price after each swap, the signed benchmark and the sender of each correcting swap — are all part of reconciliation; it needs neither the arbitrageurs' costs nor transaction indices.

**G.4 Oracle attestation.** Because reconciliation is not time-critical, the prices it uses can themselves be subject to consensus, which an oracle read at execution cannot afford. Oracle networks already aggregate the reports of independent nodes and sign the result once [@breidenbach2021ocr]; BRO-AMM can add a second, independent layer, applying a batch only after a threshold of attesters has co-signed it, or after a challenge window has passed without dispute. A corrupted feed must then also corrupt that threshold. The natural attesters are the parties exposed to the batch, but they are not neutral: LPs gain from prices that inflate charges and traders from prices that deflate them. Attestation therefore needs both sides — LPs weighted by liquidity and stakers weighted by stake — and what an epoch settles to when they disagree must not give either side a free option; we leave the design of dispute resolution to future work [for a survey of oracle designs and attacks, see @eskandari2021sok]. The cost is latency rather than gas: a few signature checks per epoch, against a settlement deadline that is already long. Only epoch-based reconciliation can absorb that delay, a further reason to price after the fact.

**G.5 Intermediary economics.** A router holding stake $r$ against its volume $V$ per epoch has coverage $c = r/(\rho V)$ and pays the premium $(f_{\max} - f_{\min})e^{-c}$ over $f_{\min}$ by (3). Holding the stake costs its cost of capital $k$ and an expected annual loss $d$ on REP's price, on $(c + 1)\rho V$ per epoch of volume, where the extra $\rho V$ is stake parked by the epoch's own trades (§4.7), assumed not to count toward coverage until settlement. Per unit of volume, with epochs of $T$ days, the total $(f_{\max} - f_{\min})e^{-c} + (k + d)(c + 1)\rho T/365$ is minimised at $c^* = \ln\big((f_{\max} - f_{\min}) \cdot 365 / ((k + d)\rho T)\big)$. With $\rho$ = 5 bp, $f_{\min}$ = 1 bp, $f_{\max}$ = 1,000 bp and $k$ = 10%:

| Epoch | Expected REP loss | Coverage $c^*$ | Stake, share of epoch volume | Stake for \$10 M a day | Premium + holding cost |
|---|---|---|---|---|---|
| hourly | 0% a year | 16.7 | 0.88% | \$4 k | 0.001 bp |
| hourly | 50% a year | 14.9 | 0.79% | \$3 k | 0.006 bp |
| daily | 0% a year | 13.5 | 0.72% | \$72 k | 0.021 bp |
| daily | 50% a year | 11.7 | 0.64% | \$64 k | 0.113 bp |

*Table 17. Cost to a router of quoting near $f_{\min}$, at its cost-minimising stake. With $f_{\max}$ = 500 or 2,000 bp the total cost changes by at most 0.006 bp, since it grows only with $\ln f_{\max}$.*

The cost assumes the router's flow is benign. Every price-correcting swap is charged on its edge beyond fee, $\varepsilon$ and $m$, whoever sends it, so a router's stake also pays for those of its users' trades that land on a stale pool. On today's swaps, with each swap's edge falling linearly from its pre-trade to its post-trade gap and $m$ = 2 bp, $\varepsilon$ = 0.5 bp:

| Flow | Chain | Volume charged | Charge | Median day | 99th-percentile day | Worst day |
|---|---|---|---|---|---|---|
| retail aggregators | Mainnet | 5% | 0.11 bp | 0.02 bp | 1.1 bp | 1.6 bp |
| retail aggregators | Arbitrum | 4% | 0.17 bp | 0.00 bp | 1.2 bp | 4.7 bp |
| unlabelled | Mainnet | 47% | 7.45 bp | 1.85 bp | 30.0 bp | 193.1 bp |
| unlabelled | Arbitrum | 25% | 1.99 bp | 0.79 bp | 5.5 bp | 108.1 bp |
| top-of-block searchers | Mainnet | 77% | 3.74 bp | 2.28 bp | 23.7 bp | 97.0 bp |
| top-of-block searchers | Arbitrum | 13% | 0.51 bp | 0.25 bp | 2.9 bp | 34.2 bp |

*Table 18. Charges that flow by label would incur under (4b), per unit of its volume, March–August 2026. Measured against the mid price rather than the directional bid/ask, these are upper bounds; with $m$ of 1 or 3 bp retail-aggregator charges are 0.09–0.20 bp.*

Retail-aggregator flow is cheap to carry; mixed flow is not, so a router prices the toxicity of its flow as order-flow buyers do today.

## Appendix H. A worked example

Consider an ETH/USDC pool with $f_{\min} = 1$ bp, $f_{\max} = 1{,}000$ bp, $\rho = 5$ bp, $\theta^* = 2$ bp, $m = 2$ bp, $\varepsilon = 0$, $\tau = 2.5\%$ and an internal rate of 1 USDC per REP. Both swaps below are \$10,000 and fall in one epoch.

*Alice*, an uninformed trader, holds 25 REP, directly or through an intermediary that trades on her behalf. Her coverage ratio is $25/(0.0005 \times 10{,}000) = 5$, so by (3) she pays $1 + 999e^{-5} = 7.73$ bp, or \$7.73; without stake she would pay $f_{\max}$, 10%. Her markout before fees is zero, so her $Q_{\mathrm{LP}}$ is $+7.73$ bp. With no price move in the block she parks $\ell V = 5\,\text{bp} \times \$10{,}000$, or 5 of her REP, until settlement.

*Bob*, an arbitrageur holding 35 REP (coverage ratio 7), corrects the pool after a market move and pays $1 + 999e^{-7} = 1.91$ bp. Along his trade the edge beyond the fee falls linearly from 10 bp to zero, so he extracts 5 bp on average, \$5.00, and his $Q_{\mathrm{LP}}$ is $-5$ bp. Writing $u$ as a fraction of his notional, by (4b) he keeps $\int_0^1 \min\big(10(1 - u), 2\big)\, du = 1.80$ bp, and the remaining 3.20 bp, \$3.20, is charged. The pool had already moved 10 bp within the block, so by (9) with $k = 0.5$ he parks $\ell = 5 + 5 = 10$ bp of his volume, 10 REP; the charge burns 3.20 of them, and the other 6.80 are released at settlement.

At reconciliation, by (7), $N = 7.73 - 5.00 + 3.20 = \$5.93$ against a target of $2\,\text{bp} \times \$20{,}000 = \$4.00$, a surplus of \$1.93. Only Alice paid more than the target on her own volume (Bob's net is $-1.8$ bp), so she receives $(1 - 0.025) \times 1.93 = 1.88$ REP, and her next \$10,000 swap, with 26.88 REP staked, pays $1 + 999e^{-5.38} = 5.62$ bp. Bob kept his allowance of \$1.80; his position did not change the benchmark he was scored against (§4.2), so the most he would rationally have paid for it is his margin over his cost. The swaps left the LPs \$2.73 in the pool's assets, from which the surplus of \$1.93 goes to escrow behind Alice's new REP; Bob's charge of \$3.20 is settled by burning his REP, which releases \$3.20 of escrow to the LPs. They end the epoch with \$4.00, exactly the target (Theorem 1).

*The allowance.* With the controller of (6) at $\chi_{\uparrow} = 2$, $n_{\min} = 5$ and $q_{\mathrm s} = 2\%$, an hour in which 6 of 200 correctable blocks are stale (3%) raises $m$ from 2 to 4 bp. On a later day with $\bar u = 0.5$, if 60% of corrected blocks are urgent, $m$ falls to $0.8 \times 4 = 3.2$ bp ($\chi_{\mathrm u} = 0.8$); on a calm day with fewer than $q_{\mathrm c} = 1\%$ of correctable blocks stale, it falls by $\chi_{\mathrm c} = 0.95$. Had a quarter of the block's protected retail volume traded before Bob, the penalty $\lambda = 0.25$ would have cut what he keeps by $\lambda a = 6.25\%$, from 1.80 to 1.69 bp.

*The bond.* After settlement Bob holds 31.80 REP. To trade his next \$10,000 at the same coverage ratio of 7, he declares a prepayment of \$3.20 in a swap, which mints 3.20 REP at par and adds \$3.20 to the escrow by (10). Alice may redeem her 1.88 new REP for \$1.88 from escrow once she has no settlement pending, or keep them staked for the lower fee.

## Appendix I. Arrival-ordered rollups: Arbitrum

Each rollup orders transactions by its own sequencer rules, so the competition signal of §4.5 must be adapted chain by chain. This appendix adapts it to Arbitrum One, whose sequencer orders transactions by arrival except for the Timeboost express lane, and repeats the evaluation of §5 on its WETH/USDC 5 bp pool over the same six months: 5,237,793 swaps in 63.4 M blocks, 1.87 M of them with a pool swap, and \$11.2 B of volume.

**I.1 Measurement.** The decision latency is 0.75 s, bracketed by 0–1.5 s (Figure 5). Against the price-free labels the AUC of $Q_{\mathrm{LP}}$ is 0.814 (0.897 for the largest swaps), and against the position-free label 0.828 (0.883), higher than on mainnet because extraction here occurs deep in the block, beyond the positional label's reach: 69% of it at position ten or later. Corrections are level with or behind retail in the block (Figures 7–8). Over the sample LPs lost \$1.34 M to extraction and ended \$0.86 M up after fees.

**The express lane.** Receipts on Arbitrum carry a `timeboosted` flag marking transactions sequenced through the Timeboost express lane. In a random sample of 3,000 blocks with a correction, read from the public endpoint, 65% of first correcting swaps and 68% of non-correcting swaps were timeboosted, and among corrections 68% of those that earned rent today and 65% of those that did not. The flag therefore does not distinguish contested corrections and is not used as an urgency signal.

**I.2 Competition by sender count.** Where the sequencer orders transactions by arrival, as Arbitrum does outside its express lane, a lead over retail is won by latency rather than by payment: an arbitrageur without a rival leads as readily as one with, so the upper tail of $z_b$ carries no information about competition. There the urgency condition in (6) is replaced by sender diversity: with $K_d$ the number of senders that each made at least 5% of the day's corrections, $m \leftarrow 0.95\, m$ if $K_d \ge K_{\min}$, where $K_{\min}$ is the required number of competing senders, which keeps several arbitrageurs profitable and deployed. The final design uses $K_{\min} = 3$: with the express lane concentrated in three entities, requiring four senders keeps the allowance higher at no gain in rebalancing (below); the robustness tests in Appendix F.7 use four. The stale tail and the penalty are unchanged.

**Express-lane concentration.** On Arbitrum, three entities won almost all Timeboost auctions [@messias2025timeboost]. With one of three express-lane holders winning, in each one-minute round, every correction it can profit from, and every correcting swap charged, LPs' worst-case gain at 5 bp is +\$0.60 M with $K_{\min} = 4$ and +\$0.84 M with $K_{\min} = 3$, against +\$0.83 M in an open race: requiring four senders when three dominate keeps the allowance higher, whereas three recovers the open-race result. Both keep the pool rebalanced.

**I.3 Results.** Every correcting swap charged, the sender rule at $K_{\min} = 3$ and a 4 bp fee leave LPs ahead of today's 5 bp pool by \$0.38–0.59 M across the cost scenarios (\$1.97 M against \$1.38 M with stable costs), with retail paying about 4.38 bp all-in (4 bp, 0.20–0.26 bp of retail charges, up to 0.12 bp of REP holding), users trading at fresher prices (3.62 against 4.28 bp), arbitrageurs' spending to be ordered first falling from \$0.94 M to \$0.24 M, and the pool as rebalanced as today. At 3 bp the sender rule falls short of today, because users already close many small gaps for the fee alone and a lower fee hands them to paid arbitrageurs (Table 9 in Appendix C). With users' corrections uncharged, LPs at today's fee gain \$0.65 M in the worst case; if users route away, LPs need to keep about 85% of their flow, because users' own trades do part of the rebalancing (Table 8). The sender rule settles at 1.46 bp and absorbs the cost shock without a raise (Figure 11), and under dropout and withholding costs 2% of LPs' gain (Table 15). Without arbitrage stake, fresh accounts take nothing at $f_{\max}$ = 500 bp; stake of about 25 times $\rho$ times mean daily arbitrage volume, \$0.34 M, keeps the pool rebalanced with daily epochs if one staker covers all arbitrageurs (hourly epochs, as on mainnet, need less); and charging against a price one second off the decision instant cuts LPs' gain from \$0.65 M to \$0.23 M, so rollups need signed prices with sub-second resolution (Appendix K.6). Settlement costs 0.19× the execution gas of the settled swaps, and a gas tank needs 0.64 k gas per swap (Figures 13–14).

**I.4 A per-gap reverse auction.** Instead of one allowance for all corrections, each gap's allowance could start low and rise with its age, $m(t) = \min(m_0 + \text{slope} \cdot \text{age}, m_{\text{cap}})$, so that the first corrector whose cost it covers takes the gap at that price; correctors then compete on the price they will work for, gap by gap. The age is computed at reconciliation from the same signed prices as the charge, and resets only when a block ends within $f + \varepsilon + m$ of the benchmark, so that a token correction cannot hold the allowance down. On Arbitrum, with $m_0$ = 0.5 bp, a 5 bp cap and every correcting swap charged, the ramp beats the sender rule when arbitrageurs act as soon as the allowance covers their cost, but not when they hold out for a margin above it, which a reverse Dutch auction invites. A slow ramp then leaves gaps standing; a steep one pays a whole step of about 1 bp per 250 ms block:

| Design | Fee | LPs' gain over today, worst case | Rebalanced in every scenario |
|---|---|---|---|
| Sender rule, $K_{\min} = 4$ | 3 bp | −\$0.32 M | yes |
| Ramp, +1 bp/s, margin 0 bp | 3 bp | +\$0.15 M | yes |
| Ramp, +1 bp/s, margin 0.25 bp | 3 bp | −\$0.15 M | no (×8) |
| Ramp, +1 bp/s, margin 0.5 bp | 3 bp | −\$0.43 M | no (×4, ×8) |
| Ramp, +4 bp/s, margin 0 bp | 3 bp | +\$0.30 M | yes |
| Ramp, +4 bp/s, margin 0.25 bp | 3 bp | −\$0.35 M | yes |
| Ramp, +4 bp/s, margin 0.5 bp | 3 bp | −\$0.47 M | yes |
| Sender rule, $K_{\min} = 3$ | 4 bp | +\$0.38 M | yes |
| Sender rule, $K_{\min} = 4$ | 4 bp | +\$0.28 M | yes |
| Ramp, +1 bp/s, margin 0 bp | 4 bp | +\$0.53 M | no (×8) |
| Ramp, +1 bp/s, margin 0.25 bp | 4 bp | +\$0.24 M | no (×4, ×8) |

*Table 19. Arbitrum, every correcting swap charged; gains are worst cases across the three cost scenarios.*

A lone arbitrageur that waits for the cap leaves each gap open for several seconds: at 3 bp, 584 hours of correctable blocks go uncorrected and LPs end \$1.07 M short of today. The ramp therefore needs at least two active correctors, which liquid pools have, and its gain depends on how close to cost they act, which our data cannot measure. The final design keeps the sender rule.

## Appendix J. Variables and parameters

Table 20 collects the variables and parameters of the settlement equation (1), the equations each enters, the values used on mainnet, and the evidence that set them.

| Symbol | Meaning | Enters | Mainnet value | How it is set |
|:----|:----------|:---|:-----|:------------|
| $v_j$, $V_{a,i}$, $V_i$ | notional of swap $j$; account's and pool's volume in epoch $i$ | (1), (3), (7) | data | — |
| $r_a$, $P_{\mathrm{int}}$ | account's staked REP; REP's internal mint and burn rate | (1), (3), (9) | — | — |
| $f_{\min}$, $f_{\max}$ | fee floor and ceiling | (3) | 3 bp; 1,000 bp | lowest fee at which LPs' net stays positive in every cost scenario (§5.1); smallest at which fresh accounts take nothing under shocks four times the market's (Appendix K.4) |
| $\rho$ | capacity scale of the curve; base parking rate | (3), (9) | 5 bp | held fixed; the curve's shape is varied through $s$ instead (Appendix C) |
| $s$ | steepness of the curve | (3) | 1 | milder curves stall correctors, steeper ones leave charges uncovered; neither passes shocks with daily epochs (Appendix C) |
| $L$, $t^*_b$, $\hat P_j$ | decision latency; decision instant of block $b$; directional benchmark | (2) | 1.5 s | measured from correcting swaps (§3.2) |
| $\varepsilon$ | tolerance for oracle error | (4a) | 0.5 bp | $\max(\lvert\text{bias}\rvert, 2\sigma_o)$ (Appendix K.6) |
| $m$ | allowance per unit of volume | (4b), (6) | discovered | by (6) |
| $\lambda$, $a_j$ | late-fix penalty; protected retail share ahead of swap $j$ | (4b) | 0.25 | position model (Appendix F.7) |
| $\chi_{\uparrow}$, $\chi_{\mathrm u}$, $\chi_{\mathrm c}$ | controller's raise, urgent-cut and calm-decay factors | (6) | 2, 0.8, 0.95 | raise fast, lower slowly; rebalancing constraint (Appendix K.3, Appendix F.7) |
| $n_{\min}$, $q_{\mathrm s}$, $q_{\mathrm c}$, $H$ | minimum stale count, stale-share thresholds for a raise and for calm decay, raise window | (6) | 5, 2%, 1%, one hour | as above |
| $m_{\min}$, $m_{\max}$, $m_0$ | bounds and starting value of the allowance | (6) | 0.02 bp, 50 bp; 5 bp | — |
| $q_{\mathrm p}$, $q_{\mathrm r}$, $q_{\mathrm k}$ | priority-fee quantile of protected retail; reference retail quantile; sender share counted in $K_d$ | (4b), (5), (6) | 90%, 75%, 5% | — |
| $\Delta_{\mathrm w}$ | scoring window | (2) | one second | timing noise inside the window (Appendix B) |
| $\kappa$, $\bar u$ ($K_{\min}$) | urgency boundary and threshold (senders' threshold on arrival-ordered chains) | (5), (6) | 2, 0.5 (3) | rebalancing constraint under cost shocks, dropout and withholding (Appendix K.3, Appendix F.7) |
| $\theta^*$, $W$ | LPs' target take-rate; high-water window | (7) | 1.5–2 bp; 30 days | target near LPs' realised take; window capturing most of an all-time mark (Appendix E) |
| $\tau$ | protocol take on rebates, to the reserve | (7) | 2.5% | illustrative; never applied to prepayment, where a markup of 1% already fails the rebalancing constraint (Appendix K.4) |
| $\ell_j$, $k$ | parked share of a swap's volume; parking speed | (9) | — | — |
| epoch | settlement period | (3), (7), (9) | one hour | stake sized for normal markets carries shocks four times the market's; settlement gas 0.18× execution (Appendix K.4, Appendix K.7) |
| $R_a$, $X_a$, $\xi$ | REP the account holds; an overpayment it declares to prepay REP at par; units it redeems at par once no settlement is pending | (10) | chosen by the account | bond outstanding peaks at \$1.12 M under shocks ×4 (Appendix K.4) |
| $R_0$ | initial issuance at deployment, backed by $P_{\mathrm{int}}$ per unit | (8) | — | spares early holders a first prepayment; consumed within weeks (Appendix K.4) |
| $c_{\mathrm{p}}$, $c_{\mathrm{r}}$ | costs of a prepayment and of a redemption | (11) | gas; and the wait for settlement | — |
| $\gamma$ | gas units prefunded per swap | §4.9 | — | gas-tank solvency (Appendix K.7) |

*Table 20. Variables and parameters of (1). Parameters are fixed within ranges at deployment and changed only after a delay (A6). Each was chosen by two criteria applied together: the design must keep the pool rebalanced in every cost scenario, and among such designs the larger worst-case gain for LPs is preferred; designs that change collateral must also leave charges collectable from stake.*

## Appendix K. Detailed results

**K.1 Scoring validity.**

$Q_{\mathrm{LP}}$ at the measured decision instant separates extraction from benign flow on labels that use no prices (Figures 5–8 in Appendix B).

| Mainnet, March–August 2026 | Value |
|---|---|
| Decision latency $L$ | 1.5 s |
| LPs' net loss, scored at $t^*$ / at the block timestamp | −\$1.58 M / +\$5.26 M |
| AUC, position labels (retail aggregators against repeat top-of-block searchers) | 0.889 (largest swaps 0.983) |
| AUC, position-free label (any non-router sender with at least 100 swaps) | 0.704 (largest swaps 0.971) |
| Share of extraction in a block's first three positions | 61% |

*Table 21. Scoring validity. Scoring at the block timestamp turns the LPs' measured loss into an apparent gain; the position-free label admits benign repeat senders, which lowers its AUC.*

**K.2 The lower fee: robustness and risks.**

| Robustness of the lower fee, mainnet | Result |
|---|---|
| LPs' gain over today, across the three cost scenarios | \$5.76–6.52 M |
| Retail's price, across the scenarios | about 1.7 bp below today |
| Arbitrageurs' payments to builders | 83–86% lower |
| Lowest fee at which LPs beat today / stay positive | 0.5 bp / 3 bp |
| LPs' net per unit of liquidity at 3 bp, today's flow / three times today's flow | \$1.41 M / \$1.95 M |
| At today's 5 bp fee, all users routed away | LPs still beat today by \$1.24 M |
| Arbitrum, arrival-ordered (Appendix I) | beats today at 4 bp, not at 3 bp |
| Fixed schedule with the benchmark known exactly: recapture / arbitrage preserved / benign overcharge | 73% / 97–99% / below 0.1 bp |

*Table 22. Sensitivity of the headline (Appendix C, Figure 10). The fixed schedule was selected on March–May and remains the best on June–August.*

| Daily LPs' result and intermediaries' exposure | Today, 5 bp | BRO-AMM, 3 bp |
|---|---|---|
| Standard deviation of LPs' daily result | \$32 k | \$65–66 k |
| Worst day / worst week | −\$211 k / −\$722 k | −\$103 k / −\$324 k |
| Router's cost of holding REP | — | at most 0.12 bp of its volume |
| Charges on retail-aggregator flow, average / worst day | — | 0.19 bp / 1.6 bp |
| Charges on unscreened flow | — | 2–8 bp |

*Table 23. Risks of competing on fee (Appendix C, Appendix G.5). Recapture arrives on volatile days, so daily results vary more but lose less.*

**K.3 Allowance discovery and robustness.**

| Controller, mainnet | LPs' worst-case gain |
|---|---|
| Decay without a competition signal | \$4.82 M |
| Urgency measured by block position (late 32%, timely 23%, urgent 45% of corrected blocks) | \$5.38 M |
| Urgency observed exactly (not implementable) | \$5.45 M |
| Cheapest arbitrageur absent for a week, or two cheapest withholding for three days, redeploying after an hour or a day | \$5.35–5.86 M; withholders' income moves by at most \$0.03 M |

*Table 24. Allowance controllers under the position model, with 45% of arbitrageurs paying builders outside the transaction (Appendix F.7). Every variant keeps the pool rebalanced, from a monopoly to ten arbitrageurs and with depth halved or doubled (Appendix C, Figure 11).*

**K.4 Arbitrage stake and bonds.**

This subsection uses decay without a signal, whose worst-case gain with full stake is \$5.01 M, because the position model does not yet combine with finite stake.

| Fresh accounts at $f_{\max}$ | LPs' worst-case gain | Taken by fresh accounts, shocks ×2 and ×4 |
|---|---|---|
| $f_{\max}$ = 30 bp | \$3.53 M | — |
| $f_{\max}$ = 500 bp | \$4.93 M | at most \$0.51 M |
| $f_{\max}$ = 1,000 bp | — | nothing |

*Table 25. Arbitrageurs free to trade from unstaked accounts (Figure 12b in Appendix C).*

| Settlement epoch | Stake, one staker for all | Stake, each its own | Shocks ×2, 25 units pooled | Shocks ×4, 25 units pooled | Stake built from zero over a month |
|---|---|---|---|---|---|
| Daily | 25 units | 50 units | fails, 123 h stale | fails, 605 h stale | 88 h stale |
| Hourly | 2 units (\$0.08 M uncovered); 5 units, none | 5 units (\$0.18 M uncovered); 25 units, none | passes, nothing uncovered | passes, \$0.36 M uncovered | 27 h stale |

*Table 26. Stake held in advance, in units of $\rho$ times the mean daily arbitrage volume (\$36 k). Charges are taken from stake within each epoch; "uncovered" counts charges beyond it. The stake columns give the smallest stake that keeps the pool rebalanced in every cost scenario, and the smallest that also leaves no charge uncovered. Steeper or milder curves do not substitute for shorter epochs (Appendix C).*

| REP bonded per epoch, none held in advance | Calm | Costs ×8 | Shocks ×2 | Shocks ×4 |
|---|---|---|---|---|
| Hourly epochs, peak | \$0.26 M | \$0.26 M | \$0.55 M | \$1.12 M |
| Hourly epochs, mean | \$0.01 M | \$0.01 M | \$0.04 M | \$0.10 M |
| Daily epochs, peak | \$1.44 M | \$1.44 M | \$4.07 M | \$10.39 M |
| Keeps the pool rebalanced | yes | yes | yes | yes |

*Table 27. Bonds prepaid at par (10), sized to hold each arbitrageur's fee within 0.1 bp of $f_{\min}$; LPs' worst-case gain \$5.04 M. Charges beyond a bond: \$0.02 M over six months in the cost scenarios and \$0.88 M under shocks ×4 (at most \$0.25 M in one epoch); none at $s$ = 0.5, for twice the bond, and \$27.7 M at $s$ = 4.*

| Supply of REP, calm markets | Keeps the pool rebalanced | LPs' gain | Note |
|---|---|---|---|
| Initial \$0.91 M and rebates only, charges burning REP | no | \$3.6–4.1 M | supply exhausted within days; $m$ rises to 39–50 bp |
| Prepayment at par | yes | \$5.24 M | — |
| Prepayment with a 1% markup | no | \$5.23 M | users' staleness +0.6 bp |
| Prepayment with a 2.5% markup | no | \$4.86 M | users' staleness +2.4 bp |

*Table 28. Where arbitrageurs' REP comes from. Charges burn \$4.24 M of REP over six months in calm markets and \$114 M under shocks ×4, against \$0.30–1.31 M of rebates; a markup takes \$0.04–0.15 M for the reserve and costs LPs \$0.4–1.2 M of recapture.*

| Redemption and initial issuance | Result |
|---|---|
| Account's REP locked while any settlement is pending | only charges beyond the bond escape, as without redemption |
| Fixed exit delay, hourly epochs: one hour / two hours | 2% of charges escape / none |
| Fixed exit delay after a keeper outage of a day | needs more than 25 hours |
| Initial issuance of \$1 M consumed by charges, calm / shocks ×4 | about 20 days / within hours |
| Initial issuance of \$5 M, calm / shocks ×4 | lasts the six months / 1.6 days |
| Initial issuance without backing | LPs lose nearly its face value as it is burned |

*Table 29. Redemption at par (10) and the initial issuance (`results/study_i/redeem.json`, `results/rep_bootstrap.json`).*

**K.5 Collateral.**

| Charge per trade and its collection | Value |
|---|---|
| Median / 99.9th percentile / maximum | 0.17 bp / 21 bp / 358 bp |
| Share of all charges on trades above 50 bp | 27% |
| Collected by parking (9) alone | 70–90% |
| Parking keyed to trade size, correction split ten ways | half its collection lost |

*Table 30. Collateral. The account's remaining stake and the reserve collect what parking does not; parking keyed to the in-block price move resists splitting.*

**K.6 Oracle error.**

| Oracle error | Effect |
|---|---|
| Overcharge on benign flow, degraded oracle | below 0.3 bp |
| Tolerance $\varepsilon \approx \max(\lvert\text{bias}\rvert, 2\sigma_o)$ | removes most unjustified charges at about 8% of recapture per basis point |
| Charging against a price one second off the decision instant, Arbitrum | halves recapture (Appendix I) |

*Table 31. Oracle error (Figure 9 in Appendix B); $\sigma_o$ is the standard deviation of the oracle's random error.*

**K.7 Settlement cost and keeper economics.**

| Settlement | Gas or result |
|---|---|
| Hook overhead on a v4 swap | 17,112 gas |
| Keeper's epoch | 26,000 gas + 14,300 per account |
| Self-settlement | 46,000 gas + 6,000 per swap |
| Settlement against batch-signed prices, hourly, relative to execution | 0.18× |
| With a succinct proof | 0.14–0.15× |
| Gas tank shared by seven mainnet pools, daily epochs | solvent at 2.3 k gas per swap, 1.2% of a swap's gas |
| Accounts that settle themselves / keeper race settlement time | 2–8% / within 1.3 minutes |

*Table 32. Settlement (Appendix D, Figures 13–14).*
