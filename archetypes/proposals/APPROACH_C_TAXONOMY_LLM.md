# Approach C — O\*NET-grounded taxonomy + measured LLM assignment

**Status:** proposal. Nothing in this document has been built. Every number tagged
*(measured)* was run read-only against the repo on 2026-08-05; every number tagged
*(estimated)* is arithmetic on a measured rate and is labelled as such.

---

## 1. Thesis

The archetype layer's problem is not that its representation is too thin — it is that
**its accuracy has never been measured, so no fix can be shown to be a fix.** This
proposal replaces the hand-written decision tree with three things, in order of
importance: (a) a **stratified, person-year-weighted gold set with per-archetype
precision/recall and a head-to-head score against the shipped tree** — the number that
does not exist today; (b) a **two-axis taxonomy (FUNCTION × CONTEXT)** whose label space
is *derived* from clustering O\*NET's 109-dimensional Work-Activities/Skills/Knowledge
space over the 763 SOC codes that carry ratings, so the node boundaries answer to
external occupational semantics rather than to regex convenience; and (c) an **LLM jury
over the readable role surface** (`role_text`, top titles, modal seniority, modal
industry L1, sampled descriptions), following the `role_soc_jury` precedent verbatim,
labelling to the 90%-of-person-years support line and distilling a calibrated classifier
onto the remaining tail. The O\*NET grounding is deliberately scoped: it defines and
validates the **label space**, and it cannot define the per-role assignment, because only
**22.39% of humanities person-years carry an O\*NET-rated SOC** *(measured)*. Claiming
otherwise would be the same overreach the current module made with the word "skillset".

---

## 2. What is broken now that this fixes

| # | Measured defect | Number | Why the current design causes it |
|---|---|---|---|
| 1 | **No accuracy exists at all.** `results/validation.json` reports purity/coherence proxies only. `FINDINGS.md` §5 calls face-validity "a hand-audit" that was never systematically run. | — | No gold set was ever built for archetypes (one *was* built for SOC: `career_clean/results/soc_gold.parquet`, n=600). |
| 2 | **Regex carries as much of the panel as SOC does.** | keyword 31.9% + soc_major_kw 10.1% of role-occupancy; person-year weighted: keyword **28.20%**, soc_major_kw **10.91%** vs soc_detail **25.93%** *(measured)* | `assign_role` precedence 2–3: ~15 ordered regexes decide the archetype whenever the 6-digit code is absent or its major is "split". |
| 3 | **Split majors are incoherent.** | SOC 11 → 0.478, 13 → 0.392, 27 → 0.465 concentration *(validation.json)*; keyword-vs-SOC agreement **0.408** | The split-refinement is regex arbitrating a genuine functional ambiguity with no ground truth to tune against. |
| 4 | **Node 7 "Analysts / Consultants" is actually managers.** | `managerproject` 63,382 py, `manageroperations` 28,871, `managerprogram` 25,770 all land in 7 | `KEYWORD_RULES` puts `project manager|program manager|operations manager` in the *analysts* rule, ahead of the generic manager rule. Nothing catches it. |
| 5 | **Node 11 "Legal, Policy & Research" absorbs bench science.** | `SOC_DETAIL["19"] = "legal"` folds all of SOC 19 wholesale — chemists, geologists, clinical psychologists, `assurancequality`. Industry purity **0.479**, worst of any node. | A one-line crosswalk entry, never validated. |
| 6 | **Managers is an admitted generic-title catch-all.** | 14.40% of in-window person-years *(measured)*; largest single role `president` (125,759 py) includes student-org and board presidencies. | Generic manager regex is the penultimate rule; anything unclaimed with "manager/director/president" falls in. |
| 7 | **Life/seniority states are treated as occupational residual.** | `partner` 27,924 py, `retired` 10,300, `member` 7,375 sit in OTHER (11.36% of in-window person-years, *measured*). | There is no NON-OCCUPATION class; the taxonomy has no home for "not in identifiable work". |
| 8 | **Nonprofit is a fragile node.** | 0.86% of in-window person-years, SOC purity 0.436 *(measured)* | It is industry-anchored inside a function-anchored taxonomy — a category error the plan itself (§11) flagged as an open test. |
| 9 | **The unsupervised cross-check is uninterpretable.** | adjusted Rand **0.16**, NMI **0.26** | KMeans was run on MiniLM embeddings of role strings. `role_canonical` is an alphabetically-sorted, space-stripped token bag (`humanmanagerresources`, `managerproject`, `atattorneylaw`) — **not embeddable text**. The readable surface is `role_features.role_text`. Whatever was embedded, the resulting agreement score is not evidence about the anchors. |
| 10 | **No skill signal despite the name.** | 0 skill features anywhere in `role_features.parquet` | The module is called "role/skillset archetypes" but the substrate is SOC codes + regex on titles. |

