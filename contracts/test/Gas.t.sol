// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Test} from "forge-std/Test.sol";
import {RecordNoop, RecordStore, RecordEvent, RecordChain} from "../src/Recorders.sol";
import {Reconciler} from "../src/Reconciler.sol";

/// Study G3/G4 gas. Run with `forge test --isolate --gas-report`: every
/// external call from the test executes as its own transaction (cold storage,
/// intrinsic 21k, calldata), so the per-function gas report is what a real
/// hook / reconciler transaction pays. Reconcile batches use distinct
/// contracts per size so each size appears as its own row (ReconcilerN*).
contract GasTest is Test {
    uint160 constant P0 = 3543191142285914205922034323214; // ~ETH/USDC 2000, sqrtPriceX96
    uint128 constant LIQ = 2e18;
    uint256 constant FEE = 5e14; // 5bp
    uint256 constant M = 2e14; // 2bp allowance

    function _rec(uint256 i) internal pure returns (uint160 pre, uint160 post, address sender) {
        pre = P0 + uint160(i * 1e24);
        post = pre + 3e27; // ~ a few bp move
        sender = address(uint160(0xA000 + (i % 7)));
    }

    function test_record_variants() public {
        RecordStore s = new RecordStore();
        RecordEvent e = new RecordEvent();
        RecordChain c = new RecordChain();
        RecordNoop z = new RecordNoop();
        for (uint256 i; i < 20; ++i) {
            (uint160 pre, uint160 post, address snd) = _rec(i);
            z.record(pre, post, LIQ, snd);
            s.record(pre, post, LIQ, snd);
            e.record(pre, post, LIQ, snd);
            c.record(pre, post, LIQ, snd);
        }
        assertEq(c.count(), 20);
    }

    function _batch(uint256 n, uint256 start) internal pure returns (Reconciler.Rec[] memory recs, bytes32 head) {
        recs = new Reconciler.Rec[](n);
        for (uint256 i; i < n; ++i) {
            (uint160 pre, uint160 post, address snd) = _rec(start + i);
            recs[i] = Reconciler.Rec(pre, post, LIQ, snd, uint64(1));
        }
        head = bytes32(0);
        for (uint256 i; i < n; ++i) {
            Reconciler.Rec memory r = recs[i];
            head = keccak256(abi.encodePacked(head, r.pre, r.post, r.liq, r.sender, r.blk));
        }
    }

    function _run(uint256 n) internal {
        Reconciler r = new Reconciler(1e30);
        for (uint256 a; a < 7; ++a) r.fund(address(uint160(0xA000 + a)), 1e24);
        (Reconciler.Rec[] memory recs, bytes32 head) = _batch(n, 0);
        r.reconcile(recs, head, 2002e18, FEE, M);
        assertGt(r.recaptured(), 0, "charges must be levied");
    }

    function test_reconcile_n001() public { _run(1); }
    function test_reconcile_n010() public { _run(10); }
    function test_reconcile_n050() public { _run(50); }
    function test_reconcile_n200() public { _run(200); }
}
