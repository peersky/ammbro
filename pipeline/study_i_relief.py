"""Study I follow-up: proven-stale relief without arbitrage stake (paper §4.4, §5.4).

No arbitrageur holds REP (no appointed arbitrageurs, no premium mint). Each correction
either pays f_max unstaked, keeping its edge, or — while relief is on — attaches a
signed report proving the pool's last price deviated from the oracle and uses one of:
  full     flat fee f_min, no charge (the pool behaves as plain Uniswap)
  clear    flat fee clamp(g − m − η, f_q, f_max)
  steep    flat fee, logistic discount growing with the gap, centred mid-window [f_q + m, f_max + m]
  reverse  flat fee, logistic discount shrinking with the gap
  sync     pays f_min and settles the per-unit charge (3b) at execution against the report
  hyst     hysteresis in g: discount on once the proven gap reaches f_min + ε + d_on, kept on
           while the gap closes, off once back within f_min; level full (fee f_min) or frozen
           (clearing fee at switch-on)
Flat fees are recomputed at each swap from the gap left (successive swaps step a large gap down).
Relief switches on when a block ends outside f + m + ε and off after the pool has stayed
within f + m for hold_s seconds (hysteresis); hold = ∞ keeps the lane always open.

    AMMBRO_CHAIN=<chain> uv run python -m pipeline.study_i_relief   → results/[<chain>/]study_i/relief.json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

INF = 1e18


def ctl() -> str:
    return "ctl_red4" if ACTIVE.ordering == "fcfs" else "ctl_feasible"


def variants() -> list:
    v = [{"mode": "full", "fmax": 500e-4, "hold_s": INF},
         {"mode": "clear", "fmax": 500e-4, "hold_s": INF, "eta": 0.0},
         {"mode": "reverse", "fmax": 500e-4, "hold_s": INF},
         {"mode": "steep", "fmax": 500e-4, "hold_s": INF},
         {"mode": "sync", "fmax": 500e-4, "hold_s": 3600}]
    for f in (500e-4, 2000e-4):
        for gfrac in (0.24, 0.12, 0.0):
            v.append({"mode": "sync", "fmax": f, "hold_s": INF, "proof_gas_frac": gfrac})
    v.append({"mode": "sync", "fmax": 500e-4, "hold_s": INF, "lag_s": 1.0})
    for lvl in ("full", "frozen"):
        for don in (2e-4, 5e-4):
            v.append({"mode": "hyst", "fmax": 500e-4, "hold_s": INF, "d_on": don, "level": lvl})
    return v


def main() -> dict:
    c = ctl()
    runs = []
    for sc in I.SCENARIOS:
        b = ("marginal_cap", c, sc, 0.0, "open", False, 0.0)
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {}))
        runs.append(b + ({"stale_rule": "outcome"},))
        runs.append(b + ({"stake": 0.0, "fmax": 500e-4},))          # no stake, no relief
        for rv in variants():
            runs.append(b + ({"relief": rv},))
    res = I.main(runs)
    today = {r["scenario"]: r for r in res if r["rule"] == "today"}
    rows = []
    for r in res:
        if r["rule"] == "today":
            continue
        t = today[r["scenario"]]; st = r["stake"]
        rl = st.get("relief")
        rows.append({
            "scenario": r["scenario"], "controller": c,
            "variant": "covered (reference)" if (st["usd"] is None and rl is None) else ("no stake, no relief" if rl is None else
                        rl["mode"] + (f"/{rl['level']}/d_on={rl['d_on']*1e4:g}bp" if rl["mode"] == "hyst" else "")),
            "fmax_bps": round(rl["fmax"] * 1e4) if rl else (st["fmax_bps"] if st["usd"] is not None else None),
            "hold_s": None if not rl else ("inf" if rl["hold_s"] >= INF else rl["hold_s"]),
            "proof_gas_frac": rl.get("proof_gas_frac", 0.24) if rl else None, "lag_s": rl.get("lag_s", 0.0) if rl else None,
            "eta_bps": round(rl.get("eta", 0.0) * 1e4, 2) if rl else None,
            "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
            "builder_payments_m": r["builder_payments_m"],
            "keeps_rebalanced": I.keeps_rebalanced(r, t),
            "rebalanced_block_share": r["rebalanced_block_share"], "today_rebalanced_share": t["rebalanced_block_share"],
            "user_staleness_bps": r["user_pretrade_staleness_bps_vw"], "today_user_staleness_bps": t["user_pretrade_staleness_bps_vw"],
            "uncorrected_hours": r["uncorrected_hours"],
            "relief_trades": st.get("relief_trades", 0), "unstaked_trades": r["unstaked"]["trades"],
            "relief_on_share": round(st.get("relief_on_blocks", 0) / max(r.get("correctable_blocks", 1), 1), 4) if rl else None,
        })
    out = {"chain": ACTIVE.name, "controller": c, "rows": rows}
    (I.OUT / "relief.json").write_text(json.dumps(out, indent=1))
    for row in rows:
        print(row)
    return out


if __name__ == "__main__":
    main()