Defects 4, 5, 6 and 7 are each a **single line** in `archetype_spec.py`, and each would have
been caught by fifty labelled roles. That is the argument for this proposal: the
measurement is worth more than the model.

---

## 3. Pipeline

### Stage 0 — O\*NET skill space → the label space
**Input:** `https://www.onetcenter.org/dl_files/database/db_29_1_text.zip` — **13,159,492
bytes**, HTTP 200 verified 2026-08-05, **O\*NET-SOC 29.1** (same version as the four O\*NET
files already in `reference/`), **CC BY 4.0**, attribution already carried in
`reference/README.md`. Only four members are needed:

| member | size | shape *(measured)* |
|---|---|---|
| `Work Activities.txt` | 8,600,908 B | 72,078 rows, **41 elements**, 879 O\*NET-SOC, scales IM/LV |
| `Skills.txt` | 5,550,164 B | 61,530 rows, **35 elements**, 879 SOC |
| `Knowledge.txt` | 5,510,036 B | 58,014 rows, **33 elements**, 879 SOC |
| `Task Statements.txt` | 2,759,559 B | 18,796 tasks, 923 SOC (for cluster *naming* only) |

Skip `Abilities.txt` (52 elems — physical/psychomotor, near-useless for humanities
white-collar separation) and `Work Context.txt` (34.7 MB, 57 elems — environmental, adds
noise). **Total added to `reference/`: ~22 MB.**

**Outputs:**
- `reference/onet_skillspace.parquet` — `soc6, element_id, element_name, domain
  (WA|SK|KN), im` : the **IM (Importance)** scale only, 109 dims per SOC. Roll 8-digit →
  6-digit by unweighted mean over the `.00/.01/.02` variants; **763 distinct 6-digit SOC**
  *(measured, from 879 8-digit)*. Z-score each dim across the 763.
- `reference/build_onet_skillspace.py` — the fetch+build driver, mirroring
  `reference/build_soc_status.py`.

**Join reality check *(measured)*:** `career_steps.occupation_code` has **850 distinct
6-digit values**; **92.99%** of coded, non-duplicate steps land on a SOC that has O\*NET
ratings (92 distinct codes unmatched — mostly `-9`/residual "all other" codes). At the
humanities person-year grain: 23.50% have any SOC, **22.39% have an O\*NET-rated SOC**.
That 22.39% is the *entire* population on which a genuine skill vector can be computed
without inference. Design accordingly.

**Clustering:** Ward / k-means over the 763×109 z-scored matrix, **each SOC weighted by
its step mass in this corpus** (not uniformly — otherwise clusters are spent on farming,
extraction and military, which the humanities panel barely touches). Sweep k ∈ [10, 20];
select by silhouette + the requirement that every cluster holds ≥2% of corpus step mass.
**Output:** `archetypes/results/onet_skill_clusters.parquet` (`soc6, cluster_id,
dist_to_centroid`) + `onet_skill_centroids.parquet`.

**Naming:** ~20 frontier-model calls, one per cluster, evidence = top-12 loading elements
by centroid z-score + top-15 member SOC titles + 5 sampled Task Statements. Human
approves the names. This is the one place the LLM is allowed to be creative, and it
touches 20 objects, not 500,000.

### Stage 1 — the taxonomy (`archetypes/taxonomy_v2.py`)
Structured, **not** flat-15. Three fields, of which only one is LLM-assigned.

- **FUNCTION** — 16 values + 2 escapes. LLM-assigned. This is the Sankey node.
  `TEACH`, `WRITE`, `DESIGN`, `PRODUCE` (performing/media production), `MARKET`,
  `SELL`, `ACCOUNT_SVC` (client/account service), `ADMIN`, `OPS_PM` (operations &
  program/project management), `EXEC` (general management & executive), `ANALYZE`
  (analysis/strategy/consulting), `FINANCE`, `SOFTWARE` (software/data/IT/product),
  `LAW` (legal & compliance), `RESEARCH` (science & scholarly research), `CARE`
  (clinical, counseling, social work), `SERVICE` (food/retail/personal/trades/logistics)
  — plus `NONOCC` (**status-only states**: student, retired, member, volunteer, bare
  intern, unqualified partner/owner) and `OTHER` (honest residual).
