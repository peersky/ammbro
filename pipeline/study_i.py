"""Study I — block-level comparison of arb payout rules.

Goal (user): the rule with the best overall LP outcome while the pool
stays rebalanced every block.

Model. Every block in the window in order (mainnet 1.32M; Arbitrum 63.4M
at their reconstructed sub-second times, blocksim):
  1. Arb phase (pool-first). Gap G = ln oracle − ln pool at block_ts + L.
     Each arb j (hedge cost h_j) picks the trade size maximizing its
     profit under the payout rule; the most profitable wins and pays the
     builder the runner-up's profit (second-price auction for the slot).
  2. Exogenous flow: the block's real non-arb swaps, replayed in order
     with real notional and direction; they move the pool and trade
     against whatever price the arb phase left.
Pool price moves linearly in ln price with depth D (USD per unit ln
price, per day, blocksim). Arb extraction on a trade of size V closing
edge a = |G| − f: E(V) = (a − V/2D)·V; the LP loses E and recaptures the
rule's charge. Exogenous LP markout: V·(f + s·(avg ln price − ln oracle)).

Payout rules (what the arb keeps; the LP recaptures E − kept):
  today        keeps E. No reconciliation.
  avg_margin   keeps min(x̄, m)·V, x̄ = average edge. The Study B/H form.
               Pays m per unit volume while the AVERAGE stays above m, so
               the arb is paid to keep trading past the oracle (overshoot)
               — tested, not assumed.
  job_cap      keeps min(x̄, m)·V_job, only for trading exactly to the band
               B (V_job = D(|G| − B)); any other size earns nothing.
  marginal_cap keeps ∫ min(marginal edge, m) over the trade. Rent is capped
               per unit along the price path, so the arb stops where the
               marginal edge equals its cost — the natural stopping point —
               and cannot be paid for overshoot. Computable ex-post: the
               reconciler knows pre/post pool price and the oracle.
  marginal_cap_gas  marginal_cap plus reimbursement of the trade's actual
               base-fee gas out of the extraction (the reconciler knows it
               from the receipt): a job reward = cost + small per-unit margin.
  + premium p  position premium (user proposal: m higher for top slots):
               every arb can buy the slot, so it is bid away to builders.

Parameter m: static grid, or a controller per UTC day:
  ctl        Study H design: raise x2 if staleness > S*, hold in [S_low,
             S*], else x0.8 if the slot was contested in > half of arb
             blocks, else blind decay x0.95. Decays into the cost cliff:
             when m falls below the cheapest arb's cost nobody arbs for a
             whole epoch.
  ctl_comp   competition-targeting: raise x2 if staleness > S*, lower x0.8
             only while the slot is contested (a second arb could also
             profit), otherwise HOLD. Settles where only the cheapest arb
             can do the job — between the cheapest and second-cheapest
             cost — and never approaches the cliff unless costs rise.
  ctl_feasible  uses ONLY on-chain-observable information. Staleness is
             self-referential: among blocks with a pool swap whose RESTING
             gap at block start exceeds f + m + EPS_SR, the share where the
             block's first swap did not move the pool toward the oracle.
             Any arb with cost below m profits from correcting such a gap,
             so in a healthy pool this ~never happens; with m below every
             arb's cost it always does. Needs only the resting price, the
             oracle report and the first swap's direction — all already in
             reconciliation. (A post-first-swap gap test is too noisy: large
             USER first swaps push the pool off and ratchet m up.) Hourly x2
             raise on it, daily decay x0.95 otherwise — no "contested" signal,
             no arb cost knowledge, no index proofs.
  ctl_div    ctl_feasible with the blind daily decay replaced by an on-chain
             competition signal: winner diversity. On a first-come-first-
             served chain whichever profitable arb arrives first wins, so when
             several can profit the wins spread across several addresses; when
             m nears the cheapest arb's cost only that arb can profit and wins
             everything. The reconciler sees each correcting swap's sender.
             Lower m x0.95 at the day's end only if > DIV_TAU of the day's arb
             wins went to someone other than the day's top winner; otherwise
             hold. Raise as ctl_feasible. The race is simulated for the signal
             only (winner drawn uniformly among the arbs that would profit);
             payouts keep the second-price model. The signal presumes a race:
             under a builder auction (mainnet PBS) the cheapest arb outbids
             the rest and wins every block it can profit from, so wins
             concentrate and the signal under-reports competition — there the
             feasible choice is ctl_feasible (Chain.ordering). Faking competition with
             extra addresses only lowers the faker's own allowance; hiding it
             needs a cartel that any arb with cost < m can break.
  ctl_fast   ctl_comp with asymmetric timing: staleness checked every
             RAISE_S (1h) and raised x2 immediately; lowering stays
             on the daily competition signal. Recovers from a cost shock
             within hours instead of days. Staleness = share of
CORRECTABLE blocks left uncorrected, where correctable means the cheapest
arb would profit with no charge at all — a fixed price band would demand
corrections no arb can afford when costs rise.

Rebalancing (the binding constraint) is judged on quantities that mean the
same at any block time: the share of blocks within fee + 1bp after the arb
phase may fall at most REB_TOL below `today`'s, and the volume-weighted gap
users trade against may rise at most USER_STALE_TOL_BPS. Runs failing
either are FAILURES whatever their LP number: with the arb gone the pool
freezes, and replayed user flow trades against a price no real router would
route to, which inflates LP P&L artificially. Also reported: uncorrected
share of correctable blocks (the earlier constraint — it counts a standing
gap once per block, so one stalled hour weighs 300 blocks on mainnet and
14,400 on Arbitrum) and uncorrected time in hours.

Arb phase position (`phase`): open (before the block's user flow, default),
close (after it), or both. No time passes inside a block, so open and close
act on the same information; close only undoes the users' own in-block
impact, which the next block's open also does with one block's fresher data. Close
matters for the pool's RESTING price between blocks (what TWAP-style
readers, lending protocols and next-block routers see).

HONESTY (bind to writeup): linear depth; exogenous flow replayed with
fixed size/direction (no routing response to pool quality); one arb
action per block; assumed arb cost population; second-price slot
auction. Calibrated against the real pool under the `today` rule.
"""
from __future__ import annotations

import json
import math
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from .blocksim import CACHE, load
from .config import REPO_ROOT, RESULTS_DIR

