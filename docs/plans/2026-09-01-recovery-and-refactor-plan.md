# Recovery & Refactor Plan — combined audit, for an implementing agent

**Date:** 2026-09-01.
**Provenance:** every number below was measured fresh this session directly against
`data/*.jsonl` (96k-record random census), `parsed/`, and `normalized/` — none of it
is inherited from RAW_DATA_AUDIT.md or the docs/audits/ files (deliberately not
consulted). Where a claim says "verify", re-measure before acting.
**Scope:** (1) recover more usable data from the raw files; (2) de-cruft the repo so
humans and agents can navigate it; (3) use the local hardware where it actually pays.

Hardware tags used below (see Part 3 for the full playbook):
- `[no-LLM]` — pure SQL/Python, no model needed. Do these first; they are the cheapest wins.
- `[fast-lane]` — local RTX 5080 (WSL2), small model (qwen3:8b via local-llm MCP, or llama-server lane).
- `[deep-lane]` — fedora = Framework Desktop, AMD Strix Halo, 128 GB unified RAM
  (`100.73.40.75:11434`, Ollama 0.33.0 as of 2026-09-01, with gemma4:31b,
  qwen3.6:35b, qwen3.8-27B, qwen3:32b, deepseek-r1:70b, mistral-medium-3.5:128b,
  gpt-oss-agent, qwen3-coder-next; always set `options.num_ctx`, default is 2048).
