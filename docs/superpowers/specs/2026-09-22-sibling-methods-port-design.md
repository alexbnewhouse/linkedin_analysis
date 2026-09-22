# Sibling-methods port: design

**Date:** 2026-09-22. **Branch:** `sibling-methods-port` (worktree off `recovery-refactor`
@ a754899). **Status:** approved in chat 2026-09-22; this is the written record.
**Source:** the assessment of `~/from_scratch_humanities_workforce` (a one-day clean-room
rebuild on the same raw shards, 2026-09-15). Six of its methods were judged worth porting; the
wage panel was explicitly excluded by the owner (portal policy forbids wage claims).

## Goal

Land six methods from the sibling build into this repo without breaking its contracts:
deterministic columns never mutate, everything new is appended with a `_source` column, every
apply is idempotent and dry-run by default, and every landed tier clears a measured precision
gate before it ships.

## Non-goals

- No wage imputation (owner decision).
- No decision on the time axis or the canonical cohort. The person table carries both axes and
  all three tiers so that decision can be made on numbers; it does not make it.
- No changes to `parse_linkedin.py`, the raw data, or any jury vote cache.
- No re-firing of any LLM jury.

## Working practice

- One dated notes file, `docs/notes/2026-09-22-sibling-methods-port.md`, records per piece:
  the pre-implementation reviewer's verdict, the before and after numbers, and the
  post-implementation reviewer's verdict. Nothing is reported as landed without the numbers.
- Per piece: a fresh subagent reviews the design section before code is written (question:
  is this an improvement, what breaks, what is the gate). Implementation is red/green/refactor
  with a data-independent suite added to `make test` and a data check added to `make test-data`.
  A second fresh subagent reviews the code and re-derives the before/after numbers afterwards.
  The implementer (the main session) is never a reviewer.
- The worktree holds a private copy of every mutable parquet output; read-only inputs
  (`parsed/`, `data/`, the three vote caches) are symlinks to the main checkout. At merge time
  the apply chain is re-run in the main checkout from the committed mappings, which is the same
  path a fresh clone takes.

## Pieces, in execution order

Order is by dependency and by how much each piece teaches the next: the benchmark measures
the baseline the other pieces will move; the education tiers feed the person table; the family
tier and the overrides both write the pooled occupation columns, family first so the overrides
can key on it.

### P1. External benchmarks (`validation/`, `reference/`)

**What.** Compare LinkedIn shares against two published references.

- `reference/nces_bachelors_by_field.json`: NCES Digest of Education Statistics Table 322.10
  counts of bachelor's degrees conferred by field for a set of academic years (1990-91,
  2000-01, 2005-06, 2010-11, 2015-16, 2020-21, 2021-22), with the table URL and edition. The
  core-humanities proxy is English + foreign languages + liberal arts/humanities +
  philosophy/religion + area/ethnic studies + history; the Digest folds history into "social
  sciences and history", so the history share is taken from the Digest's own history line where
  the edition prints it and otherwise from the Humanities Indicators share, and the choice is
  recorded per year in the JSON. Verified against the live table by fetch at build time; the
  fetch result is recorded in the JSON as `verified_on`.
- `reference/humanities_indicators.json`: the advanced-degree rate among humanities bachelor's
  holders (Humanities Indicators, ~40%), with URL.
- `validation/external_benchmarks.py`: reads `normalized/education.parquet`, restricts to
  rows with `degree_level_pooled = 4` and a non-null `end_year`, buckets by end year to the
  Digest years (±1 year), and computes the L1 share (via `nha_level_pooled = 1` on the row),
  plus English (CIP 23), history (54), business (52), and computer science (11) shares by
  `cip2_pooled`. Also the advanced-degree rate among persons with `hum_l1_bachelor_pooled_any`
  (highest pooled level ≥ 6). Output `validation/results/external_benchmarks.json`: per year,
  LinkedIn share, NCES share, ratio; plus the HI comparison; plus a release stamp.
- Reporting only. Nothing is written to a table.

**Tests.** `validation/validation_tests.py` (data-independent): the share arithmetic on a
synthetic education frame, the year bucketing, the JSON schema. `validation/benchmark_checks.py`
(data): every Digest year has n ≥ 1,000 LinkedIn rows; the L1 ratio is within [0.5, 1.5] for
every year (a tripwire, not a target).

**Gate.** Reviewer confirms the NCES numbers against the fetched table and that the ratio is
computed on the bachelor's rung, not any-degree.