OUT = RESULTS_DIR / "study_i"
F = 0.0005
REB = F + 1e-4
B_JOB = F + 0.5e-4
ARB_COSTS_BPS = [0.3, 0.6, 1.0, 1.5, 2.5]
ARB_GAS_UNITS = 250_000
SHIFT_DAY = pd.Timestamp("2026-06-01").value // 10**9 // 86400
S_STAR, S_LOW, TAU_C = 0.02, 0.005, 0.5
RAISE_S = 3600                  # fast controllers check staleness hourly
EPS_SR = 0.5e-4                 # self-referential staleness tolerance above f + m
S_STAR_SR = 0.02
S_LOW_SR = 0.01                 # daily decay allowed only below this
MIN_STALE_SR = 5                # hourly raise needs at least this many stale blocks
RAISE_SR, DECAY_SR = 2.0, 0.95  # feasible controller step sizes
# Unstaked alternative (review point 1): every arb may instead trade from a fresh,
# unstaked account, paying f_max + c * |own ln-price move| on its volume and keeping
# its whole edge (no stake, so no charge). None = all arbs staked (paper v1).
UNSTAKED = None                 # (f_max, c), f_max as a rate
# Staleness rule (review point 2): "first_swap" = the block's first swap did not move
# the pool toward the oracle (paper v1, dust-gameable); "outcome" = no point of the
# block brought the pool within f + m + EPS_SR of the oracle.
STALE_RULE = "outcome"
# Stake-limited arbitrage (review follow-up): the arbitrage market holds REP worth
# STAKE (USD, split equally across the cost population); a staked arb pays the
# coverage-curve fee f = F + (FMAX - F)·exp(-r / (RHO · v_epoch)) on its UTC-day
# volume so far (F = the pool fee as f_min). None = arbs always pay F (paper v1).
RHO = 5e-4
RED_SHARE = 0.05                # ctl_redK: a sender counts if it won at least this share of the day's corrections
BAND_LO, BAND_UP = 0.25, 1.1    # ctl_band: raise slightly when fewer than BAND_LO of arb blocks show a contested slot
DIV_TAU = 0.25                  # ctl_div: lower m only if > this share of wins went past the top winner
REB_TOL = 0.005                 # rebalancing constraint: within-band share may drop <= 0.5pp vs today
USER_STALE_TOL_BPS = 0.1        # ... and user pre-trade gap may rise <= 0.1bp vs today

_DATA = {}


def _init():
    blocks, exo = load()
    if blocks[["ln_o", "D", "base_fee_wei"]].isna().any().any():
        raise SystemExit("NaN in block inputs; one NaN poisons every later block — rebuild blocksim")
    _DATA["o"] = blocks["ln_o"].to_numpy()
    _DATA["D"] = blocks["D"].to_numpy()
    _DATA["gas"] = (blocks["base_fee_wei"].to_numpy() / 1e18 * ARB_GAS_UNITS * np.exp(blocks["ln_o"].to_numpy()))
    _DATA["day"] = blocks["day"].to_numpy()
    _DATA["bn"] = blocks["block_number"].to_numpy()
    idx = np.searchsorted(_DATA["bn"], exo["block_number"].to_numpy())
    _DATA["exo_start"] = np.searchsorted(idx, np.arange(len(blocks)), side="left")
    _DATA["exo_end"] = np.searchsorted(idx, np.arange(len(blocks)), side="right")
    _DATA["exo_s"] = exo["s"].to_numpy()
    _DATA["exo_v"] = exo["v"].to_numpy()
    step_s = json.loads((CACHE / "calibration_inputs.json").read_text()).get("step_s", 12)
    _DATA["raise_steps"] = int(round(RAISE_S / step_s))
    _DATA["step_s"] = float(step_s)   # 300 on mainnet (12s), ~14k on Arbitrum (~0.25s)


def arb_choice(rule: str, a: float, D: float, h: float, g: float, m: float, gap_abs: float):
    """(profit, V, kept, unstaked) for one arb; V = 0 means no trade. kept is the
    arb's take beyond the pool fee F (for an unstaked trade: its edge net of the
    extra fee it pays over F)."""
    best = (0.0, 0.0, 0.0, 0)
    if a <= 0:
        return best

    def ev(V, kept, u=0):
        return (kept - h * V - g, V, kept, u)

    if rule == "today":
        V = D * (a - h)
        if V > 0:
            best = max(best, ev(V, (a - V / (2 * D)) * V))
    elif rule == "avg_margin":
        for V in (2 * D * (a - m), D * (a - h)):
            if V > 0:
                x = a - V / (2 * D)
                best = max(best, ev(V, min(x, m) * V))
    elif rule == "job_cap":
        V = D * (gap_abs - B_JOB)
        if V > 0:
            x = a - V / (2 * D)
            best = max(best, ev(V, min(x, m) * V))
    elif rule in ("marginal_cap", "marginal_cap_gas"):
        if h < m or a <= m or rule == "marginal_cap_gas":
            V = D * (a - h)
            if V > 0:
                V1 = max(D * (a - m), 0.0)
                V1 = min(V1, V)
                kept = m * V1 + a * (V - V1) - (V * V - V1 * V1) / (2 * D)
                if rule == "marginal_cap_gas":
                    kept += min(g, (a - V / (2 * D)) * V - kept)
                best = max(best, ev(V, kept))
        if UNSTAKED is not None:
            fmax, c = UNSTAKED
            Vu = D * (gap_abs - fmax - h) / (1 + 2 * c)
            if Vu > 0:
                E = (a - Vu / (2 * D)) * Vu                 # edge beyond F
                extra = (fmax - (gap_abs - a) + c * Vu / D) * Vu
                best = max(best, ev(Vu, E - extra, 1))
    return best