- **CONTEXT** — 6 values. **Deterministic, no LLM**, from `industry/results/
  step_industry.parquet` L1 (~100% coverage) + `career_steps.employment_type` (100%):
  `PRIVATE`, `NONPROFIT`, `GOVERNMENT`, `EDU_INST`, `HEALTH_INST`, `INDEPENDENT`.
- **LEVEL** — 3 values from `paths/steps.parquet` `seniority_ordinal`: `IC`,
  `SUPERVISOR`, `EXEC`. Attribute only, never a node.

**Binding constraint (this is what makes "O\*NET-grounded" falsifiable):** every FUNCTION
value must be expressible as a **union of ≥1 Stage-0 skill cluster**, and that mapping is
committed in `taxonomy_v2.FUNCTION_TO_SKILL_CLUSTERS`. If a proposed FUNCTION cuts a
skill cluster in half, or if two FUNCTIONs share a cluster with no separating dimension,
the taxonomy is rejected *before* any labelling is fired. This is a cheap, automatic
check that the current 15 anchors have never been subjected to.

`taxonomy_v2.output_json_schema()` enum-constrains the LLM's structured output to the
frozen FUNCTION list — copied directly from `industry/taxonomy.py`, which already does
exactly this.

**What this fixes structurally:** Nonprofit (defect 8) becomes `CONTEXT=NONPROFIT`
applicable to any function, resolving the plan's own §11 open question with data rather
than a coin flip. `OPS_PM` vs `EXEC` vs `ANALYZE` separates defects 4 and 6. `RESEARCH`
splits from `LAW`, fixing defect 5. `NONOCC` gives defect 7 a home.

### Stage 2 — deterministic priors (free)
Per `role_canonical`, extending `role_features.py` (new module, existing file untouched):
- `soc_skill_prior` — trusted `soc_detail` (existing `SOC_MIN_SUPPORT`/`SOC_MIN_FRAC`
  gates) → Stage-0 cluster → FUNCTION. Covers **22.39%** of person-years.
- `jury_major_prior` — `role_soc_jury.soc_major` (**40.70%** of humanities person-years,
  **139,505 distinct roles hit** *(measured)*) → a *weak, multi-valued* FUNCTION prior.
  Union with the above: **64.20%** of person-years have some structured prior *(measured)*.
- `context_key` — deterministic, ~100%.

Priors enter the prompt as **evidence lines**, never as overrides. This is the
`industry/` M5 lesson: a prior that cannot discriminate must abstain, not vote.

### Stage 3 — the jury, tiered by support (`archetypes/archetype_llm.py`)
A near-verbatim fork of `career_clean/soc_llm.py`: same `Proposal` dataclass, same
`hashlib.sha256(evidence + model + prompt_version + schema_version)` cache key, same
append-only JSONL cache, same `industry.llm_pool` 3-lane pool, same reason-before-verdict
schema, same explicit abstain code. **The only changes are the taxonomy, the rubric, and
batching.** Retrieval anchors from `career_clean/soc_anchors.py` are reused unchanged —
the O\*NET alternate-title lexicon (55,121 lines, already in `reference/`) supplies the
"nearest reference titles" evidence line that lifted the SOC jury past its gate.

Evidence per role: `role_text` (**100% of 2,605,247 roles** *(measured)*), top-3
`title_raw`, modal seniority, modal industry L1 label, `n_steps`, up to 3 sampled
`description` snippets (≤400 chars each — **90.35% of humanities person-years belong to a
role with ≥1 description ≥40 chars; 74.29% with ≥3; mean length 522 chars** *(measured)*).
Descriptions are the single largest unused signal in the substrate and they are what
separates a `managerproject` at a film studio from one at a bank.

| tier | roles | jurors | batching | rationale |
|---|---|---|---|---|
| **A** head | top **2,690** (50% of py) + through **104,437** (80% of py) | 3 | 1 role/call, full evidence + descriptions | errors here move the whole panel |
| **B** mid | to **249,858** roles (90% of py) | 2 | **20 roles/call** | mass-efficient |
| **C** tail | remaining ~430k roles (last ~10% of py) | 0 | — | distilled, see Stage 3b |

