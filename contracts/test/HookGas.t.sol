// SPDX-License-Identifier: AGPL-3.0-only
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {Deployers} from "v4-core/test/utils/Deployers.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {Hooks} from "v4-core/src/libraries/Hooks.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {Currency} from "v4-core/src/types/Currency.sol";

/// Study G phase 2: gas of a swap on a real v4 PoolManager without a hook,
/// with the event hook and with the rolling-hash hook. Run each test_swap_*
/// alone with `forge test --isolate --gas-report --mt test_swap_<pool>`: every
/// swap is its own transaction, so storage is cold AND storage writes are
/// priced against the slot's value at transaction start (vm.cool alone does
/// not reset that, which makes repeated writes look cheap). The median
/// PoolSwapTest.swap gas difference to the hookless pool is the hook's real
/// overhead, including PoolManager's hook dispatch. test_hook_overhead keeps
/// the single-transaction vm.cool estimate for comparison.
contract HookGasTest is Test, Deployers {
    PoolKey kNone;
    PoolKey kEvent;
    PoolKey kChain;
    address hEvent = address(uint160(Hooks.AFTER_SWAP_FLAG) | (uint160(0x4444) << 144));
    address hChain = address(uint160(Hooks.AFTER_SWAP_FLAG) | (uint160(0x5555) << 144));

    function setUp() public {
        deployFreshManagerAndRouters();
        deployMintAndApprove2Currencies();
        deployCodeTo("RepHook.sol:RepHookEvent", abi.encode(manager), hEvent);
        deployCodeTo("RepHook.sol:RepHookChain", abi.encode(manager), hChain);
        (kNone,) = initPoolAndAddLiquidity(currency0, currency1, IHooks(address(0)), 500, SQRT_PRICE_1_1);
        (kEvent,) = initPoolAndAddLiquidity(currency0, currency1, IHooks(hEvent), 500, SQRT_PRICE_1_1);
        (kChain,) = initPoolAndAddLiquidity(currency0, currency1, IHooks(hChain), 500, SQRT_PRICE_1_1);
        // warm-up: first swap in each pool initialises tick/fee-growth slots
        swap(kNone, true, -1e14, ZERO_BYTES);
        swap(kEvent, true, -1e14, ZERO_BYTES);
        swap(kChain, true, -1e14, ZERO_BYTES);
    }

    function _cool(address hook) internal {
        vm.cool(address(manager));
        vm.cool(address(swapRouter));
        vm.cool(Currency.unwrap(currency0));
        vm.cool(Currency.unwrap(currency1));
        if (hook != address(0)) vm.cool(hook);
    }

    function _measure(PoolKey memory k, address hook, uint256 n) internal returns (uint256 avg) {
        uint256 tot;
        for (uint256 i; i < n; ++i) {
            _cool(hook);
            bool z = i % 2 == 0;
            uint256 g = gasleft();
            swap(k, z, -1e15, ZERO_BYTES);
            tot += g - gasleft();
        }
        avg = tot / n;
    }

    function test_hook_overhead() public {
        uint256 n = 20;
        uint256 none = _measure(kNone, address(0), n);
        uint256 ev = _measure(kEvent, hEvent, n);
        uint256 ch = _measure(kChain, hChain, n);
        emit log_named_uint("v4 swap, no hook (gas)", none);
        emit log_named_uint("v4 swap, event hook (gas)", ev);
        emit log_named_uint("v4 swap, rolling-hash hook (gas)", ch);
        emit log_named_uint("hook overhead, event (gas)", ev - none);
        emit log_named_uint("hook overhead, rolling hash (gas)", ch - none);
    }

    function _swaps(PoolKey memory k) internal {
        for (uint256 i; i < 20; ++i) swap(k, i % 2 == 0, -1e15, ZERO_BYTES);
    }

    function test_swap_none() public { _swaps(kNone); }
    function test_swap_event() public { _swaps(kEvent); }
    function test_swap_chain() public { _swaps(kChain); }
}
