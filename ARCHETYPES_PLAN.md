# Career archetypes plan — the humanities possibility space

**Goal.** Build an enriched, clustered dataset that assigns every humanities graduate's
career *state* into one of **10–15 role/skillset archetypes**, at every point in
**career-years 1–15**, so we can eventually render an interactive Sankey-style narrative:
where humanities grads *enter* the workforce, how they *split* across archetypes, and how
they *flow between* archetypes as they age into their careers. This document is the design
brainstorm + phased build plan. Visualization is deferred (Phase 5); the deliverable of
Phases 0–4 is the enriched dataset and the yearwise stock/flow tensors that drive it.

New module lives at `archetypes/` (peer of `career_clean/`, `cohorts/`, `edu_clean/`),
same conventions: `common.py`, topic modules, `run_*.py` drivers, `results/`, `_*_manifest.json`,
`archetype_tests.py`, and this `PLAN.md` → `FINDINGS.md`.

---

## 1. What "archetype" means here (and what it is *not*)

There are **two orthogonal ways** to cluster careers, and the repo already owns one of them:

- **Trajectory-shape archetypes (already exist).** `transition_network/trajectory_features.parquet`
  clusters *whole careers* (k=8, k-means over mobility features: n_moves, promotions, dwell,
  self-emp moves, span). These describe **the shape of a journey** — "job-hopper", "stayer",
  "strong-upward", "self-employment-heavy". They are unwindowed and say nothing about *what kind
  of work* the person does.

- **Role/skillset *state* archetypes (this project).** We cluster the **state a person occupies
  at a moment** — the *kind of work / skillset bucket* — into 10–15 nameable groups
  ("Educators & Academics", "Creatives & Media Makers", "Comms/PR & Marketing", …). Every
  person-year gets exactly one state archetype. This is the missing axis, and it is exactly what
  a Sankey needs: **nodes = state archetypes, flows = movement between them over career-age.**

The two are complementary and multiplicative: trajectory shape × state archetype is a rich later
cross-tab (e.g. "job-hoppers *within* Creatives vs *within* Finance"). We build the state axis and
reuse the trajectory axis as a covariate — we do **not** rebuild trajectory clustering.

**Design principle — cluster the *role vocabulary*, then project person-years onto it.**
Rather than clustering 40M person-years directly (unstable, time-confounded, expensive), we cluster
the **role vocabulary** (`role_canonical`, weighted by person-support) into archetypes *once*, off
the time axis. Each person-year is then assigned its archetype by a cheap role→archetype lookup.
Benefits: archetype definitions are stable and nameable, coverage is ~100% (every role maps
somewhere), and the time dimension stays clean for the yearwise analysis. `career_clean/results/
soc_candidates.parquet` (2.58M rows, one per `role_canonical`, already carrying `n_steps, n_persons,
top_titles, industry_l1_label, modal_seniority`) is a near-perfect starting aggregate; we extend it
to the full role vocab.

---

## 2. Substrate we can actually use (measured)

Person universe: **1,999,974** people; humanities cohort (`nha_level ∈ {1,2,3}`) = **485,781**;
observable in career-age 1–15 = **407,265 persons / 5.03M person-years**. Join key everywhere:
`linkedin_id`.

Per-step latent fields and their **measured coverage** (from `normalized/career_steps.parquet`,
10.8M steps, and companions):

| Signal | Source | Coverage | Use |
|---|---|---|---|
| Detailed SOC (6-digit) | `career_steps.occupation_code` | **21.5%** | strongest role label where present |
| SOC-major via LLM jury | `mappings/role_soc_jury.parquet` (`role_canonical→soc_major`) | **40%** | fills uncoded tail to 23 major groups |
| SOC-major via functional_cluster | `career_steps.functional_cluster` | 2.2% (self-emp) | self-employed recovery |
| **Any SOC-major (triangulated union)** | coalesce of the three | **63%** | primary structured anchor |
| **Industry L1–L4** | `industry/results/step_industry.parquet` | **~100%** (26 L1) | near-universal; carries the 37% SOC gap |
| Seniority | `paths/steps.parquet` `seniority_ordinal`/`seniority_score` | ~30% ordinal, score broad | maps *level*, not archetype |
| Employment form | `career_steps.employment_type` | 100% | employee / self_employed / business_owner split |
| Role text | `role_canonical` / `role_display` / `title_raw` | 98.5% | embedding backbone for the uncoded tail |
| Description free-text | `career_steps.description` | **50.8%** | skillset nuance; embed a sample |
| Company id | `company_canonical_id` | 100% id (no firmographics) | employer identity only — **no size/industry here** (industry is the separate L1 table) |
| Location | `location_*` | country 57% | facet only |

