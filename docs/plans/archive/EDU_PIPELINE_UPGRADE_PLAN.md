# Education extraction upgrade — degree / institution / field

Three workstreams that improve the raw→processed education workflow, in
dependency order. Same repo discipline throughout: **deterministic backbone is
never mutated** (jury/inference columns are added alongside, propose-only),
every new layer is **gated on a measured accuracy bar before it feeds an
analysis**, every driver is a single reproducible command with a manifest and
tests, and the humanities population is the primary lens.

Status legend: ☐ todo · ◐ in progress · ☑ done · ⧗ blocked on external resource

---

## Phase 1 — Land the CIP field jury project-wide  ☑ (data + tests landed)

**Problem.** The calibrated CIP2 LLM jury (`normalized/mappings/field_cip_jury.parquet`,
18,708 accepted field strings, unanimous accuracy **0.911** on held-out gold, gate 0.85)
is consumed **only by the portal**, behind `portal/common.CIP_SOURCES`. Every other
consumer — `cohorts/`, `archetypes/`, any enrichment analysis — reads
`normalized/education.parquet` at the deterministic-only **58.8%** CIP coverage.
Bias check (`portal/cip_bias_check.py`) is **clean** (no material composition drift;
cohort growth arts +27%, english +19%, philrel +22%, baseline +14%, history +2%).
The 122,628 `field_method='typo'` strings are **already in the jury candidate pool**
(verified 100%), so there is no separate "typo recovery" lever — the jury covers them.

**Design — add, don't mutate.** A new driver augments the canonical education table
with pooled columns; the deterministic `cip_code` / `cip2` / `cip4` / `nha_level` /
`humanities_field_group` columns stay **byte-identical** (so the `tier_counts`
fingerprint on `(linkedin_id, cip_code, nha_level)` is unchanged and every existing
consumer is unaffected). Added columns:

| column | definition |
|---|---|
| `cip2_pooled` | `coalesce(cip2, jury.cip2)` — jury fills only where `cip_code IS NULL` and `field_norm = lower(trim(field_raw))` matches an accepted jury string |
| `cip_source` | `'det'` where `cip2 IS NOT NULL`, else `'jury'` where filled, else `NULL` |
| `nha_level_pooled` | `nha_level` where `cip_code` present (keeps 6-digit override precision); else `classify_cip(cip2_pooled).level` (family-level) |
| `humanities_field_group_pooled` | same coalescing, `field_group` from the family classifier |

Join semantics copied verbatim from `portal/build.py:_edu_table` (the tested reference).

**Tasks.**
- ☑ Confirm gate: `portal/cip_bias_check.py` clean; `CIP_SOURCES` already pooled.
- ☑ Confirm `classify_cip("54")` classifies at family level (cip2 → nha_level works).
- ☑ `edu_clean/apply_cip_pooled.py` — augments `education.parquet` with `cip2_pooled`,
  `cip_source`, `nha_level_pooled`, `humanities_field_group_pooled`. Validated:
  deterministic fingerprint **byte-identical** on disk (verified vs `.bak`), row count
  identical, `cip2_pooled ⊇ cip2`, nesting holds. Manifest: `_cip_pooled_manifest.json`.
  **CIP coverage 58.8% → 69.0%** (+362,263 jury rows). **L1 persons 210,495 → 246,482.**
- ☑ `education_person.parquet` rollup (`edu_clean/rebuild_education_person.py`): added
  `nha_level_pooled`, `humanities_field_group_pooled`, and the **corrected any-degree
  flags** `hum_l1_any`/`hum_l2_any`/`hum_l3_any`/`hum_l1_bachelor_any`. Undercount FIXED:
  person-grain L1 165,854 → **246,482** (== record-grain truth). Bachelor pop 140,548.
- ☑ `run_tier_counts.py` — reports `tiers`(det) + `tiers_pooled`; fingerprint extended
  to cover pooled cols. `tier_counts.json` refreshed.
