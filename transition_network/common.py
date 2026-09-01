"""Shared config for the career-transition-network builder (Phases 1-2).

The spine (`paths/transitions.parquet`) carries both endpoints of every move on
*every* resolved axis. A transition network is just that edge list aggregated to
a chosen **node grain** and normalized against a null model. This module is the
single place that defines the available grains and where outputs land. See
`../CAREER_TRANSITION_NETWORK_PLAN.md` §4.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSITIONS = ROOT / "paths" / "transitions.parquet"
ONET_OCC = ROOT / "reference" / "onet_occupation_data.txt"
OUT_DIR = ROOT / "transition_network"


class Axis:
    """A node grain: which spine columns are the from/to node ids, plus a human
    label. ``label_strip`` removes a canonical-id prefix (``id:`` / ``soc:``)
    for display; ``label_ref`` names an optional reference label join."""

    def __init__(self, name: str, from_col: str, to_col: str,
                 label_ref: str | None = None, label_strip: str | None = None):
        self.name = name
        self.from_col = from_col
        self.to_col = to_col
        self.label_ref = label_ref
        self.label_strip = label_strip


# Registry of node grains. occupation is the v1 default — it matches the
# published occupational-mobility-network baselines (Mealy/del Rio-Chanona).
AXES: dict[str, Axis] = {
    "occupation": Axis("occupation", "from_occupation", "to_occupation",
                       label_ref="onet"),
    "role": Axis("role", "from_role", "to_role"),
    "company": Axis("company", "from_company", "to_company", label_strip="id:"),
    "employment_type": Axis("employment_type", "from_employment_type",
                            "to_employment_type"),
    "seniority": Axis("seniority", "from_seniority_ordinal",
                      "to_seniority_ordinal"),
}

# Edges below this transition count are dropped from the *backbone* (Phase 3);
# Phase 1-2 keep everything and only annotate, so analysis can pick a threshold.
DEFAULT_MIN_SUPPORT = 1

# SOC major groups (2-digit prefix) — taxonomy baseline for community cross-tabs
# and occupation-change typing. Public, stable BLS classification.
SOC_MAJOR = {
    "11": "Management", "13": "Business & Financial",
    "15": "Computer & Mathematical", "17": "Architecture & Engineering",
    "19": "Life/Physical/Social Science", "21": "Community & Social Service",
    "23": "Legal", "25": "Education", "27": "Arts/Design/Media",
    "29": "Healthcare Practitioners", "31": "Healthcare Support",
    "33": "Protective Service", "35": "Food Preparation & Serving",
    "37": "Building & Grounds", "39": "Personal Care", "41": "Sales",
    "43": "Office & Admin Support", "45": "Farming/Fishing/Forestry",
    "47": "Construction & Extraction", "49": "Installation/Maint/Repair",
    "51": "Production", "53": "Transportation", "55": "Military",
}

# Edge kinds that are NOT seniority comparisons -> excluded from the SpringRank
# revealed-seniority graph (they are state changes, not up/down moves).
NON_SENIORITY_KINDS = ("exit", "education_entry",
                       "into_self_employment", "out_of_self_employment")


def springrank(src, dst, weight, n: int, alpha: float = 1.0):
    """Regularized SpringRank (De Bacco, Larremore, Moore 2018): real-valued node
    ranks minimizing spring energy over a directed weighted edge list, via a
    sparse linear solve. `src`/`dst` are integer node indices, `weight` the edge
    weights; `alpha`>0 regularizes the otherwise-singular system (gauge fix).

    Convention: edge i->j rewards s_i = s_j + 1 (source ranks above). Our edges are
    moves *from* i *to* j, so destinations are typically more senior -> callers
    orient the axis against a lexical anchor downstream (sign is not assumed here).
    """
    import numpy as np
    import scipy.sparse as sp
    from scipy.sparse.linalg import bicgstab

    w = np.asarray(weight, dtype=float)
    A = sp.csr_matrix((w, (np.asarray(src), np.asarray(dst))), shape=(n, n))
    k_out = np.asarray(A.sum(axis=1)).ravel()
    k_in = np.asarray(A.sum(axis=0)).ravel()
    B = (alpha * sp.eye(n) + sp.diags(k_out + k_in) - (A + A.T)).tocsr()
    s, _ = bicgstab(B, k_out - k_in, atol=1e-10, maxiter=2000)
    return s
