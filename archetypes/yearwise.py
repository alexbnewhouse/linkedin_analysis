"""Phase 4 — project the humanities cohort onto archetypes, yearwise.

Career-entry career_year = calendar_year - entry_year (panel.career_age). Emits:
  - person_year_archetype.parquet : one row per (person, career_year) in [1,15]
  - occupancy.parquet             : stock  = persons per (entry_cohort, year, archetype)
  - state_flows.parquet           : population year-over-year archetype flow (Sankey)
  - job_flows.parquet             : actual job-change transitions (event-based)
All windowed per entry cohort's honest horizon (common.GRAD_COHORTS).
"""

from __future__ import annotations

from . import common as C


def _register_cohort(con) -> None:
    con.execute(f"CREATE OR REPLACE TEMP TABLE hum_cohort AS {C.humanities_cohort_sql()}")


def _register_role_archetype(con) -> None:
    ra = C.RESULTS / "role_archetype.parquet"
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE role_arch AS
      SELECT role_canonical, archetype_id, archetype_key, archetype_label
      FROM read_parquet('{ra}')
    """)


def build_person_year(con) -> str:
    panel = f"read_parquet('{C.PANEL}')"
    out = C.RESULTS / "person_year_archetype.parquet"
    # career_year = years since first job (= panel.career_age). grad_year /
    # anchor_tier are carried as OPTIONAL metadata for a graduation-anchored
    # re-cut on the ~14% with an A1/A2 anchor (common.humanities_cohort_sql).
    con.execute(f"""
      COPY (
        SELECT
          p.linkedin_id,
          (p.calendar_year - h.entry_year)               AS career_year,
          coalesce(r.archetype_id, 0)                    AS archetype_id,
          coalesce(r.archetype_label, 'Other / Unclassified') AS archetype_label,
          p.seniority_score,
          p.employment_type,
          h.nha_level,
          h.humanities_field_group,
          h.entry_year,
          h.entry_cohort,
          h.grad_year,
          h.anchor_tier,
          ((p.calendar_year - h.entry_year) <= h.max_window) AS in_window
        FROM {panel} p
        JOIN hum_cohort h USING (linkedin_id)
        LEFT JOIN role_arch r ON p.role_canonical = r.role_canonical
        WHERE p.valid_cohort
          AND (p.calendar_year - h.entry_year) BETWEEN {C.MIN_YEAR} AND {C.MAX_YEAR}
          AND h.entry_cohort IS NOT NULL
      ) TO '{out}' (FORMAT parquet)
    """)
    return str(out)


def build_occupancy(con) -> str:
    py = f"read_parquet('{C.RESULTS / 'person_year_archetype.parquet'}')"
    out = C.RESULTS / "occupancy.parquet"
    con.execute(f"""
      COPY (
        WITH stock AS (
          SELECT entry_cohort, career_year, archetype_id,
                 any_value(archetype_label) AS archetype_label,
                 count(DISTINCT linkedin_id) AS n_persons
          FROM {py}
          WHERE in_window
          GROUP BY entry_cohort, career_year, archetype_id
        )
        SELECT *,
               n_persons::DOUBLE / sum(n_persons) OVER
                 (PARTITION BY entry_cohort, career_year) AS share
        FROM stock
        ORDER BY entry_cohort, career_year, archetype_id
      ) TO '{out}' (FORMAT parquet)
    """)
    return str(out)


def build_state_flows(con) -> str:
    """Population year-over-year state flow — the Sankey's primary link tensor.
    For each person, their archetype at career_year t and t+1 (both in-window)
    form one ribbon; counts are DISTINCT persons per (cohort, t, from, to),
    including the diagonal (stayers). This captures everyone, not just people
    who changed jobs (that is build_job_flows)."""
    py = f"read_parquet('{C.RESULTS / 'person_year_archetype.parquet'}')"
    out = C.RESULTS / "state_flows.parquet"
    con.execute(f"""
      COPY (
        WITH s AS (
          SELECT linkedin_id, entry_cohort, career_year, archetype_id
          FROM {py} WHERE in_window
        )
        SELECT a.entry_cohort,
               a.career_year                       AS year_from,
               a.archetype_id                      AS from_archetype,
               b.archetype_id                      AS to_archetype,
               count(DISTINCT a.linkedin_id)        AS n_persons
        FROM s a
        JOIN s b
          ON a.linkedin_id = b.linkedin_id
         AND b.career_year = a.career_year + 1
         AND b.entry_cohort = a.entry_cohort
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3, 4
      ) TO '{out}' (FORMAT parquet)
    """)
    return str(out)


def build_job_flows(con) -> str:
    tr = f"read_parquet('{C.TRANSITIONS}')"
    out = C.RESULTS / "job_flows.parquet"
    # career_year of a transition = year(to_start_dt) - entry_year (career-entry axis). Both role
    # endpoints mapped to archetype; only in-window transitions kept.
    con.execute(f"""
      COPY (
        WITH mapped AS (
          SELECT
            h.entry_cohort,
            (year(t.to_start_dt) - h.entry_year)        AS career_year,
            coalesce(rf.archetype_id, 0)               AS from_archetype,
            coalesce(rt.archetype_id, 0)               AS to_archetype,
            h.max_window
          FROM {tr} t
          JOIN hum_cohort h USING (linkedin_id)
          LEFT JOIN role_arch rf ON t.from_role = rf.role_canonical
          LEFT JOIN role_arch rt ON t.to_role   = rt.role_canonical
          WHERE t.to_start_dt IS NOT NULL AND h.entry_cohort IS NOT NULL
        )
        SELECT entry_cohort, career_year, from_archetype, to_archetype,
               count(*) AS n_moves
        FROM mapped
        WHERE career_year BETWEEN {C.MIN_YEAR} AND max_window
        GROUP BY entry_cohort, career_year, from_archetype, to_archetype
        ORDER BY entry_cohort, career_year, from_archetype, to_archetype
      ) TO '{out}' (FORMAT parquet)
    """)
    return str(out)


def build_all(con) -> dict:
    _register_cohort(con)
    _register_role_archetype(con)
    py = build_person_year(con)
    occ = build_occupancy(con)
    sf = build_state_flows(con)
    jf = build_job_flows(con)
    return {"person_year": py, "occupancy": occ,
            "state_flows": sf, "job_flows": jf}