**Key consequence:** SOC alone covers only 63% of steps, so pure-SOC archetypes would strand a
third of the population. The archetype representation must **fuse** triangulated SOC-major (63%) +
industry L1/L2 (100%) + employment form (100%) + a **role-text embedding** (98.5%) so that *every*
role lands in an archetype. Industry and the text embedding are what carry the SOC gap.

Already-built pieces we reuse (do not rebuild): `cohorts/panel.parquet` (40M person-years with
`career_age`, primary role/occupation/seniority per year), `paths/transitions.parquet` (6.0M
adjacent step-pairs with `from_*`/`to_*` role/occupation/seniority + `transition_type`, `dwell_months`),
`industry/results/step_industry.parquet`, and the `role_soc_jury` mapping.

---

## 3. The timeline axis — "years since graduation"

The user asks for **years 1–15 after graduation**. Reality of the anchors:

- True graduation year (`education_person.bachelor_end_year`) is only **~15–20%** populated for the
  humanities cohort.
- The project's established convention (`portal/common.py`, `ANCHOR_TIERS=("A1","A2")`) recovers the
  anchor with **A2 = `start_year + 3`**, validated at **80.4% within ±1yr**; tier A3 (career-onset
  inference) is rejected. With A1+A2, anchor coverage rises to ~**80%**.
- `cohorts/panel.parquet` already ships `career_age = calendar_year − entry_year`, where `entry_year`
  = **first datable job**, not graduation. For the humanities cohort the *median* `entry_year −
  bachelor_end_year` is **0**, so first-job age and graduation age largely coincide — but the tails
  differ (grad school, late entry).

**Recommendation:** define career-year on a **graduation anchor** using `ANCHOR_TIERS=("A1","A2")`
(reuse `edu_clean/anchors.py` + `portal/common.py` so this matches every other portal figure), and
carry `career_age` (first-job) as a **secondary axis / robustness check**. Report both coverage and
the anchor-tier mix honestly. Window = **career-year ∈ [1, 15]** (year 0 = graduation year, often
noisy/partial). Anchor for cohort binning = A1 if present, else A2, else `entry_year` (flagged); since
median(`entry_year − bachelor_end_year`) = 0, first-job year is a sound *coarse* (5-year-bin) grad proxy
even though it is a poor *fine* per-year anchor.

### 3a. Graduation cohorts and cohort-specific observation windows (decided: yes)

The graduation distribution is **strongly right-skewed toward recent grads**, and the calendar data
ceilings at **2025**. A *fixed* 15-year window (require full observation to age 15) keeps only
**251,932 / 407,872** humanities people (−38%) **and systematically deletes the recent-grad mass** — a
pooled 15-year Sankey would silently describe *only* ~2005–2010 graduates in a pre/post-2008 labor
market. Measured survival of a fixed full-window requirement:

| full window required | humanities persons kept |
|---|---|
| to age 5  | 407,872 (all) |
| to age 10 | 336,735 |
| to age 15 | 251,932 |

**Decision: make graduation-cohort a first-class dimension with cohort-specific max windows.** Bin grads
into 5-year cohorts and observe each only as deep as the data honestly allow (ceiling 2025):

| grad cohort | max career-year window | note |
|---|---|---|
| 2005–2009 | 1–15 | fully mature |
| 2010–2014 | 1–10 | |
| 2015–2019 | 1–5  | the modal mass |
| 2020–2024 | 1–3  | entry snapshot only |
| ≤2004 | 1–15 (capped) | thinner, older labor market |

