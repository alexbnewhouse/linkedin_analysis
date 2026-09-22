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

## P2. Imputed bachelor's tier

## P3. Co-majors and minors

## P4. Occupation-family tier

## P5. Employer-keyed overrides

## P6. Person summary and metrics cube v0