def run_one(args) -> dict:
    rule, param, scenario, premium = args[:4]
    phase = args[4] if len(args) > 4 else "open"     # open | close | both
    record = bool(args[5]) if len(args) > 5 else False  # keep per-trade arrays (Study C)
    extra_cost = (args[6] if len(args) > 6 else 0.0) / 1e4   # added to every arb's cost (e.g. capital cost of stake)
    global UNSTAKED, STALE_RULE
    settings = args[7] if len(args) > 7 else {}
    UNSTAKED = settings.get("unstaked", None)
    STALE_RULE = settings.get("stale_rule", "outcome")
    stake_K = settings.get("stake", None)              # USD of REP held by the arbitrage market
    fmax_fee = settings.get("fmax", 500e-4)
    ramp_days = settings.get("stake_ramp_days", 0)
    pooled = settings.get("alloc", "equal") == "pooled"
    # Premium mint (review follow-up): a correcting swap's fee premium above F, net of
    # its charge, mints REP to the arbitrageur at par (less TAU), credited to its own
    # stake an hour later; arbs value the credit at a fraction v of par. Starts at 0 REP.
    pm_v = settings.get("premium_mint", None)
    TAU = settings.get("pm_tau", 0.0)               # take on premium credits (benign surplus keeps its own)
    if pm_v is not None:
        stake_K = 0.0; UNSTAKED = None
        _n = len(POPULATIONS.get(scenario, ARB_COSTS_BPS)); pend = np.zeros(_n)
        r_arb = np.full(_n, settings.get("pm_initial_stake", 0.0) / _n)   # e.g. a launch sale, held equally
    pm_minted = pm_leak = 0.0
    # Shock bonus (review follow-up): the allowance in a block is m + kappa * shock, where
    # shock is the benchmark's own move across the block ("jump", exogenous, use it or lose
    # it) or the standing gap at the block's start ("gap", endogenous; the rejected variant).
    shock_k = settings.get("shock_k", 0.0)
    shock_key = settings.get("shock_key", "jump")
    o_prev = None
    # Events: arbitrageur j absent (dropout or withholding) from day offset s for n days
    absent = settings.get("absent", [])
    win_cnt = np.zeros(len(POPULATIONS.get(scenario, ARB_COSTS_BPS)), dtype=np.int64)
    arb_inc = np.zeros(len(win_cnt))
    # Readiness: an arb with no win for dorm_s seconds goes dormant and re-enters wake_s after
    # the first block in which it could have profited (infrastructure taken down and redeployed)
    dorm_s = settings.get("dormant_after_s", None); wake_s = settings.get("wake_s", 86400.0)
    last_win = np.zeros(len(win_cnt)); wake_at = np.full(len(win_cnt), np.inf)
    # Rotation (readiness): each window a pseudo-random draw designates one registered arb, who
    # earns m; others earn m*(1 - phi). If correctable gaps stay open for grace blocks, the window
    # falls back to full m for all and the designee fails it. The controller lowers m only if at
    # least rot_k arbs passed a window, and failed none, in the last 24 h.
    rot = settings.get("rotation", None)
    if rot is not None:
        r_win = rot.get("window_s", 3600.0); r_phi = rot.get("phi", 0.5)
        r_grace = rot.get("grace_blocks", 10); rot_k = rot.get("k", 4)
        cur_w = -1; desig = 0; w_fail = False; w_stale = 0; fallback = False
        pass_t = np.full(len(win_cnt), -np.inf); fail_t = np.full(len(win_cnt), -np.inf)
        rot_fails = 0
    # Proven-stale relief (Layer 2, no arbitrage stake): every arb either pays f_max unstaked
    # or, while relief is on, attaches a signed report and pays the relief fee; neither path
    # has stake, so nothing beyond the fee is charged. Relief switches on when a block ends
    # more than g_on from the oracle and off once a block ends within g_off (hysteresis).
    # Level: "clear" = clamp(g - m - eta, f_q, f_max); "steep" = logistic discount centred on
    # the middle of [f_q + m, f_max + m]. g is read from a report lagged by lag_s seconds.
    relief = settings.get("relief", None)
    relief_on = False; rl_trades = rl_vol = 0.0; rl_blocks = 0; o_hist = []
    if relief is not None:
        stake_K = 0.0
        r_fmax = relief.get("fmax", 500e-4); r_fq = relief.get("fq", F); r_eta = relief.get("eta", 0.0)
        r_mode = relief.get("mode", "clear"); r_lag = relief.get("lag_s", 0.0)
        r_gas = relief.get("proof_gas_frac", 0.24)
        r_hold = relief.get("hold_s", 0.0)             # stay on this long after re-coupling
        inband_s = 0.0
        # hysteresis in g ("hyst"): discount switches on when the proven gap reaches
        # band + d_on and stays on while the gap closes, until it is back within the band;
        # level while on: "full" (fee f_min), "half", or "frozen" (clearing fee at switch-on)
        h_don = relief.get("d_on", 5e-4); h_level = relief.get("level", "full")
        hyst_on = False; hyst_fee = F
    if stake_K is not None and UNSTAKED is None:
        UNSTAKED = (fmax_fee, 0.0)                       # fresh accounts always available
    vol_k = float(scenario.split("_x")[1]) if scenario.startswith("vol_x") else 1.0
    trades = []
    if not _DATA:
        _init()
    o, Dd, gas, day = _DATA["o"], _DATA["D"], _DATA["gas"], _DATA["day"]
    es, ee, xs, xv = _DATA["exo_start"], _DATA["exo_end"], _DATA["exo_s"], _DATA["exo_v"]
    controlled = isinstance(param, str) and param.startswith("ctl")
    band = isinstance(param, str) and param.startswith("ctl_band")
    urg = param in ("ctl_urg", "ctl_urg2")   # hourly staleness raise + lowering driven by urgency (contested corrections)
    urg2 = param == "ctl_urg2"               # ... with blind decay as the default: x0.8 if urgent, x0.95 if calm and not stale
    comp_only = param in ("ctl_comp", "ctl_fast") or band
    # ctl_redK: decay only if at least K distinct senders each won >= RED_SHARE of the day's corrections
    red = isinstance(param, str) and param.startswith("ctl_red")
    if param == "ctl_rot":
        param_rot = True
    k_red = int(param[7:]) if red else 0
    diverse = param == "ctl_div" or red
    feasible = param in ("ctl_feasible", "ctl_div") or red or urg
    fast = param in ("ctl_fast", "ctl_feasible", "ctl_div") or red or urg
    rng = np.random.default_rng(7)
    sr_obs = sr_stale = w_sr_obs = w_sr_stale = 0
    w_corr = w_uncorr = w_n = 0
    s_star, s_low = (0.005, 0.001) if param == "ctl_tight" else (S_STAR, S_LOW)
    m = 5e-4 if controlled else (param / 1e4 if param is not None else 0.0)
    costs_base = [c / 1e4 for c in POPULATIONS.get(scenario, ARB_COSTS_BPS)]
    d_wins = np.zeros(len(costs_base), dtype=np.int64)
    shift = float(scenario.split("_x")[1]) if scenario.startswith("costs_x") else 1.0
    depth_x = float(scenario.split("_x")[1]) if scenario.startswith("depth_x") else 1.0

    o0 = o[0]; o_prev_blk = o0
    p = o0
    n_arb = len(costs_base)
    vol_ep = np.zeros(n_arb)
    day0 = day[0]
    fee_prem = 0.0; stalled_fee = 0

    def arb_fee(j):
        if stake_K is None or rule == "today":
            return F
        if pm_v is not None:
            r, v = r_arb[j], vol_ep[j]
            if r <= 0:
                return fmax_fee
            return F if v <= 0 else F + (fmax_fee - F) * math.exp(-r / (RHO * v))
        ramp = min(1.0, (day[i] - day0) / ramp_days) if ramp_days else 1.0
        if pooled:                                   # one staker (e.g. a solver) covers all arbs
            r, v = stake_K * ramp, vol_ep.sum()
        else:                                        # each arb holds an equal share
            r, v = stake_K / n_arb * ramp, vol_ep[j]
        if r <= 0:
            return fmax_fee
        return F if v <= 0 else F + (fmax_fee - F) * math.exp(-r / (RHO * v))

    lp_arb = lp_exo = builder = margin = charge_tot = arb_vol = 0.0
    exo_gap_w = exo_vol = 0.0
    reb = n = overshoot = 0
    pre_gaps = []
    eob_gaps = []; eob_n = eob_reb = 0
    pass_trades = [0, 0]; pass_vol = [0.0, 0.0]
    stale_run = persist2 = 0
    post_gaps = []
    daily = []
    d_cur = day[0]; d_stale = d_n = d_arb = d_cont = 0; d_m = m
    n_corr = n_uncorr = 0
    unst_n = 0; unst_vol = 0.0
    d_sr_obs = d_sr_stale = 0
    for i in range(len(o)):
        if day[i] != d_cur:
            st = d_stale / max(d_n, 1); ct = d_cont / max(d_arb, 1)
            daily.append((int(d_cur), round(d_m * 1e4, 4), round(st, 4), round(ct, 4)))
            if controlled:
                if urg2:
                    d_sr = d_sr_stale / max(d_sr_obs, 1)
                    if ct > TAU_C:
                        m *= 0.8
                    elif d_sr < S_LOW_SR:
                        m *= DECAY_SR
                elif urg:
                    if ct > TAU_C:
                        m *= DECAY_SR
                elif rot is not None:
                    t_d = i * _DATA["step_s"]
                    ready = int(((t_d - pass_t <= 86400) & (t_d - fail_t > 86400)).sum())
                    if ready >= rot_k:
                        m *= DECAY_SR
                elif red:
                    tot = d_wins.sum()
                    if tot and int((d_wins >= RED_SHARE * tot).sum()) >= k_red:
                        m *= DECAY_SR
                elif diverse:
                    tot = d_wins.sum()
                    if tot and 1.0 - d_wins.max() / tot > DIV_TAU:
                        m *= DECAY_SR
                elif feasible:
                    d_sr = d_sr_stale / max(d_sr_obs, 1)
                    if d_sr < S_LOW_SR:
                        m *= DECAY_SR
                elif st > s_star and not fast:
                    m *= 2.0
                elif st >= s_low:
                    pass
                elif band and ct < BAND_LO:        # too little visible competition: keep a second arb in play
                    m *= BAND_UP
                elif ct > TAU_C:
                    m *= 0.8
                elif not comp_only:
                    m *= 0.95
                m = min(max(m, 0.02e-4), 50e-4)
            d_cur = day[i]; d_stale = d_n = d_arb = d_cont = 0; d_m = m
            d_sr_obs = d_sr_stale = 0
            d_wins[:] = 0
            vol_ep[:] = 0.0
        oi = o0 + vol_k * (o[i] - o0); D = Dd[i] * depth_x
        _jump = 0.0 if o_prev is None else abs(oi - o_prev); o_prev = oi
        if pm_v is not None and i % _DATA["raise_steps"] == 0:
            r_arb += pend; pend[:] = 0.0
        _trades_before = pass_trades[0] + pass_trades[1]
        G = oi - p; gab = abs(G)
        m_blk = m + shock_k * (_jump if shock_key == "jump" else gab)
        _pre_gap = gab; _pre_sign = 1.0 if G > 0 else -1.0     # +1: pool below oracle, a buy corrects
        if es[i] < ee[i] and i % 10 == 0:
            pre_gaps.append(gab)
        if phase == "close":
            for k in range(es[i], ee[i]):
                s = xs[k]; V = xv[k]
                pav = p + s * V / (2 * D)
                lp_exo += V * (F + s * (pav - oi))
                exo_gap_w += V * abs(p - oi); exo_vol += V
                p += s * V / D
        for _pass in ((0,) if phase != "both" else (0, 1)):
          if _pass == 1:
            for k in range(es[i], ee[i]):
                s = xs[k]; V = xv[k]
                pav = p + s * V / (2 * D)
                lp_exo += V * (F + s * (pav - oi))
                exo_gap_w += V * abs(p - oi); exo_vol += V
                p += s * V / D
          G = oi - p; gab = abs(G); a = gab - F
          if relief is not None and a > 0 and rule != "today":
              costs = [c * (shift if day[i] >= SHIFT_DAY else 1.0) + extra_cost for c in costs_base]
              if absent:
                  _do = day[i] - day[0]
                  costs = [1.0 if any(aj == j and as_ <= _do < as_ + an for aj, as_, an in absent) else c for j, c in enumerate(costs)]
              correctable = arb_choice("today", a, D, costs[0], gas[i], 0.0, gab)[0] > 0
              # report price (lagged) -> proven decoupling g and relief fee
              step = _DATA["step_s"]
              if r_lag <= 0 or i == 0:
                  o_rep = oi
              elif r_lag < step:
                  o_rep = o_prev_blk + (1 - r_lag / step) * (oi - o_prev_blk)
              else:
                  kk = int(round(r_lag / step)); o_rep = o0 + vol_k * (o[max(i - kk, 0)] - o0)
              glo, ghi = r_fq + m, r_fmax + m
              traded_any = False
              for _rep in range(6):                     # successive swaps, each priced from the gap left
                  G = oi - p; gab = abs(G)
                  if gab - F <= 0:
                      break
                  g_rep = abs(o_rep - p)
                  if r_mode == "hyst":
                      if not hyst_on and g_rep >= F + EPS_SR + h_don:   # thresholds independent of m
                          hyst_on = True
                          hyst_fee = {"full": r_fq, "half": 0.5 * (r_fq + r_fmax),
                                      "frozen": min(max(g_rep - m, r_fq), r_fmax)}[h_level]
                      elif hyst_on and g_rep <= F:
                          hyst_on = False
                      fr = hyst_fee
                  elif r_mode == "clear":
                      fr = min(max(g_rep - m - r_eta, r_fq), r_fmax)
                  elif r_mode == "full":
                      fr = r_fq
                  else:
                      kx = 8.0 / max(ghi - glo, 1e-9)
                      x = 1.0 / (1.0 + math.exp(-kx * (g_rep - 0.5 * (glo + ghi))))
                      # steep: discount grows with the gap; reverse: discount shrinks with it
                      fr = r_fmax - (r_fmax - r_fq) * (x if r_mode == "steep" else 1.0 - x)
                  opts = []
                  for j, h in enumerate(costs):
                      if r_mode == "sync" and relief_on:
                          # pays F; per-unit charge max(edge_rep(u) - m, 0) settled synchronously
                          # against the report; the arb keeps at most m per unit of true edge
                          Vx = D * (gab - F - h)
                          L1 = min(max(D * (g_rep - F - m), 0.0), max(Vx, 0.0))
                          if Vx > 0 and gab - g_rep + m > h:
                              keptF = (gab - g_rep + m) * L1 + (gab - F) * (Vx - L1) - (Vx * Vx - L1 * L1) / (2 * D)
                              prof = keptF - h * Vx - gas[i] * (1 + r_gas)
                              if prof > 0:
                                  opts.append((prof, Vx, keptF, "relief", j, F))
                      for path, phi, gx in (("unstaked", r_fmax, 0.0), ("relief", fr, r_gas)):
                          if path == "relief" and (r_mode == "sync" or (r_mode == "hyst" and not hyst_on)
                                                   or (r_mode != "hyst" and not relief_on)):
                              continue
                          Vx = D * (gab - phi - h)
                          if Vx <= 0:
                              continue
                          Ex = (gab - F - Vx / (2 * D)) * Vx
                          keptF = Ex - (phi - F) * Vx
                          prof = keptF - h * Vx - gas[i] * (1 + gx)
                          if prof > 0:
                              opts.append((prof, Vx, keptF, path, j, phi))
                  if not opts:
                      break
                  opts.sort(reverse=True)
                  wb = opts[0]; rb = next((o_ for o_ in opts[1:] if o_[4] != wb[4]), None)
                  Vx, keptF = wb[1], wb[2]
                  lp_arb -= keptF; fee_prem += (wb[5] - F) * Vx
                  builder += max(rb[0], 0.0) if rb else 0.0
                  margin += wb[0] - (max(rb[0], 0.0) if rb else 0.0)
                  arb_vol += Vx; pass_trades[_pass] += 1; pass_vol[_pass] += Vx
                  if diverse:                            # FCFS race: any profitable arb can be first
                      profj = sorted({o_[4] for o_ in opts})
                      d_wins[profj[rng.integers(len(profj))]] += 1
                  if wb[3] == "relief":
                      rl_trades += 1; rl_vol += Vx
                  else:
                      unst_n += 1; unst_vol += Vx
                  p += math.copysign(Vx / D, G)
                  d_arb += 1; traded_any = True
                  if rb:
                      d_cont += 1
              if correctable:
                  n_corr += 1; d_n += 1; w_corr += 1
                  if not traded_any:
                      n_uncorr += 1; d_stale += 1; w_uncorr += 1
              a = -1.0                                   # skip the staked-arb block below
          if a > 0:
              costs = [c * (shift if day[i] >= SHIFT_DAY else 1.0) + extra_cost for c in costs_base]
              if absent:
                  _do = day[i] - day[0]
                  costs = [1.0 if any(aj == j and as_ <= _do < as_ + an for aj, as_, an in absent) else c for j, c in enumerate(costs)]
              correctable = arb_choice("today", a, D, min(costs), gas[i], 0.0, gab)[0] > 0
              fees = [arb_fee(j) for j in range(n_arb)]
              if rot is not None:
                  t_now = i * _DATA["step_s"]
                  wid = int(t_now // r_win)
                  if wid != cur_w:
                      if cur_w >= 0:
                          if w_fail:
                              fail_t[desig] = t_now; rot_fails += 1
                          else:
                              pass_t[desig] = t_now
                      cur_w = wid; w_fail = False; w_stale = 0; fallback = False
                      desig = int(np.random.default_rng(1_000_003 + wid).integers(n_arb))
                  m_of = lambda j: m_blk if (fallback or j == desig) else m_blk * (1.0 - r_phi)
              else:
                  m_of = lambda j: m_blk
              if pm_v is None:
                  res = sorted(((*arb_choice(rule, gab - fees[j], D, h, gas[i], m_of(j), gab), h, fees[j], j)
                                for j, h in enumerate(costs)), reverse=True)
              else:
                  res = sorted(((*arb_choice(rule, gab - F, D, h + (1 - pm_v * (1 - TAU)) * (fees[j] - F), gas[i], m_blk, gab), h, fees[j], j)
                                for j, h in enumerate(costs)), reverse=True)
              dorm_prof = []
              if dorm_s is not None:
                  t_now = i * _DATA["step_s"]
                  keep_ = []
                  for x in res:
                      j = x[6]
                      if t_now >= wake_at[j]:                                    # redeployed: re-enters now
                          last_win[j] = wake_at[j]; wake_at[j] = np.inf
                      if t_now - last_win[j] > dorm_s and t_now < wake_at[j]:      # dormant
                          if x[0] > 0 and x[1] > 0 and wake_at[j] == np.inf:
                              dorm_prof.append(j)
                          continue
                      keep_.append(x)
                  res = keep_ or [(0.0, 0.0, 0.0, 0, 0.0, F, 0)]
              w, r2 = res[0], (res[1] if len(res) > 1 else (0.0, 0.0, 0.0, 0, 0.0, F, 0))   # monopoly: no runner-up
              if rot is not None and correctable:
                  if w[0] > 0 and w[1] > 0:
                      w_stale = 0
                  else:
                      w_stale += 1
                      if w_stale >= r_grace and not fallback:
                          fallback = True; w_fail = True
              if dorm_prof and not (w[0] > 0 and w[1] > 0):   # a gap left uncorrected wakes dormant arbs
                  for j in dorm_prof:
                      wake_at[j] = t_now + wake_s
              if correctable and not (w[0] > 0 and w[1] > 0) and min(fees) > F + 1e-6:
                  stalled_fee += 1
              traded = w[0] > 0 and w[1] > 0
              if correctable:
                  n_corr += 1; d_n += 1; w_corr += 1
                  if not traded:
                      n_uncorr += 1; d_stale += 1; w_uncorr += 1
              if traded:
                  if diverse:     # FCFS race: any arb that would profit can be first
                      prof = [k for k, x in enumerate(res) if x[0] > 0 and x[1] > 0]
                      rw = res[prof[rng.integers(len(prof))]]
                      d_wins[rw[6]] += 1; win_cnt[rw[6]] += 1; arb_inc[rw[6]] += rw[0]
                      last_win[rw[6]] = i * _DATA["step_s"]; wake_at[rw[6]] = np.inf
                  else:
                      win_cnt[w[6]] += 1; arb_inc[w[6]] += w[0] - max(r2[0], 0.0)
                      last_win[w[6]] = i * _DATA["step_s"]; wake_at[w[6]] = np.inf
                  V, kept = w[1], w[2]
                  if w[3]:
                      unst_n += 1; unst_vol += V
                  else:
                      vol_ep[w[6]] += V
                  if pm_v is None:
                      aw = gab - w[5]                        # edge beyond the fee this arb pays
                      E = (aw - V / (2 * D)) * V
                      extra_fee = (w[5] - F) * V             # fee above the pool fee, to LPs
                      fee_prem += extra_fee
                  else:
                      E = (gab - F - V / (2 * D)) * V
                      prem = (w[5] - F) * V; ch = E - kept; jw = w[6]
                      credit = max(prem - ch, 0.0)
                      excess = max(ch - prem, 0.0)           # charge beyond the premium: from stake
                      burn = min(excess, r_arb[jw]); r_arb[jw] -= burn
                      pm_leak += excess - burn
                      pend[jw] += (1 - TAU) * credit; pm_minted += (1 - TAU) * credit
                      extra_fee = -(excess - burn)           # uncovered charge is lost to LPs
                      fee_prem += prem
                  bid = max(r2[0], 0.0) + premium / 1e4 * V
                  lp_arb -= kept - extra_fee + premium / 1e4 * V
                  charge_tot += E - kept
                  builder += bid
                  margin += w[0] - max(r2[0], 0.0)
                  arb_vol += V
                  pass_trades[_pass] += 1; pass_vol[_pass] += V
                  if record:
                      trades.append((i, day[i], V, E, kept, w[4], m, p, G))   # p = post-trade ln price
                  p += math.copysign(V / D, G)
                  if (oi - p) * G < 0 and abs(oi - p) > 0.5e-4:
                      overshoot += 1
                  d_arb += 1
                  if r2[0] > 0:
                      d_cont += 1
                  if w[3]:
                      # an unstaked trade stops short of the band; staked arbs correct the
                      # remainder in the same block (second-price among them)
                      G2 = oi - p; a2 = abs(G2) - F
                      if a2 > 0:
                          _u, UNSTAKED = UNSTAKED, None
                          fees2 = [arb_fee(j) for j in range(n_arb)]
                          res2 = sorted(((*arb_choice(rule, abs(G2) - fees2[j], D, h, gas[i], m_blk, abs(G2)), h, fees2[j], j)
                                         for j, h in enumerate(costs)), reverse=True)
                          UNSTAKED = _u
                          w2 = res2[0]; r22 = res2[1] if len(res2) > 1 else (0.0, 0.0, 0.0, 0, 0.0, F, 0)
                          if w2[0] > 0 and w2[1] > 0:
                              V2, kept2 = w2[1], w2[2]
                              vol_ep[w2[6]] += V2
                              E2 = (abs(G2) - w2[5] - V2 / (2 * D)) * V2
                              xf2 = (w2[5] - F) * V2; fee_prem += xf2
                              lp_arb -= kept2 - xf2; charge_tot += E2 - kept2
                              builder += max(r22[0], 0.0); margin += w2[0] - max(r22[0], 0.0)
                              arb_vol += V2
                              p += math.copysign(V2 / D, G2)
        # self-referential staleness: resting gap beyond f + m + eps at block start,
        # and the block's first swap did not correct it (open phase only)
        traded_this_block = pass_trades[0] + pass_trades[1] > _trades_before
        if phase == "open" and _pre_gap > F + m + EPS_SR and (traded_this_block or es[i] < ee[i]):
            sr_obs += 1; w_sr_obs += 1; d_sr_obs += 1
            if STALE_RULE == "first_swap":
                first_corrects = traded_this_block or (xs[es[i]] * _pre_sign > 0)
            else:                                 # outcome: any point of the block within the band
                thr = F + m + EPS_SR
                first_corrects = abs(oi - p) <= thr   # after the arb phase (an unstaked arb may stop outside)
                if not first_corrects:
                    pp = p
                    for k in range(es[i], ee[i]):
                        pp += xs[k] * xv[k] / D
                        if abs(oi - pp) <= thr:
                            first_corrects = True; break
            if not first_corrects:
                sr_stale += 1; w_sr_stale += 1; d_sr_stale += 1
        if fast:
            w_n += 1
            if w_n >= _DATA["raise_steps"]:
                if feasible:
                    if w_sr_stale >= MIN_STALE_SR and w_sr_stale / w_sr_obs > S_STAR_SR:
                        m = min(m * RAISE_SR, 50e-4)
                elif w_corr >= 20 and w_uncorr / w_corr > s_star:
                    m = min(m * 2.0, 50e-4)
                w_n = w_corr = w_uncorr = w_sr_obs = w_sr_stale = 0
        post = abs(oi - p)                      # after the arb phase (open) / after everything (close, both)
        n += 1
        if post <= REB:
            reb += 1; stale_run = 0
        else:
            stale_run += 1
            if stale_run >= 2:
                persist2 += 1
        if i % 50 == 0:
            post_gaps.append(post)
        if phase == "open":
            for k in range(es[i], ee[i]):
                s = xs[k]; V = xv[k]
                pav = p + s * V / (2 * D)
                lp_exo += V * (F + s * (pav - oi))
                exo_gap_w += V * abs(p - oi); exo_vol += V
                p += s * V / D
        if relief is not None:
            eg = abs(oi - p)
            if eg > F + m + EPS_SR:
                relief_on = True; inband_s = 0.0
            elif eg <= F + m:
                inband_s += _DATA["step_s"]
                if inband_s >= r_hold:
                    relief_on = False
            rl_blocks += relief_on
        o_prev_blk = oi
        eob_n += 1
        if abs(oi - p) <= REB:
            eob_reb += 1
        if i % 50 == 0:
            eob_gaps.append(abs(oi - p))
    pg = np.array(post_gaps) * 1e4
    eg = np.array(eob_gaps) * 1e4
    pre = np.array(pre_gaps) * 1e4
    return {
        "rule": rule, "param": param, "scenario": scenario, "premium_bps": premium, "phase": phase,
        "end_of_block_within_band": round(eob_reb / max(eob_n, 1), 5),
        "selfref_stale_share": round(sr_stale / max(sr_obs, 1), 5),
        "arb_trades_by_pass": {"first": pass_trades[0], "second_after_users": pass_trades[1]},
        "arb_volume_b_by_pass": {"first": round(pass_vol[0] / 1e9, 3), "second_after_users": round(pass_vol[1] / 1e9, 3)},
        "end_of_block_gap_bps": {"p50": round(float(np.median(eg)), 2), "p90": round(float(np.percentile(eg, 90)), 2),
                                 "p99": round(float(np.percentile(eg, 99)), 2)},
        "lp_net_m": round((lp_arb + lp_exo) / 1e6, 3),
        "lp_from_arbs_m": round(lp_arb / 1e6, 3), "lp_from_users_m": round(lp_exo / 1e6, 3),
        "lp_recapture_m": round(charge_tot / 1e6, 3),
        "builder_payments_m": round(builder / 1e6, 3), "arb_margin_m": round(margin / 1e6, 3),
        "wins_by_arb": win_cnt.tolist(), "income_by_arb_m": [round(float(x) / 1e6, 4) for x in arb_inc],
        "winner_hhi": round(float(((win_cnt / max(win_cnt.sum(), 1)) ** 2).sum()), 4),
        "absent": absent, "m_end_bps": round(m * 1e4, 3),
        "rotation": rot, "rotation_failed_windows": (rot_fails if rot is not None else None),
        "unstaked": {"setting": UNSTAKED, "trades": unst_n, "volume_b": round(unst_vol / 1e9, 3)}, "stale_rule": STALE_RULE,
        "stake": {"usd": stake_K, "fmax_bps": round(fmax_fee * 1e4), "ramp_days": ramp_days, "alloc": "pooled" if pooled else "equal", "fee_premium_to_lps_m": round(fee_prem / 1e6, 3),
                  "correctable_blocks_uncorrected_for_lack_of_stake": stalled_fee,
                  "premium_mint_v": pm_v, "shock_k": shock_k, "shock_key": shock_key,
                  "relief": relief, "relief_trades": rl_trades, "relief_volume_b": round(rl_vol / 1e9, 3), "relief_on_blocks": rl_blocks, "rep_minted_to_arbs_m": round(pm_minted / 1e6, 3), "uncovered_charges_m": round(pm_leak / 1e6, 3),
                  "arb_stake_end_m": None if pm_v is None else round(float(r_arb.sum()) / 1e6, 3)}, "vol_x": vol_k,
        "arb_volume_b": round(arb_vol / 1e9, 3),
        "uncorrected_share_of_correctable": round(n_uncorr / max(n_corr, 1), 5),
        "uncorrected_hours": round(n_uncorr * _DATA["step_s"] / 3600, 2),
        "correctable_blocks": n_corr,
        "rebalanced_block_share": round(reb / n, 5),
        "blocks_stale_2plus": persist2,
        "overshoot_blocks": overshoot,
        "pre_arb_gap_bps_active_blocks": {"p50": round(float(np.median(pre)), 2), "p90": round(float(np.percentile(pre, 90)), 2),
                                          "p99": round(float(np.percentile(pre, 99)), 2)},
        "post_arb_gap_bps": {"p50": round(float(np.median(pg)), 2), "p90": round(float(np.percentile(pg, 90)), 2),
                             "p99": round(float(np.percentile(pg, 99)), 2)},
        "user_pretrade_staleness_bps_vw": round(exo_gap_w / max(exo_vol, 1) * 1e4, 3),
        "m_bps_final": round(m * 1e4, 4),
        "daily": daily if controlled else None,
        "_trades": np.array(trades) if record else None,
    }


def main(runs: list, workers: int = 8) -> list:
    """Workers fork from a parent that already holds the block arrays, so
    they share them copy-on-write (63M blocks on Arbitrum, ~3.5 GB)."""
    if not _DATA:
        _init()
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("fork")) as ex:
        return list(ex.map(run_one, runs))


