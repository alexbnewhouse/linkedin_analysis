"""Phase 5 — higher-order sequence structure of career trajectories.

    uv run --group graph python -m transition_network.sequences

This is the differentiator over the one-step transition matrices that survey /
administrative data yield (CAREER_TRANSITION_NETWORK_PLAN.md §2.1, §4 Phase 5):
we have full ordered per-person trajectories, so we can ask things a single
matrix cannot. Three analyses, all reconstructed from `paths/transitions.parquet`
(consecutive primary steps already carry both endpoints on every axis):

  1. MEMORY-ORDER TEST — does the next state depend on more than the current one?
     First- vs second-order Markov compared by held-out perplexity (a real
     memory effect lowers test perplexity; held-out evaluation penalizes the
     order-2 model's extra parameters automatically). Run on the SOC-major axis
     (dense, interpretable) and the employment-type axis (full coverage).
  2. PATH MOTIFS — ordered occupation triples (a->b->c) ranked by *lift* over the
     first-order Markov expectation: paths that are over-represented specifically
     because of where they came from, not just because b->c is common.
  3. TRAJECTORY ARCHETYPES — per-profile structural features (mobility, promotion
     mix, self-employment, span, SOC start/end) clustered (k-means) into a small
     set of archetypal careers.

Outputs: `sequences.json` (report) and `trajectory_features.parquet`
(per-profile features + archetype id). CPU; the heavy step is the k-means over
~1.3M profiles (seconds). GPU is not needed at this scale.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict

import duckdb
import numpy as np
import pandas as pd

from transition_network import common as C
from transition_network.analyze import SOC_MAJOR

ALPHA = 0.1  # Laplace smoothing for the Markov models


def _triples(con, t, expr_from, expr_to):
    """Ordered (a,b,c) triples of a chosen state expr, per profile, known-only.

    A trajectory is broken at unknown states: a triple is emitted only where all
    three consecutive states are non-NULL (so we never invent a transition across
    an uncoded gap)."""
    return con.sql(f"""
      WITH s AS (
        SELECT linkedin_id, {expr_from} AS a, {expr_to} AS b,
               from_start_dt, from_row_id
        FROM read_parquet('{t}')
      ),
      tri AS (
        SELECT a, b, lead(b) OVER w AS c
        FROM s
        WINDOW w AS (PARTITION BY linkedin_id ORDER BY from_start_dt, from_row_id)
      )
      SELECT a, b, c FROM tri
      WHERE a IS NOT NULL AND b IS NOT NULL AND c IS NOT NULL
    """).df()


def memory_test(tri: pd.DataFrame, seed: int = 42) -> dict:
    """Held-out perplexity of a 1st- vs 2nd-order Markov model on the triples."""
    rng = np.random.default_rng(seed)
    mask = rng.random(len(tri)) < 0.8
    train, test = tri[mask], tri[~mask]

    # order-1: P(c | b);  order-2: P(c | a,b)
    c1 = defaultdict(lambda: defaultdict(int)); c1tot = defaultdict(int)
    c2 = defaultdict(lambda: defaultdict(int)); c2tot = defaultdict(int)
    for a, b, c in train.itertuples(index=False):
        c1[b][c] += 1; c1tot[b] += 1
        c2[(a, b)][c] += 1; c2tot[(a, b)] += 1
    V = train["c"].nunique()

    def ll(use_order2: bool) -> float:
        tot = 0.0
        for a, b, c in test.itertuples(index=False):
            if use_order2 and (a, b) in c2tot:
                p = (c2[(a, b)].get(c, 0) + ALPHA) / (c2tot[(a, b)] + ALPHA * V)
            else:  # order-1, or order-2 backing off to it for unseen contexts
                p = (c1[b].get(c, 0) + ALPHA) / (c1tot.get(b, 0) + ALPHA * V)
            tot += math.log(p)
        return tot / len(test)

    ll1, ll2 = ll(False), ll(True)
    ppl1, ppl2 = math.exp(-ll1), math.exp(-ll2)
    return {
        "triples": len(tri), "states": int(V), "test_triples": len(test),
        "perplexity_order1": round(ppl1, 3), "perplexity_order2": round(ppl2, 3),
        "perplexity_reduction_pct": round(100 * (ppl1 - ppl2) / ppl1, 2),
        "has_memory": ppl2 < ppl1,
    }


def motifs(tri: pd.DataFrame, min_support: int, top: int, label=None) -> list:
    """Top triples by lift = observed / first-order-Markov expected.

    expected(a,b,c) = count(a,b) * P(c|b), with P(c|b) from the (b->c) bigram over
    all triples. Lift>1 => the third step is over-represented given the first."""
    n_abc = tri.groupby(["a", "b", "c"]).size().rename("n_abc").reset_index()
    n_ab = tri.groupby(["a", "b"]).size().rename("n_ab").reset_index()
    n_b = tri.groupby("b").size().rename("n_b").reset_index()
    n_bc = tri.groupby(["b", "c"]).size().rename("n_bc").reset_index()
    m = (n_abc.merge(n_ab, on=["a", "b"]).merge(n_bc, on=["b", "c"])
              .merge(n_b, on="b"))
    m["p_c_given_b"] = m["n_bc"] / m["n_b"]
    m["expected"] = m["n_ab"] * m["p_c_given_b"]
    m["lift"] = m["n_abc"] / m["expected"]
    m = m[m["n_abc"] >= min_support].nlargest(top, "lift")
    lab = (lambda x: label.get(x, x)) if label else (lambda x: x)
    return [{"path": [lab(r.a), lab(r.b), lab(r.c)], "count": int(r.n_abc),
             "lift": round(r.lift, 1)} for r in m.itertuples(index=False)]


def trajectory_archetypes(con, t, k: int, seed: int) -> tuple[pd.DataFrame, dict]:
    """Per-profile structural features -> k-means archetypes."""
    feats = con.sql(f"""
      WITH e AS (SELECT *,
          row_number() OVER (PARTITION BY linkedin_id
                             ORDER BY from_start_dt, from_row_id) AS seq,
          count(*)    OVER (PARTITION BY linkedin_id) AS n
        FROM read_parquet('{t}'))
      SELECT
        linkedin_id,
        any_value(n) AS n_transitions,
        sum((kind='move')::INT)               AS n_employer_moves,
        sum((kind='promotion')::INT)          AS n_promotions,
        sum((kind='demotion')::INT)           AS n_demotions,
        sum((kind='lateral')::INT)            AS n_lateral,
        sum((kind IN ('into_self_employment','out_of_self_employment'))::INT)
                                              AS n_self_emp_moves,
        max((kind='exit')::INT)               AS has_exit,
        avg(has_gap::INT)                     AS frac_with_gap,
        avg(dwell_months)                     AS mean_dwell_months,
        sum(dwell_months) + sum(gap_months)   AS span_months,
        arg_min(from_occupation, seq) FILTER (WHERE from_occupation IS NOT NULL)
                                              AS start_occ,
        arg_max(to_occupation, seq)   FILTER (WHERE to_occupation IS NOT NULL)
                                              AS end_occ,
        arg_min(from_seniority_ordinal, seq) FILTER (WHERE from_seniority_ordinal IS NOT NULL)
                                              AS start_sen,
        arg_max(to_seniority_ordinal, seq)   FILTER (WHERE to_seniority_ordinal IS NOT NULL)
                                              AS end_sen
      FROM e GROUP BY linkedin_id HAVING any_value(n) >= 2
    """).df()

    feats["start_soc_major"] = feats["start_occ"].str.slice(0, 2).map(SOC_MAJOR)
    feats["end_soc_major"] = feats["end_occ"].str.slice(0, 2).map(SOC_MAJOR)
    feats["seniority_change"] = (feats["end_sen"] - feats["start_sen"])

    cols = ["n_transitions", "n_employer_moves", "n_promotions", "n_demotions",
            "n_lateral", "n_self_emp_moves", "has_exit", "frac_with_gap",
            "mean_dwell_months", "span_months"]
    X = feats[cols].fillna(0.0).to_numpy(dtype=float)
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    Xs = StandardScaler().fit_transform(X)
    km = KMeans(n_clusters=k, random_state=seed, n_init=10)
    feats["archetype"] = km.fit_predict(Xs)

    summary = {}
    for a in sorted(feats["archetype"].unique()):
        grp = feats[feats["archetype"] == a]
        top_path = (grp.dropna(subset=["start_soc_major", "end_soc_major"])
                    .groupby(["start_soc_major", "end_soc_major"]).size()
                    .nlargest(3))
        summary[int(a)] = {
            "size": int(len(grp)),
            "means": {c: round(float(grp[c].mean()), 2) for c in cols},
            "mean_seniority_change": round(float(grp["seniority_change"].mean(skipna=True)), 3)
                if grp["seniority_change"].notna().any() else None,
            "top_soc_start_end": [{"start": s, "end": e, "n": int(n)}
                                  for (s, e), n in top_path.items()],
        }
    return feats, summary


def build(threads: int, k: int, min_support: int, seed: int) -> dict:
    con = duckdb.connect(); con.execute(f"PRAGMA threads={threads}")
    t = str(C.TRANSITIONS)
    started = time.monotonic()

    print("[seq] memory-order test ...", flush=True)
    soc = _triples(con, t, "substr(from_occupation,1,2)", "substr(to_occupation,1,2)")
    et = _triples(con, t, "from_employment_type", "to_employment_type")
    mem = {"soc_major": memory_test(soc), "employment_type": memory_test(et)}

    print("[seq] path motifs (occupation) ...", flush=True)
    occ = _triples(con, t, "from_occupation", "to_occupation")
    occ_label = _occupation_labels(con)
    motif = motifs(occ, min_support, top=15, label=occ_label)

    print("[seq] trajectory archetypes (k-means) ...", flush=True)
    feats, arche = trajectory_archetypes(con, t, k, seed)
    feats_out = C.OUT_DIR / "trajectory_features.parquet"
    feats.to_parquet(feats_out, compression="zstd")
    con.close()

    report = {
        "memory_order_test": mem,
        "path_motifs_by_lift": motif,
        "trajectory_archetypes": {"k": k, "profiles": int(len(feats)),
                                  "clusters": arche},
        "min_support": min_support, "seed": seed,
        "runtime_s": round(time.monotonic() - started, 1),
        "outputs": {"trajectory_features": str(feats_out)},
    }
    (C.OUT_DIR / "sequences.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"memory_order_test": mem,
                      "top_motifs": motif[:6],
                      "archetypes": {a: {"size": v["size"]} for a, v in arche.items()},
                      "runtime_s": report["runtime_s"]}, indent=2, default=str), flush=True)
    return report


def _occupation_labels(con) -> dict:
    df = con.sql(f"""
      SELECT regexp_extract(column0, '^(\\d{{2}}-\\d{{4}})', 1) AS code, column1 AS label
      FROM read_csv('{str(C.ONET_OCC)}', delim='\\t', header=true,
                    columns={{'column0':'VARCHAR','column1':'VARCHAR','column2':'VARCHAR'}})
      WHERE column0 LIKE '%.00'
    """).df()
    return dict(zip(df["code"], df["label"]))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--k", type=int, default=8, help="number of trajectory archetypes")
    p.add_argument("--min-support", type=int, default=30, help="min count for a motif")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    build(args.threads, args.k, args.min_support, args.seed)


if __name__ == "__main__":
    main()
