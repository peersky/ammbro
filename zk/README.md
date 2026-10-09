# zk — Groth16 verification gas

Measures one number used by the paper: the on-chain gas of verifying a succinct proof of an epoch's
settlement (227,226 gas; paper §5.8 and Appendix D, design "keeper hourly, succinct proof").

`test/VerifyGas.t.sol` verifies one real SP1 v6.0.0 Groth16 proof, `src/fixtures/groth16-fixture.json`,
with the pinned `SP1VerifierGroth16` contract. Groth16 verification costs the same for any proven
program (fixed-size proof, pairing check), so the fixture is the proof produced by the SP1 project
template rather than by BRO-AMM's settlement logic. Off-chain proving cost is not measured here; the
keeper studies assume it (`OFFCHAIN_USD` in `pipeline/study_k4.py`).

## Run

```sh
cd zk
forge install            # dependencies pinned in foundry.lock (forge-std, sp1-contracts)
forge test --isolate --gas-report --mt test_verify_groth16
```

`pipeline/study_g.py` runs the same test and records the median gas of
`SP1Verifier.verifyProof(bytes32,bytes,bytes)` as `groth16_verify_tx` in `results/study_g/measured.json`.

The fixture and verifier come from Succinct's SP1 project template (MIT, see `LICENSE-MIT`).