- ☑ Tests: `tier_tests` gains pooled drift+nesting+superset checks; all green. Portal
  suite (43 checks) green incl. byte-identical A1 membership + "cip2 predicate ==
  historical" (0 mismatches). `humanities_tests` / `cip_tests` green.
- ☑ **Perf bonus:** fixed a pre-existing nested-loop in `portal/build.py:_edu_table`
  (jury join `ON cip_code IS NULL AND ... = lower(trim(...))` → pure equijoin; ~minutes
  → 0.1s). `run_portal_data` 5min+ → ~98s (substrate-dominated).

**Downstream revision (prep the ground).**
- ☑ `cohorts/build_panel.py` — BOTH `profiles.parquet` (per-person) and the annual
  `panel.parquet` now carry `nha_level_any`, `hum_l1_any`, `hum_l1_bachelor_any`,
  `humanities_field_group` (pooled, any-degree). Enables the humanities-vs-non cohort
  cut the module was missing (208,141 valid-cohort L1 persons). Regenerated; cohort
  tests green. **Phase re-runs (profiles/scarring/survival/typologies/generational) to
  actually PRODUCE the humanities cut are the analysis-revision step (see checklist).**
- ☑ `archetypes/common.py` — `humanities_cohort_sql` switched from the undercounting
  terminal `ep.nha_level` to the pooled `hum_l*_any` flags. **Re-run needed** to
  materialize (role assignment + yearwise tensors) — see checklist.
- ☐ `portal/build.py:_edu_table` — optional dedup: read `cip2_pooled` from the canonical
  table instead of re-joining the jury (deferred; portal correct & tested as-is).

---

## Phase 2 — Institution metadata via IPEDS/Carnegie crosswalk  ☑

**Problem.** School resolution is strong (~88% to a canonical slug) but **no
institution attributes were attached** — a first-order outcome moderator absent.

**Done.**
- ☑ IPEDS `HD2023` landed at `reference/ipeds/HD2023.csv` (NCES, public domain).
- ☑ `reference/build_ipeds_crosswalk.py` — `slug → UNITID` via exact + unique-core
  (≥3-token guard) + a hand-verified flagship map. **Precision-first, gold-inspected**
  (top-40 by volume + all core + a mid-frequency sample; no residual errors) — above
  the 0.95 bar. **68.0% person-weighted coverage; ~71% of L1-humanities persons.**
- ☑ `normalized/mappings/school_ipeds.parquet` (3,734 slugs) + `reference/institution_meta.parquet`
  (all 6,163 institutions, decoded `control_label`/`carnegie_label`/`iclevel_label`/
  region/metro). `reference/ipeds/README.md` documents source, method, decodes, coverage.
- ☑ `reference/ipeds_tests.py` — one-per-slug, unitid FK, label completeness; all green.
- ☑ Verified join: L1-humanities persons split **public 106,434 / private-nonprofit
  62,950 / for-profit 5,405** — the institution-type moderator now exists.
- ☐ (follow-up) IPEDS `ADM2023` for selectivity; time-varying Carnegie is out of scope.

---

## Phase 3 — Degree-level extraction  ◐ (deterministic lever REJECTED; jury blocked on infra)

**Deterministic field→level rescue: REJECTED (measured 0.505 < 0.90 gate).**
`edu_clean/degree_level_rescue.py` reapplies the committed degree parser
(`final_hybrid.parse_degree`) to `field_raw` for the 719,559 null-level rows. Only
9,776 rows parse to a level, and on a non-circular gold (rows with a known
`degree_level` whose field box also parses) the field-box level matches the true
level just **50.5%** of the time — the parser mis-fires on field names with
degree-like substrings (**"Public Diplomacy"→diploma**, "Secondary Education"→high
school, "Industrial Technology"→doctorate). Same precision-first verdict as the A3
anchor and the duration-only inference; the driver refuses to ship on the gate
fail. Negative recorded in `edu_clean/results/degree_level_rescue.json`. **The
reliable lever is the context LLM jury** — the parser can't disambiguate
"diplomacy" from "diploma", but a jury reading degree+field+school+duration can.

