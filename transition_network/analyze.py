"""Analyze a built transition network: backbone, centrality, communities.

    uv run --group graph python -m transition_network.analyze occupation

Phases 3-4 of CAREER_TRANSITION_NETWORK_PLAN.md, consuming the Phase 1-2 output
(`<axis>_edges.parquet`, `<axis>_nodes.parquet`):

  Phase 3 — backbone (disparity filter) + node centrality (PageRank attractors,
            betweenness bridges, HITS hub/authority, net-flow source/sink).
  Phase 4 — community detection: Infomap (directed, flow-based, on raw transition
            volume) AND Leiden (modularity, on size-controlled relative_risk),
            then cross-tabbed against SOC major groups to show what the revealed
            structure captures that the taxonomy does not.

Scale note: at the occupation grain (~824 nodes) this is instant on CPU; igraph
handles centrality and the methods are exact. The GPU path (cuGraph) only becomes
relevant at the company/title grain (millions of nodes), where cuGraph is not yet
installable on this env's Python 3.14 — revisit with a pinned RAPIDS env then.

Outputs: `<axis>_nodes_analyzed.parquet`, `<axis>_backbone_edges.parquet`,
`<axis>_communities.json`, `<axis>_analyze_manifest.json`.
"""

from __future__ import annotations

import argparse
import json
import time

import duckdb
import igraph as ig
import numpy as np
import pandas as pd
from infomap import Infomap

from transition_network import common as C
from transition_network.common import SOC_MAJOR

# Above these node counts the O(VE) / O(n^2) metrics are skipped so large grains
# (role: ~1.5M nodes) stay feasible; PageRank + SpringRank always run.
MAX_NODES_BETWEENNESS = 20_000
MAX_NODES_COMMUNITY = 200_000


def _disparity_alpha(p: np.ndarray, k: np.ndarray) -> np.ndarray:
    """Serrano et al. disparity-filter significance: an edge with normalized
    weight p among a node's k links is significant at level a if (1-p)^(k-1) < a.
    Degree-1 nodes (k<=1) cannot be filtered -> alpha 0 (always kept)."""
    out = np.where(k > 1, np.power(1.0 - np.clip(p, 0, 1), k - 1), 0.0)
    return out


