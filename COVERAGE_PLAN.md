# Coverage improvement plan — four workstreams behind the Pathways portal

The portal pipeline (`portal/`) surfaced four constraints. This document is the plan for each,
in dependency order. The design constraints throughout: **reproducible** (single drivers, frozen
caches, manifests, tests), **transparent** (every derived value carries method provenance; every
inference is published with its measured error), and **precision-first** (coverage is never bought
with unmeasured accuracy; every new layer is gated on a gold-set evaluation before it feeds an
analysis).

Summary of the levers and expected effect:

| # | Workstream | Today | Expected after | Effort |
|---|---|---|---|---|
| 1 | Number freshness & governance | stale 186k/341k/597k cited in 3 docs | single source of truth, CI-checked | hours |
| 2 | Graduation-anchor recovery | 20.1% of CIP-coded bachelor records anchored | 60–90% (tiered, validated) | days |
| 3 | Occupation coverage | 21.5% of steps SOC-coded | 60–75% at measured precision | 1–2 weeks incl. a multi-day LLM run |
| 4 | Pathway mining viability | max chain support 8 persons; `paths=[]` | populated routes at n≥40 | days, after #2+#3 |

**Status (2026-07-07).** Plans 1 and 2 are **implemented and verified**.
Plan 1: `edu_clean/run_tier_counts.py` + `tier_counts.json` + drift/doc-lint tests, docs updated.
Plan 2: `edu_clean/anchors.py` + gold-set eval (`edu_clean/results/anchor_eval.json`). Gate
outcomes: **A2 accepted** (`start_year + 3`, empirically estimated — not +4; 80.4% of gold within
±1 yr, holds by decade and by major) and **A3 rejected** (~31% within ±1 yr across 5 rule
iterations and an offset grid — LinkedIn profiles omit early-career steps, a data-sparsity ceiling,
not a fixable rule; shipped implemented but experimental, excluded from `ANCHOR_TIERS` defaults).
Realized cohort growth is therefore **+7–11%**, not the hoped ~4–5× (which was contingent on A3):
windowed y10 English 3,299→3,581, Philosophy 976→1,078, baseline 108,236→120,167. Bias check
A1-only vs pooled: all deltas far under materiality bars; pooling is defensible. **Consequence for
Plan 4:** cohort growth will not unblock pathway mining; grain coarsening (via Plan 3) is now the
load-bearing lever, and the fallback to 2-step route segments is more likely to be needed.

---

## Plan 1 — Number freshness and governance (do first; hours)

**Problem.** The humanities tier totals grew ~30% when CIP coverage was ratcheted from 49.1% to
58.8% (now L1 240,277 / L2 415,908 / L3 689,836 records), but the old figures (186,018 / 341,113 /
597,144) are still cited in `edu_clean/HUMANITIES_CLASSIFICATION.md:167-169` (the origin table),
`PORTAL_PIPELINE_PROMPT.md:23` and `:116`, and by reference in mission documents and the prototype.
This is the second documented drift (the first: transition-typed share 72.3% → 65.6%). Drift is a
credibility risk for a project whose whole advocacy stance is methodological trustworthiness.

**Plan.**
1. **Single source of truth.** Add `edu_clean/run_tier_counts.py` (or extend the existing eval
   driver) that re-derives tier counts from `normalized/education.parquet` and writes
   `edu_clean/results/tier_counts.json` with the input parquet's content hash and the CIP coverage
   it was computed at. `portal/build.py` already re-derives; point it at the same module so the
   two can never disagree.
2. **Update the citing docs** to state the current numbers *with their coverage denominator*
   ("at 58.8% CIP coverage") and a pointer to the results JSON, so the next ratchet makes the
   dependency visible instead of silently invalidating prose. Mark the old table in
   `HUMANITIES_CLASSIFICATION.md` as superseded rather than deleting it (provenance).
3. **Drift check in tests.** A small test (pattern exists in `portal/portal_tests.py`) asserting
   the JSON matches a fresh re-derivation; run it in the same pass as the portal tests. Optionally
   a grep-based doc-lint that flags any hard-coded six-digit tier count outside the results files.
4. **Update the prototype** (methods page tier table + boundary control) to 240,277 / 415,908 /
   689,836 — these are green-badge numbers.

**Note on framing:** the counts will move again (Plan 2 and future CIP ratchets). All public prose
should say "as of the <date> build" — the portal JSON already carries `generated` for this.

---

## Plan 2 — Graduation-anchor recovery (the highest-value lever; days)

**Problem.** Only 20.1% of CIP-coded bachelor records carry a usable `end_year`, so equal-window
analyses drop ~80% of every cohort (English: 29,034 persons → 3,299 windowed at year 10). The
investigation established the key facts:

- The missing dates are **genuinely absent at the source**, not parse failures (`TRY_CAST`
  failures = 0; `end_year` is never present without `start_year`; raw fields are clean 4-digit
  year strings only — `parsed/education`, `build_normalized.py:440-441`). Nothing is recoverable
  by better parsing.
