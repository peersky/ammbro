"""Study I: the block-position index on today's pools (paper §4.4, Figure 4).

For each block with a price-correcting swap in the pool, the closing position π_c is the block
fraction (tx_index + ½) / tx_count of its first correcting swap, and π_r that of its earliest
non-correcting swap. The index is z = ln(π_r / π_c): negative when retail traded first (late),
above ln κ when the correction leads retail by more than a factor κ (urgent). Corrections are split
by whether they earned rent today (gap beyond fee, hedge and gas), a proxy for contested slots.

    AMMBRO_CHAIN=mainnet|arbitrum uv run python -m pipeline.study_i_index → <results>/study_i/block_index.json
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import study_h as H
from .chains import ACTIVE
from .config import RESULTS_DIR

QS = np.round(np.linspace(0.01, 0.99, 99), 2)
EDGES = np.logspace(-3, 0, 31)


def auc(y: np.ndarray, s: np.ndarray) -> float:
    rk = pd.Series(s).rank().to_numpy(); n1 = int(y.sum()); n0 = len(y) - n1
    return float((rk[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def main() -> dict:
    df, _ = H.prepare()
    df["pos"] = (df["tx_index"] + 0.5) / df["tx_count"].clip(lower=1)
    c = (df[df["correcting"] & df["q_c_h0"].notna()].groupby("block_number").head(1)
         [["block_number", "pos", "rent_today"]])
    r = df[~df["correcting"]].groupby("block_number")["pos"].min().rename("pos_r")
    m = c.join(r, on="block_number").dropna()
    z = np.log(m.pos_r / m.pos).to_numpy()
    y = (m.rent_today > 0).to_numpy()
    q = lambda a: [round(float(x), 4) for x in np.quantile(a, QS)]
    out = {"chain": ACTIVE.name, "blocks_with_correction": int(len(c)), "blocks_with_retail": int(len(m)),
           "contested_share": round(float(y.mean()), 4), "quantile_levels": QS.tolist(),
           "z_quantiles_contested": q(z[y]), "z_quantiles_uncontested": q(z[~y]),
           "late_share": round(float((z < 0).mean()), 4),
           "urgent_share": {str(k): round(float((z > np.log(k)).mean()), 4) for k in (2, 4)},
           "auc_z_contested": round(auc(y, z), 4),
           "pos_bin_edges": EDGES.tolist(),
           "pos_hist_correction": np.histogram(np.clip(m.pos, EDGES[0], 1), EDGES)[0].tolist(),
           "pos_hist_retail": np.histogram(np.clip(m.pos_r, EDGES[0], 1), EDGES)[0].tolist(),
           "pos_quantiles_correction": q(m.pos), "pos_quantiles_retail": q(m.pos_r)}
    p = RESULTS_DIR / "study_i" / "block_index.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    o = main()
    print({k: v for k, v in o.items() if "quantile" not in k})
