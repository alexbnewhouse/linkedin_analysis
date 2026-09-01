"""Phase 6 — time-sliced transition networks + drift (CAREER_TRANSITION_NETWORK §4).

    uv run --group graph python -m transition_network.temporal

Most published occupational-mobility networks are static. We have dated moves, so
we can build one occupation network per era (binned by the year the destination
role started) and measure how the structure *moves*: which occupations rise/fall
as PageRank attractors and flow-betweenness bridges, and which occupation-to-
occupation flows grow or shrink. This is the temporal differentiator of §2.6.

Self-contained (does not depend on the Phase 1-2 outputs): it re-aggregates the
occupation edge list per era from `paths/transitions.parquet`, applies the same
relative-risk null model, and computes PageRank (igraph) + SpringRank
(`common.springrank`) per era. Occupation grain only (SOC-coded both ends).

Outputs: `temporal_occupation_nodes.parquet` (era × node × metrics) and
`temporal.json` (per-era sizes, top bridges, biggest PageRank risers/fallers,
fastest-growing flows). Read the data-quality caveats first: recency/backfill
bias means earlier eras are sparser and noisier (CAREER_PATHS_PLAN §7).
"""

from __future__ import annotations

import argparse
import json
import time

import duckdb
import igraph as ig
import numpy as np
import pandas as pd

from transition_network import common as C

ERAS = [(2005, 2009), (2010, 2014), (2015, 2019), (2020, 2025)]


def _labels(con) -> dict:
    df = con.sql(f"""
      SELECT regexp_extract(column0, '^(\\d{{2}}-\\d{{4}})', 1) AS code, column1 AS label
      FROM read_csv('{str(C.ONET_OCC)}', delim='\\t', header=true,
                    columns={{'column0':'VARCHAR','column1':'VARCHAR','column2':'VARCHAR'}})
      WHERE column0 LIKE '%.00'
    """).df()
    return dict(zip(df["code"], df["label"]))


