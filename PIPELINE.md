# Pipeline map

The single source of truth for what builds what, in what order, and how long it
takes. `make <target>` (see `Makefile`) wraps every stage.

```
data/*.jsonl  (25 GB raw, 2.0M profiles — never committed)
   │  parse_linkedin.py                                ~20 min, 8 workers
   ▼
parsed/<table>/*.parquet   (star schema: profiles, education, experience,
   │                        positions, certifications, … + _manifest.json)
   │  build_normalized.py                              see below
   ▼
normalized/education.parquet          row-level credentials + pooled CIP/level
normalized/education_person.parquet   person-grain rollup (+ IPEDS inst_* meta)
normalized/career_steps.parquet       row-level career steps + pooled SOC major
normalized/mappings/*.parquet         value-keyed canonicalization mappings
   │
   ├─ industry/build_industry.py      company → industry (L1..L4) + step_industry
   ├─ archetypes/run_all.py           role/skillset archetypes + yearwise flows
   ├─ paths/  cohorts/  transition_network/   analysis-layer builds
   ▼
portal/run_portal_data.py → portal/run_share_build.py   the shareable portal
```

## build_normalized.py

```
uv run --with numpy python build_normalized.py [--sections all|education|career]
                                               [--skip-mappings]
```

Order of steps (education): value mappings → `education.parquet` →
**pooled applies** (CIP: deterministic > jury/frontier > knn_head > degree-type;
degree-level jury) →
`education_person.parquet` → institution meta (IPEDS; skipped with a warning if
the crosswalk isn't built). Career: value mappings → functional-cluster rows →
`career_steps.parquet` (carries `occupation_major_pooled` from the SOC jury and
parsed `start_year/start_month/end_year/end_month/is_current`).

`--skip-mappings` reuses `normalized/mappings/*.parquet` verbatim and rebuilds
only the row-level tables — **minutes instead of hours**. The mappings are
value-keyed, so they stay valid until the parsed vocabulary changes (i.e. after
a re-parse of new raw data, run once without the flag).

Measured on this machine (24 threads, `--skip-mappings`): education table 7s,
pooled applies ~2 min, person rollup 3s, career_steps 75s.

## Jury / LLM layers (all propose-only, all cached)

| Axis | Fire | Merge target |
|---|---|---|
| CIP field tail | `uv run python -m edu_clean.run_cip_jury tail --execute` | `mappings/field_cip_jury.parquet` |
| CIP disagreement tiebreak (local juror; FAILED gate) | `uv run python -m edu_clean.run_cip_tiebreak` | same, method `llm_jury_v1_tb` |
| CIP disagreement band, frontier adjudication | `uv run python -m edu_clean.frontier_merge add CHUNK.txt` / `merge --execute` | same, method `frontier_v1` |
| CIP long tail, embedding-kNN (head_exact lands) | `uv run --group embed python -m edu_clean.knn_tail` | `mappings/field_cip_knn.parquet` -> `cip_source='knn_head'` |
| Degree level tail | `uv run python -m edu_clean.run_dlevel_jury` | `mappings/degree_level_jury.parquet` |
| SOC role tail | `uv run python -m career_clean.run_soc_jury` | `mappings/role_soc_jury.parquet` |
| Industry | `uv run python -m industry.fire_llm` | see `industry/SETUP.md` |

Contract: votes land in append-only JSONL caches keyed by (evidence, model,
prompt version); merges write NEW mapping parquets; deterministic columns are
never mutated (fingerprint-asserted). After any merge, re-run
`build_normalized.py --skip-mappings` to land the pooled columns.

Local hosts: the 5080 llama-server lanes (`~/llm-serving`) and the Framework
Desktop (`100.73.40.75:11434`, Ollama). Serving configs, measured throughput,
and juror selection live in `docs/plans/2026-09-01-recovery-and-refactor-plan.md`
Part 3.

## Conventions

- Each analysis module owns `common.py` (path constants), `cache/` (regenerable,
  gitignored), `results/` (published outputs; parquet gitignored, JSON
  manifests committed), and a `run_*.py` CLI per entry point.
- Every build writes a `_manifest.json` next to its outputs. Check it before
  assuming a table is current.
- Generated portal/share artifacts are NOT tracked; rebuild via `make portal`.
- Known data limits (measured 2026-09-01): education years exist on only ~22%
  of raw rows (hard raw-data wall); 48 duplicate linkedin_ids among 2.0M
  profiles remain at parse grain (content-level duplicate flags catch their
  rows downstream; a re-parse for 48 persons was judged not worth it).
- `industry/llm_proposals.jsonl` (the industry jury's raw vote cache) was lost
  on 2026-09-01 (see PR #1). Production outputs and `curated_promoted.py`
  are intact; offline calibration replay and extending the industry jury
  require re-firing (`industry/fire_llm.py`, resumable).

## Tests

`make test` runs the data-independent suites (taxonomy/logic). Suites that read
parquet (`portal_tests`, `cohort_tests`, full `cip_tests`) need the built
tables and run via `make test-data`.
