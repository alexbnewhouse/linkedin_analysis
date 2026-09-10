# METHODOLOGY — LinkedIn career-transition network pipeline

> Audience: a technical reader who has **not** seen the code. This document
> explains, stage by stage, what the pipeline does, how, with which inputs and
> outputs, the key decisions and where they live, and the measured results. It
> ends with a critical audit (`## Known issues / risks found during this audit`).
>
> All file references are relative to the repo root `/home/alex/linkedin-analysis`.
> Numbers cited as "measured" were re-derived from the committed Parquet/JSON
> during this audit unless noted; where a committed number disagrees with the
> code or the data, that is called out in the audit section.

---

## 0. What the pipeline produces

Raw LinkedIn profile snapshots (8 JSONL files, ~2M profiles, ~25 GB) are turned
into:

1. a typed **star schema** of the profiles (`parsed/`),
2. an **entity-resolved** career/education dataset (`normalized/`),
3. a temporal + sequenced **edge list** of job-to-job moves (`paths/`),
4. **directed weighted transition networks** at several node grains, with
   null-model normalization, backbone, centrality, communities, revealed
   seniority, and higher-order sequence structure (`transition_network/`).

The scientific object is a **career-transition network**: nodes are career
states (occupation / role / employer / employment-type / seniority), edges are
observed person-level moves between them.

### Pipeline diagram

```
data/*.jsonl  (8 files, ~2.0M profiles)
   │  parse_linkedin.py            (parallel, streaming; ~hours on full data)
   ▼
parsed/        star schema: profiles + 18 child tables, 1 Parquet shard/file
   │  build_normalized.py  +  career_clean/  +  edu_clean/   (~15 min)
   ▼
normalized/    career_steps.parquet (10.80M steps), education.parquet, mappings/
   │  python -m paths.build_spine                            (~18 s, CPU)
   ▼
paths/         steps.parquet (10.80M, typed intervals + fused seniority)
               transitions.parquet (6.02M edges: both endpoints on every axis)
   │  python -m transition_network.build_network <grain>     (<1 s – ~9 s)
   ▼
transition_network/  <axis>_edges.parquet (+ relative_risk, p_transition, z)
                     <axis>_nodes.parquet
   │  python -m transition_network.analyze <grain>           (<1 s – ~100 s)
   ▼               backbone + centrality + SpringRank + communities
   │  python -m paths.seniority   (reads role SpringRank → fused score)
   │  python -m transition_network.sequences  (memory test / motifs / archetypes)
   ▼
career-transition network + sequence analytics
```

### The bootstrap loop (important)

Revealed seniority is **learned from the edges the spine emits**, then **fed
back** to type those same edges, so the spine runs twice:

```
build_spine (pass 1, no seniority_scores yet → NULL revealed scores, untyped)
  → build_network role  +  build_network occupation
  → analyze role  +  analyze occupation        (computes SpringRank per node)
  → paths.seniority                            (fuse → seniority_scores.parquet)
  → build_spine --force (pass 2)               (now emits seniority_score + transition_type)
  → build_network/analyze --force (typed edges) → sequences
```

This circularity is bounded (SpringRank ranks are oriented against an
independent lexical anchor, see §3.4), but it is a circularity and the audit
flags where it can bite.

---

## 1. Stage 1 — `parse_linkedin.py` (raw JSONL → Parquet star schema)

**Purpose.** Flatten one-JSON-object-per-line profiles into typed columnar
tables, losslessly and defensively, so downstream stages never touch raw JSON.

**Input.** `data/*.jsonl` (one profile per line: scalars, a nested
`current_company` object, ~17 one-to-many lists; `experience` is doubly nested
via `positions`).

**Output.** `parsed/` — one directory per table, one Parquet shard per input
file (all shards share a schema, so a table = `read_parquet('parsed/<t>/*.parquet')`).
Plus `parsed/_manifest.json` (per-file counts, errors, timing, table row counts).

| Table | Grain | Key |
|---|---|---|
| `profiles` | one per profile (+ flattened `cc_*` current-company cols) | `linkedin_id` (+ `source_file`, `source_row`) |
| `experience` | one per job | `linkedin_id`, `experience_idx` |
| `positions` | one per role within a job | `linkedin_id`, `experience_idx`, `position_idx` |
| `education`, `certifications`, … (15 more) | one per list element | `linkedin_id`, `idx` |

**Method.** A declarative schema (`Column`, `ListTable` dataclasses,
`parse_linkedin.py:61–90`) is the single source of truth for every column and
its logical type (`str`/`int`/`bool`). One worker **process** per input file
(`ProcessPoolExecutor`), streaming line by line, so memory is bounded
regardless of input size. **Type coercion is defensive**: an unexpected value
becomes `NULL` rather than aborting the run.

**Key data-model fact (load-bearing downstream).** LinkedIn uses a
**grouped-position** model. For a *single-role* experience, `experience.title`
is the job title. For a *multi-role* experience (one with `positions` children),
`experience.title` is the **company name** and the real titles live in
`positions.title`. Stage 2 relies on this to assemble the step grain.