- `[pool-bulk]` — both machines via `industry/llm_pool.py` llama-server lanes
  (continuous batching; ~200 tok/s aggregate on the 5080 MoE lane). Lanes are currently
  DOWN (watchdogs don't survive reboots) — relaunch `serve-local*.sh` / fedora
  `serve-4b.sh`/`serve-bulk.sh` first; slot ctx must be ≥6144 (see memory: llm-serving-stack).
- `[gpu-embed]` — sentence-transformers on the 5080 (`uv sync --group embed`).

---

## Part 0 — Baseline (measured 2026-09-01)

Raw: 8 JSONL files, 25 GB, 2,000,000 profiles, 0 JSON parse errors.
Parse fidelity is **clean**: a 96k-record random key census shows `parse_linkedin.py`
captures every top-level and nested key that occurs. **The raw snapshot has NO skills
section** — "skills" can only ever be derived (Part 1, R6).

| Axis | Row coverage | Person coverage |
|---|---|---|
| Education rows | 3,577,659 rows | 1,999,974 persons |
| Field of study (CIP, pooled) | 68.9% | 86.95% |
| Degree level (pooled) | 81.9% | 94.07% |
| Institution slug | 88.1% | 94.07% |
| Institution IPEDS meta | — | 67.3% |
| Education end_year | 21.6% | 20.4% any year; 14.0% bachelor year |
| Career steps | 10,800,787 rows | 1,999,974 persons |
| Company canonical | 99.98% (71% by LinkedIn id) | — |
| Role canonical | 98.5% | — |
| Archetype (substantive) | 86.8% | — |
| SOC occupation | **21.5%** | — |

Known-good context: grouped-position data model handled correctly; year-slip constants
corrected 2026-08-05 (`paths/common.py:LAST_COMPLETE_YEAR=2025` is deliberate: last
*fully observed* graduation year for the 2026-02-19 snapshot).

Education **years are a raw-data wall, not a pipeline defect** (verified in raw bytes:
only 25.6%/21.6% of raw education entries carry start/end year). Any fix is downstream
inference (first-job-start proxy), a modeling decision — do not look for a parser bug.

---

## Part 1 — Data recovery tasks (ordered by recovered-rows per unit effort)

### R1. Land the SOC jury into career_steps `[no-LLM]` — the single biggest win
`normalized/mappings/role_soc_jury.parquet` holds 299,787 **unanimous** role_canonical
→ SOC-major votes. It is used only inside archetypes triangulation; it was never landed
on `career_steps`. Of the 8,483,362 rows with `occupation_code IS NULL`, the jury
already covers **4,328,321** (join on `role_canonical`).
- Implement exactly like education's pooled pattern: append propose-only columns
  `occupation_major_pooled`, `occupation_source` ('det' = prefix of the deterministic
  6-digit code, 'jury'), leave deterministic columns byte-identical (fingerprint assert,
  mirror `edu_clean/apply_cip_pooled.py`).
- Acceptance: SOC-major row coverage 21.5% → ~61.5%; deterministic fingerprint unchanged;
  archetypes still build (they compute their own triangulation — do not change it in this task).

### R2. Professional-degree → CIP inference `[no-LLM]`
`degree_type` already encodes the subject for professional degrees
(`business_admin`, `law`, `medicine`, `education`, `social_work`, `public_health`,
`nursing`, `fine_arts`, `engineering`, `dental`, `public_admin`, `commerce`,
`computer_science`, `applied_science`†). Rows with such a type and no `cip2_pooled`:
**119,172**; persons gaining their FIRST CIP: **32,356** (+1.6pp person coverage).
- Emit as a new `cip_source='degree_type'` tier in the pooled pass, confidence ~0.9.
- **Traps (verified):** `degree_type='philosophy'` is PhD (44k rows) — NEVER a field
  signal. `arts`/`science`/`generic` (BA/BS) carry no field. †`applied_science` (BASc)
  is borderline — decide explicitly, default exclude.
- Type→CIP2 map (~15 entries): business_admin→52, law→22, medicine→51 (51.12),
  education→13, social_work→44 (44.07), public_health→51.22, nursing→51.38,
  fine_arts→50, engineering→14, dental→51.04 (60.01 acceptable at 2-digit: 51),
  public_admin→44, commerce→52, computer_science→11.
- Acceptance: person cip2_pooled 86.95% → ≈88.6%; no change to rows that already had CIP.

### R3. CIP jury: tiebreak the disagreements `[deep-lane]`
> **OUTCOME (2026-09-01): attempted, measured, REJECTED at calibration.** The
> driver (`edu_clean/run_cip_tiebreak.py`) fired gemma3:27b on the 600-string
> gold sample: solo accuracy 0.768; on the 60 gold disagree/partial strings the
> 2-of-3 rule resolved 38 at **0.553 accuracy** — far under the pre-committed
> 0.85 bar. The disagreement band is genuinely ambiguous, not a juror-family
> artifact. NOT merged. Votes are cached (`results/cip_votes.jsonl`), stats in
> `results/cip_tiebreak_stats.json`; a retry needs a materially stronger juror
> (mistral-medium-3.5:128b or gpt-oss:120b overnight) re-calibrated on the same
> gold sample, or these rows stay honestly uncoded.
> Retry attempt (later 2026-09-01): mistral-medium-3.5:128b via Ollama failed
> OPERATIONALLY -- 469/600 requests timed out (llm_pool's timeout is too short
> for a ~5-8 tok/s 128B model) and all 131 completed generations failed JSON
> validation (schema/format handling differs on this model). Zero votes
> recorded; gate untouched. A retry needs a llama-server lane for the big
> juror, or per-model timeout + format handling in llm_pool.
> **RESOLUTION (2026-09-01, evening): the band was adjudicated by the frontier
> session itself, not a local juror.** Diagnosis first: an oracle bound showed a
> *perfect* tiebreaker could reach only 0.86 on the disagreement band (gold is one
> of the two votes in 37/43 cases) and 0.53 on the partial-abstain band, and every
> zero-LLM rule (confidence, anchors) scored 0.35-0.60 -- the band is genuinely
> multi-family, so the 0.85 gate was unattainable by construction. Fable 5.1
> labeled the 60-string gold band blind at 0.81 CIP2 / 0.91 humanities-level
> accuracy (0.85 on clean disagree strings = the ceiling), then adjudicated all
> 4,961 target strings (first-listed field rule for compounds; HS-diploma rows ->
> 53; placeholders -> XUN). Landed via `edu_clean/frontier_merge.py` as
> method `frontier_v1`. See `results/frontier_adjudication.jsonl`.
> **Bonus (R4 replacement): `edu_clean/knn_tail.py`** -- an embedding-kNN
> classifier seeded by every labeled string. Its deterministic `head_exact`
> path (compound string whose first component is itself a labeled string) was
> judged 60/60 strict and is landed as `cip_source='knn_head'`; the
> embedding-nearest paths (0.80-0.83 judged) stay propose-only. Judgments in
> `results/knn_tail_judgment_v{1,2,3}.json`.
> **Blind gold v1 (2026-09-01, late): `edu_clean/gold_v1.py`.** A held-out,
> source-stratified gold set (60 strings per landed tier + 100 residual, drawn by
> salted hash; labeled blind by Fable 5.1 with primary/secondary/unsure) measured
> every tier for the first time. Per-tier string precision on the modal-degree row
> (strict / lenient / humanities-level; `results/frontier_gold_v1_score.json`):
> det 0.89/0.96/0.98, jury 0.93/0.97/0.98, frontier 0.93/0.98/0.98,
> knn_head 0.93/0.97/0.97, degree_type 0.89/0.96/0.93. All clear the 0.90 lenient
> bar; nothing was un-landed. Two defects surfaced and were fixed in
> `apply_cip_pooled.py`: (1) honors/GPA placeholders ("Summa Cum Laude Graduate",
> "High Honors") carried a *string-level* 53 from their modal HS row, wrong on the
> same string's BBA/JD rows -- string-level 53 labels are now gated on the row's
> pooled degree level (dropped for associate..doctorate; 770 rows demoted to the
> degree-type tier); (2) HS-diploma rows with placeholder or empty fields got
> nothing because no degree_type maps to 53 -- a row-level `degree_level` tier
> (pooled level 1 -> 53) closes it (56,929 rows). The degree-level apply now runs
> before the CIP apply so the gate reads the pooled level. Pooled row coverage
> 80.95% -> 82.53%; person-level 95.97% -> 96.29% (95.96% excluding the HS tier).
> Scorer semantics worth keeping: a gold of XUN means "the field string carries no
> signal"; rows of such strings coded from the degree line (det swap, degree_type,
> degree_level) are correct, rows coded by a string-keyed tier are errors.
> **Residual is flat:** 681k uncoded rows = 474k with an empty field (208k with an
> empty degree too) + 207k with text over 166k strings; the top 5k residual strings
> cover only 20% of those rows and the head is GPA/honors/"General". A further
> frontier tranche would land < 1% of rows -- stop here.
The 2026-07-09 jury discarded 2,745 disagree + 3,096 abstain strings ≈ 103k education
rows — including plainly codeable heads: 'Information Systems' (2,996 rows, an 11-vs-52
juror split), 'Science', 'Psychology and Sociology', 'Health Policy and Management'.
- Add a third-juror tiebreak pass over the cached disagree set (votes are cached and
  never re-fired — keep that contract). Use a *disjoint-family* big juror on fedora
  (gemma4:31b or qwen3.6:35b via Ollama); accept 2-of-3 at CIP2 grain.
