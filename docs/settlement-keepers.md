# Settlement and keeper layer — design draft (2026-10-05)

Status: **design proposal**, not yet simulated or built. Measured inputs are
marked (M) with their source; everything else is a proposal or an estimate (E).
Builds on paper §4.3–§4.6, spec Study G (gas) and Study I (payout rule).

## 1. Problem

Every swap's charge (extraction beyond the job allowance, P§4.3) must be
settled against signed prices after the block: burn from the swapper's parked
stake, release the rest, credit LPs, mint/burn REP. Three forces pull on how
often and by whom:

- **Capacity.** Stake parked for an unsettled swap cannot back the next one.
  Heavy accounts need 2–5× more stake under hourly than per-block settlement
  (M, top-10 accounts at ρ = 5bp, peak window: mainnet median $2.0k vs $1.0k,
  max $11k vs $2.4k; Arbitrum $720 vs $110). The capital *cost* is negligible
  (~$0.06/h on $11k at 5%/yr); the *capacity* is not.
- **Gas.** A settlement transaction has a fixed part (signature/proof
  verification) and a per-account part (state writes); per-block settlement of
  everyone repeats the fixed part every block.
- **Liveness.** Someone must be paid to settle accounts that do not settle
  themselves, and the system must not stall if they stop.

## 2. Settlement design (proposed)

### 2.1 Price input
Assumption (author, 2026-10-05): a price entity publishes the full price batch
— directional bid/ask per block — **signed once per batch**, plus per-block
signed prices as they are produced. Verifying a batch is one signature (M:
55,879 gas for a Chainlink Data Streams report on mainnet, 62,544 / 37,544 on
Arbitrum; Study G).

### 2.2 Per-account record (hook)
The hook already writes the swapper's account slot at every swap for the
parking lock (P§4.5). In the same write it extends the account's own chain:

```
account = { stake, inFlight, seq, settledSeq, chainHead }
on swap : inFlight += ℓ·V ; seq += 1 ; chainHead = keccak(chainHead, rec)
rec     = (post sqrtP, active liquidity, Δ0, Δ1, block)
          pre-swap price = post − Δ/L inside one liquidity range
```

Each account's swaps form a complete, self-contained segment
`(settledSeq, seq]` that can be settled independently of other accounts.
Gas (M, G-park, `contracts/src/RepHookAccount.sol` on a real v4 PoolManager,
each swap its own transaction): **+17,112 gas per swap** over a hookless swap
(140,801 vs 123,689) for dispatch, price/liquidity reads, the in-block move
slot, the collateral check, the parking lock and the per-account record.

### 2.3 Two settlement paths, one pointer

| path | who | when | how | pays |
|---|---|---|---|---|
| **self-settle** | the account | any block after its swaps' prices are signed | submits its records + the signed price batch; charges computed on-chain (M: **46k + 6.0k per swap**, steady state; first-ever settlement +17k for a fresh slot) | the account (its own gas) |
| **keeper settle** | a keeper | at epoch end, everything still in flight | list of (account, fromSeq, toSeq, burn, release, head) applied on-chain (M: **26k + 14.3k per account**; skipped entry 4.4k), either computed on-chain from the records or proven off-chain (M: SP1 Groth16 verification **227,226 gas**) | the protocol take τ (§4) |

- **No double settlement:** both paths advance the same `settledSeq`.
- **Skip, don't revert:** a keeper entry whose `fromSeq ≠ settledSeq` (the
  account self-settled meanwhile) is skipped; pool totals are summed over the
  entries actually applied. Self-settling cannot grief the keeper's transaction.
- **Liveness tiers:** (1) keeper bounty escalates with delay; (2) after a
  deadline anyone may settle through the on-chain path (M: 0.3–0.6× execution
  gas); (3) flights still unsettled at the signed-data retention window are
  burned in full (P§4.6) — no account can leave its flights pending forever.

