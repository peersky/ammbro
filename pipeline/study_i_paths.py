"""Study I: daily allowance paths of the final controllers for Figure 9 (paper §5.4).

Cost shock ×4 from June. Mainnet: decay without a signal against urgency measured by block position,
both under the position model; Arbitrum: blind decay against the K_d >= 4 sender rule.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_paths → results/[<chain>/]study_i/paths.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE
from .study_i_position import POS


def main() -> dict:
    if ACTIVE.ordering == "fcfs":
        ctls, st = {"blind decay": "ctl_feasible", "K_d >= 4": "ctl_red4"}, {}
    else:
        ctls, st = {"no signal": "ctl_feasible", "urgency by position": "ctl_urgm"}, {"position_model": POS}
    runs = [("marginal_cap", c, "costs_x4", 0.0, "open", False, 0.0, dict(st)) for c in ctls.values()]
    res = I.main(runs, workers=2)
    out = {"chain": ACTIVE.name, "scenario": "costs_x4",
           "paths": {k: [[d[0], d[1]] for d in r["daily"]] for k, r in zip(ctls, res)}}
    (I.OUT / "paths.json").write_text(json.dumps(out))
    return out


if __name__ == "__main__":
    main()
