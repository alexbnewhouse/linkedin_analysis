# Approach B — Archetypes as behavioral equivalence classes in the mobility graph

Alternative to the shipped `archetype_spec.assign_role` decision tree. Every number below was
measured against the repo's own artifacts unless marked *(given by coordinator)*. The minimum-viable
test **was run in full** (§7) — three experiments, 22 seconds of compute total, outputs reproduced
verbatim. It **partly falsified the strong form of this proposal**; §1 and §7.3 state the amended
claim. Nothing outside this file was written or modified.

---

## 1. Thesis

Define archetypes by **stochastic equivalence in the labor-mobility graph**: two roles belong to
the same archetype if the *distribution of places people move to and from* is the same, regardless
of what the titles say or how SOC codes them. Concretely, treat the role→role transition matrix as
a degree-corrected stochastic block model, estimate the blocks by spectral embedding of the fused
in-profile/out-profile matrix, and name the blocks post-hoc from the evidence they aggregate. This
inverts the shipped design — where the role partition is chosen with zero reference to flow and the
flow tensor is then a downstream consequence — and it is the only formulation in which the Sankey's
nodes and its ribbons are estimated from the same object. Critically, the method must be
**stochastic-equivalence** (SBM/spectral), *not* **community detection** (Leiden/Infomap): the
former groups roles with similar flow *profiles* and is not tautological with respect to the
diagonal; the latter groups roles that flow *into each other*, which is tautological — and which,
measured here, degenerates to a single 3,000-node blob on this graph anyway.

**Amended by the MVT (§7), which I ran before writing this.** Pure mobility, at matched k=16, beats
the shipped rule tree on held-out predictive information by a *hair* — 40.0% vs 39.6% retention.
That is a dead heat, not a mandate for replacement. The decisive result is elsewhere: **the two
signals are nearly orthogonal.** Crossing the rule labels with the mobility blocks lifts held-out
retention from 39.6% to **59.5%** (+19.9 pp of ceiling), while a null control that shuffles the
mobility labels *within* rule labels — same cell count — scores **38.8%**, i.e. below rules alone.
The gain is real information, not degrees of freedom. **So the recommendation is not "replace the
decision tree with a block model"; it is "make mobility a first-class axis fused with the
structured/semantic one."** Approach B should ship as the plan's deferred Approach C: mobility
blocks × structured priors, resolved to 10–15 named nodes.

---

## 2. What's broken now that this fixes

### 2a. The role partition is estimated off the time axis and it shows
- Unsupervised cross-check of the shipped labels against KMeans(k=15) on MiniLM role-string
  embeddings: **adjusted Rand 0.16, NMI 0.26** (`archetypes/results/unsupervised_crosscheck.json`).
- The mobility-structure partition I fit in §7 agrees with the shipped rules substantially
  *better* than text does — **ARI 0.238, NMI 0.402** — while surfacing distinctions the rules
  cannot make. That is direct evidence that mobility carries signal the current pipeline discards.
- SOC-major purity mean **0.65**; the deliberately-split majors are incoherent — 11→**0.478**,
  13→**0.392**, 27→**0.465** (`archetypes/results/validation.json`). The split is done by ~15
  ordered regexes whose mutual precedence is the actual model.

### 2b. `OTHER` is a load-bearing Sankey node, which is a presentation failure
- **Six of the top fifteen off-diagonal ribbons touch archetype 0** *(given)*: OTHER→Managers
  18,699; Admin→OTHER 16,871; OTHER→Admin 15,262; Managers→OTHER 14,734. The most visually
  prominent flows in the deliverable are into and out of a residual bucket.
- **159,726 humanities person-years have a NULL `role_canonical`** and are silently `coalesce`d to
  archetype 0 in `yearwise.py` *(given)* — missing data conflated with unclassifiable work.
- Managers is 14.4% and is admitted in `FINDINGS.md` §7 to be a generic-title catch-all. Together
  Managers + OTHER + Admin = **36.5%** of person-years in three buckets, two of which are residuals.

### 2c. The 86.4% diagonal is a **time-axis** artifact, not a partition artifact — verified
This is the single most important measurement in this document, and it partly *disagrees* with the
brief's framing. Decomposing 6,112,837 adjacent humanities in-window person-year pairs with a
non-null role:

| quantity | measured |
|---|---|
| pairs are the **literally identical `role_canonical`** | **80.5%** |
| pairs change archetype (the off-diagonal) | 13.4% |
| pairs that change role at all | 1,189,543 (19.5%) |
| **of those role changes, share that also change archetype** | **68.7%** |