**Measured (`parsed/_manifest.json`).** 2,000,000 profiles; **0 JSON errors**;
82.9 s wall (8 workers). Key table sizes: `experience` 9,076,606; `positions`
2,788,549; `education` 3,577,659; `profiles` 2,000,000. ~48 `linkedin_id` values
repeat across snapshots (rows stay traceable via `source_file`+`source_row`).

---

## 2. Stage 2 — `build_normalized.py` + `career_clean/` + `edu_clean/` (entity resolution)

**Purpose.** Canonicalize the noisy free-text fields of each step so that "the
same thing" collapses (AT&T / AT&T Mobility; "Sr. Software Engineer" / "Senior
Software Engineer") while distinct things stay apart (Citizens Bank vs First
Citizens Bank; "Software Engineer" vs "Senior Software Engineer").

**Inputs.** `parsed/experience`, `parsed/positions`, `parsed/education`.
**Outputs.**
- `normalized/career_steps.parquet` (10,800,787 rows) — the one-row-per-step
  production table that the whole spine consumes.
- `normalized/education.parquet` (3,577,659 rows).
- `normalized/mappings/*.parquet` — the value→canonical maps (each carries
  `method` + `confidence`).
- `normalized/_manifest.json`.

### 2.1 The canonicalizers (`career_clean/`, `edu_clean/`)

Each field is resolved by a **hybrid** whose precedence is "highest-precision
layer that fires wins" (`career_clean/FINDINGS.md`):

```
company:    placeholder bucket → in-data company_id (+ rebrand alias)
            → name→id crosswalk → guarded typo tail → raw
title:      seniority/role parse (level | base) → guarded typo tail → raw
occupation: O*NET-SOC exact/token/de-leveled → uncoded   (separate axis on title)
employment_type: classifier over (company, title)
school/degree/field (edu): in-data URL slug / rules → CIP / fuzzy → raw
```

The benchmarked conclusions (gold pairs, pairwise P/R/F1):

| field | values → canonical | reduction | F1 | reference coverage |
|---|---|---|---|---|
| company | 3,396,043 → 2,974,747 | 0.124 | 1.00 | **69.7% on a company_id** |
| title | 3,507,500 → 2,916,756 | 0.168 | 1.00 | **98.5% parsed** (level\|base) |
| occupation | 3,507,500 → 3,180,449 | 0.093 | 1.00 | **21.9% on a SOC code** |

The standing priors (proven in both `career_clean` and `edu_clean`):
**an in-data reference key beats everything** (company_id, school slug);
**lexical/fuzzy owns typos but cannot expand acronyms** (B recall ~0.33–0.39);
**embeddings are an unsafe autonomous merger** (over-merge sibling orgs and
adjacent seniorities — title precision 0.40 @0.88), usable only as an *anchored,
propose-only* candidate generator behind the id key. Coverage to ~100% is a
**curation + review-queue** problem, not a bigger-model problem.

A cleaned title yields **three orthogonal outputs**: `seniority_level`
(e.g. `chief,executive` — a sorted token *set*), `role_canonical` (the literal
base), and `occupation_code` (O*NET-SOC family). This three-axis split is what
lets the network keep "occupation" and "seniority" separate.

### 2.2 How `career_steps.parquet` is assembled (`build_normalized.py:261–405`)

1. **Step grain (the grouped-position fold).** A `steps` CTE UNIONs:
   - single-role experiences (`experience` rows with **no** `positions` child),
     keyed `source_table='experience'`; plus
   - every `positions` row joined to its parent experience (for company),
     keyed `source_table='position'`.
   The parent join (`exp_parent`) pre-dedupes `experience` to one row per
   `(linkedin_id, experience_idx)` via `any_value` (`build_normalized.py:267–277`).
   `_manifest.json` records `career_steps_rewritten_after_parent_dedupe: true`.
2. **Company id precedence** (`:336–358`): placeholder bucket → `'id:'`+
   (rebrand-aliased) row `company_id` → value-level canonical. So the **row-level**
   `company_id` is used when present (not just the modal id), and placeholders win first.
3. The mapping tables are `LEFT JOIN`ed on the raw value with
   `IS NOT DISTINCT FROM` (NULL-safe). Each mapping `value` is unique, so these
   joins **do not fan out**.

**Data lineage (where each key column comes from):**

| column in `career_steps` | source |
|---|---|
| `company_canonical_id`, `company_id_canonical` | row `company_id` / placeholder / `career_company` map |
| `employment_type` | `career_employment_type` map keyed on `(company, title)` |
| `seniority_level`, `role_canonical` | parsed from `career_title` canonical `title:<level>\|<base>` |
| `occupation_code` | `career_occupation` map (`soc:` prefix stripped) |
| `start_date`, `end_date`, `duration`, `location` | passed through from parsed experience/position |

