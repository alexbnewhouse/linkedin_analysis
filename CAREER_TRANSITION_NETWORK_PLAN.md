# Career transition network analysis — research-grounded plan

Goal: build and analyze a **career transition network** — a directed, weighted
graph whose **nodes are career states** (occupation, title+seniority, employer,
industry, region, or employment-type) and whose **edges are observed
person-level moves between states**, then mine it with the standard
network-science toolkit (flows, centrality, community detection, null-model
filtering) to answer questions traditional occupation classifications cannot:
*which states are bridges vs traps, what are the empirically revealed labor-market
segments, and what moves are over-/under-represented relative to chance.*

This is **distinct from `CAREER_PATHS_PLAN.md`**. That document is about
*rendering* paths (timelines, Sankey/alluvial flows for a person or cohort). This
document is about the *network object and its statistics*. The two share a spine:
the transition network is literally the **aggregated edge table** that
`CAREER_PATHS_PLAN` Layers 3–5 (temporal model → per-profile sequencing →
transitions) produce. **Build that spine once; this plan consumes it.**

Everything rests on the resolved axes already shipped in `career_clean/`
(see `career_clean/FINDINGS.md`) and materialized in
`normalized/career_steps.parquet` (10.8M steps, ~2M profiles):
`role_canonical` + `seniority_level`, `occupation_code` (O*NET-SOC),
`company_canonical_id`, `employment_type`. Industry and geography are **not yet
resolved** (`CAREER_PATHS_PLAN` Layer 6) and gate the corresponding network grains.

---

## 1. What the literature establishes (best practices)

Career/labor transition networks are a mature subfield. The dominant designs:

**A. Occupational mobility networks** (del Rio-Chanona, Mealy, Lafond, Farmer
2021, *J. R. Soc. Interface*; Mealy et al. 2018). Nodes = occupations (they use
464 four-digit ACS codes), edges = empirical job-to-job transition probabilities
from a labor survey (IPUMS-CPS). The adjacency matrix is **row-normalized to
transition probabilities with explicit self-loops** (`A_ii = r`, `A_ij =
(1−r)·P_ij`), so "stay" is a first-class outcome and rows sum to 1. Key finding:
mobility is **far more restricted** than standard frictionless models assume —
network structure alone changes who is harmed by an automation shock.

**B. Inter-firm labor flow networks** (Guerrero & Axtell 2013, *PLOS ONE*; Park
et al. 2019, *EPJ Data Science*). Nodes = firms, edge = a worker migrated between
them (possibly via an unemployment spell). Findings: **in/out flows are nearly
balanced per firm**, the network's connectivity predicts the skewed firm-size
distribution, <10% of firms drive ~90% of employment growth, and a firm's
**network vicinity predicts its growth and its workers' unemployment risk**. Best
practice here: validate the network by showing its structure *predicts an external
outcome* (growth, retention).

**C. Sociological "flows and boundaries"** (Cheng & Park 2020, *AJS*; Park 2020).
The central methodological warning: **large occupations exchange many workers by
sheer size**, so raw counts are misleading. Normalize edges by a **null
expectation** — *relative risk* / observed-over-expected (the MONECA "Mobility
Network Clustering Algorithm" uses relative risk; configuration-model expectation
is the network-science equivalent). Then **flow-based community detection**
(modularity / stochastic block models / Infomap) reveals **labor-market segments
that cut across official industry and occupation codes** — segmentation those
classifications miss entirely.

**D. Skill-space / "Skillscape"** (Alabdulkareem et al. 2018, *Science
Advances*). A complementary network where relatedness comes from **shared skill
requirements**, not observed flows. Skills polarize into socio-cognitive vs
sensory-physical clusters; the topology **constrains** mobility (low-skill workers
get "stuck"). Best practice: combine **revealed** mobility (what people did) with
**latent** relatedness (skill/task overlap) — they explain different things, and
their disagreement is itself informative.