So the diagonal decomposes as `86.6% = 80.5% (same role) + 6.1% (moved, same archetype)`. **No role
partition of any kind can push the lag-1 off-diagonal above 19.5%**, and the shipped one already
captures 13.4 of those 19.5 points. The maximum improvement available to *any* competing partition
at lag 1 is **6.1 percentage points**, and a behavioral-equivalence partition will spend those
points in the wrong direction (§5b).

The diagonal is a function of the *lag*, not the partition:

| lag (career-years) | same `role_canonical` | same archetype |
|---|---|---|
| 1 | 80.5% | 86.6% |
| 2 | 64.7% | 75.6% |
| 3 | 53.4% | 67.6% |
| 5 | 39.2% | 57.0% |
| 10 | 23.0% | 43.9% |
| 14 | 17.0% | 38.5% |

Milestone framing, same data: y1→y5 **58.0%** diagonal (n=505,227); y1→y10 **43.5%** (n=415,289);
y1→y15 **38.5%** (n=311,241). A y1/y3/y5/y10/y15 milestone-column Sankey is *already* a lively
picture with the shipped partition. The reported flattening — diagonal rising 85.4% at year 1 to
89.4% at year 14 *(given)*, and by cohort ≤2004 89.9% down to 2015–19 76.7% *(given)* — tracks role
tenure lengthening with age and with observation window, exactly as expected. **Answer to the
brief's question: the 86.4% diagonal is overwhelmingly the wrong time axis (annual resampling of a
panel in which people mostly hold the same job), not the wrong partition.** Approach B should be
adopted for the reasons in §2a/§2b, not on a promise to thin the diagonal — that promise cannot be
kept and should not be made.

### 2d. The mobility substrate the repo already built is unused, and partly unbuilt
- `transition_network/role_communities.json` contains **no communities**: `{"infomap":
  {"skipped": "grain too large"}, "leiden": {"skipped": "grain too large"}}`. `analyze.py` caps
  community detection at `MAX_NODES_COMMUNITY = 200_000` and the role grain has **1,947,515 nodes**.
  There is no role-level community structure in this repo today.
- `occupation_communities.json` *does* have structure — Infomap **24 modules** (largest 210),
  Leiden **34** (largest 354, 6 singletons), `mean_infomap_soc_purity` **0.574** — i.e. ~43% of the
  revealed structure cuts across SOC. But the occupation grain covers only **7.84%** of the
  6,179,130 spine transitions (`occupation_manifest.json`), so it cannot carry the panel.
- The role grain covers **97.46%** of transitions (`role_manifest.json`) but is brutally sparse:
  **4,053,342 of 4,318,913 non-self edges (93.8%) have `n_persons = 1`**; only 937 edges have
  `n_persons ≥ 100`. Node strengths: 1,059 ≥1000, 7,843 in 100–999, 20,253 in 25–99, 1,802,612 < 10.
- Suppression is specified in the plan and never applied: `state_flows.parquet` has 11,918 cells,
  **1,830 below the stated n≥10 bar** *(given)*.

---

## 3. Pipeline

New package `archetypes/mobility/` (peer modules, `run_mobility.py` driver, `results/`, manifest),
so nothing existing is touched. duckdb + pyarrow + scipy; no pandas in the SQL layer.

**M0 — State alphabet.** `mobility/results/state_alphabet.parquet`
→ `state_key, kind, role_canonical, soc_major, industry_l1, employment_type, n_persons, n_steps`.
Two kinds. `head_role`: `role_canonical` with `n_persons ≥ 25` in `paths/transitions.parquet`
(**29,155 nodes**, measured). `backoff_cell`: everything else collapsed to
`(soc_major, industry_l1, employment_type)` — ~23 × 26 × 3 ≈ 1,800 cells with ~100% coverage
(industry L1 is ~100%-covered per `industry/results/step_industry.parquet`). The backoff alphabet is
what makes the sparsity tractable: a head role's out-profile is dense over 1,800 cells even when it
has almost no head→head edges.

**M1 — Profile matrix.** `mobility/results/state_edges.parquet`
→ `from_state, to_state, n_persons, weight, mean_dwell_months, frac_up, frac_flat, frac_down,
modal_kind`. Built by DuckDB group-by over all 6,179,130 rows of `paths/transitions.parquet`,
**over the full ~2.0M-person population, not the 486k humanities cohort** (see §5b — this is a
tautology defense, not an accident). Rows = head roles; columns = the full alphabet.

