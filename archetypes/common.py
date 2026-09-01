"""Shared substrate for the archetypes module.

Loaders, paths, constants, the triangulated SOC-major coalesce, the
graduation-anchor + cohort logic (reusing edu_clean.anchors), and the
humanities-cohort definition. Everything keys on `linkedin_id`.

Stack: duckdb + pyarrow (project default). No pandas.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent

# --- Substrate paths --------------------------------------------------------
CAREER_STEPS = ROOT / "normalized" / "career_steps.parquet"
EDUCATION_PERSON = ROOT / "normalized" / "education_person.parquet"
EDUCATION = ROOT / "normalized" / "education.parquet"
ROLE_SOC_JURY = ROOT / "normalized" / "mappings" / "role_soc_jury.parquet"
STEP_INDUSTRY = ROOT / "industry" / "results" / "step_industry.parquet"
PANEL = ROOT / "cohorts" / "panel.parquet"
STEPS = ROOT / "paths" / "steps.parquet"
TRANSITIONS = ROOT / "paths" / "transitions.parquet"

RESULTS = Path(__file__).resolve().parent / "results"

# --- Cohort / window policy (ARCHETYPES_PLAN.md §3, §3a) --------------------
NHA_LEVELS = (1, 2, 3)          # humanities-inclusive cohort
MIN_YEAR = 1                     # career-year window floor (year 0 = grad year)
MAX_YEAR = 15                    # absolute ceiling
# Last FULLY observed calendar year (paths/common.LAST_COMPLETE_YEAR), which is
# what _window() needs -- NOT the snapshot's calendar year (2026, observed only
# through February). Unchanged by the 2026-08-05 snapshot-date correction.
SNAPSHOT_YEAR = 2025

# Career-ENTRY cohorts (5-year bins on first-job year). panel.valid_cohort caps
# entry at 1990-2020, so the bins span that. The honest observation window is
# DERIVED, not hardcoded: a cohort is observed to career-year = SNAPSHOT_YEAR -
# hi (the LATEST entry in the bin), capped at MAX_YEAR. Deriving it guarantees
# every member is fully observable across the whole window -> no within-window
# right-censoring (§3a). E.g. 2020 entrants -> 5, 2015-2019 -> 6, 2010-2014 -> 11.
# (cohort_key, lo_entry_year, hi_entry_year)
_COHORT_BINS: tuple[tuple[str, int, int], ...] = (
    ("<=2004", 1990, 2004),
    ("2005-2009", 2005, 2009),
    ("2010-2014", 2010, 2014),
    ("2015-2019", 2015, 2019),
    ("2020+", 2020, 2020),
)


def _window(hi: int) -> int:
    return max(0, min(MAX_YEAR, SNAPSHOT_YEAR - hi))


# (cohort_key, lo, hi, max_window) — window derived from the horizon rule.
GRAD_COHORTS: tuple[tuple[str, int, int, int], ...] = tuple(
    (key, lo, hi, _window(hi)) for key, lo, hi in _COHORT_BINS
)


def cohort_of(grad_year: int | None) -> tuple[str | None, int]:
    """Return (cohort_key, max_window) for a graduation year, or (None, 0)."""
    if grad_year is None:
        return None, 0
    for key, lo, hi, win in GRAD_COHORTS:
        if lo <= grad_year <= hi:
            return key, win
    return None, 0


def cohort_case_sql(col: str = "grad_year") -> str:
    """SQL CASE mapping a grad-year column to its cohort key (else NULL)."""
    whens = " ".join(
        f"WHEN {col} BETWEEN {lo} AND {hi} THEN '{key}'"
        for key, lo, hi, _ in GRAD_COHORTS
    )
    return f"CASE {whens} END"


def cohort_window_case_sql(col: str = "grad_year") -> str:
    """SQL CASE mapping a grad-year column to its max observation window."""
    whens = " ".join(
        f"WHEN {col} BETWEEN {lo} AND {hi} THEN {win}"
        for _key, lo, hi, win in GRAD_COHORTS
    )
    return f"CASE {whens} ELSE 0 END"


def connect(threads: int | None = None) -> duckdb.DuckDBPyConnection:
    import os
    if threads is None:
        threads = min(16, (os.cpu_count() or 8))
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    return con


# --- Triangulated SOC-major (ARCHETYPES_PLAN.md §2) -------------------------
# Detailed occupation_code prefix (21.5%) > LLM-jury soc_major (40%) >
# functional_cluster for the self-employed (2.2%). Union ~= 63% of steps.
# Returns a 2-digit SOC major string or NULL. `c` is the career_steps alias,
# `j` the role_soc_jury alias (LEFT JOINed on role_canonical).
def soc_major_expr(c: str = "c", j: str = "j") -> str:
    return f"""
        coalesce(
          CASE WHEN {c}.occupation_code IS NOT NULL
               THEN substr({c}.occupation_code, 1, 2) END,
          {j}.soc_major,
          CASE WHEN {c}.functional_cluster IS NOT NULL
                AND regexp_matches({c}.functional_cluster, '^[0-9]{{2}}$')
               THEN {c}.functional_cluster END
        )
    """


def soc_major_method_expr(c: str = "c", j: str = "j") -> str:
    return f"""
        CASE
          WHEN {c}.occupation_code IS NOT NULL THEN 'detail'
          WHEN {j}.soc_major IS NOT NULL THEN 'jury'
          WHEN {c}.functional_cluster IS NOT NULL
                AND {c}.functional_cluster NOT LIKE '%unspecified%'
                AND regexp_matches({c}.functional_cluster, '^[0-9]{{2}}$')
               THEN 'functional_cluster'
          ELSE NULL
        END
    """


def humanities_cohort_sql() -> str:
    """A view definition body selecting the humanities cohort keyed on the
    CAREER-ENTRY axis.

    The primary timeline is `entry_year` = first datable primary job (from
    cohorts/panel.parquet), universal and clean, matching panel.career_age used
    across the repo. Graduation year is NOT recoverable from career onset for
    ~86% of people (edu_clean's A3 tier was rejected at ~31% accuracy; measured
    here: entry vs true bachelor-end lands in a *different* 5-year bin 60% of the
    time), so entry-cohort is the honest full-population axis. The true A1/A2
    graduation anchor is carried as OPTIONAL metadata (`grad_year`, non-null only
    for ~14%) for a clean graduation-anchored re-cut.

    Yields: linkedin_id, nha_level, humanities_field_group, entry_year,
    entry_cohort, max_window, grad_year, anchor_tier.
    """
    from edu_clean import anchors as _anchors

    anchor_sql = _anchors.group_anchor_sql(
        group_key="hum",
        predicate_sql="e.cip_code IS NOT NULL",
        tiers=("A1", "A2"),
    )
    ep = str(EDUCATION_PERSON).replace("'", "''")
    panel = str(PANEL).replace("'", "''")
    # Humanities tier from the ANY-degree POOLED flags (det backbone + CIP jury),
    # NOT the terminal ep.nha_level. The terminal field undercounts L1 by ~21%
    # (History-BA-then-MBA lands on the MBA) and misses jury-coded fields; the
    # any-flags fix both. Nested, so the strongest (lowest) tier wins.
    nha_level_expr = ("CASE WHEN ep.hum_l1_any THEN 1 WHEN ep.hum_l2_any THEN 2 "
                      "WHEN ep.hum_l3_any THEN 3 END")
    return f"""
      WITH anchor AS ({anchor_sql}),
      entry AS (
        SELECT linkedin_id, min(entry_year) AS entry_year
        FROM read_parquet('{panel}')
        WHERE valid_cohort GROUP BY 1
      )
      SELECT ep.linkedin_id, {nha_level_expr} AS nha_level,
             ep.humanities_field_group_pooled AS humanities_field_group,
             en.entry_year,
             {cohort_case_sql('en.entry_year')} AS entry_cohort,
             {cohort_window_case_sql('en.entry_year')} AS max_window,
             a.anchor AS grad_year,
             a.anchor_method AS anchor_tier
      FROM read_parquet('{ep}') ep
      JOIN entry en USING (linkedin_id)
      LEFT JOIN anchor a USING (linkedin_id)
      WHERE ({nha_level_expr}) IN {NHA_LEVELS}
        AND en.entry_year IS NOT NULL
        AND {cohort_case_sql('en.entry_year')} IS NOT NULL
    """