GRID_M = [0.5, 1.0, 2.0, 5.0]
SCENARIOS = ("stable", "costs_x4", "costs_x8")
# Sensitivity scenarios (Study I assumptions): arb cost population (bp) and pool depth
POPULATIONS = {
    "pop_monopoly": [0.3], "pop_duo": [0.3, 0.6], "pop_ten": [0.3, 0.45, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0],
    "pop_cheap": [c * 0.5 for c in ARB_COSTS_BPS], "pop_dear": [c * 2.0 for c in ARB_COSTS_BPS],
}
SENSITIVITY = tuple(POPULATIONS) + ("depth_x0.5", "depth_x2")
RULES = ["avg_margin", "job_cap", "marginal_cap", "marginal_cap_gas"]


def grid() -> list:
    runs = []
    for sc in SCENARIOS:
        runs.append(("today", None, sc, 0.0))
        for r in RULES:
            runs += [(r, mm, sc, 0.0) for mm in GRID_M] + [(r, c, sc, 0.0) for c in ("ctl", "ctl_tight", "ctl_comp", "ctl_fast")]
        runs += [("marginal_cap_gas", "ctl_fast", sc, pr) for pr in (0.1, 0.5)]
        runs += [(r, c, sc, 0.0) for r in ("marginal_cap", "marginal_cap_gas") for c in ("ctl_feasible", "ctl_div")]
        runs += [(r, prm, sc, 0.0, ph) for r, prm in (("today", None), ("marginal_cap_gas", "ctl_fast"))
                 for ph in ("close", "both")]
    return runs


