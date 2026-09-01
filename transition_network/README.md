# Career transition network (Phases 1-4)

Aggregates the spine edge list (`paths/transitions.parquet`) to a chosen **node
grain**, normalizes it against a null model (Phases 1-2), then mines its
structure — backbone, centrality, communities (Phases 3-4). Implements
`../CAREER_TRANSITION_NETWORK_PLAN.md`.

> **Prerequisite:** run the pipeline through `paths.build_spine` first — which
> needs `build_normalized.py`, which needs `parse_linkedin.py`. See the root
> `README.md` for the full chain.

## Run

```bash
# Phases 1-2: build + normalize a grain
uv run python -m transition_network.build_network occupation   # default grain
uv run python -m transition_network.build_network company --threads 16
uv run python -m transition_network.build_network occupation --exclude-overlap
# grains: occupation | role | company | employment_type | seniority

# Phases 3-4: backbone + centrality + communities (needs the `graph` group)
uv run --group graph python -m transition_network.analyze occupation
```

All-CPU, <1s per grain at the occupation scale. Phases 1-2 emit
`<axis>_edges.parquet`, `<axis>_nodes.parquet`, `<axis>_manifest.json`; Phases
3-4 emit `<axis>_nodes_analyzed.parquet`, `<axis>_backbone_edges.parquet`,
`<axis>_communities.json`, `<axis>_analyze_manifest.json`.

## What each edge carries

- **weight** — raw transition count (i->j).
- **n_persons** — distinct people making that move.
- **expected** — strength-preserving (gravity) null: `s_out_i · s_in_j / W`.
- **relative_risk** — `weight / expected`. >1 = over-represented vs chance. This
  is the size-controlled weight: large occupations exchange many workers by sheer
  size, so cluster/interpret on RR, not raw weight (Cheng & Park 2020).
- **p_transition** — `weight / out_strength_i`, row-normalized (sums to 1 per
  source, self-loops included) — the Mealy/del Rio-Chanona transition-matrix form.
- **z** — `(weight − expected)/√expected`, a Poisson-ish significance for backboning.
- **modal_kind**, **mean_dwell_months**, **mean_gap_months**, **frac_with_gap**,
  **frac_up/flat/down** (seniority direction mix).

Nodes carry `out_strength`, `in_strength`, `out/in_degree`, `self_loops`,
`out_persons`, and `net_flow` (out−in: sources vs sinks).

## Semantics — read before interpreting

This is a **job-to-job mobility** network: edge i->j = a person whose successive
*primary* steps were i then j. It is **conditional on a move occurring** — people
who never change employer produce no edge — so `p_transition` is
P(next state = j | a move from i happened), NOT a full Markov chain with stayers.
A **self-loop** i->i is a real move that stayed in the same occupation.

## occupation grain — validated result

824 SOC nodes (finer than the 464-node ACS baselines), 39,310 edges in 0.2s.
**Coverage is 7.8%** of the 6.03M spine transitions, because both endpoints must
carry a deterministic SOC code and only ~22% of titles do (≈0.22² ); this is the
known `career_clean` occupation-coding ceiling, not a builder gap. Filling it is a
curation/review-queue job (plan Phase 7), or use the title/company grains, which
cover far more.

Sanity (size-controlled `relative_risk` surfaces real career ladders that raw
counts bury):

| from → to | weight | RR |
|---|---|---|
| Firefighter → Fire/Prevention Supervisor | 62 | 225 |
| EMT → Paramedic | 111 | 145 |
| Helper–Electrician → Electrician | 70 | 131 |
| Police Officer → Detective | 134 | 97 |
| Cook → Chef | 55 | 76 |
| Registered Nurse → Nurse Practitioner | 1181 | 8.7 |

Biggest net **sink**: Chief Executives (everyone flows up, few leave). Biggest
net **sources**: Waiters/Waitresses, Computer Programmers, HR Assistants.

## Phases 3-4 — structure (`analyze.py`), validated

Backbone via the **disparity filter** (Serrano et al., α=0.05): 38,583 non-self
edges → a **1,495-edge skeleton**. Node centrality (igraph, directed/weighted):

- **Bridges** (flow-betweenness): Chief Executives, General & Operations
  Managers, Sales Managers, Software Developers, Waiters/Waitresses — generalist
  management plus the food-service entry/exit hub.
