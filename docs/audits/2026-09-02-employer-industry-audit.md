# Green / red / refactor audit: employer and industry data

**Date:** 2026-09-02. **Branch:** `recovery-refactor` @ 9990a7a (clean; PR #1 open against `main`).
**Method:** three parallel read-only audits (green = what is there and what can still be
gained; red = what is wrong; refactor = what structure blocks the work), each with its own
DuckDB queries, followed by coordinator re-verification of every headline claim below.
Nothing was built, fired, or edited. Full team reports with the queries that produced each
number are in `docs/audits/2026-09-02-teams/{green,red,refactor}.md`.
**Focus, per the owner:** what still needs to be done to get as much as possible out of the
employer data and the industry data.

Tests and lint at the start of the audit: `make test` (8 suites) passes in 5 s; `make lint` clean.
Hosts: local 5080 Ollama and llama-server (qwen3-4b-q4) up; Framework Desktop
(100.73.40.75) unreachable on every port, as it has been since the evening of 2026-09-01.

---

## 1. The picture

Industry coverage is 53% of career steps at L1, and that number is made of exactly two things:
214 name-token rules and 2,075 curated company ids. The 2.02M-company LLM jury run from June
never entered the spine and its vote cache was destroyed on 2026-09-01, so today there is no
propose-only industry layer at all. Worse, a material share of the 53% is wrong: the name
rules misfire on 3.34M rows in ways nobody measured (PG&E is construction, Columbia University
is local government, Goodwill is manufacturing), and the company canonicalizer glues 631k
id-less rows to company ids taken from one or two stray rows (University of Pittsburgh is UPMC
and therefore a hospital; "Independent" is an area agency on aging).

The good news is that the unresolved head is steep and cheap. Labeling 2,313 companies by hand
lifts L1 coverage from 53% to 60%; 9,436 gets 65%; 27,485 gets 70%. Every one of them has a
LinkedIn id, employee titles, and job descriptions on file. Separately, 454k university-employer
rows can get a stable key from the `linkedin.com/school/<slug>` URL the parser already stores,
which also fixes the worst of the inherited-id damage and joins to IPEDS for public/private
control.

Two pipeline facts undercut everything downstream until fixed: the pooled SOC column landed
yesterday is read by no consumer (the paths spine, cohorts panel, and transition network still
use the 21% deterministic code; archetypes and the portal each re-derive their own), and the
downstream refresh driver runs archetypes before the tables it reads and never runs the network
analysis step, so the shipped portal reflects an August analysis file and a pre-rebuild
education table.

---

## 2. Verified state

| Claim | On disk 2026-09-02 | Source |
|---|---|---|
| SOC-major row coverage 61.5% | 6,645,746 / 10,800,787 = 61.53% (det 21.46%, jury 40.07%) | green A.1 |
| Person CIP coverage 96.29% | 1,925,741 / 1,999,974 | green A.1 |
| Industry L1 row coverage "53.6%" | 53.6% is company-weighted; **53.03% step-weighted** (5,726,073 / 10,798,794) | green A.1 |
| Industry L2 / L3 step-weighted | 48.0% / 23.3% (must gate on `l1 <> 'XOT'`; `l2` is non-NULL on every XOT row) | green A.1 |
| Cert axis 545k persons | 545,409 (`normalized/certifications_person.parquet`); **no consumer reads it** | green A.1, refactor A.2 |
| Industry LLM layer | `llm_*` columns all NULL, `llm_candidates: 0` | manifest |
| Pooled SOC consumers | zero modules read `occupation_major_pooled` / `occupation_source` | coordinator grep |
| Transition network, occupation axis | 484,426 / 6,179,130 transitions = 7.8% covered (role axis 97.5%) | `occupation_manifest.json` |
| Company / employment-type network axes | registered in code, never built; no industry axis exists | coordinator |

Staleness (green A.2, refactor A.4): the 2026-09-01 refresh ran 21:11-21:16; `education.parquet`
was rebuilt at 21:27, after it. Archetypes ran before paths and cohorts rewrote their inputs.
`transition_network/occupation_nodes_analyzed.parquet` (portal input) is dated 2026-08-05;
`paths/seniority_scores.parquet` 2026-08-05; enrichment and the cohort analyses 2026-07-22.

---

## 3. What is wrong today (ranked)

Severity: CRITICAL = wrong numbers reach the portal; HIGH = wrong data in a normalized or
industry table; MEDIUM = fragile, untested, or misleading. Every item re-verified by the
coordinator unless marked (team).

**C1. Modal-id inheritance in company canonicalization.** `career_clean/common.py::export_vocab`
assigns each company string the most common `company_id` among only its id-bearing rows, with
no support threshold; `final_hybrid.canon_company_value` stamps it on every row of the string
at confidence 1.0. Measured: 631,105 rows carry an id they never had; 292,317 of them come from
strings where fewer than half the rows have any id. Universities are the main victim because
LinkedIn links them as `/school/` pages with no company id: University of Michigan (2,872 rows)
is `center-for-managing-chronic-disease`; University of Pittsburgh (1,562) is `upmc` and thus
curated `HLT.PROV.HOSP`; Stanford is `stanfordbloodcenter`; Harvard is `harvardcid`.
Placeholders became employers: "Independent" (2,324 rows), "Home" (1,938), "Consultant"
(1,742), "Contract" (308, glued to `salesforce`). The July promotion pass then labeled seven
ids by their inherited display (`ucsdhealth` = university, `consultant_66` = consultancy).
Fix: accept the modal id only when id-bearing rows >= max(3, 50% of the string's rows), same
gate in `_name_to_id_crosswalk`, extend `_PLACEHOLDER_EXACT`, and regenerate `curated_promoted`
afterwards. Pairs with E1 below (red C1, green B.2 item 5, C.3 E2).

**C2. Name rules misfire at scale.** 3.34M step rows (31%) are coded by a first-match scan of
214 tokens in which generic early tokens shadow specific later phrases. `electric` (21,809 rows)
sends PG&E, Schneider Electric, Westinghouse and American Electric Power to construction
trades while `electric power` fires zero times. `city of` codes Columbia University as local
government (1,207 rows). `department of` codes the Department of Defense as generic government
(4,441). `bank` catches 312 food banks; `industries` catches Goodwill; `farm` catches State
Farm, Perdue and Pepperidge Farm; `dairy` catches Dairy Queen; `motors` codes Lucid and Kia as
dealerships; `systems` codes BAE and General Dynamics Mission Systems as IT services;
`academy` codes Academy Sports as K-12; `school`/`medical` code Icahn, Harvard Business School
and Harvard Medical School as K-12 or ambulatory care. Conservative count of wrong-L1 rows from
the probes alone: about 40k; wrong-L2 rows are an order of magnitude more (`health` 243k rows
alone lumps Cardinal Health and the insurers into providers). No rule has ever been
precision-tested on real displays; the only negative fixture is one generic word.
Fix list and reorder in red C2; add a reachability test (every rule fires on its own keyword).

**H1. `step_industry.l1` holds dotted L2/L3 codes on 5,020 rows** (`build_industry.py:126-142`,
nonorg branch). The portal patches around it with `split_part`; archetypes reads it raw.

**H2. 1,993 career steps vanish in propagation** (NULL company key fails the `NOT LIKE` filter).
The 164k gap between `career_steps` and `sum(company_industry.freq)` is 162,250 `nonorg:` rows
plus these; no row-count assertion exists.

**H3. Curated confidence 1.0 is false for the 1,982 machine-promoted keys.** On the repo's own
residual gold the deterministic stack scores L2 0.919 / L3 0.815 / L4 0.5; AmeriCorps is coded
nonprofit. `industry/README.md` still says "Precision is 1.0 at L2-L4".

**H4. SOC jury labels include non-occupations.** Mechanics are sound (unique mapping, det =
2-digit prefix on all 2.32M rows, no fan-out, no intern-to-internist). But "Student" is coded
Education (12,452 rows), "Team"/"Program" Management (16.6k), nursing and medical students
Healthcare Practitioners (about 4.7k), and admin titles like Patient Access Specialist as
practitioners. `_non_occupation` filters eight strings. The career-side fingerprint assert
promised by PIPELINE.md and plan R1 does not exist. Fix is a filter extension and a re-merge;
no LLM needed.

**H5. Portal sector denominators (interpretive).** `industry_unresolved_share` for arts (63%)
is 18% "no observed job at year 10" plus 45% XOT. XOT among observed steps is 55% for arts vs
43% baseline, so arts sector bars are depressed by resolution rate, not employment (Media is
9.9% of the arts cohort but 27% of resolved arts persons). `needs_review` and `confidence`
reach no consumer; every XOT row carries `sector='private'`.

**H6. Pooled SOC is landed but unconsumed** (coordinator). `paths/build_spine.py:124,248,258`
and `cohorts/build_panel.py:98` use `occupation_code`; `archetypes/common.py:107` and
`portal/build.py:167` each LEFT JOIN `role_soc_jury.parquet` themselves. Three implementations
of one pooled column, and the transition network's occupation axis covers 7.8% of transitions
when the pooled major would cover roughly 38%.

**H7. `scripts/refresh_downstream.sh` is mis-ordered** (refactor A.4, verified). Stage order is
industry, archetypes, paths, cohorts, network, portal, share; archetypes reads `paths/steps`,
`paths/transitions` and `cohorts/panel`, all rewritten after it ran. `transition_network.analyze`
and `paths.seniority` are never run, so the portal consumed an August 5 analysis file. It
passes `--no-llm`, which will discard re-fired industry votes the day they exist.

**H8. Fresh rebuild is still broken on the career side** (refactor s0, verified).
`build_normalized.py:948` hard-joins `mappings/role_soc_jury.parquet`, which only the SOC jury
produces from `paths/steps` and `step_industry`, both downstream of `career_steps`. A fresh
clone cannot build `career_steps`.

**M1-M9 (team).** Fuzzy `typo_to_id` merges 1,875 non-Latin employer names onto one id (`.` =
`vip-cinema-seating`); the occupation prior has no minimum row count (133k of its 175k
companies have one row) and its arts/media majors are about 22% wrong at L1; the prior reads
the 21% deterministic SOC and so fires on none of the 113 largest unresolved companies;
`paths/build_spine.py` still re-parses raw dates (R7 "single parser" unmet, no unit test); 487
`end_date` values are duration strings; `SNAPSHOT_YEAR` is 2026 in `paths/common.py` and 2025
(meaning last complete year) in four other modules; `make test` is not data-independent;
manifests cannot establish currency; 69 of 88 duplicated step keys are unflagged.

---

## 4. What can still be gained

### 4.1 Industry: the cumulative curve (green B.1, verified at the 60% cut)

Unresolved companies sorted by row frequency, 100% acceptance, denominator 10,798,794 steps.

| Target L1 | Companies to label | Rows added | Have company id | Have descriptions |
|---|---|---|---|---|
| 55% | 117 | 213k | 116 | 117 |
| 60% | 2,313 | 753k | 2,270 | 2,313 |
| 65% | 9,436 | 1.29M | 9,255 | 9,436 |
| 70% | 27,485 | 1.83M | 26,772 | 27,477 |
| 75% | 72,058 | 2.37M | 68,437 | 71,579 |
| 80% | 177,613 | 2.91M | 154,973 | 167,204 |
| 90% | 910,538 | 3.99M | 684,429 | 616,387 |

The household-name head (MetLife, Siemens, Netflix, Uber, 3M, Aramark, Sodexo, TEKsystems,
SAIC, Peace Corps...) is unresolved for one reason: no curated entry, and brand names carry no
rule token by design. Evidence per company in ranks 1-30k is about 1,960 characters (display,
8 titles, 3 descriptions). Sibling ids fragment the head (Aon/aon-risk-services, 3m/3m_2,
netflix/netflixl): 14,755 displays sit under 32,858 ids, 1.14M rows.

For the humanities cohort (`hum_l1_any`, 293,808 persons, 1.73M steps) L1 coverage is 49.2%,
below the corpus, and the portal's year-10 endpoint is worse (arts 63% unresolved). The
humanities unresolved head is a different list: Netflix, Walt Disney World, Peace Corps,
Thomson Reuters, Teach For America, Houghton Mifflin Harcourt, SAG-AFTRA, UCLA, McGraw Hill,
Wiley, Christie's, Elsevier, YMCA. The global top-3k lifts the cohort to 56.2%; a
humanities-ranked list needs 3,682 companies for 60% and 11,243 for 65%.

Cost references (measured on SOC strings; industry evidence is larger, budget 1-3x):
headless Claude Haiku $0.0013/string, Sonnet $0.0022, Opus $0.0053, 0.3-0.75 s/string at
concurrency 4; local qwen3-4b lanes about 2.3 items/s when up. Run-to-run vote stability of the
headless jurors is 67-81%, so the append-only cache is the only reproducibility.

### 4.2 Employer: the levers (green C)

| Lever | Size | What it unlocks |
|---|---|---|
| **School-slug employer key.** Id-less experience rows whose `url` is `linkedin.com/school/<slug>` (parser stores it; today they become `raw:` keys fragmented into 31,174 keys for 20,801 slugs) | 454k rows, 299k persons; 129k steps / 60k persons in the humanities cohort; 300,878 rows already join IPEDS via `school_ipeds.parquet` | Stable university-employer identity, public/private control and Carnegie class, sector axis, fixes the university half of C1 |
| **Placeholder ids to nonorg** ("Independent", "Home", "Consultant", ".", "-", "Myself"...) | 39 companies, 10,438 rows, 9,524 persons | Honest self-employment counts; removes 4 of the top-10 humanities "employers" |
| **Employer-to-employer transition network** (`company` axis is registered, never built) | 2,797,511 id-to-id employer changes; 79,742 companies with >= 10 persons | Screen 5 "where people came from" at employer grain |
| **Tenure and linearity** | tenure computable on 99.25% of steps (median 29 months); 1.47M persons have >= 2 id-bearing employers | Screen 4 headline; message 2 |
| **Geography imputation** | 51.6% of steps have a US state; 1.41-1.75M more are at employers that are >= 80-90% one state; 1.2M current steps missing a state have a profile location | 51.6% to roughly 70-75% with an `imputed` flag |
| **Sibling-id aliasing** | 1.14M rows | Fewer split employer cells; propagates every curated entry to its siblings |
| **Sector redesign** (today 91% of resolved rows and 100% of XOT rows are `private`; all 923k EDU rows are `private`) | needs the school slug and name tokens | A usable public / nonprofit / private axis |

Dead ends, measured: exact-name linkage of the 2.7M `raw` rows recovers 26k rows (2.68M have no
id-bearing namesake; the head is universities, fixed by the slug instead); logo URLs (2.8M
id-less rows share one generic logo); `cc_industry` (106 of 2M profiles); `employment_type`
is two-valued in practice because the raw has no full-time/part-time field.

---

## 5. The ordered plan

Merged from the three teams' lists (green I/E, red fixes, refactor E-n). Phases 0 and 1 need
no model and no hardware. Phase 2 is the refactor that makes the jury re-fire safe. Phase 3 is
the re-fire.

### Phase 0: correctness before coverage (no LLM; one to two days)

Do these before any labeling, because labeling on today's keys would curate contaminated ids.

1. **Company canonicalization** (`career_clean`): support-gated modal id (C1); placeholder
   list extension (M5); school-slug key before the `raw:` fallback (green E1); skip the fuzzy
   tier when the normalized string is under 4 chars or non-Latin (M3). Regenerate the
   `career_company` mapping, then `career_steps`. Acceptance: no `id:` key from a string with
   id share under 50%; University of Michigan under one key; `nonorg:` for the 39 placeholders.
2. **Industry deterministic stack**: name-rule reorder and disables per red C2 with a
   reachability test and negative fixtures; dotted-`l1` fix (H1); keep NULL-key rows (H2) and
   assert `count(step_industry) == count(career_steps)`; occupation prior requires `freq >= 3`
   and drops major group 27 (M4); prior reads `occupation_major_pooled` (green I5, propose-only
   corroboration column); drop or re-gate the seven contaminated promoted keys (H3); set
   promoted confidence to the jury agreement, not 1.0. Rebuild vocab and `company_industry`.
   Add residual-gold scoring to `make test` with XOT counted as abstention (M8).
3. **SOC jury re-merge**: extend `_non_occupation` with bare status nouns and `% student`
   patterns (H4); re-run `run_soc_jury merge`; add the det-fingerprint and prefix tests.
4. **Consumers adopt the landed pooled SOC** (H6): paths spine `from/to_occupation` at major
   grain from `occupation_major_pooled`; cohorts `first_occupation`; a `soc_major` transition
   axis; archetypes and portal read the column instead of joining the jury table.
5. **Fix the refresh driver** (H7, refactor E-5): industry, paths, network build + analyze,
   seniority, cohorts, archetypes, portal, share; drop `--no-llm`; add a freshness check that
   fails when any input is newer than the manifest. Then run it.
6. **Break the bootstrap cycle** (H8, refactor E-6): tolerate a missing `role_soc_jury.parquet`
   in `write_career_steps` with a loud warning.

Expected after Phase 0: L1 step coverage roughly unchanged (the name-rule disables lose some
rows; the slug key and prior gains offset), but the 40k+ known-wrong L1 rows and the 631k
inherited ids are gone, the transition network's occupation axis rises from 7.8% to roughly
38% of transitions, and the portal reflects current tables.

### Phase 1: the curated head (one session, $0)

7. Label the union of the global top 2,313-3,000 unresolved companies and the
   humanities-ranked top 3,682 (large overlap) as a generated curated file keyed on company id
   plus display-alias siblings (green I2, E7). Gate: a blind 100-company second pass at >= 0.95
   L1, as with CIP gold v1. Also review the top 500 name-rule companies (559k rows) and fold
   corrections into the same file (green I7).
   Expected: L1 53.0% to 60-61%; humanities 49.2% to about 56%; about 490k persons touched.

### Phase 2: the refactor that unblocks the jury (refactor E-1 to E-4; two to three days)

8. Golden cache-key hash tests per axis (E-1). This protects 466 MB of live votes.
9. Move `industry/llm_pool.py` to `cleanlib/jury/hosts.py` verbatim with a re-export shim (E-2).
10. Add the `api="claude"` host over `cleanlib/headless_claude.py` (E-3).
11. `fire_llm --backend claude` adapter with a dry-run cost estimate (E-4). Extend the industry
    residual gold first (`fire_llm sample-gold` worksheet; 55 labels today) and calibrate the
    panel on it before firing anything. Decide where votes live now (recommend
    `industry/results/votes/*.jsonl`, gitignored, with a backup rule).

### Phase 3: the re-fire (hardware and policy dependent)

12. Ranks 3k-30k with a two-juror headless panel, unanimous at L1 lands, majority band to
    review (green I3): about 27.5k companies, $100-350 depending on evidence size, 6-11 h per
    juror at concurrency 4. Requires the owner's decision on sending company descriptions to a
    cloud model. Expected: L1 to about 70%.
13. Ranks 30k-180k on the local lanes once the Framework is back (green I4): $0, about two
    days for two jurors. Expected: to about 80%. Stop there unless a consumer needs
    singleton-employer industry (93% of employers in the windowed cohort are singletons; one
    query on the year-10 steps decides it).

### Phase 4: employer analyses the portal is waiting for (green E3-E6, E8)

14. Company transition network; tenure and linearity numbers; geography imputation with a
    provenance flag; first-employer concentration on the canonical cohort; sector redesign.

### Phase 5: structure (refactor E-7 onward)

15. Jury core migration dlevel, CIP, SOC, industry with parity checks; `company_clean/` with a
    `company_entities.parquet` master table so employer iteration stops costing a 75 s
    `career_steps` rewrite; pytest collection; untrack the vote JSONLs; wire or archive the 50
    unreachable files (6,078 LOC); doc rot per refactor F.

---

## 6. Decisions only the owner can make

1. **Cloud juror on company evidence.** Phase 3 step 12 sends company names, employee titles
   and up to three self-written job descriptions per company to a cloud model. The June design
   kept the production run local. If not permitted, step 12 collapses into step 13 (local
   lanes, +1-2 days, $0).
2. **Provenance of a frontier-labeled head.** The repo's contract is calibrated agreement on
   gold; a single-session labeling of household names has no agreement band. Proposed: blind
   second pass on 100, gate >= 0.95 L1, land as `curated` with a `frontier_v1`-style method tag.
3. **Canonical cohort** (FOUNDATION 1.4) before the humanities-ranked list is cut; the windowed
   portal population (22,427 persons) was not ranked separately.
4. **Is `sector` a product requirement?** If yes, withdraw the current column from every chart
   until Phase 0 step 1 and the redesign land (47% of steps are `private` by default).
5. **Refresh cadence.** Should a downstream refresh be mandatory after any normalized rebuild,
   and should enrichment and the cohort analyses (six weeks stale) be in it?
6. **`SNAPSHOT_YEAR` rename.** Four modules define it as 2025 meaning last complete year;
   `paths/common.py` as 2026. Rename the four to `LAST_COMPLETE_YEAR` and import from one place.

---

## 7. Where the evidence is

- `docs/audits/2026-09-02-teams/green.md`: verified state, staleness table, industry curve,
  employer signal inventory, humanities impact, queries q01-q12.
- `docs/audits/2026-09-02-teams/red.md`: findings C1-C2, H1-H5, M1-M9, L1-L2 with the SQL that
  reproduces each; 16 tests to add; 19 doc corrections.
- `docs/audits/2026-09-02-teams/refactor.md`: the true DAG, similarity measurements, the
  `cleanlib/jury` design with a 12-item do-not-touch list, dead-code table, test inventory,
  refactor plan E-1 to E-16, doc rot table.
- Query scripts and raw outputs for this session are in the session scratchpad
  (`scratchpad/{green,red,refactor}/`); the reports quote every load-bearing query inline.

---

## 8. Status at the end of 2026-09-02

Everything in Phase 0 and Phase 1 landed the same day, test-first, on branch
`recovery-refactor` (uncommitted).  `make test` is data-free and green;
`make test-data` and `make check-freshness` are green on the rebuilt data.

**Phase 0 (correctness).** C1 modal-id inheritance gated (`MIN_ID_ROWS` 3,
`MIN_ID_SHARE` 0.5), placeholders extended, fuzzy tier guarded, school-slug
keys; C2 name rules rewritten with a reachability test; H1/H2 propagation
one-row-per-step with `XOT` carrying no sector; H3 curated corrections and
retractions, promoted confidence 0.95; M4/I5 prior on the pooled 2-digit
major with a 0.6 modal-share floor; H4 student/extern forms out of the SOC
jury; H6 pooled SOC consumed by paths, cohorts, the `soc_major` network axis,
archetypes and the portal; H7 refresh driver rewritten (17 stages, revealed
seniority as a fixed point) with `scripts/check_freshness.py`; H8 the jury
mapping is optional at bootstrap; M7 `LAST_COMPLETE_YEAR` rename.

**Phase 1 (the curated head).** 4,709 unresolved head companies reviewed
(top 3,000 by rows plus the humanities-ranked top 3,700), 4,635 labeled into
`industry/curated_head.py`, 74 abstained.  Tooling is now in the repo:
`python -m industry.head_tools extract|write`, the label record
`industry/results/head_labels_v1.jsonl`, the blind gate sample
`industry/results/head_gate_{blind,key}.jsonl` and its scorer
`python -m industry.head_gate` (bar: L1 agreement 0.90).

| measure (row-weighted, all 10.8M steps) | before audit | after Phase 0 | after head pass |
|---|---|---|---|
| L1 coverage | 53.0% | 49.8% | **58.3%** |
| L2 / L3 / L4 | | | 53.1% / 25.2% / 2.1% |
| humanities cohort L1 | 49.2% | 44.8% | **53.9%** |
| curated rows | | | 2.95M (27.4%, 6,706 companies) |
| unresolved rows | | | 4.50M (41.7%): 2.56M id-keyed, 1.78M `raw:` |

The Phase 0 dip is real and intended: the retired name-rule tokens and the
stricter prior were mostly-wrong coverage.  The residual id-keyed curve is now
+1,000 companies to 59.3%, +5,000 to 61.6%, +10,000 to 63.5%, +20,000 to
65.9%; the `raw:` tail is the LLM proposer's job (Phase 3).

**Found while labeling, fixed the same evening.** The top of the residual head
was status strings that carry a LinkedIn company id: "Stay at Home Mom"
(453 rows under `women-tech-community`), "Private Company" (841),
"Private Family" (733), "self-emplyed" (133), "In Transition" (171),
"Profesional independiente" (312), "Seeking new opportunities" (1,382 across
variants), "Sabbatical" (316), "Multiple companies" (1,464 across variants),
"Volunteer" (250).  `career_clean/approach_a_rules.py` now buckets them
(homemaker, self_employed, unemployed, career_break, confidential,
private_household -> employment `employee`, volunteer) with anchored rules
and a negative list of real organisations that share the prefix (Seeking
Alpha, Independent Artist Group, Volunteer State CC, Private Equity Partners);
the company mapping and career_steps were regenerated and the refresh re-run.  Landing them exposed one more Python/SQL drift: the build's employment_type CASE hard-coded only the `none -> unknown` override, so `private_household` would have leaked into the employment axis as its own value; the CASE is now generated from `_BUCKET_TO_EMPLOYMENT` and pinned by `check_employment_sql_mirrors_buckets`.  `career_break` joins `EXIT_TYPES` in the spine (P9 in `paths/spine_tests.py`).

**Found while labeling, not fixed (taxonomy gaps).** No code for personal-care
salons (Regis, Great Clips, Supercuts, Sport Clips: about 1,000 rows, skipped);
no code for private households as employers (NAICS 814; now a `nonorg`
bucket, which is the honest state); gig marketplaces (ACX, Textbroker,
Care.com, Rover) skipped because the platform is not the employer;
"family office" (476 rows) left raw rather than guessed into FIN.ASM.

**Not done.** Phase 2 (the `cleanlib/jury` refactor), Phase 3 (the re-fire;
Framework offline), Phase 4 (employer analyses for the portal), the owner
decisions in section 6.  Decision 2 now has a concrete artifact: label
`head_gate_blind.jsonl` blind and run the scorer.
