# linkedin-analysis

Career and education trajectories of the US workforce, built from a 2.0M-profile
LinkedIn snapshot (2026-02-19), with a focus on humanities graduates (the NHA
Humanities Workforce portal). Raw JSONL → Parquet star schema → canonicalized
education/career tables → analysis layers (industry, archetypes, cohorts,
paths, transition networks) → a shareable portal.

**Start here:**

- `PIPELINE.md` — the DAG, build commands (`make <target>`), runtimes, and
  repo conventions. Read this before touching any build.
- `FOUNDATION.md` — the analytical foundation: cohort definitions, measurement
  decisions, known biases.
- `docs/` — methodology, audits (`docs/audits/`), plans (`docs/plans/`,
  historical in `docs/plans/archive/`), reference assets.
- `docs/plans/2026-09-01-recovery-and-refactor-plan.md` — the audit that
  shaped the current pipeline: coverage numbers per axis, recovery tasks,
  local-LLM hardware playbook.

## Layout

| Path | What |
|---|---|
| `parse_linkedin.py` | raw JSONL → `parsed/` star schema (lossless) |
| `build_normalized.py` | `parsed/` → `normalized/` canonical tables + pooled columns |
| `edu_clean/`, `career_clean/` | value canonicalizers + LLM juries (education / career) |
| `cert_clean/` | certifications → skills-domain axis |
| `cleanlib/` | shared cleaning primitives (normalizer; new modules build on this) |
| `industry/` | company → industry taxonomy (deterministic + jury) |
| `archetypes/` | role/skillset archetypes |
| `cohorts/`, `paths/`, `transition_network/` | analysis layers |
| `portal/`, `share/` | the Humanities Workforce portal build |
| `reference/` | O*NET, CIP, IPEDS reference data |
| `archive/` | one-off probes kept for the record; not live code |

## Setup

```bash
uv sync            # base deps (duckdb, pyarrow, orjson, …)
make test          # logic suites: no built parquet needed (~10 s)
make test-data     # suites that read the built tables
make check-freshness   # is every downstream table newer than its inputs?
```

Raw data (`data/*.jsonl`), `parsed/`, and large generated parquet are never
committed; see `.gitignore` and PIPELINE.md's conventions section.

LLM jury layers run on local hardware (RTX 5080 + a Strix Halo mini-PC on the
tailnet) — all propose-only, cached, and calibration-gated. No profile text
leaves these machines.