def keeps_rebalanced(r: dict, today: dict) -> bool:
    return bool(r["rebalanced_block_share"] >= today["rebalanced_block_share"] - REB_TOL
                and r["user_pretrade_staleness_bps_vw"] <= today["user_pretrade_staleness_bps_vw"] + USER_STALE_TOL_BPS)


def run() -> dict:
    res = main(grid())
    for r in res:
        r.pop("_trades", None)          # per-trade arrays are for Study C, never serialized
    calib = json.loads((CACHE / "calibration_inputs.json").read_text())
    today = {r["scenario"]: r for r in res if r["rule"] == "today" and r["phase"] == "open"}
    for r in res:
        t = today[r["scenario"]]
        r["lp_net_vs_today_m"] = round(r["lp_net_m"] - t["lp_net_m"], 3)
        # binding constraint: no worse rebalancing than today (+0.5pp tolerance)
        r["keeps_rebalanced"] = keeps_rebalanced(r, t)
    for sc in SCENARIOS:
        ok = [r for r in res if r["scenario"] == sc and r["keeps_rebalanced"]]
        best = max(ok, key=lambda r: r["lp_net_m"])
        out_best = {k: best[k] for k in ("rule", "param", "premium_bps", "phase", "lp_net_m", "lp_net_vs_today_m")}
        today[sc]["_best"] = out_best
    # Robust choice: must keep the pool rebalanced in EVERY scenario; ranked
    # by worst-case LP gain vs today. A static m that only works when you
    # already know arb costs is hindsight, not a design.
    key = lambda r: (r["rule"], str(r["param"]), r["premium_bps"], r["phase"])
    by = {}
    for r in res:
        by.setdefault(key(r), []).append(r)
    robust = []
    for k, rs in by.items():
        if k[0] == "today" or not all(r["keeps_rebalanced"] for r in rs):
            continue
        robust.append({"rule": k[0], "param": k[1], "premium_bps": k[2], "phase": k[3],
                       "worst_lp_vs_today_m": float(min(r["lp_net_vs_today_m"] for r in rs)),
                       "by_scenario": {r["scenario"]: float(r["lp_net_vs_today_m"]) for r in rs}})
    robust.sort(key=lambda x: -x["worst_lp_vs_today_m"])
    out = {
        "robust_ranking": robust,
        "assumptions": {"pool_fee": F, "rebalanced_band_bps": REB * 1e4, "job_band_bps": B_JOB * 1e4,
                        "arb_costs_bps": ARB_COSTS_BPS, "cost_shocks_from": "2026-06-01 (x4, x8)",
                        "controller": {"s_star": S_STAR, "s_low": S_LOW, "tau_contested": TAU_C}},
        "calibration": {"real": {k: calib[k] for k in ("real_lp_markout_m", "real_pre_first_swap_gap_bps",
                                                       "arb_like_volume_b", "depth_usd_per_bp_median")},
                        "simulated_today_stable": {k: today["stable"][k] for k in (
                            "lp_net_m", "lp_from_arbs_m", "lp_from_users_m", "arb_volume_b",
                            "pre_arb_gap_bps_active_blocks")}},
        "best_keeping_rebalanced": {sc: today[sc].pop("_best") for sc in SCENARIOS},
        "runs": res,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(out, indent=1))
    return out


