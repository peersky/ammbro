# contracts — hook and settlement gas (Study G)

Foundry benchmarks behind the paper's gas figures (§5.8, Appendix D). They measure cost, not
production readiness: the contracts implement only what each measurement needs.

| Contract | What it measures |
|---|---|
| `src/RepHook.sol` | the swap hook on a real Uniswap v4 PoolManager: one `afterSwap` record per swap (`test/HookGas.t.sol`) |
| `src/Recorders.sol` | three ways a hook can leave the record reconciliation needs (`test/Gas.t.sol`) |
| `src/Reconciler.sol` | reconciling a batch of swaps against one oracle report in closed form (`test/Gas.t.sol`) |
| `src/RepHookAccount.sol` | parking, self-settlement and keeper epochs per account (`test/Park.t.sol`) |
| `src/GasTankPaymaster.sol` | the gas tank as an ERC-4337 paymaster for keepers (`test/AaGas.t.sol`) |

Oracle report verification is measured on the deployed Chainlink verifier from real transactions
(`pipeline/study_g.py`), and Groth16 proof verification in [`../zk`](../zk).

## Run

Dependencies are not vendored. The measurements used forge-std v1.17.0, account-abstraction v0.7.0
(EntryPoint v0.7), and Uniswap v4-core and v4-periphery at package versions 1.0.2 and 1.0.4, the
`main` branches at the time (neither repository tags these versions):

```sh
cd contracts
forge install --no-git foundry-rs/forge-std@v1.17.0 eth-infinitism/account-abstraction@v0.7.0 \
  Uniswap/v4-core Uniswap/v4-periphery
forge test --isolate --gas-report
```

`pipeline/study_g.py` runs the individual tests (`--mt`) and writes the medians to
`results/study_g/measured.json`.