### P2. Imputed bachelor's tier (`edu_clean/apply_bachelor_imputed.py`)

**What.** A row gets `degree_level_pooled = 4`, `degree_level_source = 'imputed_bachelor'`
when ALL hold:

1. `degree_level_pooled IS NULL` (deterministic and jury both missed);
2. `cip2_pooled IS NOT NULL AND cip2_pooled <> '53'` (a real field is coded);
3. the school is not a high school, MOOC, bootcamp, or a named graduate/professional school
   (regex on `school_raw`, the sibling's list extended with graduate-school patterns); and
   where the school resolves to IPEDS, `inst_iclevel_label` is a four-year institution;
4. `degree_raw` carries no degree token at all (already implied by 1, asserted anyway);
5. the person has no OTHER row for the same school with a graduate level (guards
   "Psychology / Harvard" typed beside "PhD / Harvard").

Runs after `apply_cip_pooled`, before `rebuild_education_person`. Idempotent: rebuilds from
`degree_level` + jury each time. Manifest `normalized/_bachelor_imputed_manifest.json`.
Measured candidates before the school gates: 265,995 rows, 95,563 persons gaining a first
level.

**Consumers.** `write_education_person` already uses `coalesce(degree_level_pooled,
degree_level)` for `highest_degree_level_pooled` and `hum_l1_bachelor_pooled_any`, so those grow.
`bachelor_end_year` stays on the deterministic rung (unchanged). A new column
`bachelor_level_source_any` on the person table records whether any bachelor-rung row is
imputed, so a consumer can exclude.

**Tests.** `edu_clean/imputed_tests.py`: the school regex on fixtures (high school, MOOC,
graduate school, seminary, plain university); the five-condition predicate on a synthetic
frame; idempotence. Data check added to `edu_clean/tier_tests.py`: no deterministic
`degree_level` changed (fingerprint), and every imputed row satisfies the predicate.

**Gate.** 100 imputed rows drawn by salted hash, shown to the post-reviewer with school, degree,
field, description: precision ≥ 0.90 that the row is plausibly a bachelor's (repo rescue bar).
Below the bar the tier stays propose-only (mapping written, not landed).

### P3. Co-majors and minors (`edu_clean/comajors.py`)

**What.** Port the sibling's splitting LOGIC (parentheticals, `minor in` / `x minor` /
`(minor)` markers, `double major in`, `concentration|emphasis|track in`, separators `/ ; & ,
and`), not its taxonomy. Resolution of each component goes through the existing value mapping
`normalized/mappings/edu_field.parquet` (exact on the raw string, then on the normalized
string). Rules, precision-first:

1. Whole string first: if the whole `field_raw` resolves with a `cip_*` method at confidence
   1.0, it is ONE field. No split. (Protects "Business Administration and Management,
   General" and every CIP title.)
2. Otherwise split. Each component must itself resolve with a `cip_*` method; a component that
   does not resolve is dropped, and if fewer than two components resolve the row has no
   secondary.
3. A component after a minor marker is a minor; after a concentration marker it is a
   concentration; the rest are majors in order of appearance. Primary = first major and must
   equal the row's existing `cip_code` (or the row is left alone; recorded as `conflict`).

Output: `normalized/mappings/edu_field_components.parquet` keyed by `field_raw` value:
`components` (JSON list of `{text, role, cip_code}`), `n_majors`, `n_minors`, `status`
(`single|split|conflict|unresolved`). An apply (`edu_clean/apply_comajors.py`) appends to
`education.parquet`: `cip_secondary`, `cip2_secondary`, `minor_cip2`, `field_components_n`,
`comajor_source`. `write_education_person` gains `double_major_any`, `hum_l1_comajor_any`
(L1 on a secondary major at the bachelor rung), `minor_hum_l1_any`.

**Tests.** `edu_clean/comajor_tests.py`: every CIP title in `reference/cip_codes.csv` yields
`status='single'` (regression against splitting CIP commas and "and"); the marker grammar on
the sibling's fixtures re-expressed as CIP expectations; `history and political science` →
54 + 45; `biology, chemistry minor` → major 26, minor 40; `english/journalism` → 23 + 09.
Data check: `cip_secondary` never equals `cip_code`; no row with `status='single'` carries a
secondary.

**Gate.** 100 split rows by salted hash, reviewed blind: precision ≥ 0.90 on "these are two
distinct majors/minors and the CIPs are right".

### P4. Occupation-family tier (`career_clean/families/`)

**What.** Port `classify_titles.py`, `taxonomy.py` (FAMILIES, SENIORITY, and the family →
SOC-major anchor), and `test_classify_titles.py` verbatim into `career_clean/families/`
(`taxonomy.py`, `classify.py`, `family_tests.py`), then adapt only where the tests demand
(imports, house lint). Driver `career_clean/run_families.py`:

1. `classify`: run `classify_title` over every distinct title value in
   `normalized/mappings/career_title.parquet` (3.5M), writing
   `normalized/mappings/title_family.parquet`: `value, family, seniority9, flags, confidence,
   soc_major_anchor, landable`.
2. `gate`: join to `career_clean/results/soc_gold.parquet` through the title mapping
   (`value → role_canonical`; use `role_display` as the classified string, the gold's own
   `top_titles` as extra fixtures) and score `soc_major_anchor = gold_major` per family, on
   `confidence='high'`. Write `career_clean/results/family_gate.json`. A family is `landable`
   when its anchor precision ≥ 0.85 on ≥ 30 gold roles (the jury's bar; families with fewer
   gold roles are reported and stay unlandable). Non-occupation families (`student`, `intern`,
   `volunteer_board`, `not_working`, `unclassified`) never land.
3. `build_normalized.write_career_steps` gains `title_family`, `title_family_confidence`,
   `title_seniority9` (row-level from the mapping; propose-only) and extends the pooled major:
   precedence det > jury > family (landable AND high), with `occupation_source = 'family'`.
   The mapping is OPTIONAL like `role_soc_jury` (fresh clone builds without it).

**Tests.** `family_tests.py` (ported, 631 assertions) added to `make test`;
`career_clean/family_data_checks.py` (data): landed rows only where det and jury are null;
every landed family is in the gate file with `landable=true`; coverage delta printed.

**Gate.** The per-family precision file, read by the post-reviewer; plus a 100-row blind sample
of landed steps with title, employer, industry L1 and the assigned major.

**Expected.** SOC-major row coverage 61.3% → roughly 85–90% if most families clear. Any family
under the bar stays in the mapping as `landable=false` for later work.

### P5. Employer-keyed overrides (`career_clean/overrides.py`, `run_overrides.py`)

**What.** A pure function `override(title_raw, role_canonical, seniority_level,
seniority_rank_token, industry_l1, industry_l2) -> Override | None` over an ordered rule
table. Initial rules, each with a reason code:

| reason | condition | occupation_code | major |
|---|---|---|---|
| `vice_president` | `vice` in seniority tokens and role is `president` (or title matches VP patterns) | 11-1021 | 11 |
| `k12_principal` | title is bare `principal` / `school principal` / `assistant principal` AND industry L1 = EDU (L2 not higher-ed) | 11-9032 | 11 |
| `firm_principal` | bare `principal` AND industry L1 in (PRO, FIN, TEC, RE) | 11-1021 | 11 |
| `law_firm_partner` | title in {partner, managing partner, associate, senior associate, of counsel, counsel, shareholder} AND industry L2 is legal services | 23-1011 | 23 |

`assistant manager` seniority is NOT touched (it lives in the fused seniority score; the
pre-reviewer may argue for a separate propose-only column).

`run_overrides.py` reads `career_steps` + `industry/results/step_industry.parquet`, writes the
row-level mapping `normalized/mappings/career_occupation_override.parquet` keyed
`(source_table, linkedin_id, experience_idx, position_idx)` → `occupation_code_override,
soc_major_override, reason`. `write_career_steps` appends `occupation_code_pooled` (precedence
override > det) and lets override win the pooled major (`occupation_source = 'override'`).
The mapping is optional.

**Tests.** `career_clean/override_tests.py`: every rule on fixtures, negatives ("Vice
President of Sales" still 11 but 11-1021; "Principal Software Engineer" untouched; "Associate"
at a bank untouched). Data check: override rows count per reason; no override where the
condition fails.

**Gate.** Post-reviewer scores a 50-row sample per reason (title, employer, L1, L2, override).
A reason under 0.90 is removed from the table before landing.

### P6. Person summary and metrics cube v0 (`persons/`)

**What.** `persons/build_person.py` → `persons/person.parquet`, one row per `linkedin_id`:

- education: `bachelor_cip2`, `bachelor_cip4`, `bachelor_cip_source`, `bachelor_field_group`,
  `bachelor_nha_level` (det and pooled variants), `bachelor_level_source` (det | jury |
  imputed_bachelor), `bachelor_end_year`, `hum_l1_bachelor`, `hum_l2_bachelor`,
  `hum_l3_bachelor` (pooled), `double_major_any`, `comajor_cip2`, `minor_cip2`,
  `highest_degree_level_pooled`, `has_grad_degree`, `has_master`, `has_doctorate`, `has_jd`,
  `has_mba`, `has_md_prof`, `has_med`, `has_msw` (from `degree_type` and level), `inst_control_label`,
  `inst_state`;
- career (from `paths/steps.parquet`, `career_steps`, `step_industry`): `entry_year`,
  `first_soc_major`, `first_occupation_code_pooled`, `first_title_family`, `n_steps`,
  `n_employers`, `ever_manager_plus`, `ever_director_plus`, `ever_vp_plus`,
  `ever_founder_owner` (seniority tokens per `paths/common.SENIORITY_RANK` ≥ 6 / 7 / 8 and
  employment_type in owner/self-employed), `cur_soc_major`, `cur_occupation_code_pooled`,
  `cur_title_family`, `cur_role_display`, `cur_company_canonical_id`, `cur_industry_l1`,
  `cur_us_state`, `cur_start_year`;
- axes: `career_years_entry = LAST_COMPLETE_YEAR - entry_year`, `career_years_grad =
  LAST_COMPLETE_YEAR - bachelor_end_year`, `career_stage_entry`, `career_stage_grad`
  (0-2, 3-5, 6-10, 11-20, 21+); no coalescing of the two.

`persons/build_metrics.py` → `persons/results/metrics.json` + `persons/results/tables/*.csv`.
Groups: `all`; `tier:l1|l2|l3` (bachelor, pooled); `group:<bachelor_field_group>`;
`cip2:<code>` with n ≥ 300. Per group: n; grad-degree rates by type; attainment flags;
`double_major`; current SOC-major distribution and current family distribution; first SOC
major; breadth (entropy, majors for 80%, top-3 share); first → current transition counts;
plus-k panels (k = 1, 5, 10, 20) on BOTH axes as separate keys (`at_k_entry`, `at_k_grad`);
seniority attainment by stage on both axes; time-to-first-job on the grad axis; top employers,
industries, states; cohort trend of the L1 bachelor share by end year. Every cell with
person-support < `portal.common.MIN_SUPPORT` (10) is suppressed, and a `suppressed_cells`
count is carried per panel. Top-level `release`: snapshot date, `LAST_COMPLETE_YEAR`, git SHA,
input manifests' timestamps, build time.

**Tests.** `persons/person_tests.py` (data-independent): stage bucketing, attainment from
tokens, entropy and 80% cover on fixtures, suppression rule. `persons/person_checks.py` (data):
row count equals distinct persons; every person with a bachelor's row has a
`bachelor_level_source`; the two axes are never coalesced (both columns nullable, no fill);
group n sums are consistent with the person table.

**Gate.** Post-reviewer reconciles five metrics against direct DuckDB queries on the source
tables (n by tier, grad-degree rate for L1, current SOC-major distribution for L1, at+10 on
each axis, suppressed-cell count) and confirms the release stamp is present.

**Makefile.** `persons` target; `make refresh` gains a `persons` stage after `archetypes`;
`scripts/check_freshness.py` learns the new outputs.

## What does not change

`education.parquet` and `career_steps.parquet` deterministic columns (fingerprint-asserted in
every apply). The jury mappings. `portal/`, `cohorts/`, `archetypes/` (they may read the new
columns later; nothing here rewires them). The share build.

## Risks and guards

- Coverage-raising tiers can only be judged by held-out precision; each has a gate scored by
  the reviewer, not the implementer.
- The co-major splitter's main risk is splitting CIP titles; the whole-string-first rule plus a
  test over every CIP title guards it.
- The imputed tier's risk is graduate degrees typed without a level word; the graduate-school
  regex, the IPEDS level, and the same-school-graduate-row guard reduce it, and the blind sample
  measures what remains.
- The family tier's anchor is a 2-digit convention per family; families whose members straddle
  majors (e.g. `general_management`, `business_analysis`) will fail the gate and stay unlanded.
- `write_career_steps` is a 75-second rebuild; every change to it is followed by
  `normalization_regression_checks.py`.

## Merge

Squash-free: one commit per piece, each with its tests green and its notes entry. Merge into
`recovery-refactor` after the six post-reviews. Then in the main checkout: re-run the apply
chain from the committed mappings and `make check-freshness`.
