# Approach A — Learn the archetype space from a rich role representation

**Status:** proposal. Nothing in this document has been merged; no existing file was modified.
**Author lens:** representation quality, not rule quality.
**Date:** 2026-08-05. All numbers below were measured against the repo unless marked *(given)*.

---

## 1. Thesis

The shipped build is a **title-string classifier applied three times and counted as three
independent signals**. I verified this: `career_steps.occupation_code` is populated from
`normalized/mappings/career_occupation.parquet`, which is keyed on the raw title string
(`value` → `canonical_id`), and only **18,918 distinct `role_canonical` values carry any
detailed code at all**, of which **99.58% carry exactly one distinct code**
(96.73% of coded steps). `normalized/mappings/role_soc_jury.parquet` is **299,787 rows
for 299,787 distinct roles**, all `method='llm_jury_v1'`, all unanimous — again a pure
function of the role string. `archetype_spec.KEYWORD_RULES` reads
`role_features.role_text` = `lower(mode(role_display) || ' ' || mode(title_raw))`,
mean **9.85 words / 77.7 chars**. So SOC-detail, SOC-major, and the regex tree are all
deterministic functions of the same ~10-word string, and "within-archetype SOC purity 0.65"
and "keyword-vs-SOC agreement 0.41" are **self-agreement statistics, not external
validation**. Meanwhile the one large body of genuinely independent evidence about what the
work actually is — **5,480,406 free-text `description` fields, 50.9% of non-duplicate steps,
mean 454.3 chars (median 337, p90 1,005), 98.91% of them textually unique** — is used
nowhere in `archetypes/`. This proposal replaces the ~10-word title with a **role document**
built from that evidence, learns the archetype geometry from it by over-clustering and
merging rather than hand-specifying it, and adds a **step-level refinement layer** for the
polysemous head roles that the title can never disambiguate.

---

## 2. What's broken now that this fixes

| Measured defect | Root cause in the representation | What Approach A does |
|---|---|---|
| Unsupervised cross-check **ARI 0.16, NMI 0.26** (`results/unsupervised_crosscheck.json`) | MiniLM is being asked to cluster a 9.85-word modal title. I reproduced **exactly this** (ARI 0.161 on title-only text, 4,000 head roles, k=15) and moved it to **0.211** simply by appending 8 sampled descriptions per role — same model, same k, same roles. | Encode ~1,900-char role documents instead of ~40-char titles. |
| **Industry L1 "≈100% coverage" is not real.** `industry/results/step_industry.parquet`: `l1='XOT'` on **5,072,721 / 10,798,794 = 46.97%** of steps, and `XOT` is **exactly co-extensive with `method='unresolved'`** (identical count). Informative L1 = **53.03%**. `l2` is 98.5% populated but `XOT→XOT` for the whole residual. `validation.json` shows `top_l1='XOT'` for **12 of 16** archetypes. | `role_features.industry_l1 = mode(industry_l1)` returns the residual token for a large share of roles, so the "signal that carries the 37% SOC gap" is mostly a junk category encoded as a value. | Recompute industry as **modal *informative* L1 + its share**, `NULL` when the informative share is below a floor. Never encode `XOT` as a category. |
| `industry_l1` and `mean_seniority` are aggregated in `role_features.py` and **never read** by `assign_role()` — they appear only in `validate.py`. | The decision tree has no mechanism to consume continuous or distributional features. | Both become blocks in the fused vector; seniority additionally gets **residualized out** (see §3.4). |
| Embedding fallback resolves **1,153 roles = 0.044% of the 2,605,247-role vocabulary**, 0.27% of role-occupancy *(given: 0.27%)*. | It matches a role string against 15 hand-written descriptor strings with a 0.45 cosine floor — the weakest possible use of an encoder. | The encoder defines the space; there is no "fallback" tier. |
| **Archetype 7 "Analysts/Consultants" is dominated by project/program/operations managers** — `managerproject` 63k person-years, `manageroperations` 29k, `managerprogram` 26k *(given)*. | `KEYWORD_RULES` line `analyst\|consult\|strateg\|business operations\|project manager\|program manager\|operations (analyst\|manager\|associate)` fires on the title alone. A project manager at a construction firm and one at an ad agency get the same label. | §3.7. The title is identical; the descriptions are not. Step-level refinement splits them by what is being delivered. |
| **Archetype 11 "Legal, Policy & Research" absorbs chemists, geologists, clinical psychologists and `assurancequality`** *(given)*. | `SOC_DETAIL["19"] = "legal"` folds the entire Life/Physical/Social Science major in by fiat. | §3.5. Over-clustering to 200–400 micro-clusters *guarantees* a lab/QA/bench-science micro-cluster exists as a separate object; the merge step then attaches it by measured proximity, and it will not be near policy-brief and litigation documents. Nothing is folded by fiat. |
| **`president` = 125,759 person-years, the single largest role in the corpus** → Managers *(given)*; Managers is 14.4% of person-years and admittedly a generic-title catch-all. | `president` is a pure **rank** token with zero functional content. The representation has no way to express "this string tells you the level and nothing about the work." | §3.4 (seniority residualization) + §3.6 (Managers is demoted from a functional node to a **level axis**) + §3.7 (`president` is the canonical polysemous role and is resolved per-step). |
| **OTHER = 11.36% of in-window person-years** *(given)*; `residual_other` is 10.6% of role-occupancy *(given)* across 597,936 roles. | These are roles whose title matched no regex. 60.3% of all roles (1,571,682 / 2,605,247) have at least one description ≥20 chars — for most of the residual there *is* evidence, it is just unread. | Roles with descriptions are placed by projection, not abstention. Abstention is reserved for roles with neither usable text nor description. |
| Bucket sizes are unbalanced by construction: Managers 14.4%, OTHER 11.4%, Nonprofit 0.9%. | Bucket boundaries were set before the data were looked at. | Balance becomes a **cut-selection criterion** on the merge dendrogram (§3.5), not an afterthought. |