- Also worth accepting: 2-juror votes that agree at 2-digit but disagreed at finer grain,
  if that's what sank them (inspect `edu_clean/cache` vote records first).
- Effort: ~2.7k prompts — under an hour on the deep lane. Calibrate on the existing
  600-string gold sample first (bar: ≥0.85, same as the original panel).

### R4. CIP jury: one more tail tranche `[pool-bulk]`
The remaining uncoded-with-text gap is 570,904 rows over 398,297 distinct strings
(flat tail, 1.4 rows/string). The next 25k strings by frequency cover **177,555 rows**
(~130k at the historical ~73% accept rate); the 25k after that only add ~45k rows.
Fire ONE tranche, then stop — ROI collapses beyond it.
- Reuse `edu_clean/run_cip_jury.py tail --limit` as-is; extend `NON_FIELD_LITERALS`
  with the measured noise first (GPA strings '4.0'/'3.8', grade levels '12'/'9-12'/'12th'/
  'Senior', honors already partly covered) so they stop burning jury budget.

### R5. Gate and land SOC detail proposals `[pool-bulk]`
`career_occupation_proposals.parquet` (1.9M anchored-embedding proposals) covers
1,156,974 unmatched rows at cosine ≥0.9. Do NOT land on cosine alone — measured
failure: 'Intern' → 29-1216 *internist* (cosine 0.84, 39k rows). Jury-gate the top
proposals (by row frequency) with the same 2-juror unanimous pattern as R3, then land
accepted ones as `occupation_pooled` detail grain over the R1 major grain.
- Suggested budget: top 50k proposals by row coverage; run after R1 (R1 may make
  detail grain unnecessary for some analyses — check the actual consumer first).