Acceptance: Tier A unanimous → `jury_unanimous`; 2-of-3 → `jury_majority` (flagged,
`agreement=0.67`); split → review queue. Tier B unanimous → accept; else review queue.
Agreement is the calibratable confidence, exactly as in `industry/jury.py`. The shipped
SOC jury's realised rates are the honest prior: of **391,027** voted strings, **299,787
accepted (76.7%)**, 81,460 disagreed, 9,780 abstained *(measured,
`soc_jury_stats.json`)*.

### Stage 3b — distillation onto the tail
Train on Tier A+B accepted labels (~250k roles — a very large training set) a calibrated
linear classifier over `[MiniLM(role_text) ‖ one-hot(soc_major) ‖ one-hot(industry_l1) ‖
owner_share ‖ mean_seniority]`. Predict the ~430k tail roles. **Threshold on predicted
probability**: below it, the role becomes `OTHER` (or `NONOCC` if it matches the frozen
status-word list) rather than being forced into a function. Held-out accuracy is measured
on a 10% Tier-B holdout and **reported per-tier** — so the Sankey can carry a per-node
error bar, and the 10% distilled mass is never silently mixed with the 90% labelled mass.

This replaces the regex ladder with a *learned, measurable* function. It is the cost move
that makes the whole thing affordable.

### Stage 4 — outputs and drop-in interop
`archetypes/results/role_archetype_v2.parquet`:

```
role_canonical, function_key, function_id, function_label,
context_key, level_key,
assign_method  ∈ {soc_skill, jury_unanimous, jury_majority, distilled,
                  nonocc_rule, other_residual},
agreement (float, null for deterministic), model_set (string),
distill_prob (float, null unless distilled),
n_persons, n_steps,
archetype_id, archetype_key, archetype_label   -- COMPATIBILITY COLUMNS
```

The last three are a frozen `FUNCTION → legacy 0–15` map (`TEACH→1`, `DESIGN/PRODUCE→2`,
`WRITE→3`, `MARKET→4`, `SELL/ACCOUNT_SVC→5`, `EXEC→6`, `ANALYZE/OPS_PM→7`, `FINANCE→8`,
`SOFTWARE→9`, `ADMIN→10`, `LAW/RESEARCH→11`, `CARE→12`, `CONTEXT=NONPROFIT→13`,
`SERVICE→14`, `CONTEXT=INDEPENDENT→15`, `NONOCC/OTHER→0`). **Therefore
`archetypes/yearwise.py`, `occupancy.parquet`, `state_flows.parquet` and
`person_year_archetype.parquet` all rebuild unchanged** — v2 is a drop-in replacement for
`role_archetype.parquet` at the schema level. `assign.py` and `archetype_spec.py` are
bypassed, not deleted: they remain the scored baseline (§5) and the offline fallback when
no vote cache is present.

---

## 4. Cost & runtime

**The support-floor curve is the crux.** Roles the humanities cohort ever occupies:

| person-year coverage | roles needed |
|---|---|
| 50% | **2,690** |
| 80% | **104,437** |
| 90% | **249,858** |
| 99% | **582,197** |

Cross-check on the in-window cut (career_age 1–15, `valid_cohort`, nha 1–3; 6,747,679
person-years, 547,249 distinct roles) *(measured)*: top 1,000 roles → 41.81%; top 10,000 →
61.65%; top 100,000 → 81.07%; top 200,000 → 89.30%; roles with ≥3 person-years (312,958)
→ 94.85%. Same shape, same conclusion.

**Label to 90% (249,858 roles) and distil the rest.** Past 90% the curve is savage: the
last 9 points cost 332,000 additional roles averaging ~1 person-year each — roughly 3×
the LLM spend for 1/9 the mass.

**Measured throughput** *(from `career_clean/results/soc_tail4_run.log`)*: **2.64
units/s** sustained across the 3-lane llama.cpp pool (`local5080` 16 slots + `fw4b` 8 +
`fwmoe` 8), ~600 prompt tokens/unit, 269,886 units fired with 0 failures and 0 parse
failures. The shipped SOC jury totalled ~784,000 single-role units ≈ **82 wall-clock
hours**. That is the honest precedent cost.