**Measured (`normalized/_manifest.json`).** 925.3 s wall, 32 threads. The
employment_type mapping is the long pole (558.7 s, 9.34M keys). `career_steps`:
10,800,787 rows.

---

## 3. Stage 3 — `paths/` (the temporal + sequencing spine, Layers 3–5)

**Purpose.** Turn one-row-per-step into (a) steps with **typed time intervals**
and **fused seniority**, and (b) an **edge list** of moves between successive
*primary* steps. Everything is relational DuckDB SQL with all policy in
`paths/common.py`.

**Input.** `normalized/career_steps.parquet`.
**Outputs.** `paths/steps.parquet`, `paths/transitions.parquet`,
`paths/seniority_scores.parquet` (built by `paths/seniority.py`), `paths/_manifest.json`.

### 3.1 Layer 3 — date parsing → typed intervals (`build_spine.py:55–169`)

Raw dates are strings: `"Mon YYYY"` (month precision), `"YYYY"` (year),
`"Present"` (open), or NULL/garbage. The parser emits per step:

- `start_dt`, `end_dt` (DATE), `start_granularity`/`end_granularity`
  (`month`/`year`/`present`), `is_ongoing` (`end_date='Present'`), `datable`.
- **"Present" anchor.** Open intervals close at `SNAPSHOT_DATE = '2025-02-19'`
  (`common.py:35`), the scrape date — **not** "today", so ongoing roles do not
  silently lengthen. The anchor is stored.
- **Year widening.** `"YYYY"` → `[Jan 1 … Dec 31]`, flagged via `*_granularity`
  so overlap math can treat it as imprecise.
- `tenure_months = date_diff('month', start, end) + 1` (a one-month role = 1).
- **Sanity flags** (surfaced, not dropped): `bad_negative_duration` (end<start),
  `bad_future_start` (start>snapshot). A **garbage bound**
  `MAX_STEPS_PER_PROFILE = 100` (`common.py:41`) drops scrape-merge mega-profiles
  (max observed 715) *before* the O(n²) self-join.

### 3.2 Layer 3b — fused per-step `seniority_score` ∈ [0,1] (`build_spine.py:123–146`)

Three independent layers, blended:

- **Layer A (lexical, deterministic backbone).** `seniority_level` is a
  comma-joined sorted token set; collapse to one ordinal = rank of the
  **most-senior named token** via `SENIORITY_RANK` (`common.py:81–96`; intern=0 …
  chief=9). No named token (the empty string, ~7.3M steps, or only company-specific
  `lvlN` bands) → ordinal **NULL** (= unknown). Normalized by `LEX_MAX_RANK=9`.
- **Layer B (cross-occupation status).** O*NET **Job Zone** (1–5) keyed on SOC,
  from `reference/soc_status.parquet`, normalized `job_zone_norm = (zone-1)/4`.
- **Layer C (revealed).** Per-`role_canonical` SpringRank percentile
  (`revealed_pct`) from `paths/seniority_scores.parquet` (see §3.4).

Fusion is a **confidence-weighted mean** (weights `W_LEXICAL=1`, `W_REVEALED=1`,
`W_JOBZONE=0.5`, `common.py:107–109`):

```
            w_A·(ord/9)  +  w_C·conf_C·revealed_pct  +  w_B·job_zone_norm
score  =  ───────────────────────────────────────────────────────────────
                 w_A          +  w_C·conf_C            +  w_B
```

(each term present only if its layer fired; `NULLIF(denominator,0)` → NULL when
no layer fired). A per-step `seniority_confidence` = strongest contributing
layer's base confidence (A 0.75, B 0.6, C 0.5·conf_C) **+ 0.1 per extra agreeing
layer**. Coverage: **93.3% of steps get a score** (re-measured), vs ~16% from
the lexical layer alone.

### 3.3 Layer 4 — concurrency self-join (`build_spine.py:179–210`)

Careers overlap (side gigs, board seats, an LLC). A datable step is flagged
`is_concurrent_secondary` (= `dominated`) when another datable step of the same
person overlaps it by **≥ `CONCURRENCY_OVERLAP_FRAC = 0.5`** of the shorter
interval **and outranks** it. Rank (best first):
`in_workforce > longer dwell > finer date granularity > more senior > earlier
start > lower row_id`. The `row_id` tiebreaker is unique, so no two steps can
mutually dominate. Dominated steps are removed from the *primary timeline* edges
are built along. **Measured:** 2,524,211 secondary steps (~23%).

### 3.4 `paths/seniority.py` — Layer C orient + scale

Reads `transition_network/role_nodes_analyzed.parquet` (`springrank`,
`springrank_support`). Two steps:

1. **ORIENT.** SpringRank's convention puts the *source* of a flow higher, and
   the absolute sign is arbitrary. We negate `springrank`, then correlate it
   against each role's **mean lexical ordinal** (from `steps.parquet`); if the
   correlation is negative we flip. This anchors revealed rank to the
   independent lexical scale (non-circular orientation).
