"""Study K5 — one global REP valued by per-pool virtual curves (paper §4.9, §5.8, Appendix G).

Seven mainnet pools, daily epochs, March as an observation window and April–August
simulated. Each pool keeps a virtual curve for the common REP: marginal price
P_p = c_p·R_p, c_p = α/L̂_p (L̂_p: liquidity high-water mark, from the pool's own
swaps). Every pool starts with zero REP: unstaked volume pays f_max; cash surplus
above θ* mints REP along the curve to accounts whose own payments exceeded θ*;
extraction beyond the allowance is taken from the account's stake along the curve
and paid to the pool's LPs. Stake is global per account, split across its pools by
volume and valued at each pool's curve price in the coverage curve. Variant: an ICO
on each curve priced by buyers' H-day fee-savings demand.

Reported per pool: LP net income (cash and REP) against today and the target, fees
paid by REP holders, charges covered, curve area vs backing, ICO proceeds, and the
dispersion of curve prices across pools.

Scores: the study pool uses the canonical q (bid/ask at block + L); census pools
use an approximate mid-price q from Binance 1-second closes at block + L (ETH legs
from ETHUSDT trades; DAI/USDC at the peg). Curves are kept in USD for exposition; a
pair-native implementation keeps each curve in its pool's own assets.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .benchmark import PriceSeries
from .census import OUT as CENSUS, POOLS as CENSUS_POOLS
from .config import DATA_DIR, ONCHAIN_DIR, RESULTS_DIR
from .pools import STUDY_POOL
from .qlp import q_lp

OUT = RESULTS_DIR / "study_k"
L_S = 1.5
FEE = {"eth_usdc_005": 5e-4, "usdc_weth_030": 3e-3, "wbtc_weth_005": 5e-4, "link_weth_030": 3e-3,
       "uni_weth_030": 3e-3, "pepe_weth_030": 3e-3, "dai_usdc_001": 1e-4}
KLINE = {"wbtc_weth_005": "BTCUSDT", "link_weth_030": "LINKUSDT", "uni_weth_030": "UNIUSDT", "pepe_weth_030": "PEPEUSDT"}
M_ALLOW, CAP, TAU = 2e-4, 5e-2, 0.025


def kline(symbol: str):
    k = pd.read_parquet(DATA_DIR / "parquet" / "klines1s" / f"{symbol}.parquet")
    ts = k["ts_us"].to_numpy(); px = k["close"].to_numpy()
    return lambda t: px[np.clip(np.searchsorted(ts, t, side="right") - 1, 0, len(px) - 1)]


def scored_pools() -> dict[str, pd.DataFrame]:
    """Per swap: day, account, q, notional (USD)."""
    out = {}
    on = ONCHAIN_DIR
    qc = pd.read_parquet(on / "scored_timing" / STUDY_POOL.name / "q_c.parquet", columns=["tx_hash", "log_index", "q_c_h0"])
    sc = pd.concat(pd.read_parquet(p, columns=["tx_hash", "log_index", "block_ts", "notional_token0"])
                   for p in sorted((on / "scored" / STUDY_POOL.name).glob("*.parquet")))
    tx = pd.concat(pd.read_parquet(p, columns=["tx_hash", "tx_from"]) for p in sorted((on / "txs" / STUDY_POOL.name).glob("*.parquet"))).drop_duplicates("tx_hash")
    d = sc.merge(qc, on=["tx_hash", "log_index"]).merge(tx, on="tx_hash", how="left")
    out[STUDY_POOL.name] = pd.DataFrame({"day": d["block_ts"] // 86400, "acct": d["tx_from"], "q": d["q_c_h0"], "v": d["notional_token0"]})
    eth = PriceSeries("ETHUSDT")
    for pool, _ in CENSUS_POOLS:
        df = pd.read_parquet(CENSUS / f"{pool.name}.parquet", columns=["block_ts", "tx_from", "amount0_raw", "amount1_raw", "usd"])
        t = (df["block_ts"].to_numpy(np.int64) * 1_000_000) + int(L_S * 1e6)
        a0 = df["amount0_raw"].astype(float).to_numpy() / 10**pool.dec0
        a1 = df["amount1_raw"].astype(float).to_numpy() / 10**pool.dec1
        if pool.name == "dai_usdc_001":
            p1 = np.ones(len(df))                                   # USDC in DAI at the peg
        elif pool.name == "usdc_weth_030":
            p1 = eth.price_at(t)                                     # WETH in USDC
        else:
            p1 = eth.price_at(t) / kline(KLINE[pool.name])(t)        # WETH in the pool's token0
        q, _ = q_lp(a0, a1, p1)
        out[pool.name] = pd.DataFrame({"day": df["block_ts"] // 86400, "acct": df["tx_from"], "q": q, "v": df["usd"]})
    return out


def depth_from_swaps() -> pd.DataFrame:
    """Daily pool depth (USD per unit of ln price) from each pool's own swaps:
    median of notional / |Δ ln price| over swaps that moved the pool by at least
    3 ticks (Study I's estimator). Proportional to in-range liquidity; used as the
    liquidity measure for the curves' high-water mark."""
    rows = []
    srcs = {STUDY_POOL.name: pd.concat(pd.read_parquet(p, columns=["block_number", "log_index", "block_ts", "tick", "notional_token0"])
                                       for p in sorted((ONCHAIN_DIR / "scored" / STUDY_POOL.name).glob("*.parquet"))).rename(columns={"notional_token0": "usd"})}
    for pool, _ in CENSUS_POOLS:
        srcs[pool.name] = pd.read_parquet(CENSUS / f"{pool.name}.parquet", columns=["block_number", "log_index", "block_ts", "tick", "usd"])
    for name, d in srcs.items():
        d = d.sort_values(["block_number", "log_index"])
        dt = d["tick"].diff().abs()
        ok = dt >= 3
        dep = (d["usd"] / (dt * np.log(1.0001)))[ok]
        g = dep.groupby((d["block_ts"] // 86400)[ok]).median()
        rows.append(pd.DataFrame({"pool": name, "day": g.index, "usd": g.values}))
    return pd.concat(rows)


RHO = 5e-4                                # capacity scale: stake worth ρ·V gives discount e^−1 (study K)
F_MAX_X = [1.5, 2.0, 3.0, 5.0]            # f_max (unstaked fee) as a multiple of today's fee tier
OBS_DAYS = 31                             # March: observation window before launch (ICO demand)
ICO_H = [7, 30]                           # ICO: days of fee savings a buyer pays for
F_MIN_X = 0.2                             # coverage-curve floor f_min as a multiple of today's tier
ETA = [0.0, 1.0]                          # benign volume elasticity to the fee above today's tier
THETA_X = [0.0, 0.5]                      # LP target θ* as a multiple of today's tier


def swaps_frame(sw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One frame: pool code, day, account code, markout net of today's fee (qm), notional."""
    fr = []
    for name, d in sw.items():
        d = d.dropna(subset=["q", "v"])
        d = d[d["v"] > 0]
        fr.append(pd.DataFrame({"pool": name, "day": d["day"].to_numpy(np.int64), "acct": d["acct"].fillna("?").to_numpy(),
                                "qm": d["q"].to_numpy() - FEE[name], "v": d["v"].to_numpy()}))
    df = pd.concat(fr, ignore_index=True)
    df["a"] = pd.factorize(df["acct"])[0]           # one account across pools: stake is global
    return df.drop(columns="acct").sort_values(["day", "pool"], kind="stable").reset_index(drop=True)


def ico(obs: pd.DataFrame, names: list[str], c0: np.ndarray, fmax: np.ndarray, fmin: np.ndarray,
        theta: np.ndarray, H: float, nA: int):
    """REP pre-sale on each pool's own curve, paid in the pool's pair, uniform price.

    Buyers are accounts whose own payments over the observation window would have
    exceeded θ* at f_max, with no edge-taking swaps on net. A buyer with daily volume V
    in pool p values H days of fee savings, H·V·Δf·(1 − e^{−s/(ρV)}), for stake worth s
    and pays the clearing price per unit of value, so it buys s* = ρV·ln(H·Δf/ρ).
    Clearing: the curve's marginal price P_p = c_p·R_p at which REP worth Σs* is sold,
    R_p = √(Σs*/c_p). Proceeds Σs* go to the pool's LPs; the curve area c·R²/2 is half
    of them, so area ≤ backing from the start."""
    pi = {n: i for i, n in enumerate(names)}; P = len(names)
    n_obs = obs["day"].nunique()
    p_ = obs["pool"].map(pi).to_numpy()
    fm = fmax[p_]
    g = pd.DataFrame({"a": obs["a"].to_numpy(), "p": p_, "v": obs["v"].to_numpy(),
                      "x": (obs["qm"].to_numpy() + fm - theta[p_]) * obs["v"].to_numpy()}).groupby(["a", "p"]).sum().reset_index()
    g = g[g["x"] > 0]
    V = g["v"].to_numpy() / n_obs
    df_ = fmax[g["p"]] - fmin[g["p"]]
    s = np.where(H * df_ > RHO, RHO * V * np.log(np.maximum(H * df_ / RHO, 1.0)), 0.0)
    Sval = np.bincount(g["p"], s, minlength=P)
    R = np.sqrt(Sval / c0)
    price = c0 * R
    B = np.zeros(nA)
    np.add.at(B, g["a"].to_numpy(), np.where(price[g["p"]] > 0, s / np.where(price[g["p"]] > 0, price[g["p"]], 1), 0.0))
    return B, R, Sval.copy(), Sval, int((s > 0).sum())


def bootstrap(df: pd.DataFrame, liq_usd: pd.DataFrame, fmax_x: float, eta: float, theta_x: float,
              obs: pd.DataFrame | None = None, ico_h: float | None = None) -> dict:
    """Pools start with zero REP, or with an ICO on their curves (ico_h). Per UTC day (one epoch):
    fee per (account, pool) from the coverage curve with the account's global stake
    split across its pools by volume and valued at the pool's own curve price; unstaked
    volume pays f_max. Edge-takers (q < −m today) trade only if their edge covers the fee;
    other flow scales by min(1, (fee_today/f)^η). Charges are taken from the account's
    stake along the pool's curve and paid to LPs. Cash surplus above θ* mints REP along
    the curve to accounts whose own payments exceeded θ*."""
    names = sorted(df["pool"].unique()); pi = {n: i for i, n in enumerate(names)}; P = len(names)
    fee0 = np.array([FEE[n] for n in names]); fmax = fmax_x * fee0; fmin = F_MIN_X * fee0; theta = theta_x * fee0
    days = sorted(df["day"].unique())
    lq = liq_usd.pivot_table(index="day", columns="pool", values="usd")
    lq = lq.reindex(sorted(set(lq.index) | set(days))).ffill().bfill()[names].cummax()   # high-water mark incl. pre-launch
    c_all = 1.0 / lq.reindex(days).to_numpy()                  # α = 1: α only sets REP's unit
    nA = int(max(df["a"].max(), obs["a"].max() if obs is not None else 0)) + 1
    B = np.zeros(nA)                                           # REP per account (all staked)
    R = np.zeros(P); back = np.zeros(P); proceeds = np.zeros(P); buyers = 0
    if ico_h is not None:
        B, R, back, proceeds, buyers = ico(obs, names, c_all[0], fmax, fmin, theta, ico_h, nA)
    acc = {k: np.zeros(P) for k in ("v0", "v", "cash", "today", "target", "fee_paid", "ch", "covered", "rep_to_lps", "minted_usd")}
    first_mint = [None] * P; fee_path = {n: [] for n in names}; benign_path = {n: [] for n in names}
    staked = {n: [] for n in names}                            # (staked volume share, fee on staked volume) per day
    disp = []; max_area = np.zeros(P)
    rep_lp = np.zeros(P); trace = []
    for k, (day, g) in enumerate(df.groupby("day", sort=True)):
        c = c_all[k]
        price = c * R
        p_ = g["pool"].map(pi).to_numpy(); a_ = g["a"].to_numpy(); qm = g["qm"].to_numpy(); v0 = g["v"].to_numpy()
        # stake split and fee per (account, pool) on observed volume
        key = a_ * P + p_
        uk, inv = np.unique(key, return_inverse=True)
        Vap = np.bincount(inv, v0); ua = uk // P; up = uk % P
        ia = np.unique(ua, return_inverse=True)[1]
        Va = np.bincount(ia, Vap)
        r_ap = B[ua] * Vap / Va[ia]
        f_ap = fmin[up] + (fmax[up] - fmin[up]) * np.exp(-r_ap * price[up] / (RHO * Vap))
        f = f_ap[inv]
        sv = np.bincount(up, Vap * (r_ap > 0), minlength=P); sf = np.bincount(up, Vap * f_ap * (r_ap > 0), minlength=P)
        tv = np.bincount(up, Vap, minlength=P)
        for i in range(P):
            if tv[i] > 0:
                staked[names[i]].append((sv[i] / tv[i], sf[i] / sv[i] if sv[i] > 0 else np.nan, tv[i]))
        taker = qm + fee0[p_] < -M_ALLOW
        w = np.where(taker, (-qm >= f).astype(float), np.minimum(1.0, (fee0[p_] / f) ** eta))
        v = v0 * w
        ch = np.minimum(np.maximum(-qm - f - M_ALLOW, 0.0), CAP) * v
        cash = (qm + f) * v
        for arr, val in (("v0", v0), ("v", v), ("cash", cash), ("today", (qm + fee0[p_]) * v0), ("fee_paid", f * v), ("ch", ch)):
            acc[arr] += np.bincount(p_, val, minlength=P)
        x_ap = np.bincount(inv, cash - theta[p_] * v); ch_ap = np.bincount(inv, ch)
        # charges: stake taken along the curve, paid to the pool's LPs
        cov_ap = np.minimum(ch_ap, r_ap * price[up])
        C = np.bincount(up, cov_ap, minlength=P)
        C = np.minimum(C, c * R ** 2 / 2)
        Rn = np.sqrt(np.maximum(R ** 2 - 2 * C / c, 0.0)); dR = R - Rn
        tot = np.bincount(up, cov_ap, minlength=P)
        take = np.where(tot[up] > 0, dR[up] * cov_ap / np.where(tot[up] > 0, tot[up], 1), 0.0)
        np.subtract.at(B, ua, take); np.maximum(B, 0, out=B)
        R = Rn; back -= C
        acc["covered"] += C; acc["rep_to_lps"] += dR; rep_lp += dR
        # mint from cash surplus above θ*
        S = np.bincount(up, x_ap, minlength=P)
        pos = np.where(x_ap > 0, x_ap, 0.0); posp = np.bincount(up, pos, minlength=P)
        mint = np.where(S > 0, (1 - TAU) * S, 0.0)
        Rm = np.sqrt(R ** 2 + 2 * mint / c); dRm = Rm - R
        share = np.where(posp[up] > 0, pos / np.where(posp[up] > 0, posp[up], 1), 0.0)
        np.add.at(B, ua, dRm[up] * share)
        R = Rm; back += mint; acc["minted_usd"] += mint
        for i in range(P):
            if first_mint[i] is None and mint[i] > 0:
                first_mint[i] = k
            m = p_ == i
            if m.any():
                fee_path[names[i]].append(float((f[m] * v0[m]).sum() / v0[m].sum()))
                b = m & ~taker
                if b.any():
                    benign_path[names[i]].append(float((f[b] * v0[b]).sum() / v0[b].sum()))
            max_area[i] = max(max_area[i], (c[i] * R[i] ** 2 / 2) / back[i] if back[i] > 0 else 0.0)
        trace.append({"day": int(day), "rep_accounts": float(B.sum()), "R": R.round(6).tolist(), "price": (c * R).tolist(),
                      "charged_rep": dR.tolist(), "minted_rep": dRm.tolist(),
                      "benign_fee_bp": [round(benign_path[n][-1] * 1e4, 2) if benign_path[n] else None for n in names]})
        pr = c * R; live = pr[pr > 0]
        disp.append(live.max() / live.min() if len(live) > 1 else 1.0)
    acc["target"] = theta * acc["v"]
    pr = c_all[-1] * R; pstar = pr[pr > 0].min() if (pr > 0).any() else 0.0
    out = {}
    for i, n in enumerate(names):
        fp = fee_path[n]
        bp = lambda x: round(float(x / acc["v"][i] * 1e4), 2) if acc["v"][i] > 0 else None
        out[n] = {
            "days_to_first_mint": first_mint[i],
            "fee_bp": {"first_week": round(float(np.mean(fp[:7])) * 1e4, 2), "last_month": round(float(np.mean(fp[-30:])) * 1e4, 2),
                       "benign_last_month": round(float(np.mean(benign_path[n][-30:])) * 1e4, 2),
                       "f_max": round(fmax[i] * 1e4, 2), "f_min": round(fmin[i] * 1e4, 2)},
            "staked_last_month": {"volume_share": round(float(np.mean([x[0] for x in staked[n][-30:]])), 3),
                                  "fee_bp": round(float(np.nanmean([x[1] for x in staked[n][-30:]])) * 1e4, 2)},
            "volume_kept": round(float(acc["v"][i] / acc["v0"][i]), 3),
            "lp_net_bp": {"today": round(float(acc["today"][i] / acc["v0"][i] * 1e4), 2), "cash": bp(acc["cash"][i]),
                          "cash_plus_rep_at_pstar": bp(acc["cash"][i] + rep_lp[i] * pstar),
                          "target": round(theta[i] * 1e4, 2)},
            "lp_net_usd": {"today": round(float(acc["today"][i])), "cash": round(float(acc["cash"][i])),
                           "rep_at_pstar": round(float(rep_lp[i] * pstar))},
            "charges_usd": round(float(acc["ch"][i])), "covered_share": round(float(acc["covered"][i] / acc["ch"][i]), 3) if acc["ch"][i] > 0 else None,
            "max_area_over_backing": round(float(max_area[i]), 4),
            "ico_proceeds_bp_of_volume": round(float(proceeds[i] / acc["v"][i] * 1e4), 3) if acc["v"][i] > 0 else None,
            "end_price_over_pstar": round(float(pr[i] / pstar), 3) if pstar > 0 else None,
        }
    return {"pools": out, "ico_buyers": buyers, "names": names, "trace": trace, "price_dispersion_max_over_min": {"median": round(float(np.median(disp)), 3), "end": round(float(disp[-1]), 3)}}


def run() -> dict:
    sw = scored_pools()
    liq = depth_from_swaps()
    df = swaps_frame(sw)
    d0 = df["day"].min() + OBS_DAYS
    obs, live = df[df["day"] < d0], df[df["day"] >= d0]
    out = {"runs": {}}
    for tx in THETA_X:
        for eta in ETA:
            for fx in F_MAX_X:
                for h in [None] + ICO_H:
                    key = f"theta={tx:g}x eta={eta:g} fmax={fx:g}x start={'zero' if h is None else f'ico{h}d'}"
                    out["runs"][key] = bootstrap(live, liq, fx, eta, tx, obs, h)
    out["notes"] = {"allowance_bps": M_ALLOW * 1e4, "tau": TAU, "rho": RHO, "f_min_x": F_MIN_X, "epoch": "UTC day",
                    "window": f"observation {OBS_DAYS} days (March), simulation April–August",
                    "start": "zero REP, or ICO on each pool's curve priced by buyers' H-day fee savings",
                    "scores": "study pool canonical q; census pools approximate mid q (Binance 1s closes)"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "global_rep.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    res = run()
    for key, r in res["runs"].items():
        print(f"{key}   buyers {r['ico_buyers']}  dispersion {r['price_dispersion_max_over_min']}")
        for p, v in r["pools"].items():
            print(f"  {p:14s} mint@d{v['days_to_first_mint']}  fee {v['fee_bp']['first_week']:6.1f}→{v['fee_bp']['last_month']:6.1f}bp staked {v['staked_last_month']['volume_share']:.2f}@{v['staked_last_month']['fee_bp']:5.1f} (fmin {v['fee_bp']['f_min']})  "
                  f"vol {v['volume_kept']:.2f}  LP bp today {v['lp_net_bp']['today']:6.2f} cash {v['lp_net_bp']['cash']} +rep {v['lp_net_bp']['cash_plus_rep_at_pstar']} "
                  f"target {v['lp_net_bp']['target']}  covered {v['covered_share']}  area/back {v['max_area_over_backing']}  ico {v['ico_proceeds_bp_of_volume']}bp")