Why not keepers every block (E): a proof per block with swaps is ≈ 39M gas/h on
mainnet (≈ 40% of τ at 2.5%) and ≈ all of τ on Arbitrum, and a proof takes
minutes — longer than a block. Fast release therefore comes from accounts
settling themselves; keepers are the catch-all.

### 2.4 Settlement budget over the window (M, Study G `settlement_budget`)

All designs include the per-swap hook (17.1k); priced at each block's base fee.

| design | mainnet (× execution) | Arbitrum (× execution) |
|---|---|---|
| keeper on-chain, every block (Data Streams report per block) | $96.7k (0.72) | $21.2k (0.72) |
| **keeper on-chain, hourly, one signed price batch** | **$24.9k (0.18)** | **$5.7k (0.19)** |
| keeper zk, hourly, one Groth16 proof | $20.5k (0.14) | $4.3k (0.15) |
| every account self-settles hourly (on-chain) | $38.7k (0.28) | $6.8k (0.23) |
| *execution of the swaps themselves* | $148k | $30k |

**Finding.** With one signed price batch per epoch, zk saves only ~18% (mainnet)
to ~24% (Arbitrum) over settling the same epoch on-chain: the per-block report
verification it was meant to remove is already gone, and what remains — the
per-swap hook (~60% of the zk total) and the per-account writes — no proof can
remove. The simpler, lower-risk design (on-chain hourly settlement with a batch
signature, no prover, no trusted setup) is within ~20% of the zk design. zk
pays off with scale (the 6.0–6.4k per-swap on-chain charge computation goes)
and as a way for one keeper to settle many pools; it is not needed for
viability.

### 2.5 Proving workload (E, SP1 zkVM, one batch signature)
Per hourly epoch: one signature + keccak chain and charge per swap (~10k
cycles) + the account list. Mainnet ≈ 2M cycles (p99 7M), Arbitrum ≈ 8M (p99
60M) → seconds on a consumer GPU, minutes on a laptop CPU; the Groth16 wrap
(1–2 min, ~16 GB RAM) dominates. Verification on-chain ≈ 250–300k gas (E, to
measure). Proving is cheap; on-chain state writes are the cost.

(The earlier estimate of ~$7k / ~$4k for the zk design under-counted the
per-account write — measured 14.3k, not ~6k; the measured figures are in §2.4.)

## 3. Keeper market

### 3.1 Options

**(a) Open race.** Anyone proves; first valid proof takes an escalating
bounty. Permissionless and simple, but competing keepers prove the same epoch
in parallel — duplicated work that someone pays for, and race losers exit.

**(b) Designated leader per pool (proposed default).** For each pool and term
(e.g. a week) one keeper is the **settlement leader**, chosen by a reverse
auction: lowest fee per settled swap wins, subject to posting a performance
bond. The leader alone is paid in its term; if it misses an epoch deadline its
bond is slashed by a fixed amount and the epoch falls back to the open race
(option a), then to the on-chain path. Related: am-AMM (Adams et al. 2024)
auctions a pool's management rights; here the auctioned right is a duty, and
the bid is a price for it, not a payment for rent.

- Accountability: one party is responsible; liveness failure is attributable
  and costs its bond.
- Censorship: the leader cannot block anyone — accounts self-settle, and the
  open race / on-chain path take over after the deadline.
- No duplicated proving within a term.

**(c) Multi-pool proofs.** A leader may serve many pools with one proof per
epoch: verification is paid once, each pool adds only its root/total updates
(E: ~20–30k gas). This is what makes small pools serviceable (§3.2).

### 3.2 The small-pool problem
A keeper's fixed cost per epoch (proof verification ≈ 300k gas, plus
operations) does not shrink with the pool, but τ does. A pool recapturing
$1k over six months yields $25 at τ = 2.5% — less than one month of hourly
proof verification on mainnet even at 2026 gas prices. Without amortization
across pools, only large pools are served. Two levers: multi-pool proofs
(§3.1c) and paying keepers in a unit that is not tied to one small pool (§4).

## 4. Joint REP and proof of useful work (proposal, open)

