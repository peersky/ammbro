"""Gaming the decision latency L: can arbitrageurs who delay their trades bias its re-estimation, and to what end?

L is estimated as the offset from the block timestamp that minimises the median fee-adjusted residual of
correcting swaps (toxic_top3), as the midpoint of a late-biased (last print) and an early-biased (next
print) profile (Study E). A share alpha of those correctors delays its trades by delta seconds in calm
periods, which shifts its residual curve by delta; the re-estimated L is the argmin of the mixed curve
(1 - alpha) c(t) + alpha c(t - delta), a first-order approximation of the median over the mixed population.
Its effect is read off the measured sweep of scoring outcomes over L (Study E latency_sweep_block_anchor),
with and without the operator's bracket [1.25, 1.75] s (A6), beyond which L may not move.

    uv run python -m pipeline.l_gaming → results/l_gaming.json
"""
from __future__ import annotations

import json

import numpy as np

from .config import RESULTS_DIR

ALPHAS = [0.1, 0.25, 0.5, 1.0]
DELTAS_S = [0.5, 1.0, 2.0, 4.0]
BRACKET = (1.25, 1.75)


def est(off, late, nxt, alpha, delta):
    def mix(c):
        shifted = np.interp(off - delta, off, c, left=c[0], right=c[-1])
        return (1 - alpha) * c + alpha * shifted
    a, b = off[np.argmin(mix(late))], off[np.argmin(mix(nxt))]
    return round(((a + b) / 2) / 0.25) * 0.25


def analyse() -> dict:
    e = json.loads((RESULTS_DIR / "study_e" / "metrics.json").read_text())
    off = np.array(e["decision_time_profile"]["offsets_s"], dtype=float)
    late = np.array(e["decision_time_profile"]["by_group"]["toxic_top3"]["curve_bps"], dtype=float)
    nxt = np.array(e["decision_time_profile_next_print"]["by_group"]["toxic_top3"]["curve_bps"], dtype=float)
    sw = e["latency_sweep_block_anchor"]
    Ls = np.array([r["L_s"] for r in sw]); cap = np.array([r["headline_delta_m"] for r in sw])
    lvr = np.array([r["gross_lvr_m"] for r in sw])
    L0 = est(off, late, nxt, 0.0, 0.0)
    f = lambda x, y: float(np.interp(x, Ls, y)) if x <= Ls[-1] else float(y[-1] + (y[-1] - y[-2]) / (Ls[-1] - Ls[-2]) * (x - Ls[-1]))
    rows = []
    for a in ALPHAS:
        for d in DELTAS_S:
            L1 = est(off, late, nxt, a, d)
            Lc = min(max(L1, BRACKET[0]), BRACKET[1])
            rows.append({"alpha": a, "delta_s": d, "L_estimated_s": L1, "L_within_bracket_s": Lc,
                         "recapture_change_pct": round(100 * (f(Lc, cap) / f(L0, cap) - 1), 2),
                         "measured_extraction_change_pct": round(100 * (f(Lc, lvr) / f(L0, lvr) - 1), 2),
                         "recapture_change_pct_unbounded": round(100 * (f(L1, cap) / f(L0, cap) - 1), 2)})
    out = {"L_honest_s": L0, "bracket_s": BRACKET, "sweep": sw, "rows": rows}
    (RESULTS_DIR / "l_gaming.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    o = analyse()
    print("honest L", o["L_honest_s"])
    for r in o["rows"]:
        print(r)
