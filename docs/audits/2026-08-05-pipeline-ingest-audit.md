# Ingest / parse / normalize / consolidate audit

**Date:** 2026-08-05. **Scope:** `parse_linkedin.py`, `build_normalized.py`, the
`career_clean` / `edu_clean` canonicalizers as production writers, and
`paths/build_spine.py` — the code path from `data/*.jsonl` to
`paths/transitions.parquet`. **Question asked:** is the pipeline losing usable
data on its way to the career-possibility-space product?

Every number below was measured during this audit against the committed
artifacts (DuckDB whole-table scans) or against the raw JSONL (160,000-record
head sample across all 8 files, ~8% of the corpus; per-table element ratios
match the full parse manifest to three significant figures). Rejected
candidates are kept in §4 so they stay rejected.

**Headline:** the parser is lossless and the normalizer's data model is right.
The losses are all in *consolidation* — three facts the project has already
established but that never reached the tables that need them, plus a
one-character error in the snapshot anchor that silently deletes the most recent
year of every career.

---

## 1. The snapshot anchor is off by one year

`paths/common.SNAPSHOT_DATE = "2025-02-19"`. The correct value is
**2026-02-19**.

The constant's own comment says "Raw snapshot files are dated 2025-02-19." The
files are dated **2026**-02-19:

```
data/snap_mlsi9jwqziij1k8zq.1.jsonl  mtime=2026-02-19 07:25:57
...all eight identical to the minute
```

The constant was introduced 2026-06-10, four months after the download, when
`ls -l` had stopped printing the year. Three independent estimators agree with
the file dates and disagree with the constant:

| Estimator | Latest observed |
|---|---|
| `posts.created_at` | Feb 2026 (1,104 posts, partial month) |
| `certifications.meta` "Issued …" | Feb 2026 (1,160 credentials, partial month) |
| `career_steps.start_date` | Oct 2025 at full monthly volume (10,630), cliff to 334 in Nov |

Under a 2025-02-19 anchor, 182,634 steps start in the future. They are not
garbage — they are Mar–Oct 2025 starts, at normal monthly volume, on ongoing
roles.

What this costs, measured:

- **182,634 steps (163,499 persons) are dropped from the primary timeline.**
  `paths/build_spine.py` builds `prim` as `datable AND NOT bad_negative_duration
  AND NOT bad_future_start`. Every one of these rows trips both flags (its end
  is anchored to a date before its start), so it emits no transition edge.
  **167,368 of them are that person's most recent step** — the pipeline is
  systematically discarding current jobs, and preferentially those of people who
  moved most recently.
- **2,298,494 ongoing steps (1,709,814 persons) have their tenure truncated ~12
  months early.** Mean tenure on ongoing steps reads 88.3 months; corrected it is
  107.4. This propagates into `dwell_months`, the cohort survival and scarring
  phases, and — because `dur_days` is the second-ranked tiebreaker in
  `CONCURRENCY_SQL` — into which role is picked as primary when two overlap.
**Correction to a first draft of this section:** the year-grain constants are
*not* wrong, and cohort windows were not one year short. `SNAPSHOT_YEAR`
conflates two different facts, and every one of its ~25 use sites except three
wants the one that did not change:

- **last fully observed calendar year (2025)** — what equal-window discipline
  needs (`anchor <= SNAPSHOT_YEAR - N`), and what a graduation anchor bound
  needs (a 2026 `end_year` is a degree not yet earned). 2026 is observed only
  through February, so this stays 2025 under the corrected date.
- **calendar ceiling of the data (2026)** — what a step/panel-year cap needs
  (`year(start_dt) <= …`, `least(y1, …)`). Only three sites use it this way.

That conflation is what made the slip invisible: the constant was named for the
snapshot but used for the window, so nobody comparing it against the data
noticed the year was wrong.