### R6. Certifications as the skills axis `[no-LLM head + deep-lane tail]`
Raw has no skills section; certifications are the best structured proxy and are
completely unused: 1,673,732 rows, 27.3% of persons. The head is extremely
canonicalizable ('Project Management Professional (PMP)' + 'PMP®' variants, CPA, RN,
BLS, Series 7/63, AWS/Azure, Security+, CSM, Six Sigma…).
- New `cert_clean/` (or a module in the shared cleanlib after F4): value-canonicalize
  `certifications.title`, attach an issuer/domain taxonomy (finance-license, health-clinical,
  IT-cloud, IT-security, PM-agile, trades, …). Deterministic head first (top ~5k titles by
  frequency — measure coverage before deciding whether a jury tail is worth it).
- Person-level rollup: `certifications_person.parquet` (has_any, domains, n_certs).
- Skill-signal availability measured for the wider derivation question: about 65.5% of
  persons, experience descriptions 66.4%, certifications 27.3%, courses 5.1% — 86.1%
  have ≥1 surface. Free-text skill extraction over descriptions/about is the only truly
  expensive job in this plan (millions of rows) — if attempted, `[pool-bulk]`, scope to a
  target subpopulation first, and it MUST stay on-machine (PII; delegation policy).

### R7. Materialize parsed career dates `[no-LLM]`
`career_steps` stores raw date strings; every consumer re-parses them (the year-slip
bug class came from exactly this). 99.26% populated; 100% carry a 4-digit year; 86%
are 'Mon YYYY'. Add `start_year`, `start_month`, `end_year`, `end_month`, `is_current`
(end='Present') columns in `write_career_steps`, single parser, unit-tested.

### R8. Small institution lifts `[gpu-embed]` (optional, low yield)
Slug-less school rows: 382k (`school_method='raw'`) but person-level upside <6pp and
IPEDS is inherently US-only (67.3%). If attempted: embedding/fuzzy name→slug match of
the 398k raw-only titles against the 3.1M slugged vocabulary, threshold-gated; and drop
placeholder schools ('None' 1,842 rows, 'School name:' 274) to honest NULL.

### R9. Profile-grain dedup `[no-LLM]`
48 duplicate `linkedin_id`s among 2,000,000 profiles (2,000,000 vs 1,999,952 distinct).
Keep-first at profile grain during parse or normalize; today only exact row-level
repeats are flagged downstream.

**Explicitly rejected / not worth it:** education-year recovery from raw (absent, see
Part 0); field-from-description sweep (~99k desc-only rows are overwhelmingly
"Activities and Societies:" noise); institution recovery beyond R8; deeper CIP tail
tranches beyond R4.

---

## Part 2 — Refactor tasks

