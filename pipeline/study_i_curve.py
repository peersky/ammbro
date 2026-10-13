"""Study I: a coverage curve that keeps staked arbitrage working through volatility, without the lane.

First pass: the exponential curve (2) with a steepness s, f = f_min + (f_max − f_min)·exp(−s·c), swept
over s for stake sized for normal markets (25 units) and thin stake (10 units). The power-law and
trailing-volume variants below are available through the `curve` setting for a second pass.

With the exponential curve on the epoch's own volume, stake sized for normal markets loses coverage
when volume spikes, the fee rises towards f_max and corrections stop (rep_loop.json). This tests two
changes to the curve (2), alone and together:
  power   f = f_min + (f_max − f_min)·(1 + c)^(−α), c = stake / (ρ·volume), α = 4.7 — about the
          exponential's fee at normal coverage, but a gentle rise when coverage falls;
  trail   coverage against the account's average daily volume over the last 30 epochs, so that a
          spike does not move the fee within the epoch.
Charges are collected from stake within each epoch (stake tops up between epochs); what stake cannot
cover is counted as uncovered and lost to LPs, so a gentler curve cannot hide a collateral shortfall.
Mainnet, decay without a signal (§5.5 convention), f_max = 500 bp, users' corrections uncharged.

    AMMBRO_CHAIN=mainnet uv run python -m pipeline.study_i_curve [scenario ...] → results/study_i/curve[_<scenarios>].json
"""
from __future__ import annotations

import json

from . import study_i as I
from .chains import ACTIVE

STEEPNESS = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
CURVES = {f"exponential, steepness {k:g}": {"steepness": k} for k in STEEPNESS}


def main(scenarios=("stable", "vol_x2", "vol_x4"), steepness=None) -> dict:
    curves = CURVES if steepness is None else {f"exponential, steepness {k:g}": {"steepness": k} for k in steepness}
    unit = json.loads((I.OUT / "stake.json").read_text())["stake_unit_usd"]
    c = "ctl_feasible"
    runs, cfg = [], []
    for sc in scenarios:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, "today", None))
        runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0, {"stale_rule": "outcome"})); cfg.append((sc, "fully staked", None))
        for name, cv in curves.items():
            runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0,
                         {"stake": 25 * unit, "alloc": "pooled", "fmax": 500e-4, "curve": cv, "collateral": True}))
            cfg.append((sc, name, 25))
        for name, cv in curves.items():
            runs.append(("marginal_cap", c, sc, 0.0, "open", False, 0.0,
                         {"stake": 10 * unit, "alloc": "pooled", "fmax": 500e-4, "curve": cv, "collateral": True}))
            cfg.append((sc, name, 10))
    res = I.main(runs, workers=6)
    today = {s: r for (s, d, _), r in zip(cfg, res) if d == "today"}
    rows = []
    for (s, d, k), r in zip(cfg, res):
        if d == "today":
            continue
        t = today[s]
        rows.append({"scenario": s, "curve": d, "stake_units": k, "lp_gain_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3),
                     "uncorrected_hours": r["uncorrected_hours"], "keeps_rebalanced": I.keeps_rebalanced(r, t),
                     "uncovered_charges_m": r["stake"]["uncovered_charges_m"], "m_end_bps": r.get("m_bps_final"),
                     "user_staleness_bps": r["user_pretrade_staleness_bps_vw"], "today_user_staleness_bps": t["user_pretrade_staleness_bps_vw"]})
    out = {"chain": ACTIVE.name, "stake_unit_usd": unit, "curves": curves, "rows": rows}
    tag = "" if steepness is None else "_s" + "_".join(f"{k:g}" for k in steepness)
    name = ("curve" if len(scenarios) == 3 else f"curve_{'_'.join(scenarios)}") + tag + ".json"
    (I.OUT / name).write_text(json.dumps(out, indent=1))
    return out


