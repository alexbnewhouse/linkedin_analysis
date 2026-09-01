"""Build the CIP-jury candidate and gold parquets (pure DuckDB, no LLM).

Populations (both from ``normalized/education.parquet``, restricted to rows
with field text, keyed by ``field_norm = lower(trim(field_raw))``):

  * candidates -- rows where ``cip_code IS NULL`` (the deterministic field
    coder abstained): one row per distinct field string, with the evidence
    context the jury will see.
  * gold       -- rows where ``cip_code IS NOT NULL``: the same context
    columns computed the same way over the CODED rows, plus the dominant
    2-digit CIP family (``gold_cip2``) and its share (``dominance``). Only
    strings with dominance >= 0.90 are kept, and a deterministic
    frequency-stratified sample of 600 (200 per n_rows tercile) is flagged
    ``in_sample`` for calibration.

No joins are needed: every context column lives on education.parquet itself,
so all counts are exact. Evidence honesty: every context value is a
frequency-modal observation from the string's own rows; nothing is imputed.
``modal_degree_text`` is NULL whenever no row carries a non-blank degree_raw.

NOTE (mirrors the SOC-jury 2026-07-08 review finding): deterministic coding is
per RAW STRING, but lower/trim collapses distinct raws onto one field_norm, so
a field_norm can have both coded and uncoded rows -- candidates and gold
OVERLAP on 537 strings (probe 2026-07-09). Those mixed strings are excluded
from the jury merge (run_cip_jury.cmd_merge).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "edu_clean" / "results"
CANDIDATES = RESULTS / "cip_candidates.parquet"
GOLD = RESULTS / "cip_gold.parquet"

EDUCATION = ROOT / "normalized" / "education.parquet"

DOMINANCE_MIN = 0.90
SAMPLE_PER_TERCILE = 200
# Fixed salt for the deterministic stratified sample (ORDER BY hash(key||salt);
# no random.random() anywhere) -- rerunning extract reproduces the same 600.
SAMPLE_SEED = "cip_gold_v1"


def _modal_sql(counts_cte: str, value_col: str) -> str:
    """Deterministic mode: highest count, ties broken by value ASC."""
    return f"""
        SELECT field_norm, {value_col} AS v FROM (
          SELECT field_norm, {value_col},
                 row_number() OVER (PARTITION BY field_norm
                                    ORDER BY c DESC, {value_col} ASC) AS rn
          FROM {counts_cte}
        ) WHERE rn = 1
    """


def _build_context(con: duckdb.DuckDBPyConnection, tag: str, where: str) -> None:
    """Materialize ``ctx_{tag}``: one row per field_norm with the shared
    evidence context, over the education-row population selected by ``where``."""
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE pop_{tag} AS
        SELECT linkedin_id,
               lower(trim(field_raw)) AS field_norm,
               field_raw,
               nullif(trim(degree_raw), '') AS degree_text,
               degree_level, cip2
        FROM read_parquet('{EDUCATION}')
        WHERE field_raw IS NOT NULL AND trim(field_raw) <> '' AND {where}
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE agg_{tag} AS
        SELECT field_norm, count(*) AS n_rows,
               count(DISTINCT linkedin_id) AS n_persons,
               count(*) FILTER (degree_level = 4) AS n_bachelor_rows
        FROM pop_{tag} GROUP BY 1
    """)
    # Top-3 raw spellings by frequency, pipe-joined, each truncated to 60 chars.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE variants_{tag} AS
        WITH vc AS (
          SELECT field_norm, field_raw, count(*) AS c
          FROM pop_{tag} GROUP BY 1, 2
        ), ranked AS (
          SELECT field_norm, field_raw, c,
                 row_number() OVER (PARTITION BY field_norm
                                    ORDER BY c DESC, field_raw ASC) AS rn
          FROM vc
        )
        SELECT field_norm,
               string_agg(left(field_raw, 60), ' | ' ORDER BY rn) AS top_raw_variants
        FROM ranked WHERE rn <= 3 GROUP BY 1
    """)
    # Modal non-blank degree text (NULL when no row has one -- never invented).
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE deg_{tag} AS
        {_modal_sql(f'''(
          SELECT field_norm, degree_text, count(*) AS c
          FROM pop_{tag} WHERE degree_text IS NOT NULL GROUP BY 1, 2
        )''', 'degree_text')}
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ctx_{tag} AS
        SELECT a.field_norm, a.n_rows, a.n_persons,
               v.top_raw_variants,
               d.v AS modal_degree_text,
               a.n_bachelor_rows
        FROM agg_{tag} a
        LEFT JOIN variants_{tag} v USING (field_norm)
        LEFT JOIN deg_{tag} d USING (field_norm)
    """)


