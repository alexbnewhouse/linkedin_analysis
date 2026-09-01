# Cohort analysis

Tracks how career outcomes evolve for groups sharing a starting point
(entry-year, graduation-year, proxied generation). Implements all phases of
`../COHORT_ANALYSIS_PLAN.md`. Consumes the spine (`paths/steps.parquet`,
`paths/transitions.parquet`), the fused `seniority_score`, occupation Job-Zone
status (`reference/soc_status.parquet`), and a BLS unemployment reference.

> **The governing caveat: selection.** LinkedIn is a present-day snapshot of
> survivors, so this analysis is **left-truncated / survivorship-biased** and
> **recency/backfill-biased** (older cohorts' early careers are sparsely
> backfilled from 2025 profiles; recent careers are fresh and fully recorded).
> These biases dominate naive cross-cohort comparisons. The phases are ordered
> to *expose* the bias first, then lead with the design most robust to it, and
> every output carries the caveat. **No result here is a clean population estimate.**

## Run (after the spine is built)

```bash
uv run python reference/build_bls_unemployment.py        # one-time reference
uv run python -m cohorts.build_panel --force             # Phase 0: panel + cohort keys
uv run python -m cohorts.cohort_tests                     # integrity + sanity
uv run python -m cohorts.profiles                         # Phase 1: equal-age profiles
uv run --group cohort python -m cohorts.scarring          # Phase 2: entry-conditions
uv run --group cohort python -m cohorts.survival          # Phase 3: time-to-advance
uv run python -m cohorts.typologies                       # Phase 4: typologies + mix
uv run python -m cohorts.generational                     # Phase 5: generational
```

## Phases & what they found

**Phase 0 — panel** (`build_panel.py`). Per-profile cohort keys
(`profiles.parquet`: entry_year, entry-year unemployment, graduation_year,
proxied generation, first occupation/employer, observed span, right-censored,
valid_cohort) + an **annual `(profile, career_age)` panel** (`panel.parquet`,
40.2M rows) holding each year's *primary* role (highest seniority active that
year). 1.996M profiles; 1.65M in valid cohorts (entry 1990-2020).

**Phase 1 — equal-age profiles** (`profiles.py`). Mean `seniority_score` /
Job-Zone by `(cohort, career_age)`, clipped to a common window. *Run first to
expose the bias:* at entry, older cohorts look more senior (1990: 0.39 vs 2015:
0.33 — a 0.063 spread = the survivorship/backfill signature); by age 8 it
reverses. Cross-cohort *levels* are not trustworthy.

**Phase 2 — entry-conditions / scarring** (`scarring.py`). The one *identified*
design: WLS of mean seniority on the **entry-year unemployment rate** + career
age (+ period FE robustness), SE clustered by entry-year. Age-controlled: a
**−0.004 initial scar that fades over ~4.5 yrs** (both significant) — the
recession-scarring signature. **But** flagged as confounded (low-unemployment
cohorts are also the recent, better-documented ones); period FE removes it but
over-controls at the cell grain. Suggestive, not clean-causal.

**Phase 3 — survival** (`survival.py`). KM + Cox for time-to-first-upward-move,
right-censored at the snapshot. The dramatic cohort gradient (median 17y→6y,
1990→2015) is **largely a backfill/observation-window artifact**; the near-null
Cox HR (~1.0) for entry unemployment is the credible read.

**Phase 4 — typologies + mobility mix** (`typologies.py`). *The methodological
payoff:* compared at **equal observation** (first 8 yrs), cohort differences
mostly **vanish** — upward-move share is flat (~0.37 across all cohorts), 1995 vs
2015 transition mix nearly identical. One modest real trend: early
into-self-employment declines (0.027→0.016). Validates that the equal-age control
works (vs the artifacts in Phases 1/3).

**Phase 5 — generational** (`generational.py`). Tests the "job-hopping
generation" claim at matched career age. Millennials show ~2× moves/profile and
shorter tenure than Gen X — but this is **a documentation artifact** (matched
*age* doesn't fix differential backfill; recent cohorts' early moves are better
recorded), so our data **cannot** cleanly confirm or refute the claim. Generation
is a proxy (no birth date).

## Knobs (`common.py`)
`SNAPSHOT_YEAR`, `MIN/MAX_ENTRY_YEAR` (valid-cohort bounds), `COMMON_WINDOW_YEARS`
(equal-age comparison horizon), `COHORT_BIN_YEARS`, `ENTRY_AGE_PROXY`, generation
boundaries. The left-truncation guard in `cohort_tests.py` enforces that
equal-window comparisons stay within the observable set.

## Honest bottom line
The robust, repeatable findings are **null/artifact results** — at equal
observation, cohorts barely differ, and the dramatic raw gradients are selection
and backfill. That *is* the finding, and it matches the labor literature
("career-stage and the economy, not cohort"). The scarring coefficient is the
only positive signal, and it is explicitly hedged.