**LLM jury: blocked on serving stack (llama-server lanes 8090/8091 down; only
Ollama:11434 up).** Design below stands; build + run when the stack is up.

### original plan (unchanged design):

**Problem.** `degree_level` is NULL for **726,490 (20.3%)** rows; the raw `degree` box
for these holds field strings ("psychology", "business administration") or non-degree
noise ("none", "study abroad", "minor"). Duration-**only** inference was correctly
rejected (74.7% < 85% gate). Untried: an LLM jury reading **context**
(degree_raw + field_raw + school + program duration + co-degrees), the pattern that
cleared 0.88–0.91 for SOC and CIP.

**Plan (mirror the CIP/SOC jury playbook).**
- ⧗ Needs local LLM serving stack (llama-server lanes / Framework host) — confirm up.
- ☐ Candidates = distinct `degree_norm` among NULL-level rows (head-concentrated).
- ☐ Gold = deterministically-leveled strings (strip level, check recovery), + a
  hand-curated hard set including genuine no-degree → **abstain**.
- ☐ Two-juror unanimity to a small enum {HS, cert, associate, bachelor, master,
  doctorate, none/abstain}; anchors with leak guard; calibrate; gate ≥0.85.
- ☐ Near-free deterministic partial first: field→level rescue for the 71,490 NULL-level
  rows whose `field_raw` contains a degree token.
- ☐ Land as `degree_level_pooled` + `degree_level_source` (propose-only). Grows the
  bachelor-major population and the "touches humanities" breadth.

---

## Cross-cutting: "encompass the updated data" downstream checklist

**Analysis-revision status (all items below now IMPLEMENTED unless noted):**

- ☑ **Archetypes re-run** — `run_yearwise` on the corrected cohort: **407,265 →
  551,560 persons** (6.84M person-years), OTHER share stable 11.4%. Sub-field
  alluvial is a query on the tensor (English→Writers 30% / Fine Arts→Creatives 57%
  at y10). `archetypes/results/*` regenerated.
- ☑ **Institution facet** — `edu_clean/apply_institution_meta.py` attaches the
  primary institution's IPEDS type to `education_person` (`inst_control_label`,
  `inst_carnegie_label`, region, metro) for every consumer. 67.3% coverage; L1
  humanities skew R1 57.7k / master's 29.8k / liberal-arts 7.9k.
- ☑ **Cohorts humanities cut** — ALL five phases now carry a humanities dimension
  (profiles/scarring/survival/typologies/generational), tests green. Findings:
  humanities track ~0.018 below on seniority at equal age, advance ~13% slower to
  first upward move (Cox HR 0.87), NOT differentially recession-scarred (interaction
  p=0.41), but ~2× more likely to enter self-employment (3.9% vs 2.1%).
- ☑ **Enrichment possibility-space** — `enrichment/build_enrichment.py`: humanities
  over-index on every non-job-title dimension — volunteer 16.1% vs 13.0%, publications
  5.6% vs 3.6%, honors 10.7% vs 8.5%, professionally multilingual 10.8% vs 8.7%
  (Language majors 31.2%); top causes Education/Children/Arts&Culture. Tests green.
