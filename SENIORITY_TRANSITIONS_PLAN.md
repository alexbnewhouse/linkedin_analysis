# Seniority detection & career-transition typing — research-grounded plan

Goal: replace the brittle, single-signal seniority ordinal and the thin
`kind` ladder in `paths/build_spine.py` with a **layered seniority model** and a
**confidence-scored transition-typing scheme** that can label promotion,
demotion, lateral, employer move, occupation/career change, into/out-of
self-employment, exit, and re-entry — including the **majority of moves that
carry no explicit seniority word**, and **cross-company** comparisons our current
code cannot make.

This is a foundation upgrade for the spine (`paths/`) and the network
(`transition_network/`). It follows this repo's standing philosophy, proven in
`career_clean/` and `transition_network/`: a **high-precision deterministic
backbone**, a **propose-only learned layer**, a **curation ratchet** with a
review queue, and **explicit `method` + `confidence` columns on every output**.

> **Status: the keystone is BUILT.** Layer C (SpringRank revealed seniority on
> the `role`/`occupation` graphs, anchored to the lexical Layer A) and the fused
> per-step `seniority_score` + Δsen `transition_type`/`transition_confidence` are
> implemented in `transition_network/analyze.py` (SpringRank), `paths/seniority.py`
> (fuse), and `paths/build_spine.py` (typing), validated by `paths/seniority_tests.py`.
> Coverage: **seniority on 93.5% of steps** (was ~16%), **72.3% of edges typed
> with a confident direction** (was 15.8%); gold role-pair ordering 7/7; known
> occupation ladders all resolve "up". **Remaining/optional:** Layer B (O*NET Job
> Zone/SVP + ISEI status anchor — Phase 0), `re_entry` look-back rule, gold
> transition-label P/R curve for tuning `τ`, and embedding leveling for the role
> tail (Phase 5). Revealed seniority is propose-only; using `n_persons` weight
> (not RR-gated) makes bare ambiguous tokens noisier — RR-weighting is a tuning knob.

---

## 0. What we have, in numbers (measured on `paths/transitions.parquet`, 6.02M edges)

These distributions are *why* the current system is conservative to the point of
being mostly blind. Measured directly:

| fact | value | consequence |
|---|---|---|
| edges where **both** endpoints carry a named seniority token | **15.8%** | 84% of moves get `seniority_direction='unknown'` |
| edges where **both** endpoints carry a SOC `occupation_code` | **7.8%** | occupation-change typing is near-useless on raw coverage |
| edges that are **same-employer** (`from_company=to_company`) | **20.1%** | promotion/demotion only ever fire on 1/5 of moves |
| `kind` = `move` (different employer, untyped beyond that) | **74.6%** | the dominant outcome carries almost no semantics |
| `kind` = `promotion` / `demotion` | **1.3% / 0.4%** | "honest but blind" — real upward moves are mostly hidden in `move`/`lateral` |
| `seniority_direction` = unknown / flat / up / down | **84.2 / 9.2 / 4.1 / 2.5%** | direction signal is dominated by "unknown" |

The empty-string seniority token alone is ~7.3M steps (`career_clean/FINDINGS.md`,
`paths/common.py` docstring). The current code (correctly) refuses to read
"Senior Engineer → Consultant" as a demotion just because "Consultant" has no
marker — but the cost is that it *also* refuses to see "Analyst → Consultant →
Engagement Manager" as a progression at all. **The fix is not to fake a direction
from the lexical axis; it is to add two more, independent seniority axes that
*do* cover the no-word majority, and to fuse them with calibrated confidence.**

---

## 1. Research synthesis — best practices and gaps

### 1.1 How industry & the literature model seniority

