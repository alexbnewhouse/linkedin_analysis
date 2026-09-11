# Refactor-team audit — structure, duplication, dead code, tests, DAG hygiene

Date: 2026-09-02. Branch `recovery-refactor` (clean at start). Read-only audit; nothing under the repo was modified. Every claim cites a file:line, an LOC count, a similarity number, a grep, or an mtime. Scratch scripts and outputs: `dag_scan.py`, `dag.json`, `dag_summary.txt`, `reach.py`, `reach_strict.txt`, `reach_loose.txt`, `similarity.py`, `similarity.txt`, `invocations.txt`, `git_dates.tsv`, `mtimes.txt` (this directory).

Framing: the industry vote cache (`industry/llm_proposals.jsonl`, 2.7 GB) is gone; `industry/results/build_manifest.json` reads `llm_candidates = 0`, L1 row coverage 53.6%. Measured today from `company_industry.parquet` + `industry/cache/company_vocab.parquet`: method `unresolved` = 1,851,038 companies / 4,933,342 rows (46.4%), `occupation_prior` = 174,558 / 264,474 (2.5%); the text-bearing residual (`fire_llm._residual`) = 2,025,556 companies / 5,197,776 rows (48.9% of 10,636,544 company-bearing rows). Head is steep: top 5,000 residual companies = 9.6% of all rows, top 25k = 16.8%, top 50k = 20.5%, top 200k = 28.4%. A 25k-company re-fire recovers a third of the missing L1 mass. The plan (section E) is ordered around making that re-fire run through the shared, calibrated, cached machinery with the headless Claude host.

## Summary (top findings)

1. **F4 (cleanlib) is only started**: 163 LOC. The jury machinery is still four copies. `edu_clean/cip_llm.py` vs `career_clean/soc_llm.py` line-ratio **0.818** with 9 functions >=0.80 (4 identical); drivers `run_cip_jury` vs `run_soc_jury` **0.706**; `approach_b_fuzzy` **0.933**; `llm_pool` still lives in `industry/` and is imported by 5 edu/career files plus two `make_pool` monkeypatch seams (`run_cip_tiebreak.py:76-81`, `gold_v1.py:295-303`).
2. **F2 is not landed for career**: `build_normalized.py:948` hard-joins `mappings/role_soc_jury.parquet`, which only the SOC jury produces from `paths/steps` + `industry/results/step_industry` (both downstream of career_steps). Fresh clone cannot build career_steps (bootstrap cycle).
3. **`scripts/refresh_downstream.sh` is wrong** (proved by `refresh.log` stamps vs mtimes): archetypes ran 21:11-21:13 reading `paths/steps` and `cohorts/panel` that were rewritten at 21:13:47 / 21:14:14; `transition_network.analyze` and `paths.seniority` never run (portal consumed `occupation_nodes_analyzed.parquet` dated 2026-08-05; spine used 08-05 seniority scores); it passes `--no-llm`, which would silently drop re-fired industry votes; the education table was rewritten 12 minutes after the "done" portal build.
4. **Undocumented edges**: archetypes -> cohorts/paths/industry; portal -> `analyze.py` output; spine <-> revealed-seniority loop (only in METHODOLOGY.md); `archetypes/assign.py:142` writes into `normalized/mappings/`; `cert_clean` outputs have zero consumers; SOC taxonomy lives in `transition_network.common`.
5. **Industry residual sizing** (measured): text-bearing residual = 2,025,556 companies / 5,197,776 rows (48.9%); top-5k residual companies = 9.6% of rows, top-25k = 16.8%, top-50k = 20.5%. Headless Claude measured on SOC: Haiku $0.0013/str, Sonnet $0.0022, Opus $0.0053; a 25k two-voter industry re-fire ~ $250-350.
6. **Design (section B.3)**: `cleanlib/jury/{spec,cache,request,hosts,fire,gate,merge}.py`; `hosts.py` = `llm_pool.py` moved verbatim + `api="claude"` host wrapping `headless_claude.call`; `industry/fire_llm.py` becomes a `JurySpec` + `--backend claude`. Do-not-touch list of 12 items (cache-key payload, prompts/versions, Proposal line format, landed parquet schemas, merge exclusions, fingerprint asserts, `curated_promoted.PROMOTED`, vocab SQL tiebreaks, test pins, lane strings, statusline grep contract).
7. **Tests**: `make test` is not data-independent (`tier_tests`, `enrichment_tests` read built parquet); `normalization_regression_checks`/`spine_tests` are pure but not in `test`; no pytest config; zero tests for the company key join / `propagate_to_steps`, name-rule precision (1 negative case for 215 rules), XOT denominators, date parser, SOC pooled-prefix invariant, or frozen golden cache-key hashes.
8. **Dead/stale**: 50 files (6,078 LOC) unreachable from Makefile/scripts/PIPELINE/README; ~2,000 LOC must be **wired** (analyze, seniority, cohorts phases, validate, bias checks, run_industry), ~2,500 archived (June A/B/C benches, SE eval drivers, revealed_seniority_eval), `rebuild_education_person.py` deleted.
9. **Git/config**: `cip_votes.jsonl` (51.8 MB, rewritten by every calibration) and `dlevel_votes.jsonl` are tracked while `soc_votes.jsonl` is ignored; `edu_clean/results/*.{parquet,jsonl}` not gitignored; `education.parquet.bak` (259 MB), `__pycache__`, dangling symlink, empty `.agents/.codex` remain; uv.lock is in sync with pyproject; `numpy` missing from base deps (hence `--with numpy`).
10. **Ordered plan (section E)**: E-1 golden-hash tests -> E-2 move pool -> E-3 claude host -> E-4 fire_llm adapter + pilot on gold -> E-5 fix refresh driver + freshness check -> E-6 tolerate missing jury mappings -> E-7 jury core migration (dlevel -> cip -> soc -> industry with parity checks) -> E-10 `company_clean/` employer layer with a `company_entities.parquet` master table so employer iteration avoids the 75 s career_steps rebuild.

## 0. Verification of yesterday's F1-F9 "LANDED" claims

