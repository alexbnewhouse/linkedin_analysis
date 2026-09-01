"""Graduation-anchor recovery — Plan 2 of COVERAGE_PLAN.md.

Only ~20% of CIP-coded bachelor records carry a usable `end_year`, so the
portal's equal-observation-window discipline drops ~80% of every cohort. This
module computes `anchor_year` + `anchor_method` in {A1, A2, A3} per
(person, qualifying-degree population), with every inferred anchor carrying
method provenance and a measured, gated error profile.

  A1 — observed. Earliest usable `end_year` (in [1950, 2025], not
       `in_progress`) among a person's qualifying degree rows. This is the
       original portal rule, unchanged. Gold by construction. ACCEPTED.

  A2 — start-plus-duration. `start_year + D_HAT_BACHELOR` for rows that have
       `start_year` but no `end_year` at all. `D_HAT_BACHELOR` is fit
       empirically from the 220,421 both-dates CIP-bachelor rows to maximize
       the share landing within +/-1 year — NOT simply the median duration.
       The raw duration distribution is right-skewed (dur=2: 15.2%, dur=3:
       16.9%, dur=4: 47.8% [mode/median], dur=5: 10.5%), so the window
       {2,3,4} (offset 3) beats {3,4,5} (offset 4). Neither a per-decade nor
       a per-CIP2 duration split moves the +/-1yr share meaningfully (see
       anchor_eval.json), so a single constant offset is both simplest and
       empirically sufficient.
       MEASURED (person grain, matching the A1 min-collapse rule): 80.4%
       within +/-1yr (n=203,124), 95.2% within +/-2yr. Holds up across every
       entry decade (75-88%) and all five named majors (80.0-82.8%) — see
       edu_clean/results/anchor_eval.json / edu_clean/FINDINGS.md. CLEARS the
       80%/+/-1yr acceptance gate — ACCEPTED by default.

  A3 — career-onset inference. For persons with NO usable education dates at
       all (~77% of the CIP-bachelor population), the start year of the
       person's first plausible post-degree career step (first datable,
       in-workforce, non-intern/non-student primary step) from
       paths/steps.parquet. MEASURED: only ~31% within +/-1yr and ~42% within
       +/-2yr (median error 0, but very wide spread — average absolute error
       is 4-7 years even for thin one-step profiles, a genuine data-sparsity
       ceiling: LinkedIn profiles frequently omit early-career jobs, especially
       for older cohorts). Several iterations (excluding interns by title,
       requiring employee-type, requiring minimum tenure, entry-level-only
       first step, constant offsets from -5..+5, per-decade recentering) were
       tried and none moved the +/-1yr share above ~32% — see
       edu_clean/results/anchor_eval.json for the full grid. REJECTED per the
       gate; shipped flagged EXPERIMENTAL only, for provenance/completeness.

See `edu_clean/results/anchor_eval.json` (edu_clean/run_anchor_eval.py) for the
full validation harness output and `edu_clean/FINDINGS.md` for the writeup.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
STEPS = ROOT / "paths" / "steps.parquet"

# --- Shared bounds (must match portal.common / paths.common) ----------------
MIN_ANCHOR_YEAR = 1950
# Last FULLY observed graduation year (paths/common.LAST_COMPLETE_YEAR), NOT the
# snapshot's calendar year. The snapshot is 2026-02-19, so admitting a 2026
# end_year would count an unearned degree as an observed anchor. Unchanged by
# the 2026-08-05 snapshot-date correction.
SNAPSHOT_YEAR = 2025
BACHELOR_LEVEL = 4

# --- A2: empirically fit duration offset ------------------------------------
# Only degree_level=4 (bachelor) has been validated against gold; other levels
# are informational medians (NOT gate-checked) provided for extensibility.
# See the module docstring for why 3, not the median duration of 4, is used
# for bachelor's.
D_HAT_BY_LEVEL: dict[int, int] = {
    1: 4,   # HS -- unvalidated
    2: 1,   # unvalidated
    3: 2,   # associate -- unvalidated
    4: 3,   # bachelor -- VALIDATED (anchor_eval.json); optimal +/-1yr offset
    5: 2,   # unvalidated
    6: 2,   # master -- unvalidated
    7: 4,   # doctorate -- unvalidated
}

# --- Tier policy -------------------------------------------------------------
ALL_TIERS = ("A1", "A2", "A3")
# Gate result (edu_clean/results/anchor_eval.json): A1 and A2 clear the
# >=80%-within-+/-1yr bar (A2 measures 80.4%); A3 misses badly (~31%).
ACCEPTED_TIERS: tuple[str, ...] = ("A1", "A2")
EXPERIMENTAL_TIERS: tuple[str, ...] = ("A3",)


def q(p) -> str:
    return str(p).replace("'", "''")


def a1_predicate_sql(alias: str = "e") -> str:
    """A1 usability predicate for one education row (unchanged rule)."""
    return (f"{alias}.end_year BETWEEN {MIN_ANCHOR_YEAR} AND {SNAPSHOT_YEAR} "
            f"AND NOT coalesce({alias}.in_progress, FALSE)")


def a2_candidate_sql(alias: str = "e", degree_level: int = BACHELOR_LEVEL) -> str:
    """A2 candidate anchor for one row: start_year + d_hat, only for rows with
    NO end_year at all (per the plan's "records with start only" scope), not
    in_progress, and only when the projected anchor does not exceed the
    snapshot (a projection past the snapshot is not an observed anchor)."""
    d_hat = D_HAT_BY_LEVEL[degree_level]
    return (
        f"CASE WHEN {alias}.end_year IS NULL "
        f"AND NOT coalesce({alias}.in_progress, FALSE) "
        f"AND {alias}.start_year BETWEEN 1900 AND {SNAPSHOT_YEAR} "
        f"AND {alias}.start_year + {d_hat} <= {SNAPSHOT_YEAR} "
        f"THEN {alias}.start_year + {d_hat} END"
    )


# --- A3: career-onset (from paths/steps.parquet) ----------------------------
# Best design found (see module docstring + anchor_eval.json iteration grid):
# the start year of a person's earliest datable, in-workforce, non-intern
# primary step. "in_workforce" = employment_type in (employee, business_owner,
# self_employed) (paths.common.WORKFORCE_TYPES); interns are excluded via
# seniority_ordinal (0 = intern/trainee in paths.common.SENIORITY_RANK).
def register_a3_onset(con) -> None:
    """Person-level TEMP TABLE a3_onset(linkedin_id, anchor_year). Independent
    of any major/degree population -- computed once, reused by every group."""
    steps = f"read_parquet('{q(STEPS)}')"
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE a3_onset AS
      SELECT linkedin_id, min(year(start_dt)) AS anchor_year
      FROM {steps}
      WHERE datable AND NOT bad_negative_duration AND NOT bad_future_start
        AND in_workforce
        AND (seniority_ordinal IS NULL OR seniority_ordinal >= 1)
        AND year(start_dt) BETWEEN {MIN_ANCHOR_YEAR} AND {SNAPSHOT_YEAR}
      GROUP BY 1
    """)


