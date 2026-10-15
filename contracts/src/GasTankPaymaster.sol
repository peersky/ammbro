// SPDX-License-Identifier: AGPL-3.0-only
pragma solidity 0.8.26;

import {BasePaymaster} from "account-abstraction/core/BasePaymaster.sol";
import {IEntryPoint} from "account-abstraction/interfaces/IEntryPoint.sol";
import {PackedUserOperation} from "account-abstraction/interfaces/PackedUserOperation.sol";
import {SimpleAccount} from "account-abstraction/samples/SimpleAccount.sol";

/// Study G-aa — the gas tank as an ERC-4337 paymaster (docs/settlement-keepers.md §5).
/// Sponsors a keeper's UserOp only if it calls `settlement` through the
/// account's execute(), with a selector on the allow-list; the tank (this
/// paymaster's EntryPoint deposit) is funded by swappers' gas withholding.
contract GasTankPaymaster is BasePaymaster {
    address public immutable settlement;
    bytes4 public immutable allowed;

    constructor(IEntryPoint ep, address settlement_, bytes4 allowed_) BasePaymaster(ep) {
        settlement = settlement_;
        allowed = allowed_;
    }

    function _validatePaymasterUserOp(PackedUserOperation calldata op, bytes32, uint256)
        internal
        view
        override
        returns (bytes memory, uint256)
    {
        require(bytes4(op.callData[:4]) == SimpleAccount.execute.selector, "not execute");
        (address dest,, bytes memory inner) = abi.decode(op.callData[4:], (address, uint256, bytes));
        require(dest == settlement, "not settlement");
        bytes4 sel;
        assembly { sel := mload(add(inner, 32)) }
        require(sel == allowed, "selector");
        return ("", 0);
    }
}

/// Stand-in for the settlement contract's applyEpoch: one account-slot
/// read-modify-write per entry (the measured 14.3k/account path's storage
/// pattern). Identical work on both paths, so the difference is 4337 overhead.
contract EpochSink {
    mapping(address => uint256) public slot;

    function applyEpoch(address[] calldata accounts, uint256[] calldata burns) external {
        for (uint256 i; i < accounts.length; ++i) {
            slot[accounts[i]] = slot[accounts[i]] + burns[i] + 1;
        }
    }
}
