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
   ├─ persons/build_person.py         one row per person, both time axes, all tiers (2026-09-22)
   │     └─ persons/build_metrics.py  metrics cube v0: per-group panels, floor 10, release stamp
   ├─ validation/external_benchmarks  LinkedIn shares vs NCES / Humanities Indicators (reporting only)
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
are gated on the row's degree level, and uncoded high-school rows get 53; then the strict
imputed-bachelor tier, `edu_clean/apply_bachelor_imputed.py`, then the co-major columns,
`edu_clean/apply_comajors.py`) →
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
| Co-majors / minors (propose-only; P3 2026-09-22) | `uv run python -m edu_clean.run_comajors` (value mapping) then `apply_comajors --execute` (runs inside `build_normalized` after the imputed apply) | `mappings/edu_field_components.parquet`; education `cip_secondary`, `minor_cip`, `comajor_source`; person `double_major_any`, `hum_l1_comajor_any`, `minor_hum_l1_any`; blind sample `edu_clean/results/comajors_sample.jsonl` |
| Imputed bachelor's (strict, propose-only; P2 2026-09-22) | `uv run python -m edu_clean.apply_bachelor_imputed --execute` (runs inside `build_normalized` after the CIP apply) | `education.degree_level_source = 'imputed_bachelor'`; person flag `bachelor_imputed_any`; blind sample `edu_clean/results/imputed_bachelor_sample.jsonl` |
| SOC role tail | `uv run python -m career_clean.run_soc_jury` | `mappings/role_soc_jury.parquet` |
| Occupation-family tier (rules; P4 2026-09-22) | `make families` (classify + per-(family, stratum) gate) then `make normalize-career` | `mappings/title_family.parquet`; steps `title_family`, `title_family_confidence`, `title_seniority9`; pooled major `occupation_source = 'family'` only for gate-cleared strata (3 of 104) |
| Employer-keyed overrides (P5 2026-09-22) | `make overrides` then `make normalize-career` | `mappings/career_occupation_override.parquet` (row-level); steps `occupation_code_pooled`, `occupation_code_source`, `override_reason`; pooled major `occupation_source = 'override'` |
| Industry | `uv run python -m industry.fire_llm` | see `industry/SETUP.md` |

Pooled-occupation precedence on `career_steps` (2026-09-22): override > det > jury > family for
`occupation_major_pooled` / `occupation_source`; `occupation_code_pooled` is override > det (jury and
family know only the major group). The three propose-only mappings (`role_soc_jury`, `title_family`,
`career_occupation_override`) are OPTIONAL: a fresh clone builds with their columns NULL.

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

## Human coding of blind samples

Every propose-only tier drawn a blind sample that a reviewer scored against a rubric. `coding/`
exports each sample as a Label Studio project, ingests any annotator's labels, and scores precision
and Cohen's kappa (`make coding-export`; `coding/README.md`). Reviewer labels live in
`coding/labels/<sample>.<annotator>.jsonl`; superseded draws in `coding/labels/superseded/`.

## Status line and long jobs

`.claude/statusline.sh` (wired in `.claude/settings.json`) shows every running pipeline process
it can see by name (`⚙ normalize 4m, persons 1m`), any job started through
`scripts/track.sh <label> -- <command>` with a progress hint from its log (`▶ soc-tail 12m [pool]
4,200 done`), and the driver one-liner in `.build_status`. Finished markers stay for ten minutes
and are then removed by the status line itself; a `.build_status` that claims to be running with
no driver alive is flagged and removed after fifteen minutes. Nothing needs cleaning by hand.

## Tests

`make test` runs the logic suites that need no built parquet (about 10 s), plus the status-line checks (`scripts/statusline_tests.sh`):
humanities/degree-level rules, self-employment and company canonicalization
(`career_clean/company_tests`), the SOC jury filters, the industry classifier
(name-rule precision fixtures, propagation on a temp dir, curated provenance),
archetype assignment, certifications, the synthetic spine, and
`normalization_regression_checks.py` (incl. the fresh-clone bootstrap and the
freshness logic). Suites that read the built tables (`tier_tests`,
`enrichment_tests`, `cip_tests`, `portal_tests`, `cohort_tests`) run via
`make test-data`.