The theme of the audit: the pipeline's *principles* are sound (value-grain
canonicalization, precision-first deterministic backbone + calibrated LLM pooling,
propose-only columns, honest residues, frozen vote caches). The debt is in
*navigability*: git hygiene, doc sprawl, mirrored-module duplication, and a rebuild
path that only works in the order that lives in people's heads.

### F1. Git hygiene — DO THIS BEFORE ANY OTHER TASK
- **175 untracked paths including most of the codebase**: `archetypes/`, `cohorts/`,
  `paths/` py files, `transition_network/`, `enrichment/`, most of `edu_clean/` and
  `career_clean/`, every root *_PLAN.md, even README.md. Months of work exists only as
  working-tree files. Commit code + docs + manifests now (respecting .gitignore).
- Extend `.gitignore` first: `industry/llm_proposals.jsonl*` (2×2.7 GB at module root —
  currently unignored *and* uncommitted), `*.bak`, `*Zone.Identifier`,
  `archetypes/results/`, `normalized/*.bak`, `_extracted_pdf.txt` (or delete it).
- Decide the generated-artifact policy: `portal/results/portal_data.json` (30k lines)
  and `share/*.html`/`.zip` (29k lines) are *tracked and dirty* — either untrack them
  (regenerable; recommended) or commit them atomically with each build, never leave dirty.
- Branch mismatch: work is on `master`, repo default is `main` — pick one (main) and
  delete the other.
- Acceptance: `git status` clean or intentionally-dirty-only; a fresh clone + documented
  bootstrap reproduces the build.

### F2. Fix the fresh-rebuild break (correctness, verified by inspection)
`build_normalized.py::write_education_person` selects `nha_level_pooled`,
`cip2_pooled`, `degree_level_pooled` — columns that `write_education` (which runs
immediately before it) does NOT write; they are patched in later by
`edu_clean/apply_cip_pooled.py`, `apply_degree_level_pooled.py`,
`apply_institution_meta.py`, then `edu_clean/rebuild_education_person.py`. A fresh
`uv run python build_normalized.py --sections education` therefore fails (or silently
requires 4 follow-up commands in exact order that no doc states).
- Fold the pooled passes into `build_normalized.py` as first-class steps (they are
  propose-only and idempotent already), or make `write_education_person` tolerate
  missing pooled columns and emit a loud warning. Prefer the former.
- The last full normalized build manifest is `sections: career` from 2026-06-10 —
  nobody has run the full education path end-to-end since the pooled passes landed.
  A clean full rebuild is the acceptance test (and is also where R1/R2/R7 land).

### F3. One pipeline map, one entry point
22 `run_*.py` CLIs + build scripts, DAG only in docstrings. Add:
- `PIPELINE.md` (or top of README): the real DAG with rebuild order and rough runtimes —
  parse (25 GB → parsed/) → build_normalized (+pooled) → industry → archetypes →
  paths/cohorts/transition_network → portal → share build.
- A `justfile`/`Makefile` with the ~8 real targets (parse, normalize, normalize-edu,
  normalize-career, industry, archetypes, portal, test). Every target = one uv command.

### F4. Extract the shared cleaning library
`edu_clean/` (36 files, 6.6k LOC) and `career_clean/` (26 files, 4.7k LOC) are
deliberate mirrors: `approach_b_fuzzy.py` is 92% character-identical; `common.py`
shares the normalizer/Result/vocab-export/metrics core; there are now FOUR separately
evolved LLM-jury drivers (cip, dlevel, soc, industry) plus `industry/llm_pool.py`.
- Create `cleanlib/` with: text normalizer + token_key, `Result`/`DetailedResult`,
  vocab export, gold-pair metrics, the generic jury driver (candidates → cached votes →
  unanimity/consensus gate → mapping parquet), and the host pool (move `llm_pool.py`
  here; industry imports it back).
