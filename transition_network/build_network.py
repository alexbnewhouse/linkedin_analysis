"""Build a career-transition network at a chosen node grain (Phases 1-2).

    uv run python -m transition_network.build_network occupation
    uv run python -m transition_network.build_network company --threads 16

Phase 1 (aggregate) and Phase 2 (null-model normalization) over
`paths/transitions.parquet`. Emits, per axis:

  <axis>_edges.parquet   directed weighted edges with raw counts AND the
                         null-normalized weights (relative risk, conditional
                         transition probability, Poisson z).
  <axis>_nodes.parquet   per-node in/out strength, degree, self-loops, label.
  <axis>_manifest.json   coverage + run stats.

IMPORTANT semantics. This is a **job-to-job mobility** network: an edge i->j is a
person whose successive *primary* steps were occupation i then j. It is therefore
**conditional on a move occurring** — people who never change employer produce no
edge, so the row-normalized weight p_ij is P(next state = j | a move from i
happened), NOT a full occupational Markov chain that includes stayers. A
**self-loop** i->i is a real move that changed employer (or role) but stayed in
the same occupation. The relative-risk weight controls for the fact that large
occupations exchange many workers by size alone (Cheng & Park 2020).

GPU note: aggregation/normalization are relational and stay on DuckDB/CPU. The
emitted edge list (compact, integer-codable node ids) is the input to the
GPU graph-algorithm phases (centrality, community detection) — see plan §4-5.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import duckdb

from transition_network import common as C


def _q(path) -> str:
    return str(path).replace("'", "''")


def _onet_labels_sql() -> str:
    """SOC family (6-digit) -> title, from the O*NET `.00` base rows."""
    return f"""
      SELECT DISTINCT
        regexp_extract(column0, '^(\\d{{2}}-\\d{{4}})', 1) AS node,
        column1 AS label
      FROM read_csv('{_q(C.ONET_OCC)}', delim='\\t', header=true,
                    columns={{'column0':'VARCHAR','column1':'VARCHAR','column2':'VARCHAR'}})
      WHERE column0 LIKE '%.00'
    """


def build(axis_name: str, threads: int, min_support: int,
          exclude_overlap: bool = False) -> dict:
    if axis_name not in C.AXES:
        raise SystemExit(f"unknown axis '{axis_name}'; choose from {list(C.AXES)}")
    ax = C.AXES[axis_name]
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")

    edges_out = C.OUT_DIR / f"{axis_name}_edges.parquet"
    nodes_out = C.OUT_DIR / f"{axis_name}_nodes.parquet"
    t = f"read_parquet('{_q(C.TRANSITIONS)}')"
    fcol, tcol = ax.from_col, ax.to_col
    # Genuine concurrency (has_overlap) is optionally dropped so the network
    # reflects successions, not roles held simultaneously (red-team H2).
    overlap_filter = "AND NOT has_overlap" if exclude_overlap else ""

    started = time.monotonic()

    # --- Phase 1: aggregate to a weighted directed multigraph ---------------
    # Only edges where BOTH endpoints are defined on this axis (uncoded nodes,
    # e.g. occupations without a SOC code, are excluded and reported as gaps).
    print(f"[net:{axis_name}] Phase 1: aggregate ...", flush=True)
    con.sql(f"""
      CREATE TEMP TABLE agg AS
      SELECT
        CAST({fcol} AS VARCHAR) AS from_node,
        CAST({tcol} AS VARCHAR) AS to_node,
        count(*)                       AS weight,
        count(DISTINCT linkedin_id)    AS n_persons,
        ({fcol} = {tcol})              AS is_self_loop,
        avg(dwell_months)              AS mean_dwell_months,
        avg(gap_months)                AS mean_gap_months,
        avg(has_gap::INT)              AS frac_with_gap,
        avg(CASE WHEN seniority_direction='up'   THEN 1 ELSE 0 END) AS frac_up,
        avg(CASE WHEN seniority_direction='flat' THEN 1 ELSE 0 END) AS frac_flat,
        avg(CASE WHEN seniority_direction='down' THEN 1 ELSE 0 END) AS frac_down,
        mode(kind)                     AS modal_kind,
        -- fused-seniority typing (SENIORITY_TRANSITIONS): direction now covers
        -- the no-seniority-word majority, not just edges with a lexical token
        mode(transition_type)          AS modal_transition_type,
        avg(delta_sen)                 AS mean_delta_sen,
        avg(transition_confidence)     AS mean_transition_confidence
      FROM {t}
      WHERE {fcol} IS NOT NULL AND {tcol} IS NOT NULL {overlap_filter}
      GROUP BY 1, 2, is_self_loop
    """)

    total_edge_rows = con.sql(f"SELECT count(*) FROM {t}").fetchone()[0]
    kept = con.sql("SELECT sum(weight) FROM agg").fetchone()[0] or 0
    coverage = round(kept / total_edge_rows, 4) if total_edge_rows else 0.0

    # --- node strengths (computed on the FULL aggregate incl self-loops) ----
    con.sql("""
      CREATE TEMP TABLE node_out AS
        SELECT from_node AS node, sum(weight) AS out_strength,
               sum(n_persons) AS out_persons,
               count(*) FILTER (WHERE NOT is_self_loop) AS out_degree,
               sum(weight) FILTER (WHERE is_self_loop) AS self_loops
        FROM agg GROUP BY 1;
      CREATE TEMP TABLE node_in AS
        SELECT to_node AS node, sum(weight) AS in_strength,
               count(*) FILTER (WHERE NOT is_self_loop) AS in_degree
        FROM agg GROUP BY 1;
    """)
    grand_total = con.sql("SELECT sum(weight) FROM agg").fetchone()[0]

    # --- Phase 2: null-model normalization ----------------------------------
    # Strength-preserving (gravity) null: expected_ij = s_out_i * s_in_j / W.
    # relative_risk = observed / expected  (>1 = over-represented vs chance).
    # p_transition  = observed / out_strength_i  (row-normalized, incl self).
    # z             = (observed - expected)/sqrt(expected)  (Poisson-ish).
    print(f"[net:{axis_name}] Phase 2: null-model normalization ...", flush=True)
    label_join, label_select = "", "e.from_node AS from_label, e.to_node AS to_label"
    if ax.label_ref in ("onet", "soc_major"):
        if ax.label_ref == "onet":
            con.sql(f"CREATE TEMP TABLE labels AS {_onet_labels_sql()}")
        else:
            vals = ", ".join(f"('{k}', '{v.replace(chr(39), chr(39) * 2)}')"
                             for k, v in C.SOC_MAJOR.items())
            con.sql(f"CREATE TEMP TABLE labels AS SELECT * FROM (VALUES {vals}) t(node, label)")
        label_join = (
            "LEFT JOIN labels lf ON lf.node = e.from_node "
            "LEFT JOIN labels lt ON lt.node = e.to_node"
        )
        label_select = ("coalesce(lf.label, e.from_node) AS from_label, "
                        "coalesce(lt.label, e.to_node) AS to_label")
    elif ax.label_strip:
        n = len(ax.label_strip) + 1
        label_select = (
            f"CASE WHEN starts_with(e.from_node,'{ax.label_strip}') "
            f"THEN substr(e.from_node,{n}) ELSE e.from_node END AS from_label, "
            f"CASE WHEN starts_with(e.to_node,'{ax.label_strip}') "
            f"THEN substr(e.to_node,{n}) ELSE e.to_node END AS to_label")

    con.sql(f"""
      COPY (
        SELECT
          e.from_node, e.to_node, {label_select},
          e.weight, e.n_persons, e.is_self_loop, e.modal_kind,
          e.modal_transition_type,
          round(e.mean_delta_sen, 4) AS mean_delta_sen,
          round(e.mean_transition_confidence, 3) AS mean_transition_confidence,
          so.out_strength, si.in_strength,
          (so.out_strength * si.in_strength) / {grand_total}.0 AS expected,
          e.weight / ((so.out_strength * si.in_strength) / {grand_total}.0)
            AS relative_risk,
          e.weight::DOUBLE / so.out_strength AS p_transition,
          (e.weight - (so.out_strength * si.in_strength) / {grand_total}.0)
            / sqrt((so.out_strength * si.in_strength) / {grand_total}.0) AS z,
          round(e.mean_dwell_months, 1) AS mean_dwell_months,
          round(e.mean_gap_months, 1)   AS mean_gap_months,
          round(e.frac_with_gap, 3) AS frac_with_gap,
          round(e.frac_up, 3) AS frac_up, round(e.frac_flat, 3) AS frac_flat,
          round(e.frac_down, 3) AS frac_down,
          (e.weight >= {min_support}) AS in_backbone_support
        FROM agg e
        JOIN node_out so ON so.node = e.from_node
        JOIN node_in  si ON si.node = e.to_node
        {label_join}
      ) TO '{_q(edges_out)}' (FORMAT parquet, COMPRESSION zstd)
    """)

    # --- node table ---------------------------------------------------------
    label_node = "n.node"
    node_label_join = ""
    if ax.label_ref in ("onet", "soc_major"):
        node_label_join = "LEFT JOIN labels l ON l.node = n.node"
        label_node = "coalesce(l.label, n.node)"
    elif ax.label_strip:
        nn = len(ax.label_strip) + 1
        label_node = (f"CASE WHEN starts_with(n.node,'{ax.label_strip}') "
                      f"THEN substr(n.node,{nn}) ELSE n.node END")
    con.sql(f"""
      COPY (
        SELECT
          n.node, {label_node} AS label,
          coalesce(o.out_strength, 0) AS out_strength,
          coalesce(i.in_strength, 0)  AS in_strength,
          coalesce(o.out_degree, 0)   AS out_degree,
          coalesce(i.in_degree, 0)    AS in_degree,
          coalesce(o.self_loops, 0)   AS self_loops,
          coalesce(o.out_persons, 0)  AS out_persons,
          coalesce(o.out_strength,0) - coalesce(i.in_strength,0) AS net_flow
        FROM (SELECT node FROM node_out UNION SELECT node FROM node_in) n
        LEFT JOIN node_out o ON o.node = n.node
        LEFT JOIN node_in  i ON i.node = n.node
        {node_label_join}
      ) TO '{_q(nodes_out)}' (FORMAT parquet, COMPRESSION zstd)
    """)

    n_nodes = con.sql(f"SELECT count(*) FROM read_parquet('{_q(nodes_out)}')").fetchone()[0]
    n_edges = con.sql(f"SELECT count(*) FROM read_parquet('{_q(edges_out)}')").fetchone()[0]
    n_self = con.sql(f"SELECT count(*) FROM read_parquet('{_q(edges_out)}') WHERE is_self_loop").fetchone()[0]
    con.close()

    return {
        "axis": axis_name,
        "exclude_overlap": exclude_overlap,
        "nodes": n_nodes,
        "edges": n_edges,
        "self_loop_edges": n_self,
        "total_spine_transitions": total_edge_rows,
        "transitions_covered": int(kept),
        "axis_coverage": coverage,
        "grand_total_weight": int(grand_total),
        "min_support": min_support,
        "runtime_s": round(time.monotonic() - started, 1),
        "outputs": {"edges": str(edges_out), "nodes": str(nodes_out)},
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("axis", nargs="?", default="occupation", choices=list(C.AXES))
    p.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    p.add_argument("--min-support", type=int, default=C.DEFAULT_MIN_SUPPORT)
    p.add_argument("--exclude-overlap", action="store_true",
                   help="drop edges flagged has_overlap (genuine concurrency)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = build(args.axis, args.threads, args.min_support, args.exclude_overlap)
    (C.OUT_DIR / f"{args.axis}_manifest.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[net] {json.dumps(summary, indent=2)}", flush=True)


if __name__ == "__main__":
    main()
