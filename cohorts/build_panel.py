"""Phase 0 — cohort panel + per-profile cohort keys (COHORT_ANALYSIS_PLAN §6).

    uv run python -m cohorts.build_panel [--force]

Emits two tables from the spine (`paths/steps.parquet`, `paths/transitions.parquet`)
+ references (BLS unemployment, the person-level education rollup
`normalized/education_person.parquet`):

  profiles.parquet  one row per profile: entry_year (= first datable primary
                    step year), entry-year unemployment (the scarring instrument),
                    graduation_year, proxied generation, first occupation/employer,
                    observed career-age span, right-censored flag, valid_cohort.
  panel.parquet     annual (profile, career_age) panel: the person's PRIMARY role
                    each calendar year (highest seniority_score active that year),
                    with seniority_score, occupation status (job_zone_norm),
                    employment_type. career_age = calendar_year - entry_year.

All-CPU DuckDB. The panel is the substrate every later phase consumes; the
left-truncation/survivorship caveat (COHORT_ANALYSIS_PLAN §3) governs its use.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import duckdb

from cohorts import common as C

EDU_PERSON = C.ROOT / "normalized" / "education_person.parquet"


def _q(p) -> str:
    return str(p).replace("'", "''")


def build(threads: int) -> dict:
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    started = time.monotonic()
    steps = f"read_parquet('{_q(C.STEPS)}')"
    bls = f"read_parquet('{_q(C.BLS)}')"
    edu_person = f"read_parquet('{_q(EDU_PERSON)}')"

    # valid steps: datable, sane, placeable in time
    con.sql(f"""
      CREATE TEMP TABLE vstep AS
      SELECT linkedin_id, start_dt, end_dt,
             year(start_dt) AS y0, year(end_dt) AS y1,
             seniority_score, seniority_confidence, occupation_code,
             job_zone_norm, employment_type, role_canonical, tenure_months
      FROM {steps}
      WHERE datable AND NOT bad_negative_duration AND NOT bad_future_start
        AND year(start_dt) <= {C.SNAPSHOT_CAL_YEAR}
    """)

    # --- per-profile cohort keys -------------------------------------------
    con.sql(f"""
      CREATE TEMP TABLE prof AS
      WITH grad AS (
        -- graduation anchor from the person-level education rollup: prefer the
        -- bachelor completion year (the recession-scarring design's anchor;
        -- the old min(end_year) conflated HS/associate with college), falling
        -- back to the earliest credential end year (the old semantics).
        SELECT linkedin_id,
               CAST(coalesce(
                 CASE WHEN bachelor_end_year BETWEEN 1950 AND {C.SNAPSHOT_YEAR}
                      THEN bachelor_end_year END,
                 CASE WHEN any_end_year_min BETWEEN 1950 AND {C.SNAPSHOT_YEAR}
                      THEN any_end_year_min END,
                 CASE WHEN highest_degree_year BETWEEN 1950 AND {C.SNAPSHOT_YEAR}
                      THEN highest_degree_year END,
                 CASE WHEN any_end_year_max BETWEEN 1950 AND {C.SNAPSHOT_YEAR}
                      THEN any_end_year_max END
               ) AS INT) AS graduation_year
        FROM {edu_person}
      ),
      hum AS (
        -- humanities membership on the ANY-degree POOLED flags (det backbone +
        -- CIP jury). Uses hum_l*_any, NOT the terminal nha_level, so a
        -- History-BA-then-MBA person is still humanities. Enables the
        -- humanities-vs-non-humanities cohort cut the module was missing.
        SELECT linkedin_id,
               CASE WHEN hum_l1_any THEN 1 WHEN hum_l2_any THEN 2
                    WHEN hum_l3_any THEN 3 END AS nha_level_any,
               hum_l1_any, hum_l1_bachelor_any, humanities_field_group_pooled
        FROM {edu_person}
      ),
      base AS (
        SELECT
          linkedin_id,
          min(y0) AS entry_year,
          max(y1) AS last_year,
          count(*) AS n_steps,
          arg_min(occupation_code, start_dt) AS first_occupation,
          arg_min(role_canonical, start_dt) AS first_role,
          bool_or(end_dt >= DATE '{C.SNAPSHOT_CAL_YEAR}-01-01') AS right_censored
        FROM vstep GROUP BY 1
      )
      SELECT
        b.linkedin_id, b.entry_year, b.last_year,
        b.last_year - b.entry_year AS observed_max_career_age,
        b.n_steps, b.first_occupation, b.first_role, b.right_censored,
        g.graduation_year,
        (b.entry_year - {C.ENTRY_AGE_PROXY}) AS birth_year_proxy,
        {C.generation_for_birth_year_sql(f"(b.entry_year - {C.ENTRY_AGE_PROXY})")} AS generation,
        u.unemployment_rate AS entry_unemployment,
        (b.entry_year BETWEEN {C.MIN_ENTRY_YEAR} AND {C.MAX_ENTRY_YEAR}) AS valid_cohort,
        ({C.COHORT_BIN_YEARS} * (b.entry_year // {C.COHORT_BIN_YEARS})) AS entry_cohort_bin,
        coalesce(h.nha_level_any, 0) AS nha_level_any,
        coalesce(h.hum_l1_any, FALSE) AS hum_l1_any,
        coalesce(h.hum_l1_bachelor_any, FALSE) AS hum_l1_bachelor_any,
        h.humanities_field_group_pooled AS humanities_field_group
      FROM base b
      LEFT JOIN grad g USING (linkedin_id)
      LEFT JOIN hum h USING (linkedin_id)
      LEFT JOIN {bls} u ON u.year = b.entry_year
    """)
    con.sql(f"COPY (SELECT * FROM prof) TO '{_q(C.PROFILES_OUT)}' "
            f"(FORMAT parquet, COMPRESSION zstd)")

    # --- annual panel: primary role per (profile, calendar year) -----------
    # expand each step over the years its interval covers, then keep the
    # highest-seniority active role per person-year (the year's "primary").
    con.sql(f"""
      COPY (
        WITH expanded AS (
          SELECT v.linkedin_id,
                 unnest(range(v.y0, least(v.y1, {C.SNAPSHOT_CAL_YEAR}) + 1)) AS calendar_year,
                 v.seniority_score, v.seniority_confidence, v.occupation_code,
                 v.job_zone_norm, v.employment_type, v.role_canonical, v.tenure_months
          FROM vstep v
        ),
        primary_year AS (
          SELECT * FROM expanded
          QUALIFY row_number() OVER (
            PARTITION BY linkedin_id, calendar_year
            ORDER BY seniority_score DESC NULLS LAST, tenure_months DESC NULLS LAST
          ) = 1
        )
        SELECT
          p.linkedin_id, p.calendar_year,
          p.calendar_year - pr.entry_year AS career_age,
          pr.entry_year, pr.entry_cohort_bin, pr.entry_unemployment,
          pr.generation, pr.valid_cohort,
          pr.nha_level_any, pr.hum_l1_any, pr.hum_l1_bachelor_any,
          pr.humanities_field_group,
          p.seniority_score, p.seniority_confidence,
          p.occupation_code, p.job_zone_norm, p.employment_type, p.role_canonical
        FROM primary_year p
        JOIN prof pr USING (linkedin_id)
        WHERE p.calendar_year - pr.entry_year >= 0
      ) TO '{_q(C.PANEL_OUT)}' (FORMAT parquet, COMPRESSION zstd)
    """)

    # --- summary ------------------------------------------------------------
    pstats = con.sql(f"""
      SELECT count(*), count(*) FILTER (WHERE valid_cohort),
             count(graduation_year), count(entry_unemployment),
             count(generation)
      FROM read_parquet('{_q(C.PROFILES_OUT)}')""").fetchone()
    npanel = con.sql(f"SELECT count(*), count(DISTINCT linkedin_id) "
                     f"FROM read_parquet('{_q(C.PANEL_OUT)}')").fetchone()
    cohort_sizes = con.sql(f"""
      SELECT entry_cohort_bin, count(*) n
      FROM read_parquet('{_q(C.PROFILES_OUT)}')
      WHERE valid_cohort GROUP BY 1 ORDER BY 1""").fetchall()
    con.close()

    return {
        "profiles": pstats[0],
        "valid_cohort_profiles": pstats[1],
        "with_graduation_year": pstats[2],
        "with_entry_unemployment": pstats[3],
        "with_generation": pstats[4],
        "panel_rows": npanel[0],
        "panel_profiles": npanel[1],
        "valid_cohort_bin_sizes": {int(b): n for b, n in cohort_sizes},
        "runtime_s": round(time.monotonic() - started, 1),
        "outputs": {"profiles": str(C.PROFILES_OUT), "panel": str(C.PANEL_OUT)},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    for out in (C.PANEL_OUT, C.PROFILES_OUT):
        if os.path.exists(out) and not args.force:
            raise SystemExit(f"{out} exists; rerun with --force")
    summary = build(args.threads)
    (C.OUT_DIR / "_panel_manifest.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