def run_sensitivity() -> dict:
    """Assumption sensitivity: arb cost population and pool depth, for the
    feasible controllers and a static allowance. Written beside metrics.json."""
    runs = []
    for sc in ("stable",) + SENSITIVITY:
        runs.append(("today", None, sc, 0.0))
        runs += [("marginal_cap_gas", p, sc, 0.0) for p in ("ctl_feasible", "ctl_div", 5.0)]
    res = main(runs)
    today = {r["scenario"]: r for r in res if r["rule"] == "today"}
    rows = []
    for r in res:
        r.pop("_trades", None)
        t = today[r["scenario"]]
        rows.append({k: r[k] for k in ("scenario", "rule", "param", "lp_net_m", "builder_payments_m", "rebalanced_block_share",
                                       "user_pretrade_staleness_bps_vw", "uncorrected_hours", "m_bps_final")}
                    | {"lp_net_vs_today_m": round(r["lp_net_m"] - t["lp_net_m"], 3), "keeps_rebalanced": keeps_rebalanced(r, t)})
    out = {"populations_bps": POPULATIONS, "depth_scenarios": ["depth_x0.5", "depth_x2"], "runs": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sensitivity.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    import sys
    import time
    if sys.argv[1:] == ["sensitivity"]:
        for r in run_sensitivity()["runs"]:
            print(r)
        raise SystemExit(0)
    t = time.time()
    out = run()
    print(json.dumps(out["calibration"], indent=1))
    for r in out["runs"]:
        print(f"{r['scenario']:8} {r['rule']:12} m={str(r['param']):4} prem={r['premium_bps']:<3} "
              f"LP {r['lp_net_m']:+6.2f} (vs today {r['lp_net_vs_today_m']:+5.2f}) recap {r['lp_recapture_m']:5.2f} "
              f"builder {r['builder_payments_m']:5.2f} arbmargin {r['arb_margin_m']:4.2f} vol {r['arb_volume_b']:5.2f}B "
              f"uncorr {r['uncorrected_share_of_correctable']*100:5.2f}% {'OK ' if r['keeps_rebalanced'] else 'BAD'} reb {r['rebalanced_block_share']*100:6.2f}% overshoot {r['overshoot_blocks']:>6} "
              f"user_stale {r['user_pretrade_staleness_bps_vw']:5.2f} post_p90 {r['post_arb_gap_bps']['p90']:5.2f} m_end {r['m_bps_final']}")
    print("BEST per scenario (hindsight):", json.dumps(out["best_keeping_rebalanced"]))
    print("ROBUST RANKING (rebalanced in every scenario, worst-case LP gain vs today):")
    for x in out["robust_ranking"]:
        print("  ", x)
    print(f"{time.time()-t:.0f}s")
