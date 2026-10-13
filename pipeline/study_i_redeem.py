"""Study I: redeeming REP at par, and whether a redemption lets an arbitrageur escape its charges (paper §4.6–4.8).

REP is minted only by swaps (rebates, and declared prepayments at par) and is redeemable at par from
escrow. The risk is a corrector that trades, redeems its REP before the epoch's charges are settled, and
walks away. Three locking rules are compared on the simulated no-owned-stake run (bond leased so that
supply never binds, hourly and daily epochs):
  parked only   — only the stake parked per trade by (9) stays locked until settlement; the rest of the
                  account's REP can be redeemed at once, so charges beyond the parked stake escape;
  account lock  — no REP of an account with settlements pending can be redeemed; only charges beyond
                  the account's whole bond escape;
  fixed delay d — a redemption completes d after it is requested, whatever is pending; charges whose
                  settlement (epoch end plus a keeper lag) falls after that escape.
Then, offline, the REP flows with redemption: arbitrageurs redeem what they hold beyond the next epoch's
need and prepay again when short; escrow stays at P_int per unit outstanding.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.study_i_redeem → results/study_i/redeem.json
"""
from __future__ import annotations

import json

import numpy as np

from . import study_i as I
from .chains import ACTIVE

SCENARIOS = ("stable", "costs_x4", "costs_x8", "vol_x2", "vol_x4")
EPOCHS = {"hourly": 3600.0, "daily": 0.0}
DELAYS_MIN = [0, 15, 60, 120, 1440, 2880]
KEEPER_LAG_MIN = {"keeper 2 min": 2, "keeper outage 1 h": 60, "keeper outage 24 h": 1440}


def flows(L, C):
    """Arbitrageurs hold the epoch's bond plus its charges; they prepay at par when short and redeem
    what exceeds the next epoch's need. Returns prepaid, redeemed and the peak outstanding."""
    H = prepaid = redeemed = 0.0; peak = 0.0
    for t in range(len(L)):
        need = L[t] + C[t]
        if H < need:
            prepaid += need - H; H = need
        H -= C[t]
        nxt = L[t + 1] + C[t + 1] if t + 1 < len(L) else 0.0
        if H > nxt:
            redeemed += H - nxt; H = nxt
        peak = max(peak, H)
    return {"prepaid_m": round(prepaid / 1e6, 3), "redeemed_m": round(redeemed / 1e6, 3), "burned_m": round(float(C.sum()) / 1e6, 3),
            "peak_outstanding_m": round(peak / 1e6, 3)}


def main() -> dict:
    runs, cfg = [], []
    for sc in SCENARIOS:
        for ep_name, ep in EPOCHS.items():
            st = {"stake": 0.0, "alloc": "equal", "fmax": 500e-4, "lease": {"slack_bps": 0.1, "series": True, "park_k": 1.0}}
            if ep:
                st["stake_epoch_s"] = ep
            runs.append(("marginal_cap", "ctl_feasible", sc, 0.0, "open", False, 0.0, st)); cfg.append((sc, ep_name))
    res = I.main(runs, workers=6)
    rows = []
    for (sc, ep_name), r in zip(cfg, res):
        ls = r["lease"]
        ch = np.array(ls["charges_by_minutes_to_settlement_k"]) * 1e3
        tot = float(ch.sum())
        mins = np.arange(len(ch))
        delay = {}
        for lag_name, lag in KEEPER_LAG_MIN.items():
            for d in DELAYS_MIN:
                esc = float(ch[mins + lag > d].sum())
                delay[f"{lag_name}, delay {d} min"] = {"escaped_m": round(esc / 1e6, 3), "share": round(esc / tot, 4) if tot else 0.0}
        L = np.array(ls["per_epoch_lease_k"]) * 1e3; C = np.array(ls["per_epoch_charges_k"]) * 1e3
        rows.append({"scenario": sc, "epoch": ep_name, "charges_m": round(tot / 1e6, 3),
                     "parked_only_escaped_m": ls["charges_beyond_parked_m"], "parked_only_epoch_max_m": ls["charges_beyond_parked_epoch_max_m"],
                     "account_lock_escaped_m": ls["credit_total_m"], "account_lock_epoch_max_m": ls["credit_epoch_max_m"],
                     "fixed_delay": delay, "flows": flows(L, C)})
    out = {"chain": ACTIVE.name, "delays_min": DELAYS_MIN, "keeper_lag_min": KEEPER_LAG_MIN, "rows": rows}
    (I.OUT / "redeem.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for r in main()["rows"]:
        print(r["scenario"], r["epoch"], "| charges", r["charges_m"], "| parked only", r["parked_only_escaped_m"], r["parked_only_epoch_max_m"],
              "| account lock", r["account_lock_escaped_m"], r["account_lock_epoch_max_m"], "| flows", r["flows"])
        for k, v in r["fixed_delay"].items():
            if v["share"] > 0 or "delay 0 " in k:
                print("     ", k, v)
