# persons/: person summary table and metrics cube v0

    make persons            # build_person (12 s) then build_metrics (~50 s)
    make test               # persons.person_tests (logic)
    make test-data          # persons.person_checks (data invariants)

## What it is

`person.parquet` is one row per `linkedin_id` (1,999,974) that puts, side by side, the things
the axis and cohort decisions need: the bachelor's field on the pooled rung with its source, all
three humanities tiers as explicit flags, graduate-degree flags by type, the co-major flags, and a
career summary (first step, current step, attainment) on BOTH time axes. `results/metrics.json`
is one bulk pass over it: per group, the distributions, breadth, transitions, plus-k panels on
each axis, and attainment by stage, every cell suppressed below the portal floor.

It does not decide the axis or the cohort. It carries both so that decision can be made on numbers.

## Single-source rule

- Education per-person flags come FROM `normalized/education_person.parquet` and are never
  recomputed here: `bachelor_end_year` (deterministic rung), `highest_degree_level_pooled`,
  `hum_l1_bachelor` (= `hum_l1_bachelor_pooled_any`, the ANY-row rule), `bachelor_imputed_any`,
  `double_major_any`, `hum_l1_comajor_any`, `minor_hum_l1_any`.
- This table ADDS: the bachelor-rung ROW (pooled level 4; det source first, earliest end year;
  `bachelor_cip2`, `bachelor_cip_source`, `bachelor_level_source`, `bachelor_field_group`,
  `comajor_cip2`, `minor_cip2`), `hum_l2_bachelor` / `hum_l3_bachelor` (ANY-row on the bachelor
  rung), graduate-degree type flags from `degree_type`, the IPEDS join (`inst_control_label`,
  `inst_state`), and the career summary.
- Career columns derive from `paths/steps.parquet` (the temporal spine) joined NULL-safely on the
  four step keys to `normalized/career_steps.parquet` (pooled occupation, family, display, state)
  and `industry/results/step_industry.parquet`; the join is asserted to keep every spine row.
  `cohorts/profiles.parquet` stays the cohort-analysis view; `person_checks` asserts `entry_year`
  agrees with it.

## Rules that a reader must know

- Two axes, never coalesced: `career_years_entry = LAST_COMPLETE_YEAR - entry_year` (first datable
  step, 1,999,916 persons) and `career_years_grad = LAST_COMPLETE_YEAR - bachelor_end_year`
  (deterministic bachelor year, 279,671 persons). In-progress degrees are NULL on the grad axis.
- `tier:l1|l2|l3` in the cube use the ANY-row flags, so `bachelor_cip2` (one chosen row) and the
  tier can disagree for the 85k persons with more than one bachelor-rung row.
- `bachelor_end_year` is deterministic-only (as in `education_person`); `bachelor_cip2` is the
  pooled row. They can come from different rows.
- Current step = the ongoing step with the cohort panel's tie-break (`seniority_score DESC NULLS
  LAST, tenure_months DESC NULLS LAST`), so `cur_*` equals the panel's 2026 primary role.
- Graduate flags overlap by design: `has_master` is any level-6 degree that is not law, medicine or
  dental, so it includes MBA, M.Ed and MSW rows; `has_mba` / `has_med` / `has_msw` are subsets.
- Every panel carries `n_total` (persons in all cells), `n_kept` (cells that cleared the floor) and
  `n_printed` (the cells listed); a share must use `n_total` as its denominator.
- `suppressed_cells_by_panel` at the top level separates the employer long tail (one-person
  employers) from the substantive panels; `total_suppressed_cells_excluding_employers` is the
  number to quote.
- Attainment uses `seniority_ordinal` (manager 6, director 7, vice president 8), never the token
  string; `ever_founder_owner` is `employment_type IN (business_owner, self_employed)`.
- Plus-k panels are windowed: a person counts at horizon k only when the anchor year is at most
  `LAST_COMPLETE_YEAR - k`; `eligible` and `with_step` are both reported.
- Disclosure: every categorical cell below `portal.common.MIN_SUPPORT` (10) is dropped; when
  exactly one cell is below the floor the next-smallest cell is dropped too (audit 2.11's two-cell
  rule); a `suppressed_cells` count appears only when at least two cells were suppressed. Full
  complementary suppression across the nesting (tier:l1 inside tier:l2 inside all, cip2 groups
  inside field groups) is NOT done in v0; do not publish differences between nested panels.
- The release stamp (`_manifest.json`, `results/metrics.json`) carries snapshot id and date,
  calendar and last-complete years, git SHA with a dirty flag, the parameter block, input mtimes,
  and a schema version.