| stage | volume | estimate |
|---|---|---|
| Stage 0 O\*NET fetch + cluster | 763×109 matrix | **< 10 min** CPU |
| Stage 0 cluster naming | 20 frontier calls | ~$0.30, minutes |
| Tier A: 104,437 roles × 3 jurors, 1/call | 313,311 units | 313,311 / 2.64 = **~33 h** |
| Tier A *reduced* to top 20,000 roles (67% of py) × 3 | 60,000 units | **~6.3 h** |
| Tier B: 230,000 roles × 2 jurors, 20/call | 23,000 calls, ~2.5k in + 1.6k out tok each | at 4× single-call latency ⇒ **~10 h**; at 10× pessimism **~24 h** |
| Stage 3b MiniLM over 582k `role_text` | GPU batch 512 | **~20 min** |
| Stage 3b fit + predict | linear model | seconds |
| **Total local** | | **~16–30 GPU-hours**, vs 82 h for the shipped SOC jury |

Batching is what buys the saving, not a smaller vocabulary. Risk: batched calls invite
position bias and lazy copying of the previous item's label. **Mitigation and its test are
in §5** (a 500-role batched-vs-unbatched agreement check, run before Tier B fires).

**Cloud alternative** (Tier A+B ≈ 290k role-labels, ~26k batched requests, ≈ **75M input
/ 12M output tokens**): with the Batch API's 50% discount and prompt caching on the frozen
taxonomy prefix, this is a low-hundreds-of-dollars job at a small-model tier. *Verify
current per-token rates before committing — do not budget from this document.* It is
**not** the recommended path: the repo's PII rule (`industry/README.md` §7.9 — intra-vendor,
no scraped PII egress) and the fact that the local pool already exists and is already
proven at this exact volume both point local. Cloud is for the **gold set only**, where
the model must be independent of the production jurors.

**Gold set:** 1,200 frontier-model proposal calls (~1,800 in / 250 out tokens each ⇒ ~2.2M
in / 0.3M out) — a few dollars — plus **~7 human-hours** of adjudication. This is the only
irreducible human cost in the proposal and it is what the whole thing is for.

---

## 5. Validation plan — the heart

### 5.1 Gold set design
**n = 1,200 roles**, three strata, drawn by the repo's existing reproducible idiom
(`ORDER BY hash(role_canonical || 'archetype_gold_v1')`, no RNG — copied from
`soc_candidates.SAMPLE_SEED`). Frozen to `archetypes/results/archetype_gold.parquet`
before any labelling.

- **S1 — person-year-weighted (n = 600).** Sample roles with probability **proportional to
  humanities in-window person-years** (PPS, systematic, fixed hash order). This is the
  stratum that matters: precision/recall computed on it, with the PPS weights, estimates
  **panel accuracy** — "what fraction of the 6.43M person-years driving the Sankey carry
  the right node". The shipped module has no such number, and a uniform-over-roles sample
  would not produce one either, because 582,197 roles carry the last 1% of mass.
- **S2 — uniform over roles with ≥3 person-years (n = 300).** From the 312,958-role
  population. Measures the mid-tail and the distilled tier, which S1 would essentially
  never sample.
- **S3 — adversarial, purposive but frozen (n = 300).** Not for headline rates; **for the
  confusion matrix**. Deliberately loaded with the known failure classes, all verified to
  exist: generic titles (`manager`, `specialist`, `coordinator`, `associate`, `partner`,
  `president`, `officer`, `member`); status states (`retired`, `student`, `volunteer`,
  bare `intern`); function-qualified managers (`managerproject`, `manageroperations`,
  `managerprogram`, `managerproduct`, `managerstore`, kitchen/shift); SOC-19 bench
  scientists vs policy researchers vs `assurancequality`; self-employed with vs without a
  stated trade; matched nonprofit/corporate pairs of the *same* function; and — the
  highest-yield sub-stratum — **roles where the shipped tree's `soc_detail` route and its
  keyword route disagree** (recoverable by re-running `assign_role` with each branch
  disabled; keyword-vs-SOC agreement is **0.408**, so this population is enormous).

### 5.2 Who labels
**Human adjudication is ground truth; the LLM proposes.** A frontier model
(explicitly *not* one of the production jurors — this independence is load-bearing) emits
function + context + level + rationale per role, one call, full evidence including
descriptions. A human accepts or corrects all 1,200 in a worksheet. `industry/fire_llm
sample-gold` already ships this exact workflow.