| Item | Claimed | Verified state | Evidence |
|---|---|---|---|
| F1 git hygiene | landed | Mostly landed, one policy hole. Branches `main`/`recovery-refactor`; 60 commits; pack 25.6 MiB. Vote caches tracked inconsistently: `edu_clean/results/cip_votes.jsonl` (51.8 MB, rewritten by every calibration run, last 2026-09-02 02:23), `dlevel_votes.jsonl` (9.9 MB), `career_clean/results/headless_votes.jsonl` are tracked; `career_clean/results/soc_votes.jsonl` (405 MB) is ignored. `edu_clean/results/cip_candidates.parquet` (15.4 MB) tracked. `share/System-Map.html`, `share/System-Schema.html` still tracked although `/share/*.html` is ignored. | `git ls-files` + `stat`; `.gitignore:46,59`; `git check-ignore` table s6 |
| F2 fresh-rebuild fix | landed (education) | Landed for education, not career. `build_normalized.py:948` LEFT JOINs `mappings/role_soc_jury.parquet` unconditionally; `build_mappings` never creates it (`:228-230` only lists it); with `--skip-mappings` a missing file is a hard `SystemExit` (`:236-243`); without the flag `write_career_steps` fails on the missing parquet. The file comes from `career_clean.run_soc_jury merge`, whose candidates come from `paths/steps.parquet` (`soc_candidates.py:44`), which needs `career_steps` -- a bootstrap cycle (sA.3). | `build_normalized.py:228-243, 948-953`; `soc_candidates.py:44-46` |
| F3 pipeline map + Makefile | landed | Landed but incomplete. 12 targets; none for `paths`, `cohorts`, `transition_network` (build and analyze), `enrichment`, `reference/*`. PIPELINE.md omits three real edges (sA.2). The de-facto downstream driver `scripts/refresh_downstream.sh` has a stage-order bug and skips `analyze.py` (sA.4). | `Makefile:4-5`; `PIPELINE.md:8-24`; `refresh_downstream.sh:31-37` |
| F4 cleanlib | "extracted; migrate incrementally" | Started only: 163 LOC (`text.py` 62 + `headless_claude.py` 88 + `__init__` 13). Not moved: `Result`/`pair_scores`/`reduction` (fn-similarity 0.93/1.00), `approach_b_fuzzy` (0.933), jury driver (cip_llm vs soc_llm 0.818, nine functions >=0.80, four at 1.00), `llm_pool` (still `industry/`, imported by 5 edu/career files + 2 monkeypatch sites). | sB |
| F5 root docs | landed | Landed (3 root .md). Residue: 12 live-doc references and 27 `.py` comments cite bare plan names now under `docs/plans/archive/` (`COVERAGE_PLAN.md` from 11 files). | sF |
| F6 cruft | landed | Partial. Still present: `normalized/education.parquet.bak` (259 MB, 2026-06-10), root `__pycache__/` (+13 more incl. `archive/exploration/__pycache__`), `vault` symlink, empty `.agents/`, `.codex/`, dangling symlink `edu_clean/results/tiebreak_calib.log -> /tmp/claude-1000/.../75f1b68a.../tiebreak_calib.log`, `.claude/settings.local.json` with a one-off PowerShell permission. Gone: `_extracted_pdf.txt`, `llm_proposals.jsonl.bak`, Zone.Identifier. | `ls`, `find`, `ls -L` |
| F7 tests | landed | Partial. `make test` runs in ~5 s wall (log 13:24:21 -> 13:24:26 incl. lint). Two "data-independent" suites read built parquet: `tier_tests` re-derives from `normalized/education.parquet` via `run_tier_counts.compute()` (`tier_tests.py:44-46`); `enrichment_tests` runs `build_enrichment.build()` over `education_person.parquet` + `parsed/*` (`enrichment_tests.py:17`); `dlevel_tests` reads the merged mapping if present. `normalization_regression_checks.py` is pure (only `reference/cip_codes.csv`) yet in `test-data`. `paths/spine_tests` (synthetic), `paths/seniority_tests`, `reference/ipeds_tests` in neither target. No pytest config. | sD |
| F8 ruff | landed | Landed; `make lint` passes. | `pyproject.toml:35-46` |
| F9 cache/results | landed (doc) | Documented. gitignore does not cover `edu_clean/results/*.parquet|*.jsonl`, `career_clean/results/*.jsonl` (except soc_votes), `industry/results/*.jsonl`, `cert_clean/results/`, `cleanlib/cache/`. Downstream writes upstream: `archetypes/assign.py:142` mirrors `role_archetype.parquet` into `normalized/mappings/`. | s6 |

## A. True DAG vs documented DAG

Method: `dag_scan.py` (AST: repo imports, path-shaped literals, read/write call sites) over 150 files; every `common.py` path constant read; reachability (`reach.py`); output mtimes cross-checked with `refresh.log`.

### A.1 The real graph

```
data/*.jsonl -parse_linkedin.py-> parsed/<table>/*.parquet, parsed/_manifest.json
parsed/{education,experience,positions} -{edu,career}_clean.common.export_vocab-> {edu,career}_clean/cache/vocab_*.parquet
   (freshness = mtime vs parsed/_manifest.json; build_normalized reads BOTH module caches via load_vocab)
build_normalized.py
   reads: parsed/*, edu_clean/cache, career_clean/cache, reference/cip_codes.csv,
          mappings/role_soc_jury.parquet [HARD, produced by the SOC jury -- cycle 1]
          mappings/field_cip_jury, field_cip_knn, degree_level_jury [apply_* passes]
          reference/institution_meta + mappings/school_ipeds [apply_institution_meta; soft]
   writes: normalized/{education,education_person,career_steps}.parquet, mappings/*.parquet (10),
          _manifest.json, _cip_pooled_manifest.json, _dlevel_pooled_manifest.json, _institution_meta_manifest.json
cert_clean.run_cert: parsed/certifications -> mappings/cert_domain.parquet, certifications_person.parquet, _cert_manifest.json
   CONSUMERS: none (grep certifications_person|cert_domain outside cert_clean = 0)
industry.build_industry: career_steps -> industry/cache/company_vocab.parquet (744 MB) -> results/company_industry.parquet,
   step_industry.parquet, build_manifest.json; reads industry/llm_proposals.jsonl (LOST)
industry.fire_llm: company_vocab + gold.py/gold_residual.py -> llm_proposals.jsonl (append) | results/gold_worksheet.jsonl
paths.build_spine: career_steps + paths/seniority_scores.parquet [if exists -- cycle 2] -> paths/steps, transitions, _concurrency, _manifest
transition_network.build_network: paths/transitions + reference/onet -> {axis}_edges/nodes.parquet + manifest
transition_network.analyze: {axis}_edges/nodes -> {axis}_nodes_analyzed.parquet, backbone, communities.json, analyze_manifest
paths.seniority: transition_network/role_nodes_analyzed.parquet -> paths/seniority_scores.parquet [cycle 2 closes]
transition_network.sequences/temporal -> trajectory_features.parquet, temporal_occupation_nodes.parquet
cohorts.build_panel: paths/steps, transitions, reference/bls -> cohorts/panel.parquet, profiles.parquet, _panel_manifest
cohorts.typologies: cohorts/panel + transition_network/trajectory_features.parquet (dated 2026-06-04)
career_clean.soc_candidates: paths/steps + career_steps + industry/results/step_industry + industry/taxonomy.json
   -> career_clean/results/soc_{candidates,gold}.parquet -run_soc_jury-> soc_votes.jsonl -merge-> mappings/role_soc_jury.parquet
edu_clean.{cip_candidates,run_cip_jury,run_cip_tiebreak,frontier_merge,knn_tail,run_dlevel_jury,gold_v1}:
   normalized/education.parquet (+ edu_clean/cache/vocab_field, mappings/edu_field) -> edu_clean/results/{cip,dlevel}_votes.jsonl,
   frontier_adjudication.jsonl -> mappings/field_cip_jury.parquet (appended in place by tiebreak/frontier), field_cip_knn, degree_level_jury
archetypes.run_all: role_features reads career_steps + industry/results/step_industry + paths/steps;
   yearwise reads cohorts/panel.parquet + paths/transitions; assign writes archetypes/results/role_archetype.parquet
   AND normalized/mappings/role_archetype.parquet (assign.py:142)
edu_clean.anchors (imported by portal.build:25, archetypes.common:150): reads paths/steps.parquet
portal.run_portal_data: normalized/education + paths/steps,transitions + transition_network/occupation_nodes_analyzed.parquet
   + industry/results/step_industry + industry/taxonomy.json + reference/{soc_status,cip_humanities}
   -> portal/results/portal_data.json, portal/_manifest.json, portal/results/_cache/
portal.run_share_build: portal_data.json + portal/share_template.html -> share/Humanities-Workforce-portal.{html,zip}
enrichment.build_enrichment: education_person + parsed/* -> enrichment/results/enrichment.json
```

### A.2 Undocumented edges