- **LinkedIn Economic Graph.** Titles are standardized to ~15,000 occupations,
  collapsed to ~3,600 "occupation representatives" that group role+specialty
  **regardless of seniority** — i.e. LinkedIn keeps *occupation* and *seniority*
  on separate axes, exactly as our `occupation_code` (SOC) vs `seniority_level`
  split already does. Seniority itself is a small ordinal set (Junior, Mid,
  Senior, Principal, Director, …) extracted by pattern recognition plus
  IC-vs-management linguistic cues.
  ([economicgraph.linkedin.com/workforce-data](https://economicgraph.linkedin.com/workforce-data),
  [LinkedIn Salary engineering](https://engineering.linkedin.com/blog/2018/12/using-economic-graph-data-to-power-the-linkedin-salary-product))
- **O*NET Job Zones & SVP.** O*NET assigns every SOC occupation a **Job Zone
  (1–5)** and an **SVP range** ("Specific Vocational Preparation" — time to reach
  average competence). This is a ready-made, **cross-occupation** preparation/skill
  ladder keyed directly on the SOC codes we already carry. Note: from Feb 2026
  O*NET merges Job Zones 1 & 2 into "1-2".
  ([SVP help](https://www.onetonline.org/help/online/svp),
  [Job Zones help](https://www.onetonline.org/help/online/zones),
  [SVP stratification PDF](https://www.onetcenter.org/dl_files/SVP.pdf))
- **Occupational status / prestige scales.** Sociology's cross-occupation status
  measures: **ISEI** (International Socio-Economic Index, ~16–90, education+income
  optimized) and **SIOPS/Treiman** (prestige, ~12–78). Both are keyed to **ISCO**,
  and an **O*NET-SOC → ISCO crosswalk** exists, so we can attach an ISEI/SIOPS
  score to each SOC.
  ([Ganzeboom ISEI 2010 PDF](http://www.harryganzeboom.nl/pdf/2010%20-%20Ganzeboom%20-%20A%20New%20International%20Socio-Economic%20Index%20ISEI%20of%20occupational%20status%20for%20the%20International%20Standard%20Classification%20of%20Occupation.pdf),
  [SIOPS](https://metadaten.bibb.de/en/classification/detail/12),
  [O*NET-SOC→ISCO crosswalk, IBS](https://ibs.org.pl/app/uploads/2016/04/onetsoc_to_isco_cws_ibs_en1.pdf))
- **Cross-company leveling (the levels.fyi problem).** "Engineering Manager at a
  startup" ≠ "Engineering Manager at Google." levels.fyi's answer is a normalized
  **Skill Index 0–100** that codifies level/scope/responsibility across firms;
  the standing wisdom is that the *same title means different things* by firm,
  size, and industry, so a global title→level map is wrong without context.
  ([levels.fyi career levels](https://www.levels.fyi/blog/what-are-career-levels.html),
  [levels.fyi data guide](https://www.levels.fyi/reports/archive/guides/Levels.fyi%20Compensation%20Data%20Guide.pdf))

### 1.2 How transition *types* are operationalized when wage data is absent

- HR/labor practice defines **promotion = move to a class with more
  complex duties / higher rank**, **lateral = same level, often same grade/pay**,
  **demotion = compulsory reduction in rank**. When wages are unavailable the
  field operationalizes these on **title-rank change + organizational structure
  (span of control)**, not pay. The canonical academic design matches lateral
  movers to non-movers with the *same title in the same org unit*.
  ([UW-Madison HR](https://hr.wisc.edu/hr-guides/for-hr-professionals/change-in-responsibilities-and-title-promotion-lateral-or-demotion/),
  ["Stepping Sideways to Step Up," Mgmt Science](https://pubsonline.informs.org/doi/10.1287/mnsc.2021.03746))
- **Intra-firm promotion vs between-firm upward mobility** are genuinely
  different objects and should be typed differently — firm flow-network studies
  collapse them, but LinkedIn's grouped-position model lets us keep them apart
  (`CAREER_TRANSITION_NETWORK_PLAN.md` §2.4).
- **Career change vs job change.** A *job change* is an employer/title move; a
  *career change* is an **occupation change** (different SOC family / task
  content). Sequence/Markov work (CAREER foundation model; drifting Markov; IT
  career-path sequence clustering) treats trajectories as state sequences and
  conditions on history; higher-order models beat first-order Markov.
  ([CAREER foundation model](https://arxiv.org/html/2202.08370v4),
  [IT career-path sequence clustering, ACM TMIS](https://dl.acm.org/doi/10.1145/3712705))

### 1.3 The hard part — contextual / revealed seniority

The decisive literature for us:

- **Revealed hierarchy from directed flows.** If most flows go A→B and rarely
  B→A, B is "more senior/dominant." This is a solved problem:
  - **SpringRank** (De Bacco, Larremore, Moore 2018, *Sci. Adv.*) — assigns
    **real-valued** ranks minimizing a spring energy over the directed edge list;
    solves a **sparse linear system**, scales to our graph sizes, and provides a
    significance test and edge-direction prediction.
    ([arXiv 1709.09002](https://arxiv.org/abs/1709.09002),
    [LarremoreLab/SpringRank](https://github.com/LarremoreLab/SpringRank))
  - **Minimum-violation / "agony" rankings** (Gupte et al.; "Resolution of
    ranking hierarchies in directed networks," Letizia et al. 2018) — find the
    ordered partition minimizing hierarchy-violating edges; O(m²)/O(m) variants.
    ([agony / hierarchy resolution](https://arxiv.org/pdf/1608.06135),
    ["Tiers for peers"](https://arxiv.org/pdf/1903.02999))
  - **Elo-style** sequential dominance estimation — robust to a changing node set
    and gives uncertainty. ([Elo dominance](https://researchonline.ljmu.ac.uk/3205/3/ANBEH-D-11-00183R1%20cut.pdf))
- **Revealed seniority specifically from careers.** "Extracting Job Title
  Hierarchy from Career Trajectories: A Bayesian Perspective" infers title rank
  from trajectories, quantifying **Difficulty-of-Promotion** as a monotone
  transform of **tenure** (longer tenure before a move ⇒ harder/bigger jump) in a
  Gaussian Bayesian network — i.e. *use dwell time as a seniority-gap signal*.
  A granted patent, **"Machine learning to infer title levels across entities,"**
  is exactly the cross-company leveling task: train title-level embeddings from
  transition data (entities, titles, durations).
  ([Bayesian title hierarchy](https://www.researchgate.net/publication/326206347_Extracting_Job_Title_Hierarchy_from_Career_Trajectories_A_Bayesian_Perspective),
  [infer title levels across entities (patent)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12105720),
  [JAMES multi-aspect title embeddings](https://arxiv.org/pdf/2202.10739))

**This is the single most important finding for us: we already emit the exact
directed edge list these methods consume** (`paths/transitions.parquet`,
`transition_network/*_edges.parquet`), and the network module already runs
graph algorithms over it (`analyze.py`: PageRank, betweenness, Infomap/Leiden).
SpringRank on our *own* role/occupation graphs gives a **data-driven, contextual
seniority ordinal for every node — including the 7.3M empty-string titles** — with
no hand-coded rank map. That is the keystone of this plan.

### 1.4 Gaps we are positioned to fill

1. Published seniority models are either **lexical** (LinkedIn's pattern set) or
   **prestige-anchored** (ISEI/SIOPS) or **revealed** (SpringRank) — *rarely all
   three fused with calibrated confidence.* Our data supports the fusion.
2. Cross-company leveling is proprietary (levels.fyi, the patent). We can
   reproduce its core with **revealed seniority + a company-prestige adjustment**
   learned from our own flows, fully open and auditable.
3. We have **full longitudinal sequences**, so revealed seniority can be learned
   per-person-consistent (A-then-B within one career), which is stronger evidence
   than aggregate cross-sectional flows.

---

## 2. Proposed layered seniority model

Produce, **per resolved node** (and per step), a fused ordinal `seniority_score`
on a common 0–1 scale plus a `seniority_confidence` and a `method` provenance.
Three independent layers, then a calibrated fuse. Each is *propose-only* except
the lexical backbone, which stays deterministic.

### Layer A — within-title lexical level (KEEP, deterministic backbone)

What we have: `SENIORITY_RANK` over the named tokens in `seniority_level`
(`paths/common.py`). Precision-1.0 where it fires (the `career_clean` parser is
F1 1.0 on the title axis). **Do not change its semantics.** Two safe extensions:

- Treat numeric band tokens (`lvlN`) as an **ordinal only within the same
  `(company_canonical_id, role_canonical)`** — they are company-specific and not
  globally comparable, but `lvl1→lvl3` at the *same employer & role* is an
  unambiguous within-ladder promotion. Currently they are dropped to NULL; this
  recovers a clean, high-precision intra-firm signal.
- Add an explicit **IC-vs-management flag** from the token set
  (`manager/head/director/vice/chief` ⇒ management; `staff/principal/senior/lead`
  ambiguous) so the typing scheme can recognize the IC→management track switch
  that LinkedIn models and that pure rank misses.

Coverage: ~16% of edges (both endpoints), precision highest. This is the anchor
the other two layers are *calibrated against*.

### Layer B — cross-occupation status anchor (NEW, deterministic, keyed on SOC)

Attach to each `occupation_code` (SOC) a cross-occupation status value so we can
compare seniority/status **across occupations and across companies** even with no
shared title. **Recommendation: use BOTH, in priority order:**

1. **O*NET Job Zone (1–5) and SVP** — *primary*, because it is keyed **directly
   on O*NET-SOC** (no crosswalk needed; we already ship
   `reference/onet_occupation_data.txt` and use O*NET in `career_clean`), it is
   free/US/maintained, and it is literally a preparation/experience ladder.
   Obtain: O*NET `Job Zones.txt` + `Job Zone Reference.txt` from the O*NET
   database download (same source as our alternate-titles file).
2. **ISEI (and SIOPS as a cross-check)** — *secondary status anchor*, via the
   O*NET-SOC→ISCO crosswalk then ISCO→ISEI/SIOPS. Captures *socioeconomic status*
   that Job Zone (a preparation measure) misses — e.g. it separates high-status
   low-prep roles. Obtain: IBS O*NET-SOC→ISCO crosswalk (.dta) + Ganzeboom
   ISEI/SIOPS-by-ISCO tables.

Store as `reference/soc_status.parquet`:
`soc_code, job_zone, svp_low, svp_high, isco, isei, siops`. Use Job Zone+SVP as
the operational anchor; carry ISEI/SIOPS for validation and as a status-change
signal in occupation-change typing.

Caveats to record: Job Zone/SVP/ISEI describe an **occupation**, not a person's
level within it — a junior and a senior nurse share a SOC and thus a Job Zone.
So Layer B alone **cannot** distinguish within-occupation seniority; its job is
the **cross-occupation** comparison Layer A cannot make. Coverage inherits the
~22% deterministic SOC coverage (the network already lives with this), extensible
via the existing SOC review queue.

### Layer C — revealed seniority from our own directed network (NEW, the keystone)

Run **SpringRank** (primary) on the directed, person-weighted transition graphs
we already emit, to get a real-valued rank per node that needs **no lexical word
and no SOC code** — it works on the empty-string titles. Three graphs:

- **role graph** — nodes = `role_canonical`, edges = `from_role→to_role` counts
  (already aggregatable; `transition_network` has a `role` axis). Gives a
  revealed level for *every* role string, covering the no-seniority-word
  majority. **This is the layer that finally levels "Analyst → Consultant →
  Engagement Manager."**
- **occupation graph** — nodes = SOC; we already built it
  (`transition_network/occupation_edges.parquet`, 824 nodes, 39k edges).
  SpringRank here gives a revealed occupation-status ordinal to cross-check
  against ISEI/Job Zone (Layer B), and to *extend* status to SOCs missing an
  ISEI score.
- **title+seniority graph** — nodes = `seniority_level|role_canonical`, the
  finest grain, for within-employer ladder inference.

Why SpringRank as primary (vs agony / Elo):
- Real-valued ranks (not just ordinal tiers) fuse cleanly with A and B.
- Solves a **sparse linear system** → scales to ~1M-node role graph; GPU-friendly
  (conjugate-gradient on `cupy`/`torch`, see §4 GPU note).
- Built-in **significance test** (vs a null) → directly populates `confidence`.
- Predicts edge direction → a natural **validation** target (§5).
Use **minimum-violation/agony** as a robustness cross-check on the backboned
graph, and **dwell-as-difficulty** (the Bayesian-DOP idea) as a *secondary
weight*: weight each A→B edge by evidence so that long-tenure-then-move and
high-relative-risk edges count more, down-weighting noise and lateral churn.

Critical guards (this is propose-only, learned-from-flows, so it can be
circular):
- Learn ranks on **person-consistent within-career** A→B pairs (we have full
  sequences) and on **relative_risk-significant** edges only (already computed in
  `transition_network`), not raw counts — raw counts re-introduce the
  large-occupation bias (Cheng & Park) the network module already corrects.
- **Anchor/orient** the SpringRank axis using Layer A: regress SpringRank on the
  lexical ordinal where both exist; if correlation is negative, flip; this fixes
  the sign and puts revealed rank on the lexical scale. Nodes where revealed and
  lexical **disagree strongly** are exactly the review-queue items.
- Exclude `exit`/`education_entry`/self-employment-axis edges from the ranking
  graph (they are state changes, not seniority comparisons).

### Fusing A + B + C → one ordinal + confidence

Per node, compute `seniority_score ∈ [0,1]` as a **confidence-weighted average**
of the three z-normalized layers, with provenance:

```
score = (w_A·z_A + w_B·z_B + w_C·z_C) / (w_A + w_B + w_C)
```
- `w_A` high and fixed where a named token exists (deterministic backbone).
- `w_B` = Job-Zone/ISEI availability (0 if SOC uncoded).
- `w_C` = SpringRank significance × log(edge support) for the node.
- `seniority_confidence` = function of how many layers fired and how much they
  **agree** (variance across the three z-scores → low confidence when they
  conflict). `method` records which layers contributed (e.g. `A+C`, `B-only`).

This yields a usable seniority for **~100% of nodes** (Layer C covers the
no-word tail), but with **honest, layer-aware confidence** — the repo's
"precision backbone + propose-only + confidence" pattern, applied to seniority.

---

## 3. Transition-typing scheme

Replace the single `kind` CASE ladder in `build_spine.py` with a typing step that
consumes the fused seniority plus employer / occupation / employment-type / tenure
/ location context and emits **two columns**: `transition_type` (the label) and
`transition_confidence` (0–1), plus a `type_method`/provenance string. Keep the
existing `kind` and `seniority_direction` columns **unchanged for backward
compatibility** — the new columns are additive (this is how the repo evolved
`career_clean` outputs).

**Seniority comparison rule (the cross-company fix).** Define a single helper
`Δsen = to_seniority_score − from_seniority_score`, with a confidence
`min(from_conf, to_conf)`. "Up" iff `Δsen > τ_up`, "down" iff `Δsen < −τ_down`,
else "flat", where `τ` are tuned on gold (§5). Because `seniority_score` is on a
common cross-node scale (Layers B+C), this comparison is **valid across
companies and across occupations** — "Senior Engineer at a 5-person startup vs
Engineer at Google" is decided by their fused scores, not by the literal word.

**Ordered rules** (first match wins; each carries a base confidence, multiplied by
the seniority/coverage confidence where relevant):

1. **exit** — `to_employment_type ∈ {retired, unemployed, homemaker}`. conf 0.95.
2. **re_entry** — *new*: previous edge into an `EXIT_TYPES`/long `has_gap`, then a
   return to a `WORKFORCE_TYPE`. Requires looking one step back (a window the
   spine already orders); emit on the returning edge. conf scaled by gap length.
3. **education_entry** — `to_employment_type = student`. conf 0.95.
4. **into_self_employment / out_of_self_employment** — the existing
   `SELF_EMPLOYED_TYPES` axis, unchanged. conf 0.9.
5. **occupation_change (career change)** — `from_occupation ≠ to_occupation` at the
   **SOC major-group** level (first 2 digits) AND both coded. Sub-type by status:
   if `Δ(ISEI or Job Zone) > 0` → `occupation_change_up`, etc. Distinguishes a
   *career change* from a mere *job change*. conf scaled by SOC coverage
   confidence; uncoded → fall through.
6. **same-employer move** (`from_company = to_company`, non-placeholder):
   - `Δsen > τ_up` → **promotion** (conf = base × Δsen-confidence)
   - `Δsen < −τ_down` → **demotion**
   - `|Δsen| ≤ τ` and same role/occupation → **lateral**
   - `lvlN` within same role advanced → **promotion** (deterministic, conf 0.95)
   - IC→management track switch with `Δsen ≥ 0` → **promotion** (management track)
7. **employer move (between-firm)** (`from_company ≠ to_company`):
   - `Δsen > τ_up` (confident) → **employer_move_up** (between-firm upward mobility)
   - `Δsen < −τ_down` → **employer_move_down**
   - else → **employer_move_lateral**
   - This is the key new capability: the 74.6% `move` bucket gets a **direction**
     whenever the fused seniority is confident, and stays a neutral
     `employer_move` (not silently up/down) when it is not.
8. **fallback** — `move` (different employer, seniority unknown) /
   `lateral` (same employer, seniority unknown). Mirrors today's honesty: never
   manufacture a direction without confidence.

**How it handles the three hard cases the red-team raised:**

- *No-seniority-word majority:* Layer C gives every role a revealed score, so
  rules 6–7 fire with `transition_confidence` set by SpringRank significance,
  rather than collapsing to "unknown." We surface the confidence instead of
  hiding the move.
- *Cross-company comparison:* `Δsen` on the common B+C scale, not the lexical
  word — explicitly designed for between-firm leveling.
- *Occupation change:* rule 5 uses SOC major-group + status delta, separating
  career change from job change, which the current code cannot express at all.

**Confidence is first-class.** Every typed edge carries `transition_confidence`;
downstream (the network module, any analysis) can threshold. High-confidence
deterministic labels (exit, self-employment axis, lvlN promotions, lexical
up/down) sit at the top; revealed-seniority directions are mid-confidence
"propose" labels; conflicts feed the review queue.

---

## 4. Integration with the existing pipeline

### Spine (`paths/`)

- **`paths/common.py`** — keep `SENIORITY_RANK`. Add: `SOC_STATUS_PATH`
  (`reference/soc_status.parquet`), `SENIORITY_SCORES_PATH`
  (`paths/seniority_scores.parquet`, the fused per-node table), and the typing
  thresholds `TAU_UP`, `TAU_DOWN`, `SOC_MAJOR_LEN=2`, plus a `RE_ENTRY` policy
  knob. These are new "open decisions" in one auditable place, same as the
  existing knobs.
- **New module `paths/seniority.py`** — builds `seniority_scores.parquet`
  (node → `seniority_score, seniority_confidence, method, z_A, z_B, z_C,
  is_management`). Layer A from the token set; Layer B by joining
  `reference/soc_status.parquet`; Layer C by reading
  `transition_network/role_edges.parquet` / `occupation_edges.parquet` and
  running SpringRank. This module is **propose-only** for B/C — it writes scores
  and confidences; it does not overwrite the deterministic Layer-A ordinal.
- **`paths/build_spine.py`** — Layer 3b joins `seniority_scores` onto each step
  (adds `seniority_score`, `seniority_confidence`, `is_management`). Layer 5 adds
  `Δsen`, `transition_type`, `transition_confidence`, `type_method` columns
  **alongside** the existing `kind`/`seniority_direction` (additive, no breakage).
  The SQL stays deterministic; the only new inputs are the two reference/score
  parquets, mirroring how `occupation_code` already enters from `career_clean`.

### Network (`transition_network/`)

- `analyze.py` already computes graph algorithms; **add SpringRank there** as
  another node metric (`springrank`, `springrank_significance`) on each axis —
  it is the natural home (it already builds the igraph/edge structures and emits
  `*_nodes_analyzed.parquet`). `paths/seniority.py` then reads those columns
  rather than re-implementing SpringRank.
- The network's `relative_risk` and `n_persons` become the **edge weights** for
  the SpringRank graph (significance-aware, person-counted), reusing Phase-2
  null-model work and avoiding the large-node bias.
- New typed edges enrich every grain's `modal_kind`/`frac_up/down` — the network
  immediately gains direction on the previously-untyped 74.6% `move` mass.

### What stays deterministic vs propose-only

| component | mode |
|---|---|
| Layer A lexical ordinal, `lvlN`-within-ladder, IC/mgmt flag | **deterministic** |
| Layer B Job-Zone/SVP/ISEI join | **deterministic** (reference data) |
| Layer C SpringRank scores | **propose-only** (carry significance) |
| Fused `seniority_score` | deterministic *formula*, propose-only *inputs* |
| Rules 1–4 (exit, re-entry, edu, self-emp) | **deterministic** |
| Rules 5–7 directional labels | deterministic rule over a propose-only score → **confidence-scored** |

### GPU

Per repo convention, aggregation/typing stay on DuckDB/CPU (seconds). GPU pays
off in **Layer C at scale**: SpringRank is a sparse linear solve — run it with
`cupy`/`torch` conjugate gradient on the ~1M-node **role** graph (the occupation
graph at 824 nodes is trivially CPU). Embedding-based leveling (JAMES/Job2Vec
style) is an *optional* later propose-only layer for the role tail, on `torch`
GPU — never an autonomous decider (the `career_clean` embedding prior:
embeddings propose, they don't decide; they over-merge adjacent seniorities).

---

## 5. Validation & benchmarking (repo-consistent)

New `paths/seniority_tests.py` and additions to `paths/spine_tests.py`
(mirroring the existing `*_tests.py` and `career_clean/gold.py` pattern):

1. **Gold seniority pairs** — hand-label ~60 ordered role pairs that humans agree
   on (`Analyst < Senior Analyst < Manager < Director`;
   `Engineer < Staff Engineer`; cross-occupation `Cook < Chef`, `EMT < Paramedic`
   — several already validated as high-RR edges in
   `transition_network/README.md`). Metric: does `seniority_score` order each
   pair correctly? Report **pairwise accuracy** per layer and fused, and the
   share where the fused layer **beats** Layer-A-only (the whole point: coverage
   gain without precision loss).
2. **Gold transition labels** — ~80 labeled edges (employer move up/down/lateral,
   promotion, demotion, occupation change, re-entry), drawn from observed edges,
   stressing the no-word and cross-company cases. Metric: **precision/recall/F1**
   of `transition_type`, plus a precision-at-confidence-threshold curve (so we can
   pick `τ` and a confidence cutoff that hits a target precision, the
   `career_clean` calibration method).
3. **Internal consistency checks** (no labels needed): SpringRank should predict
   held-out edge directions better than chance (the method's own validation);
   fused score should correlate positively with ISEI/Job Zone where both exist;
   known ladders (RN→NP, Police→Detective from the network README) must come out
   "up." Regression-style asserts like `normalization_regression_checks.py`.
4. **Coverage report** in the manifest: % of edges now typed with confidence ≥ k,
   vs the current 15.8%/7.8% — the headline improvement.

Target: keep deterministic-rule precision ≥ 0.95 on gold; the revealed layer is
acceptable at lower precision *as long as its confidence is calibrated* (the
review queue absorbs the rest), exactly as the SOC anchored-embedding layer is
treated in `career_clean`.

---

## 6. Phased build steps

- **Phase 0 — reference data.** Build `reference/soc_status.parquet` (Job
  Zone/SVP from O*NET download; ISEI/SIOPS via the IBS SOC→ISCO crosswalk).
  Cheap, deterministic, unblocks Layer B. *Deliverable: the parquet + a coverage
  note.*
- **Phase 1 — role edge axis + SpringRank in `analyze.py`.** Ensure a
  `role` and `title_seniority` grain edge list exists
  (`transition_network/build_network.py role`), add SpringRank to `analyze.py`,
  emit `springrank`/significance on `*_nodes_analyzed.parquet`. *Deliverable:
  revealed ranks for occupation (validate against the README's known ladders) and
  role.*
- **Phase 2 — `paths/seniority.py` fuse.** Compute Layers A/B/C → fused
  `seniority_scores.parquet` with confidence + method; anchor C's sign to A.
  *Deliverable: per-node seniority with ~100% coverage and honest confidence.*
- **Phase 3 — typing in `build_spine.py`.** Add `Δsen`, `transition_type`,
  `transition_confidence` columns (additive). Re-run the spine (~17s).
  *Deliverable: every edge typed with confidence; coverage report vs the 15.8%
  baseline.*
- **Phase 4 — gold + tests.** `paths/seniority_tests.py`, gold sets, calibration
  curves, regression asserts. *Deliverable: P/R/F1 + the precision-at-threshold
  table; tuned `τ`.*
- **Phase 5 (optional, propose-only) — embedding leveling for the role tail**
  (JAMES/Job2Vec-style, GPU `torch`) to extend revealed seniority to low-support
  role nodes SpringRank cannot rank reliably; feeds the review queue only.

### Open decisions to confirm

1. **Job Zone vs ISEI as the *primary* Layer-B anchor** (recommend Job Zone/SVP —
   no crosswalk, keyed on SOC, maintained — with ISEI as cross-check).
2. **SpringRank edge weight** — **RESOLVED: `n_persons`.** A head-to-head eval
   (`transition_network/REVEALED_SENIORITY_COMPARISON.md`) tested `relative_risk`,
   `relative_risk × log n_persons`, trophic levels, agony/min-violation, and
   David's Score against the SpringRank-on-`n_persons` baseline on both the
   role and occupation graphs. None beat it: RR-weighting *lowers* down-precision
   and badly hurts the independent job-zone anchor (ρ 0.43→0.19); trophic/agony
   tie it (same Laplacian family) but add nothing; David's Score is worst. Weak
   `down` (~0.47) is intrinsic to the up-skewed flow asymmetry, not a weighting
   artifact — manage it via τ, not the weight.
3. **`τ_up`/`τ_down` and the confidence cutoff** — set on the gold P-at-threshold
   curve.
4. **SOC granularity for "occupation change"** — major group (2-digit) vs broad
   (recommend 2-digit to avoid calling every specialty shift a career change).
5. **re_entry definition** — gap length + employment-type rule; needs the look-back
   window in Layer 5.
6. **Whether to roll SpringRank into the within-career (person-consistent) graph
   or the aggregate flow graph** (recommend person-consistent pairs as the weight,
   aggregate graph as the structure).

---

## 7. Recommendation — build this first

**Build Layer C (revealed seniority via SpringRank) on the role and occupation
graphs we already have, anchored to the existing Layer-A lexical ordinal, and
wire a single fused `seniority_score` + `transition_confidence` into the spine.**

Rationale, tied to our data:
- It is the **only** layer that covers the **84% of edges and 7.3M empty-string
  titles** that today get `unknown`. Layers A and B together still can't type the
  no-word, cross-company majority; Layer C is the unlock.
- The **infrastructure already exists**: the directed, null-normalized edge list
  (`transition_network/*_edges.parquet`) and a graph-analysis module
  (`analyze.py` with PageRank/Infomap/Leiden) — SpringRank is one more sparse
  solve in the same place, and the network README already shows the revealed
  ladders we expect it to recover (RN→NP, EMT→Paramedic, Police→Detective).
- It is **scalable and GPU-friendly** (sparse linear system), **self-validating**
  (edge-direction prediction), and fits the repo's **propose-only + confidence +
  review-queue** philosophy exactly.
- Anchoring C to A keeps the deterministic precision backbone intact while
  multiplying coverage — the same "high-precision backbone + propose-only
  extension" trade that already won for company, title, and occupation in
  `career_clean`.

Phase 0 (the Job Zone/ISEI reference) is cheap and can run in parallel, but the
**decisive, differentiating capability is SpringRank-from-our-own-network**, and
it should be the first thing built.