- **Attractors** (PageRank): Chief Executives, Sales Managers, HR Specialists.
- **Sources/sinks**: `net_flow` (CEO is the dominant sink).

Community detection runs two methods that answer different questions:
**Infomap** (directed, flow-based, on raw volume) and **Leiden** (modularity, on
size-controlled `relative_risk`). Infomap finds **27 modules** whose **mean
alignment with SOC major groups is only 0.56** — i.e. ~44% of the revealed
structure cuts *across* the official taxonomy (the Cheng & Park finding,
quantified). The modules are interpretable: a tech/engineering/production
segment (Software Developers + Engineers + Production, crossing 3 SOC majors), a
healthcare segment (RN/NP/medical managers), a public-safety segment
(police/fire/EMT + military), a science/academia segment.

GPU note: exact on CPU at this scale (~824 nodes, 0.5s). The GPU path (cuGraph)
matters only at the company/title grain (millions of nodes) and is blocked on
RAPIDS' Python-3.14 support; revisit with a pinned env then.

## SpringRank revealed seniority (node metric)

`analyze.py` also computes **SpringRank** on the seniority-comparison subgraph
(excludes exit/education/self-employment edges, weighted by `n_persons`): a
real-valued revealed rank per node (`springrank`, `springrank_support`) from the
directed flow asymmetry. It recovers the known ladders (NP above RN, Detective
above Patrol, Chef above Cook) with no lexical word, and is the input to
`paths/seniority.py` (the `role`-grain ranks drive the fused step `seniority_score`).
Auto-scales: betweenness/communities are skipped above 20k/200k nodes, so the
`role` grain (1.9M nodes) computes SpringRank in ~100s.

Edges now also carry `modal_transition_type`, `mean_delta_sen`, and
`mean_transition_confidence` — so every grain inherits the fused-seniority
**direction** on the previously-untyped `move` mass (e.g. RN→NP `mean_delta_sen`
+0.58 → `employer_move_up`).

## Phase 5 — higher-order sequence structure (`sequences.py`), validated

    uv run --group graph python -m transition_network.sequences

Three analyses over full per-person trajectories (the differentiator vs one-step
survey matrices):

- **Memory-order test** — 1st- vs 2nd-order Markov by held-out perplexity.
  **SOC-major trajectories show real memory (order-2 cuts perplexity 7.5%)**;
  employment-type is essentially Markovian (0.19%) — a genuine contrast.
- **Path motifs** — occupation triples by lift over the first-order expectation.
  Top motifs are **oscillation/return** patterns (Programmer→Software
  Developer→Programmer, lift 7.2; Accountant→Supervisor→Accountant) — exactly
  what a one-step matrix cannot see.
- **Trajectory archetypes** — k-means over per-profile structural features (1.34M
  profiles with ≥3 primary steps); e.g. within-field job-hoppers vs long churned
  careers. Outputs `sequences.json` + `trajectory_features.parquet`.

## Phase 6 — time-sliced networks + multi-grain (`temporal.py`), built

    uv run --group graph python -m transition_network.temporal

Multi-grain already works via the axis argument (`occupation`, `role`,
`company`, `employment_type`, `seniority` — built occupation + role). `temporal.py`
adds the time dimension: one occupation network per era (binned by the year the
destination role started), each with its own relative-risk null model, PageRank,
betweenness, and SpringRank. Findings:

- **Era volumes** rise 21k→54k moves (2005-09 → 2020-25): the recency/backfill
  bias (CAREER_PATHS_PLAN §7) is visible, not hidden — earlier eras are sparser.
- **Bridge drift**: Chief Executives / General & Operations Managers stay the top
  bridges, but **Software Developers enters the top-3 by 2020-25** — a real
  structural shift.
- **Fastest-growing flows** capture the tech boom: Engineers→Software Developers
  grew ~78×, Web Developer→Software Developer, and RN→Nurse Practitioner nearly
  tripled (credential expansion). The per-edge flow-growth signal is more reliable
  than the per-node PageRank riser/faller list, which is noisy for low-degree
  peripheral occupations — read it with that caveat.

Outputs `temporal_occupation_nodes.parquet` (era × node × metrics) + `temporal.json`.

## Next (plan Phase 7+)

External-outcome validation + bias post-stratification; cross-axis
(industry×seniority, blocked on Layer-6 industry resolution); optional embedding
leveling for the role tail.