This does two things at once: (1) it **uses all the data** instead of throwing away 38%, and (2) it turns
the confound into signal — we can compare the **year-1→year-5 flow for 2015–2019 entrants against the same
band for 2005–2009 entrants**, i.e. measure how the humanities possibility-space itself shifted across
generations, always **at equal career-age** (the `cohorts/` module's cardinal rule against survivorship
artifacts). The pooled all-cohort Sankey remains available as the sum over cohorts *at equal career-age*.

> **Build note (2026-07-16, see `archetypes/FINDINGS.md` §3).** The axis was implemented on **career
> entry (first-job year)**, not graduation. Measured reality: graduation year cannot be recovered from
> career onset — first-job vs true bachelor-end lands in a *different* 5-year bin 60% of the time and no
> offset fixes it (reproducing edu_clean's rejected A3). So `career_year = calendar_year − entry_year`
> (= `panel.career_age`) is the universal, clean primary axis and cohorts are **entry cohorts**; the true
> A1/A2 graduation anchor (~15% of people) is carried as optional metadata for a clean graduation re-cut.

---

## 4. Feature design — the fused role-state representation

We build features at **two grains** and clip them together.

**4a. Role-level feature vector** (unit = `role_canonical`, the clustering unit). For each role,
aggregate across all its steps:
- **Structured priors** (interpretable, low-dim): modal + distribution of triangulated SOC-major;
  modal industry L1/L2; employment-form mix (employee/self-emp/owner); seniority profile
  (mean/spread of `seniority_ordinal`); person-support `n_persons`.
- **Text embedding** (semantic, high-dim): sentence-transformer embedding of a role descriptor built
  from `role_display` + top raw titles + a sampled, concatenated set of `description` snippets for
  that role (where present). This is what separates "Content Strategist" from "Strategy Consultant"
  when both lack a SOC code. Embeddings via the `embed` dep group (sentence-transformers/torch) or the
  local LLM serving stack; ~50–200k roles above a person-support floor is cheap to embed.
- **Fusion:** L2-normalize the text embedding; one-hot/soft-encode the structured priors; concatenate
  with a tunable weight `α` on structured vs text. (α is an open decision; start 0.5.)

**4b. Person-year state** (unit = `(linkedin_id, career_year)`, from `panel.parquet` primary role).
Each person-year inherits its role's archetype via lookup. Where the panel's primary-role selection is
ambiguous (concurrent roles), keep the highest-seniority primary (panel already does this).

Only roles above a **person-support floor** (e.g. ≥25 persons) are clustered directly; the long tail
is assigned by nearest-centroid in the fused space (or by its SOC-major×industry cell). Log the tail
share so coverage is never silently overstated.

---

## 5. Clustering method — three approaches, and the recommendation

**Approach A — Unsupervised over the fused role space.** KMeans (k≈12–15) or HDBSCAN over 4a vectors.
Pro: fully data-driven, may surface non-obvious skillset groupings. Con: clusters can be hard to name,
unstable across seeds, and may fracture by seniority/industry rather than skillset. Requires heavy
post-hoc labeling.

**Approach B — Semi-supervised anchored archetypes (recommended).** Hand-define ~15 **archetype anchors**
as SOC-major × function seeds (see §11), embed each anchor's descriptor, then assign each role to its
nearest anchor in the fused space, with unsupervised KMeans used only to *split/merge* anchors that are
over/under-populated. Pro: nameable and stable by construction, coverage 100%, directly matches a
Sankey's need for legible nodes; the anchor list is auditable and tweakable. Con: anchor design injects
priors (mitigated by letting data split/merge and by measuring within-anchor coherence).

**Approach C — Two-level (macro archetype → micro sub-bucket).** Approach B for the 12–15 macro nodes,
then an unsupervised sub-clustering inside each for optional Sankey drill-down. Pro: satisfies "10–15
buckets" at the top while preserving detail. Con: more moving parts; defer sub-level to a later phase.

**Recommendation: build B now, structured so C is a later add-on.** Anchored assignment gives us the
legible 12–15 buckets the narrative needs; keep the fused vectors and centroids so an unsupervised pass
(A) can be run as a *validation cross-check* ("do the data agree with our anchors?") and so drill-down
(C) is a config change, not a rebuild.

Cluster on the **role vocabulary**, freeze the model (anchor centroids + role→archetype map), then
project. Archetype assignment is versioned in a manifest with the seed list, α, support floor, and the
unsupervised-agreement score.

---

## 6. From archetypes to the Sankey — the yearwise stock & flow tensors

Two artifacts drive the eventual visualization:

- **Stock (occupancy).** `occupancy[grad_cohort][career_year][archetype]` = count/share in each
  archetype at each in-window year, indexed by graduation cohort (§3a) and faceted by
  `humanities_field_group` / `nha_level`. Built from `panel.parquet` filtered to the humanities cohort
  and windowed per-cohort. Pooled view = sum over cohorts at equal career-year.

- **Flow (transitions).** `flow[grad_cohort][career_year][from_archetype][to_archetype]` from
  `paths/transitions.parquet`: map `from_role`→archetype and `to_role`→archetype, timestamp the
  transition at `year(to_start_dt) − grad_year`, bin into the (cohort, year) axes. This is the Sankey's
  link tensor and encodes both *staying* (diagonal) and *switching* (off-diagonal), including
  entry/exit and into-self-employment as special archetypes/edges. Every cohort is observed only within
  its honest window (§3a), so the tensor is never populated past a cohort's censoring horizon.

Because a Sankey across 15 years is dense, the plan produces the **full tensor** and lets the viz layer
choose the framing (year-to-year ribbons, entry→year-15 aggregate, or a small set of milestone columns
e.g. years 1/3/5/10/15). Suppression follows the project bar (`MIN_SUPPORT`, n≥10; facet floor 5).

---

## 7. Enriched dataset — deliverables (schema)

- `archetypes/results/archetype_model.json` — the frozen model: anchor list, centroids meta, α,
  support floor, unsupervised-agreement score, version.
- `archetypes/results/role_archetype.parquet` — `role_canonical, archetype_id, archetype_label,
  assign_method (anchor|nearest|soc_industry_fallback), assign_confidence, n_persons`. The reusable
  role→archetype crosswalk (goes in `normalized/mappings/` too).
- `archetypes/results/person_year_archetype.parquet` — `linkedin_id, career_year, archetype_id,
  seniority_score, employment_type, nha_level, humanities_field_group, grad_year, grad_cohort,
  anchor_tier, in_window`. The core enriched panel (humanities cohort) — one row per person-year;
  `in_window` marks rows inside the cohort's honest observation horizon (§3a).
- `archetypes/results/occupancy.parquet` / `flows.parquet` — the stock/flow tensors of §6.
- `archetypes/FINDINGS.md` — coverage, archetype profiles, validation, honest caveats.

---

## 8. Validation

- **Coverage ledger:** % of person-years assigned by anchor vs nearest vs fallback; the tail share.
  Never report a Sankey without the coverage denominator.
- **Cluster coherence:** within-archetype SOC-major purity and industry purity; silhouette on fused
  vectors; **unsupervised-agreement** (Approach A vs B adjusted-Rand) as the "do the data back the
  anchors?" check.
- **Face validity:** top roles/titles per archetype must read as a coherent skillset (hand-audit a
  sample, like `career_clean`'s gold checks).
- **Timeline sanity:** occupancy at year 1 should match known humanities entry patterns (Education,
  Comms/Marketing, Admin, Hospitality heavy); leakage tests that anchor recovery isn't distorting
  year-1 mix.
- **Selection caveat (inherited from cohorts):** cross-year gradients conflate survivorship/backfill;
  always compare at equal career-year and flag right-censoring. Reuse the `cohorts/` warnings.

---

## 9. Phased build plan

- **Phase 0 — Scaffold & anchor spec.** Create `archetypes/`; write `common.py` (loaders, the
  triangulated-SOC-major coalesce, graduation-anchor via `edu_clean/anchors.py`); draft the ~15
  archetype anchor list (§11) as a reviewable JSON. *Output:* module skeleton + `anchors.json`.
- **Phase 1 — Role feature table.** Build the full role-vocab aggregate (extend `soc_candidates`
  logic to all roles): structured priors per `role_canonical`. *Output:* `role_features.parquet`.
- **Phase 2 — Embeddings & fusion.** Embed role descriptors (+ sampled descriptions); fuse with
  structured priors. *Output:* `role_vectors.parquet` (+ embed manifest).
- **Phase 3 — Cluster & assign.** Anchored assignment (Approach B) with data-driven split/merge;
  freeze model; run unsupervised cross-check. *Output:* `archetype_model.json`, `role_archetype.parquet`.
- **Phase 4 — Yearwise dataset.** Project `panel.parquet` + `transitions.parquet` onto archetypes,
  window on graduation anchor, build stock/flow tensors + person-year panel. *Output:*
  `person_year_archetype.parquet`, `occupancy.parquet`, `flows.parquet`, `FINDINGS.md`.
- **Phase 5 — Visualization (deferred).** Sankey/alluvial narrative in the portal; sub-bucket
  drill-down (Approach C). Not in scope now.

Each phase: a `run_*.py` driver, a manifest, and `archetype_tests.py` cases, mirroring `career_clean`
and `cohorts`.

---

## 10. Open decisions (recommendation in bold)

1. **Cohort scope:** strict humanities `nha_level=1` (166k) vs inclusive `1–3` (486k).
   → **Inclusive (1–3), with `nha_level` and `humanities_field_group` as facets** so the narrative can
   zoom from "all humanities-adjacent" to "core humanities".
2. **Timeline anchor:** graduation (A1/A2) vs first-job `career_age`.
   → **Graduation A1/A2 primary, first-job secondary** (§3). **Cohort-specific windows adopted** (§3a):
   graduation-cohort is a first-class axis; each cohort observed only to its honest censoring horizon.
3. **Clustering approach:** A vs **B** vs C. → **B now, C-ready** (§5).
4. **k / archetype count:** target **13–15 macro archetypes** (§11), tunable by data-driven split/merge.
5. **Employment-form as its own archetype?** e.g. "Founders & Independent Practitioners" as a distinct
   node vs a cross-cutting attribute. → **Distinct node** (self-employment is a real destination in the
   possibility-space narrative), *and* keep `employment_type` as an attribute for cross-tabs.
6. **Description embedding depth:** role-level only vs per-step sample. → **Role-level for v1**; per-step
   is a Phase-2 enrichment if coherence is weak.

---

## 11. Illustrative anchor list (13–15 archetypes) — a starting draft for Phase 0

Grounded in the SOC-major + industry-L1 signal humanities grads actually land in. Names/boundaries are
a **draft to be refined by data**, not final:

1. **Educators & Academics** — teaching, instruction, academia (SOC 25; industry EDU)
2. **Creatives & Media Makers** — design, art, film/audio, production (SOC 27-1/27-4; MED)
3. **Writers, Editors & Content** — writing, editorial, content strategy (SOC 27-3)
4. **Communications, PR & Marketing** — comms, brand, social, marketing (SOC 13-1161/27-3; cross-industry)
5. **Sales & Business Development** — sales, BD, account management (SOC 41)
6. **Managers & Operations Leaders** — general management, ops, program leadership (SOC 11)
7. **Business & Strategy Analysts / Consultants** — analysis, consulting, strategy (SOC 13-1)
8. **Finance & Accounting** — finance, accounting, financial analysis (SOC 13-2; FIN)
9. **Tech & Product** — software, data, product, IT (SOC 15; TEC)
10. **Administrative & Coordination** — admin, coordination, office/support (SOC 43)
11. **Legal, Policy & Research** — legal, policy, social-science research (SOC 23/19; PRO.LEGAL/PUB)
12. **Healthcare & Human Services** — clinical, counseling, social work, community (SOC 29/31/21; HLT)
13. **Nonprofit, Public Service & Advocacy** — mission-driven roles across functions (industry NPO/PUB)
14. **Hospitality, Retail & Service** — food, retail, personal service, events (SOC 35/39; HOS)
15. **Founders & Independent Practitioners** — self-employed / business owners / freelance
    (employment_type = self_employed/business_owner)

Nonprofit/Public (13) is deliberately industry-anchored rather than function-anchored — it captures the
common humanities pattern of *mission-sector placement across many functions*; whether it survives as a
node or dissolves into functional archetypes with an NPO/PUB attribute is an explicit data-driven test
in Phase 3.