**M2 — Features.** `F = [ sqrt(P_out) | sqrt(P_in) ]`, where `P_out` is the row-normalized
out-profile and `P_in` the row-normalized in-profile (from the transpose). Square root is the
variance-stabilizing transform for multinomial profiles — it puts the geometry in Hellinger
distance, so a role with 40 moves and a role with 40,000 are compared on shape, not volume.
Optional third block `α·E` = L2-normalized MiniLM embedding of the role's `role_display` /
`title_raw` text (from `archetypes/results/role_features.parquet`, which already carries
`role_text`, `soc_detail`, `soc_major`, `owner_share`, `n_persons`, `n_steps` — reuse, do not
rebuild). `α = 0` is the pure-mobility arm; `α > 0` the fused arm. **α is chosen by V1, not by
taste.**

**M3 — Spectral embedding.** `scipy.sparse.linalg.svds(F, k=64)`; `X = U·S`; then **row-normalize
`X` to the unit sphere**. Sphere projection is not cosmetic: it is what makes this an estimator for
a *degree-corrected* SBM rather than a plain SBM, by dividing out the per-node degree parameter θᵢ
so k-means recovers blocks instead of size classes (Qin & Rohe 2013; Lyzinski et al. 2014).
Output `mobility/results/state_embedding.parquet` → `state_key, dim_0 … dim_63`.