def build(con: duckdb.DuckDBPyConnection | None = None) -> dict:
    """Build both parquets on ONE connection; returns row counts."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    con = con or duckdb.connect()
    con.execute("PRAGMA threads=8")

    # ---- candidates: the uncoded tail --------------------------------------
    _build_context(con, "cand", "cip_code IS NULL")
    con.execute(f"""
        COPY (
          SELECT field_norm, n_rows, n_persons, top_raw_variants,
                 modal_degree_text, n_bachelor_rows
          FROM ctx_cand ORDER BY n_rows DESC, field_norm ASC
        ) TO '{CANDIDATES}' (FORMAT parquet)
    """)

    # ---- gold: deterministically coded strings -----------------------------
    _build_context(con, "gold", "cip_code IS NOT NULL")
    con.execute("""
        CREATE OR REPLACE TEMP TABLE gold_dom AS
        WITH fc AS (
          SELECT field_norm, cip2, count(*) AS c
          FROM pop_gold GROUP BY 1, 2
        ), ranked AS (
          SELECT field_norm, cip2, c, sum(c) OVER (PARTITION BY field_norm) AS tot,
                 row_number() OVER (PARTITION BY field_norm
                                    ORDER BY c DESC, cip2 ASC) AS rn
          FROM fc
        )
        SELECT field_norm, cip2 AS gold_cip2, c::DOUBLE / tot AS dominance
        FROM ranked WHERE rn = 1
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE gold_pre AS
        SELECT c.*, g.gold_cip2, g.dominance
        FROM ctx_gold c JOIN gold_dom g USING (field_norm)
        WHERE g.dominance >= {DOMINANCE_MIN}
    """)
    # Deterministic frequency-stratified calibration sample: 200 per n_rows
    # tercile, picked by a fixed salted hash (reproducible, seedless-RNG-free).
    con.execute(f"""
        COPY (
          WITH t AS (
            SELECT *, ntile(3) OVER (ORDER BY n_rows DESC, field_norm ASC) AS tercile
            FROM gold_pre
          ), r AS (
            SELECT *, row_number() OVER (
                       PARTITION BY tercile
                       ORDER BY hash(field_norm || '{SAMPLE_SEED}')) AS pick
            FROM t
          )
          SELECT field_norm, n_rows, n_persons, top_raw_variants,
                 modal_degree_text, n_bachelor_rows, gold_cip2, dominance,
                 tercile, (pick <= {SAMPLE_PER_TERCILE}) AS in_sample
          FROM r ORDER BY n_rows DESC, field_norm ASC
        ) TO '{GOLD}' (FORMAT parquet)
    """)

    counts = {
        "candidates": con.execute(
            f"SELECT count(*) FROM read_parquet('{CANDIDATES}')").fetchone()[0],
        "gold": con.execute(
            f"SELECT count(*) FROM read_parquet('{GOLD}')").fetchone()[0],
        "gold_in_sample": con.execute(
            f"SELECT count(*) FROM read_parquet('{GOLD}') WHERE in_sample").fetchone()[0],
    }
    return counts
