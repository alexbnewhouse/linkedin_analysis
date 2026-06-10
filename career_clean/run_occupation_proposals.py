"""Materialize the two PROPOSE-ONLY occupation coverage extensions (audit f.1).

The deterministic SOC backbone codes 21.5% of career_steps rows, which collapses
to 7.84% of transition edges on the flagship occupation axis. Two extensions the
module already built and evaluated never made it into artifacts; this runner
materializes both as review-queue-grade parquet files under
``normalized/mappings/``. NEITHER is joined into career_steps -- they are
proposals with evidence, to be consumed behind explicit confidence thresholds
(e.g. the occupation network, industry's occupation_prior) or curated into the
deterministic lexicon via the ratchet.

  career_occupation_proposals.parquet      (--part anchored; needs GPU + embed deps)
      One row per occupation-UNMATCHED distinct title value whose nearest
      O*NET anchor reaches the cosine threshold (default 0.70, the eval'd
      operating point): proposed SOC, the anchor title that attracted it, the
      cosine, and the value's row frequency. The 8-pair gold set behind the
      P=1.0 eval is thin by the module's own admission (FINDINGS), hence
      propose-only.

  career_description_cluster_proposals.parquet   (--part description; CPU)
      Row-keyed functional-cluster (SOC major group) proposals mined from
      free-text descriptions with the se_description lead/vote miner,
      generalized from the 459K self-employment rows to the full
      occupation-unmatched population that carries a description (4.39M rows;
      51.8% of all uncoded rows). Rows already covered by the production
      ``functional_cluster`` column (the SE population) are excluded.
      Confidence stays the miner's honest 0.50 (desc_lead) / 0.40 (desc_vote).

Run AFTER build_normalized (reads its mappings + career_steps):

    uv run --group embed python -m career_clean.run_occupation_proposals                # both parts
    uv run python -m career_clean.run_occupation_proposals --part description           # CPU-only
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import time
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .common import ROOT

MAPPINGS = ROOT / "normalized" / "mappings"
CAREER_STEPS = ROOT / "normalized" / "career_steps.parquet"
ANCHORED_OUT = MAPPINGS / "career_occupation_proposals.parquet"
DESC_OUT = MAPPINGS / "career_description_cluster_proposals.parquet"
COSINE_THRESHOLD = 0.70  # eval'd operating point (results/occupation.json)


def _write(path, columns: dict[str, list[Any]]) -> int:
    table = pa.table(columns)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(path)
    return table.num_rows


# ------------------------------------------------------------------ anchored
def run_anchored(threshold: float = COSINE_THRESHOLD) -> None:
    from . import approach_c_embed as C_embed

    con = duckdb.connect()
    # unmatched only: values the deterministic lexicon coded keep their code;
    # blocked_* values (bare Owner/Retired/...) are deliberate refusals and
    # must not re-enter through the back door.
    rows = con.sql(f"""
        SELECT m.value, coalesce(v.freq, 1) AS freq
        FROM read_parquet('{MAPPINGS / "career_occupation.parquet"}') m
        LEFT JOIN read_parquet('{ROOT / "career_clean" / "cache" / "vocab_title.parquet"}') v
          ON m.value = v.value
        WHERE m.method = 'unmatched'
        ORDER BY freq DESC, m.value
    """).fetchall()
    values = [r[0] for r in rows]
    freq = {r[0]: r[1] for r in rows}
    total_rows = sum(freq.values())
    print(f"[anchored] {len(values)} unmatched values ({total_rows} rows)", flush=True)

    t0 = time.monotonic()
    cols: dict[str, list[Any]] = {
        "value": [], "freq": [], "proposed_soc": [], "anchor_title": [],
        "cosine": [], "method": [], "confidence": [],
    }
    for value, soc, anchor, cos in C_embed.anchored_occupation_proposals(values, threshold):
        cols["value"].append(value)
        cols["freq"].append(freq[value])
        cols["proposed_soc"].append(soc)
        cols["anchor_title"].append(anchor)
        cols["cosine"].append(round(cos, 4))
        cols["method"].append("anchored_embedding")
        # uncalibrated: the cosine itself, floored to the threshold band.
        cols["confidence"].append(round(cos, 4))
    n = _write(ANCHORED_OUT, cols)
    covered = sum(cols["freq"])
    print(
        f"[anchored] wrote {n} proposals ({100 * n / max(len(values), 1):.1f}% of values, "
        f"{100 * covered / max(total_rows, 1):.1f}% of unmatched rows) "
        f"in {time.monotonic() - t0:.1f}s -> {ANCHORED_OUT}",
        flush=True,
    )


# --------------------------------------------------------------- description
def _mine(arg: tuple) -> tuple | None:
    """Worker: (key..., description) -> proposal row or None."""
    from . import se_description as D

    src, lid, eidx, pidx, desc = arg
    cluster, method, conf, evidence = D.infer_cluster(desc)
    if cluster is None:
        return None
    return src, lid, eidx, pidx, cluster, method, conf, evidence


def run_description(processes: int | None = None) -> None:
    con = duckdb.connect()
    cur = con.execute(f"""
        SELECT source_table, linkedin_id, experience_idx, position_idx, description
        FROM read_parquet('{CAREER_STEPS}')
        WHERE occupation_method = 'unmatched'
          AND description IS NOT NULL
          AND functional_cluster IS NULL  -- SE rows: description already applied in production
    """)
    cols: dict[str, list[Any]] = {
        "source_table": [], "linkedin_id": [], "experience_idx": [], "position_idx": [],
        "proposed_cluster": [], "method": [], "confidence": [], "evidence": [],
    }
    t0 = time.monotonic()
    scanned = 0
    nproc = processes or max(1, (mp.cpu_count() or 2) - 2)
    with mp.Pool(nproc) as pool:
        while True:
            batch = cur.fetchmany(200_000)
            if not batch:
                break
            scanned += len(batch)
            for hit in pool.imap(_mine, batch, chunksize=2_000):
                if hit is None:
                    continue
                for col, v in zip(cols, hit):
                    cols[col].append(v)
            print(
                f"[description] scanned {scanned} rows, {len(cols['method'])} proposals "
                f"({time.monotonic() - t0:.0f}s)",
                flush=True,
            )
    n = _write(DESC_OUT, cols)
    print(
        f"[description] wrote {n} proposals ({100 * n / max(scanned, 1):.1f}% of the "
        f"{scanned} unmatched-with-description rows) in {time.monotonic() - t0:.1f}s "
        f"-> {DESC_OUT}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", choices=("both", "anchored", "description"), default="both")
    parser.add_argument("--threshold", type=float, default=COSINE_THRESHOLD)
    parser.add_argument("--processes", type=int, default=None)
    args = parser.parse_args()
    if args.part in ("both", "anchored"):
        run_anchored(args.threshold)
    if args.part in ("both", "description"):
        run_description(args.processes)


if __name__ == "__main__":
    main()