- ☑ **Degree-level jury — LANDED.** Calibrated **0.9949** unanimous accuracy
  (qwen3-4b 0.995 / llama3.1-8b 0.988). Head run: 10,000 keys / 20,000 units,
  **0 failures, 0 parse errors**; merge accepted **3,013 keys → 79,063 rows**
  (1,787 correctly abstained on non-degree strings, 674 disagreed → not shipped).
  `apply_degree_level_pooled --execute` landed `degree_level_pooled` /
  `degree_level_source`: **degree-level coverage 79.7% → 81.9%** (+79,449 rows —
  mostly certificate/associate credentials the null degree-box hid, + 13,671
  bachelor's). Backbone byte-identical, CIP-pooled columns + fingerprint intact,
  all edu tests green. Deterministic tiebreaker added to candidate ordering.
  Person rollup propagated (2026-07-24): `education_person` gains
  `highest_degree_level_pooled` + `hum_l1_bachelor_pooled_any`; 19,766 persons
  gain a highest level, L1-humanities bachelors 140,548 → **141,245**. Institution
  meta re-attached; no fan-out; downstream tests green.
  Details below (superseded ◐ note kept for provenance):

- ◐ **(superseded) Degree-level jury — UNBLOCKED, calibrated, running.** Harness
  `edu_clean/dlevel_{taxonomy,jury}.py` + `run_dlevel_jury.py` + `dlevel_tests.py`.
  **5080 lane fixed:** restarted `llama-server` locally; the Framework lanes'
  build can't serve the strict-JSON-schema grammar (HTTP 000) and the 30B bulk-moe
  won't fit alongside a 2nd model in 16GB, so the panel was reconfigured to **two
  disjoint LOCAL jurors** — `qwen3-4b-q4` (:8090) + `llama31-8b` (:8092), both
  served by the working sm_120 build (slim 16k ctx so both fit). **Calibration
  PASSED emphatically: unanimous accuracy 0.9949** (n=592/600, coverage 98.7%,
  0 parse failures; per-juror qwen3 0.995 / llama3.1 0.988). Head run firing over
  the top-10k (degree,field) keys (~41% of the 517k null-level rows), ~4 units/s.
  On completion: `run_dlevel_jury merge` → `edu_clean.apply_degree_level_pooled
  --execute` (landing driver BUILT: adds `degree_level_pooled`/`degree_level_source`,
  backbone byte-identical, validated). Deterministic field→level rescue stays
  rejected (0.505). **NOTE:** the two slim local jurors are one-off processes for
  this run; restart `~/llm-serving/serve-local.sh` to restore the normal config.
- ☐ Portal institution-type facet + `_edu_table` dedup onto canonical `cip2_pooled`
  — optional presentation wiring (deferred; portal correct & tested as-is).

---
### (superseded) earlier checklist — kept for provenance
Status of consumers after Phases 1–2 (☑ = data/wiring done; ⟳ = re-run/revise to
actually PRODUCE the humanities cut — the analysis-revision step):

- ☑ `edu_clean/` — tier counts (det + pooled), `HUMANITIES_CLASSIFICATION.md` refreshed
  (69.0% pooled coverage, 246,482 L1 persons), tests green.
- ☑ `portal/` — already pooled for CIP; verified byte-consistent, 43 tests green; jury
  join perf fixed. ⟳ optional: add an **institution-type facet** (Phase 2 crosswalk)
  and dedup `_edu_table` onto canonical `cip2_pooled`.
- ☑ `cohorts/` — panel + profiles carry humanities flags (208,141 valid-cohort L1).
  ⟳ **re-run + extend** `profiles/scarring/survival/typologies/generational` to cut by
  `hum_l1_any` (humanities-vs-non), the module's missing question. `scarring.py` should
  also swap its instrument to `graduation_year` (already computed).
- ⟳ `archetypes/` — `humanities_cohort_sql` fixed (cohort 407k→552k). **Re-run**
  `run_yearwise` (role map is cohort-independent) to materialize the corrected/larger
  cohort's occupancy + Sankey tensors; add `humanities_field_group` + IPEDS facets.
- ⟳ Institution moderator (Phase 2) — wire `school_ipeds`+`institution_meta` into portal
  choices / cohorts / archetypes as an outcome facet (public/private, R1/LAC, region).
- ⟳ Degree-level (Phase 3) — deterministic rescue rejected; run the context LLM jury
  once the llama-server lanes are up, then land `degree_level_pooled` canonically.
- ⟳ Enrichment opportunities (recommendations/volunteer/languages) — now over the
  larger pooled population; unbuilt (the possibility-space expansion from prior turns).