### 4.1 Why per-pair REP alone does not pay keepers well
REP is per pair by design (P§4.4): a pair-native trading license whose value
is the discount it buys in *that* pool. Paying keepers in a small pool's REP
pays them in an illiquid asset whose value depends on that pool alone — the
same reason keepers would avoid small pools in cash terms.

### 4.2 A protocol-level work token (working name pREP)
- **Issued for verified work:** pREP is minted to the keeper whose proof
  settles swaps, per swap settled (or per account settled), across any pool.
  The work is *useful* by construction — each unit is a settlement the system
  needed, verified on-chain by the proof — hence **proof of useful work**:
  issuance tied to verified, non-duplicable work rather than to hash power
  (PoW) or capital (PoS). Each swap can be settled once (`settledSeq`), so the
  same work cannot be claimed twice.
- **Backed by income:** pREP is a claim on the pooled protocol take — the
  share of τ not needed for each pool's reserve — from *all* pools. Its value
  tracks aggregate protocol activity, so a keeper serving a small pool is paid
  in the same unit as one serving a large pool.
- **Self-funding invariant (as for REP):** pREP issuance in an epoch is bounded
  by the τ income that backs it; no unbacked minting.
- **Bond asset:** leaders post their performance bond in pREP, so a slashed
  bond burns claims on future protocol income.

### 4.3 Growth incentive: serving a pool early
A keeper that serves a new pool from inception bears its fixed cost while τ is
small. Proposal: the leader of a pool's first terms earns a **curator share** —
a small fraction of that pool's future τ, vesting over time and capped — so a
keeper choosing a pool in expectation of growth is paid if the growth happens.

Constraint (must hold, to study): the curator share must not reward wash
growth. Wash volume pays the pool fee `f` on every unit (and, if it corrects
the pool, the job charge); the incentive is safe if the curator's marginal
reward per unit of volume stays below `f` and the growth metric counts
**surplus actually recaptured from others** (fees and charges paid by
accounts other than the curator and its known affiliates), not raw volume.

### 4.4 Open questions
1. pREP valuation and reflexivity: a claim on future τ is equity-like; can
   pREP and REP together enter a death spiral (C2's question, one level up)?
2. Issuance rule: per swap, per account, or per unit of gas saved versus the
   on-chain path? Which is hardest to inflate with self-generated swaps?
3. Leader auction: term length, bond size vs the damage of a missed epoch,
   reserve price, collusion between leader and large accounts.
4. Curator share: rate, cap, vesting, wash-resistance proof.
5. Does a protocol-level token change the paper's claim that REP is
   counterparty-free and pair-native (title, abstract)? pREP would be a second
   asset; the paper must say so.
6. Regulatory framing of a token that claims protocol income — out of scope
   for the paper, but it must be acknowledged.

## 5. Studies needed (proposed order)

1. ✅ **G-park (measured, §2.2–2.4):** hook +17.1k/swap; self-settle 46k + 6.0k/swap;
   keeper epoch 26k + 14.3k/account; Groth16 verification 227k.
2. **K1 settlement economics (simulate, real data):** every account's swaps;
   each account chooses its self-settlement cadence (own gas vs stake freed);
   keepers settle the rest per epoch. Outputs: share of accounts/volume that
   self-settle, stake freed, keeper revenue vs cost per epoch (quiet hours, gas
   spikes), τ needed, settlement delay.
3. **K2 keeper market (simulate):** open race vs designated leader vs
   multi-pool; leader reverse auction with a keeper population of differing
   costs; missed-deadline and fallback dynamics; duplicated-work cost of the
   open race.
4. **K3 small pools and pREP (simulate):** a pool size distribution (needs
   data on smaller pools — e.g. the v3 0.30% and v4 ETH/USDC pools from the
   venue probe, other pairs); whether multi-pool proofs plus pREP keep small
   pools served; curator share vs wash-growth attack.
5. **ZK PoC (build):** SP1 guest settling a segment (one account) and an epoch
   (all accounts) with one batch signature; settlement contract with both
   paths and the skip rule; cycles, proving time, Groth16 verification gas.