2. **SCALE.** z-normalize → `revealed_z`; convert to a bounded percentile
   `revealed_pct ∈ [0,1]`; `revealed_confidence = clip(support / p90(support), 0, 1)`.

Output `paths/seniority_scores.parquet` (`role_canonical, revealed_pct,
revealed_confidence, revealed_z, support`). **Propose-only** — never overwrites
the deterministic lexical ordinal.

### 3.5 Layer 5 — transition edges (`build_spine.py:218–349`)

The primary timeline = datable, sane (not `bad_*`), not concurrent-secondary,
ordered `(start_dt, end_dt, row_id)` per person. Each consecutive pair → one
edge carrying **both endpoints on every axis** plus:

- **Gap / overlap** from **month-floors** of the two boundaries:
  `delta_months = months(floor(from_end) → floor(to_start))`,
  `gap_months = max(delta−1, 0)`, `overlap_months = max(1−delta, 0)`. So a
  same-month A-ends/B-starts handoff is **neither** gap nor overlap.
  `has_gap` iff `delta−1 ≥ GAP_MONTHS_MIN(1)`; `has_overlap` iff
  `1−delta ≥ OVERLAP_MONTHS_MIN(2)`.
- **`kind`** (legacy ladder, first match wins, `:283–300`): `exit` (to
  retired/unemployed/homemaker) > `education_entry` (to student) >
  `into/out_of_self_employment` > same-employer `promotion`/`demotion`/`lateral`
  (only on lexical ordinal, both sides named) > `move`.
- **`seniority_direction`** (`:275–280`): up/down/flat only when **both** lexical
  ordinals are non-NULL; else `unknown`. (Deliberately blind — refuses to read
  "Senior Engineer → Consultant" as a demotion just because "Consultant" has no
  marker.)

#### The `transition_type` rule ladder (the upgrade, `:306–329`)

Uses `Δsen = to_sen_score − from_sen_score` and `sen_conf = min(from_conf,
to_conf)`. A direction is asserted only when `sen_conf ≥ CONF_MIN(0.3)` AND
`Δsen` clears the threshold. First match wins:

1. `exit` — to ∈ {retired, unemployed, homemaker}. conf 0.95.
2. `education_entry` — to = student. conf 0.95.
3. `into_self_employment` / `out_of_self_employment` — crossing the
   {self_employed, business_owner} axis. conf 0.95.
4. **occupation_change** — both coded AND **SOC major group** (first
   `SOC_MAJOR_LEN=2` digits) differs → `_up` / `_down` (if confident & `Δsen`
   clears τ) else neutral `occupation_change`.
5. **same employer** (`from_company = to_company`, non-placeholder `nonorg:%`) →
   `promotion` / `demotion` (confident `Δsen`) else `lateral`.
6. **different employer** → `employer_move_up` / `_down` (confident `Δsen`) /
   `employer_move_lateral` (confident but flat) / neutral `employer_move`.

`transition_confidence` (`:331–339`): deterministic rules 1–3 → 0.95; directional
labels → `0.5 + 0.5·sen_conf`; everything else → `0.4·sen_conf`.

**Thresholds** (`common.py:122–124`): `TAU_UP = 0.08`, `TAU_DOWN = 0.12`
(asymmetric — demotions require stronger evidence), `CONF_MIN = 0.3`. These were
calibrated by `paths/tune_thresholds.py`, which uses the **lexical layer as
silver truth** on both-lexical edges and measures how often the *independent*
revealed signal agrees: **~62% overall, ~65% for "up", ~50% (near chance) for
"down"** (`common.py:114–119`). That is the honest ceiling of a flow-revealed
directional signal and the author already knows it is weak.

### 3.6 Measured spine results

Re-measured from the committed `paths/transitions.parquet` (6,018,391 edges) and
`steps.parquet`:

- steps 10,798,352; profiles 1,999,961; **frac_datable 0.9925**; frac_ongoing 0.2145.
- bad_negative_duration 165,665; bad_future_start 182,634; secondary steps 2,524,211.
- frac steps with seniority_score **0.933**.
- current `transition_type` distribution (rebuilt with τ=0.08/0.12):

| transition_type | count |
|---|---|
| employer_move_lateral | 1,723,091 |
| employer_move_up | 1,590,738 |
| employer_move_down | 615,493 |
| lateral | 572,527 |
| promotion | 491,024 |
| employer_move | 455,517 |
| into_self_employment | 192,058 |
| demotion | 119,807 |
| out_of_self_employment | 101,867 |
| occupation_change_up | 56,986 |
| occupation_change | 42,906 |
| occupation_change_down | 24,023 |
| exit | 18,198 |
| education_entry | 14,156 |

> **Note:** `paths/_manifest.json` reports a *different* distribution
> (e.g. employer_move_up 1,827,583; employer_move_down 989,202) and
> `transitions_typed_conf_ge_min = 4,390,277 (72.9%)`. The committed parquet
> instead gives conf≥0.3 on 3,950,920 edges (65.6%). The manifest is stale
> relative to the current parquet — see audit HIGH-2.