def _a3_join_expr(tiers: tuple[str, ...]) -> tuple[str, str]:
    """(join_clause, anchor_year_expr) for A3, or ('', 'NULL') if not enabled."""
    if "A3" not in tiers:
        return "", "NULL"
    return "LEFT JOIN a3_onset a3 USING (linkedin_id)", "a3.anchor_year"


def group_anchor_sql(
    group_key: str,
    predicate_sql: str,
    degree_level: int = BACHELOR_LEVEL,
    alias: str = "e",
    tiers: tuple[str, ...] = ACCEPTED_TIERS,
    edu_table: str | None = None,
) -> str:
    """SQL for one population's (group_key, linkedin_id, anchor, anchor_method)
    rows, honoring which tiers are enabled. `predicate_sql` selects the
    qualifying-degree rows for this population (e.g. a CIP2-family bundle or
    "cip_code IS NOT NULL" for baseline); `degree_level` is applied in
    addition. A person's several qualifying rows collapse to ONE anchor per
    the precedence A1 > A2 > A3 (never fans out on linkedin_id).

    Requires `register_a3_onset(con)` to have been called first if "A3" is in
    `tiers`.
    """
    edu = edu_table or f"read_parquet('{q(EDUCATION)}')"
    a2_expr = a2_candidate_sql(alias, degree_level) if "A2" in tiers else "NULL"
    a3_join, a3_expr = _a3_join_expr(tiers)
    return f"""
      WITH per_row AS (
        SELECT {alias}.linkedin_id,
               CASE WHEN {a1_predicate_sql(alias)} THEN {alias}.end_year END AS a1,
               {a2_expr} AS a2
        FROM {edu} {alias}
        WHERE {alias}.degree_level = {degree_level} AND ({predicate_sql})
      ),
      per_person AS (
        SELECT linkedin_id, min(a1) AS a1, min(a2) AS a2
        FROM per_row GROUP BY 1
      )
      SELECT '{group_key}' AS group_key, p.linkedin_id,
             coalesce(p.a1, p.a2, {a3_expr}) AS anchor,
             CASE WHEN p.a1 IS NOT NULL THEN 'A1'
                  WHEN p.a2 IS NOT NULL THEN 'A2'
                  WHEN {a3_expr} IS NOT NULL THEN 'A3'
             END AS anchor_method
      FROM per_person p
      {a3_join}
      WHERE coalesce(p.a1, p.a2, {a3_expr}) IS NOT NULL
    """