- Recovery substrates that DO exist: 32,184 CIP-bachelor rows have `start_year` but no end;
  ~77% have neither date but the person's **career steps are 99.25% datable**; 19.6% of no-date
  rows carry a free-text `description`.

**Plan: a tiered anchor with per-person method provenance.** Replace the single anchor rule with
`anchor_year` + `anchor_method` ∈ {A1, A2, A3}, computed in a new `edu_clean/anchors.py` (shared
by portal and cohorts):

- **A1 — observed** (today's rule): earliest usable `end_year` among qualifying degrees.
  Gold standard; unchanged.
- **A2 — start-plus-duration**: `start_year + d̂(degree_level)` for records with start only.
  Estimate `d̂` empirically from the 220,421 both-dates CIP-bachelor rows (median duration by
  degree level and, if it matters, by decade), don't assume 4. Adds ~32k CIP-bachelor records
  (~15% relative gain) — modest but nearly free.
- **A3 — career-onset inference**: for persons with no education dates at all, infer the anchor
  from the start of the first plausible post-degree career step. This is the big lever (~77% of
  the population, with 99.25%-datable careers). Definition to be tuned on gold (see below), e.g.
  "start year of the first non-student, non-internship primary step," possibly with a small
  calibrated offset.

**Validation harness (the gate).** The A1 population is a built-in gold set. Hold out the A1
persons, apply the A2 and A3 predictors to them as if their `end_year` were unknown, and measure
the error distribution (median error, share within ±1 and ±2 years), overall and by entry decade.
Acceptance gates, proposed: a method ships only if ≥80% of gold predictions fall within ±1 year;
otherwise it stays a labeled experiment. Publish the error table in `edu_clean/FINDINGS.md`
whatever the outcome.

**Bias check (required, not optional).** A3-anchored people differ systematically from A1 people
(they chose not to date their education). Before mixing tiers in a headline analysis, compare
A1-only vs A1+A2+A3 results on the portal's own statistics (fan shares, up-share, curves). If the
tiers disagree materially, report tiered results; if they agree, say so and pool. This is the
same discipline the repo already applies to survivorship.

**Integration.** `portal/common.py` gains an `ANCHOR_TIERS` config (default: all accepted tiers);
`portal_data.json` gains per-major `anchor_method_mix` so the UI can state what share of a cohort
is inferred. Windowing logic is unchanged — only anchor coverage grows. Expected effect: windowed
cohorts grow ~4–5× (Philosophy 976 → ~4–5k; baseline 108k → ~500k), which directly feeds Plan 4.

---

## Plan 3 — Occupation coverage scale-up (1–2 weeks; the industry playbook, reapplied)

**Problem.** 21.5% of steps carry a SOC code (`career_clean/occupation.py`'s deterministic,
precision-first cascade; ambiguous and generic titles deliberately uncoded). Consequences: the
year-10 fan is ~76–80% "unclassifiable," breadth/distinctive metrics are starved, and the
occupation-grain network covers only 7.8% of transitions.

**What's already in place.**
- A propose-only **anchored-embedding queue**: `normalized/mappings/career_occupation_proposals.parquet`,
  1,898,602 title→SOC proposals with cosine scores (92.6% potential coverage, est. precision ~0.80
  by analogy to the CIP task — not production-grade alone).
- The uncoded mass is **head-heavy**: 7,609 role canonicals cover 50% of uncoded steps; the top
  canonicals are the deliberately-blocked generics (`manager`, `owner`, `consultant`, `sales`…).
- 51.8% of uncoded steps carry a free-text description, currently mined only for the 459k
  self-employment rows.
- A proven scale template: the industry module's LLM pipeline classified a 2.03M-item residual at
  99.8% completion in ~6 days on local hardware, with jury calibration holding L1 precision at
  0.96 (`industry/METHODS.md`; frozen content-hashed vote cache; strict enum schema;
  reason-before-verdict; agreement-band acceptance, not verbalized confidence).

**Plan: an LLM title/context jury, fused with the embedding queue, calibrated like industry.**

1. **Unit of work = (role_canonical, context bundle).** For head canonicals (freq ≥ some floor),
   classify the canonical once and propagate — exactly the industry "label companies, not jobs"
   move. Context bundle: the canonical's most frequent raw titles, plus (for generic titles) up to
   3 sampled descriptions and modal industry — the evidence that makes `manager` decidable or
   honestly abstainable.
2. **Two-stage taxonomy to keep the enum tight.** Stage 1: SOC major group (23-way enum +
   abstain). Stage 2: detailed SOC within the chosen group (each group is a small enum). The fan,
   breadth, and pathway features need stage 1 far more than stage 2; accept different precision
   gates per stage (proposal: ship stage 1 at measured P ≥ 0.93, stage 2 at P ≥ 0.85, else the
   step stays uncoded at that depth).
3. **Fusion rule for cheap precision:** where the anchored-embedding proposal and the LLM vote
   agree on the detailed SOC, accept at high confidence (two independent methods); where they
   disagree, jury the item (3 diverse local jurors, tau=0.5 agreement bands) or leave it in the
   review queue. This upgrades the existing 1.9M-row proposals parquet from "review queue" to a
   fusion input at near-zero cost.
4. **Gold sets, before the big run.** (a) Reuse the deterministic layer: sample coded titles,
   strip the code, check the LLM recovers it (cheap recall/precision floor). (b) A hand-curated
   ~150-pair hard set mirroring the industry residual gold: generics with/without disambiguating
   descriptions, cross-cutting titles, seniority-only titles — including cases whose correct
   answer is *abstain*. Calibrate agreement bands on this before firing the bulk run.
5. **Run mechanics: reuse, don't rebuild.** The `llm_pool` host pool, frozen content-hashed vote
   cache (`PROMPT_VERSION`, input-hash keyed, resumable), frequency-ordered firing, and the
   <0.1%-new-votes stop rule port directly. Volume: labeling the top ~900k canonicals (80% of
   uncoded step mass) at industry-run throughput (~2.3 items/s pooled) ≈ 4.5 days; the top ~100k
   (which is most of the head value) ≈ half a day. Start with the 100k head, evaluate, then decide
   whether the tail run pays.
6. **Provenance and governance.** LLM/fusion codes land in separate columns
   (`soc_llm`, `soc_method`, `soc_agreement`), propose-only against the deterministic backbone,
   exactly like `llm_*` in industry. Downstream consumers opt in per analysis and must state which
   layers they consume. All-local open-weight models, no PII egress; cloud calls only for gold
   calibration if at all.

**Fan presentation (the product decision this unblocks).** Even at ~70% coverage an unclassified
bucket remains. Recommendation: keep the fan honest — shares of the whole windowed population with
a visible "not classifiable" bar and the coverage number in the caption; offer "among classified"
as a secondary toggle, never the default. No silent renormalization.

---

## Plan 4 — Pathway mining viability (days, after Plans 2–3)

**Problem.** The spec's 3–4-step role-canonical chains at n ≥ 40 found a maximum support of 8
persons. Two causes, both structural: cohorts are 1–5k people (Plan 2 fixes: ~4–5×), and the role
grain is absurdly fine — 1.9M canonicals produced by token-sort-concat (`managerproject`,
`engineersoftware`; `final_hybrid.py:289`), with no synonym merging and no human-readable labels
(career-clean audit finding #7).

**Plan.**
1. **Coarsen the grain into named role families.** Two complementary routes, in order of
   preference: (a) once Plan 3 lands, map steps to **detailed SOC** (or SOC minor group) and mine
   chains at that grain — it is human-readable, externally defined, and defensible; (b) for the
   still-uncoded remainder, cluster role canonicals into ~2–5k role families
   (embedding + community detection over the existing role-transition network), each family
   named by its most frequent raw title, hand-reviewed for the top families by step mass. Every
   family keeps its member list (reproducible, inspectable).
2. **Re-mine with the existing machinery.** `portal/pathways.py` needs only a grain swap — the
   n-gram/person-support/suppression logic and the `unexpected` flag are already built and tested.
   Keep n ≥ 40 and the [2,40) suppressed-count reporting.
3. **Relax length before support.** If 3-step chains still fall short for small majors, publish
   2-step **route segments** (still real, still counted) rather than lowering n. A segment chain
   can be composed editorially into a vignette while remaining honest about what was measured.
4. **Formalize "unexpected."** Current implementation (terminal SOC group outside the major's
   top-5 fan) is reasonable; add the alternative the pipeline agent proposed — terminal-group RR
   below ~1.2 for the major overall while route support clears n ≥ 40 ("individually well-trodden
   route into a collectively rare destination") — and pick on the real data. Document the chosen
   definition in `portal/FINDINGS.md`; the UI already explains the tag in one sentence.
5. **Editorial naming stays human.** The pipeline emits stages, supports, dwell medians, and the
   unexpected flag with `name: null`; NHA staff name routes and write gloss. This division is
   already reflected in the JSON contract.

**Sizing sanity check.** With ~4.5× cohorts (Plan 2) and a ~30× reduction in grain cardinality
(1.9M canonicals → ~5k families or ~800 detailed SOCs), repeat probability for a 3-step chain
rises by orders of magnitude; the English suppressed-route count (13 in [2,40) at today's grain)
should convert to dozens of routes clearing n ≥ 40. If it doesn't, the honest fallback is #3.

---

## Sequencing and verification

1. **Plan 1** immediately (hours, zero risk, removes a standing credibility bug).
2. **Plan 2** next — it multiplies every downstream sample and is pure local computation with a
   built-in gold set.
3. **Plan 3** in parallel with Plan 2's validation (the gold-set build and 100k-head run don't
   depend on anchors). Bulk tail run only after the head-run evaluation.
4. **Plan 4** last, on top of both.

After each plan lands: re-run `portal.run_portal_data` + tests, diff `portal_data.json`, update
`portal/FINDINGS.md` with the new funnel table, and refresh the prototype's badges (illustrative →
pipeline data) only for panels whose numbers now come from gated, validated layers. Every plan's
driver must be a single reproducible command with a manifest, in keeping with the rest of the repo.
