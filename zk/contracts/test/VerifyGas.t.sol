// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {stdJson} from "forge-std/StdJson.sol";
import {SP1Verifier} from "@sp1-contracts/v6.0.0/SP1VerifierGroth16.sol";

/// Study G: on-chain gas of verifying one real SP1 Groth16 proof (the
/// template's fixture, produced by SP1 v6.0.0). Run with
/// `forge test --isolate --gas-report --mt test_verify_groth16`.
contract VerifyGasTest is Test {
    using stdJson for string;

    function test_verify_groth16() public {
        string memory json = vm.readFile(string.concat(vm.projectRoot(), "/src/fixtures/groth16-fixture.json"));
        bytes32 vkey = json.readBytes32(".vkey");
        bytes memory pv = json.readBytes(".publicValues");
        bytes memory proof = json.readBytes(".proof");
        SP1Verifier v = new SP1Verifier();
        v.verifyProof(vkey, pv, proof); // reverts if the proof is invalid
        emit log_named_uint("public values bytes", pv.length);
        emit log_named_uint("proof bytes", proof.length);
    }
}
