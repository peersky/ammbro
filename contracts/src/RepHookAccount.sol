// SPDX-License-Identifier: AGPL-3.0-only
pragma solidity 0.8.26;

import {BaseTestHooks} from "v4-core/src/test/BaseTestHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {PoolId} from "v4-core/src/types/PoolId.sol";
import {SwapParams} from "v4-core/src/types/PoolOperation.sol";
import {BalanceDelta, BalanceDeltaLibrary} from "v4-core/src/types/BalanceDelta.sol";
import {StateLibrary} from "v4-core/src/libraries/StateLibrary.sol";

/// Study G-park — the REP-AMM swap hook with the execution-time work the
/// design needs (paper §4.5, docs/settlement-keepers.md §2.2):
///   - parking lock ℓ·V with ℓ = ρ + k·Δ_block, Δ_block the pool's price move
///     so far in this block (one per-pool slot, rewritten on a block's first swap);
///   - collateral check: free stake (stake − inFlight) must cover the lock;
///   - per-account record chain extended in the account's own slots.
/// The swapper is tx.origin in this PoC (a router would pass it in hookData).
///
/// Settlement (docs/settlement-keepers.md §2.3) lives here because it writes
/// the same account state:
///   - selfSettle: the account settles ALL its pending swaps — records,
///     a price batch signed once by the price entity (one ecrecover), charges
///     computed on-chain in closed form (per-unit cap, P§4.3).
///   - applyEpoch: a keeper's proven list of (account, fromSeq, toSeq, burn,
///     release, headAtTo); entries already self-settled are skipped, not
///     reverted. Proof verification is measured separately (Groth16 verifier).
contract RepHookAccount is BaseTestHooks {
    using StateLibrary for IPoolManager;
    using BalanceDeltaLibrary for BalanceDelta;

    struct Account {
        uint96 stake; // REP stake, pool units
        uint96 inFlight; // parked for unsettled swaps
        uint32 seq; // swaps recorded
        uint32 settledSeq; // swaps settled
    }

    struct PoolBlock {
        uint64 blk; // block of the pool's last swap
        uint160 sqrtStart; // pool price at that block's first swap
    }

    IPoolManager public immutable manager;
    uint256 public immutable rhoE18; // base parking rate, 1e18
    uint256 public immutable kE18; // parking speed per unit of in-block move, 1e18

    mapping(address => Account) public accounts;
    mapping(address => bytes32) public chainHead;
    mapping(PoolId => PoolBlock) public poolBlock;
    mapping(address => bytes32) public settledHead;
    uint256 public lpCredit; // charges recaptured for LPs (pool units)
    address public immutable priceSigner;
    uint256 public immutable feeE18; // pool fee, 1e18
    uint256 public immutable mE18; // job allowance, 1e18

    struct Rec {
        uint160 sqrtP; // post-swap price
        uint128 liq;
        int256 delta; // BalanceDelta as recorded
        uint64 blk;
    }

    struct Entry {
        address account;
        uint32 fromSeq;
        uint32 toSeq;
        uint96 burn;
        uint96 release;
        bytes32 headAtTo;
    }

    error InsufficientStake();
    error BadRecords();
    error BadPrices();

    constructor(IPoolManager m, uint256 rho, uint256 k, address signer, uint256 fee, uint256 allowance) {
        manager = m;
        rhoE18 = rho;
        kE18 = k;
        priceSigner = signer;
        feeE18 = fee;
        mE18 = allowance;
    }

    /// prices[i] = oracle price (token1 per token0, 1e18) for block fromBlock + i,
    /// already directional per the record's side; one signature over the batch.
    function selfSettle(Rec[] calldata recs, uint64 fromBlock, uint256[] calldata prices, uint8 v, bytes32 r, bytes32 s)
        external
    {
        address who = msg.sender;
        Account memory acc = accounts[who];
        bytes32 h = _chain(settledHead[who], recs);
        if (h != chainHead[who] || acc.settledSeq + recs.length != acc.seq) revert BadRecords();
        if (ecrecover(keccak256(abi.encodePacked(fromBlock, prices)), v, r, s) != priceSigner) revert BadPrices();
        uint256 burn = _charges(recs, fromBlock, prices);
        if (burn > acc.stake) burn = acc.stake; // rest falls to the account's whole stake / reserve (P§4.5)
        acc.stake -= uint96(burn);
        acc.inFlight = 0;
        acc.settledSeq = acc.seq;
        accounts[who] = acc;
        settledHead[who] = h;
        lpCredit += burn;
    }

    function _chain(bytes32 h, Rec[] calldata recs) internal pure returns (bytes32) {
        for (uint256 i; i < recs.length; ++i) {
            Rec calldata x = recs[i];
            h = keccak256(abi.encodePacked(h, x.sqrtP, x.liq, x.delta, x.blk));
        }
        return h;
    }

    function _charges(Rec[] calldata recs, uint64 fromBlock, uint256[] calldata prices) internal view returns (uint256 burn) {
        for (uint256 i; i < recs.length; ++i) {
            burn += charge(recs[i], prices[recs[i].blk - fromBlock]);
        }
    }

    /// Keeper path: entries proven off-chain (proof checked by the caller's
    /// verifier — measured separately). Self-settled accounts are skipped.
    function applyEpoch(Entry[] calldata es) external returns (uint256 applied) {
        uint256 credit;
        for (uint256 i; i < es.length; ++i) {
            Entry calldata e = es[i];
            Account memory acc = accounts[e.account];
            if (acc.settledSeq != e.fromSeq || e.toSeq > acc.seq) continue; // skip, don't revert
            uint96 burn = e.burn > acc.stake ? acc.stake : e.burn;
            acc.stake -= burn;
            acc.inFlight = e.release > acc.inFlight ? 0 : acc.inFlight - e.release;
            acc.settledSeq = e.toSeq;
            accounts[e.account] = acc;
            settledHead[e.account] = e.headAtTo;
            credit += burn;
            ++applied;
        }
        lpCredit += credit;
    }

    /// Extraction beyond the allowance for one swap inside one liquidity range,
    /// token0 units (closed form as in Reconciler.charge; pre-swap price from
    /// the swap's token1 delta: Δ√P = Δy·Q96/L).
    function charge(Rec calldata x, uint256 pOracle) public view returns (uint256) {
        int128 d1 = int128(x.delta);
        uint256 dy = uint256(uint128(d1 < 0 ? -d1 : d1));
        uint256 dsq = dy * (1 << 96) / x.liq;
        uint256 pre = d1 < 0 ? uint256(x.sqrtP) - dsq : uint256(x.sqrtP) + dsq;
        (uint256 lo, uint256 hi) = pre < x.sqrtP ? (pre, uint256(x.sqrtP)) : (uint256(x.sqrtP), pre);
        if (lo == hi) return 0;
        uint256 vol = (uint256(x.liq) * (1 << 96) / lo) * (hi - lo) / hi;
        uint256 e0 = _edge(pre, pOracle);
        uint256 e1 = _edge(x.sqrtP, pOracle);
        uint256 m = mE18;
        if (e0 <= m && e1 <= m) return 0;
        uint256 a0 = e0 > m ? e0 - m : 0;
        uint256 a1 = e1 > m ? e1 - m : 0;
        uint256 avg = (a0 > 0 && a1 > 0) ? (a0 + a1) / 2
            : (a0 > a1 ? a0 : a1) * (a0 > a1 ? a0 : a1) / (2 * (e0 > e1 ? e0 - e1 : e1 - e0));
        return vol * avg / 1e18;
    }

    function _edge(uint256 sqrtP, uint256 pOracle) internal view returns (uint256) {
        uint256 p = (sqrtP * sqrtP >> 96) * 1e18 >> 96;
        uint256 gap = p > pOracle ? (p - pOracle) * 1e18 / pOracle : (pOracle - p) * 1e18 / pOracle;
        return gap > feeE18 ? gap - feeE18 : 0;
    }

    /// ℓ·V with ℓ = ρ + k·Δ_block (relative in-block move since the block's first swap)
    function _lock(PoolId id, uint160 sqrtP, BalanceDelta delta) internal returns (uint256) {
        PoolBlock memory pb = poolBlock[id];
        if (pb.blk != block.number) {
            poolBlock[id] = PoolBlock(uint64(block.number), sqrtP);
            pb.sqrtStart = sqrtP;
        }
        uint256 a = sqrtP > pb.sqrtStart ? sqrtP - pb.sqrtStart : pb.sqrtStart - sqrtP;
        uint256 move = a * 2e18 / pb.sqrtStart; // dP/P ≈ 2·d√P/√P
        int128 d0 = delta.amount0();
        uint256 v = uint256(uint128(d0 < 0 ? -d0 : d0)); // notional in token0
        return v * (rhoE18 + kE18 * move / 1e18) / 1e18;
    }

    function _record(address who, uint256 lock, uint160 sqrtP, uint128 liq, BalanceDelta delta) internal {
        Account memory acc = accounts[who];
        if (uint256(acc.stake) < uint256(acc.inFlight) + lock) revert InsufficientStake();
        acc.inFlight += uint96(lock);
        acc.seq += 1;
        accounts[who] = acc;
        chainHead[who] = keccak256(abi.encodePacked(chainHead[who], sqrtP, liq, BalanceDelta.unwrap(delta), uint64(block.number)));
    }

    function deposit(address a, uint96 amt) external {
        accounts[a].stake += amt;
    }

    function afterSwap(address, PoolKey calldata key, SwapParams calldata, BalanceDelta delta, bytes calldata)
        external
        override
        returns (bytes4, int128)
    {
        PoolId id = key.toId();
        (uint160 sqrtP,,,) = manager.getSlot0(id);
        uint256 lock = _lock(id, sqrtP, delta);
        _record(tx.origin, lock, sqrtP, manager.getLiquidity(id), delta);
        return (this.afterSwap.selector, 0);
    }
}