def epochs(scenarios=("stable", "vol_x2", "vol_x4")) -> dict:
    """Shorter settlement epochs: coverage and collateral reset hourly or every four hours instead of daily,
    with the current curve (s = 1), stake for normal markets (25 units) and thin stake (10 units)."""
    unit = json.loads((I.OUT / "stake.json").read_text())["stake_unit_usd"]
    runs, cfg = [], []
    for sc in scenarios:
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None, None))
        for ep in (3600.0, 4 * 3600.0):
            for units in (25, 10):
                runs.append(("marginal_cap", "ctl_feasible", sc, 0.0, "open", False, 0.0,
                             {"stake": units * unit, "alloc": "pooled", "fmax": 500e-4, "collateral": True, "stake_epoch_s": ep}))
                cfg.append((sc, ep, units))
    res = I.main(runs, workers=6)
    today = {c[0]: r for c, r in zip(cfg, res) if c[1] is None}
    rows = [{"scenario": c[0], "epoch_h": c[1] / 3600, "stake_units": c[2],
             "lp_gain_vs_today_m": round(r["lp_net_m"] - today[c[0]]["lp_net_m"], 3),
             "uncovered_charges_m": r["stake"]["uncovered_charges_m"], "uncorrected_hours": r["uncorrected_hours"],
             "keeps_rebalanced": I.keeps_rebalanced(r, today[c[0]])} for c, r in zip(cfg, res) if c[1] is not None]
    out = {"chain": ACTIVE.name, "stake_unit_usd": unit, "rows": rows}
    (I.OUT / f"curve_epochs_{'_'.join(scenarios)}.json").write_text(json.dumps(out, indent=1))
    return out


def thin() -> dict:
    """Collateral side: each arbitrageur holds its own thin stake (1 or 2 units in total, split equally),
    so a steep curve lets it trade near f_min on little collateral; charges beyond its own stake are
    uncovered."""
    unit = json.loads((I.OUT / "stake.json").read_text())["stake_unit_usd"]
    runs, cfg = [], []
    for sc in ("stable", "vol_x4"):
        runs.append(("today", None, sc, 0.0, "open", False, 0.0, {})); cfg.append((sc, None, None))
        for k in (1.0, 4.0, 8.0):
            for units in (1, 2):
                runs.append(("marginal_cap", "ctl_feasible", sc, 0.0, "open", False, 0.0,
                             {"stake": units * unit, "alloc": "equal", "fmax": 500e-4, "curve": {"steepness": k}, "collateral": True}))
                cfg.append((sc, k, units))
    res = I.main(runs, workers=6)
    today = {c[0]: r for c, r in zip(cfg, res) if c[1] is None}
    rows = [{"scenario": c[0], "steepness": c[1], "stake_units_total": c[2],
             "lp_gain_vs_today_m": round(r["lp_net_m"] - today[c[0]]["lp_net_m"], 3),
             "uncovered_charges_m": r["stake"]["uncovered_charges_m"], "uncorrected_hours": r["uncorrected_hours"],
             "keeps_rebalanced": I.keeps_rebalanced(r, today[c[0]])} for c, r in zip(cfg, res) if c[1] is not None]
    out = {"chain": ACTIVE.name, "stake_unit_usd": unit, "rows": rows}
    (I.OUT / "curve_thin.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["epochs"]:
        for r in epochs(tuple(sys.argv[2:]) or ("stable", "vol_x2", "vol_x4"))["rows"]:
            print(r)
        raise SystemExit
    if sys.argv[1:2] == ["thin"]:
        for r in thin()["rows"]:
            print(r)
        raise SystemExit
    args = [a for a in sys.argv[1:] if not a.startswith("s=")]
    steep = next((tuple(float(x) for x in a[2:].split(",")) for a in sys.argv[1:] if a.startswith("s=")), None)
    for r in main(tuple(args) or ("stable", "vol_x2", "vol_x4"), steep)["rows"]:
        print(r)