- Migrate incrementally: new work (R3–R6) uses cleanlib; existing modules migrate
  opportunistically. Do NOT rewrite calibrated mappings — only the machinery.

### F5. Root doc consolidation
18 root .md files, ~6k lines, heavily stale (8 are June-dated plans for work that has
since shipped or moved). `docs/` already has the right shape (audits/ notes/ design/
plans/). Move: completed plans → `docs/plans/archive/`; active strategy docs
(FOUNDATION, METHODOLOGY, NARRATIVE_FRAMING_PLAN, MESSAGES) → `docs/` or keep at most
3 at root; RAW_DATA_AUDIT.md is superseded by this document (archive it). Rewrite
README.md (dated June 8, predates most modules) to: what this is, the pipeline map,
bootstrap, where docs live. This file itself moves to `docs/plans/` once executed.

### F6. Delete cruft `[no-LLM]`
- `*Zone.Identifier` sidecars (root + data/), `_extracted_pdf.txt`,
  `normalized/education.parquet.bak`, `industry/llm_proposals.jsonl.bak` (2.7 GB —
  verify main file readable first), root `__pycache__/`.
- `sp_audit/` (48 LOC of one-off queries), `exploration/` probes, `prototype/atlas.html`
  → `docs/` notes or delete; they read as live modules but are archaeology.
- `Career Skill Archetypes Framework.pdf` → `docs/reference/` (its extraction already
  lives at `docs/notes/nha-career-skill-archetypes-framework.md`).
- `vault` symlink into Windows Documents: document why it exists or remove it.

