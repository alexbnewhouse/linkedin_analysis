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
   │
   ├─ paths/build_spine.py            steps + transitions (carries soc_major/soc_source)
   │     └─ transition_network/build_network role → analyze role
   │           └─ paths/seniority.py  revealed-seniority scores → build_spine AGAIN
   │     └─ transition_network/{build_network,analyze} occupation | soc_major
   ├─ cohorts/build_panel.py          reads paths/steps + education_person
   ├─ archetypes/run_all.py           reads career_steps, step_industry, paths/*, cohorts/panel
   ▼
portal/run_portal_data.py → portal/run_share_build.py   the shareable portal
   (reads education, paths/*, transition_network/occupation_nodes_analyzed, step_industry)
```

That is the REAL dependency order (audit 2026-09-02, refactor team A.1). It is
encoded once, in `scripts/refresh_downstream.sh` (`make refresh`, 15 stages,
resumable with `START=n`), and checked by `scripts/check_freshness.py`
(`make check-freshness`, exit 1 when any output is older than its inputs). Run
both after any normalized rebuild or jury merge; the refresh ends with the check.

## build_normalized.py

```
uv run --with numpy python build_normalized.py [--sections all|education|career]
                                               [--skip-mappings]
```

Order of steps (education): value mappings → `education.parquet` →
**pooled applies** (degree-level jury first, then CIP: deterministic >
jury/frontier > knn_head > degree-type > degree-level; string-level 53 labels
are gated on the row's degree level, and uncoded high-school rows get 53) →
`education_person.parquet` → institution meta (IPEDS; skipped with a warning if
the crosswalk isn't built). Career: value mappings → functional-cluster rows →
`career_steps.parquet` (carries `occupation_major_pooled` from the SOC jury and
parsed `start_year/start_month/end_year/end_month/is_current`). The jury
mapping is OPTIONAL: a fresh clone builds `career_steps` with NULL pooled
columns and a warning, then the SOC jury runs and the table is rebuilt.

Company key precedence in `career_steps` (audit 2026-09-02): placeholder
(`nonorg:<bucket>`) > the row's own `company_id` > a `linkedin.com/school/<slug>`
employer URL (`id:<slug>`, method `school_url`; universities have no company_id)
> the value-level mapping, whose modal id is support-gated (`career_clean.common
.MIN_ID_ROWS` / `MIN_ID_SHARE`) so id-less rows never inherit an id from one or
two stray rows.

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
| CIP blind gold (held out; re-score after any tier change) | `uv run python -m edu_clean.gold_v1 score` | `edu_clean/results/frontier_gold_v1{,_score}.{parquet,json}` |
| CIP juror calibration on the gold (any local model) | `uv run python -m edu_clean.gold_v1 calibrate ollama/<model> "<name>=<url>\|<slots>\|ollama"` | `edu_clean/results/frontier_gold_v1_calibration.json` |
| CIP precision report + kNN threshold sweep | `uv run python -m edu_clean.gold_v1 report` / `uv run --group embed python -m edu_clean.gold_v1 knn` | `frontier_gold_v1_{report,knn_sweep}.json`; prose in `docs/methods/cip-precision-gold-v1.md` |
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
- Every build writes a `_manifest.json` next to its outputs. `make
  check-freshness` compares every stage's manifest against its inputs; run it
  before assuming a table is current.
- Industry `XOT` (unresolved) rows carry NO `sector`; depth-k coverage must be
  computed as `l1 <> 'XOT' AND depth >= k`; `step_industry` has exactly one row
  per `career_steps` row (asserted in the build).
- The curated industry tiers are `industry/curated.py` (hand, 1.0) >
  `industry/curated_head.py` (frontier-labeled head, 0.95) >
  `industry/curated_promoted.py` (jury-promoted, 0.95); the head tier's blind
  gate is `industry/results/head_gate_{blind,key}.jsonl` scored by
  `python -m industry.head_gate` (bar: L1 agreement >= 0.90).
- Name rules (`industry/name_rules.py`) are precision-tested on real displays
  in `industry/tests.py`; retired generic tokens are listed at the bottom of
  the rules file. Household names are curated-tier material (`curated.py`,
  `curated_head.py`, `curated_promoted.py`; precedence hand > head > promoted).
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

`make test` runs the logic suites that need no built parquet (about 10 s):
humanities/degree-level rules, self-employment and company canonicalization
(`career_clean/company_tests`), the SOC jury filters, the industry classifier
(name-rule precision fixtures, propagation on a temp dir, curated provenance),
archetype assignment, certifications, the synthetic spine, and
`normalization_regression_checks.py` (incl. the fresh-clone bootstrap and the
freshness logic). Suites that read the built tables (`tier_tests`,
`enrichment_tests`, `cip_tests`, `portal_tests`, `cohort_tests`) run via
`make test-data`.
