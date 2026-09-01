"""Head-to-head evaluation of revealed-seniority / hierarchy methods.

    uv run --group graph python -m transition_network.revealed_seniority_eval occupation
    uv run --group graph python -m transition_network.revealed_seniority_eval role
    uv run --group graph python -m transition_network.revealed_seniority_eval both --out FILE

Read-only on the production data. Builds several node-rank "revealed seniority"
signals on the SAME directed transition graph that `transition_network.analyze`
uses (edges = `<axis>_edges.parquet`, weight choices below, NON_SENIORITY_KINDS
and self-loops excluded), then scores each against a LEXICAL SILVER TRUTH using
the same construction as `paths/tune_thresholds.py`.

Methods (all produce a real-valued node rank; higher = more senior, oriented
against the lexical anchor so signs are comparable):
  - springrank_npersons   : the production baseline (weight = n_persons).
  - springrank_rr          : SpringRank, weight = relative_risk (size-controlled).
  - springrank_rr_logn     : SpringRank, weight = relative_risk * log1p(n_persons).
  - davids_score           : David's Score from flow-asymmetry win proportions.
  - min_violation_agony     : eigen/iterative minimum-violation (agony) rank.
  - trophic_level           : MacKay/Johnson trophic levels (linear solve).

Silver truth: on graph edges where BOTH endpoints carry a named lexical seniority
token (built per-graph from `paths/transitions.parquet`), sign(mean Δlexical
ordinal) is the truth. A method predicts direction via sign(rank[to]-rank[from]);
we report coverage / directional accuracy / up-precision / down-precision over a
threshold sweep on the rank gap. Secondary anchors: Spearman vs O*NET job-zone
(occupation only), Spearman vs per-node mean lexical ordinal, and the gold ladders.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.sparse.linalg import bicgstab
from scipy.stats import spearmanr

from transition_network import common as C

TAUS = [0.0, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30, 0.50, 1.0]

# Gold occupation ladders (must come out "up"); SOC codes resolved by label.
GOLD_OCC_LADDERS = [
    ("Registered Nurses", "Nurse Practitioners"),
    ("Cooks, Restaurant", "Chefs and Head Cooks"),
    ("Police and Sheriff's Patrol Officers",
     "Detectives and Criminal Investigators"),
]


# --------------------------------------------------------------------------- #
# Graph loading: replicate analyze.py's seniority subgraph exactly.            #
# --------------------------------------------------------------------------- #
def load_graph(axis: str, con: duckdb.DuckDBPyConnection) -> dict:
    """Return node ids, integer src/dst, and the three candidate edge weights
    (n_persons, relative_risk, rr*log1p(n_persons)) for the seniority subgraph
    (non-self, NON_SENIORITY_KINDS excluded) of the chosen axis."""
    edges_in = C.OUT_DIR / f"{axis}_edges.parquet"
    kinds = ",".join(f"'{k}'" for k in C.NON_SENIORITY_KINDS)
    e = con.sql(f"""
        SELECT from_node, to_node, n_persons, relative_risk
        FROM read_parquet('{edges_in}')
        WHERE NOT is_self_loop
          AND modal_kind NOT IN ({kinds})
          AND n_persons > 0
    """).df()
    nodes = pd.unique(pd.concat([e["from_node"], e["to_node"]], ignore_index=True))
    nodes = np.sort(nodes)
    idx = {n: i for i, n in enumerate(nodes)}
    src = e["from_node"].map(idx).to_numpy()
    dst = e["to_node"].map(idx).to_numpy()
    npers = e["n_persons"].to_numpy(dtype=float)
    rr = e["relative_risk"].to_numpy(dtype=float)
    rr = np.where(np.isfinite(rr) & (rr > 0), rr, 0.0)
    weights = {
        "n_persons": npers,
        "relative_risk": rr,
        "rr_logn": rr * np.log1p(npers),
    }
    return {"nodes": nodes, "idx": idx, "src": src, "dst": dst,
            "n": len(nodes), "weights": weights}


# --------------------------------------------------------------------------- #
# Methods. Each returns a real-valued node rank vector (length n).             #
# Orientation is fixed downstream against the lexical anchor.                  #
# --------------------------------------------------------------------------- #
def springrank(src, dst, w, n, alpha=1.0):
    """Regularized SpringRank (identical math to common.springrank)."""
    A = sp.csr_matrix((w, (src, dst)), shape=(n, n))
    k_out = np.asarray(A.sum(axis=1)).ravel()
    k_in = np.asarray(A.sum(axis=0)).ravel()
    B = (alpha * sp.eye(n) + sp.diags(k_out + k_in) - (A + A.T)).tocsr()
    s, _ = bicgstab(B, k_out - k_in, atol=1e-10, maxiter=2000)
    # common.springrank's "source higher" convention -> invert so to-node senior
    return -s


def davids_score(src, dst, w, n):
    """David's Score from a dyadic dominance matrix, computed SPARSELY so it
    scales to the 1.9M-node role graph. For each present ordered pair we form
    Pij = wij/(wij+wji) (proportion of flow i->j), variance-stabilized to
    Dij = Pij - 0.5. David's Score = (w1+w2) - (l1+l2) with w1=row sums (wins),
    l1=col sums (losses), w2=D@w1, l2=D^T@l1. A move i->j is a 'win' for the
    DESTINATION (more senior), so we build the dominance matrix on the transpose
    of the flow (winner index = dst). The dyadic index D is only nonzero on
    present edges (or their reciprocals), so it stays sparse."""
    # W[i,j] = flow j->i  (i.e. i "wins" against j) ; aggregate parallel edges
    W = sp.csr_matrix((w, (dst, src)), shape=(n, n))
    Wt = W.T.tocsr()
    T = (W + Wt).tocsr()             # symmetric total dyadic interaction
    # P = W / T on the support of T; D = P - 0.5 on that same support.
    Tc = T.tocoo()
    wv = np.asarray(W[Tc.row, Tc.col]).ravel()
    P = wv / Tc.data
    D = sp.csr_matrix((P - 0.5, (Tc.row, Tc.col)), shape=(n, n))
    w1 = np.asarray(D.sum(axis=1)).ravel()   # summed wins
    l1 = np.asarray(D.sum(axis=0)).ravel()   # summed losses
    w2 = D.dot(w1)                            # weighted second-order wins
    l2 = D.T.dot(l1)
    return w1 + w2 - l1 - l2


def trophic_level(src, dst, w, n):
    """MacKay/Johnson trophic levels: solve L h = (k_in - k_out) restricted to
    weakly-connected components, where L = diag(u) - (A + A^T), u = in+out
    strength. Within each component fix a gauge (mean 0). Higher h = downstream
    (sink) = more senior under our destination-senior convention."""
    A = sp.csr_matrix((w, (src, dst)), shape=(n, n))
    k_in = np.asarray(A.sum(axis=0)).ravel()
    k_out = np.asarray(A.sum(axis=1)).ravel()
    u = k_in + k_out
    L = sp.diags(u) - (A + A.T)
    b = k_in - k_out
    # weakly-connected components for gauge fixing / singular handling
    nc, lab = sp.csgraph.connected_components(A + A.T, directed=False)
    h = np.zeros(n)
    for c in range(nc):
        m = np.where(lab == c)[0]
        if len(m) == 1:
            continue
        Lc = L[m][:, m].tocsr()
        bc = b[m]
        # regularize the singular (gauge) direction
        Lc = Lc + 1e-9 * sp.eye(len(m))
        hc, _ = bicgstab(Lc, bc, atol=1e-10, maxiter=4000)
        h[m] = hc - hc.mean()
    return h


def min_violation_agony(src, dst, w, n, iters=200):
    """Minimum-violation ranking via the Gauss-Seidel/eigen-style iteration of
    De Bacco-like agony minimization. We use a tractable iterative scheme: each
    node's rank is pulled toward (downstream_mean + 1) and (upstream_mean - 1),
    i.e. r_i relaxes to balance incoming (should be below) and outgoing (above)
    edges by one rung. This converges to a min-violation-style ordering and is
    O(E) per sweep, so it scales to the role graph. Higher r = more senior."""
    r = np.zeros(n)
    # precompute neighbor weight sums
    A = sp.csr_matrix((w, (src, dst)), shape=(n, n))
    AT = A.T.tocsr()
    k_out = np.asarray(A.sum(axis=1)).ravel()
    k_in = np.asarray(A.sum(axis=0)).ravel()
    denom = k_out + k_in
    denom[denom == 0] = 1.0
    for _ in range(iters):
        # target from out-edges i->j: j should be ~ r_i+1  => r_i ~ E_j[r_j]-1
        # target from in-edges k->i: r_i ~ E_k[r_k]+1
        out_term = A.dot(r) - k_out          # sum_j w*(r_j - 1)
        in_term = AT.dot(r) + k_in           # sum_k w*(r_k + 1)
        r_new = (out_term + in_term) / denom
        r_new -= r_new.mean()
        if np.max(np.abs(r_new - r)) < 1e-7:
            r = r_new
            break
        r = r_new
    return r


METHODS = {
    "springrank_npersons": ("springrank", "n_persons"),
    "springrank_rr": ("springrank", "relative_risk"),
    "springrank_rr_logn": ("springrank", "rr_logn"),
    "davids_score": ("davids", "n_persons"),
    "min_violation_agony": ("agony", "n_persons"),
    "trophic_level": ("trophic", "n_persons"),
}


def compute_rank(method: str, g: dict) -> np.ndarray:
    kind, wkey = METHODS[method]
    w = g["weights"][wkey]
    s, d, n = g["src"], g["dst"], g["n"]
    if kind == "springrank":
        return springrank(s, d, w, n)
    if kind == "davids":
        return davids_score(s, d, w, n)
    if kind == "agony":
        return min_violation_agony(s, d, w, n)
    if kind == "trophic":
        return trophic_level(s, d, w, n)
    raise ValueError(method)


# --------------------------------------------------------------------------- #
# Silver truth + evaluation harness.                                           #
# --------------------------------------------------------------------------- #
def silver_edges(axis: str, con: duckdb.DuckDBPyConnection,
                 idx: dict) -> pd.DataFrame:
    """Per node-pair lexical direction from persons carrying BOTH lexical tokens
    (mirrors tune_thresholds' silver construction, aggregated to graph edges)."""
    fcol = {"occupation": "from_occupation", "role": "from_role"}[axis]
    tcol = {"occupation": "to_occupation", "role": "to_role"}[axis]
    df = con.sql(f"""
        SELECT {fcol} AS f, {tcol} AS t,
               avg(to_seniority_ordinal - from_seniority_ordinal) AS lex_delta,
               count(*) AS n
        FROM read_parquet('{C.TRANSITIONS}')
        WHERE from_seniority_ordinal IS NOT NULL
          AND to_seniority_ordinal IS NOT NULL
          AND {fcol} IS NOT NULL AND {tcol} IS NOT NULL
          AND {fcol} <> {tcol}
        GROUP BY 1, 2
    """).df()
    df = df[df["lex_delta"] != 0].copy()
    df["fi"] = df["f"].map(idx)
    df["ti"] = df["t"].map(idx)
    df = df.dropna(subset=["fi", "ti"])
    df["fi"] = df["fi"].astype(int)
    df["ti"] = df["ti"].astype(int)
    df["lex_dir"] = np.sign(df["lex_delta"].to_numpy())
    return df


def node_mean_lex(axis: str, con: duckdb.DuckDBPyConnection,
                  nodes: np.ndarray, idx: dict) -> np.ndarray:
    """Per-node mean lexical ordinal (secondary anchor)."""
    if axis == "role":
        df = con.sql(f"""
            SELECT role_canonical AS node, avg(seniority_ordinal) AS m
            FROM read_parquet('{C.ROOT / "paths" / "steps.parquet"}')
            WHERE role_canonical IS NOT NULL AND seniority_ordinal IS NOT NULL
            GROUP BY 1
        """).df()
    else:
        # occupation: mean lexical ordinal of moves touching that occupation
        df = con.sql(f"""
            SELECT node, avg(o) AS m FROM (
              SELECT from_occupation AS node, from_seniority_ordinal AS o
              FROM read_parquet('{C.TRANSITIONS}')
              WHERE from_seniority_ordinal IS NOT NULL AND from_occupation IS NOT NULL
              UNION ALL
              SELECT to_occupation AS node, to_seniority_ordinal AS o
              FROM read_parquet('{C.TRANSITIONS}')
              WHERE to_seniority_ordinal IS NOT NULL AND to_occupation IS NOT NULL
            ) GROUP BY 1
        """).df()
    out = np.full(len(nodes), np.nan)
    m = df.set_index("node")["m"].to_dict()
    for n, i in idx.items():
        if n in m:
            out[i] = m[n]
    return out


def orient(rank: np.ndarray, mean_lex: np.ndarray) -> np.ndarray:
    """Flip the rank so it increases with the lexical anchor (sign is arbitrary
    for every undirected-energy method)."""
    ok = np.isfinite(rank) & np.isfinite(mean_lex)
    if ok.sum() < 3:
        return rank
    c = np.corrcoef(rank[ok], mean_lex[ok])[0, 1]
    return -rank if (np.isfinite(c) and c < 0) else rank


def eval_silver(rank: np.ndarray, silver: pd.DataFrame, taus) -> dict:
    gap = rank[silver["ti"].to_numpy()] - rank[silver["fi"].to_numpy()]
    truth = silver["lex_dir"].to_numpy()
    # normalize gap by its own scale so the tau sweep is comparable across methods
    scale = np.std(gap) or 1.0
    gnorm = gap / scale
    rows = []
    for tau in taus:
        fire = np.abs(gnorm) > tau
        if fire.sum() == 0:
            rows.append({"tau": tau, "coverage": 0.0, "dir_acc": np.nan,
                         "up_prec": np.nan, "down_prec": np.nan})
            continue
        pred = np.sign(gnorm[fire])
        tr = truth[fire]
        acc = (pred == tr).mean()
        up = pred > 0
        dn = pred < 0
        up_p = (tr[up] > 0).mean() if up.any() else np.nan
        dn_p = (tr[dn] < 0).mean() if dn.any() else np.nan
        rows.append({"tau": tau, "coverage": float(fire.mean()),
                     "dir_acc": float(acc), "up_prec": float(up_p),
                     "down_prec": float(dn_p)})
    # headline = tau-0 (full coverage) directional accuracy + up/down precision
    base = rows[0]
    return {"sweep": rows, "n_silver": int(len(silver)),
            "dir_acc_full": base["dir_acc"], "up_prec_full": base["up_prec"],
            "down_prec_full": base["down_prec"]}


def eval_gold_ladders(axis: str, rank: np.ndarray, idx: dict,
                      con: duckdb.DuckDBPyConnection) -> dict:
    if axis != "occupation":
        return {}
    lab2soc = {r[0]: r[1] for r in con.sql(f"""
        SELECT DISTINCT from_label, from_node
        FROM read_parquet('{C.OUT_DIR / "occupation_edges.parquet"}')
    """).fetchall()}
    res = {}
    for lo, hi in GOLD_OCC_LADDERS:
        slo, shi = lab2soc.get(lo), lab2soc.get(hi)
        if slo in idx and shi in idx:
            res[f"{lo} -> {hi}"] = bool(rank[idx[shi]] > rank[idx[slo]])
    return res


def run_axis(axis: str, con: duckdb.DuckDBPyConnection,
             methods: list[str]) -> dict:
    t0 = time.monotonic()
    g = load_graph(axis, con)
    load_s = time.monotonic() - t0
    print(f"[{axis}] graph: {g['n']:,} nodes, {len(g['src']):,} edges "
          f"(loaded {load_s:.1f}s)", flush=True)

    silver = silver_edges(axis, con, g["idx"])
    print(f"[{axis}] silver edges (node-pairs, both lexical, nonflat): "
          f"{len(silver):,} (up {int((silver.lex_dir>0).sum()):,} / "
          f"down {int((silver.lex_dir<0).sum()):,})", flush=True)
    mean_lex = node_mean_lex(axis, con, g["nodes"], g["idx"])

    job_zone = None
    if axis == "occupation":
        sz = con.sql(f"""
            SELECT soc_code, job_zone_norm
            FROM read_parquet('{C.ROOT / "reference" / "soc_status.parquet"}')
        """).df().set_index("soc_code")["job_zone_norm"].to_dict()
        job_zone = np.array([sz.get(n, np.nan) for n in g["nodes"]])

    results = {}
    for m in methods:
        mt = time.monotonic()
        rank = compute_rank(m, g)
        rank = orient(rank, mean_lex)
        runtime = time.monotonic() - mt

        sv = eval_silver(rank, silver, TAUS)
        ok = np.isfinite(rank) & np.isfinite(mean_lex)
        rho_lex = spearmanr(rank[ok], mean_lex[ok]).statistic if ok.sum() > 3 else np.nan
        rho_jz = np.nan
        if job_zone is not None:
            okz = np.isfinite(rank) & np.isfinite(job_zone)
            if okz.sum() > 3:
                rho_jz = spearmanr(rank[okz], job_zone[okz]).statistic
        ladders = eval_gold_ladders(axis, rank, g["idx"], con)
        gold_ok = sum(ladders.values()) if ladders else None
        gold_tot = len(ladders) if ladders else None

        results[m] = {
            "dir_acc": sv["dir_acc_full"], "up_prec": sv["up_prec_full"],
            "down_prec": sv["down_prec_full"], "n_silver": sv["n_silver"],
            "spearman_mean_lex": float(rho_lex),
            "spearman_job_zone": float(rho_jz) if np.isfinite(rho_jz) else None,
            "gold_ladders": ladders, "gold_pass": gold_ok, "gold_total": gold_tot,
            "runtime_s": round(runtime, 2), "sweep": sv["sweep"],
        }
        print(f"[{axis}] {m:>22}: acc={sv['dir_acc_full']:.3f} "
              f"up={sv['up_prec_full']:.3f} down={sv['down_prec_full']:.3f} "
              f"rho_lex={rho_lex:.3f} rho_jz="
              f"{rho_jz if np.isfinite(rho_jz) else float('nan'):.3f} "
              f"gold={gold_ok}/{gold_tot} t={runtime:.1f}s", flush=True)

    return {"axis": axis, "n_nodes": g["n"], "n_edges": int(len(g["src"])),
            "n_silver": int(len(silver)), "methods": results}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("axis", nargs="?", default="both",
                   choices=["occupation", "role", "both"])
    p.add_argument("--methods", default=",".join(METHODS))
    p.add_argument("--out", default=None, help="write JSON results here")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    axes = ["occupation", "role"] if args.axis == "both" else [args.axis]
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    out = {}
    for ax in axes:
        out[ax] = run_axis(ax, con, methods)
    con.close()
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, default=str))
        print(f"\nwrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
