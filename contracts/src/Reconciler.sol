// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// Study G — post-block reconciliation of a batch of swaps against one oracle
/// report (paper §4.3, §4.5, §4.6). Per swap: re-hash the record (proves it
/// is the one the hook committed to, RecordChain), compute the extraction
/// beyond the job allowance in closed form, and debit the swapper's stake
/// (whole stake, then the per-pool reserve). Report signature verification
/// is measured separately on the real Chainlink VerifierProxy (pipeline/study_g.py).
contract Reconciler {
    struct Rec {
        uint160 pre;
        uint160 post;
        uint128 liq;
        address sender;
        uint64 blk;
    }

    uint256 internal constant Q96 = 2 ** 96;
    uint256 internal constant ONE = 1e18;

    bytes32 public settledHead; // last record hash already reconciled
    mapping(address => uint256) public stake; // REP stake per account (pool units)
    uint256 public reserve; // per-pool reserve, funded by the protocol take
    uint256 public recaptured; // total charge recaptured for LPs

    constructor(uint256 reserve_) {
        reserve = reserve_;
    }

    function fund(address a, uint256 amt) external {
        stake[a] += amt;
    }

    /// @param recs   the swaps since `settledHead`, in hook order
    /// @param head   the hook's current head; the batch must hash to it
    /// @param pOracle oracle price of token1 in token0, 1e18 fixed point,
    ///               already directional (bid or ask by the swap's side)
    /// @param fee    pool fee, 1e18 (5bp = 5e14)
    /// @param m      job allowance per unit, 1e18
    function reconcile(Rec[] calldata recs, bytes32 head, uint256 pOracle, uint256 fee, uint256 m) external {
        bytes32 h = settledHead;
        uint256 total;
        for (uint256 i; i < recs.length; ++i) {
            Rec calldata r = recs[i];
            h = keccak256(abi.encodePacked(h, r.pre, r.post, r.liq, r.sender, r.blk));
            uint256 c = charge(r.pre, r.post, r.liq, pOracle, fee, m);
            if (c != 0) {
                total += c;
                uint256 s = stake[r.sender];
                if (s >= c) {
                    stake[r.sender] = s - c;
                } else {
                    stake[r.sender] = 0;
                    reserve -= c - s; // only an exhausted account touches the reserve
                }
            }
        }
        require(h == head, "records do not match hook");
        settledHead = h;
        recaptured += total;
    }

    /// Extraction beyond the allowance for one swap inside one liquidity range,
    /// in token0. Edge at a pool price p is the relative gap to the oracle
    /// beyond the fee; along the swap it moves linearly from its pre-trade
    /// to its post-trade value, so ∫ max(edge − m, 0) dV is a clipped trapezoid.
    function charge(uint160 pre, uint160 post, uint128 liq, uint256 pOracle, uint256 fee, uint256 m)
        public
        pure
        returns (uint256)
    {
        if (pre == post) return 0;
        (uint256 lo, uint256 hi) = pre < post ? (uint256(pre), uint256(post)) : (uint256(post), uint256(pre));
        // token0 moved: L·Q96·(√hi − √lo)/(√hi·√lo)
        uint256 v = (uint256(liq) * Q96 / lo) * (hi - lo) / hi;
        uint256 e0 = _edge(pre, pOracle, fee);
        uint256 e1 = _edge(post, pOracle, fee);
        if (e0 <= m && e1 <= m) return 0;
        uint256 a = e0 > m ? e0 - m : 0;
        uint256 b = e1 > m ? e1 - m : 0;
        uint256 avg;
        if (a > 0 && b > 0) {
            avg = (a + b) / 2; // fully above the allowance
        } else {
            // crosses the allowance: only the part above it is charged
            uint256 top = a > b ? a : b;
            uint256 span = (e0 > e1 ? e0 - e1 : e1 - e0);
            avg = top * top / (2 * span);
        }
        return v * avg / ONE;
    }

    function _edge(uint160 sqrtP, uint256 pOracle, uint256 fee) internal pure returns (uint256) {
        uint256 p = (uint256(sqrtP) * uint256(sqrtP) / Q96) * ONE / Q96; // token1 per token0, 1e18
        uint256 gap = p > pOracle ? (p - pOracle) * ONE / pOracle : (pOracle - p) * ONE / pOracle;
        return gap > fee ? gap - fee : 0;
    }
}