**Fix, applied 2026-08-05.** `SNAPSHOT_DATE` corrected in `paths/common.py` and
`portal/common.py`; `paths/common.py` now carries `SNAPSHOT_YEAR = 2026` and
`LAST_COMPLETE_YEAR = 2025` as the documented source of truth, and
`portal/common.py` and `cohorts/common.py` gained `SNAPSHOT_CAL_YEAR = 2026`
for the ceiling sites (`portal/build.py` ×2, `portal/choices.py`,
`cohorts/build_panel.py` ×3, `cohorts/cohort_tests.py`). The three remaining
year constants (`build_normalized.EDU_SNAPSHOT_YEAR`,
`edu_clean/anchors.SNAPSHOT_YEAR`, `archetypes/common.SNAPSHOT_YEAR`) keep the
value 2025 with corrected documentation, and six hardcoded `2025` literals in
`edu_clean/run_anchor_eval.py` now reference the constant. A seventh site the
first pass missed, `cohorts/common.py`, is included.

Spine rebuilt through the full two-pass bootstrap (spine → role/occupation
networks → SpringRank → `paths.seniority` → spine pass 2):

| | before | after |
|---|---|---|
| `bad_future_start` | 182,634 | **0** |
| `bad_negative_duration` | 165,665 | **0** |
| transitions | 6,018,391 | **6,179,130** (+160,739) |
| typed edges at conf ≥ 0.3 | 3,950,920 | **4,647,558** (+696,638) |
| steps with a seniority score | 93.32% | **95.25%** |
| mean tenure, ongoing steps | 88.3 mo | **100.3 mo** |

`paths.spine_tests` and `paths.seniority_tests` both pass. Everything
downstream of the spine — cohorts panel, industry, archetypes, portal — is now
stale against it and needs rebuilding.

---

## 2. The SOC jury never reached `career_steps`, so the spine cannot see occupation changes

`normalized/mappings/role_soc_jury.parquet` was merged on 2026-07-11: 299,787
accepted role strings covering 4,330,823 steps, at a calibrated unanimous-band
accuracy of 0.887 against a pre-committed 0.85 gate. `portal/common.py` and
`archetypes/common.py` both consume it. Nothing else does.

`build_normalized.write_career_steps` joins only the deterministic O*NET
mapping, so `career_steps.occupation_code` is populated on **21.46%** of steps
(8,189,112 of 10,800,787 rows carry `occupation_method = 'unmatched'`). Every
consumer that reads `career_steps` rather than re-deriving the union inherits
that number: `paths/build_spine.py`, `cohorts/build_panel.py`, and
`industry/common.py`.

Measured uplift from a single left join the pipeline already knows how to write:

| Grain | Deterministic only | + jury |
|---|---|---|
| Steps with a SOC major | 21.46% | **61.53%** |
| Humanities steps (`hum_l1_any`) with a SOC major | 21.45% | **61.59%** |
| Transitions with *both* endpoints coded | 471,815 (7.8%) | **2,567,413 (42.7%)** |
| Observable occupation changes | 127,848 | **1,171,556** |

The last row is the one that matters for the product. "What occupations do
humanities graduates move between" is the possibility-space question, and the
transition network can currently see 11% of the answer. The spine's
`transition_type` ladder tests `substr(occupation, 1, 2) <> substr(...)` at
exactly the major-group grain the jury emits, so the codes are drop-in.

Join safety checked three ways: the mapping is unique on `role_canonical`
(299,787 rows / 299,787 keys, all unanimous) so there is no fan-out; the jury
was fired only on the uncoded tail, so it overlaps the deterministic codes on
**zero** rows and needs no precedence rule; and `reference/soc_status.parquet`
is keyed on 7-character detailed SOC, so the 2-digit jury code must land in a
**new column** (`soc_major` + `soc_major_source`, mirroring
`archetypes/common.soc_major_expr`) rather than overwrite `occupation_code`.

Adding a third source, `functional_cluster` for the self-employed, adds a
further 117,206 steps (62.6% total) on the same pattern.

---

## 2a. Where the jury should spend its next GPU-hour

Measured from `soc_votes.jsonl` (786,986 cached votes) against
`soc_candidates.parquet`. The uncoded candidate universe is 2,585,368 strings /
8,369,415 steps.

| Band | Strings | Steps | Status |
|---|---|---|---|
| accepted (unanimous) | 300,831 | 4,863,186 | merged |
| **disagree** | **81,616** | **990,106** | paid for twice, discarded |
| abstain | 9,802 | 323,004 | honest refusal on status titles; leave alone |
| **unvoted** | **2,193,119** | **2,193,119** | every one a hapax |