**E. Representation-learning layer** (Job2Vec, Zhang et al. 2019; AHEAD; resume
representation learning, 2023). Embed nodes from the transition graph
(graph-topology + transition-balance + duration views) for **next-move
prediction** and title benchmarking. Useful as a *predictive* and *candidate-
generation* layer on top of the descriptive network — consistent with this repo's
established prior (embeddings propose, they don't autonomously decide).

**Cross-cutting best practices distilled:**

1. **Normalize edges against a null model** (relative risk / configuration model)
   before interpreting or clustering — never cluster raw transition counts.
2. **Keep self-loops explicit** and row-normalize to probabilities; "stayers"
   are signal, not noise.
3. **Directed and weighted**; asymmetry (A→B ≫ B→A) is a core finding, not an
   artifact to symmetrize away.
4. **Backbone/significance-filter** the dense long tail (disparity filter, or
   keep only edges significant vs the null) before community detection and viz.
5. **Validate against an external outcome** (wage change, growth, retention,
   tenure) so the network isn't just a pretty picture.
6. **Report representativeness explicitly** and, where possible, reweight.

---

## 2. Gaps in the literature we are positioned to address

Most landmark studies above run on **survey or administrative data** (CPS,
Finnish/Mexican registers) that is representative but **coarse, cross-sectional in
flow, and small in occupational resolution** (hundreds of occupations, aggregate
year-to-year flows). Our data is the opposite: **individual longitudinal
sequences at massive scale and fine resolution.** That asymmetry is the
opportunity.

1. **Full sequences, not just one-step aggregate flows.** CPS-style data gives a
   transition matrix; we have each person's *ordered multi-step trajectory*. We
   can study **higher-order / non-Markovian** structure (does step *n* depend on
   steps *n−1, n−2*?), path motifs, and trajectory clustering — which one-step
   matrices cannot.
2. **Multi-grain, swappable node definition on one substrate.** Same 10.8M-step
   spine, networks at occupation / title+seniority / employer / industry / region
   / employment-type, and **cross-axis** edges (e.g. finance→tech *and*
   IC→manager simultaneously). Few studies hold the substrate fixed and vary the
   node grain.
3. **Self-employment / freelance as a first-class state.** `career_clean`'s
   `employment_type` axis (the `SELF_EMPLOYED_PLAN` work) makes
   "left BigCo → went independent" and the **return** edge measurable — usually
   invisible in payroll/employer-based register data.
4. **Intra-firm promotion edges.** LinkedIn's grouped-position model encodes
   *within-company* role progressions explicitly (positions children). We can
   separate **promotion** edges from **employer-move** edges — a distinction
   firm-level flow networks collapse.
5. **Bias as a studied variable, not just a caveat.** LinkedIn skews
   white-collar, English-speaking, recently-active, and over-represents job-movers
   (IZA DP 17896; UNDP). The literature treats this as a limitation; we can
   **quantify and partially correct** it (post-stratify against BLS/ILO marginals
   on occupation×region; compare mover-heavy vs full-tenure cohorts) and report
   sensitivity.
6. **Temporal dynamics.** Most mobility networks are static. With dates (Layer 3)
   we can build **time-sliced networks** and test how segments and bridge-roles
   shift across cohorts/eras (e.g. pre/post a tech hiring boom).

These are the publishable/decision-useful angles. They also dictate the build
order below.

---

## 3. Prerequisites (the shared spine) — BUILT

The transition network **cannot be built without** these. **Done** in `paths/`
(`paths/build_spine.py`, ~17s CPU on the full 10.8M steps; see `paths/README.md`):
`steps.parquet` (10,798,352 steps, 99.25% datable) and `transitions.parquet`
(6,018,391 edges, each carrying both endpoints on every axis + `kind`, dwell,
gap/overlap, seniority direction). Phases 1-2 of the network are also built in
`transition_network/`. The three spine layers it implements:

- **L3 Temporal model.** Parse `start_date`/`end_date` strings → typed intervals
  with granularity + `is_ongoing`, close "Present" at the explicit snapshot
  anchor (~Feb 2025). 87.4% of steps are datable; 12.6% are not.
- **L4 Per-profile sequencing.** Order steps; resolve **concurrency** (281k
  profiles have ≥2 concurrent current roles) by a documented **primary-role
  policy**; fold grouped-position promotion chains.
- **L5 Edge emission.** For each person, successive primary states → a transition
  row: `(from_state, to_state, axis, kind∈{promotion,lateral,move,
  into/out-of-self-employment,exit,gap}, dwell_time, gap_length,
  seniority_direction, t_start)`.

If `CAREER_PATHS_PLAN` Phase A→C is already underway, **this plan starts at §4**.
If not, those three phases are the critical path and should be built first.

---

## 4. Plan — phased

Mirrors the repo convention: a new `transition_network/` module, CPU-first,
deterministic, benchmarked; embeddings/LLM only as a guarded, propose-only layer.

> **Status: Phases 1-4 BUILT** (`transition_network/build_network.py` +
> `analyze.py`; see `transition_network/README.md`). occupation grain: 824
> nodes, 39,310 edges; relative-risk + row-normalized weights; disparity-filter
> backbone (1,495 edges); PageRank/betweenness/HITS centrality; Infomap (27
> flow modules, mean SOC-major alignment 0.56 → ~44% cuts across the taxonomy)
> + Leiden cross-check. **Phase 5 BUILT** (`transition_network/sequences.py`):
> SOC-major trajectories show real memory (order-2 perplexity −7.5%), oscillation
> path motifs, k-means trajectory archetypes. **Seniority/transition-typing
> upgrade BUILT** (see `SENIORITY_TRANSITIONS_PLAN.md`): SpringRank revealed
> seniority → fused `seniority_score` (93% of steps) → `transition_type` on
> ~66% of edges (calibrated asymmetric τ). **Phase 6 BUILT** (multi-grain via the
> axis arg; `transition_network/temporal.py` time-sliced networks — Software
> Developers rises into the top-3 bridges by 2020-25, tech-boom flows grow ~78×).
> Phases 7-8 (external-outcome validation, bias post-stratification, cross-axis
> on the still-unbuilt industry/region grains) remain.

### Phase 1 — Raw transition matrix per axis
From the L5 edge table, aggregate to a weighted directed multigraph per axis
(start with **occupation (SOC)** — highest analytic value, cleanest source, and
directly comparable to the published networks). Emit `count`, `n_persons`,
`mean_dwell`, `mean_gap`, `kind` mix per edge. Add the **self-loop** = stayers /
within-state promotions. Sanity-bound (drop the 696-step garbage profiles, dedup
the 0.35% duplicate steps). *Deliverable: `edges_<axis>.parquet`, node table with
in/out strength.*

### Phase 2 — Normalization & null model
Compute, per edge, the **observed-over-expected** ratio against a
configuration/gravity null (expected flow ∝ out-strength_i · in-strength_j) — the
relative-risk fix for the large-occupation bias (Cheng & Park). Also produce the
**row-normalized transition-probability** matrix with explicit self-loops (Mealy
form) for the modeling grain. *Deliverable: edge table gains `rr`, `p_transition`,
`expected`, `z`/significance.*

### Phase 3 — Backbone & descriptive structure
Significance-filter (disparity filter or null-model threshold) to a backbone.
Compute node metrics: in/out-strength, **flow betweenness** (bridge roles),
PageRank (attractor states), **net-flow / balance** per node (sources vs sinks —
the Guerrero–Axtell balance check), and asymmetry per edge. *Deliverable: ranked
"bridge" and "trap/attractor" states with confidence; a structural report.*

### Phase 4 — Community detection (revealed segments)
Run flow-based community detection (Infomap and a weighted modularity/SBM
cross-check) on the normalized network → **empirical labor-market segments**.
Cross-tab segments against official SOC major groups and (when ready) industry to
show what the flow structure reveals that the taxonomy misses. Validate stability
(bootstrap over profiles; configuration-null comparison). *Deliverable: segment
assignment per state + a "segments vs taxonomy" comparison.*

### Phase 5 — Sequence / higher-order structure (our differentiator)
Move beyond the one-step matrix: test **first- vs higher-order Markov** memory on
trajectories, extract frequent **path motifs**, and cluster whole trajectories
(sequence clustering) to find archetypal careers. This is what survey transition
matrices cannot do and is the clearest novelty. *Deliverable: memory-order test,
top motifs, trajectory archetypes.*

### Phase 6 — Multi-grain + cross-axis + temporal slices
Re-run Phases 1–4 at title+seniority, employer (the inter-firm LFN), and — once
Layer 6 resolves them — **industry** and **region** grains. Build **cross-axis**
networks (industry×seniority). Add **time-sliced** networks (by cohort/era) and
measure segment/bridge drift. Self-employment entry/exit edges are first-class
throughout. *Deliverable: parallel networks + a temporal-dynamics report.*

### Phase 7 — Validation & bias
- **External-outcome validation:** does network position predict an observed
  outcome (seniority gain, dwell time, return-from-self-employment)? Mirrors the
  Guerrero–Axtell growth/retention validation.
- **Representativeness:** post-stratify node masses to BLS/ILO occupation×region
  marginals; report mover-cohort vs full-cohort sensitivity; surface every bias
  from `CAREER_PATHS_PLAN §7` (selection, recency/backfill, Present-staleness,
  unobservable gaps, 22% SOC-coding survivorship) **as network-level caveats**
  (e.g. occupation network only covers the ~22% deterministically SOC-coded tail
  unless the review queue is filled — state it).

### Phase 8 (optional) — Latent layers & prediction
- **Skill-space overlay** (Skillscape-style): if/when a skill axis exists, build
  the relatedness network and compare revealed-vs-latent (where do people move
  *despite* low skill overlap, and vice versa).
- **Node embeddings (Job2Vec/AHEAD-style)** as a *propose-only* predictive layer
  for next-move prediction and to populate candidate edges for the sparse tail —
  never as an autonomous merger, per this repo's standing prior.

---

## 5. Method choices already settled by repo priors

- **Reference key beats models** → the network is built on the *already-resolved*
  `occupation_code` / `company_canonical_id`, not on raw strings or embeddings.
- **Embeddings propose, never decide** → confined to Phase 8.
- **Deterministic, CPU, benchmarked, with explicit confidence/method columns** →
  same conventions as `career_clean`; every edge carries provenance.

**GPU usage (RTX 5080, 16GB).** The spine and edge aggregation (Phases 1-2) are
relational and stay on DuckDB/CPU — GPU buys nothing there. GPU pays off in
**Phases 3-4** (centrality, Infomap/SBM community detection on the backboned
graph) and **Phase 8** (node embeddings / next-move prediction via `torch`,
already proven on this box in `career_clean/approach_c_embed.py`). Caveat:
`torch` runs on GPU now, but **RAPIDS `cudf`/`cugraph` are not installed and do
not yet support this env's Python 3.14** — so the GPU graph-algorithm path needs
either a pinned 3.11/3.12 RAPIDS env or `torch`/`cupy`-based implementations.
Confirm which before Phase 3. The edge list is emitted GPU-ready (compact
integer-codable node ids, Arrow/Parquet) either way.

## 6. Open decisions to confirm

1. **Default node grain for v1** — recommend **occupation (SOC)** to match the
   published baselines, then employer + industry. Confirm.
2. **Null model** — configuration (degree-preserving) vs gravity (strength-
   preserving) expectation for relative risk? (Recommend strength-preserving.)
3. **Primary-role policy** for concurrency (inherited from `CAREER_PATHS_PLAN`
   decision #2) — drives every edge; must be fixed before Phase 1.
4. **Self-loop treatment** — count within-employer promotions as self-loops on
   the occupation grain, or as edges? (They are edges on the title+seniority
   grain.)
5. **Min-support threshold** for an edge to survive backboning/rendering.
6. **Bias correction scope** — caveat-only vs active post-stratification to
   BLS/ILO (Phase 7). Determines whether external reference data is needed.
7. **Industry/geography dependency** — those grains are blocked on
   `CAREER_PATHS_PLAN` Layer 6; build occupation/employer first or wait?

---

## 7. References

- del Rio-Chanona, Mealy, Lafond, Farmer (2021). *Occupational mobility and
  automation: a data-driven network model.* J. R. Soc. Interface.
  https://royalsocietypublishing.org/doi/10.1098/rsif.2020.0898
- Mealy et al. (2018). *Automation and occupational mobility.* arXiv:1906.04086.
- Guerrero & Axtell (2013). *Employment Growth through Labor Flow Networks.*
  PLOS ONE. https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0060808
- Park et al. (2019). *A network theory of inter-firm labor flows.* EPJ Data Sci.
  https://epjdatascience.springeropen.com/articles/10.1140/epjds/s13688-020-00251-w
- Cheng & Park (2020). *Flows and Boundaries: A Network Approach to Studying
  Occupational Mobility.* Am. J. Sociology. https://www.journals.uchicago.edu/doi/10.1086/712406
- Alabdulkareem et al. (2018). *Unpacking the polarization of workplace skills.*
  Science Advances. https://www.science.org/doi/10.1126/sciadv.aao6030
- Zhang et al. (2019). *Job2Vec: Job Title Benchmarking with Collective
  Multi-View Representation Learning.* arXiv:2009.07429.
- Career Path Prediction using Resume Representation Learning (2023).
  arXiv:2310.15636.
- Dorn & Schoner (2025). *Representativeness of online resume data.* IZA DP 17896.
  https://docs.iza.org/dp17896.pdf
- *LLMs for Career Mobility Analysis (gender/race/job change).* arXiv:2511.12010.
