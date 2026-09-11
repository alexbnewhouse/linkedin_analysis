"""Build the career-path / transition-network spine (Layers 3-5).

    uv run python -m paths.build_spine            # -> paths/steps.parquet, transitions.parquet
    uv run python -m paths.build_spine --force

Reads ``normalized/career_steps.parquet`` and emits, via staged DuckDB SQL
(mirroring ``build_normalized.py``):

  steps.parquet        one row per career step + typed interval (Layer 3),
                       seniority ordinal, and concurrency flags (Layer 4).
  transitions.parquet  one row per move between successive *primary* steps of a
                       person (Layer 5) — the edge list every transition-network
                       grain aggregates from.

All work is relational (date parse + window + a bounded per-profile self-join),
which DuckDB does on CPU in seconds; this is not where the GPU helps. The GPU
payoff is downstream and this output is built for it: the edge list is the input
to GPU graph algorithms (cuGraph centrality / community detection) and to the
propose-only torch embedding layer — see CAREER_TRANSITION_NETWORK_PLAN.md §4.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import duckdb

from paths import common as C


def _quote(path) -> str:
    return str(path).replace("'", "''")


def _ranks_values() -> str:
    """SENIORITY_RANK -> a SQL VALUES list joined against split level tokens."""
    return ", ".join(f"('{tok}', {rank})" for tok, rank in C.SENIORITY_RANK.items())


def _connect(threads: int) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    return con


# --- Layer 3 + seniority ordinal: per-step enrichment -----------------------
# Date strings are "Mon YYYY" (month precision), "YYYY" (year precision),
# "Present" (open -> snapshot anchor), or NULL/garbage (undatable). Year-only
# intervals are widened to [Jan 1 .. Dec 31] and flagged via *_granularity so
# downstream math can treat them as imprecise.
STEPS_SQL = f"""
COPY (
  WITH src AS (
    SELECT
      *,
      row_number() OVER () AS row_id,
      count(*) OVER (PARTITION BY linkedin_id) AS profile_step_count
    FROM read_parquet('{{steps_in}}')
  ),
  bounded AS (  -- sanity bound: drop scrape-garbage mega-profiles
    SELECT * FROM src WHERE profile_step_count <= {C.MAX_STEPS_PER_PROFILE}
  ),
  ranks(tok, rank) AS (VALUES {{ranks}}),
  temporal AS (
    SELECT
      b.*,
      -- start
      coalesce(try_strptime(start_date, '{C.MONTH_FMT}'),
               try_strptime(start_date, '{C.YEAR_FMT}'))::DATE AS start_dt,
      CASE
        WHEN try_strptime(start_date, '{C.MONTH_FMT}') IS NOT NULL THEN 'month'
        WHEN try_strptime(start_date, '{C.YEAR_FMT}')  IS NOT NULL THEN 'year'
      END AS start_granularity,
      -- end
      (end_date = 'Present') AS is_ongoing,
      CASE
        WHEN end_date = 'Present' THEN DATE '{C.SNAPSHOT_DATE}'
        WHEN try_strptime(end_date, '{C.MONTH_FMT}') IS NOT NULL
          THEN last_day(try_strptime(end_date, '{C.MONTH_FMT}')::DATE)
        WHEN try_strptime(end_date, '{C.YEAR_FMT}') IS NOT NULL
          THEN make_date(year(try_strptime(end_date, '{C.YEAR_FMT}')), 12, 31)
      END AS end_dt,
      CASE
        WHEN end_date = 'Present' THEN 'present'
        WHEN try_strptime(end_date, '{C.MONTH_FMT}') IS NOT NULL THEN 'month'
        WHEN try_strptime(end_date, '{C.YEAR_FMT}')  IS NOT NULL THEN 'year'
      END AS end_granularity
    FROM bounded b
  ),
  toks AS (  -- explode the comma-joined rank-token SET, one token per row.
    -- seniority_rank_token (career_clean finding-2 axis) extends seniority_level
    -- with rank-only words (manager, supervisor) that the level signature must
    -- not absorb; fall back to seniority_level for older career_steps builds.
    SELECT row_id,
           unnest(string_split(coalesce(seniority_rank_token, seniority_level, ''), ',')) AS tok
    FROM temporal
  ),
  sen AS (  -- ordinal = rank of the most-senior NAMED token, else NULL (unknown)
    SELECT x.row_id, max(r.rank) AS seniority_ordinal
    FROM toks x
    LEFT JOIN ranks r ON r.tok = x.tok
    GROUP BY x.row_id
  )
  SELECT
    t.row_id,
    t.linkedin_id,
    t.source_table,
    t.experience_idx,
    t.position_idx,
    t.profile_step_count,
    -- resolved node attributes (the swappable network axes)
    t.company_canonical_id,
    t.company_id_canonical,
    t.company_raw,
    t.employment_type,
    t.title_raw,
    t.role_canonical,
    t.seniority_level,
    sen.seniority_ordinal,
    t.occupation_code,
    -- pooled SOC-major axis (deterministic prefix, else the calibrated jury
    -- major; audit 2026-09-02 H6 -- the spine used the 21% detailed code only)
    t.occupation_major_pooled AS soc_major,
    t.occupation_source       AS soc_source,
    t.location,
    -- Layer 3b: fused seniority_score in [0,1] = confidence-weighted mean of the
    -- three layers present (A lexical within-role, C revealed cross-role, B Job
    -- Zone cross-occupation). NULL when none fire. See SENIORITY_TRANSITIONS_PLAN.
    sc.revealed_pct,
    st.job_zone_norm,
    ( CASE WHEN sen.seniority_ordinal IS NOT NULL THEN {C.W_LEXICAL} * (sen.seniority_ordinal / {C.LEX_MAX_RANK}) ELSE 0 END
      + CASE WHEN sc.revealed_pct IS NOT NULL THEN {C.W_REVEALED} * coalesce(sc.revealed_confidence, 0) * sc.revealed_pct ELSE 0 END
      + CASE WHEN st.job_zone_norm IS NOT NULL THEN {C.W_JOBZONE} * st.job_zone_norm ELSE 0 END
    ) / NULLIF(
      CASE WHEN sen.seniority_ordinal IS NOT NULL THEN {C.W_LEXICAL} ELSE 0 END
      + CASE WHEN sc.revealed_pct IS NOT NULL THEN {C.W_REVEALED} * coalesce(sc.revealed_confidence, 0) ELSE 0 END
      + CASE WHEN st.job_zone_norm IS NOT NULL THEN {C.W_JOBZONE} ELSE 0 END
    , 0) AS seniority_score,
    -- confidence: strongest contributing layer + an agreement bonus per EXTRA
    -- layer. greatest(0, ...) clamps the no-layer case (bonus would be -0.1) so
    -- confidence is never negative and downstream `>= k` thresholds hold.
    greatest(0.0, least(1.0,
      greatest(
        CASE WHEN sen.seniority_ordinal IS NOT NULL THEN 0.75 ELSE 0 END,
        CASE WHEN st.job_zone_norm IS NOT NULL THEN 0.6 ELSE 0 END,
        CASE WHEN sc.revealed_pct IS NOT NULL THEN 0.5 * coalesce(sc.revealed_confidence, 0) ELSE 0 END
      )
      + 0.1 * greatest(0, (sen.seniority_ordinal IS NOT NULL)::INT
               + (sc.revealed_pct IS NOT NULL)::INT
               + (st.job_zone_norm IS NOT NULL)::INT - 1)
    )) AS seniority_confidence,
    -- Layer 3: typed interval
    t.start_date AS start_date_raw,
    t.end_date   AS end_date_raw,
    t.start_dt,
    t.end_dt,
    t.start_granularity,
    t.end_granularity,
    t.is_ongoing,
    (t.start_dt IS NOT NULL AND t.end_dt IS NOT NULL) AS datable,
    -- inclusive month count (a single-month role is 1 month, not 0)
    CASE WHEN t.start_dt IS NOT NULL AND t.end_dt IS NOT NULL
         THEN date_diff('month', t.start_dt, t.end_dt) + 1 END AS tenure_months,
    -- sanity flags (surface, do not plot)
    (t.start_dt IS NOT NULL AND t.end_dt IS NOT NULL AND t.end_dt < t.start_dt)
      AS bad_negative_duration,
    (t.start_dt > DATE '{C.SNAPSHOT_DATE}') AS bad_future_start,
    (t.employment_type IN {C.sql_in_list(C.WORKFORCE_TYPES)}) AS in_workforce
  FROM temporal t
  LEFT JOIN sen ON sen.row_id = t.row_id
  LEFT JOIN sen_scores sc ON sc.role_canonical = t.role_canonical
  LEFT JOIN soc_status st ON st.soc_code = t.occupation_code
) TO '{{steps_out}}' (FORMAT parquet, COMPRESSION zstd)
"""


# --- Layer 4: concurrency flag (bounded per-profile self-join) --------------
# A datable step is is_concurrent_secondary when another datable step of the
# same person overlaps it by >= CONCURRENCY_OVERLAP_FRAC of the shorter interval
# AND outranks it. Rank (best first): in_workforce, longer dwell, finer date
# granularity (a precise record beats a year-widened one on an equal span — the
# only place granularity inflation is corrected; see red-team M3), more senior,
# earlier start, lower row_id (stable, unique tiebreaker => no mutual domination).
CONCURRENCY_SQL = f"""
WITH dat AS (
  SELECT row_id, linkedin_id, start_dt, end_dt,
         (date_diff('day', start_dt, end_dt) + 1) AS dur_days,
         CASE WHEN in_workforce THEN 1 ELSE 0 END AS wf,
         CASE start_granularity WHEN 'month' THEN 2 WHEN 'year' THEN 1 ELSE 0 END
           AS gran,
         coalesce(seniority_ordinal, -1) AS ord
  FROM read_parquet('{{steps_out}}')
  WHERE datable AND NOT bad_negative_duration
)
SELECT a.row_id,
       bool_or(
         (b.wf > a.wf)
         OR (b.wf = a.wf AND b.dur_days > a.dur_days)
         OR (b.wf = a.wf AND b.dur_days = a.dur_days AND b.gran > a.gran)
         OR (b.wf = a.wf AND b.dur_days = a.dur_days AND b.gran = a.gran
             AND b.ord > a.ord)
         OR (b.wf = a.wf AND b.dur_days = a.dur_days AND b.gran = a.gran
             AND b.ord = a.ord AND b.start_dt < a.start_dt)
         OR (b.wf = a.wf AND b.dur_days = a.dur_days AND b.gran = a.gran
             AND b.ord = a.ord AND b.start_dt = a.start_dt AND b.row_id < a.row_id)
       ) AS dominated