---

## 3. Pipeline

Inputs are all existing artifacts; no upstream module is modified.

### 3.0 Role universe and support tiers

Support is extremely concentrated *(given)*: of **681,454** roles the humanities cohort ever
occupies, **2,690 cover 50%** of person-years, **104,437 cover 80%**, **249,858 cover 90%**,
**582,197 cover 99%**. My own corroborating global cut on `role_features.parquet`: 829 roles
with `n_persons ≥ 1000` cover 37.4% of steps; `≥100` → 7,335 roles / 56.0%; `≥25` → 23,876 /
64.1%; `≥5` → 110,344 / 72.2%; and **2,248,478 singleton roles carry 21.7% of steps**.

This is the sizing lever. Define three tiers and spend compute proportionally:

- **Tier A — space-defining set.** Top **~30,000** roles by humanities person-years
  (≈75% of person-years). Full rich documents, best encoder, all stability sweeps run here.
- **Tier B — projection set.** All **681,454** occupied roles. Rich documents where
  descriptions exist, title-only documents otherwise. Encoded once with the frozen model,
  assigned by nearest micro-centroid. Never influences the geometry.
- **Tier C — step-level refinement set.** Steps belonging to roles flagged polysemous
  (§3.7), which have their own `description`.

Tier A never sees Tier B, so cluster boundaries cannot be dragged around by the long tail —
a real failure mode when 21.7% of steps sit on singleton roles.

### 3.1 Role document assembly (DuckDB, one pass)

Output `archetypes/results/role_docs.parquet`:
`role_canonical, doc_title, doc_desc, n_desc_sampled, n_persons, n_steps, industry_l1_inf,
industry_l1_inf_share, industry_l2_inf, owner_share, employee_share, seniority_mean,
seniority_p10, seniority_p90, n_distinct_titles, doc_has_desc`.

Sources and construction:

- `doc_title` — from `normalized/career_steps.parquet`: `mode(role_display)` plus the
  **top 5 distinct `title_raw` by frequency**, comma-joined. (Do **not** embed
  `role_canonical` itself; it is an alphabetically-sorted, space-stripped token bag —
  `humanmanagerresources`, `customerrepresentativeservice`, `atattorneylaw` — and is not
  readable text. Only `role_display`/`title_raw` are.)
