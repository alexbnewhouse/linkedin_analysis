"""Layer C + fuse: revealed per-role seniority score (SENIORITY_TRANSITIONS_PLAN).

    uv run --group graph python -m paths.seniority

Reads the SpringRank revealed ranks that `transition_network.analyze` computes on
the directed `role` graph (`transition_network/role_nodes_analyzed.parquet`) and
turns them into a per-`role_canonical` seniority signal that covers the ~84% of
moves carrying no explicit seniority word — the thing the lexical layer cannot do.

Two steps:
  1. ORIENT. SpringRank's convention ranks the *source* of a move higher, but our
     edges are moves *to* more-senior destinations, so raw rank is inverted; and
     the absolute sign is arbitrary. We fix both by anchoring to Layer A: correlate
     -springrank with each role's mean lexical seniority ordinal (from
     `paths/steps.parquet`) and flip if needed. The result increases with seniority.
  2. SCALE. Convert to a bounded percentile `revealed_pct in [0,1]` and a
     `revealed_confidence` from SpringRank support (incident person-volume).

Output `paths/seniority_scores.parquet` (`role_canonical, revealed_pct,
revealed_confidence, revealed_z, support`). `build_spine` joins it per step and
fuses with the lexical level into `seniority_score` (see Layer 3b there). This
module is **propose-only**: it never overwrites the deterministic lexical ordinal.
"""

from __future__ import annotations

import argparse
import json
import time

import duckdb
import numpy as np

from paths import common as C

ROLE_NODES = C.ROOT / "transition_network" / "role_nodes_analyzed.parquet"
SCORES_OUT = C.OUT_DIR / "seniority_scores.parquet"


def build(threads: int) -> dict:
    if not ROLE_NODES.exists():
        raise SystemExit(f"{ROLE_NODES} missing; run "
                         f"`transition_network.analyze role` first")
    con = duckdb.connect(); con.execute(f"PRAGMA threads={threads}")
    started = time.monotonic()

    # role node -> revealed rank (springrank) + support, plus the role's mean
    # lexical ordinal from the steps (the Layer-A anchor for orientation).
    df = con.sql(f"""
      WITH lex AS (
        SELECT role_canonical, avg(seniority_ordinal) AS mean_lex, count(*) AS n
        FROM read_parquet('{str(C.STEPS_OUT)}')
        WHERE role_canonical IS NOT NULL
        GROUP BY 1
      )
      SELECT r.node AS role_canonical, r.springrank, r.springrank_support,
             lex.mean_lex
      FROM read_parquet('{str(ROLE_NODES)}') r
      LEFT JOIN lex ON lex.role_canonical = r.node
    """).df()

    # ORIENT: revealed seniority increases with the lexical anchor.
    revealed = -df["springrank"].to_numpy()  # source-higher convention -> invert
    both = df["mean_lex"].notna().to_numpy() & np.isfinite(revealed)
    corr = np.corrcoef(revealed[both], df["mean_lex"].to_numpy()[both])[0, 1]
    if corr < 0:
        revealed = -revealed
    z = (revealed - np.nanmean(revealed)) / (np.nanstd(revealed) or 1.0)
    df["revealed_z"] = z
    # SCALE to a bounded percentile in [0,1].
    order = df["revealed_z"].rank(method="average", pct=True)
    df["revealed_pct"] = order
    # CONFIDENCE from support (log person-volume), saturating at the 90th pct.
    sup = df["springrank_support"].to_numpy()
    cap = np.quantile(sup[sup > 0], 0.9) if (sup > 0).any() else 1.0
    df["revealed_confidence"] = np.clip(sup / (cap or 1.0), 0, 1)
    df = df.rename(columns={"springrank_support": "support"})

    out = df[["role_canonical", "revealed_pct", "revealed_confidence",
              "revealed_z", "support"]]
    out.to_parquet(SCORES_OUT, compression="zstd")
    con.close()

    return {
        "roles": len(out),
        "anchor_correlation_with_lexical": round(float(corr), 3),
        "flipped": bool(corr < 0),
        "roles_with_lexical_anchor": int(both.sum()),
        "runtime_s": round(time.monotonic() - started, 1),
        "output": str(SCORES_OUT),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--threads", type=int, default=8)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    summary = build(args.threads)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