**The tail is exhausted, not half-done.** The jury has already voted on every
candidate string that occurs more than once in the corpus: the 2,193,119
unvoted strings carry exactly one step each. They do not deduplicate —
2,193,112 distinct `role_display` values — and only 11 of them share a display
with an already-voted string. Voting them costs 4.39M calls, 5.6× the entire
run to date, for a ceiling of 2.19M steps: 0.5 steps per call before the
observed 21% disagreement and 2.5% abstention, against 6.2 steps per call for
the run so far.

It is also the slice where the jury is *least* reliable. O*NET anchor
availability, sampled:

| Band | With an anchor |
|---|---|
| accepted | 71.3% |
| unvoted tail | 44.5% |
| disagree | 35.7% |

More than half the tail carries no reference conventions at all — and the
reference conventions are exactly what took calibration from 0.693 (v1, failed
its gate) to 0.887 (v2, passed). Expanding the tail would spend 5.6× the
compute on the lowest-precision population in the corpus. **Recommendation: stop
expanding it.**

**The recoverable data is the disagreement band.** 990,106 steps, already voted
twice, currently discarded — 16% of all voted steps. Recovering it would take
SOC-major coverage from 61.5% to about 70.7%.

The disagreements are not diffuse, and their shape says this is a rubric
problem rather than a tiebreaker problem. The top 12 code pairs are 63.6% of
disagreement steps, and the manager boundary dominates:

| Pair | Steps | Share |
|---|---|---|
| 11 Management / 13 Business & Financial | 170,767 | 17.2% |
| 11 Management / 15 Computer & Mathematical | 102,224 | 10.3% |
| 11 Management / 43 Office & Admin Support | 85,662 | 8.7% |
| 13 Business & Financial / 41 Sales | 59,632 | 6.0% |
| 13 Business & Financial / 43 Office & Admin | 54,823 | 5.5% |

