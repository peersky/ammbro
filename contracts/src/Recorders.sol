// SPDX-License-Identifier: AGPL-3.0-only
pragma solidity ^0.8.26;

/// Study G — three ways a swap hook can leave the record reconciliation needs.
/// Each `record` is what an afterSwap hook would run once per swap; gas is
/// measured per call as a separate transaction (`forge test --isolate`).
///
/// The record: pool price before and after the swap (sqrtPriceX96), the
/// active liquidity, the swapper, and the block. That is all the per-unit
/// cap charge needs (paper §4.3, §4.6).

/// (0) Baseline: same call, records nothing — its gas is the intrinsic cost
/// (21k, calldata, dispatch) that a hook inside a swap does not pay again.
contract RecordNoop {
    function record(uint160, uint160, uint128, address) external {}
}

/// (1) Full record in fresh storage: self-contained, on-chain readable.
contract RecordStore {
    struct Rec {
        uint160 pre;
        uint64 blk;
        uint160 post;
        uint128 liq;
        address sender;
    }

    mapping(uint256 => Rec) public recs;
    uint256 public n;

    function record(uint160 pre, uint160 post, uint128 liq, address sender) external {
        recs[n] = Rec(pre, uint64(block.number), post, liq, sender);
        unchecked {
            ++n;
        }
    }
}

/// (2) Event only: cheapest; reconciliation trusts the log and is challengeable
/// within the oracle's retention window (optimistic).
contract RecordEvent {
    event SwapRecord(uint160 pre, uint160 post, uint128 liq, address indexed sender, uint64 blk);

    function record(uint160 pre, uint160 post, uint128 liq, address sender) external {
        emit SwapRecord(pre, post, liq, sender, uint64(block.number));
    }
}

/// (3) Rolling hash: one storage slot per pool. Reconciliation supplies the
/// records as calldata and the reconciler re-hashes them, so a forged record
/// cannot be settled — no trust, one warm SSTORE per swap.
contract RecordChain {
    bytes32 public head;
    uint256 public count;

    function record(uint160 pre, uint160 post, uint128 liq, address sender) external {
        head = keccak256(abi.encodePacked(head, pre, post, liq, sender, uint64(block.number)));
        unchecked {
            ++count;
        }
    }
}