- `doc_desc` — up to **12 sampled `description` values**, each truncated to 300 chars,
  ` | `-joined. Sampling is **stratified by `company_canonical_id` then ordered by
  `hash(linkedin_id)`** so no single employer's boilerplate dominates a role. Filter to
  `length(description) BETWEEN 60 AND 1200` and `NOT is_duplicate`.
  Measured availability by support band (descriptions >40 chars):
  `n_persons≥1000` → 100% of roles have ≥5, mean 2,185/role; `≥100` → 100%, mean 371;
  `≥25` → 99.7%, mean 131; `≥10` → 90.4%, mean 61; `≥5` → 56.7%, mean 32;
  `≥2` → 17.8%, mean 11. **Tier A is fully covered; the tail is not** (§6).
- `industry_l1_inf` — from `industry/results/step_industry.parquet`, modal `l1`
  **excluding `XOT`**, with `industry_l1_inf_share` = share of the role's steps on that
  informative L1. `NULL` when share < 0.20. Same for `l2`.
- `owner_share` / `employee_share` — from `career_steps.employment_type`.
- seniority — from `paths/steps.parquet` (`seniority_ordinal`) and
  `paths/seniority_scores.parquet` (`revealed_pct`), joined on the 4-part step key with the
  pre-collapse `any_value` guard already used in `role_features.py` (the fan-out fix noted in
  `FINDINGS.md` §6 is real and must be kept).

The encoder input is a natural-language template, not a feature dump:

```
Job title: {doc_title}.
Industry: {industry_label or "unspecified"}.
Typical work described by people in this role: {doc_desc}
```

Structured facts that are *categorical and low-cardinality* (industry, employment form)
appear **both** in the template text and as explicit one-hot blocks — the text form lets the
encoder use them semantically, the one-hot form makes the fusion weight controllable.

### 3.2 Encoding

Two **views**, encoded separately so the fusion weight is explicit and a missing view is
representable:

- `V_title` — `doc_title` only, `max_seq_length=64`.
- `V_desc` — full template, `max_seq_length=256`. Zero vector + `doc_has_desc=false` when
  no description exists.

Model: `all-MiniLM-L6-v2` (384-d) for all sweeps because it is already cached and
benchmarked here; a 768-d `bge-base-en-v1.5` / `e5-base-v2` / `gte-base` for the frozen
production run. Encode with `normalize_embeddings=True`. Output
`archetypes/results/role_vectors.parquet` (`role_canonical, v_title[], v_desc[],
doc_has_desc, tier`) plus an embed manifest recording model id, revision hash, seq length,
and batch size.

### 3.3 Fusion — how to concatenate, scale, and weight