**M4 — Blocking.** k-means over `X`, person-support-weighted, k swept 10…20.
Then **Karrer–Newman DCSBM local search** to refine: given current blocks, estimate the block flow
matrix Ω̂ and degree corrections, then reassign each state to the block maximizing its Poisson-DCSBM
log-likelihood; iterate ~5 sweeps to convergence. This is ~O(E·k) per sweep in pure numpy — no
`graph-tool` required (it is not installed and is not pip-installable on this env's Python 3.14).
Output `mobility/results/state_block.parquet` → `state_key, block_id, dist_to_centroid,
dcsbm_loglik_margin, block_support`.

**M5 — Naming.** Blocks are named once, by a human, from an evidence card per block: top-20 roles
by person-years rendered as **`role_display` / `title_raw`** (mandatory — `role_canonical` is an
alphabetically-sorted space-stripped token bag, `humanmanagerresources`, `managerproject`, and is
unreadable), SOC-major distribution, modal industry L1, employment-type mix, mean `springrank` from
`transition_network/role_nodes_analyzed.parquet` (revealed seniority, free), and the top-5 in/out
block partners by relative risk. Frozen to `mobility/block_spec.json` with the audit trail. The
labels are *arguments about the data*, and the card is the argument.

**M6 — Tail and cold start.** Three tiers, each logged, never silently merged.
(a) `profile_knn` — tail role with ≥1 transition: assign to `argmax_b Σⱼ nᵢⱼ log Ω̂_bj` (multinomial
posterior under the fitted DCSBM). Uses whatever mobility exists, however thin.
(b) `text_knn` — role with zero transitions or off-graph: MiniLM cosine to the nearest *head role*
(not to a hand-written descriptor), inherit its block.
(c) `unobserved` — **NULL `role_canonical` becomes its own explicit state and is never folded into
a substantive block.** This alone fixes 159,726 person-years currently laundered into OTHER.
Output `mobility/results/role_block.parquet` → `role_canonical, block_id, block_label,
assign_method ∈ {direct, profile_knn, text_knn, unobserved}, profile_support, confidence`.

**M7 — Panel and tensors.** Emit the same shapes `yearwise.py` emits so the viz layer is a drop-in
swap: `person_year_block.parquet`, `occupancy_block.parquet`, `state_flows_block.parquet`,
`job_flows_block.parquet`. Plus two additions that are the actual fix for §2c:
- `milestone_flows.parquet` → `entry_cohort, year_from ∈ {1,3,5,10}, year_to, from_block, to_block,
  n_persons` — the milestone-column Sankey (43.5% diagonal at y1→y10 instead of 86.6%).
- `event_flows.parquet` → flows keyed on **actual job-change events** from `transitions.parquet`
  with `dwell_months` and `gap_months` carried, so a ribbon is "a move" not "a calendar year".
Apply the plan's own `MIN_SUPPORT` n≥10 suppression (1,830 of 11,918 current cells violate it).

---

## 4. Compute and runtime

Graph size after support filtering (all measured, `transition_network/role_nodes.parquet` ×
`role_edges.parquet`):

| node support floor (in+out strength) | nodes | head→head edges | share of non-self move volume | share of humanities person-years |
|---|---|---|---|---|
| ≥5 | 144,903 | — | — | **74.4%** |
| ≥10 | 69,021 | 1,586,534 | 49.8% | 70.7% |
| **≥25** | **29,155** | **1,256,384** | **43.4%** | **66.0%** |
| ≥50 | 16,022 | 1,027,334 | 38.7% | 62.2% |
| ≥100 | 8,902 | 803,793 | 33.8% | 58.0% |
| ≥1000 | 1,059 | — | — | 39.5% |

(95.4% of humanities person-years sit on a role that appears on the graph *at all*; the backoff
alphabet in M0 is what recovers the 26–34% of *move volume* that head→head filtering drops.)

Costs at the recommended ≥25 floor:
- M1 DuckDB aggregation over 6.18M transition rows: **seconds**.
- M3 `svds(k=64)` on a 29,155 × ~31,000 sparse matrix, ~2.5M nnz: **10–30 s**, < 2 GB.
- M4 k-means 29k×64 with k-sweep 10–20: **< 60 s**. DCSBM refinement, 5 sweeps × 1.26M edges:
  **~10 s** numpy.
- M6 profile-kNN over ~650k tail roles: DuckDB join + numpy argmax, **1–2 min**. Text-kNN for the
  ~250k zero-mobility roles: MiniLM on GPU (`torch 2.12.0+cu130` present), **~2 min**; the
  250k×29k similarity is a chunked torch matmul, no FAISS needed.
- M7 panel projection: comparable to today's `yearwise.py`, **minutes**.
- **Total wall clock well under 15 minutes**, single machine, CPU-only except the optional embed.

Empirical anchor: the §7 MVT — DuckDB extraction of a 3,000-node graph, sparse SVD, k-means, Leiden
and Infomap — ran **end to end in 3 seconds**.

Library availability, checked in `.venv` (Python 3.14.0, duckdb 1.5.3):
- **Present**: `scipy 1.17.1`, `numpy 2.4.6`, `scikit-learn 1.9.0`, `python-igraph 1.0.0`,
  `leidenalg 0.12.0`, `infomap 2.11.0`, `networkx 3.6.1`, `pandas 2.3.3`, `torch 2.12.0+cu130`,
  `sentence-transformers 5.5.1`, `pyarrow 24.0.0`. The `graph` and `embed` groups are already
  materialized in the base venv.
- **Absent**: `graph-tool` (the canonical nested-DCSBM/MDL implementation — not pip-installable on
  3.14), `graspologic`, `node2vec`, `gensim`, `hmmlearn`. Consequences, all designed around:
  - DCSBM via scipy spectral + Karrer–Newman local search instead of graph-tool's MCMC. Loses
    automatic k selection by minimum description length; k is chosen by V1 instead.
  - node2vec is **deliberately replaced** by truncated SVD of the PPMI matrix of the random-walk
    profile — Qiu et al. (2018, NetMF) show these optimize the same objective, and the SVD version
    is deterministic, seedless, and needs no new dependency. Recommend skipping node2vec entirely.
  - HMM (latent-state emission model) would need `hmmlearn` (small, pure-Python, easy add) or ~150
    lines of numpy forward-backward. **Deferred, not recommended for v1**: with 80.5% same-role
    persistence the HMM will spend its capacity modeling dwell time, and the Baum-Welch states are
    materially harder to name than block-model blocks. Note it as a Phase-2 option.
  - Optimal-matching / sequence-edit-distance clustering (TraMineR-style) is **rejected on
    complexity grounds**: O(n²) pairwise alignment over 486k sequences is ~10¹¹ alignments, and it
    clusters *whole trajectories*, which is the axis `transition_network/trajectory_features.parquet`
    already occupies (k=8 kmeans, 1,337,321 people). It answers a different question.

---

## 5. Validation plan

### 5a. Falsifiable criteria (pre-register before fitting)

**V1 — Predictive-information retention (primary, and the kill criterion). ALREADY RUN — see §7.2.**
ρ = I(B_t ; R_{t+1}) / I(R_t ; R_{t+1}), where R is the fine-grained head-role alphabet and B the
candidate 10–15-way partition. Estimated as held-out log-likelihood gain over the marginal on a
**20% person-level holdout** (581,632 test pairs), Dirichlet-smoothed. Interpretation: *what
fraction of the one-step predictive information carried by the full role vocabulary survives the
coarse-graining?* This is the formal statement of "behavioral equivalence" — exactly the criterion
for a lumpable Markov abstraction. Measured: **rules k=16 → 39.6%; spectral DCSBM k=16 → 40.0%**.
Passes, but by 0.4 pp. **Revised gate for the production build: ρ_fused ≥ ρ_rules + 5 pp at
k ≤ 16.** Pure mobility does not clear that; the fused arm (§5a V1b) must.

**V1b — Complementarity (the criterion that actually justifies the build). ALREADY RUN — §7.3.**
Held-out retention of the *joint* partition (rule label × mobility block) vs each alone, with a
label-shuffle null control that holds cell count fixed. Measured: rules 39.6%, mobility 39.2%,
**joint 59.5%**, **null control 38.8%**. Require the fused/two-level model to realize ≥ half the
+19.9 pp complementarity gap while staying at ≤ 15 named nodes. This is the number that decides
whether Approach B ships.

**V2 — Out-of-sample block stability.** Fit blocks independently on two disjoint 50% person
samples of the full population. Require **ARI ≥ 0.8** between the two fits (weighted by
person-years). A partition that moves under resampling cannot anchor a narrative.

**V3 — Blind naming.** Three raters see each block's top-20 `role_display` list with no label.
Require ≥2/3 raters to produce semantically equivalent names for **≥12 of 15** blocks. This is the
legibility gate; failing it means the block model wins statistically and loses as a deliverable.

**V4 — Coverage ledger.** Person-year shares by `assign_method`, with `unobserved` broken out.
Require the residual (`text_knn` + `unobserved`) to be smaller than today's **11.5% OTHER**, and
repeat `FINDINGS.md` §5's decomposition to show it is not absorbing white-collar mass.

**V5 — Flow lift, not flow mass.** Report the block flow tensor as `relative_risk` against the
strength-preserving gravity null already used throughout `transition_network`
(`expected = s_out_i · s_in_j / W`). Require **≥10 off-diagonal cells with RR ≥ 2 and n ≥ 500**.
This is what makes off-diagonal ribbons *meaningful* rather than merely *numerous*.

**V6 — Convergent-but-not-identical validity.** Block × SOC-major cross-tab: require mean block
purity in **[0.45, 0.85]**. Purity → 1 means we laboriously rebuilt SOC; purity → 0 means noise.
The occupation-grain Infomap benchmark already in the repo sits at **0.574**, squarely in band.

**V7 — Mandatory diagonal decomposition.** Every reported diagonal must be published as
`diag = same_role_share + (role_changed & same_block)`. Reporting 86% without the 80.5% term is
the error that motivated this whole document.

### 5b. The tautology objection, head-on

*Objection:* "clusters chosen to minimize between-cluster flow will trivially produce a strong
diagonal, so your Sankey proves nothing."

**Rebuttal 1 — the objection is fatal to community detection and I therefore reject community
detection.** Modularity (Leiden) and the map equation (Infomap) are *assortative* objectives: they
explicitly maximize within-block flow, which is literally the diagonal. Using them here would be
circular. A DCSBM is not: it fits a free K×K block-flow matrix Ω with no assortativity prior, so a
block can be defined by *whom it feeds* rather than by internal cohesion. This is stochastic
equivalence, not cohesion, and it is the entire reason for the method choice.

**Rebuttal 2 — measured, on this graph, Leiden degenerates, and it is dominated on both axes.**
Resolution sweep on the 3,000-node head graph (RBConfiguration, `n_persons` weights):

| resolution | k | largest block | share in largest |
|---|---|---|---|
| 0.1 | **1** | 3,000 | 1.00 |
| 0.25 | **1** | 3,000 | 1.00 |
| 0.5 | 5 | 2,065 | 0.69 |
| 1.0 | 10 | 660 | 0.22 |
| 2.0 | 25 | 393 | 0.13 |
| 5.0 | 90 | 141 | 0.05 |
| Infomap (directed) | 57 | 918 | 0.31 |

There is no stable resolution that yields 10–15 balanced communities: 0.5 gives a 69% blob, 1.0
gives 10, 2.0 gives 25. And the res=1.0 partition — the only one in the target range — is **worst on
both metrics simultaneously**: lowest predictive retention (**33.3%** vs rules 39.6%, spectral 39.2%)
*and* highest diagonal (94.8% at lag 1, 67.4% at lag 10 vs spectral 63.1%, rules 58.9%). That is the
tautology signature in its pure form — buying diagonal by destroying information — and it is exactly
what the primary metric is designed to catch. **Community detection is rejected on evidence, not on
principle.**

**Rebuttal 3 — the tautological headroom is bounded, I measured it, and it grows with lag.** Because
80.5% of adjacent person-years are the *same role*, the diagonal is bounded below by 80.5% for every
possible partition. On the head-role subpopulation (like-for-like denominator):

| lag | same role | rules k=16 | spectral k=15 | Leiden res=1 k=10 |
|---|---|---|---|---|
| 1 | 89.5% | 93.0% | **93.9%** (+0.9) | 94.8% (+1.8) |
| 3 | 71.3% | 80.6% | **83.0%** (+2.4) | 85.4% (+4.8) |
| 5 | 59.1% | 72.0% | **75.2%** (+3.2) | 78.5% (+6.5) |
| 10 | 41.7% | 58.9% | **63.1%** (+4.2) | 67.4% (+8.5) |

**This is the strongest form of the objection and I concede it: the tautology penalty is +0.9 pp at
lag 1 but +4.2 pp at lag 10 — it grows precisely at the lag where the milestone Sankey lives.** It
is nonetheless (a) an order of magnitude smaller than the same-role floor that dominates the
diagonal, (b) half the size of Leiden's, and (c) *always reportable*, because V7 mandates publishing
the decomposition. The defensible posture is disclosure with a quantified penalty column in
`FINDINGS.md`, not a claim that the effect is absent. **I am explicitly not claiming this approach
thins the diagonal; it thickens it, and §2c explains why nothing could do otherwise.**

**Rebuttal 4 — the primary metric cannot be gamed by shrinking off-diagonal flow.** V1 measures
information about the *fine-grained role future R_{t+1}*, not about the block's own next state.
Collapsing everything into one block drives the diagonal to 100% and ρ to **exactly 0**. Maximizing
the diagonal and maximizing V1 are opposed objectives, and §7.2 shows the opposition empirically:
across the three partitions, retention and diagonal are *inversely* ordered (Leiden 33.3% / 67.4%
at lag 10; spectral 39.2% / 63.1%; rules 39.6% / 58.9%). A partition cannot buy diagonal without
paying in retention. Report both, always, as a paired figure — and keep Leiden res=1.0 in
`FINDINGS.md` as a permanent negative control.

**Rebuttal 5 — fit on a different population than you render.** Blocks are estimated on the mobility
of the **full ~2.0M-person population** (M1); the Sankey renders the **486k humanities cohort**.
The block structure is therefore not fitted to the sample being described, and the humanities
cohort's flows are an out-of-sample property of the partition. V2 hardens this with a
disjoint-half-sample stability requirement. (Honest cost: this imports non-humanities mobility
structure into a humanities story — see §6.)

**Rebuttal 6 — report lift, not mass.** V5's relative-risk framing means a ribbon is interesting
when it is *over-represented against a size-controlled null*, not when it is thick. This is already
the repo's house convention (`transition_network/README.md`) and it is immune to the objection: RR
is normalized by exactly the strengths that a self-reinforcing partition would inflate.

---

## 6. Honest weaknesses (where this is worse than the shipped decision tree)

0. **On its own, it barely wins — and at k=15 it loses.** Measured (§7.2–7.3): pure-mobility
   retention is **39.2% at k=15 vs the rules' 39.6% at k=16**, and only **40.0% at matched k=16**.
   A 0.4 pp edge on 581,632 held-out pairs does not justify replacing a working pipeline. Anyone
   reading only §1–§4 would over-read the thesis; the honest claim is *complementarity*
   (+19.9 pp joint), not superiority. **If the fused arm fails V1b, this proposal should be
   dropped and the shipped tree kept.**
0b. **The 10–15-node budget is expensive, and mobility pays more for it than the rules do.**
   Retention/k for the block model: k=10 **32.9%**, k=12 36.8%, k=15 39.2%, k=16 40.0%, k=20 42.8%,
   k=25 46.2%, k=30 49.2%. Forcing legibility down to 10 nodes throws away a quarter of the
   partition's predictive power. The rule tree's 16 nodes are fixed by fiat and cannot be traded
   against this curve at all, which is in one sense a weakness and in another an honest simplicity.
1. **Naming is post-hoc and contestable.** The rule tree's labels are true by construction — a role
   is in "Finance & Accounting" because a regex said so. Mine are discovered and must be argued
   for. MVT block B13 groups *customer service representative, assistant manager, photographer,
   server, bartender, pharmacy technician, cashier*. That is behaviorally coherent — a shared
   early-career entry/exit hub — and lexically indefensible to a lay reader. Expect several such.
2. **Cold start is genuinely worse, on a quarter of the mass.** Only 74.4% of humanities
   person-years sit on a role with graph strength ≥5; 4.6% are off the mobility graph entirely
   (401,756 roles with strength 1–4 plus 41,561 off-graph roles account for 1,657,038 person-years).
   Those fall to `text_knn` — i.e. on ~24% of the data this approach *is* the shipped approach with
   extra steps, and it inherits the same ARI-0.16 weakness there.
3. **Stability and diffability.** SVD + k-means has seed, k, and support-floor sensitivity; a rule
   tree is deterministic and its diff is readable in a PR. Every rebuild can silently move roles
   between blocks. V2 measures this but does not eliminate it.
4. **Survivorship in the graph itself.** The mobility graph contains only people who *moved*. High-
   tenure, low-churn roles (tenured faculty, long-serving administrators, sole proprietors) have
   thin profiles and get pulled toward whichever hub they occasionally touch. The rule tree has no
   such bias.
5. **It cannot express a normative category the data don't support.** "Nonprofit, Public Service &
   Advocacy" (0.9% of person-years, SOC purity 0.436) will almost certainly dissolve — mobility says
   nonprofit comms *is* comms. That is probably scientifically right and may be narratively
   unacceptable to the project's stakeholders. The rule tree can simply assert the node.
6. **Recency bias in the substrate.** `transition_network/temporal.py` measures era volumes rising
   21k → 54k moves from 2005–09 to 2020–25. The block structure will be disproportionately fit to
   post-2015 mobility and then applied to 1990s entrants.
7. **The fitting-population trade-off has no free answer.** Fit on the full population (Rebuttal 5)
   and you import non-humanities structure; fit on the humanities cohort and the tautology objection
   sharpens. I recommend the former and disclosing it.
8. **A 2-second regex is replaced by a pipeline.** Operationally this is strictly more machinery to
   maintain for a deliverable whose headline number (§2c) it does not improve.

---

## 7. Minimum viable test — **already run** (22 s total)

### 7.1 — Does a mobility partition exist, and is it legible? (3 s)

`/tmp/apb_mvt.py`, read-only, nothing written to the repo. Recipe: take the top 3,000
`role_canonical` by humanities in-window person-years (**51.8% of person-years**); count distinct
movers on every head→head edge in `paths/transitions.parquet` (**399,692 directed non-self edges,
1,244,398 person-moves, density 0.044**); build `[sqrt(P_out) | sqrt(P_in)]`; `svds(k=48)`;
sphere-normalize; k-means k=15. Compare against the shipped labels and against Leiden on the
identical graph.

**Result 1 — mobility structure agrees with the rules more than text does, and adds structure.**
ARI(spectral, rules) = **0.238**, NMI = **0.402** — against the text-embedding cross-check's ARI
0.16 / NMI 0.26.

**Result 2 — community detection degenerates; stochastic equivalence does not.**
Leiden (RBConfiguration, res=0.25) → **1 community of 3,000 nodes**, ARI 0.000, diagonal 100.0%.

**Result 3 — the diagonal budget, like-for-like** (2,908,989 head-role pairs, same_role 89.5%):
rules **93.0%**, spectral DCSBM **94.0%**, Leiden **100.0%**.

**Result 4 — the blocks are legible with zero title semantics and zero SOC.** Verbatim top roles
per block (`role_canonical` is a sorted token bag; these would be rendered as `role_display` in
production):

| block | n roles | person-yrs | top roles | plausible name |
|---|---|---|---|---|
| B0 | 95 | 104,324 | humanmanagerresources; humanresources; recruiter; generalisthumanresources; recruitertechnical | **HR & Recruiting** |
| B1 | 266 | 379,220 | account; sales; accountmanager; realtor; representativesales; businessdevelopment; agentestatereal | Sales, BD & Real Estate |
| B2 | 241 | 262,034 | scientist; professor; research; assistantprofessor; assistantgraduateresearch; adjunctfaculty | **Academia & Research** |
| B3 | 204 | 282,968 | managerproject; consultant; managerprogram; engineersoftware; analystbusiness; managerproduct | Project/Product/Analysis |
| B4 | 175 | 165,992 | producer; editor; writer; copywriter; reporter; editormanaging | Writing, Editorial & Production |
| B5 | 348 | 344,243 | administrativeassistant; manageroffice; paralegal; coordinatorprogram; assistantlegal | Admin & Coordination |
| B6 | 320 | 356,072 | manager; generalmanager; manageroperations; businessowner; managerstore; supervisor | Operations & Store Management |
| B7 | 44 | 53,711 | attorney; counsel; counselgeneral; clerklaw; corporatecounsel | Legal Practice |
| B8 | 91 | 72,269 | accountant; analystfinancial; financemanager; bookkeeper; controller | Finance & Accounting |
| B9 | 176 | 168,294 | marketing; managermarketing; communications; coordinatormarketing; communicationsspecialist | Marketing & Communications |
| B10 | 133 | 117,626 | nurseregistered; casemanager; psychologistschool; therapist; socialworker | Clinical & Human Services |
| B11 | 119 | 192,523 | designergraphic; creative; designer; designerinterior; artist | Design & Creative |
| B12 | 268 | 496,167 | owner; president; officer; founder; partner; cofounder | Owners & Principals |
| B13 | 311 | 298,398 | customerrepresentativeservice; assistantmanager; photographer; server; bartender; cashier | Frontline Service (see §6.1) |
| B14 | 209 | 202,575 | teacher; instructor; substituteteacher; englishteacher; elementaryschoolteacher | **K-12 Teaching** |

Three distinctions the shipped tree cannot make, recovered here with no lexical input: **HR/
Recruiting** as its own state (currently swallowed by Admin, whose regex includes `human resources|
\bhr\b|recruit`); **K-12 teaching split from academia/research** (currently merged into "Educators
& Academics", with `research` separately routed to "Legal, Policy & Research"); and **Legal
practice split from policy/research**. There is no `OTHER` block — the residual is a coverage
statement (§3 M6), not a Sankey node.

### 7.2 — V1 head-to-head, held out on 20% of people (13 s)

`/tmp/apb_mvt2.py`. 2,909,007 lag-1 pairs, person-level 80/20 split (train 2,324,223 / test
584,784). Ceiling `I(R_t ; R_{t+1})` = **5.61 nats**.

| partition | k | held-out I(Z_t ; R_{t+1}) | retention ρ | diagonal @lag1 | @lag10 |
|---|---|---|---|---|---|
| shipped rules | 16 | 2.2204 | **39.6%** | 93.0% | 58.9% |
| spectral DCSBM | 15 | 2.1968 | 39.2% | 93.9% | 63.1% |
| spectral DCSBM | **16** | 2.2412 | **40.0%** | — | — |
| Leiden res=1.0 | 10 | 1.8641 | 33.3% | 94.8% | 67.4% |

Retention/k curve (spectral): 10→32.9%, 12→36.8%, 15→39.2%, 16→40.0%, 20→42.8%, 25→46.2%,
30→49.2%. **Read honestly: at matched k the block model wins by 0.4 pp. That is a tie.** The V1
gate is passed but not cleared with room; on its own this does not justify the build.

### 7.3 — The complementarity test, with a null control (6 s)

`/tmp/apb_mvt3.py`. Same holdout. Cross the shipped rule label with the mobility block (152
occupied cells), and compare against a control that **shuffles the mobility label within each rule
label** — identical cell count, mobility information destroyed.

| model | cells | retention ρ |
|---|---|---|
| rules alone | 16 | 39.6% |
| mobility alone | 15 | 39.2% |
| **rules × mobility (joint)** | 152 | **59.5%** |
| null control (mobility shuffled within rules) | 152 | **38.8%** |

Adding mobility to the rules is worth **+19.9 pp of ceiling**; adding the rules to mobility is worth
**+20.3 pp**. The null control lands *below* rules alone, so none of the gain is a cell-count
artifact. **Semantic/SOC structure and mobility structure are close to orthogonal predictors of
where a humanities graduate goes next.** This is the result that should drive the decision: not
"replace the tree," but "the tree is using half the available signal."

**Confirmed by the MVT:** the approach is fast (3–13 s at 3,000 nodes), the blocks are legible
without any lexical input, community detection is empirically dominated on both retention and
diagonal, and mobility carries large information the shipped pipeline discards. **Falsified by the
MVT:** the strong form of the thesis — that a mobility-only partition should replace the rule tree.
**Still untested and now the top follow-up:** the fused arm (M2 with α > 0) and the two-level
resolution down to ≤ 15 named nodes — i.e. whether the +19.9 pp complementarity survives the
legibility budget. That is a ~1-day build on the machinery in §3, and V1b is its gate.