FROM dat a
JOIN dat b
  ON a.linkedin_id = b.linkedin_id
 AND a.row_id <> b.row_id
 AND date_diff('day', greatest(a.start_dt, b.start_dt),
                      least(a.end_dt, b.end_dt)) + 1
     >= {C.CONCURRENCY_OVERLAP_FRAC} * least(a.dur_days, b.dur_days)
GROUP BY a.row_id
"""


# --- Layer 5: edges between successive primary steps ------------------------
# gap/overlap are derived from the month-floors of the two boundaries, so a
# same-month A-ends/B-starts handoff is neither gap nor overlap (fixes the
# last-day-of-month off-by-one, red-team H1). has_overlap surfaces genuine
# concurrency that slipped under the Layer-4 threshold (red-team H2).
TRANSITIONS_SQL = f"""
COPY (
  WITH steps AS (
    SELECT s.*, coalesce(c.dominated, FALSE) AS is_concurrent_secondary
    FROM read_parquet('{{steps_out}}') s
    LEFT JOIN concurrency c USING (row_id)
  ),
  prim AS (  -- primary timeline: datable, sane (no neg/future), not a side-step
    SELECT * FROM steps
    WHERE datable AND NOT bad_negative_duration AND NOT bad_future_start
      AND NOT is_concurrent_secondary
  ),
  seq AS (
    SELECT
      linkedin_id,
      row_id AS from_row_id,
      lead(row_id)               OVER w AS to_row_id,
      start_dt AS from_start_dt, end_dt AS from_end_dt,
      greatest(tenure_months, 0) AS dwell_months,
      employment_type           AS from_employment_type,
      company_canonical_id      AS from_company, company_id_canonical AS from_company_id,
      role_canonical            AS from_role, seniority_level AS from_seniority,
      seniority_ordinal         AS from_seniority_ordinal,
      seniority_score           AS from_sen_score,
      seniority_confidence      AS from_sen_conf,
      occupation_code           AS from_occupation, location AS from_location,
      soc_major                 AS from_soc_major,
      lead(seniority_score)      OVER w AS to_sen_score,
      lead(seniority_confidence) OVER w AS to_sen_conf,
      lead(start_dt)             OVER w AS to_start_dt,
      lead(employment_type)      OVER w AS to_employment_type,
      lead(company_canonical_id) OVER w AS to_company,
      lead(company_id_canonical) OVER w AS to_company_id,
      lead(role_canonical)       OVER w AS to_role,
      lead(seniority_level)      OVER w AS to_seniority,
      lead(seniority_ordinal)    OVER w AS to_seniority_ordinal,
      lead(occupation_code)      OVER w AS to_occupation,
      lead(soc_major)            OVER w AS to_soc_major,
      lead(location)             OVER w AS to_location
    FROM prim
    WINDOW w AS (PARTITION BY linkedin_id ORDER BY start_dt, end_dt, row_id)
  ),
  paired AS (
    SELECT *,
      date_diff('month', date_trunc('month', from_end_dt),
                         date_trunc('month', to_start_dt)) AS delta_months,
      (to_sen_score - from_sen_score) AS delta_sen,
      least(coalesce(from_sen_conf, 0), coalesce(to_sen_conf, 0)) AS sen_conf
    FROM seq WHERE to_row_id IS NOT NULL
  )
  SELECT
    linkedin_id, from_row_id, to_row_id,
    from_start_dt, from_end_dt, to_start_dt,
    dwell_months,
    greatest(delta_months - 1, 0) AS gap_months,
    greatest(1 - delta_months, 0) AS overlap_months,
    (delta_months - 1 >= {C.GAP_MONTHS_MIN}) AS has_gap,
    (1 - delta_months >= {C.OVERLAP_MONTHS_MIN}) AS has_overlap,
    -- seniority direction: only when BOTH sides carry a named token (else unknown)
    CASE
      WHEN from_seniority_ordinal IS NULL OR to_seniority_ordinal IS NULL THEN 'unknown'
      WHEN to_seniority_ordinal > from_seniority_ordinal THEN 'up'
      WHEN to_seniority_ordinal < from_seniority_ordinal THEN 'down'
      ELSE 'flat'
    END AS seniority_direction,
    -- edge kind, in explicit priority order (red-team M2):
    --   exit > education-entry > self-employment axis > same-employer > move
    CASE
      WHEN to_employment_type IN {C.sql_in_list(C.EXIT_TYPES)} THEN 'exit'
      WHEN to_employment_type = 'student' THEN 'education_entry'
      WHEN from_employment_type NOT IN {C.sql_in_list(C.SELF_EMPLOYED_TYPES)}
       AND to_employment_type   IN {C.sql_in_list(C.SELF_EMPLOYED_TYPES)}
        THEN 'into_self_employment'
      WHEN from_employment_type IN {C.sql_in_list(C.SELF_EMPLOYED_TYPES)}
       AND to_employment_type   NOT IN {C.sql_in_list(C.SELF_EMPLOYED_TYPES)}
        THEN 'out_of_self_employment'
      WHEN from_company = to_company AND from_company IS NOT NULL
       AND from_company NOT LIKE 'nonorg:%' THEN
        CASE
          WHEN to_seniority_ordinal > from_seniority_ordinal THEN 'promotion'
          WHEN to_seniority_ordinal < from_seniority_ordinal THEN 'demotion'
          ELSE 'lateral'
        END
      ELSE 'move'
    END AS kind,
    -- NEW (additive): fused-seniority transition typing. Δsen is on a common
    -- cross-role/cross-company scale, so up/down is valid between firms — but
    -- only asserted when sen_conf clears CONF_MIN; else a neutral label.
    round(delta_sen, 4) AS delta_sen,
    round(sen_conf, 3)  AS seniority_score_confidence,
    CASE
      WHEN to_employment_type IN {C.sql_in_list(C.EXIT_TYPES)} THEN 'exit'
      WHEN to_employment_type = 'student' THEN 'education_entry'
      WHEN from_employment_type NOT IN {C.sql_in_list(C.SELF_EMPLOYED_TYPES)}
       AND to_employment_type   IN {C.sql_in_list(C.SELF_EMPLOYED_TYPES)} THEN 'into_self_employment'
      WHEN from_employment_type IN {C.sql_in_list(C.SELF_EMPLOYED_TYPES)}
       AND to_employment_type   NOT IN {C.sql_in_list(C.SELF_EMPLOYED_TYPES)} THEN 'out_of_self_employment'
      WHEN from_soc_major IS NOT NULL AND to_soc_major IS NOT NULL
       AND from_soc_major <> to_soc_major THEN
        CASE WHEN sen_conf >= {C.CONF_MIN} AND delta_sen >  {C.TAU_UP}   THEN 'occupation_change_up'
             WHEN sen_conf >= {C.CONF_MIN} AND delta_sen < -{C.TAU_DOWN} THEN 'occupation_change_down'
             ELSE 'occupation_change' END
      WHEN from_company = to_company AND from_company IS NOT NULL
       AND from_company NOT LIKE 'nonorg:%' THEN
        CASE WHEN sen_conf >= {C.CONF_MIN} AND delta_sen >  {C.TAU_UP}   THEN 'promotion'
             WHEN sen_conf >= {C.CONF_MIN} AND delta_sen < -{C.TAU_DOWN} THEN 'demotion'
             ELSE 'lateral' END
      ELSE  -- different employer
        CASE WHEN sen_conf >= {C.CONF_MIN} AND delta_sen >  {C.TAU_UP}   THEN 'employer_move_up'
             WHEN sen_conf >= {C.CONF_MIN} AND delta_sen < -{C.TAU_DOWN} THEN 'employer_move_down'
             WHEN sen_conf >= {C.CONF_MIN} THEN 'employer_move_lateral'
             ELSE 'employer_move' END
    END AS transition_type,
    -- HIGH-trust direction flag: TRUE when BOTH endpoints carry a lexical
    -- seniority token (the precision backbone), so consumers can isolate
    -- trustworthy up/down from the chance-level revealed-only 'down' calls.
    (from_seniority_ordinal IS NOT NULL AND to_seniority_ordinal IS NOT NULL)
      AS direction_from_lexical,
    -- confidence: deterministic rules ~0.95; directional labels scale with sen_conf
    CASE
      WHEN to_employment_type IN {C.sql_in_list(C.EXIT_TYPES)}
        OR to_employment_type = 'student'
        OR (from_employment_type IN {C.sql_in_list(C.SELF_EMPLOYED_TYPES)})
           <> (to_employment_type IN {C.sql_in_list(C.SELF_EMPLOYED_TYPES)}) THEN 0.95
      WHEN sen_conf >= {C.CONF_MIN} AND abs(delta_sen) > {C.TAU_UP}
        THEN round(0.5 + 0.5 * sen_conf, 3)
      ELSE round(0.4 * sen_conf, 3)
    END AS transition_confidence,
    from_employment_type, to_employment_type,
    from_company, to_company, from_company_id, to_company_id,
    from_role, to_role, from_seniority, to_seniority,
    from_seniority_ordinal, to_seniority_ordinal,
    from_sen_score, to_sen_score,
    from_occupation, to_occupation,
    from_soc_major, to_soc_major,
    from_location, to_location
  FROM paired
) TO '{{trans_out}}' (FORMAT parquet, COMPRESSION zstd)
"""


def _register_aux(con) -> bool:
    """Bootstrap-tolerant aux inputs for Layer 3b. `sen_scores` (Layer C, revealed
    seniority) is produced by paths/seniority.py *after* a first spine pass, so on
    pass 1 we register an empty table (NULL revealed scores) and enrich on pass 2.
    `soc_status` (Layer B, Job Zone) is static reference data; register it as a
    view if present, else empty. Returns whether revealed scores were available."""
    if C.SOC_STATUS_PATH.exists():
        con.sql(f"CREATE TEMP VIEW soc_status AS "
                f"SELECT * FROM read_parquet('{_quote(C.SOC_STATUS_PATH)}')")
    else:
        con.sql("CREATE TEMP TABLE soc_status(soc_code VARCHAR, job_zone INT, "
                "svp_low DOUBLE, svp_high DOUBLE, job_zone_norm DOUBLE)")
    if C.SENIORITY_SCORES_PATH.exists():
        con.sql(f"CREATE TEMP VIEW sen_scores AS "
                f"SELECT * FROM read_parquet('{_quote(C.SENIORITY_SCORES_PATH)}')")
        return True
    con.sql("CREATE TEMP TABLE sen_scores(role_canonical VARCHAR, "
            "revealed_pct DOUBLE, revealed_confidence DOUBLE, "
            "revealed_z DOUBLE, support DOUBLE)")
    return False


def build(steps_in, steps_out, trans_out, threads: int) -> dict:
    con = _connect(threads)
    timings = {}
    has_scores = _register_aux(con)

    t0 = time.monotonic()
    print(f"[spine] Layer 3: temporal + seniority enrichment "
          f"(revealed scores: {'yes' if has_scores else 'BOOTSTRAP/none'}) ...", flush=True)
    con.sql(STEPS_SQL.format(steps_in=_quote(steps_in), steps_out=_quote(steps_out),
                             ranks=_ranks_values()))
    timings["steps"] = round(time.monotonic() - t0, 1)
    print(f"[spine] steps done in {timings['steps']}s", flush=True)

    t0 = time.monotonic()
    print("[spine] Layer 4: concurrency self-join ...", flush=True)
    # In-memory temp table (no intermediate parquet to clean up) consumed by L5.
    con.sql(f"CREATE TEMP TABLE concurrency AS "
            f"{CONCURRENCY_SQL.format(steps_out=_quote(steps_out))}")
    timings["concurrency"] = round(time.monotonic() - t0, 1)
    print(f"[spine] concurrency done in {timings['concurrency']}s", flush=True)

    t0 = time.monotonic()
    print("[spine] Layer 5: transition edges ...", flush=True)
    con.sql(TRANSITIONS_SQL.format(steps_out=_quote(steps_out), trans_out=_quote(trans_out)))
    timings["transitions"] = round(time.monotonic() - t0, 1)
    print(f"[spine] transitions done in {timings['transitions']}s", flush=True)

    stats = con.sql(f"""
      SELECT
        count(*) AS steps,
        count(DISTINCT linkedin_id) AS profiles,
        round(avg(datable::INT), 4) AS frac_datable,
        round(avg(is_ongoing::INT), 4) AS frac_ongoing,
        sum(bad_negative_duration::INT) AS bad_negative,
        sum(bad_future_start::INT) AS bad_future
      FROM read_parquet('{_quote(steps_out)}')
    """).fetchone()
    conc = con.sql("SELECT count(*) FILTER (WHERE dominated) FROM concurrency").fetchone()[0]
    edge_stats = con.sql(f"""
      SELECT count(*), sum(has_gap::INT), sum(has_overlap::INT),
             sum((transition_confidence >= {C.CONF_MIN})::INT)
      FROM read_parquet('{_quote(trans_out)}')
    """).fetchone() if has_scores else (None,) * 4
    base = con.sql(f"SELECT count(*) FROM read_parquet('{_quote(trans_out)}')").fetchone()[0]
    frac_sen = con.sql(
        f"SELECT round(avg((seniority_score IS NOT NULL)::INT), 4) "
        f"FROM read_parquet('{_quote(steps_out)}')").fetchone()[0]
    kinds = con.sql(f"""
      SELECT kind, count(*) n FROM read_parquet('{_quote(trans_out)}')
      GROUP BY 1 ORDER BY n DESC
    """).fetchall()
    types = con.sql(f"""
      SELECT transition_type, count(*) n FROM read_parquet('{_quote(trans_out)}')
      GROUP BY 1 ORDER BY n DESC
    """).fetchall() if has_scores else []
    con.close()

    return {
        "has_revealed_scores": has_scores,
        "steps": stats[0],
        "profiles": stats[1],
        "frac_datable": stats[2],
        "frac_ongoing": stats[3],
        "bad_negative_duration": stats[4],
        "bad_future_start": stats[5],
        "concurrent_secondary_steps": conc,
        "transitions": base,
        "transitions_with_gap": edge_stats[1],
        "transitions_with_overlap": edge_stats[2],
        "transitions_typed_conf_ge_min": edge_stats[3],
        "frac_steps_with_seniority_score": frac_sen,
        "transition_kinds": {k: n for k, n in kinds},
        "transition_types": {str(k): n for k, n in types},
        "timings_s": timings,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--steps-in", type=Path, default=C.CAREER_STEPS)
    p.add_argument("--steps-out", type=Path, default=C.STEPS_OUT)
    p.add_argument("--transitions-out", type=Path, default=C.TRANSITIONS_OUT)
    p.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    p.add_argument("--force", action="store_true",
                   help="overwrite existing spine outputs")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    for out in (args.steps_out, args.transitions_out):
        if Path(out).exists() and not args.force:
            raise SystemExit(f"{out} exists; rerun with --force to replace it")

    started = time.monotonic()
    summary = build(args.steps_in, args.steps_out, args.transitions_out, args.threads)
    summary["runtime_s"] = round(time.monotonic() - started, 1)
    summary["snapshot_date"] = C.SNAPSHOT_DATE
    summary["outputs"] = {"steps": str(args.steps_out),
                          "transitions": str(args.transitions_out)}
    C.MANIFEST_OUT.write_text(json.dumps(summary, indent=2))
    print(f"\n[spine] {json.dumps(summary, indent=2)}", flush=True)


if __name__ == "__main__":
    main()