Blocks, each L2-normalized **independently** before weighting (otherwise the 384-d text
block silently dominates a 26-d one-hot block by norm alone — this is the concrete answer to
the plan's open `α`):

| block | dim | weight | note |
|---|---|---|---|
| `V_desc` | 384/768 | `w_d = 0.55` | zeroed and mass redistributed when `doc_has_desc=false` |
| `V_title` | 384/768 | `w_t = 0.25` | always present |
| industry one-hot (informative L1 only, +1 "unspecified" slot) | 26 | `w_i = 0.12` | scaled by `industry_l1_inf_share` |
| employment form (employee / self-emp / owner shares) | 3 | `w_e = 0.08` | **soft feature only** — see below |
| seniority | 0 | — | **not a feature**; it is *removed* (§3.4) |

**Soft, not hard.** Structured priors enter as weighted blocks, never as partitions. The
shipped build's hard SOC-prefix crosswalk is exactly what produces the archetype-11 failure:
one dictionary entry (`"19": "legal"`) moves an entire scientific workforce. A soft block
lets industry pull chemists toward a technical neighbourhood without being able to
single-handedly define membership. The **one** structured field I would treat as a hard
constraint is nothing — including `employment_type`, and that is a deliberate reversal of
`ARCHETYPES_PLAN.md` §10.5 (see §3.6).

After concatenation, apply PCA-whitening to 128 dims fit **on Tier A only**, then re-L2-
normalize. Whitening matters because the description block has far higher intrinsic
dimensionality than the one-hots, and unwhitened cosine will otherwise rank roles by
description verbosity.

`w_*` are swept on the held-out-description criterion (§5), not chosen by taste. Fix the
sweep grid in the manifest before running it.

### 3.4 Residualize the seniority axis

Compute a scalar `s` per role (standardized `seniority_mean` from `paths/steps.parquet`,
imputed at the Tier-A median when absent). Regress the whitened matrix `Z` on `s` and
subtract: `Z ← normalize(Z − s ⊗ ((sᵀZ)/(sᵀs)))`.

Why this is load-bearing rather than cosmetic: in my k=15 run on rich role documents, two of
fifteen clusters fractured on **organizational rank rather than function** — one held
`president, officer, partner, operations, marketing, businessdevelopment`, another held
`assistant, boardmember, volunteer, member, secretary, assistantgraduate`. That is the exact
failure `ARCHETYPES_PLAN.md` §5 predicted ("may fracture by seniority/industry rather than
skillset") and it is what produces a 14.4% "Managers" node and a 10.6% "Admin" node that are
really *the same functions at two ranks*. Removing the rank direction is the mechanism that
lets `president` and `assistant` be classified by their work.

### 3.5 Clustering — over-cluster, then merge

Do **not** run flat k=15. I measured flat k=15 seed-stability (mean pairwise ARI over 5
seeds) at **0.657** on title-only vectors and **0.700** on rich vectors — with a worst pair
of 0.515 and 0.633 respectively. A partition that disagrees with itself by a third across
seeds cannot support a published Sankey.

Two-stage instead:

1. **Micro layer.** Spherical k-means (`MiniBatchKMeans` on L2-normalized vectors) with
   **k_micro ∈ [200, 400]** over Tier A, sample-weighted by `n_persons` (this is what makes
   the 2,690 roles covering 50% of person-years actually drive the geometry). Run 20 seeds;
   keep the run with best inertia; record the micro-level co-assignment matrix across seeds
   as the stability substrate.
2. **Macro layer.** Agglomerative clustering (`metric='cosine'`, `linkage='average'`) over
   the **k_micro centroids**, weighted by micro-cluster person mass, producing a full
   dendrogram. Cut at each k ∈ [8, 20].
3. **Cut selection.** Choose k by a pre-registered objective, in priority order:
   (a) mean pairwise ARI ≥ 0.85 across 10 seeds and 10 person-weighted bootstraps;
   (b) no macro cluster > 15% and none < 2% of person-years;
   (c) maximal held-out-description accuracy (§5).
   If no k in [10, 15] clears (a), **report that the data do not support 10–15 stable
   clusters** rather than shipping the prettiest cut.

Why this and not the alternatives, concretely for this data:
- **UMAP+HDBSCAN** — `umap-learn` and `hdbscan` are **not installed** in `.venv`
  (`sklearn.cluster.HDBSCAN` is available via sklearn 1.9.0). More importantly HDBSCAN
  assigns noise, and this project requires ~100% coverage with an honest residual; a
  density method on a long-tailed space will label a large fraction noise and we would be
  right back to a big OTHER. Use UMAP for the 2-D **audit plot only**, never for the
  production geometry (its output is seed-dependent and distorts global distances).
- **NMF / topic models over a role×term matrix** — worth building as a *naming aid*
  (§3.6), not as the partition: soft topic loadings do not give the hard one-state-per-
  person-year the Sankey needs, and a role like `manager` will load on six topics.
- **GMM** — full covariance on 128 dims × 30k roles is fine computationally but the
  spherical-cosine geometry of normalized sentence embeddings is a poor match for Gaussian
  densities, and it adds a second unstable fit.
- **Flat agglomerative on all 30k roles** — O(n²) memory is affordable but it is
  single-linkage-fragile and gives no micro layer to audit or override.

The micro layer is the crucial deliverable beyond the partition itself: it is a **human-
overridable seam**. A reviewer who disagrees that "quality assurance" belongs with a
particular macro node edits one micro→macro row, not a regex, and the change is versioned.

### 3.6 Naming, and demoting "Managers"

Per macro cluster emit a **name card** into `archetypes/results/archetype_cards.json`:
top 25 roles by person-years; top 15 distinct `title_raw`; **c-TF-IDF / weighted log-odds
with an informative Dirichlet prior** over description terms (this is where NMF/c-TF-IDF
earns its place — discriminative terms, not frequent terms); modal informative industry L1
with share; seniority profile *before* residualization; employment-form mix; 10 verbatim
description snippets nearest the centroid; and the 3 nearest sibling macro clusters.

A name is proposed by an LLM **from the card only**, then the card and the name go to the
blind rater test in §5. The card is the artifact of record; the name is a label on it.
Never let the LLM see the previous archetype names — that would relaunder the current
taxonomy.

**Structural recommendation, falling out of §3.4:** drop "Managers & Operations Leaders" as
a *functional* archetype. A manager is not a kind of work, it is a **level of** some kind of
work, and encoding it as a node is what makes the largest node (14.4%) the least legible one
and drives the 86.4% year-over-year stay rate. Ship instead:
`(archetype_id, level_band)` where `level_band ∈ {individual contributor, senior IC,
manager, executive}` derived from `paths/steps.parquet seniority_ordinal` /
`seniority_scores.revealed_pct`. The Sankey then has *fewer, cleaner* nodes and gains a
genuinely interesting second read ("humanities grads enter Comms as ICs and become Comms
managers" is a better story than "they move from Comms to Managers"). Same argument, weaker,
applies to `Founders & Independent Practitioners`: `employment_type` is a **form**, not a
function; make it a facet and test whether a founder node survives on its own coherence.
Both are testable, not asserted — see §5.

### 3.7 Step-level refinement for polysemous roles

This is the part with no analogue in the shipped build, and it is what actually fixes
`president`, `managerproject`, and `owner`.

A role-level document is a **mixture** when the role string is functionally empty. Verbatim
descriptions I pulled for `role_canonical='manager'`:

> "As the Gas Station Manager, I was responsible for … handling cash and finances,
> processing orders, ensuring well-stocked shelves, and overseeing a team of employees."
> · "At Lindsay's Deli, I was a manager focused on employee training, inventory management,
> and financial tracking…" · "Worked in a variety of departments that worked to service
> mortgage loans … Equity Line of Credit, Foreclosure, Loan Accounting, Project Management,
> and Trustee."

and for `role_canonical='owner'`:

> "We handle commercial and residential lawn and maint. care." · "Specialized in prototypical
> construction/design … timber-framing, wooden boat construction and repair, studio
> furniture." · "Commercial, fashion and wedding photographer. Em-Cee and entertainment
> services, Disc-Jockey."

Mean-pooling these into one `owner` vector produces a centroid that describes nobody. So:

1. **Flag polysemy.** For each Tier-A role, embed its sampled descriptions individually and
   compute the mean pairwise cosine (equivalently: the norm of the mean vector). Roles below
   a threshold (calibrate on the Tier-A distribution; expect `president`, `manager`, `owner`,
   `consultant`, `assistant`, `coordinator`, `associate`, `intern`, `director`, `partner`
   to be flagged) get `is_polysemous=true` in `role_archetype.parquet`.
2. **Refine per step.** For steps on a polysemous role **that carry their own description**,
   encode the step description and assign the *step* to its nearest micro-centroid.
   Emit `archetypes/results/step_archetype.parquet`
   (`linkedin_id, source_table, experience_idx, position_idx, archetype_id, micro_id,
   cos, assign_method`).
3. **Person-year resolution order** in the panel build: step-level archetype (if present) →
   role-level archetype → employer-modal archetype (`company_canonical_id`, from the
   non-polysemous steps at that firm, only when the firm has ≥25 such steps) → OTHER.
   `assign_method` records which fired, and the **coverage ledger reports the mix** — the
   plan's §8 rule that no Sankey ships without its denominator is preserved and strengthened.

Concretely on the named failures:
- `managerproject` / `manageroperations` / `managerprogram` (63k / 29k / 26k person-years):
  the title is identical across a construction PM, an agency PM, and a software PM; their
  descriptions are not. Step refinement routes them to construction/ops, comms/marketing,
  and tech/product respectively, and archetype 7 recovers its actual analyst/consultant mass
  instead of being 60%+ managers.
- `president` (125,759 person-years): rank-only token, removed from the seniority axis by
  §3.4, then split per-step into small-business owner / nonprofit executive / corporate
  officer / student-organization president. Steps that still have no functional content fall
  to the employer-modal rule or are explicitly abstained — **not** silently pooled into a
  14.4% node.
- The SOC-19 set (`chemist`, `geologist`, clinical psychologists, `assurancequality`): these
  are not polysemous, so they are fixed at the *role* layer — over-clustering guarantees a
  bench-science/QA micro-cluster exists as a distinct object and it merges by measured
  cosine, with no `"19" → legal` dictionary entry able to override it.

### 3.8 Downstream — unchanged interfaces

`archetypes/yearwise.py` is reused as-is except that the role→archetype join becomes the
resolution chain of §3.7. Deliverables keep their existing names and add two:

- `archetypes/results/role_archetype.parquet` — **existing schema preserved** plus
  `micro_id, is_polysemous, cos, level_band_modal`. Mirror to
  `normalized/mappings/role_archetype.parquet` unchanged in contract.
- `archetypes/results/step_archetype.parquet` — new (§3.7).
- `archetypes/results/person_year_archetype.parquet` — existing columns plus
  `level_band, assign_method, archetype_cos`.
- `archetypes/results/occupancy.parquet`, `state_flows.parquet`, `job_flows.parquet` —
  unchanged shape, now additionally keyed by `level_band`.
- `archetypes/results/archetype_model.json`, `archetype_cards.json`, `_*_manifest.json`.

---

## 4. Compute & runtime

**Hardware verified on this box:** NVIDIA GeForce RTX 5080, **17.09 GB**, compute capability
**(12, 0)**, `torch 2.12.0+cu130`, `torch.cuda.is_available() == True`,
`sentence-transformers 5.5.1`, `scikit-learn 1.9.0`, `scipy 1.17.1`, `networkx 3.6.1`,
`igraph 1.0.0`. **`umap-learn` and standalone `hdbscan` are NOT installed**
(`sklearn.cluster.HDBSCAN` is). Python 3.14.0.

**Measured encoder throughput** (`all-MiniLM-L6-v2`, this GPU, real role documents built
from `career_steps`):

| view | mean chars | max_seq | batch | throughput |
|---|---|---|---|---|
| title-only | 39.9 | 64 | 256 | **12,774 docs/s** |
| title + 8×300-char descriptions | 1,899.1 | 256 | 256 | **1,852 docs/s** |

Derived budget:

| stage | size | cost |
|---|---|---|
| Doc assembly (DuckDB, `career_steps` + `step_industry` + `paths/steps`) | 10.8M steps | 4,000 head roles assembled in ~4 s; full-corpus single pass with `row_number()` partitions: **~5–10 min**, run in support tiers to bound memory |
| Tier A encode, MiniLM, seq 256 | 30,000 | **16 s** |
| Tier B encode, MiniLM, seq 256 | 681,454 | **368 s ≈ 6 min** |
| Tier B encode, 768-d base model (~4–6× slower) | 681,454 | **25–40 min** |
| Entire 2,605,247-role vocabulary, MiniLM | 2.6M | **~23 min** |
| Tier C step-level encode (polysemous steps with own description) | ~1.5M est. | **~13 min** |
| MiniBatchKMeans k=300 × 20 seeds, Tier A (30k × 128) | — | **< 2 min CPU** |
| Agglomerative on 300 centroids × 13 cuts | — | instant |
| Stability sweep 10 seeds × 10 bootstraps × k∈[8,20] | — | **~20–40 min CPU** |
| Nearest-centroid projection of Tier B onto 300 micro-centroids | 681k × 300 | **seconds** (one GEMM, 0.8 GB) |

**Total: well under 2 GPU-hours end to end**, dominated by the stability sweep on CPU. Memory:
Tier B at 384-d float32 = 1.05 GB; at 768-d = 2.1 GB — both fit in RAM, and the GPU only ever
sees one batch. No distributed anything. The support concentration is what makes this cheap:
the expensive, carefully-sampled documents are built for 30k roles, and the other 651k get a
single matrix multiply.

Add `umap-learn` to the `embed` dep group **only** for the audit plot.

---

## 5. Validation plan — falsifiable, and non-circular

The shipped build's headline metrics cannot be reused, because SOC purity validates a
title-derived label against a title-derived code (§1). New criteria, each with a
pre-registered bar:

**V1 — Held-out description transfer (the primary test).** Split each Tier-A role's sampled
descriptions into disjoint halves A and B. Build role vectors and the full clustering from
half A. Independently build a half-B vector per role and assign it by nearest micro-centroid.
Report accuracy and ARI of B-assignment vs A-clustering.
*Bar: ≥0.60 accuracy on a 12–15-class problem (chance ≈0.07).* Below **0.55**, the
description signal is not stable enough to define archetypes and the thesis is dead.

**V2 — Seed and bootstrap stability.** Mean pairwise ARI across 10 seeds and 10
person-weighted bootstrap resamples of Tier A. *Bar: ≥0.85 at the chosen k.* Measured
baselines for the naive alternative: flat k=15 gives **0.657** (title-only) and **0.700**
(rich). If two-stage cannot clear 0.85 at any k ∈ [10,15], report that honestly.

**V3 — External, non-circular labels.** (a) **Informative industry**: hold `industry_l1_inf`
out of the fused vector for a 20% role sample and measure adjusted mutual information between
cluster and held-out industry on the 53.03% of steps with a non-`XOT` L1. (b) **Employer**:
for firms with ≥100 humanities steps, measure whether the firm's archetype mix is
concentrated where it should be (a hospital, a school district, an ad agency). (c) The
**18,918 roles with a curated `occupation_code`** used as a *small gold set* only, never as a
global metric.

**V4 — Blind legibility test (the one the current build has never run).** Three raters get,
shuffled: 15 name cards (exemplar roles + 5 description snippets each, names stripped) and
15 candidate names. Measure name→card matching accuracy and inter-rater agreement.
*Bar: ≥80% correct matching, Fleiss' κ ≥ 0.6.* This is the only real test of "legible to a
lay reader" and it is the classic failure point of unsupervised taxonomies.

**V5 — Beats the shipped build on the product criteria.**
- Node balance: no node > 15% and none < 2% of in-window person-years
  (currently Managers 14.4%, Nonprofit 0.9%).
- Residual: OTHER ≤ 8% of in-window person-years (currently **11.36%** *(given)*).
- **Named-failure regression tests**, run as `archetype_tests.py` cases:
  `managerproject`/`manageroperations`/`managerprogram` no longer co-located with
  analyst/consultant roles at the role layer, and their step-level assignments disperse
  across ≥3 macro nodes; `chemist`, `geologist`, `assurancequality` and clinical-psychology
  roles are **not** in the legal/policy node; `president` disperses across ≥4 macro nodes at
  the step layer.
- Transition sanity (better than raw stay-rate): on `paths/transitions.parquet` restricted to
  pairs where **both** sides have a description, an employer change with semantically similar
  descriptions should *keep* the archetype and a change with dissimilar descriptions should
  *move* it. Report the 2×2. A raw drop in the 86.4% stay rate is **not** by itself evidence
  of improvement — it can just be noise — so this conditional version is the metric.

**V6 — Description-presence bias audit (a gate, not a nice-to-have).** Report description
coverage by `career_year`, `entry_cohort`, seniority decile, current archetype, and
`humanities_field_group`. If coverage varies more than ~2× across cohorts, the fusion must
down-weight `V_desc` or the archetype shares are biased by *who writes descriptions* rather
than *what people do*. See §6.

---

## 6. Honest weaknesses — where this is worse than the shipped decision tree

1. **Description presence is not missing-at-random, and this is the serious one.** The title
   is present on 98.5% of steps with roughly uniform coverage. The description is present on
   **50.9%**, and it is self-reported LinkedIn marketing prose — almost certainly denser for
   more self-promotional, higher-status, more recent, more white-collar profiles. Approach A
   makes the representation *richest exactly where the sample is most selected*, which is a
   new bias the regex build does not have. V6 is a gate for a reason; if it fails, the honest
   move is to down-weight `w_d` and accept a weaker representation.
2. **The measured gain so far is modest, not decisive.** Appending 8 descriptions moved
   ARI-vs-rules from 0.161 → 0.211 and seed stability from 0.657 → 0.700, but it **lowered**
   cosine silhouette from 0.101 → 0.085. And the k=15 rich clustering still produced two
   rank-fractured clusters and 2–3 junk drawers. This proposal is a hypothesis with
   supporting evidence, not a demonstrated win. §5 exists to kill it cheaply.
3. **Auditability is genuinely lost.** `archetype_spec.py` is 300 lines a reviewer can read,
   grep, and patch: one regex edit fixes one mislabel, deterministically, with a unit test.
   A learned space requires a rebuild and a re-audit to move one role, and "why is this role
   here" is answered by a cosine, not a rule. The micro layer mitigates this but does not
   eliminate it.
4. **Reproducibility and dependency weight.** The shipped build is pure DuckDB + regex: no
   GPU, no model download, no seed. Approach A pins a model revision, a seed, a whitening
   fit, and a CUDA stack — and this box is `sm_120`, a new architecture where wheel
   availability has been fragile. A stale model cache silently changes the taxonomy.
5. **The tail degenerates to the status quo for a fifth of the mass.** 19.03% of humanities
   in-window person-years sit on globally singleton roles, and only 17.8% of roles with
   `n_persons ≥ 2` have ≥5 descriptions. For those, the "rich document" is one title and
   maybe one description — i.e. approximately what exists today. Approach A improves the head
   dramatically and the deep tail barely at all, so a headline "we now use descriptions"
   would be overselling.
6. **Temporal mismatch.** A description describes a *job over its whole span*, but the panel
   needs a *person-year* state. A 6-year tenure with one description gives identical evidence
   to career-year 1 and career-year 6, which will artificially *raise* the stay rate — the
   opposite of what §3.7 is trying to fix.
7. **LLM naming can launder incoherence.** A capable model will produce a confident,
   plausible name for a junk cluster. V4 is the mitigation and it is slow and expensive
   (human raters), so there is real pressure to skip it. If V4 is skipped, this approach is
   strictly worse than the hand-written taxonomy, which at least has names chosen by someone
   who understood the domain.
8. **Demoting Managers and Founders is a judgement call I am making, not a measurement.**
   `ARCHETYPES_PLAN.md` §10.5 explicitly decided Founders should be a node. I disagree on
   representational grounds (form ≠ function), but the plan's reasoning — that
   self-employment is a real destination in the possibility-space narrative — is a product
   argument my representational argument does not defeat.

---

## 7. Minimum viable test — 4–6 hours, ~20 min of GPU

Cheapest experiment that confirms or kills the thesis. Nothing here writes to
`archetypes/results/`; all outputs go to `/tmp` or `archetypes/proposals/mvt/`.

**Step 1 (30 min, CPU).** Assemble rich documents for the **top 5,000 roles by humanities
person-years** (covers ≳55% of person-years; the top 2,690 alone cover 50% *(given)*), using
the §3.1 SQL with employer-stratified description sampling. Also emit, per role, its
descriptions split into disjoint halves A/B.

**Step 2 (10 min, GPU).** Encode three views: title-only, description-only, title+description.
Measured cost at 1,852 docs/s → **under 30 s of GPU per view**; the wall time is model load
and I/O.

**Step 3 (1 h) — the decisive test: V1 held-out description transfer.** Cluster on the
half-A vectors via over-cluster(k=200) → ward/average-cosine merge to k=13. Assign the
half-B vectors independently. Report accuracy + ARI.
**Kill criterion: half-B accuracy < 0.55 ⇒ descriptions do not carry stable archetype
information at role level and Approach A should be abandoned in favour of Approach B/C.**

**Step 4 (1 h) — the diagnostic on the three named failures.** For `president`,
`managerproject`, `manageroperations`, `managerprogram`, `owner`, `manager`, `consultant`,
and the SOC-19 set (`chemist`, `geologist`, `assurancequality`, clinical-psychology roles):
sample 2,000 step-level descriptions each, embed, cluster within-role at k=6–10, print
c-TF-IDF top terms and 5 verbatim snippets per within-role cluster, and hand-read them.
**Pass criterion: `president` and `managerproject` split into interpretable, functionally
distinct groups.** If `president`'s 125,759 person-years do **not** split interpretably, the
step-level refinement layer of §3.7 is dead, Managers stays a catch-all under any approach,
and that is itself a publishable finding.

**Step 5 (1 h, CPU).** Stability sweep: 10 seeds × 10 person-weighted bootstraps × k ∈ [8,20],
two-stage vs flat, on the same 5,000 roles. **Pass: two-stage ≥ 0.85 mean pairwise ARI at
some k ∈ [10,15]** (baselines to beat: 0.657 title-only flat, 0.700 rich flat).

**Step 6 (30 min, CPU) — V6 gate.** Description-presence rate by `career_year`,
`entry_cohort`, seniority decile, and current `archetype_id`, from
`person_year_archetype.parquet` joined back to `career_steps`. **Flag if the spread exceeds
2×.**

Decision rule: Steps 3 **and** 4 must pass. Step 5 sets `k`. Step 6 sets `w_d`. If Step 3
passes but Step 4 fails, build the role layer only and keep an honest "unresolvable rank
titles" residual instead of a Managers node. If Step 3 fails, this proposal is wrong and the
shipped decision tree — with its industry and seniority features actually wired in — is the
better investment.
