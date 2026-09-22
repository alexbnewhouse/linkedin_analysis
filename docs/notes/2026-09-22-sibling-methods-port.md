# Sibling-methods port: running notes

**Date started:** 2026-09-22. **Spec:** `docs/superpowers/specs/2026-09-22-sibling-methods-port-design.md`.
**Branch:** `sibling-methods-port` (worktree). **Source project:** `~/from_scratch_humanities_workforce`.

Each piece records: pre-review verdict, before numbers, what was built, after numbers,
post-review verdict, and the decision (landed / propose-only / dropped). Numbers are measured,
with the query or command that produced them.

## Baseline (worktree, before any change)

Data: mutable parquet outputs copied from the main checkout (rsync, 2026-09-22); `parsed/`,
`data/` and the three vote caches are symlinks. `make test`: all suites pass (7 s).

Measured on `normalized/career_steps.parquet` (10,800,787 rows):

| axis | coverage |
|---|---|
| `occupation_code` (deterministic 6-digit) | 21.5% |
| `occupation_major_pooled` (det + jury) | 61.3% |
| `functional_cluster` | 4.3% |
| named `seniority_level` token | 30.4% |

Measured on `normalized/education.parquet` (3,577,659 rows): `degree_level_pooled` NULL on
647,041 rows; of those 265,995 carry a real `cip2_pooled` (not 53) and 95,563 persons would gain
their first degree level from an imputed-bachelor tier before any school gate. `field_raw`
contains a separator token (`and`, `/`, `,`, `&`, `;`, `double`, `minor`) on 44.5% of rows, an
upper bound that includes CIP titles.

Query: see `persons/` checks once built; until then the numbers above came from ad-hoc DuckDB
in the assessment session (2026-09-22).

## P1. External benchmarks

**Pre-review (fresh subagent, 2026-09-22): VERDICT: BUILD WITH CHANGES.** Verbatim core: "the 13%
history fallback is not defensible as specified. The Digest itself prints history bachelor's
separately: d22 Table 325.92 ... history's share is 19.6% (1990-91) ... 14.3% (2020-21). A flat 0.13
understates history by 10-35%"; "the plan is right to compare CORE6 against the NCES core proxy;
comparing L1 to it would print ratios of 1.3-1.4 and read as 'LinkedIn over-represents the
humanities', which is the opposite of the truth"; "the advanced-degree comparison is confounded by
cohort ... restricted to bachelor_end_year <= LAST_COMPLETE_YEAR - 10 (n = 21,597) the rate is 42.9%,
right on the HI figure". Changes adopted: printed history counts from Table 325.92 (verified by fetch;
2021-22 estimated at the 2020-21 share 0.143 and flagged); `l1_proxy` (core6 + theology 39 + visual
and performing arts 50) reported beside `core6`; advanced-degree primary line restricted to cohorts
<= 2015 with the all-persons line secondary; education fingerprint and stated biases in the output.

**Sources verified 2026-09-22 by fetch:** Digest d23 Table 322.10 (all 17 lines, six years; several
2020-21 values differ from the sibling's d22 hand entry); Digest d22 Table 325.92 (history bachelor's
1990-91 through 2020-21); Humanities Indicators: 42% of humanities majors held an advanced degree in
2021 (ACS); all graduates 37% (2018).

**Built:** `validation/` (common, external_benchmarks, validation_tests, benchmark_checks),
`reference/nces_bachelors_by_field.json`, `reference/humanities_indicators.json`,
`validation/results/external_benchmarks.json`. Command: `uv run python -m validation.external_benchmarks`.

**After (measured):**

| Digest year | LinkedIn n | core6 LinkedIn | core6 NCES | ratio | l1_proxy ratio |
|---|---|---|---|---|---|
| 1991 | 5,953 | 10.06% | 12.08% | 0.83 | 0.94 |
| 2001 | 10,103 | 8.53% | 11.68% | 0.73 | 0.87 |
| 2006 | 16,131 | 8.80% | 11.67% | 0.75 | 0.88 |
| 2016 | 33,756 | 6.30% | 7.83% | 0.80 | 0.91 |
| 2021 | 29,643 | 5.19% | 6.55% | 0.79 | 0.86 |
| 2022 (history est.) | 29,534 | 4.56% | 6.19% | 0.74 | 0.80 |

Advanced-degree rate among L1 bachelor's holders with bachelor's year <= 2015: 42.9% (n=21,597) vs
Humanities Indicators 42% (ratio 1.02); all persons 32.3% (n=181,767). Rung subset: dated rows
n=288,856 core6 6.81% vs undated n=1,190,936 core6 7.48%. Tests: `validation.validation_tests`
(logic) and `validation.benchmark_checks` (data) pass. Finding: LinkedIn under-represents core
humanities bachelor's by about a fifth, consistently across three decades.

## P2. Imputed bachelor's tier

## P3. Co-majors and minors

## P4. Occupation-family tier

## P5. Employer-keyed overrides

## P6. Person summary and metrics cube v0
