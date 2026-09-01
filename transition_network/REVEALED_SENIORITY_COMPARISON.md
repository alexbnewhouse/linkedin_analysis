# Revealed-Seniority / Hierarchy Methods — Head-to-Head

**Question.** SpringRank (weight = `n_persons`) is the production "revealed
seniority" signal, but it agrees with the lexical layer only ~62% of the time and
is near-chance on *down* moves. Do any alternative hierarchy-from-flows methods
fix the weak-`down` problem on the same transition graphs?

**Verdict (TL;DR): No. Keep SpringRank-on-`n_persons`.** Every alternative either
ties it (trophic levels, minimum-violation agony — they are the same Laplacian
family) or is strictly worse (David's Score). The `relative_risk` weighting that
was hypothesized to fix the large-occupation bias actually *lowers* down-precision,
disproving that hypothesis. The weak-`down` signal is a property of the data
(down-moves are genuinely noisier and rarer in the silver truth), not of the
ranking method or the edge weighting.

## Method & harness

All methods run on the exact seniority subgraph `analyze.py` uses: `<axis>_edges`,
self-loops dropped, `NON_SENIORITY_KINDS` dropped, `n_persons > 0`. Each produces a
real-valued node rank, oriented (sign-flipped) to increase with the per-node mean
lexical ordinal — identical to `paths/seniority.py`.

**Silver truth (non-circular).** Reusing `tune_thresholds`' construction:
aggregate person-level moves where *both* endpoints carry a named lexical
seniority token to the graph node-pair level; `sign(mean Δordinal)` is the truth.
The ranking methods never see the lexical word, so this is a clean held-out signal.
A method predicts direction via `sign(rank[to] − rank[from])`; we sweep a threshold
on the (scale-normalized) rank gap and report coverage / directional accuracy /
up-precision / down-precision. Secondary anchors: Spearman vs O*NET `job_zone_norm`
(occupation only, fully independent), Spearman vs per-node mean lexical ordinal, and
the gold occupation ladders (RN→NP, Cook→Chef, Police→Detective must be "up").

Module: `transition_network/revealed_seniority_eval.py` (read-only; no production
module touched).

## Results — ROLE graph (the production grain)

1,844,766 nodes, 3,964,750 edges, 310,821 silver node-pairs (186,596 up /
124,225 down — note the 60/40 up-skew). Metrics at full coverage (τ=0):

| method | dir_acc | up_prec | **down_prec** | ρ(mean lex) | runtime |
|---|---|---|---|---|---|
| **springrank_npersons (baseline)** | 0.585 | 0.630 | **0.474** | 0.173 | 57s |
| springrank_rr | 0.578 | 0.627 | 0.462 | 0.177 | 39s |
| springrank_rr_logn | 0.579 | 0.627 | 0.464 | 0.178 | 40s |
| davids_score | 0.538 | 0.613 | 0.421 | 0.079 | **0.7s** |
| min_violation_agony | 0.586 | 0.628 | 0.474 | 0.156 | 10s |
| trophic_level | 0.587 | 0.628 | 0.475 | 0.157 | 375s |

Threshold sweep (the weak-`down` problem persists at every operating point; e.g.
springrank_npersons down_prec rises only 0.474 → 0.542 as coverage falls 100% → 36%):

| τ | coverage | acc | up_prec | down_prec |
|---|---|---|---|---|
| 0.00 | 100% | 0.585 | 0.630 | 0.474 |
| 0.10 | 91% | 0.593 | 0.633 | 0.484 |
| 0.30 | 75% | 0.606 | 0.639 | 0.502 |
| 0.50 | 61% | 0.616 | 0.643 | 0.517 |
| 1.00 | 36% | 0.630 | 0.646 | 0.542 |

## Results — OCCUPATION graph

818 nodes, 37,196 edges, 2,321 silver node-pairs (1,234 up / 1,087 down).
This grain also exposes the O*NET job-zone anchor and the gold ladders.

| method | dir_acc | up_prec | down_prec | ρ(mean lex) | **ρ(job_zone)** | gold ladders |
|---|---|---|---|---|---|---|
| **springrank_npersons** | 0.567 | 0.588 | 0.540 | 0.088 | **0.434** | **3/3** |
| springrank_rr | 0.540 | 0.569 | 0.509 | 0.094 | 0.194 | 2/3 |
| springrank_rr_logn | 0.577 | 0.600 | 0.550 | 0.119 | 0.262 | 3/3 |
| davids_score | 0.561 | 0.586 | 0.532 | 0.040 | 0.303 | 1/3 |
| min_violation_agony | 0.568 | 0.589 | 0.541 | 0.088 | 0.421 | 3/3 |
| trophic_level | 0.568 | 0.589 | 0.541 | 0.088 | 0.421 | 3/3 |

## Per-method notes

- **SpringRank (`n_persons`) — baseline, recommended.** Best independent anchor
  on the occupation graph (ρ_job_zone = 0.434, well ahead of every alternative),
  passes all 3 gold ladders, and is the (tied) best on the role silver truth. Fast
  enough at scale (57s on 1.9M nodes). It is the most defensible single signal.

- **Trophic levels (MacKay/Johnson).** Statistically indistinguishable from
  SpringRank on the role silver truth (acc 0.587 vs 0.585; down 0.475 vs 0.474)
  and on the occupation graph it lands a hair *below* SpringRank on the job-zone
  anchor (0.421 vs 0.434). Expected: trophic levels and regularized SpringRank are
  both solutions of a graph-Laplacian system over `(k_in − k_out)`, so they nearly
  coincide. **6.5× slower** (375s vs 57s) because the per-component solve has no
  global regularizer shortcut. No reason to switch.

- **Minimum-violation / agony (iterative).** Also a Laplacian-family relaxation;
  numerically tracks trophic/SpringRank (acc 0.586, down 0.474). Cheaper than
  trophic (10s) but no accuracy gain, and a slightly weaker job-zone anchor (0.421)
  and weaker mean-lex correlation than SpringRank on the role graph (0.156 vs 0.173).

- **David's Score (flow-asymmetry dominance).** Cheapest by far (0.7s on 1.9M
  nodes, sparse implementation) but clearly the **worst** quality: role acc 0.538,
  down_prec 0.421, near-zero mean-lex correlation (0.079), and only **1/3** gold
  ladders. Pairwise win-rate throws away the transitive flow structure the Laplacian
  methods exploit. Reject.