| Edge | Evidence | Why it matters |
|---|---|---|
| archetypes -> `cohorts/panel.parquet`, `paths/steps`, `paths/transitions`, `industry/results/step_industry` | `archetypes/common.py:19-26`; `role_features.py:15-29`; `yearwise.py:30,117` | PIPELINE.md draws archetypes as a sibling of paths/cohorts; it is downstream of both. `refresh_downstream.sh` runs it before them (A.4). |
| portal -> `transition_network/occupation_nodes_analyzed.parquet` (from `analyze.py`, not `build_network`) | `portal/common.py:34`; `analyze.py:140` | `analyze.py` in no Makefile target, not in the refresh driver; the file portal consumed on 2026-09-01 is dated 2026-08-05 12:35 while `occupation_nodes.parquet` is 2026-09-01 21:14. |
| `build_spine` -> `paths/seniority_scores.parquet` <- `paths.seniority` <- `analyze` (role axis) | `build_spine.py:374-376`; `seniority.py:36` | Bootstrap loop documented only in `docs/METHODOLOGY.md s0`; `seniority_scores.parquet` dated 2026-08-05; the 2026-09-01 spine used stale scores (`paths/_manifest.json: has_revealed_scores = true`). |
| `build_normalized` -> `mappings/role_soc_jury.parquet` (hard) | `build_normalized.py:948` | Fresh clone cannot build career_steps. |
| SOC jury -> `paths/steps` + `industry/results/step_industry` | `soc_candidates.py:44-46,131,151` | A cleaning module depends on two analysis layers; the jury's `industry_l1_label` evidence (hence every SOC cache key) is a function of the industry build. Existing votes are keyed on evidence rendered at fire time, so an industry re-fire does not orphan them, but a fresh `extract` would render different evidence for roles whose modal L1 changed -> those strings re-fire. Document, do not "fix". |
| `edu_clean.anchors` -> `paths/steps.parquet` | `edu_clean/anchors.py` | Upstream module reading a downstream output. |
| `archetypes.assign` writes `normalized/mappings/role_archetype.parquet` | `assign.py:142` | Only downstream->upstream write; nothing reads the mirror (grep outside archetypes/archive = 0). Delete. |
| `cert_clean` outputs -> nothing | grep = 0 | R6 built the axis; no consumer. |
| `industry/name_rules.py` -> `career_clean.common.normalize` | `name_rules.py:18` | Should be `cleanlib.normalize` (same object via re-export at `career_clean/common.py:201`). |
| `career_clean/soc_taxonomy.py`, `portal/common.py` -> `transition_network.common.SOC_MAJOR` | `soc_taxonomy.py:15`; `portal/common.py:194,204` | Label space of a calibrated jury (`n_codes` is in the cache key) lives in a downstream analysis module. |
| `edu_clean/run_anchor_eval.py` -> `portal.common` | `run_anchor_eval.py:27` | Reverse dependency in a validation harness. |

### A.3 Cycles

1. career_steps <-> SOC jury (hard): career_steps -> paths/steps -> soc_candidates (also needs step_industry <- career_steps) -> `run_soc_jury merge` -> `role_soc_jury.parquet` -> `write_career_steps` LEFT JOIN (`:948`). Bootstrap order must be career_steps-without-jury -> industry -> paths -> SOC jury -> career_steps; code does not allow the first step. Fix E-6.
2. spine <-> revealed seniority (soft): `build_spine` reads `seniority_scores.parquet` if present (`:374`); the file comes from `paths.seniority` <- `analyze` <- `build_network` <- `paths/transitions` <- `build_spine`. Terminates (conditional read) but the second pass is automated nowhere; spine is one iteration stale.
3. industry <-> career_clean (import-level): `industry.name_rules` imports `career_clean.common`; `career_clean.soc_candidates` reads `industry/results`. No runtime cycle; it is why `cleanlib` must own `normalize`.

### A.4 The downstream refresh driver is wrong (`scripts/refresh_downstream.sh`)

From `refresh.log` stage stamps and output mtimes (2026-09-01):

```
[2/7] archetypes 21:11:51 -> 21:13:34  wrote role_features.parquet 21:12:07, person_year_archetype 21:13:31
[3/7] paths      21:13:34 -> 21:13:55  wrote paths/steps.parquet 21:13:47, transitions 21:13:55   <- archetypes read the OLD ones
[4/7] cohorts    21:13:55 -> 21:14:16  wrote cohorts/panel.parquet 21:14:14                      <- archetypes.yearwise read the OLD panel
[5/7] network    21:14:16 -> 21:14:16  build_network only; occupation_nodes_analyzed.parquet still 2026-08-05 12:35
[6/7] portal     21:14:16 -> 21:15:58  read the 2026-08-05 analyzed nodes
      normalized/education.parquet rewritten 21:27:54 (after the refresh) -> portal_data.json (21:15:58) is stale
```

Defects: (i) archetypes runs before its inputs; (ii) `analyze` and `seniority` never run; (iii) `build_industry --propagate --no-llm` (`:31`) discards the frozen jury cache -- harmless today, fatal the day the industry jury is re-fired; (iv) `.build_status` says "refresh done (7/7)" for a portal that predates its education input. Fix E-5.

### A.5 Module reading another module's `cache/`

None across analysis modules. `build_normalized.py` reads `edu_clean/cache` and `career_clean/cache` vocab via `load_vocab` (by design). `industry/cache/company_vocab.parquet` is read only by `industry/*`. The violation is the reverse direction: `archetypes/assign.py:142` writing into `normalized/mappings/`.

### A.6 Documented but different / missing

- `make industry` runs `build_industry --propagate` (uses cache) while `refresh_downstream.sh` passes `--no-llm`.
- PIPELINE.md jury table: industry row says "see SETUP.md"; SETUP.md describes Anthropic Batch and Ollama pool, neither is the headless-Claude route; `industry/doctor.py:53-67` checks for the `anthropic` SDK and `ant auth`.
- README.md/Makefile call `make test` "data-independent"; two suites read built parquet.
- PIPELINE.md lists `cert` as a stage; nothing consumes its outputs.

## B. Duplication and the cleanlib jury core

### B.1 Measurements (`similarity.py`: difflib ratio on comment-stripped, whitespace-normalized lines; token Jaccard; per-function ratio >=0.80)

| Pair | line-ratio | tok-Jaccard | matched | functions >=0.80 |
|---|---|---|---|---|
| `edu_clean/cip_llm.py` vs `career_clean/soc_llm.py` | 0.818 | 0.722 | 175/213 | cache_key 1.00, append_cache 1.00, build_request 1.00, make_pool 1.00, load_cache 0.95, on_result 0.95, fire 0.93, unanimous_accept 0.89, votes_by_key 0.80 |
| `cip_llm.py` vs `edu_clean/dlevel_jury.py` | 0.442 | 0.344 | 99/215 | append_cache 1.00, make_pool 0.89, unanimous_accept 0.88, load_cache 0.85 |
| `soc_llm.py` vs `dlevel_jury.py` | 0.435 | 0.321 | 97/213 | same four |
| `industry/llm.py` vs `cip_llm.py` / `soc_llm.py` | 0.211 / 0.212 | 0.22 | 54 | append_cache 0.89 (Proposal + cache_key payload same design; rest is the Batch-API path) |
| `industry/local_llm.py` vs `cip_llm.py` | 0.125 | 0.236 | 23/154 | `_fire.on_result` is the same buffer-50 pattern (`local_llm.py:131-147` vs `cip_llm.py:247-266`) |
| `run_cip_jury.py` vs `run_soc_jury.py` | 0.706 | 0.586 | 163/224 | cmd_extract 1.00, cmd_calibrate 0.90, _load_candidates 0.89, main 0.86 |
| `run_cip_jury.py` vs `run_dlevel_jury.py` | 0.209 | 0.294 | 37/116 | compressed rewrite of the same driver |
| `industry/fire_llm.py` vs any driver | <=0.056 | <=0.18 | <=11 | none -- structurally different (modes, cost estimate, two backends) |
| `edu_clean/approach_b_fuzzy.py` vs `career_clean/approach_b_fuzzy.py` | 0.933 | 0.762 | 98/104 | _signature, _tokens_match, run, find, union all 1.00 |
| `approach_c_embed.py` (edu vs career) | 0.543 | 0.500 | 92/140 | _get_model 1.00, run 1.00, find 1.00, union 1.00, embed 0.96 |
| `edu_clean/common.py` vs `career_clean/common.py` | 0.458 | 0.463 | 91/177 | _cache_fresh 1.00, reduction 1.00, pair_scores 0.93 (Result, timer twins by inspection; normalizers differ in SOFT_STOP and must stay separate) |
| `edu_clean/common.py` vs `cleanlib/text.py` | 0.311 | -- | 35/48 | _protect_domain_tokens 1.00 |
| `run_eval.py` (edu vs career) | 0.743 | 0.634 | 81/104 | valid_pairs 1.00, error_pairs 0.95 |
| `cip_taxonomy` / `soc_taxonomy` / `dlevel_taxonomy` | 0.35-0.48 | -- | -- | output_json_schema 1.00 / 0.88 / 0.88 |
| `cip_tests.py` vs `soc_tests.py` | 0.522 | 0.532 | 66/100 | test_build_request_pure 0.87, test_cache_key 0.80 |
| `industry/llm_pool.py` vs `cleanlib/headless_claude.py` | 0.049 | 0.113 | 9 | none -- different layers; `headless_bench.py:105-127` re-implements a mini pool with ThreadPoolExecutor |
| portal `{bias,cip_bias,soc_bias}_check.py` | 0.30-0.44 | -- | -- | same report skeleton, three axes |
| `*_tests.py` boilerplate | <=0.15 | -- | -- | only the 5-line `check()` helper repeats (11 copies) |