### 3.7 Tests

`uv run python -m paths.spine_tests` — 13 checks (kind ladder, gap off-by-one,
single-month tenure, concurrency domination, exit-before-self-employment). **All
pass.** `uv run --group graph python -m paths.seniority_tests` — gold role-pair
ordering **7/7**, known ladders (RN→NP +0.472, Cook→Chef +0.291, Police→Detective
+0.077) all "up". **All pass** (it reports 93.3% steps scored, 65.6% edges typed
at conf≥0.3).

---

## 4. Stage 4 — `transition_network/` (build + analyze, Phases 1–5)

### 4.1 `common.py` — axes and SpringRank

**Axis registry** (`common.py:36–45`): `occupation` (`from/to_occupation`,
O*NET-labeled), `role`, `company`, `employment_type`, `seniority`. `SOC_MAJOR`
(`:53–64`) maps 2-digit SOC prefixes to major-group names. `NON_SENIORITY_KINDS`
(exit/education/self-employment) are excluded from the SpringRank graph.

**`springrank(src, dst, weight, n, alpha=1.0)`** (`:72–92`): regularized
SpringRank (De Bacco, Larremore, Moore 2018). Builds adjacency `A`, out/in
strengths `k_out`, `k_in`, and solves the sparse system
`(α·I + diag(k_out+k_in) − (A + Aᵀ)) s = (k_out − k_in)` via BiCGSTAB. α>0
gauge-fixes the otherwise-singular Laplacian. Returns real-valued ranks (source
ranked above by convention; callers orient downstream).

### 4.2 `build_network.py` — Phase 1 aggregate + Phase 2 null model

**Input** `paths/transitions.parquet`; **output** `<axis>_edges.parquet`,
`<axis>_nodes.parquet`, `<axis>_manifest.json`.

**Phase 1 (`:79–120`).** Keep only edges where **both** endpoints are defined on
the axis, aggregate to a directed multigraph: `weight` (count), `n_persons`
(distinct people), `is_self_loop`, mean dwell/gap, `frac_with_gap`,
`frac_up/flat/down`, `modal_kind`, `modal_transition_type`, `mean_delta_sen`,
`mean_transition_confidence`. Node strengths (`node_out`/`node_in`) are computed
on the full aggregate **including self-loops**.

**Phase 2 — null-model normalization (`:146–172`).** A **strength-preserving
(gravity) null**:

```
expected_ij   = s_out_i · s_in_j / W            (W = grand total weight)
relative_risk = weight / expected               (>1 = over-represented vs chance)
p_transition  = weight / s_out_i                (row-normalized incl. self-loops; rows sum to 1)
z             = (weight − expected) / √expected  (Poisson-ish)
```

`relative_risk` is the size-controlled weight (Cheng & Park 2020: large
occupations exchange many workers by sheer size). **Semantics caveat (in the
README and verified):** this is a **job-to-job mobility** network *conditional on
a move occurring* — people who never move produce no edge, so `p_transition` is
`P(next = j | a move from i happened)`, **not** a full Markov chain with stayers.
A self-loop i→i is a real move that changed employer but stayed in the same
occupation.

**Measured per grain:**

| grain | nodes | edges | self-loops | axis coverage |
|---|---|---|---|---|
| occupation | 824 | 39,310 | 727 | **7.84%** of 6.02M edges |
| role | 1,911,042 | 4,280,522 | 66,009 | 97.48% |

Occupation coverage is low **by design**: both endpoints need a deterministic
SOC code and only ~22% of titles get one, so ≈0.22² ≈ 4.8% naive (7.8% observed
because coded titles co-occur). This is the known `career_clean` ceiling, not a
builder gap. `p_transition` rows verified to sum to 1 per source.

### 4.3 `analyze.py` — Phase 3 backbone + centrality + SpringRank, Phase 4 communities

**Phase 3a — disparity-filter backbone (`:45–79`).** Serrano et al.: for a
non-self edge with normalized weight `p = weight/strength` among a node's `k`
links, the edge is significant at level α if `(1−p)^(k−1) < α`. Computed in both
directions (`a_out` using out-strength/out-degree at the source, `a_in` at the
target); `disparity_alpha = min(a_out, a_in)`; `in_backbone = disparity_alpha <
α` (default **α=0.05**). Degree-1 nodes can't be filtered → α=0 (always kept).

**Phase 3b — centrality (igraph, directed/weighted, `:81–98`).** PageRank
(attractors) always; betweenness (inverse-weight distances), HITS hub/authority
only when `n_nodes ≤ MAX_NODES_BETWEENNESS (20,000)`.

**Phase 3c — SpringRank revealed seniority (`:100–110`).** On the
seniority-comparison subgraph (non-self edges whose `modal_kind ∉
NON_SENIORITY_KINDS`), **weighted by `n_persons`**. Output `springrank` (z-scored)
+ `springrank_support = log1p(incident person-volume)`. The `role`-grain ranks
feed `paths/seniority.py`.