- **SpringRank with `relative_risk` weighting (the Cheng-Park hypothesis test).**
  The plan flagged that raw `n_persons` might reintroduce large-occupation bias and
  cause the weak `down`. **The data rejects this.** On the role graph, `rr` and
  `rr × log1p(n_persons)` *lower* down-precision (0.462 / 0.464 vs 0.474) and
  overall accuracy. On the occupation graph, pure `rr` is markedly worse on the
  independent job-zone anchor (0.194 vs 0.434) and drops a gold ladder. `rr_logn`
  is competitive on the occupation silver truth but still trails badly on job-zone
  (0.262 vs 0.434). Significance-gating `rr` does not help because the problem is
  not large-occupation bias — it is that down-moves are intrinsically noisier.

## Why `down` is weak (and why no method fixes it)

The silver truth itself is up-skewed (60% up / 40% down) and down-moves are the
genuinely ambiguous ones — lateral/demotion/re-entry moves whose flow direction
does not cleanly encode a rung. All Laplacian-family methods read the *same*
net-flow asymmetry, so they converge to the *same* ~0.47 down-precision. The only
lever that improves `down` is raising the rank-gap threshold (trading coverage),
and that lever is identical across methods. This is a data/feature limit, not a
ranking-algorithm choice.

## Recommendation for `paths/seniority.py` / `analyze.py`

**No change.** Keep SpringRank with `weight = n_persons` exactly as
`transition_network/analyze.py` and `paths/seniority.py` use it today.

- Do **not** switch to `relative_risk` weighting — it measurably degrades the
  independent O*NET anchor and the down direction.
- Do **not** adopt trophic levels or agony — equal accuracy, no `down` fix, and
  trophic is 6.5× slower at the production grain.
- If a cheap secondary signal is ever wanted (e.g. for robustness ensembling on a
  changing node set), trophic levels are the natural near-duplicate of SpringRank,
  but they add nothing on these graphs today.
- The real lever for the weak-`down` regime is the existing **threshold τ** in
  `paths/tune_thresholds.py` (trade coverage for down-precision), plus keeping
  revealed typing **propose-only** with confidence attached — which the system
  already does. Treat low-confidence down-calls as such rather than chasing a
  better ranker.

*Reproduce:* `uv run --group graph python -m transition_network.revealed_seniority_eval both --out results.json`
