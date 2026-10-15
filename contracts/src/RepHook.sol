// SPDX-License-Identifier: AGPL-3.0-only
pragma solidity 0.8.26;

import {BaseTestHooks} from "v4-core/src/test/BaseTestHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {PoolId} from "v4-core/src/types/PoolId.sol";
import {SwapParams} from "v4-core/src/types/PoolOperation.sol";
import {BalanceDelta} from "v4-core/src/types/BalanceDelta.sol";
import {StateLibrary} from "v4-core/src/libraries/StateLibrary.sol";

/// Study G phase 2 — the REP-AMM swap hook on a real Uniswap v4 PoolManager.
/// One afterSwap call per swap records what reconciliation needs: the
/// post-swap price, active liquidity, the swap's deltas and its sender. The
/// pre-swap price is the previous record's post-swap price (liquidity changes
/// do not move price), so a single hook call per swap suffices.
abstract contract RepHookBase is BaseTestHooks {
    using StateLibrary for IPoolManager;

    IPoolManager public immutable manager;

    constructor(IPoolManager m) {
        manager = m;
    }

    function afterSwap(address sender, PoolKey calldata key, SwapParams calldata, BalanceDelta delta, bytes calldata)
        external
        override
        returns (bytes4, int128)
    {
        PoolId id = key.toId();
        (uint160 sqrtP,,,) = manager.getSlot0(id);
        uint128 liq = manager.getLiquidity(id);
        _record(id, sqrtP, liq, BalanceDelta.unwrap(delta), sender);
        return (this.afterSwap.selector, 0);
    }

    function _record(PoolId id, uint160 sqrtP, uint128 liq, int256 delta, address sender) internal virtual;
}

/// Event only — reconciliation reads the log (optimistic, challengeable).
contract RepHookEvent is RepHookBase {
    event SwapRecord(PoolId indexed id, uint160 sqrtP, uint128 liq, int256 delta, address sender, uint64 blk);

    constructor(IPoolManager m) RepHookBase(m) {}

    function _record(PoolId id, uint160 sqrtP, uint128 liq, int256 delta, address sender) internal override {
        emit SwapRecord(id, sqrtP, liq, delta, sender, uint64(block.number));
    }
}

/// Rolling hash per pool — the reconciler re-hashes the records it is handed.
contract RepHookChain is RepHookBase {
    mapping(PoolId => bytes32) public head;

    constructor(IPoolManager m) RepHookBase(m) {}

    function _record(PoolId id, uint160 sqrtP, uint128 liq, int256 delta, address sender) internal override {
        head[id] = keccak256(abi.encodePacked(head[id], sqrtP, liq, delta, sender, uint64(block.number)));
    }
}