### B.2 Jury skeleton, stage by stage (B bespoke, C copy-paste >=0.85, V variant)

| Stage | industry | CIP | SOC | dlevel | tiebreak | headless bench |
|---|---|---|---|---|---|---|
| 1 candidates | B `fire_llm._residual`, `_gold_rows_from_vocab` | B `cip_candidates.build` + anchors | B `soc_candidates.build` + anchors | B inline SQL `dlevel_jury._rows/gold` | V `_targets()` by vote_state | B `load_tail` |
| 2 evidence | B `llm.evidence_text` | B | B | B | reuses CIP | reuses SOC |
| 3 system prompt | B `_SYSTEM` + `T.labelled_catalog` | B | B | B | reuses | V SOC prompt + batch rules |
| 4 taxonomy/schema | B `industry.taxonomy` (4-level) | schema fn C 1.00 with SOC | C | C 0.88 | reuses | V votes-array schema |
| 5 cache key | origin: sha256(json{evidence,model,prompt_version,schema_version,n_codes}) | C | C 1.00 | C | reuses | V adds `"batch"` |
| 6 Proposal + cache I/O | origin `llm.py:125-164` | C `cip_llm.py:112-150` | C 1.00 | C (no torn-line warning) | reuses | V own JSONL schema |
| 7 request body | `local_llm.build_request:71-87` | C `cip_llm.py:183-199` (NUM_CTX 6144 vs 8192) | C 1.00 | C (4096) | reuses | B subprocess |
| 8 host pool + on_result | `llm_pool.HostPool` + `local_llm._fire` and Anthropic Batch `llm.propose` | C `cip_llm.fire:209-273` + `make_pool` env override | C 0.93 | C | monkeypatches `L.make_pool` (`:76-81`) | own ThreadPoolExecutor |
| 9 parse/validate | `llm._parse_result_text` | C inline | C | C | reuses | inline |
| 10 gate | B `jury.aggregate` hierarchical (tau 0.5) + `run_industry` calibration | `unanimous_accept` C 0.89 + `cmd_calibrate` C 0.90 | C | C 0.88 | B `majority_accept` 2-of-3 | inline band |
| 11 merge | B propose-only `llm_*` columns (`build_industry.py:51-95`) | `cmd_merge` COPY -> `field_cip_jury.parquet` + exclusions (V) | V | V (TINYINT) | append UNION ALL + dup assert (`:208-224`) ~ `frontier_merge.py:60-68` | none |

Also: the `make_pool` monkeypatch seam appears twice (`run_cip_tiebreak.py:76-81`, `gold_v1.py:295-303`); HOSTS_ENV lane strings pasted in `cip_llm.py:43-47`, `soc_llm.py:40-44`, `dlevel_jury.py:33-36`, `run_cip_tiebreak.py:56`.

### B.3 Design: `cleanlib/jury/`

```
cleanlib/jury/
  spec.py      JurySpec + cache_key
  cache.py     Proposal, load_cache, append_cache, votes_by_key, VoteBuffer
  request.py   bare_model, build_request
  hosts.py     <- industry/llm_pool.py moved VERBATIM + the claude host type
  fire.py      fire(spec, items, jurors, pool_factory, execute) -> FireStats
  gate.py      unanimous, majority, hierarchical (wraps industry.jury), calibration_report
  merge.py     write_mapping / append_mapping (COPY TEMP TABLE + dup-key assert)
  bench.py     <- industry/bench_hosts.py (optional)
industry/llm_pool.py -> 3-line shim `from cleanlib.jury.hosts import *` (keeps 5 importers + tests working)
```

```python
# spec.py
@dataclass(frozen=True)
class JurySpec:
    name: str                              # "industry" | "cip" | "soc" | "dlevel"
    key_field: str                         # "key" | "field_norm" | "role_canonical" | "key"
    taxonomy: Any                          # protocol: all_codes(), is_valid(code), output_json_schema(), SCHEMA_VERSION, ABSTAIN|None
    prompt_version: int                    # cip 1, soc 2, dlevel 1 (taxonomy); industry 3 (llm.PROMPT_VERSION)
    system_prompt: str                     # the axis's _SYSTEM, unchanged
    evidence_text: Callable[[dict], str]   # the axis's renderer, unchanged
    cache_file: Path
    rationale_max: int | None = 400        # cip/soc/dlevel 400; industry None
    num_ctx: int = 6144                    # cip/soc 6144, dlevel 4096, industry 8192
    think_off_prefixes: tuple[str, ...] = ("qwen3", "bulk-moe", "deepseek-r1")   # industry: ("qwen3","deepseek-r1")
    default_jury: tuple[str, ...] = ()
    hosts_env: str | None = None           # the OLLAMA_HOSTS spec the axis pins

def cache_key(spec, item, model) -> str:   # byte-identical to all four today
    payload = json.dumps({"evidence": spec.evidence_text(item), "model": model,
                          "prompt_version": spec.prompt_version,
                          "schema_version": spec.taxonomy.SCHEMA_VERSION,
                          "n_codes": len(spec.taxonomy.all_codes())}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# cache.py
@dataclass
class Proposal: key: str; code: str; confidence: str; rationale: str; model: str; input_hash: str
    def to_json(self): return json.dumps(self.__dict__, ensure_ascii=False)     # field order preserved
def load_cache(path, *, tag="") -> dict[str, Proposal]    # torn-line tolerant; UNKNOWN KEYS IGNORED (new, additive)
def append_cache(path, proposals) -> None
def votes_by_key(spec, items, jurors, cache=None) -> dict[str, dict[str, str]]
class VoteBuffer: __init__(spec, cache_path, flush_every=50); on_result(meta, resp); close(); parse_failures

# request.py
def bare_model(model) -> str              # "llamacpp/qwen3-4b-q4" -> "qwen3-4b-q4"; "claude/haiku" -> "haiku"
def build_request(spec, item, model, *, schema=None) -> dict   # identical dict to today's three copies

# hosts.py (moved verbatim; NEW marked)
@dataclass class OllamaHost: name; base_url; parallel=1; models=frozenset(); api="ollama"   # api: ollama|llamacpp|claude (NEW)
def hosts_from_env(env=None)             # NEW grammar case "claude=claude|4|claude" (slots = concurrency; url unused)
def _claude_chat(host, body) -> dict:    # NEW: body.messages[0]=system, [1]=user, body["format"]=schema
    r = headless_claude.call(body["model"], system, user, body["format"], thinking_tokens=0)
    return {"message": {"content": json.dumps(r["output"])}, "eval_count": r["usage"]["output"],
            "prompt_eval_count": r["usage"]["input"], "model_snapshot": r["model"],
            "cost_usd": r["cost_usd"], "duration_s": r["duration_s"]}
def _fetch_claude(host)                  # NEW discovery: host.aliases if shutil.which("claude") else None (no network)
class HostPool: unchanged; discover() picks probe by api; _http_chat dispatches api=="claude"

# fire.py
@dataclass class FireStats: items; jurors; pending_units; cached_units; approx_prompt_tokens_per_unit; done; failed; skipped; parse_failures
def fire(spec, items, jurors, *, pool_factory=HostPool, execute=False, progress_every=25) -> FireStats
    # keep today's print formats: "[{name}] firing {n:,} units across [...]" and the pool's "[pool] N done ... left"
    # (.claude/statusline.sh:22-24 greps both)

# gate.py
def unanimous(codes, n_jurors, taxonomy) -> str | None      # today's unanimous_accept with jury size as parameter
def majority(codes, k, taxonomy) -> str | None               # run_cip_tiebreak.majority_accept
def hierarchical(codes: dict[str,str], taxonomy, tau=0.5)    # thin wrapper over industry.jury.aggregate
def calibration_report(spec, items, votes, gold_field, jurors, accept) -> dict

# merge.py
def write_mapping(path, rows, columns, *, order_by) -> int
def append_mapping(path, rows, columns, key_col) -> int      # UNION ALL + count(*)-count(DISTINCT key)==0 assert + tmp/replace
```