def build(axis_name: str, alpha: float, threads: int) -> dict:
    if axis_name not in C.AXES:
        raise SystemExit(f"unknown axis '{axis_name}'; choose from {list(C.AXES)}")
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    edges_in = C.OUT_DIR / f"{axis_name}_edges.parquet"
    nodes_in = C.OUT_DIR / f"{axis_name}_nodes.parquet"
    if not edges_in.exists():
        raise SystemExit(f"{edges_in} missing; run build_network {axis_name} first")

    started = time.monotonic()
    edges = con.sql(f"SELECT * FROM read_parquet('{str(edges_in)}')").df()
    nodes = con.sql(f"SELECT * FROM read_parquet('{str(nodes_in)}')").df()

    # --- Phase 3a: disparity-filter backbone (on non-self edges) ------------
    # p in each direction = weight / strength; k = degree in that direction.
    e = edges[~edges["is_self_loop"]].copy()
    deg_out = nodes.set_index("node")["out_degree"].to_dict()
    deg_in = nodes.set_index("node")["in_degree"].to_dict()
    str_out = nodes.set_index("node")["out_strength"].to_dict()
    str_in = nodes.set_index("node")["in_strength"].to_dict()
    p_out = e["weight"] / e["from_node"].map(str_out)
    p_in = e["weight"] / e["to_node"].map(str_in)
    a_out = _disparity_alpha(p_out.to_numpy(), e["from_node"].map(deg_out).to_numpy())
    a_in = _disparity_alpha(p_in.to_numpy(), e["to_node"].map(deg_in).to_numpy())
    e["disparity_alpha"] = np.minimum(a_out, a_in)
    e["in_backbone"] = e["disparity_alpha"] < alpha

    # --- Phase 3b: centrality via igraph (directed, weighted) ---------------
    node_ids = list(nodes["node"])
    idx = {n: i for i, n in enumerate(node_ids)}
    n_nodes = len(node_ids)
    g = ig.Graph(directed=True)
    g.add_vertices(n_nodes)
    ne = e[(e["from_node"].isin(idx)) & (e["to_node"].isin(idx))]
    src = ne["from_node"].map(idx).to_numpy()
    dst = ne["to_node"].map(idx).to_numpy()
    g.add_edges(list(zip(src, dst)))
    w = ne["weight"].to_numpy(dtype=float)
    rr = ne["relative_risk"].to_numpy(dtype=float)
    w_list = w.tolist()
    cent = pd.DataFrame({"node": node_ids, "pagerank": g.pagerank(weights=w_list, directed=True)})
    if n_nodes <= MAX_NODES_BETWEENNESS:  # O(VE): only for small grains
        cent["betweenness"] = g.betweenness(weights=(1.0 / np.maximum(w, 1e-9)).tolist(), directed=True)
        cent["hub_score"] = g.hub_score(weights=w_list)
        cent["authority_score"] = g.authority_score(weights=w_list)

    # --- Phase 3c: SpringRank revealed seniority (excl. non-seniority kinds) -
    # weight = n_persons (validated best vs relative_risk-weighting, trophic
    # levels, agony/min-violation, and David's Score — see
    # transition_network/REVEALED_SENIORITY_COMPARISON.md; RR-weighting *hurts*
    # the job-zone anchor and weak-'down' is intrinsic, not a weighting artifact).
    sr_mask = ~ne["modal_kind"].isin(C.NON_SENIORITY_KINDS)
    sr_w = ne.loc[sr_mask, "n_persons"].to_numpy(dtype=float)
    s_raw = C.springrank(src[sr_mask.to_numpy()], dst[sr_mask.to_numpy()], sr_w, n_nodes)
    sd = s_raw.std() or 1.0
    cent["springrank"] = (s_raw - s_raw.mean()) / sd
    # support = incident person-volume on the seniority subgraph (rank reliability)
    supp = np.zeros(n_nodes)
    np.add.at(supp, src[sr_mask.to_numpy()], sr_w)
    np.add.at(supp, dst[sr_mask.to_numpy()], sr_w)
    cent["springrank_support"] = np.log1p(supp)

    # --- Phase 4: community detection (only for tractable grains) -----------
    infomap_mod, leiden_mod = {}, {}
    if n_nodes <= MAX_NODES_COMMUNITY:
        im = Infomap("--directed --silent --seed 42")
        for s, t, wt in zip(src, dst, w):
            im.add_link(int(s), int(t), float(wt))
        im.run()
        infomap_mod = {node_ids[nid]: mid for nid, mid in im.get_modules().items()}
        # Leiden modularity on the RR-symmetrized undirected graph
        gu = ig.Graph(directed=False); gu.add_vertices(n_nodes)
        gu.add_edges(list(zip(src, dst))); gu.es["w"] = rr
        gu = gu.simplify(combine_edges={"w": "sum"})
        import leidenalg
        part = leidenalg.find_partition(gu, leidenalg.ModularityVertexPartition,
                                        weights="w", seed=42)
        leiden_mod = {node_ids[i]: c for i, c in enumerate(part.membership)}

    # --- assemble node table ------------------------------------------------
    nodes = nodes.merge(cent, on="node", how="left")
    nodes["infomap_community"] = nodes["node"].map(infomap_mod).astype("Int64") if infomap_mod else pd.NA
    nodes["leiden_community"] = nodes["node"].map(leiden_mod).astype("Int64") if leiden_mod else pd.NA
    nodes["soc_major"] = nodes["node"].str.slice(0, 2).map(SOC_MAJOR) \
        if axis_name == "occupation" else None

    nodes_out = C.OUT_DIR / f"{axis_name}_nodes_analyzed.parquet"
    backbone_out = C.OUT_DIR / f"{axis_name}_backbone_edges.parquet"
    nodes.to_parquet(nodes_out, compression="zstd")
    e.to_parquet(backbone_out, compression="zstd")

    # --- community / cross-tab summary --------------------------------------
    def _summ(col):
        if nodes[col].isna().all():
            return {"skipped": "grain too large"}
        vc = nodes[col].value_counts()
        return {"n_communities": int(nodes[col].nunique()),
                "largest": int(vc.iloc[0]) if len(vc) else 0,
                "singletons": int((vc == 1).sum())}

    summary = {
        "axis": axis_name, "alpha": alpha,
        "nodes": len(nodes), "edges_nonself": len(e),
        "backbone_edges": int(e["in_backbone"].sum()),
        "infomap": _summ("infomap_community"),
        "leiden": _summ("leiden_community"),
        "runtime_s": round(time.monotonic() - started, 1),
    }
    communities = {"summary": summary}
    if axis_name == "occupation" and not nodes["infomap_community"].isna().all():
        # how well does each Infomap module map onto a single SOC major group?
        ct = nodes.dropna(subset=["soc_major"])
        purity = (ct.groupby("infomap_community")["soc_major"]
                  .agg(lambda s: s.value_counts(normalize=True).iloc[0]).mean())
        summary["mean_infomap_soc_purity"] = round(float(purity), 3)
        # example: the largest few Infomap modules, top occupations + SOC spread
        top_mods = nodes["infomap_community"].value_counts().head(6).index
        communities["example_infomap_modules"] = {
            int(m): {
                "size": int((nodes["infomap_community"] == m).sum()),
                "soc_majors": (nodes[nodes["infomap_community"] == m]["soc_major"]
                               .value_counts().head(4).to_dict()),
                "top_nodes": (nodes[nodes["infomap_community"] == m]
                              .nlargest(5, "pagerank")["label"].tolist()),
            } for m in top_mods
        }
    (C.OUT_DIR / f"{axis_name}_communities.json").write_text(json.dumps(communities, indent=2, default=str))
    (C.OUT_DIR / f"{axis_name}_analyze_manifest.json").write_text(json.dumps(summary, indent=2))
    con.close()
    print(json.dumps(communities, indent=2, default=str), flush=True)
    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("axis", nargs="?", default="occupation", choices=list(C.AXES))
    p.add_argument("--alpha", type=float, default=0.05,
                   help="disparity-filter significance level for the backbone")
    p.add_argument("--threads", type=int, default=8)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    build(args.axis, args.alpha, args.threads)


if __name__ == "__main__":
    main()