Two disciplines, both non-negotiable:
1. **Report the human-correction rate.** If the human changes <5% of proposals, the gold
   is substantially LLM-derived and every accuracy figure computed against it is
   inflated. Say so in the number, not in a footnote. This is precisely the trap
   `career_clean/soc_anchors.py` documents: a weaker retrieval guard leaked the
   label-generating lexicon entry into 41/600 gold items and inflated measured unanimity
   from 0.887 to 0.8931. Leakage is real here and it has bitten this repo before.
2. **Double-label 200 of the 1,200 with a second human** and report **Cohen's κ**. If
   κ < 0.75 the taxonomy is underspecified — fix the boundaries and relabel *before*
   claiming anything. No one has ever asked whether these 15 archetypes are
   inter-subjectively assignable at all.

### 5.3 What gets reported
Mirroring `industry/README.md`'s per-level table:
- **Per-FUNCTION precision / recall / F1 / support**, in **two tables**: role-grain and
  person-year-weighted. They will differ substantially and both must be shown.
- **Full 18×18 confusion matrix** (16 functions + NONOCC + OTHER), person-year weighted.
- **Per-`assign_method` accuracy** — `soc_skill` vs `jury_unanimous` vs `jury_majority`
  vs `distilled`. This is the coverage/precision trade curve and it is what licenses a
  per-node error bar on the Sankey.
- **CONTEXT precision/recall** separately (deterministic ⇒ a cheap sanity check on the
  industry join).
- **Head-to-head: score the shipped `role_archetype.parquet` on the identical gold set**,
  after mapping v2 FUNCTION → legacy id with the §3 Stage-4 crosswalk. Paired bootstrap
  over gold roles for the difference.

### 5.4 Pre-committed, falsifiable acceptance criteria
Registered before labelling begins, in the manifest, mirroring
`soc_calibration.json`'s `gate_note` ("pre-committed bar: unanimous-band accuracy ≥ 0.85").

1. **Person-year-weighted overall accuracy ≥ 0.85** on S1. (Anchors: the SOC jury's
   unanimous band measured **0.887**; industry L1 measured **P/R 0.862**.)
2. **Every FUNCTION holding ≥3% of person-years: precision ≥ 0.80 and recall ≥ 0.70.**
3. **Beats the shipped tree by ≥ 8 points** person-year-weighted, with a paired-bootstrap
   95% CI on the difference excluding 0.
4. **Inter-human κ ≥ 0.75** on the 200-role double-labelled subsample.
5. **OTHER + NONOCC ≤ 8% of person-years, OTHER alone ≤ 4%** (today OTHER is 11.36%).
6. **Distilled tier held-out accuracy ≥ 0.75**; below that, the tail ships as OTHER rather
   than carrying a fabricated label.
7. **Batching does no harm:** on 500 Tier-B roles labelled both batched-20 and
   unbatched-1, item-level agreement ≥ 0.95. Below that, Tier B reverts to 1 role/call and
   the runtime estimate in §4 roughly quintuples — a cost hit, not a correctness hit.

**Failing 1, 2, 3 or 4 kills the proposal.** The correct response is to keep the shipped
decision tree, publish the measured gold numbers for it, and spend the saved effort on
Phase 5. That outcome is still a large net gain over today, because the tree's accuracy
would finally be known.

---

## 6. Honest weaknesses — where this is *worse* than the shipped tree

1. **Reproducibility collapses.** `archetype_spec.py` is a pure function of ~200 lines of
   regex: anyone clones the repo and reproduces `role_archetype.parquet` bit-identically
   in seconds, offline. This proposal's output depends on a multi-hundred-megabyte vote
   cache (`career_clean/results/soc_votes.jsonl` is already **405,773,482 bytes**), on
   specific quantized model builds, on two specific machines reachable over tailscale.
   The frozen keyed cache makes *re-runs* deterministic, but a reviewer cannot regenerate
   it from scratch without ~30 GPU-hours and the same hardware. That is a real loss.
2. **LLM drift.** At temperature 0 with a fixed seed, quantized MoE inference is still not
   bit-reproducible across llama.cpp builds. The unanimity gate converts drift into
   *abstention* rather than *error* — but the abstention rate drifts, so coverage is not
   stable across rebuilds, and coverage is a headline number.
3. **Unanimity is expensive and a 16-way task is harder than a 23-way SOC task.** The
   shipped SOC jury rejected **23.3%** of everything it saw (81,460 disagree + 9,780
   abstain of 391,027). Archetype boundaries are *fuzzier* than SOC major groups —
   ANALYZE/OPS_PM, MARKET/SELL, RESEARCH/LAW are genuinely contestable — so expect a lower
   unanimity rate. Every point of lost unanimity is a point of lost person-year coverage
   pushed into review or OTHER.
