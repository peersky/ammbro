// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {Deployers} from "v4-core/test/utils/Deployers.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {Hooks} from "v4-core/src/libraries/Hooks.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {BalanceDelta} from "v4-core/src/types/BalanceDelta.sol";
import {StateLibrary} from "v4-core/src/libraries/StateLibrary.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {RepHookAccount} from "../src/RepHookAccount.sol";

/// Study G-park: execution-time parking + per-account record (swap gas vs a
/// hookless pool), self-settlement of 1/10/50 pending swaps, and keeper epoch
/// application for 10/100/400 accounts (and an all-skipped epoch).
/// Run each test alone: forge test --isolate --gas-report --json --mt <name>
contract ParkTest is Test, Deployers {
    using StateLibrary for IPoolManager;

    RepHookAccount hook;
    PoolKey kPark;
    PoolKey kNone;
    uint256 constant PK = 0xA11CE; // price entity's test key
    address signer;
    mapping(address => RepHookAccount.Rec[]) recs;

    function setUp() public {
        deployFreshManagerAndRouters();
        deployMintAndApprove2Currencies();
        signer = vm.addr(PK);
        // real CREATE2 deployment (so the gas report tracks it): mine a salt whose
        // address carries exactly the afterSwap permission bits
        bytes memory init = abi.encodePacked(type(RepHookAccount).creationCode,
            abi.encode(manager, uint256(5e14), uint256(1e18), signer, uint256(5e14), uint256(2e14)));
        bytes32 ih = keccak256(init);
        uint160 mask = uint160((1 << 14) - 1);
        bytes32 salt;
        for (uint256 i;; ++i) {
            address a = vm.computeCreate2Address(bytes32(i), ih, address(this));
            if (uint160(a) & mask == Hooks.AFTER_SWAP_FLAG) { salt = bytes32(i); break; }
        }
        hook = new RepHookAccount{salt: salt}(manager, 5e14, 1e18, signer, 5e14, 2e14);
        (kPark,) = initPoolAndAddLiquidity(currency0, currency1, IHooks(address(hook)), 500, SQRT_PRICE_1_1);
        (kNone,) = initPoolAndAddLiquidity(currency0, currency1, IHooks(address(0)), 500, SQRT_PRICE_1_1);
        swap(kNone, true, -1e14, ZERO_BYTES); // warm the baseline pool's tick state too
    }

    function _acct(uint256 i) internal pure returns (address) {
        return address(uint160(0xB0000 + i));
    }

    /// one swap whose tx.origin is `a`; record it exactly as the hook does
    function _swapAs(address a, bool zeroForOne) internal {
        vm.prank(address(this), a);
        BalanceDelta d = swap(kPark, zeroForOne, -1e15, ZERO_BYTES);
        (uint160 sqrtP,,,) = manager.getSlot0(kPark.toId());
        recs[a].push(RepHookAccount.Rec(sqrtP, manager.getLiquidity(kPark.toId()), BalanceDelta.unwrap(d), uint64(block.number)));
    }

    function _fund(uint256 n) internal {
        for (uint256 i; i < n; ++i) {
            hook.deposit(_acct(i), 1e24);
            _swapAs(_acct(i), i % 2 == 0); // every account has a non-empty chain (steady state)
        }
    }

    // --- execution: swap gas with parking + record vs hookless ---
    function test_park_swap() public {
        _fund(7);
        for (uint256 i; i < 20; ++i) _swapAs(_acct(i % 7), i % 2 == 0);
    }

    function test_park_baseline() public {
        for (uint256 i; i < 20; ++i) swap(kNone, i % 2 == 0, -1e15, ZERO_BYTES);
    }

    // --- self-settlement ---
    /// settle everything `a` has pending (records since its last settlement)
    function _settleAll(address a) internal {
        uint256[] memory prices = new uint256[](1);
        prices[0] = 1.002e18; // oracle 20bp from the pool: charges are levied
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(PK, keccak256(abi.encodePacked(uint64(block.number), prices)));
        RepHookAccount.Rec[] memory rr = recs[a];
        vm.prank(a);
        hook.selfSettle(rr, uint64(block.number), prices, v, r, s);
        delete recs[a];
    }

    /// first settlement (fresh settledHead slot) then a steady-state one of n
    /// swaps; the gas report's min is the steady state, max the first time
    function _selfSettle(uint256 n) internal {
        _fund(1);
        address a = _acct(0);
        _settleAll(a);
        for (uint256 i; i < n; ++i) _swapAs(a, i % 2 == 0);
        _settleAll(a);
        (, uint96 inFlight,, uint32 settled) = hook.accounts(a);
        assertEq(inFlight, 0);
        assertEq(settled, n + 1);
    }

    function test_self_n001() public { _selfSettle(1); }
    function test_self_n010() public { _selfSettle(10); }
    function test_self_n050() public { _selfSettle(50); }

    // --- keeper epoch application for n accounts (steady state: every account
    // has settled before, so its settledHead slot is already non-zero) ---
    function _entries(uint256 n) internal view returns (RepHookAccount.Entry[] memory es) {
        es = new RepHookAccount.Entry[](n);
        for (uint256 i; i < n; ++i) {
            address a = _acct(i);
            (, uint96 inFlight, uint32 seq, uint32 settled) = hook.accounts(a);
            es[i] = RepHookAccount.Entry(a, settled, seq, 1e12, inFlight, hook.chainHead(a));
        }
    }

    function _primeAll(uint256 n) internal {
        _fund(n);
        for (uint256 i; i < n; ++i) _settleAll(_acct(i));
        for (uint256 i; i < n; ++i) _swapAs(_acct(i), i % 2 == 1);
    }

    function _epoch(uint256 n) internal {
        _primeAll(n);
        assertEq(hook.applyEpoch(_entries(n)), n);
    }

    function test_epoch_n0010() public { _epoch(10); }
    function test_epoch_n0100() public { _epoch(100); }
    function test_epoch_n0400() public { _epoch(400); }

    function test_epoch_skip_n0100() public {
        _primeAll(100);
        RepHookAccount.Entry[] memory es = _entries(100);
        for (uint256 i; i < 100; ++i) es[i].fromSeq += 1; // as if every account had self-settled
        assertEq(hook.applyEpoch(es), 0);
    }
}