Industry adapter after the refactor (`industry/fire_llm.py`, ~60 LOC changed):

```python
SPEC = JurySpec(name="industry", key_field="key", taxonomy=T, prompt_version=llm.PROMPT_VERSION,
                system_prompt=llm._SYSTEM, evidence_text=llm.evidence_text, cache_file=llm.CACHE_FILE,
                rationale_max=None, num_ctx=local_llm.NUM_CTX, think_off_prefixes=local_llm._THINK_OFF_PREFIXES)
_PANELS["claude"] = {"tail": ("claude/haiku",), "jury": ("claude/haiku","claude/sonnet","claude/opus"),
                     "head": ("claude/opus",), "calibrate": ("claude/haiku","claude/sonnet","claude/opus")}
# --backend claude -> pool_factory=lambda: HostPool(hosts_from_env({"OLLAMA_HOSTS": "claude=claude|4|claude"}))
# local_llm.propose_local_panel -> fire(SPEC, items, models, pool_factory=..., execute=True), then group by key
# llm.cached_panel / build_industry unchanged (same cache via cleanlib.jury.cache.load_cache)
```

Cost/throughput from `career_clean/results/headless_bench.json` (SOC evidence, 25 items/call): Haiku $0.00134/str, 1.64 s/str sequential, 0.75 s/str at c=4; Sonnet $0.00223; Opus $0.00528; Haiku-vs-Sonnet band 28-33%; retries ~7%. Industry evidence is larger (8 titles + 3 descriptions <=600 chars, `industry/common.py:33-35`), so budget ~3x until measured: top-5k residual (9.6% of rows) two-voter ~ $50-70; top-25k (16.8%) ~ $250-350 before Opus on the band. Per-unit claude host first (parity-safe); batching is E-9.

Migration order: dlevel (9.9 MB, 79,449 landed rows) -> CIP (51.8 MB, 491,063 rows) -> SOC (405 MB, 299,787 roles) -> industry (empty cache; only key format matters), each with E-7 parity checks.

### B.4 Do-not-touch list

