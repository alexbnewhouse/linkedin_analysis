"""Integrity + sanity checks for the cohort panel (run after build_panel).

    uv run python -m cohorts.cohort_tests

Plain-assert style (cf. paths/spine_tests.py). Validates the Phase-0 panel that
every later phase consumes, plus a left-truncation guard: cross-cohort outcome
comparisons must be confined to the common observation window.
"""

from __future__ import annotations

import duckdb

from cohorts import common as C


def main() -> None:
    con = duckdb.connect()
    p = f"read_parquet('{str(C.PANEL_OUT)}')"
    pr = f"read_parquet('{str(C.PROFILES_OUT)}')"

    def check(name, cond):
        assert cond, f"FAIL: {name}"
        print(f"  ok: {name}")

    # --- panel integrity ---
    dup = con.sql(f"SELECT count(*) - count(DISTINCT (linkedin_id, calendar_year)) FROM {p}").fetchone()[0]
    check("panel: one row per (profile, calendar_year)", dup == 0)
    check("panel: no negative career_age",
          con.sql(f"SELECT count(*) FROM {p} WHERE career_age < 0").fetchone()[0] == 0)
    check("panel: no calendar_year past snapshot",
          con.sql(f"SELECT count(*) FROM {p} WHERE calendar_year > {C.SNAPSHOT_CAL_YEAR}").fetchone()[0] == 0)
    check("panel: job_zone_norm in [0,1] or NULL",
          con.sql(f"SELECT count(*) FROM {p} WHERE job_zone_norm < 0 OR job_zone_norm > 1").fetchone()[0] == 0)
    check("panel: seniority_score in [0,1] or NULL",
          con.sql(f"SELECT count(*) FROM {p} WHERE seniority_score < 0 OR seniority_score > 1").fetchone()[0] == 0)

    # --- profiles integrity ---
    bad_valid = con.sql(f"""SELECT count(*) FROM {pr}
        WHERE valid_cohort <> (entry_year BETWEEN {C.MIN_ENTRY_YEAR} AND {C.MAX_ENTRY_YEAR})""").fetchone()[0]
    check("profiles: valid_cohort iff entry_year in bounds", bad_valid == 0)
    check("profiles: observed_max_career_age >= 0",
          con.sql(f"SELECT count(*) FROM {pr} WHERE observed_max_career_age < 0").fetchone()[0] == 0)
    cov = con.sql(f"SELECT avg((entry_unemployment IS NOT NULL)::INT) FROM {pr} WHERE valid_cohort").fetchone()[0]
    check("profiles: entry_unemployment present for >95% of valid cohorts", cov > 0.95)

    # --- sanity: seniority rises with career age within a cohort ---
    s0, s8 = con.sql(f"""
        SELECT avg(seniority_score) FILTER (WHERE career_age = 0),
               avg(seniority_score) FILTER (WHERE career_age = 8)
        FROM {p} WHERE entry_cohort_bin = 2005""").fetchone()
    check("sanity: 2005 cohort mean seniority rises age 0 -> 8", s8 > s0)

    # --- left-truncation guard ---
    # Cohorts old enough to be fully observed (entry <= snapshot - window) must
    # actually reach the common window; the very recent bins (e.g. 2020) cannot,
    # which is why equal-window comparisons must restrict to the observable set.
    fully_obs_max_entry = C.SNAPSHOT_YEAR - C.COMMON_WINDOW_YEARS
    min_obs = con.sql(f"""
        SELECT min(mx) FROM (
          SELECT entry_cohort_bin, max(career_age) mx FROM {p}
          WHERE valid_cohort AND entry_year <= {fully_obs_max_entry} GROUP BY 1)""").fetchone()[0]
    check(f"left-truncation guard: fully-observable cohorts (entry<={fully_obs_max_entry}) "
          f"reach the common window ({C.COMMON_WINDOW_YEARS}y)", min_obs >= C.COMMON_WINDOW_YEARS)
    # and confirm a too-recent bin is correctly NOT fully observable (guards the bound)
    recent_max = con.sql(f"SELECT max(career_age) FROM {p} WHERE entry_cohort_bin = 2020").fetchone()[0]
    check("left-truncation guard: 2020 bin is below the window (correctly censored)",
          recent_max < C.COMMON_WINDOW_YEARS)

    con.close()
    print("\nAll cohort panel checks passed.")


if __name__ == "__main__":
    main()
