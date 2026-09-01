"""Build the SOC-jury candidate and gold parquets (pure DuckDB, no LLM).

Populations (both from ``paths/steps.parquet``, restricted to rows with a
``role_canonical``):

  * candidates -- steps where ``occupation_code IS NULL`` (the deterministic
    O*NET backbone abstained): one row per distinct ``role_canonical``, with the
    evidence context the jury will see.
  * gold       -- steps where ``occupation_code IS NOT NULL``: the same context
    columns computed the same way over the CODED steps, plus the dominant
    2-digit SOC major group (``gold_major``) and its share (``dominance``).
    Only strings with dominance >= 0.90 are kept (99.8% of coded strings), and
    a deterministic frequency-stratified sample of 600 (200 per n_steps
    tercile) is flagged ``in_sample`` for calibration.

JOIN KEY (verified by probe): steps <-> normalized/career_steps.parquet and
steps <-> industry/results/step_industry.parquet share the step identity
(linkedin_id, source_table, experience_idx, position_idx) -- but position_idx
is NULL for source_table='experience' rows, so the join MUST be null-safe
(IS NOT DISTINCT FROM). With plain equality only the 2.29M 'position' rows
match; null-safe the match rate is 100.0% (8,369,539/8,369,539 uncoded rows,
role_display present on all but 1). The key is unique up to 88 duplicate keys
per table (of 10.8M) -- negligible fan-out for the modal aggregations; exact
counts (n_steps, n_persons, top_titles, modal_seniority) are computed from
steps.parquet alone, without any join.

Evidence honesty: every context value is a frequency-modal observation from the
string's own steps; nothing is imputed. ``industry_l1_label`` is NULL whenever
no step resolved to a real L1 (XOT and NULL are unresolved).
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "career_clean" / "results"
CANDIDATES = RESULTS / "soc_candidates.parquet"
GOLD = RESULTS / "soc_gold.parquet"

STEPS = ROOT / "paths" / "steps.parquet"
CAREER_STEPS = ROOT / "normalized" / "career_steps.parquet"
STEP_INDUSTRY = ROOT / "industry" / "results" / "step_industry.parquet"
TAXONOMY_JSON = ROOT / "industry" / "taxonomy.json"

DOMINANCE_MIN = 0.90
SAMPLE_PER_TERCILE = 200
# Fixed salt for the deterministic stratified sample (ORDER BY hash(key||salt);
# no random.random() anywhere) -- rerunning extract reproduces the same 600.
SAMPLE_SEED = "soc_gold_v1"

# Null-safe step-identity join (position_idx IS NULL on 'experience' rows).
_STEP_KEY = (
    "s.linkedin_id = {t}.linkedin_id AND s.source_table = {t}.source_table "
    "AND s.experience_idx IS NOT DISTINCT FROM {t}.experience_idx "
    "AND s.position_idx IS NOT DISTINCT FROM {t}.position_idx"
)


def _l1_labels() -> list[tuple[str, str]]:
    """L1 industry code -> label from the frozen industry taxonomy (level==1)."""
    nodes = json.loads(TAXONOMY_JSON.read_text())["nodes"]
    return [(n["code"], n["label"]) for n in nodes if n["level"] == 1]


def _modal_sql(counts_cte: str, value_col: str) -> str:
    """Deterministic mode: highest count, ties broken by value ASC."""
    return f"""
        SELECT role_canonical, {value_col} AS v FROM (
          SELECT role_canonical, {value_col},
                 row_number() OVER (PARTITION BY role_canonical
                                    ORDER BY c DESC, {value_col} ASC) AS rn
          FROM {counts_cte}
        ) WHERE rn = 1
    """


def _build_context(con: duckdb.DuckDBPyConnection, tag: str, where: str) -> None:
    """Materialize ``ctx_{tag}``: one row per role_canonical with the shared
    evidence context, over the step population selected by ``where``."""
    # Population projection (no joins -> exact counts).
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE pop_{tag} AS
        SELECT linkedin_id, source_table, experience_idx, position_idx,
               role_canonical, title_raw,
               nullif(trim(seniority_level), '') AS seniority_level,
               occupation_code
        FROM read_parquet('{STEPS}')
        WHERE role_canonical IS NOT NULL AND {where}
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE agg_{tag} AS
        SELECT role_canonical, count(*) AS n_steps,
               count(DISTINCT linkedin_id) AS n_persons
        FROM pop_{tag} GROUP BY 1
    """)
    # Top-3 raw titles by frequency, pipe-joined, each truncated to 60 chars.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE titles_{tag} AS
        WITH tc AS (
          SELECT role_canonical, title_raw, count(*) AS c
          FROM pop_{tag} WHERE title_raw IS NOT NULL AND trim(title_raw) <> ''
          GROUP BY 1, 2
        ), ranked AS (
          SELECT role_canonical, title_raw, c,
                 row_number() OVER (PARTITION BY role_canonical
                                    ORDER BY c DESC, title_raw ASC) AS rn
          FROM tc
        )
        SELECT role_canonical,
               string_agg(left(title_raw, 60), ' | ' ORDER BY rn) AS top_titles
        FROM ranked WHERE rn <= 3 GROUP BY 1
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE sen_{tag} AS
        {_modal_sql(f'''(
          SELECT role_canonical, seniority_level, count(*) AS c
          FROM pop_{tag} WHERE seniority_level IS NOT NULL GROUP BY 1, 2
        )''', 'seniority_level')}
    """)
    # Modal readable label from career_steps (null-safe key), with modal raw
    # title as the fallback when no step has a role_display.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE disp_{tag} AS
        {_modal_sql(f'''(
          SELECT s.role_canonical, cs.role_display, count(*) AS c
          FROM pop_{tag} s
          JOIN read_parquet('{CAREER_STEPS}') cs ON {_STEP_KEY.format(t="cs")}
          WHERE cs.role_display IS NOT NULL AND trim(cs.role_display) <> ''
          GROUP BY 1, 2
        )''', 'role_display')}
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE disp_fb_{tag} AS
        {_modal_sql(f'''(
          SELECT role_canonical, title_raw, count(*) AS c
          FROM pop_{tag} WHERE title_raw IS NOT NULL AND trim(title_raw) <> ''
          GROUP BY 1, 2
        )''', 'title_raw')}
    """)
    # Modal RESOLVED industry L1 ('XOT' and NULL are unresolved -> excluded;
    # a string with no resolved step gets NULL, never an invented label).
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ind_{tag} AS
        {_modal_sql(f'''(
          SELECT s.role_canonical, split_part(si.l1, '.', 1) AS l1, count(*) AS c
          FROM pop_{tag} s
          JOIN read_parquet('{STEP_INDUSTRY}') si ON {_STEP_KEY.format(t="si")}
          WHERE si.l1 IS NOT NULL AND split_part(si.l1, '.', 1) <> 'XOT'
          GROUP BY 1, 2
        )''', 'l1')}
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ctx_{tag} AS
        SELECT a.role_canonical, a.n_steps, a.n_persons,
               coalesce(d.v, f.v) AS role_display,
               t.top_titles,
               ll.label AS industry_l1_label,
               sn.v AS modal_seniority
        FROM agg_{tag} a
        LEFT JOIN disp_{tag} d USING (role_canonical)
        LEFT JOIN disp_fb_{tag} f USING (role_canonical)
        LEFT JOIN titles_{tag} t USING (role_canonical)
        LEFT JOIN ind_{tag} i USING (role_canonical)
        LEFT JOIN l1_labels ll ON i.v = ll.code
        LEFT JOIN sen_{tag} sn USING (role_canonical)
    """)


def build(con: duckdb.DuckDBPyConnection | None = None) -> dict:
    """Build both parquets on ONE connection; returns row counts."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    con = con or duckdb.connect()
    con.execute("PRAGMA threads=8")

    con.execute("CREATE OR REPLACE TEMP TABLE l1_labels (code VARCHAR, label VARCHAR)")
    con.executemany("INSERT INTO l1_labels VALUES (?, ?)", _l1_labels())

    # ---- candidates: the uncoded tail --------------------------------------
    _build_context(con, "cand", "occupation_code IS NULL")
    con.execute(f"""
        COPY (
          SELECT role_canonical, n_steps, n_persons, role_display, top_titles,
                 industry_l1_label, modal_seniority
          FROM ctx_cand ORDER BY n_steps DESC, role_canonical ASC
        ) TO '{CANDIDATES}' (FORMAT parquet)
    """)

    # ---- gold: deterministically coded strings -----------------------------
    _build_context(con, "gold", "occupation_code IS NOT NULL")
    con.execute("""
        CREATE OR REPLACE TEMP TABLE gold_dom AS
        WITH mgc AS (
          SELECT role_canonical, left(occupation_code, 2) AS mg, count(*) AS c
          FROM pop_gold GROUP BY 1, 2
        ), ranked AS (
          SELECT role_canonical, mg, c, sum(c) OVER (PARTITION BY role_canonical) AS tot,
                 row_number() OVER (PARTITION BY role_canonical
                                    ORDER BY c DESC, mg ASC) AS rn
          FROM mgc
        )
        SELECT role_canonical, mg AS gold_major, c::DOUBLE / tot AS dominance
        FROM ranked WHERE rn = 1
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE gold_pre AS
        SELECT c.*, g.gold_major, g.dominance
        FROM ctx_gold c JOIN gold_dom g USING (role_canonical)
        WHERE g.dominance >= {DOMINANCE_MIN}
    """)
    # Deterministic frequency-stratified calibration sample: 200 per n_steps
    # tercile, picked by a fixed salted hash (reproducible, seedless-RNG-free).
    con.execute(f"""
        COPY (
          WITH t AS (
            SELECT *, ntile(3) OVER (ORDER BY n_steps DESC, role_canonical ASC) AS tercile
            FROM gold_pre
          ), r AS (
            SELECT *, row_number() OVER (
                       PARTITION BY tercile
                       ORDER BY hash(role_canonical || '{SAMPLE_SEED}')) AS pick
            FROM t
          )
          SELECT role_canonical, n_steps, n_persons, role_display, top_titles,
                 industry_l1_label, modal_seniority, gold_major, dominance,
                 tercile, (pick <= {SAMPLE_PER_TERCILE}) AS in_sample
          FROM r ORDER BY n_steps DESC, role_canonical ASC
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