1. Cache-key payload and hashing for all four axes; values today: CIP `PROMPT_VERSION=1/SCHEMA_VERSION=1` (`cip_taxonomy.py:37-38`), SOC `2/1` (`soc_taxonomy.py:21,25`), dlevel `1/1`, industry `PROMPT_VERSION=3` (`llm.py:45`) + `SCHEMA_VERSION=1` (`taxonomy.py:34`); `n_codes = len(all_codes())`.
2. `evidence_text` bodies for all axes (inside the hash; industry's also keeps `curated_promoted` provenance interpretable and `gold_residual` keys matching).
3. `_SYSTEM` prompts verbatim (edits require a `PROMPT_VERSION` bump).
4. Proposal JSONL line format: six fields in order `key, code, confidence, rationale, model, input_hash`, `ensure_ascii=False`, append-only, last-write-wins by `input_hash`. Tolerant loader is additive only.
5. Landed mapping parquets and schemas: `field_cip_jury` (`field_norm, cip2, method, n_jurors, unanimous`; methods `llm_jury_v1`, `llm_jury_v1_tb`, `frontier_v1`), `field_cip_knn`, `role_soc_jury` (`role_canonical, soc_major, method, n_jurors, unanimous`), `degree_level_jury` (`key, degree_level_jury TINYINT, method`).
6. Merge exclusions and gates: `NON_FIELD_LITERALS` + `_NUMERIC` (`run_cip_jury.py:47-81`), `EMPLOYMENT_FORMS` + `_non_occupation` (`run_soc_jury.py:45-61`), mixed-population exclusion (`run_cip_jury.py:230-237`, `run_soc_jury.py:204-211`), unanimous bar 0.85, tiebreak 2-of-3.
7. `apply_cip_pooled` fingerprint asserts (`:215-259`) and `run_tier_counts` `content_hash` / `tier_counts.json`.
8. `industry/curated_promoted.PROMOTED` (1,982 ids, generated 2026-07-07 under the Opus + >=1 juror unanimous-L1 gate): never regenerate from a different-panel cache without re-gating on `gold_residual` through `run_industry`.
9. `industry/common.export_company_vocab` SQL incl. ORDER BY tiebreaks (`common.py:86-89`).
10. `industry/tests.py` pins: `LOCAL_JURY` (`:227`), `LOCAL_HEAD` (`:229`), default hosts (`:294`), torn-line/determinism checks; a `claude` host must not change `hosts_from_env({})`.
11. HOSTS_ENV lane strings (ports 8090/8091/8092, slots) -- move into `JurySpec.hosts_env`, values unchanged.
12. `.claude/statusline.sh` grep contract: `firing N units`, `[pool] N done ... left`, `PHASE DONE` / `merged ->` / `"gate"`.

## C. Dead / stale code

Reachability (`reach.py`): strict roots = `python -m X`/`python X.py` in Makefile, `scripts/*.sh`, `industry/*.sh`, PIPELINE.md, README.md -> 100/150 reachable, 50 unreachable (6,078 LOC). Loose (+ every .md) -> 123/150, 27 unreachable (2,513 LOC).

| File | LOC | Reachable via | Recommendation |
|---|---|---|---|
| `transition_network/analyze.py` | 203 | docs only | Wire into `make network` (portal reads its output). |
| `paths/seniority.py` | 108 | docs only | Wire (`make seniority`, second spine pass). |
| `transition_network/sequences.py`, `temporal.py` | 250, 190 | docs only | Wire into `make network` (cohorts.typologies reads trajectory_features) or archive with typologies. |
| `transition_network/revealed_seniority_eval.py` | 413 | docs only | Archive with `REVEALED_SENIORITY_COMPARISON.md`. |
| `cohorts/{generational,profiles,scarring,survival,typologies}.py` | 672 | cohorts/README | Wire into `make cohorts`. |
| `archetypes/validate.py` | 192 | none | Wire as `make archetypes-validate`. |
| `portal/{bias,soc_bias,cip_bias}_check.py` | 351 | FINDINGS only | Wire as `make portal-checks` (pooled-axis bias audits; re-run after any jury merge). |
| `industry/run_industry.py` | 264 | docs + run_panels.sh | Wire as `make industry-eval` (calibration gate for E-4). |
| `industry/doctor.py` | 189 | SETUP.md | Keep; rewrite for the claude host (`:53-67` checks anthropic SDK / ant auth). |
| `industry/bench_hosts.py` | 137 | METHODS.md | Move with the pool to `cleanlib/jury/bench.py` or archive. |
| `industry/run_panels.sh` | 39 | none | Archive (Ollama panel; lost cache). |
| `industry/run_tail.sh` | 48 | METHODS.md | Keep; update for `--backend claude` (resumable big-run driver). |
| `industry/{jury,classify,gold,gold_residual,local_llm}.py` | 112,145,88,124,203 | imported | Live; `local_llm.py` shrinks to constants + adapter after B.3. |
| `career_clean/headless_bench.py` | 230 | none | Keep until the claude host lands, then archive. |
| `career_clean/run_occupation_proposals.py` | 174 | none | Keep (R5 open; produced `career_occupation_proposals.parquet`, no consumers). |
| `career_clean/run_self_employed.py`, `run_se_description.py` | 108, 133 | none | Archive (eval drivers; `se_*` stay live via `final_hybrid`). |
| `career_clean/run_eval.py`, `run_final_compare.py`, `run_occupation.py`, `approach_c_embed.py`, `gold.py` | 134,146,79,230,114 | docs | Archive as `archive/bench_2026_06/career/` (approach_a/b stay: `final_hybrid` imports them). |
| `edu_clean/run_eval.py`, `run_hybrid.py`, `hybrid.py`, `run_final_compare.py`, `run_gold.py`, `approach_c_embed.py`, `probe_pairs.py`, `gold.py` | 123,54,149,195,138,166,100,230 | docs/none | Archive as `archive/bench_2026_06/edu/`. Except `encoder_bench.py` (280): `nearest_neighbor.py:26` imports `encode` from it (needed by knn_tail/gold_v1) -> move `encode` into `nearest_neighbor.py` first. |
| `edu_clean/rebuild_education_person.py` | 29 | none | Delete (superseded by F2). |
| `edu_clean/degree_level_rescue.py` | 179 | none; no consumer of its JSON | Archive (superseded by dlevel jury; confirm with owner). |
| `edu_clean/run_anchor_eval.py` | 333 | none | Keep as validation harness; wire into `test-data` (portal cites its JSON only in comments). |
| `edu_clean/tiebreak_lab.py` | 182 | docs | Keep until R3 closed. |
| `paths/tune_thresholds.py` | 84 | comment only | Archive. |
| `paths/spine_tests.py`, `paths/seniority_tests.py`, `reference/ipeds_tests.py` | 118, 95, 54 | docs | Wire into `make test` (spine_tests is synthetic) / `test-data`. |
| `normalization_regression_checks.py` | 445 | test-data | Move to `make test` (pure). |
| `archive/` (16 files) | ~1.9k | none | Fine; delete `archive/exploration/__pycache__`. |
| `industry/curated_promoted.py` | 2,002 | curated.py | Data table (1,982 entries); keep. |

## D. Tests

### D.1 Inventory

| Suite | LOC | style | `test_*` fns | reads built data | target | wall |
|---|---|---|---|---|---|---|
| `edu_clean/humanities_tests` | 161 | `__main__` + `check()` | 0 | no | test | <1 s |
| `edu_clean/tier_tests` | 119 | `__main__` | 0 | yes (education.parquet) | test | ~1 s |
| `edu_clean/dlevel_tests` | 55 | `__main__` | 0 | if built | test | <1 s |
| `career_clean/se_tests` | 202 | `__main__` | 0 | no | test | <1 s |
| `industry/tests` | 475 | `__main__` (relative imports) | 11 | no (fake transport) | test | ~2 s |
| `archetypes/archetype_tests` | 126 | `__main__` (relative) | 0 | no | test | <1 s |
| `enrichment/enrichment_tests` | 34 | `__main__` | 0 | yes (education_person + parsed) | test | ~1 s |
| `cert_clean/cert_tests` | 68 | `__main__` | 4 | no | test | <1 s |
| `edu_clean/cip_tests` | 183 | `__main__` | 9 | guarded `exists()` | test-data | -- |
| `career_clean/soc_tests` | 124 | `__main__` | 6 | guarded | test-data | -- |
| `portal/portal_tests` | 515 | `__main__` | 0 | yes | test-data | minutes |
| `cohorts/cohort_tests` | 75 | `__main__` | 0 | yes | test-data | -- |
| `normalization_regression_checks` | 445 | `__main__` | 0 | no | test-data | -- |
| `paths/spine_tests` | 118 | `__main__` | 0 | no (synthetic) | none | -- |
| `paths/seniority_tests` | 95 | `__main__` | 0 | yes | none | -- |
| `reference/ipeds_tests` | 54 | `__main__` | 0 | yes | none | -- |

`make test` whole run: 5 s wall. No pytest config/conftest. As-is, 0 files match `test_*.py`; with `python_files = ["*_tests.py","tests.py"]` four files yield collected functions (industry 11, cip 9, soc 6, cert 4); the other 12 need a `def test_suite(): main()` shim. Relative imports are fine under pytest (all packages have `__init__.py`).

### D.2 Gaps on the employer/industry path

| Gap | Exists | Evidence | Proposed test |
|---|---|---|---|
| Company key join `career_steps.company_canonical_id` <-> `company_industry.key`; `propagate_to_steps` | nothing | `build_industry.py:119-173` untested; only `classify_row` checks (`tests.py:88-103`) | Synthetic `career_steps` (id:/raw:/nonorg: rows, one company missing) -> `propagate_to_steps` on a temp dir: one output row per input, nonorg rows get prior, missing company -> XOT/unresolved, `L1_coverage_pct` arithmetic. |
| Name-rule precision fixtures | 1 positive + 1 generic-word negative | `tests.py:72-78`; 215 rules (`name_rules.py:27-260`) | >=3 positives + >=3 negatives per L1 incl. household names that must not fire (Netflix, Uber, 3M, MetLife, Siemens are `unresolved` today); whole-token match assert. |
| Propagation invariants | none | -- | `step_industry` rows == `career_steps` rows; `l1 = truncate(industry_code,1)`; depth consistent with l2..l4; `needs_review` semantics. |
| XOT in portal denominators | `analyses.py:308-338` computes `industry_unresolved_share`; `launchboard.py:264` excludes XOT | `portal_tests.py:84-90` only MIN_SUPPORT | Synthetic substrate with 50% XOT: sector shares sum to 1 over resolved, unresolved_share == 0.5, top-N "Other" fold. |
| Date parser | none | `build_normalized.py:790-801`, `:918-923` | DuckDB fixture test: `Jan 2019`, `2019`, `Present`, `jan 2019`, `Sept 2020`, `2019 - 2021`, NULL -> (year, month, is_current). |
| SOC pooled prefix invariant | none (grep = 0) | `build_normalized.py:894-904` | `occupation_source='det'` => `occupation_major_pooled = substr(occupation_code,1,2)`; `'jury'` => `occupation_code IS NULL`; `role_soc_jury.role_canonical` unique. |
| Frozen cache-key golden values | determinism + sensitivity only | `industry/tests.py:136-142`; cip/soc `test_cache_key` | Golden sha256 constants per axis (compute before any refactor). |
| Proposal loader tolerance | none | `Proposal(**json.loads(line))` -> `TypeError` on extra keys -> counted malformed (`llm.py:150-154`, `cip_llm.py:135-139`) | Extra `model_snapshot` field loads. |
| HostPool | 20+ checks, fake transport | `industry/tests.py:278-448` (171 LOC) | Keep; add claude-host tests with a fake `headless_claude.call`. |
| `make test` labeling | -- | F7 | Move `tier_tests`, `enrichment_tests` -> test-data; `normalization_regression_checks`, `spine_tests`, `cip_tests`, `soc_tests` -> test. |

## E. Ordered refactor plan

| # | What | Unblocks | Size | Risk | Verification |
|---|---|---|---|---|---|
| E-1 | Golden-hash tests: pin `cache_key` for one fixture item per axis + Proposal line format; tolerant-loader test. | Every later jury change; protects 466 MB of live votes. | S (~70 LOC) | none | `make test` green; constants committed. |
| E-2 | Move `industry/llm_pool.py` -> `cleanlib/jury/hosts.py` verbatim; 3-line re-export shim; move pool tests (`industry/tests.py:278-448`) to `cleanlib/jury_tests.py`, call from `industry.tests`. | Claude host (E-3); ends five cross-module imports. | S (342 moved, +10) | low | `make test`; `python -c "import industry.llm_pool as p; assert p.HostPool"`. |
| E-3 | `api="claude"` host: `_claude_chat` transport over `cleanlib.headless_claude.call`, binary-presence discovery, `hosts_from_env` grammar `claude=claude\|4\|claude`, `bare_model("claude/haiku")`; carry `model_snapshot`, `cost_usd`, `duration_s` on the response. | Industry re-fire on the subscription login through the calibrated retry/mark-down/requeue scheduler. | S/M (~90 + 40 tests) | medium (spend): dry-run must print measured $/item; pool caps waste at 3 calls/item. | Fake-call tests; then `fire_llm calibrate --backend claude --limit 30 --execute` (~$0.40) and `run_industry` bands vs `gold_residual`. |
| E-4 | `fire_llm` adapter: `--backend claude`, `_PANELS["claude"]`, tolerant loader, claude cost estimate from bench numbers, `propose_local_panel` through the pool with `pool_factory`. | The recovery: calibrate on gold -> `tail --limit 25000` (16.8% of rows) -> `build_industry --propagate` -> L1 from 53.6% toward ~70%; `jury` on top-5k head (9.6%) for consensus-gated curated growth. | S (~60) | medium (spend); `--limit`, dry-run default. | `build_manifest.json` `llm_candidates` > 0; `llm_disagrees_with_deterministic_L1` reviewed; `run_industry` bands; XOT share drops. |
| E-5 | Fix `refresh_downstream.sh`: industry -> paths -> network (build + analyze) -> seniority -> optional second spine -> cohorts -> archetypes -> portal -> share; remove `--no-llm` (env flag); add `scripts/check_freshness.py` (every manifest's inputs older than outputs); `make refresh`. | Re-fired votes reaching step_industry -> archetypes -> portal; stops stale archetypes inputs (sA.4). | S (~40 sh + ~60 py) | low | mtimes monotone per stage; `check_freshness` exit 0. |
| E-6 | `write_career_steps`: tolerate missing `role_soc_jury.parquet` (empty `(role_canonical, soc_major)` relation + warning; `--skip-mappings` not requiring it); same guard for `field_cip_jury`/`field_cip_knn`/`degree_level_jury` in apply passes. | Fresh-clone rebuild; employer-side career_steps rebuilds before the SOC jury; breaks cycle 1. | S (~25) | low | Unit test on a temp dir lacking the file; `--sections career --skip-mappings` on a scratch `--out`. |
| E-7 | `cleanlib/jury/{spec,cache,request,fire,gate,merge}.py` per B.3; migrate dlevel -> CIP -> SOC -> industry; per-axis `*_llm.py` keeps only `_SYSTEM`, `evidence_text`, `JURY`, `HOSTS_ENV`, `SPEC`; replace both `make_pool` monkeypatches with `pool_factory`. | One rail for every jury incl. open R5 and the industry `head` curator; claude host available to CIP/SOC tiebreaks. | M (+450 / -650) | medium; mitigated by E-1 + parity | Per axis: golden hash equal; `votes_by_key` resolves identical key count on the real cache; re-run `merge` to scratch and `EXCEPT` both ways = 0; `make test`. |
| E-8 | Move `SOC_MAJOR` to `cleanlib/taxonomies/soc.py` (re-export from `transition_network.common`); `name_rules` imports `cleanlib.normalize`. | Removes layering inversions; `n_codes` unchanged (23+1). | S | low | E-1 tests. |
| E-9 | Batched claude units (`OllamaHost.batch`, `take_many`, list transport; votes-array schema from `headless_bench.schema`). | Throughput/cost at 200k+ companies (28.4% of rows); measured 25 items/call -> 1.6 s/str. | M (~80 + tests) | medium (item<->vote alignment; keep the `i` index check from `headless_bench.py:83-86`) | Fake transport with mis-ordered/missing votes; per-item cache keys unchanged. |
| E-10 | `company_clean/` (mirror of `cert_clean/`): extract placeholder buckets + `ENTITY_ALIASES` + `canonical_company_id` + name->id crosswalk (`career_clean/approach_a_rules.py:27-100,247-290`), `canon_company_value`/`canon_company` (`final_hybrid.py:97-150`), `_write_company_aliases` (`build_normalized.py:190-198`); outputs `normalized/mappings/career_company.parquet` (unchanged) plus a new `normalized/company_entities.parquet` (canonical_id, display, company_id, aliases, freq, n_persons, titles, descriptions) built from `career_clean/cache/vocab_company.parquet` + parsed/, replacing `industry.common.export_company_vocab`'s 744 MB scan of the 1.9 GB career_steps. | Employer loop (alias/ID recovery for MetLife/Siemens/Netflix/Uber/3M, curated-head growth, re-classification) iterates in seconds-minutes on the mapping, not a 75 s career_steps rewrite; `write_career_steps` re-runs only when the mapping changes. | L (~500 moved, ~150 new) | medium (mapping parity) | `career_company.parquet` old vs new `EXCEPT` = 0; `company_vocab` evidence text byte-identical on a 10k sample; `industry.tests`. |
| E-11 | D.2 tests (name-rule fixtures, propagation, XOT, dates, SOC prefix). | Confidence for every employer change. | M (~250) | none | `make test` / `test-data`. |
| E-12 | `cleanlib/manifest.py` (`generated` ISO, `runtime_s`, `inputs{path: mtime}`, `outputs`, counts) in every builder; today `normalized/_manifest.json` uses `created_at_epoch_s`, `industry/results/build_manifest.json`, `paths/_manifest.json`, `cohorts/_panel_manifest.json` have no date, archetypes `elapsed_s`, portal `runtime_s`. | The freshness check; knowing whether the portal reflects the re-fired industry. | S (~60 + 8 one-liners) | low | `check_freshness` covers all 11 manifests. |
| E-13 | Pytest ini (`python_files=["*_tests.py","tests.py"]`), `test_suite()` shims, relabel targets per D.1, add spine/ipeds/seniority tests. | Faster iteration on E-10/E-11. | S | none | `pytest -q` collects all 16. |
| E-14 | Untrack `cip_votes.jsonl`, `dlevel_votes.jsonl`, `headless_votes.jsonl`, `headless_bench_calls.jsonl`, `cip_candidates.parquet`, `share/System-*.html`; ignore `edu_clean/results/*.{parquet,jsonl}`, `career_clean/results/*.jsonl`, `industry/results/*.jsonl` (keep `gold_worksheet.jsonl` explicitly), `cert_clean/results/*.parquet`, `cleanlib/cache/`; document the out-of-band backup. | Stops 50 MB commits per calibration run. | S | low | `git status` clean after a `gold_v1 calibrate`. |
| E-15 | Dead code per sC (wire 8 files; archive ~2,500 LOC; delete `rebuild_education_person.py`, the `role_archetype` mirror write, `education.parquet.bak`, `__pycache__`, dangling symlink, empty `.agents/.codex`, PowerShell permission). | Navigability; Makefile becomes the complete DAG. | S/M | low | `reach.py --strict` unreachable shrinks to `__init__` + benches. |
| E-16 | Doc rot per sF. | -- | S/M | none | -- |

Not recommended: unifying `edu_clean.common.normalize` with `cleanlib.text.normalize` (different `SOFT_STOP`; every education mapping key depends on it); merging the two `approach_b_fuzzy.py` before E-10 (both live in `final_hybrid`; do it inside E-10 under the `EXCEPT` parity check); rewriting `industry/jury.py` (pure, tested).

## F. Doc rot

| Doc | Date | State | Recommend |
|---|---|---|---|
| `industry/README.md` | 06-10 | "Measured results" L1 42.0% (`:159-161`); manifest says 53.6% after the 07-07 promotion. LLM section = Anthropic Batch + frozen `llm_proposals.jsonl` (gone). Run commands valid. | Rewrite LLM + results sections after E-4. |
| `industry/SETUP.md` | 09-01 | Auth = `ant auth`/API key (`:48-56`); Ollama pool current; no headless-Claude route; says the cache exists (`:23,31,146`). | Rewrite s3 after E-3/E-4. |
| `industry/METHODS.md` | 06-23 | 639 lines incl. the 6.2-day run outcome (99.82% residual classified, `:563-590`) whose votes are gone; agreement-band calibration (0.977/0.967) is the only record. | Keep as historical; add a dated banner: cache lost 2026-09-01; surviving artifacts `curated_promoted.py` (1,982 ids), `industry_eval.json` (07-07). |
| `industry/LLM_JUDGE_JURY_REPORT.md` | 06-09 | Design rationale for `jury.py`. | Move to `docs/notes/`. |
| `industry/LABELING_PROMPT.md` | 06-08 | Agent hand-labeling prompt with the 162-node catalog pasted (`:122-292`, duplicates `taxonomy.json`); superseded by the headless-Claude code path. | Archive; regenerate the catalog from `taxonomy.labelled_catalog()` if needed. |
| `docs/superpowers/plans/2026-06-10-llm-host-pool.md` (948 lines), `specs/2026-06-10-llm-host-pool-design.md` | 06-10 | Executed plan/spec for `llm_pool.py`. | Archive under `docs/plans/archive/`; update module path after E-2. |
| `docs/superpowers/specs/2026-08-03-atlas-education-provenance-design.md` | 08-03 | References `prototype/atlas.html` (now `archive/atlas-prototype.html`). | Archive. |
| `docs/METHODOLOGY.md` | 06-04 | Line refs stale (`build_normalized.py:261-405` -> `write_career_steps` is `:804-965`); predates pooled columns, parsed dates, cert axis, SOC jury; the only place the seniority bootstrap loop is written (s0). | Rewrite Stage 2; lift the loop into PIPELINE.md. |
| `PIPELINE.md` | 09-01 | Missing analyze/seniority loop, archetypes' real inputs, cert consumer (none), `make test` label, headless backend row, refresh driver. | Update with sA. |
| `README.md` | 09-01 | "`make test` -- data-independent suites" false. | One-line fix. |
| `career_clean/PLAN.md`, `SELF_EMPLOYED_PLAN.md` | 06-02/04 | Completed plans in a module dir. | Move to `docs/plans/archive/`. |
| `edu_clean/FINDINGS.md` (07-07), `career_clean/FINDINGS.md` (06-03), `portal/FINDINGS.md` (07-15), `archetypes/FINDINGS.md` (07-16) | -- | Dated findings logs; `tier_tests` lints `edu_clean/*.md`. | Keep. |
| `edu_clean/HUMANITIES_CLASSIFICATION.md` | 07-21 | Spec of `humanities.py`. | Keep. |
| `transition_network/README.md`, `paths/README.md`, `cohorts/README.md` | 06-04 | Commands exist; none say their outputs feed portal/archetypes or the loop. | Keep; add "consumed by" lines. |
| `transition_network/REVEALED_SENIORITY_COMPARISON.md` | 06-04 | Eval report for `revealed_seniority_eval.py`. | Archive with the script. |
| `docs/plans/archive/*` (12) | 06-07 | Fine; 12 live-doc refs + 27 `.py` comments cite bare names (`COVERAGE_PLAN.md` x11, `ARCHETYPES_PLAN.md` x8). | Fix doc refs; leave code comments. |
| `docs/methods/cip-precision-gold-v1.md` | 09-02 | Current. | Keep. |
| `FOUNDATION.md`, `docs/MESSAGES.md`, `docs/NARRATIVE_FRAMING_PLAN.md`, `docs/notes/*`, `docs/design/*` | 08 | Product/analysis docs. | Out of scope; keep. |

## 6. Config / tooling

- pyproject vs uv.lock: no drift. `uv.lock` (2026-06-08) carries all five groups (`dev` empty, `embed`, `graph`, `cohort`, `llm`) with the same specifiers; the only Sep-1 pyproject change was `[tool.ruff]`. `uv sync` without `--group` installs base + empty `dev`; hence `--with numpy` in the Makefile for the DuckDB UDF (`build_normalized.py:811-822`). Recommend adding `numpy>=1.26` to base deps. `refresh_downstream.sh` runs every stage under `--group embed --group graph --group cohort` (torch etc.) even when unneeded.
- ruff: `select = E4,E7,E9,F,W6`, ignore `E702,E741`, excludes `archive`, `.venv`; passes.
- `.gitignore` (`git check-ignore`): ignored -- every `cache/`, `portal/results/_cache`, `archetypes/results`, `enrichment/results/*.parquet`, `career_clean/results/*.parquet`, `industry/results/*.parquet`, `normalized/**.parquet`, `paths|transition_network|cohorts/*.parquet`, `share/*.{html,zip}`, `portal_data.json`, `*.log`. Not ignored -- `edu_clean/results/*.{parquet,jsonl}`, `career_clean/results/*.jsonl` (except `soc_votes.jsonl`), `industry/results/*.jsonl`, `cert_clean/results/`, `cleanlib/cache/`. Largest tracked blobs: `cip_votes.jsonl` 51.8 MB, `cip_candidates.parquet` 15.4 MB, `dlevel_votes.jsonl` 9.9 MB.
- `.claude`: `settings.json` enables the superpowers plugin + statusline; `statusline.sh` parses `edu_clean/results/{tail_tranche2,mistral_calib,tiebreak_fire,tiebreak_calib}.log` for `firing N units` / `[pool] N done` (B.4-12); `settings.local.json` holds one obsolete PowerShell permission; `.agents/`, `.codex/` are empty June dirs.
- `scripts/refresh_downstream.sh`: sA.4. `scripts/overnight_followups.sh` is a dated one-off (R4/R3) -> archive.

## Appendix -- scripts used (`scratchpad/refactor/`)

- `dag_scan.py` -> `dag.json`, `dag_summary.txt`: AST scan of 150 files (repo imports, path literals, read/write call sites, cross-dir strings).
- `reach.py` -> `reach_strict.txt`, `reach_loose.txt`: import-graph reachability from documented entry points.
- `similarity.py` -> `similarity.txt`: difflib line-ratio, token Jaccard, matched-line counts, per-function >=0.80 pairs, 17 groups.
- `invocations.txt`: every `python -m X` / `python X.py` mention in .md/.sh/.py with counts.
- `git_dates.tsv`, `mtimes.txt`: last-commit date/count per file (28 of 60 commits are 2026-06-10, 16 are 2026-09-01), mtimes by day.
- Ad hoc: `git check-ignore` table, `stat` mtimes vs `refresh.log`, DuckDB counts over `company_industry.parquet` / `company_vocab.parquet`, key dumps of 11 manifests.
