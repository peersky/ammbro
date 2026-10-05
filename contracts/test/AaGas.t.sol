// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {EntryPoint} from "account-abstraction/core/EntryPoint.sol";
import {IEntryPoint} from "account-abstraction/interfaces/IEntryPoint.sol";
import {PackedUserOperation} from "account-abstraction/interfaces/PackedUserOperation.sol";
import {SimpleAccount} from "account-abstraction/samples/SimpleAccount.sol";
import {SimpleAccountFactory} from "account-abstraction/samples/SimpleAccountFactory.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";
import {GasTankPaymaster, EpochSink} from "../src/GasTankPaymaster.sol";

/// Study G-aa: keeper settlement sponsored by the gas tank through ERC-4337
/// (EntryPoint v0.7, SimpleAccount, GasTankPaymaster) vs the same call made
/// directly. Run each alone: forge test --isolate --gas-report --json --mt <name>
contract AaGasTest is Test {
    EntryPoint ep;
    SimpleAccount keeper;
    GasTankPaymaster pm;
    EpochSink sink;
    uint256 constant KEY = 0xBEEF;
    address bundler = address(0xB0B);

    function setUp() public {
        ep = new EntryPoint();
        sink = new EpochSink();
        SimpleAccountFactory fac = new SimpleAccountFactory(IEntryPoint(address(ep)));
        keeper = fac.createAccount(vm.addr(KEY), 0);
        pm = new GasTankPaymaster(IEntryPoint(address(ep)), address(sink), EpochSink.applyEpoch.selector);
        pm.deposit{value: 10 ether}();          // the tank
    }

    function _payload(uint256 n) internal pure returns (address[] memory a, uint256[] memory b) {
        a = new address[](n); b = new uint256[](n);
        for (uint256 i; i < n; ++i) { a[i] = address(uint160(0xC0000 + i)); b[i] = i + 1; }
    }

    function _warm(uint256 n) internal {
        (address[] memory a, uint256[] memory b) = _payload(n);
        sink.applyEpoch(a, b);                  // slots non-zero: steady state, like returning accounts
    }

    function _op(uint256 n) internal view returns (PackedUserOperation[] memory ops) {
        (address[] memory a, uint256[] memory b) = _payload(n);
        bytes memory inner = abi.encodeCall(EpochSink.applyEpoch, (a, b));
        PackedUserOperation memory op;
        op.sender = address(keeper);
        op.nonce = ep.getNonce(address(keeper), 0);
        op.callData = abi.encodeCall(SimpleAccount.execute, (address(sink), 0, inner));
        op.accountGasLimits = bytes32(uint256(200_000) << 128 | uint256(5_000_000));
        op.preVerificationGas = 60_000;
        op.gasFees = bytes32(uint256(1 gwei) << 128 | uint256(10 gwei));
        op.paymasterAndData = abi.encodePacked(address(pm), uint128(100_000), uint128(0));
        bytes32 h = MessageHashUtils.toEthSignedMessageHash(ep.getUserOpHash(op));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(KEY, h);
        op.signature = abi.encodePacked(r, s, v);
        ops = new PackedUserOperation[](1);
        ops[0] = op;
    }

    function _direct(uint256 n) internal { _warm(n); (address[] memory a, uint256[] memory b) = _payload(n); sink.applyEpoch(a, b); }

    function _aa(uint256 n) internal {
        _warm(n);
        PackedUserOperation[] memory ops = _op(n);
        vm.prank(bundler, bundler);
        ep.handleOps(ops, payable(bundler));
        assertEq(sink.slot(address(uint160(0xC0000))), 2 * 2 + 0);   // applied twice: warm-up + sponsored
    }

    function test_direct_n010() public { _direct(10); }
    function test_direct_n100() public { _direct(100); }
    function test_aa_n010() public { _aa(10); }
    function test_aa_n100() public { _aa(100); }
}