### F7. Test infrastructure
10+ `*_tests.py` files, all `if __name__ == "__main__"` style, no pytest, no CI, no
single runner. Adopt pytest (they're mostly compatible already), add a `test` target
running all module tests + `normalization_regression_checks.py`, and (optional) a
GitHub Action if the repo ever gets a remote — otherwise a pre-commit hook locally.

### F8. Lint/format config
`.ruff_cache` shows ruff 0.15.x is used, but pyproject has no `[tool.ruff]` — pin
target-version, line length, and rule set so agents and humans converge.

### F9. Caches and results layout (document, don't move)
5.2 GB `edu_clean/cache`, 710 MB `industry/cache`, 533 MB `career_clean/cache`,
results/ parquet scattered in module dirs. The convention (module-local `cache/` =
regenerable, `results/` = published, manifests committed) is actually fine — but it is
written nowhere. One paragraph in PIPELINE.md + make sure every cache/results dir is
gitignore-covered (archetypes/results currently is not).

---

## Part 3 — Local hardware playbook

Machines (verified live 2026-09-01; fedora details updated from the on-box docs
`~/local-agent-lab/{README,RESULTS}.md` (2026-08-18, measured) and `~/llm_testing/`):
| | local (WSL2 box) | fedora = Framework Desktop (Strix Halo mini-PC) |
|---|---|---|
| Compute | RTX 5080, ~13.7 GB usable VRAM | Ryzen AI MAX+ 395, 128 GB unified RAM, Radeon 8060S (gfx1151) |
| Always-on path | local-llm MCP `local_delegate` (fast lane, qwen3:8b, 32k ctx) | Ollama **0.33.0 on `:11434`** (verified live 2026-09-01 — upgraded since the 2026-08-18 docs, which describe a 0.30.4/`:11435` split that no longer holds; `:11435` is down/intermittent). HTTP reachable even when Tailscale SSH auth has lapsed |
| Bulk path | llama-server sm_120 build, port 8090 (qwen3-4b -np16 or 30B-A3B MoE Q3 ~200 tok/s agg) | llama.cpp **b10488** two builds: Vulkan prebuilt (use this) + HIP-from-source. Tiers via `~/local-agent-lab/bin/serve.sh`: fast `:8098`, deep `:8099`. **Serve with Vulkan + `--spec-type draft-mtp,ngram-mod`** — measured 2.1× fresh-gen / 2.8× edit-shaped decode on Qwen3.8-27B (26.7/36.0 tok/s vs 12.7 baseline; qwen3.6/3.8 GGUFs carry their own MTP head, no draft model needed) |
| Model zoo | small | gemma4:31b, qwen3.6:35b(+A3B), qwen3.8-27B, qwen3:32b, deepseek-r1:70b, mistral-medium-3.5:128b, gpt-oss-agent:65GB, qwen3-coder-next:52GB, qwen2.5-coder:32b. Ollama blobs double as llama.cpp GGUFs for qwen3.5/3.6/3.8 (NOT gptoss/glm — ollama-only arch names) |
| Status | lanes DOWN (relaunch watchdogs) | Ollama UP; llama-server tiers DOWN (relaunch `bin/serve.sh`); SSH re-authed 2026-09-01 |

Measured model quality for agent-shaped work (fedora agentbench, 7 real edit→run→fix
tasks, 2026-08-18): **Qwen3.8-27B dense Q4+MTP = 7/7** (only model to solve the
long-horizon task, 22–29 tok/s); **Qwen3.6-35B-A3B Q4+MTP = 6/7 at 60–86 tok/s** —
3× faster, fails only long-horizon spec-holding. Tool-call reliability 100% across ~90
calls for both. Rule of thumb: dense 27B when the prompt requires holding a whole spec;
A3B MoE for bulk classify/extract throughput (this is the jury workhorse for R4/R5).
Ollama-direct gotchas (from `~/llm_testing/ADVICE.md`): default `num_ctx` is 2048 —
always set options.num_ctx per request; `OLLAMA_KV_CACHE_TYPE=q8_0` halves KV memory
for long-context runs.

Routing rules for this plan:
1. **Default to no model at all.** R1, R2, R7, R9, F-everything are SQL/Python. The
   measured LLM failure mode here is the fluent false positive ('Intern'→internist,
   PhD→philosophy) — deterministic passes and juries with calibration gates exist
   precisely to contain that. Never let a local model make an ungated judgment call.
2. **Small batches of hard judgments → deep lane Ollama** (R3 tiebreaks, R5 gold
   calibration, R6 cert-taxonomy head checks): thousands of prompts, big disjoint-family
   models, no serving setup needed.
3. **Tens-of-thousands+ prompts → llama-server pool** (R4 tail tranche, R5 at scale,
   any description sweep): relaunch the lanes first; `PYTHONUNBUFFERED=1`; don't restart
   a serving lane mid-run (5 consecutive failures = host marked down for the run);
   per-slot ctx ≥6144.
4. **Embeddings → 5080** (R8 name→slug, any new anchor work). sentence-transformers
   under `--group embed`; the anchored-embedding pattern is already proven in
   `career_clean/approach_c_embed.py`.
5. **Privacy line:** raw profile text (descriptions, about, names) must not leave these
   machines. Juries over *distinct vocabulary strings* (field names, titles, cert names)
   are the safe pattern; row-grain free text (R6 extension) is local-only, hard rule.
6. **Replicability contract (keep it):** frozen vote caches (jsonl) + calibration JSONs
   + committed mapping parquets mean any future agent can reproduce or extend a jury
   without re-firing — this is the repo's best idea; every new jury (R3–R6) must
   follow it.
7. **Worthwhile-ness, honestly:** for R3/R4/R5/R6 the local juries are clearly worth it
   (zero marginal cost, proven calibration ≥0.85, overnight-scale runtimes). The one
   task where local-vs-API is a real decision is a full description/about skill-extraction
   sweep (~5.5M steps with text): pool-bulk makes it a multi-day local job; scope it or
   split gold-calibration (API, small) from bulk (local) as industry/M6 already did.

---

## Part 4 — Fedora coding-agent docs: what they say, and how they bear on this plan

Read 2026-09-01 after SSH re-auth. Three docs, in order of authority:

1. **`~/local-agent-lab/RESULTS.md` + README (2026-08-18) — measured, trust this.**
   A real agentic benchmark (edit→run→fix loops scored by whether tests pass) plus
   backend sweeps. Its facts are folded into Part 3 above: Vulkan+MTP serving config,
   Qwen3.8-27B 7/7 vs Qwen3.6-A3B 6/7-but-3×-faster, perfect tool-call reliability,
   the `:8098`/`:8099` tiers (its `:11435` second-daemon setup is already stale —
   see Part 3; `:11434` runs 0.33.0 now). Also measured
   harness overhead: **opencode 1.18.18** (10 tools ≈ 5.3k schema tokens, 41.8k prompt
   tokens/task) is ~half the cost of **pi 0.84.2** with its 6 extensions (88.8k);
   both are installed and configured on fedora. Known bug: opencode's non-interactive
   `run` hangs against the fast tier (zero requests leave it) — use pi `-p` there, or
   opencode against the deep tier only.
2. **`~/llm_testing/LOCAL_AGENT_GUIDE.md` — intent + patterns, partially superseded.**
   Earlier generation (tool landscape "2025", assumes system Ollama `:11434`, aider/
   OpenHands/agent_stack). Its lasting content: the multi-model patterns
   (architect+editor, reasoner→coder→reviewer, router→specialist), the context-
   compression warning (1 pass fine, chained passes destructive — prefer big num_ctx
   over aggressive compression), and the Ollama 2K-default-ctx trap. Its model/speed
   tables are estimates, not measurements — where they conflict with RESULTS.md,
   RESULTS.md wins.
3. **`~/llm_testing/ADVICE.md` — hardware tuning reference** (XNACK, HSA override,
   rocm-smi's misleading 512MB VRAM reading, KV-cache quantization). Note it predates
   the Vulkan-beats-ROCm-for-decode finding; do not take its backend advice over
   RESULTS.md.

**Can the implementing agent for THIS plan be local?** Honest assessment against the
measured results: the fedora bench tasks are small, self-contained, single-file loops —
and even there only the dense 27B goes 7/7, at 22–29 tok/s. Part 2's high-risk tasks
(F1 git surgery over 175 paths, F2 build-order rework, F4 cleanlib extraction) are
multi-file, judgment-heavy, and mistake-expensive: keep those on a frontier-model
session. Genuinely local-delegable implementation work: F6 cruft deletion, F8 lint
config, F3's Makefile, doc moves in F5 — mechanical, verifiable, low blast radius —
via opencode/pi against the deep tier (`PORT=8099 ~/local-agent-lab/bin/serve.sh
qwen3.8 vulkan --spec-type draft-mtp,ngram-mod`), or simply done inline by the frontier
session since each is minutes of work. The unambiguous local win remains Part 1's jury
workloads (R3–R6), where the pipeline's calibration gates were designed exactly to
contain a local model's error rate — with Qwen3.6-35B-A3B+MTP now the preferred bulk
juror (60–86 tok/s) and Qwen3.8-27B/gemma4:31b as the disjoint-family second voice.

---

## Part 5 — Suggested execution order

1. F1 (git safety net) → F6 (cruft) — one session, no model.
2. F2 + R1 + R2 + R7 + R9 in one `build_normalized.py` overhaul → full clean rebuild
   end-to-end (also proves F2). Re-run `normalization_regression_checks.py` + tier counts.
3. F3 + F5 + F8 (map, docs, lint) — cheap, big navigability payoff.
4. R3 (tiebreak, deep lane) → R4 (one tail tranche, pool) → re-run pooled apply.
5. F4 (cleanlib) alongside R6 (certifications = its first consumer).
6. R5 if a consumer actually needs detail-grain SOC; R8 only if institution work surfaces.
7. Downstream refreshes after any recovery landing: archetypes → paths/cohorts →
   portal (respect each module's manifest/cache invalidation).
