"""Study A — classifier validation (§17.1/§17.8).

ROC-AUC of q_LP (score = -q_lp, higher = more toxic) against the
independent labels, plus overlaid histograms and slices by trade size
and block position. Gate: AUC > 0.75 on high-confidence labels.

Outputs: results/study_a/metrics.json + histograms + ROC curve PNGs.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import canonical
from .config import DATA_DIR, HORIZONS_S, REPO_ROOT, ONCHAIN_DIR, RESULTS_DIR
from .pools import STUDY_POOL

SCORED_DIR = ONCHAIN_DIR / "scored" / STUDY_POOL.name
LABELS_DIR = ONCHAIN_DIR / "labels" / STUDY_POOL.name
OUT_DIR = RESULTS_DIR / "study_a"


def mann_whitney_auc(score_toxic: np.ndarray, score_benign: np.ndarray) -> float:
    """AUC = P(toxic score > benign score) via rank statistic."""
    both = np.concatenate([score_toxic, score_benign])
    ranks = pd.Series(both).rank().to_numpy()
    r_toxic = ranks[: len(score_toxic)].sum()
    n_t, n_b = len(score_toxic), len(score_benign)
    return float((r_toxic - n_t * (n_t + 1) / 2) / (n_t * n_b))


def load_joined() -> pd.DataFrame:
    scored = pd.concat(pd.read_parquet(p) for p in sorted(SCORED_DIR.glob("*.scored.parquet")))
    labels = pd.concat(pd.read_parquet(p) for p in sorted(LABELS_DIR.glob("*.labels.parquet")))
    df = scored.merge(
        labels[["tx_hash", "log_index", "label", "toxic_sandwich", "toxic_searcher", "sandwich_victim"]],
        on=["tx_hash", "log_index"],
        how="left",
    )
    return df


def run() -> dict:
    base = load_joined()
    out = compute(canonical.apply(base, "canonical"), plot=True)
    legacy = compute(canonical.apply(base, "legacy_forward"), plot=False)
    out = {"timeline": canonical.DESCRIPTION["canonical"], **out,
           "legacy_forward_trade_price": legacy}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "metrics.json").write_text(json.dumps(out, indent=2))
    return out


def compute(df: pd.DataFrame, plot: bool) -> dict:
    labeled = df[df["label"].notna()].copy()
    out: dict = {"n_total": len(df), "n_toxic": int((labeled.label == "toxic").sum()),
                 "n_benign": int((labeled.label == "benign").sum())}

    for h in HORIZONS_S:
        col = f"q_lp_h{h}"
        sub = labeled.dropna(subset=[col])
        tox = -sub.loc[sub.label == "toxic", col].to_numpy()
        ben = -sub.loc[sub.label == "benign", col].to_numpy()
        out[f"auc_h{h}"] = mann_whitney_auc(tox, ben)

    # Slices at h=0
    sub = labeled.dropna(subset=["q_lp_h0"])
    for lo, hi, name in STUDY_POOL.size_buckets():
        s = sub[(sub.notional_token0 >= lo) & (sub.notional_token0 < hi)]
        if (s.label == "toxic").sum() > 50 and (s.label == "benign").sum() > 50:
            out[f"auc_h0_size_{name}"] = mann_whitney_auc(
                -s.loc[s.label == "toxic", "q_lp_h0"].to_numpy(),
                -s.loc[s.label == "benign", "q_lp_h0"].to_numpy(),
            )
    for top, name in [(True, "top3"), (False, "mid_block")]:
        s = sub[(sub.tx_index <= 3) == top]
        if (s.label == "toxic").sum() > 50 and (s.label == "benign").sum() > 50:
            out[f"auc_h0_pos_{name}"] = mann_whitney_auc(
                -s.loc[s.label == "toxic", "q_lp_h0"].to_numpy(),
                -s.loc[s.label == "benign", "q_lp_h0"].to_numpy(),
            )

    if not plot:
        return out
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 5))
        bins = np.linspace(-30, 30, 121)
        for lbl, color in [("benign", "#2c7fb8"), ("toxic", "#d95f0e")]:
            q = sub.loc[sub.label == lbl, "q_lp_h0"] * 1e4
            ax.hist(q.clip(-30, 30), bins=bins, density=True, alpha=0.55, label=f"{lbl} (n={len(q):,})", color=color)
        ax.set_xlabel("q_LP at h=0 (bps)"); ax.set_ylabel("density")
        ax.set_title(f"q_LP by label — AUC(h0) = {out['auc_h0']:.3f}")
        ax.legend(); fig.tight_layout()
        fig.savefig(OUT_DIR / "qlp_histograms.png", dpi=150)
    except ImportError:
        print("matplotlib missing — metrics.json only")

    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