def _era_network(con, t, lo, hi) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate the occupation edge list for moves whose destination started in
    [lo, hi], with relative-risk, and per-node PageRank + SpringRank."""
    edges = con.sql(f"""
      WITH e AS (
        SELECT from_occupation AS f, to_occupation AS g, n_persons, modal_kind, kind
        FROM (
          SELECT from_occupation, to_occupation,
                 count(DISTINCT linkedin_id) AS n_persons,
                 mode(kind) AS modal_kind, any_value(kind) AS kind
          FROM {t}
          WHERE from_occupation IS NOT NULL AND to_occupation IS NOT NULL
            AND year(to_start_dt) BETWEEN {lo} AND {hi}
          GROUP BY 1, 2
        )
      )
      SELECT f AS from_node, g AS to_node, n_persons AS weight, modal_kind,
             (f = g) AS is_self
      FROM e
    """).df()
    if edges.empty:
        return edges, pd.DataFrame()
    nonself = edges[~edges["is_self"]].copy()
    # relative risk vs strength-preserving null (same as Phase 2)
    s_out = edges.groupby("from_node")["weight"].sum()
    s_in = edges.groupby("to_node")["weight"].sum()
    W = edges["weight"].sum()
    nonself["expected"] = (nonself["from_node"].map(s_out) *
                           nonself["to_node"].map(s_in)) / W
    nonself["relative_risk"] = nonself["weight"] / nonself["expected"]

    node_ids = sorted(set(edges["from_node"]) | set(edges["to_node"]))
    idx = {n: i for i, n in enumerate(node_ids)}
    g = ig.Graph(directed=True); g.add_vertices(len(node_ids))
    src = nonself["from_node"].map(idx).to_numpy()
    dst = nonself["to_node"].map(idx).to_numpy()
    g.add_edges(list(zip(src, dst)))
    w = nonself["weight"].to_numpy(dtype=float)
    pr = g.pagerank(weights=w.tolist(), directed=True)
    betw = (g.betweenness(weights=(1.0 / np.maximum(w, 1e-9)).tolist(), directed=True)
            if len(node_ids) <= 20000 else [np.nan] * len(node_ids))
    sr_mask = ~nonself["modal_kind"].isin(C.NON_SENIORITY_KINDS)
    s_raw = C.springrank(src[sr_mask.to_numpy()], dst[sr_mask.to_numpy()],
                         w[sr_mask.to_numpy()], len(node_ids))
    nodes = pd.DataFrame({
        "node": node_ids, "pagerank": pr, "betweenness": betw,
        "springrank": (s_raw - s_raw.mean()) / (s_raw.std() or 1.0),
        "out_strength": [s_out.get(n, 0) for n in node_ids],
        "in_strength": [s_in.get(n, 0) for n in node_ids],
    })
    nodes["pagerank_pct"] = nodes["pagerank"].rank(pct=True)
    return nonself, nodes


def build(threads: int) -> dict:
    con = duckdb.connect(); con.execute(f"PRAGMA threads={threads}")
    t = f"read_parquet('{C.TRANSITIONS}')"
    labels = _labels(con)
    started = time.monotonic()

    per_era, all_nodes, era_summ = {}, [], {}
    for lo, hi in ERAS:
        tag = f"{lo}-{hi}"
        edges, nodes = _era_network(con, t, lo, hi)
        if nodes.empty:
            continue
        nodes["era"] = tag
        all_nodes.append(nodes)
        per_era[tag] = (edges, nodes)
        top = nodes.nlargest(6, "betweenness")["node"].tolist() \
            if nodes["betweenness"].notna().any() else nodes.nlargest(6, "pagerank")["node"].tolist()
        era_summ[tag] = {
            "nodes": len(nodes), "edges": len(edges),
            "total_moves": int(edges["weight"].sum()),
            "top_bridges": [labels.get(n, n) for n in top],
        }

    nodes_long = pd.concat(all_nodes, ignore_index=True)
    nodes_long["label"] = nodes_long["node"].map(lambda n: labels.get(n, n))
    out_nodes = C.OUT_DIR / "temporal_occupation_nodes.parquet"
    nodes_long.to_parquet(out_nodes, compression="zstd")

    # drift: PageRank percentile change between the first and last populated era
    eras_present = list(per_era)
    first, last = eras_present[0], eras_present[-1]
    pf = per_era[first][1].set_index("node")["pagerank_pct"]
    pl = per_era[last][1].set_index("node")["pagerank_pct"]
    common = pf.index.intersection(pl.index)
    # require some support in the last era to avoid tiny-sample noise
    supp = per_era[last][1].set_index("node")["out_strength"] + \
           per_era[last][1].set_index("node")["in_strength"]
    common = [n for n in common if supp.get(n, 0) >= 50]
    drift = pd.DataFrame({"node": common,
                          "delta_pagerank_pct": [pl[n] - pf[n] for n in common]})
    drift["label"] = drift["node"].map(lambda n: labels.get(n, n))
    risers = drift.nlargest(8, "delta_pagerank_pct")[["label", "delta_pagerank_pct"]]
    fallers = drift.nsmallest(8, "delta_pagerank_pct")[["label", "delta_pagerank_pct"]]

    # fastest-growing flows: share of era moves, first vs last era (min support)
    def _share(tag):
        e = per_era[tag][0].copy()
        e["share"] = e["weight"] / e["weight"].sum()
        return e.set_index(["from_node", "to_node"])[["share", "weight"]]
    sf, sl = _share(first), _share(last)
    join = sl.join(sf, lsuffix="_last", rsuffix="_first", how="left").fillna(0)
    join = join[join["weight_last"] >= 50]
    join["share_growth"] = join["share_last"] - join["share_first"]
    grow = join.nlargest(8, "share_growth").reset_index()
    growing = [{"from": labels.get(r.from_node, r.from_node),
                "to": labels.get(r.to_node, r.to_node),
                "share_first": round(r.share_first, 5), "share_last": round(r.share_last, 5)}
               for r in grow.itertuples(index=False)]

    summary = {
        "eras": era_summ,
        "pagerank_risers": [{"label": r.label, "delta_pct": round(r.delta_pagerank_pct, 3)}
                            for r in risers.itertuples(index=False)],
        "pagerank_fallers": [{"label": r.label, "delta_pct": round(r.delta_pagerank_pct, 3)}
                             for r in fallers.itertuples(index=False)],
        "fastest_growing_flows": growing,
        "drift_window": f"{first} -> {last}",
        "runtime_s": round(time.monotonic() - started, 1),
        "output": str(out_nodes),
    }
    (C.OUT_DIR / "temporal.json").write_text(json.dumps(summary, indent=2, default=str))
    con.close()
    print(json.dumps(summary, indent=2, default=str), flush=True)
    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--threads", type=int, default=8)
    return p.parse_args()


def main() -> None:
    build(parse_args().threads)


if __name__ == "__main__":
    main()