11-vs-something is 45.7% of disagreement steps; 13-vs-something a further
13.8%. Rule 3 of the current rubric already governs this exact boundary
("a manager who RUNS a function is 11; a specialist working WITHIN a function
is not"), so it is under-specified for these cases rather than absent — the
same failure mode anchors fixed in v1.

**Proposed sequence, cheapest first:**

1. **Enlarge the calibration sample.** Only 74 of 600 gold strings landed in the
   disagree band — too few to gate a decision on (roughly ±11pp at 95%).
   `SAMPLE_PER_TERCILE` 200 → ~667 gives ~2,000 gold strings and ~250
   disagreement cases. Cost: ~4,000 calls. Gold strings are deterministically
   coded and so anchor-rich, which the existing gate note already flags as
   selection bias; the disagree-within-gold subset is the closest honest
   analogue available for this decision.
2. **Sharpen rule 3 on the measured confusion pairs**, bump `PROMPT_VERSION`,
   and re-fire the 81,616 disagreement strings only — 163,232 calls, 21% of the
   run to date.
3. **Re-measure the unanimous band** on the enlarged gold against the same
   pre-committed 0.85 bar, and merge only on a pass. If a 2-of-3 tiebreaker is
   wanted as well, measure that band separately and give it its own value in the
   mapping's existing `method` column, so consumers can drop it independently.
   Do not assume it inherits the unanimous band's precision: 2-of-3 is a
   strictly weaker gate, and the band it targets is the anchor-poor one.

### 2b. What to do about the 2.19M hapax steps

They are worth more than their 20% share of steps suggests, because an edge
needs *both* endpoints coded and hapax steps are scattered across half the
population. Transition endpoints, classified:

| from → to | edges | share |
|---|---|---|
| coded → coded (**usable now**) | 2,633,465 | 42.6% |
| one endpoint hapax | 1,207,634 | 19.6% |
| both endpoints hapax | 488,774 | 7.9% |

Coding the tail would unlock 1,696,408 more edges — **+64%** on the usable edge
list.

But it is a network-density problem, not a population-coverage one. 1,024,970
persons have at least one hapax step; **943,188 of them (92%) also have a coded
step** and stay visible. Only **81,782 persons (4.1%)** have nothing but hapax
steps. Nobody should worry that the possibility space is missing people.

**Route 1 — bridge across uncoded steps. Free, no inference, do it.** Emit
edges between a person's consecutive *coded* steps rather than consecutive
steps, carrying a `steps_skipped` count. This asserts only what the data says —
this person's coded occupation went A → C, with n steps in between we cannot
code — and invents no label. Measured: **+683,702 new edges (+26%)**, of which
**417,180 are occupation changes** (against 1,200,126 on the adjacent edge
list). A bridged edge is not an adjacent move, so its dwell/gap semantics
differ; it must be flagged and never pooled with adjacent edges unlabelled.

**Route 2 — actually coding the tail is currently ungate-able, and that, not
compute, is the blocker.** Ground truth exists only where the deterministic
matcher succeeded, which is exactly where strings sit close to the O*NET
lexicon. Measured anchor availability:

| Population | With an anchor |
|---|---|
| coded hapax strings (the only labelled analogue, n=5,240) | **78.4%** |
| uncoded hapax tail (the target) | **44.5%** |

The labelled hapaxes are anchor-*richer* than the unlabelled ones, by
construction. So the existing gold cannot gate any tail method — LLM,
distilled classifier, or embedding kNN alike. For the head this was a
documented caveat; for the tail it is disqualifying.

**The unblocking move is small and human.** Hand-label a stratified sample of
~400 anchor-poor uncoded tail strings — the only thing that makes any tail
method falsifiable. (A frontier model could produce silver labels far faster;
that is defensible if it is a different model class from the jurors and is
labelled silver, never gold.) Once that sample exists, three cheap methods
become decidable, all abstention-thresholdable to whatever precision bar is
set:

- **batched jury** — 20 strings per call against an array-output grammar cuts
  the tail from 4.39M calls to ~219k. Randomize batch composition per juror, or
  correlated within-batch errors will inflate apparent unanimity.
- **a classifier distilled** from the 2.1M labels already in hand
  (1.83M deterministic + 300k accepted jury), thresholded on predicted
  probability.
- **embedding kNN** to the O*NET lexicon, which reaches semantic neighbours
  token-Jaccard cannot.

Until that sample exists, route 1 is the whole of what can be honestly shipped.

**Two mechanical notes.**

`n_steps` is rendered into `evidence_text` and therefore into the cache key
(`sha256(evidence + model + prompt_version + schema_version + n_codes)`). It
tells the model nothing about what a job is, but it makes 787k cached votes
hostage to any rebuild that shifts step counts, and it makes every prompt unique
below the system block. Drop it at the next `PROMPT_VERSION` bump. (Checked: the
2026-08-05 spine rebuild did **not** shift `n_steps` — the uncoded population is
identical — so the cache is intact.)

A cheap-first cascade — fire the 4B juror on everything, call the 30B MoE only
where the 4B did not abstain — is provably lossless under strict unanimity,
because a pair containing an abstention can never be accepted. It saves 0.95%
of calls (the 4B juror's abstention rate). Not worth the complexity.

---

## 3. `build_normalized.py` cannot run from a clean `parsed/`

`write_education_person` selects `degree_level_pooled`, `cip2_pooled`,
`nha_level_pooled`, and `humanities_field_group_pooled` from
`education.parquet`. `write_education`, twenty lines earlier in the same file,
does not emit those columns — they are appended afterwards by
`edu_clean/apply_cip_pooled.py` and `apply_degree_level_pooled.py`.

Verified by running `write_education_person` against a synthesized
`education.parquet` carrying exactly the columns `write_education` writes:

```
Binder Error: Referenced column "degree_level_pooled" not found in FROM clause!
```

So `uv run python build_normalized.py`, the command README.md gives as stage 2,
hard-fails on a fresh checkout. The real order is build → `apply_cip_pooled`
→ `apply_degree_level_pooled` → `rebuild_education_person` →
`apply_institution_meta`, documented only inside `EDU_PIPELINE_UPGRADE_PLAN.md`.
The committed parquets are correct; the recipe for reproducing them is not.

Cheapest honest fix: have `write_education_person` `coalesce` the pooled columns
through a `columns()`-guarded existence check, or make the pooled columns
first-class outputs of `write_education`. Failing that, README.md's stage-2 row
must list all five commands.

---

## 4. Candidates checked and rejected

Each of these looked like a loss and is not. Recording them so they are not
re-investigated.

- **Unmapped raw fields.** A full key inventory of the raw JSONL (top level,
  list elements, and the doubly-nested `experience[].positions[]`) returns
  **zero** keys absent from `parse_linkedin.py`'s schema. The parser is
  field-complete. Row counts are exact end to end: 2,000,000 profiles, 0 JSON
  errors, and `experience` (8,012,238 singles) + `positions` (2,788,549) =
  10,800,787 = `career_steps` rows.
- **The dropped parent-experience rollups.** `_CAREER_STEPS_CTE` discards the
  1,064,368 parent rows that have `positions` children. This is lossless for
  the fields that matter: 1,064,075 of them (99.97%) have `title` identical to
  `company`, 12 carry a description, 19 carry a start date. The data model is
  right.
- **Date parsing.** 0 unparsed `start_date` values and 487 unparsed `end_date`
  values (all field-shift artifacts like `"1 year 5 months"`) out of 10.8M
  steps. 80,414 steps carry no dates at all, and none of them carry a `duration`
  string to reconstruct from. `frac_datable = 0.9925` is the true ceiling.
- **Education years.** 0 raw `start_year`/`end_year` strings fail `TRY_CAST`.
  The 21.6% end-year coverage is a source-data fact, not a parse loss, and
  confirms the existing "graduation year for the other 85%" non-lever.
- **`educations_details`** (96% populated) is the school name only, and
  `education[].title` is already 99.9% populated. Nothing to rescue.
- **`is_duplicate` is not filtered by the spine**, but exact repeats overlap
  100% and are eliminated by the Layer-4 concurrency rule before edges are
  built: zero same-company, same-role, same-start-date self-loops in
  `transitions.parquet`. Safe as-is.
- **`MAX_STEPS_PER_PROFILE = 100`** drops 13 profiles and 2,435 steps. Noise.
- **Duplicate `linkedin_id`s**: 27 ids, 74 rows. 22 profiles have a null
  `linkedin_id` (their child rows fall back to `id`, which is 100% populated).
  Noise.

---

## 5. Smaller, real, and cheap

- **Position location backfill.** Positions inherit `company` and `company_id`
  from their parent experience but not `location`. **257,357 position rows**
  have no location where their parent has one — a two-line `coalesce` in
  `_CAREER_STEPS_CTE`. (Descriptions were checked on the same join and are
  worth 17 rows; skip them.)
- **The location gazetteer tail.** 748,441 rows carry a populated `location`
  string that `career_clean/location.py` returns `unparsed` for — 10.9% of
  populated rows. The head of that tail is thin and heterogeneous: bare US
  cities without a state (Irvine 991, Santa Monica 803), informal US regions
  (Southern California 3,120, New England 1,092, Northern Virginia 682, DFW
  700), lowercase state abbreviations (`Atlanta, Ga` 676), and countries missing
  from the curated head list (Afghanistan 985, `Kabul, Afghanistan` 864). A
  grind, not a lever; worth a few points of coverage if geography becomes a
  product.
- **`Remote` is being thrown away as a failed place-parse.** 27,144 rows say
  "Remote", plus Virtual (1,338), Online (1,138), Worldwide (1,957), Global
  (2,549), Nationwide (1,224). These are not locations that failed to parse;
  they are a work-arrangement signal the corpus records nowhere else. A
  `location_mode` axis on the same mapping would cost nothing and is directly
  relevant to what students ask about.
- **Bachelor-year rescue from `start_year`.** 40,622 bachelor rows carry a start
  year and no end year; taking a start-anchored estimate would give **4,227**
  additional `hum_l1_any` persons a graduation anchor, against a current base of
  40,802 (+10.4%). This manufactures a year, so it belongs behind an explicit
  `bachelor_end_year_method` column or nowhere.
- **Profile `city` / `country_code`** are 100% populated and never joined to
  career steps. 888,525 *ongoing* steps have no location of their own, and the
  profile's current city is a defensible fill for exactly those. It is not
  defensible for the 3.9M historical steps that also lack one.

---

## Sequencing

§1 first and alone: it is one constant, it invalidates every timing artifact
downstream, and every other item is cheaper to do once on corrected dates. §2
second — it is a single left join and a new column, and it is what turns the
transition network from 128k observable occupation moves into 1.17M. §3
whenever the education side is next touched, since the committed outputs are
already correct. §5 opportunistically.