4. **The O\*NET grounding is weaker than the framing suggests, and I will not oversell
   it.** Only **22.39%** of humanities person-years carry an O\*NET-rated SOC. The skill
   space will be beautifully coherent on that fifth and *silent* on the other 78%. Worse,
   the corpus's mass sits precisely where O\*NET is weakest: `president` (125,759 py),
   `owner`, `manager`, `partner` are titles O\*NET deliberately does not resolve. So these
   are **function archetypes with a skill-grounded label space** — not skill-space
   clusters. Calling them "skillset archetypes" would repeat the current module's sin.
5. **Two axes make the Sankey harder, not easier.** 16 functions × 6 contexts = 96 cells
   against a 12–15-node budget. Collapsing back to FUNCTION for the headline diagram
   discards exactly the CONTEXT information that justified the second axis; turning
   CONTEXT on produces a thinner, noisier, more suppression-limited diagram
   (`MIN_SUPPORT` n≥10, facet floor 5).
6. **Gold-set circularity is the failure mode most likely to actually happen.** If the
   human adjudication hours do not materialise, the gold degenerates into
   frontier-model-labels-scoring-small-model-labels, and this proposal ships something
   *worse* than the tree: an unearned accuracy number that invites false confidence.
7. **Iteration cost.** Fixing `SOC_DETAIL["19"]` is a 30-second edit and a 3-minute rerun.
   Moving the RESEARCH/LAW boundary here changes `schema_version`, busts every affected
   cache key, and costs hours to days of re-firing.
8. **Tail honesty is unchanged, just relabelled.** ~10% of person-years get a distilled
   label with ~0.75-ish accuracy. That is better than an unmeasured regex, but it is not
   good, and it must be shown as its own row in every coverage table.

---

## 7. Minimum viable test — ~3 human-hours, ~5 GPU-minutes

The entire thesis reduces to one claim: **an LLM jury on `role_text` beats the regex
ladder on the roles that carry the panel's mass.** Test it on 300 roles.

| # | step | time |
|---|---|---|
| 1 | Draw **S1-lite: 300 roles, PPS-sampled by humanities in-window person-years**, frozen salted hash. Emit a worksheet with `role_text`, top-3 `title_raw`, modal seniority, modal industry L1, 2 description snippets, and the person-year weight. | 30 min |
| 2 | **Hand-label all 300** against a provisional 16-value FUNCTION list. One person, one pass. Record every genuinely ambiguous case — that count *is* the taxonomy health check, and it is the cheapest possible proxy for criterion 4 (κ). | 60 min |
| 3 | **Score the shipped `role_archetype.parquet` against these 300, person-year weighted.** | 15 min |
| 4 | Fire the **existing** 2-juror local panel on the same 300 with an archetype prompt — reuse `soc_llm.py` almost verbatim (swap `soc_taxonomy` → `archetype_taxonomy`, keep `soc_anchors` retrieval, keep the cache). 300 × 2 = **600 units at 2.64 u/s = ~4 minutes of GPU.** | 60 min (mostly writing the taxonomy module) |
| 5 | Compare jury vs tree on the same 300; report jury unanimity coverage. | 15 min |

**Step 3 is the highest-value 15 minutes in this entire document, and it is worth doing
even if everything else is rejected** — it produces the first measured accuracy figure the
archetype layer has ever had.

**Kill criteria:**
- Tree scores **≥ 0.85** person-year-weighted ⇒ **thesis dead.** The regex ladder is
  adequate; spend the money on Phase 5 (visualization) instead.
- Jury unanimous-band accuracy **< 0.80**, or unanimity coverage **< 0.70** ⇒ the 16-way
  taxonomy is too fuzzy for a 4B/30B panel. Either collapse to ~10 functions, or restrict
  frontier-model labelling to Tier A only and distil harder.
- Jury beats tree by **< 5 points** ⇒ not worth 30 GPU-hours. Keep the tree — but **still
  build the full gold set**, because it converts every future claim in `FINDINGS.md` from
  unmeasured to measured, at 7 human-hours and a few dollars.
- Ambiguity rate in step 2 **> 15%** ⇒ fix the taxonomy before spending anything at all.