**Phase 4 — communities (`:112–127`, only when `n_nodes ≤ 200,000`).**
**Infomap** (directed, flow-based, on raw `weight`) and **Leiden** (modularity,
on the **RR-symmetrized** undirected graph). Cross-tabbed against SOC major
groups via mean per-module purity.

**Measured (occupation, `occupation_analyze_manifest.json`).** 38,583 non-self
edges → **1,495-edge backbone**; Infomap **27 communities** (largest 213, 1
singleton); Leiden 36; **mean Infomap–SOC purity 0.56** (i.e. ~44% of the
revealed structure cuts across the official taxonomy). RR surfaces real ladders
(Firefighter→Supervisor RR 225, EMT→Paramedic 145, Police→Detective 97,
Cook→Chef 76, RN→NP 8.7). Biggest net sink: Chief Executives.

> The `transition_network/README.md` and `CAREER_TRANSITION_NETWORK_PLAN.md`
> claim "21 modules" / purity "0.55"; the committed manifest is 27 / 0.56 — see
> audit LOW-1.

### 4.4 `sequences.py` — Phase 5 higher-order structure

**Input** `paths/transitions.parquet`; **output** `sequences.json`,
`trajectory_features.parquet`.

1. **Memory-order test (`:68–99`).** From per-profile ordered state triples
   `(a,b,c)` (emitted only when all three are non-NULL), an 80/20 train/test
   split; fit order-1 `P(c|b)` and order-2 `P(c|a,b)` with Laplace smoothing
   `ALPHA=0.1`; compare **held-out perplexity** (order-2 backs off to order-1 on
   unseen contexts). Lower order-2 perplexity ⇒ real memory.
   **Measured:** SOC-major perplexity 2.414 → 2.232 (**−7.5%**, real memory);
   employment-type 1.243 → 1.241 (−0.19%, essentially Markovian) — a genuine contrast.
2. **Path motifs (`:102–119`).** Occupation triples ranked by
   `lift = observed / [count(a,b)·P(c|b)]` over the first-order expectation,
   `min_support=30`. Top motifs are **oscillation/return** patterns
   (Programmer→Software Developer→Programmer, lift 7.2) — invisible to one-step
   matrices.
3. **Trajectory archetypes (`:122–182`).** Per-profile structural features
   (n_transitions, employer-move/promotion/demotion/lateral/self-emp counts,
   has_exit, frac_with_gap, mean_dwell, span_months) over profiles with **≥2
   transitions (≥3 steps)**; StandardScaler → **k-means (k=8)**. **Measured:**
   1,337,321 profiles clustered.

---

## 5. Stage 5 — `reference/` (external taxonomies)

Static, public, government/standards lookups; none derived from LinkedIn:

- **O\*NET-SOC 29.1** — `onet_occupation_data.txt` (SOC titles/descriptions, the
  network's node labels and SOC major cross-tab) and `onet_alternate_titles.txt`
  (~55k title→SOC, the `career_clean` occupation backbone).
- **CIP 2020** — `cip_codes.csv` (edu field resolution).
- **Job Zones** — `build_soc_status.py` joins `Job_Zones.txt` with
  `Job_Zone_Reference.txt`, collapses to 6-digit SOC families (preferring the
  `.00` base zone, else the modal family zone), and writes
  `reference/soc_status.parquet` (`soc_code, job_zone, svp_low, svp_high,
  job_zone_norm = (zone−1)/4`). This is seniority **Layer B**.

---

## 6. Consolidated data lineage

| column / metric | produced by | from |
|---|---|---|
| `linkedin_id`, raw `experience`/`positions`/`education` | `parse_linkedin.py` | `data/*.jsonl` |
| `company_canonical_id`, `role_canonical`, `seniority_level`, `occupation_code`, `employment_type` | `build_normalized.py` + `career_clean` | parsed tables + O\*NET / placeholder rules |
| `start_dt`/`end_dt`, granularity, `tenure_months`, `bad_*`, `is_concurrent_secondary` | `paths/build_spine.py` (L3/L4) | `career_steps.parquet` + `common.py` knobs |
| `revealed_pct`, `revealed_confidence` (per role) | `paths/seniority.py` | role-grain `springrank` |
| `job_zone_norm` (per SOC) | `reference/build_soc_status.py` | O\*NET Job Zones |
| `seniority_score`, `seniority_confidence` (per step) | `build_spine.py` (L3b) | Layer A ordinal + C revealed + B job zone |
| `kind`, `seniority_direction`, `transition_type`, `transition_confidence` (per edge) | `build_spine.py` (L5) | step endpoints + `Δsen` + τ/CONF_MIN |
| `relative_risk`, `p_transition`, `z`, strengths | `build_network.py` | aggregated edges + gravity null |
| `pagerank`, `betweenness`, `springrank`, communities, backbone | `analyze.py` | `<axis>_edges/_nodes.parquet` |
| memory test, motifs, archetypes | `sequences.py` | `transitions.parquet` |

---

## Known issues / risks found during this audit

Severity scale: HIGH (affects correctness of a headline result or a widely-used
column), MED (correct-ish but misleading or fragile), LOW (cosmetic / doc drift).

### Pre-known (confirmed, quantified — not the focus)

- **Revealed-seniority direction is weak.** `tune_thresholds.py` against the
  lexical silver truth: ~62% overall agreement, ~65% "up", **~50% "down" (chance)**
  (`common.py:114–119`). Confirmed. Impact below in MED-1.
- **Occupation-axis coverage ≈ 7.8%** (`occupation_manifest.json`, re-derived).
  Confirmed; documented as the SOC-coding ceiling.

### HIGH

**HIGH-1 — Negative `seniority_confidence` (and negative `transition_confidence`).**
`build_spine.py:137–146`. The per-step confidence adds an "agreement bonus"
`0.1·(n_layers_fired − 1)`. When **no** layer fires (seniority_score NULL),
`n_layers_fired = 0` → bonus `−0.1`, and `greatest(...) = 0`, so
`seniority_confidence = −0.1`. **Measured: 653,890 steps have confidence −0.10**
(all where the score is NULL). This propagates into edges: `sen_conf =
min(from,to)` becomes negative, and `transition_confidence = round(0.4·sen_conf,3)
= −0.040` on **104,942 edges** (re-measured). A confidence < 0 is meaningless and
will silently break any `confidence ≥ k` threshold and any confidence-weighted
aggregate (e.g. `mean_transition_confidence` in `build_network`).
*Fix:* clamp — wrap the whole expression in `greatest(0.0, …)`, or only apply the
agreement bonus when `n_layers_fired ≥ 1` (e.g. `0.1·greatest(n_layers−1, 0)`),
and set confidence to NULL/0 when no layer fired.

**HIGH-2 — `paths/_manifest.json` does not match the committed
`transitions.parquet`.** The manifest reports `transition_types` with
employer_move_up 1,827,583 / employer_move_down 989,202 / employer_move_lateral
1,112,537 and `transitions_typed_conf_ge_min 4,390,277 (72.9%)`. The committed
parquet gives 1,590,738 / 615,493 / 1,723,091 and conf≥0.3 on 3,950,920 (65.6%).
The headline "**72.3% of edges typed with a confident direction**" (paths/README,
SENIORITY_TRANSITIONS_PLAN) is from the stale manifest; the current data is
**65.6%**, and "directional" types (the `_up`/`_down`/promotion/demotion set) are
only **48.2%**. The manifest distribution is consistent with the *old* symmetric
τ=0.05/0.05; the parquet was rebuilt with τ=0.08/0.12 but the manifest/READMEs
were not regenerated (the file mtimes are deceptively close). *Fix:* re-run
`build_spine --force` end-to-end and regenerate the manifest + README numbers, or
explicitly stamp which τ each artifact was built with.

**HIGH-3 — "down"/demotion directions rest heavily on a chance-level signal.**
Because revealed "down" agreement is ~50% (HIGH pre-known), and **278,337 of the
615,493 `employer_move_down` edges have *no* lexical token on either side**
(re-measured) — i.e. their direction comes purely from the revealed layer —
roughly half of those ~278k "down" calls are expected to be wrong. The mean
`seniority_score_confidence` on `employer_move_down` is 0.55, so they clear
CONF_MIN and look confident. Any downstream read of "demotion / downward mobility
rate" on the revealed-only mass is unreliable. *Fix:* gate `_down`/`demotion`
labels behind a higher confidence bar than `_up` (the asymmetric τ alone does not
fix a precision problem), surface a separate `direction_source ∈
{lexical, revealed}` flag, and caveat any down-mobility statistic.

### MED

**MED-1 — SpringRank uses raw `n_persons` weights, re-importing the
large-node bias the network elsewhere corrects.** `analyze.py:102–103` weights
the SpringRank edges by `n_persons`, **not** by `relative_risk` (which Phase 2
computed precisely to remove the "big states exchange many workers by size" bias,
Cheng & Park). The plan itself flags this (`SENIORITY_TRANSITIONS_PLAN` §0 note:
"using `n_persons` weight (not RR-gated) makes bare ambiguous tokens noisier").
So the revealed-seniority axis that feeds 93% of step scores is built on the
biased weight. *Fix:* weight by `relative_risk` (or `relative_risk · log
n_persons`), significance-gated, per the plan's own recommendation.

**MED-2 — Disparity-filter `p` denominator includes self-loop strength, but the
filter runs on non-self edges only.** `analyze.py:69–77` computes
`p = weight / str_out`, where `str_out` (from the node table) includes self-loop
weight, yet `e` excludes self-loops. For occupation, self-loops are 285,235 of
471,815 total weight (~60%), so `p` is materially deflated and `(1−p)^(k−1)` is
inflated → the backbone is **more conservative than the textbook disparity
filter** (which normalizes by the strength of the *retained* link set). Not
wrong per se, but it changes the backbone and is undocumented. *Fix:* normalize
by non-self out/in-strength, or document that self-loops are intentionally part
of the strength denominator.

**MED-3 — `relative_risk` is unstable / unbounded for self-loops and tiny
nodes.** `build_network.py:156`. A node whose only activity is a single self-loop
gets `expected = s_out·s_in/W` that can be ≪ 1, so `relative_risk` explodes
(observed max **471,815 = W** on occupation self-loops; mean RR on self-loops
13,219 vs 50.8 on non-self). Leiden clusters on RR (`analyze.py:122`), and
although self-loops are dropped before Leiden, RR is also exposed to users and
used in summaries. *Fix:* report RR with a support floor (e.g. only interpret RR
where `weight ≥ k`), and/or shrink RR toward 1 for low-`expected` edges.

**MED-4 — Year-only intervals can out-rank precise concurrent roles on dwell.**
`build_spine.py:182–185`. A `"YYYY"` role is widened to a full 12 months, so on
the concurrency tiebreaker it can dominate a shorter month-precision role; the
finer-granularity preference only breaks **exact** dwell ties. Documented in
paths/README "Known limitations", but it means the primary-role choice (which
drives every edge) is sometimes decided by a parsing artifact, not real tenure.
*Fix:* compare dwell with a granularity-aware tolerance, or down-weight
year-widened dwell.

**MED-5 — Concurrency below the 0.5 overlap fraction silently becomes a "move"
edge.** `common.py:60` + Layer 5. Two genuinely simultaneous roles overlapping by
<50% of the shorter both stay primary and chain as a succession `move`. 892,268
edges carry `has_overlap` (≥2 months) flagging this, and `--exclude-overlap`
exists, but the **default** network includes them, so a fraction of "moves" are
actually concurrency. *Fix:* document the default clearly in the network manifest
(it is only in the spine README), or default to excluding overlap edges from the
mobility network.

### LOW

**LOW-1 — Doc/number drift in the network READMEs/plans.**
`transition_network/README.md` and `CAREER_TRANSITION_NETWORK_PLAN.md` say
Infomap finds **21 modules** with **purity 0.55**; the committed
`occupation_analyze_manifest.json` says **27** and **0.56**. The "1,495-edge
backbone" and RR ladder table do match. *Fix:* regenerate README numbers from the
manifest (Infomap is seeded `--seed 42`, so the count should be reproducible).

**LOW-2 — `GROUP BY 1, 2, is_self_loop` is redundant.**
`build_network.py:101`. `is_self_loop = (from_node = to_node)` is functionally
determined by the group keys, so grouping by it is harmless but misleading (it
cannot split a group). Cosmetic. *Fix:* drop it from the GROUP BY.

**LOW-3 — `tenure_months` ignores granularity, so year-only dwell is inflated
and `bad_negative_duration` interacts oddly.** `build_spine.py:157–158` computes
inclusive months on the widened interval; a role recorded only as "2005" gets
`tenure_months = 12` regardless of true length. Carried as a known imprecision
(granularity columns exist), but `mean_dwell_months` in the network mixes precise
and year-widened dwell without weighting. *Fix:* expose a precise-only dwell
mean, or weight by granularity.

**LOW-4 — Memory-order "has_memory" is a raw perplexity inequality, not a
significance test.** `sequences.py:98` sets `has_memory = ppl2 < ppl1` with no
confidence interval. Employment-type is reported `has_memory: true` on a 0.19%
reduction — within noise. The README correctly calls it "essentially Markovian",
but the boolean overstates it. *Fix:* bootstrap the perplexity gap or report a CI
and only flag memory above a threshold.

**LOW-5 — Stale `parsed/_manifest.json` workers/timing vs current data layout.**
The parsed manifest records `workers: 8`, `elapsed_s: 82.9` on the snapshot files;
harmless but worth noting that all measured runtimes in the docs are from a
specific machine/run and are not re-validated here.

### Things checked that are CORRECT (to avoid false alarms)

- `p_transition` rows sum to 1 per source (self-loops included) — verified.
- Mapping joins in `build_normalized.py` use unique-keyed value maps and
  `IS NOT DISTINCT FROM`; **no fan-out**, parent experiences pre-deduped.
- Concurrency tiebreaker ends in a unique `row_id`, so no mutual domination
  (a real correctness risk in self-joins) — verified, and `spine_tests` covers it.
- `exit` correctly out-prioritizes `out_of_self_employment` (self_employed →
  retired = exit) — covered by `spine_tests`.
- SpringRank orientation is anchored to an **independent** lexical signal
  (`tune_thresholds` predictor excludes the lexical layer), so the τ calibration
  is non-circular even though the overall seniority loop is a bootstrap.
- Gap/overlap month-floor logic removes the last-day-of-month off-by-one
  (`spine_tests` H1) — verified.
