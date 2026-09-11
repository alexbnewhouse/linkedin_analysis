# GREEN TEAM REPORT: employer + industry opportunity map

Date: 2026-09-02. Repo: /home/alex/linkedin-analysis @ recovery-refactor (clean, HEAD 9990a7a).
Read-only audit. Every number below is either (a) from a query in this session (scripts and
raw outputs in this directory, `q01`..`q12`; the label in brackets, e.g. [q02 C1], points at the
query and its printed result) or (b) tagged "doc claim" with the file:line, and marked verified
or not. No LLM fired, no build run.

Denominators used throughout: career_steps 10,800,787 rows [q01 H1]; step_industry 10,798,794
rows [q01 H3] (the 1,993 rows with no company string are dropped by the propagate join
[q06 E8]); company_industry 2,990,297 companies / 10,636,544 org rows [q04 S5].

---

## A. Verified state

### A.1 Headline claims

| Claim | On disk today | Verdict |
|---|---|---|
| SOC-major row coverage 61.5% | 6,645,746 / 10,800,787 = **61.53%** (det 2,317,425 = 21.46%; jury 4,328,321) [q01 H1, H1b] | verified |
| Person CIP coverage 96.29% | 1,925,741 / 1,999,974 = **96.29%** (`cip2_pooled`) [q01 H2] | verified |
| Industry L1 row coverage "53.6%" | company-weighted 53.6% (manifest, org rows); **step-weighted 53.03%** = 5,726,073 / 10,798,794 [q01 H3, q02 C0]. XOT = 5,072,721 rows (4,933,342 org + 139,379 nonorg) | verified; quote 53.03% for steps, as FOUNDATION.md:783 already insists |
| Cert axis ~545k persons | certifications_person.parquet = **545,409** rows [q01 H4]; `_cert_manifest.json` persons 545,409 | verified |
| L2 48.7% / L3 23.7% (manifest, company-weighted) | step-weighted **L2 48.0%, L3 23.34%** (`l1<>'XOT' AND depth>=k`) [final check]. Note: `l2`/`l3` are non-NULL on all 4,933,342 unresolved org rows, so `l2 IS NOT NULL` reads 98.5%; consumers must gate on `l1<>'XOT'` | verified |

Two structural facts that reframe the industry numbers:

1. **The M6 bulk run's product is gone.** `industry/METHODS.md` (doc claim, lines under
   "Outcome (run completed 2026-06-20)") records 2,023,473 residual companies classified by
   the local jury at L1 P 0.96. Those votes only ever lived in `llm_proposals.jsonl` as
   propose-only `llm_*` columns; the deterministic spine never absorbed them (doc: "row L1
   coverage 41.9%" after the merge). The cache was destroyed 2026-09-01 (PIPELINE.md:80).
   Today `company_industry.llm_*` is all NULL and `build_manifest.json` says
   `llm_candidates: 0` (verified by column types INTEGER/NULL [q01 schema]). The only
   survivor is `curated_promoted.py`: **1,982** promoted company_ids covering **1,247,680
   rows** [q04 N4], all resolving as `curated`. So the 53% is deterministic + 2,075 curated
   entries and nothing else.
2. **The occupation-prior tier reads the 21.5% deterministic SOC, not the 61.5% pooled
   SOC.** `industry/common.py:74-104` builds `occ_coded_frac`/`modal_occ` from
   `occupation_code`, not `occupation_major_pooled`. In the unresolved head, `occ_coded_frac`
   is 0.13-0.34 [q02 C3], so the tier (threshold 0.5, `occupation_prior.py:71`) fires on 0 of
   the 113 companies with freq >= 1000 and 19 of the 3,422 with freq 100-999 [q02 C2].

### A.2 Staleness table (file mtimes, `stat`; manifests read)

The 2026-09-01 downstream refresh (`refresh.log`) ran industry -> archetypes -> paths ->
cohorts panel -> network(occupation) -> portal -> share between 21:11 and 21:16. The
education tables were then rebuilt at **21:27** (commit 2922bc9 21:30, "blind gold v1 + CIP
tier reconfiguration": 56,929 HS rows -> 53, 770 placeholder rows demoted, person CIP
95.97% -> 96.29%). Everything that reads education/education_person and was built at 21:11-21:16
is therefore formally stale by one tier change.

| Artifact | Built | Reads | Status vs inputs |
|---|---|---|---|
| normalized/career_steps.parquet | 09-01 08:12 | parsed, mappings (role_soc_jury 07-11) | current; carries R1 pooled SOC + R7 dates |
| normalized/certifications_person.parquet | 09-01 08:22 | parsed/certifications | current |
| normalized/education{,_person}.parquet | 09-01 21:27 | mappings field_cip_jury 21:06, field_cip_knn 21:07 | current |
| industry/cache/company_vocab.parquet | 09-01 09:23 | career_steps | current (see A.1 item 2) |
| industry/results/company_industry, step_industry | 09-01 21:11 | vocab, curated | current; llm_* empty |
| archetypes/results/* (assign, yearwise, role_features, person_year_archetype) | 09-01 21:12-13 | career_steps, step_industry, **education_person** | stale vs education_person (21:27) |
| paths/steps, transitions, _concurrency | 09-01 21:13 | career_steps | current |
| cohorts/panel.parquet, profiles.parquet | 09-01 21:14 | paths/steps, **education_person** | stale vs education_person |
| transition_network/occupation_* | 09-01 21:14 | transitions | current |
| transition_network/role_* (nodes/edges/analyzed, role_manifest 08-05) | 08-05 | transitions (rebuilt 09-01) | **stale: predates R1/R7 rebuild** |
| portal/results/portal_data.json, portal/_manifest.json, share/*.html | 09-01 21:15 | **education.parquet**, paths, occ_nodes, step_industry | stale vs education.parquet (21:27); L1 boundary counts unchanged (240,277 records in both manifests) so impact is at most the 770 demoted + 56,929 HS rows, none of which can enter a bachelor's-level bundle |
| cohorts/_profiles, _scarring, _survival manifests, age_profiles.parquet | 07-22 | panel (rebuilt 09-01) | **stale** |
| enrichment/results/enrichment.json | 07-22 | education_person + parsed | **stale**: it reports hum_l1_any = 246,482 persons; education_person today has 293,808 [q05 HU0] |
| archetypes/results/validation.json, unsupervised_crosscheck.json | 07-16 | | stale |
| industry/results/industry_eval.json | 07-07 | gold + llm cache | stale and now irreproducible (cache lost) |
| portal/results/bias_check, cip_bias_check, soc_bias_check | 07-07..07-11 | | stale |
| reference/ipeds/_crosswalk_manifest.json, mappings/school_ipeds.parquet | 07-22 | | current (inputs unchanged) |

Minimum refresh to be consistent: re-run archetypes -> cohorts panel -> portal (about 5
minutes per refresh.log timings), then the 07-22 cohorts analyses and enrichment; rebuild the
role network only if anything consumes it (portal reads occupation nodes only,
`portal/common.py:33`).

### A.3 Small defects seen in passing (for the red team; zero-cost fixes)

- `step_industry.l1` carries dotted sub-codes on 5,020 nonorg rows (`HLT.PROV`, `NPO.SOCS`,
  `PRO.LEGAL`, ...) [q08b "dotted l1 leak"] because `build_industry.py:143-144` sets
  `l1 = coalesce(o.code, m.code)` without truncating. `portal/build.py:214` already patches
  around it.
- `l2`/`l3`/`l4` are populated on unresolved org rows (4,933,342 rows carry a non-NULL `l2` while `l1='XOT'`); any depth-k coverage must be computed as `l1<>'XOT' AND depth>=k`.
- `sector` is `'private'` on every XOT row (`taxonomy.sector_of('XOT')`): 46.97% of steps
  carry a sector they do not have [q04 S2]. Consumers must NULL it on XOT (see B.8).
- `id:consultant_66` (display "Consultant", 1,766 rows) was promoted to `PRO.CONSL`
  (`curated_promoted.py:166`); it is a self-employment placeholder that acquired a LinkedIn
  company id, not a consultancy [q07b PH1].

---

## B. Industry roadmap

### B.1 The cumulative curve (what it costs to move L1 coverage)

Unresolved org companies sorted by row frequency, 100% acceptance assumed; denominator
10,798,794 step rows; base 5,726,073 covered [q02 C1, C4, C5].

| Target L1 | Rows to add | Companies to label | Of which: with company_id | with descriptions | with modal_occ (det) | min freq at cut | Distinct persons touched |
|---|---|---|---|---|---|---|---|
| 55% | 213,263 | **117** | 116 | 117 | 117 | 974 | (not measured) |
| 60% | 753,203 | **2,313** | 2,270 | 2,313 | 2,312 | 127 | ~450k (top-3k = 491,656) |
| 65% | 1,293,143 | **9,436** | 9,255 | 9,436 | 9,416 | 49 | ~700k (top-10k = 710,595) |
| 70% | 1,833,082 | **27,485** | 26,772 | 27,477 | 27,097 | 20 | (top-50k = 1,002,409) |
| 75% | 2,373,022 | **72,058** | 68,437 | 71,579 | 66,124 | 8 | |
| 80% | 2,912,962 | **177,613** | 154,973 | 167,204 | 134,522 | 3 | |
| 85% | 3,452,901 | 409,371 | 313,930 | 338,160 | 220,538 | 2 | |
| 90% | 3,992,841 | 910,538 | 684,429 | 616,387 | 310,504 | 1 | |
| ceiling | 4,933,342 | 1,851,038 | | | | | (org rows; 139,379 nonorg XOT rows only reachable via occupation prior) |

Round-number cuts [q02 C4]: top 1,000 -> +552,269 (58.1%); 3,000 -> +834,496 (60.8%);
5,000 -> +1,019,636 (62.5%); 10,000 -> +1,320,263 (65.3%); 20,000 -> +1,664,433 (68.4%);
50,000 -> +2,164,294 (73.1%); 100,000 -> +2,564,153 (76.8%); 250,000 -> +3,130,125 (82.0%);
500,000 -> +3,582,304 (86.2%).

Realistic acceptance: the previous local run abstained (XOT) on 1.8% and failed validation
on 0.18% (doc claim, METHODS.md "Outcome"); a unanimity gate on a 2-3 juror panel historically
left the majority band (0.941 precision, n=34) in the queue. Plan on landing **85-95%** of the
"rows to add" per tranche.

Evidence available to a juror [q09 EV1]: ranks 1-30k carry ~1,960 chars of evidence per
company (display + 8 titles + 3 descriptions, all present); 30k-180k ~1,090 chars; 180k-450k
~460; the freq-1 tail ~230 (median 122). Freq buckets [q02 C2]: freq >= 1000: 113 companies
/ 210,218 rows, all with descriptions; 100-999: 3,422 / 680,302, all with descriptions; 10-99:
56,714 / 1,380,423 (56,714 with titles, 1,377,773 rows with descriptions); 2-9: 387,895 /
1,259,505 (1,053,804 rows with descriptions); 1: 1,402,894 (811,252 with a description).

### B.2 Why the household-name head is unresolved

Checked MetLife, Siemens, Netflix, Uber, Aramark, Sodexo, TEKsystems, Thomson Reuters,
Enterprise, Disney World, Aon, 3M, SAIC, H&R Block, Johnson Controls, McKesson, Schlumberger,
Peace Corps, Fiserv, Anthem, Chick-fil-A, BD, UCLA, Cargill, CSC, Sherwin-Williams, Eaton
[q03 N1-N3]:

1. **No curated entry.** `curated.lookup()` returns None for every one of them. Hand-curated
   `CURATED` has ~93 entries (`curated.py:26-137`); `PROMOTED` has 1,982 (`curated_promoted.py`),
   produced 2026-07-07 from the top-5,000 residual with a unanimous-only gate from a cache
   that no longer exists. Everything below rank ~2,000 of the June residual, and everything in
   the majority band, is simply absent. Keys are well-formed company_ids (`id:metlife`,
   `id:siemens`, `id:netflix`...) so M1 would fire the moment an entry exists.
2. **Name rules cannot fire on brands.** `name_rules.py` is a 214-token industry-word list;
   "MetLife", "Aon", "3M", "Siemens", "Netflix" contain no token by design (generic words are
   deliberately excluded, `name_rules.py:20-25`). This is correct precision discipline, not a
   bug; it just means the brand head is structurally M1-or-nothing.
3. **Occupation prior starved** (A.1 item 2): det `occ_coded_frac` 0.13-0.34 in the head, below
   the 0.5 floor.
4. **Sibling ids fragment the head.** The same display appears under several company_ids:
   Aon (`aon`, `aon-risk-services...`), 3M (`3m`, `3m_2`), H&R Block (3 ids), Netflix
   (`netflix`, `netflixl`), SAIC (`saicinc`, `spacedev`), Sherwin-Williams (2), Enterprise
   Holdings under `enterprise-mobility-` [q03 N2]. Corpus-wide, 14,755 display names sit under
   32,858 id-keys covering 1,143,547 rows [q04 S10]. `career_company_id_alias.parquet` holds 3
   aliases. A curated entry keyed on one id misses its siblings; a display-alias pass should
   ride along with any head curation. (Only 439 unresolved companies / 5,185 rows share a
   display with an already-curated company [q04 S11], so the alias gain is small today but
   grows with every curated entry.)
5. **Placeholders wearing company_ids.** "Independent" (`id:region-vii-area-agency-on-aging`,
   2,517 rows), "." (`id:vip-cinema-seating`, 2,616), "Home" (`id:home_60`, 1,968), "-"
   (`id:business`, 616), "Myself", "Entrepreneur", "Personal", "Own Business": 39 id-keyed
   companies, 10,438 rows, 9,524 persons [q07b PH1-PH2]. They belong in `nonorg:self_employed`
   (employment_type, industry-by-occupation), not in the review queue.

### B.3 Ordered task list

Costs use: headless Claude measured on the SOC tail (`career_clean/results/headless_bench.json`,
25 strings/call): Haiku $0.00134/string, 0.75 s/string at c=4; Sonnet $0.00202-0.00223,
0.27-0.87 s; Opus $0.00528, 1.1 s. SOC strings are ~150 input tokens; industry evidence in the
head is ~490 tokens (1,960 chars) plus a ~2,500-token shared system prefix (`llm._SYSTEM` =
10,038 chars, [q "SYSTEM length"]), so treat the SOC figure as a lower bound and 2x as the
upper bound until a 200-company pilot pins it. Local lanes: qwen3-4b on the two batched
llama-server lanes sustained ~2.3 items/s (doc claim, METHODS.md "Throughput accounting";
consistent with 2.03M items in 6.2 days). Lanes were DOWN and fedora offline as of 2026-09-01
evening (memory notes; not probed today, per the no-host-calls constraint).

| # | Task | L1 gain (rows / pp) | Persons | Method | Lane / $ | Effort | Prereq |
|---|---|---|---|---|---|---|---|
| I1 | **Hygiene: placeholder ids -> nonorg; alias sibling ids; fix dotted-l1 leak; NULL sector on XOT** | 10,438 rows leave the queue; 5,020 rows corrected; sector honest on 5.07M rows | 9,524 | SQL + a 39-entry list | none / $0 | hours | none |
| I2 | **Frontier/hand curated pass on the head: top 2,313-3,000 unresolved by freq** (2,270 have company_ids; display + 8 titles + 3 descriptions available for all) | +753k to +834k rows (**53.0 -> 60.0-60.8%**) | ~490k (top-3k touches 491,656 persons) | Extend `curated.CURATED` via a new generated file (same shape as `curated_promoted.py`), keyed on company_id + display-alias siblings; blind 100-company gold from the same band, gate >= 0.95 L1 | frontier session (subscription) or the owner; ~3k names at 50-100 per batch = a few hours; $0 marginal | 1 session | none; independent of the lost cache |
| I3 | **Headless Claude 2-juror pass on ranks 3k-30k** (~27.5k companies -> 70%) | +1.0M rows over I2 (**-> ~70%**, ~0.9M realistic) | ~500k additional (top-50k reaches 1,002,409) | Haiku + Sonnet, unanimous at L1 lands, majority band -> review; append-only cache keyed like `llm.cache_key`; needs an industry adapter over `cleanlib/headless_claude.py` (prompt/schema already in `industry/llm.py`) | Haiku $36-74 + Sonnet $60-124 = **$95-200**; wall 6-11 h per juror at c=4 (parallelizable) | adapter 0.5 day + run | I2 (so the head is not re-fired); rebuild industry gold: `gold_residual.py` has ~55 labels, `fire_llm sample-gold` writes a worksheet; calibrate the headless panel on it first (`fire_llm calibrate` pattern) |
| I4 | **Local lanes on ranks 30k-180k** (~150k companies -> 80%) | +1.08M rows (**-> ~80%**, ~0.95M realistic) | | qwen3-4b bulk juror (calibrated L1 0.889, n=72, doc claim) plus one disjoint-family second voice (gemma3:27b / Qwen3.6-35B-A3B) for the unanimity gate; the 3-juror local panel measured unanimous 1.0 (n=24), majority 0.941 (n=34) (`industry/results/promoted_eval.log`, doc claim) | $0; ~18 h single-juror at 2.3 items/s, ~2 days for two jurors | relaunch watchdogs; wake fedora | I3; lanes up |
| I5 | **Occupation prior on pooled SOC** (change `common.export_company_vocab` to use `occupation_major_pooled` for `occ_coded_frac`/`modal_occ`; keep the 13 industry-bound majors and a modal-share >= 0.6 rule) | fires on **405,290 rows** (+3.75pp) at conf 0.3-0.5; 154,564 rows on companies with freq >= 5 (+1.4pp) [q08b OP1] | | propose-only column (`prior_pooled_code`) used as corroboration for I2-I4 and as a shallow fallback; examples: DoorDash -> 53/TRN, Olive Garden -> 35/HOS.FOOD, VIPKid -> 25/EDU, but also EEOC -> 23/PRO.LEGAL (should be PUB.GOV) and Triple Canopy -> 33/PUB.JUST (private contractor) [q08b OP3] | none / $0 | 0.5 day | a 100-company blind check of the company-grain tier: `gold.py` has only 6 row-grain prior cases, none at company grain |
| I6 | **Tail (180k-910k, -> 90%)** | +1.08M rows | | local bulk only; 1-2 rows per company; evidence 230-460 chars | $0; ~4 days at 2.3 items/s | | I4; only if a consumer needs singleton-employer industry (see D) |
| I7 | **Precision pass on the name-rule head** | 0 coverage; precision at depth | | top-500 name_rule companies = 559,104 rows [q08b NR1]; broad single-token rules (health, technologies, systems, capital, financial, energy, media, industries, homes, records, machine, electric, spa, fitness, gym, equity, savings) sit on 232,687 companies / 842,307 rows [q08b NR2]; visible misfires in the top-40: GE Healthcare -> HLT.PROV (is MDEV), Cardinal Health -> HLT.PROV (distribution), CVS Pharmacy -> HLT.PROV (retail), NYC Dept of Education -> PUB.GOV (is EDU.K12) [q04 S9] | frontier/hand review of 500 names, hours | | none; fold into I2's curated file (hand entries win on key conflict, `curated.py:141`) |
| I8 | **Sector column redesign** | makes the public/nonprofit/private axis usable | | today: sector = taxonomy-branch default; resolved rows: private 91.4%, public 6.6%, nonprofit 2.05% [q04 S2b]; all 923,456 EDU rows are 'private' (public universities included) [q04 S3]; XOT rows 'private'. Redesign: NULL on XOT; EDU.HED via school slug -> IPEDS control (E1 below gives the slug); name tokens (city of / county / department of / district / public schools -> public; foundation / church / ministries / charities -> nonprofit); everything else `unknown` | none / $0 | 1 day | E1 |

Priority order: I1 -> I2 -> I5 (cheap corroboration) -> I3 -> I4 -> I7 -> I8 -> I6.
I2 alone moves the corpus past 60% and the humanities cohort past 56% (D below) for zero
dollars, and it is the only step that needs no hardware and no calibration infrastructure.

### B.4 What the lost cache means for the roadmap

Re-firing the full 2.03M residual locally is a ~6-9 day job (6.2 days measured in June for
2.03M; I6 is the same population) and would reproduce a propose-only column nobody consumes.
The roadmap above deliberately lands coverage through the curated ratchet (M1) and gated
tiers, so that the next cache loss cannot erase coverage again. Every fired vote should still
go to an append-only JSONL under `industry/results/` (not module root), with `.gitignore`
coverage and a backup rule; run-to-run vote stability of the headless jurors is only 67-81%
(memory: headless-claude-jury), so the cache is the only reproducibility.

---

## C. Employer roadmap

### C.1 Signal inventory (consumers by grep; coverage by query)

| Signal | Coverage | Consumers today | Notes |
|---|---|---|---|
| `company_raw` / `company_canonical_id` / `company_id_canonical` | 10,798,794 rows keyed; 7,829,820 with a LinkedIn id (72.5%): company_id 7,661,286 + name_crosswalk 120,815 + typo_to_id 47,719; raw 2,706,281; typo 100,443; placeholder 162,250; NULL 1,993 [q06 E1] | paths/build_spine (from/to_company), portal/analyses.employer_field, portal/choices, transition_network (company axis defined, never built), industry, archetypes | 1,068,349 distinct ids; 1,921,789 distinct raw keys |
| `employment_type` | 100%: employee 94.71% (**`default_employee` = absence of a marker**), business_owner 2.47% (title), self_employed 1.77% (placeholder 1.16 + title 0.61), student 0.49%, retired 0.33%, various/unknown/confidential/homemaker/unemployed/stealth < 0.2% [q06 E9] | paths (WORKFORCE/SELF_EMPLOYED/EXIT types), cohorts panel, archetypes yearwise/role_features, portal choices | LinkedIn's own full-time/part-time/contract/internship field is NOT in the raw: `experience.subtitle` is populated on 1,928 of 9,076,606 rows [q07b P3, P5]; `positions.subtitle` is the parent company name [q10 A9]. Internship is title-only: ~307k rows contain "intern" [q12 INT1] |
| dates: `start_year` / `end_year` / `is_current` | start 10,720,373 (99.26%); end 8,420,062; current 2,299,824; **tenure computable 10,719,886 (99.25%)** [q06 E10, q07b T0]; paths/steps `tenure_months` on 10,717,451 [q10 A11] | paths, cohorts, portal, archetypes | rough tenure quantiles p10/25/50/75/90 = 6/12/29/63/129 months [q07b T1] |
| `duration` (raw text) | 563,046 rows only | none | redundant with dates |
| location: `location_us_state` / `location_country` / `location_city` | US state 5,568,459 (**51.56%**), country 56.88%, raw string 63.81% [q07b L1]; 3,909,062 rows have no location string, 716,827 unparsed [q07b L2] | paths (from/to_location), portal (not wired) | see E5 for the imputation headroom |
| `description` | experience 4,169,939 + positions 1,320,214 rows [q07b P3, P4] | industry vocab (3 longest per company), career_clean SE description, archetypes keywords | the largest untapped text asset (FOUNDATION Screen 3 "what this work involves"); local-only by policy |
| `company_logo_url` | 7,844,209 experience rows; **dead as a key**: 2,802,876 of the id-less rows share one generic static logo [q11b G3], and 763,663 of 764,547 logos on id-bearing rows map 1:1 to an id that is already present [q11 G1-G2] | none | no opportunity |
| `url` (experience) | 6,082,682 rows; **455,102 id-less rows carry a `linkedin.com/school/<slug>` url** (22,138 slugs, 300,023 persons) [q10 A3, A7] | none | the one big employer-linkage lever (E1) |
| `positions` (grouped roles) | 2,788,549 parsed = 2,788,549 in career_steps; parent experience rows with children (1,064,368) are replaced by them: 9,076,606 - 1,064,368 = 8,012,238 = experience rows in career_steps [q06 E11, E12] | build_normalized | **joined correctly** |
| profile-level `current_company_name` / `_company_id` / `cc_title` / `cc_location` / `connections` / `followers` / `city` / `location` | 1,968,709 / 1,315,802 / (cc_*) / connections 1,944,630 (median 201, p75 500 = LinkedIn cap) / city 1,999,999 / location 1,516,142 [q07b P1, P2b]; `cc_industry` 106 (dead) | enrichment (profiles), none for employer work | current-company id could cross-check `is_current`; `city`/`location` give a fallback location for 1,197,481 of the 1,197,482 current steps missing a state [q12 GEO2] |
| company size proxy (`n_persons` in corpus) | companies by persons: >= 10k: 12 (278,792 rows); 1k-10k: 455 (1.44M); 100-999: 6,421 (2.18M); 10-99: 72,854 (2.24M); 2-9: 517,383 (1.93M); 1: 2,393,172 (2.57M) [q07b Z1] | portal employer_field size buckets (per major) | usable now as "employer size in this sample", never as firm size |
| `is_duplicate` | 34,144 rows [q06 E13] | paths | fine |

### C.2 Quantified items the coordinator asked for

(a) **The 2.7M `company_method='raw'` rows.** 2,706,281 rows over 1,921,789 distinct raw
strings (1,910,646 after lower/alnum normalization) [q06 E1, q09 E5]. The head is
universities: Arizona State University 2,716 rows, UT Austin 2,442, Penn State 2,361, USC
2,256, Florida 2,245, Penn 2,046 ... [q06 E2]. Exact normalized-name linkage to id-bearing
rows recovers almost nothing: **24,801 rows map to a single id, 1,341 to a dominant (>= 90%)
id, 1,979 ambiguous, and 2,678,160 rows (2,425,544 person-rows) have no id-bearing namesake at
all** [q09 E6]; the linkable head is small stuff (dupontpioneer 297, midwesternuniversity 160)
[q09 E7]. career_clean's `name_crosswalk`/`typo_to_id` tiers already took the easy matches.
The reason the university head is raw is not a name problem: LinkedIn serves schools as
`/school/<slug>` pages with no `company_id` (all 2,716 ASU employer rows carry
`https://www.linkedin.com/school/arizona-state-university/` [q10 A1, A5]). Fix is E1, not
fuzzy matching. For industry the raw rows are already 1,184,263 name_rule + 129,631 prior;
1,392,387 remain unresolved [q09 E9].

(b) **Rows with company_id but no company_industry match: zero.** The 1,993 rows lacking any
company string (`company_canonical_id IS NULL`) and the 162,250 `nonorg:` placeholder rows are
the only non-matches, and the latter are handled by the nonorg branch of the propagate query
[q06 E8, E8b]. No key mismatch exists.

(c) **employment_type**: table above. It is a two-valued axis in practice (employee vs
self-employment marker) with a thin status tail; it cannot carry a full-time/part-time/contract
composition because the raw never had it.

(d) **Tenure**: 99.25% computable; `is_current` 21.3% of rows.

(e) **positions**: verified exact (row counts reconcile to the parsed tables).

### C.3 Ordered task list

| # | Task | What it unlocks (FOUNDATION message / screen) | Size | Method | Lane / $ | Effort | Prereq |
|---|---|---|---|---|---|---|---|
| E1 | **School-slug employer key.** In `build_normalized` company canonicalization, before the `raw:` fallback, key id-less experience rows whose `url` matches `linkedin.com/school/<slug>` as `school:<slug>` (or `id:<slug>`), and add the slug to the industry vocab | Stable identity for university employers: today 585,431 steps sit under school urls, 459,724 keyed `raw:` and fragmented into 31,174 keys for 20,801 slugs (university-of-michigan alone -> 150 keys) [q11b G4, G7]. Joins to IPEDS: 3,165 slugs / 300,878 rows already in `school_ipeds.parquet` [q11b G8, G8c] -> employer control (public/private), Carnegie class, state; feeds I8 (sector) and Screen 7 (concrete places) and the "ways in" panel (TA/RA/adjunct steps) | 455,102 parsed rows, 300,023 persons; humanities: **128,957 steps / 60,155 hum_l1 persons** [q11b G6] | SQL; parser already stores `url` (`parse_linkedin.py:187`) | none / $0 | 1 day incl. tests | none; re-run normalize --skip-mappings, then industry vocab (37,903 of these steps are still XOT and would resolve to EDU via the slug [q11b G5]) |
| E2 | **Placeholder-ids -> nonorg** (39 companies, 10,438 rows, 9,524 persons: '.', Independent, Home, Consultant, -, Myself, Entrepreneur, Personal, Own Business) [q07b PH1-2]; also revisit `consultant_66 -> PRO.CONSL` | correct self-employment counts (message 6's "leadership is self-employment" caveat; choices.self_employment), removes 4 of the top-10 humanities unresolved "employers" | 10,438 rows | extend `career_clean` placeholder bucket with an id-keyed exception list | $0 | hours | none |
| E3 | **Employer-to-employer transition network** (`transition_network.build_network company`, never run; axis defined at `transition_network/common.py:40`) | Screen 5 "where people came from" at employer grain; employer landmarks for message 3 | 6,179,130 transitions; 4,925,101 change employer; **2,797,511 are id -> id employer changes** [q11b TR1]; restrict nodes to companies with >= 10 persons (79,742 companies) to stay under suppression | one CLI run + min_support | $0 | hours | E1 (so universities are nodes) |
| E4 | **Employer tenure / linearity numbers** (share of persons with one employer over ten years; median tenure by entry cohort) | Screen 4's missing headline; message 2 | tenure on 10,717,451 steps; 1,470,453 persons have >= 2 distinct id-bearing employers [q07b T2]; 1,999,974 persons have a datable first step, 1,329,932 with an id-bearing first employer, 636,951 raw, 32,836 nonorg [q07b F1] | queries over paths/steps + cohorts/panel | $0 | 1 day | none (panel refresh recommended, A.2) |
| E5 | **Geography lift** | Screen 7 ("before designing around 51.6%, find out whether it can be improved") | 5,232,328 steps lack a US state; **1,748,261 are at an employer whose located steps are >= 80% one state (n >= 5), 1,410,269 at >= 90% (n >= 10)**; 276,490 are known non-US; the 1,197,482 current steps missing a state all have a profile-level city/location [q12 GEO1-2]. Potential: 51.6% -> ~70-75% with an `imputed` flag | SQL, two provenance tiers (`employer_modal`, `profile_current`) | $0 | 1-2 days | none |
| E6 | **First-employer concentration + employer size buckets on the canonical cohort** | message 1/3 employer honesty; Screen 7 | first employers: nonorg:self_employed 26,022, us-army 15,991, USAF 11,677, us-navy 10,232, ibm 5,797, att 5,744, wellsfargo 5,562 ... [q07b F2]; 866,922 distinct first employers | already computable; portal `employer_field` does it for the windowed cohort at MIN_SUPPORT 10 (arts 18,472 employers / 92.4% singletons; english 9,281 / 92.6%; history 4,614 / 92.6%; philrel 2,961 / 95.5%) [portal_data.json] | $0 | query | cohort decision (FOUNDATION 1.4) |
| E7 | **Sibling-id aliasing** (14,755 displays under 32,858 ids, 1.14M rows) [q04 S10] | fewer split employer cells; propagates curated industry | 1,143,547 rows | display-exact alias within id-keys when the display is not a placeholder; extends `career_company_id_alias.parquet` (3 rows today) | $0 | 1 day | E2 |
| E8 | **Description mining for "what this work involves"** | Screen 3 panel 1 | 5.49M rows with text | local-only (policy), scoped to the canonical cohort's year-10 steps first | pool-bulk, days | large | cohort decision; not an employer-coverage task |

Not recommended: fuzzy/embedding linkage of the 1.9M raw names (E6 shows the exact-name
ceiling is ~26k rows and the head is fixed by E1); logo-based linkage (dead, C.1).

---

## D. Humanities-specific impact

Cohorts on disk [q05 HU0]: hum_l1_any 293,808 persons; hum_l2_any 510,306; hum_l3_any
776,769; hum_l1_bachelor_any 181,048; hum_l1_bachelor_pooled_any 181,767.

**Industry L1 coverage is lower for humanities than for everyone** [q05 HU1]:

| Population | Steps | L1 covered | Persons |
|---|---|---|---|
| all | 10,798,794 | 53.03% | 1,999,719 |
| hum_l1_any | 1,733,444 | **49.23%** | 293,765 |
| hum_l2_any | 3,099,176 | 49.35% | 510,237 |
| hum_l1_bachelor_pooled_any | 1,109,554 | **48.75%** | 181,743 |

At the portal's year-10 endpoint it is worse still: `industry_unresolved_share` in
portal_data.json is arts 0.6311, commmedia 0.5739, english 0.5627, philrel 0.5602, history
0.5189. Method mix among hum_l1 steps: unresolved 50.77%, name_rule 29.75%, curated 14.93%,
occupation_prior 4.55% [q05 HU2]. Resolved L1 mix: EDU 11.8%, MED 7.5%, HLT 4.9%, FIN 4.1%,
CON 3.8%, PUB 3.2%, TEC 3.1%, PRO 2.9% [q05 HU3].

**The humanities unresolved head is a different list from the corpus head** [q05 HU4, HU5]:
Netflix (937 hum steps / 633 persons), Walt Disney World (836/585), Peace Corps (680/546),
"Independent" (656/609, a placeholder id), Thomson Reuters (621/362), Teach For America
(526/384), Houghton Mifflin Harcourt (457/298), SAG-AFTRA (443/404), UCLA (441/306),
Chick-fil-A (441/358), McGraw Hill, Wiley, Christie's, Elsevier, YMCA, Hasbro, Gensler,
Bloomberg, Live Nation, Mattel, Pratt Institute (raw), Gartner, Office Depot, Aramark,
Siemens, Anthem. Publishers, media, culture, service programs: exactly the destinations the
portal wants to name, and exactly what M1/M3 structurally miss.

What the industry tasks buy the cohort [q05 HU6-7 and the hum curve]:

- I2 at top-3,000 (global ranking): recovers 120,123 hum_l1 steps / 72,145 persons ->
  hum_l1 coverage **49.2% -> 56.2%**.
- I3 through top-10,000: 200,253 hum steps / 106,903 persons -> **60.8%**.
- Ranking by humanities rows instead of global rows is more efficient for the cohort: 60%
  needs 3,682 companies (min 18 hum steps each), 65% needs 11,243, 70% needs 26,483, 75%
  needs 53,518, 80% needs 96,854. Recommendation: build I2's list as the union of global
  top-2,313 and hum-ranked top-3,682 (large overlap; both lists are on disk in `q05_out.txt`
  / `q02_out.txt` form and can be regenerated from the queries in the appendix).
- E1 gives 60,155 hum_l1 persons a stable university-employer key (128,957 steps), which is
  the biggest single humanities employer class (EDU is the top resolved sector).
- E2 removes "Independent" (#4 humanities unresolved) from the employer list.

---

## E. Open questions for the owner

1. **Canonical cohort (FOUNDATION 1.4) before any humanities-ranked labeling list is cut.**
   The hum-ranked head differs between `hum_l1_any` and `hum_l1_bachelor_pooled_any` only in
   order, but the windowed portal population is 22,427 persons and its unresolved employers
   were not measured here; a year-10-step-weighted ranking for that population is a 2-minute
   query once the cohort is fixed.
2. **Acceptance gate for a frontier-labeled head (I2).** The repo's contract is calibrated
   agreement on gold; a single frontier session labeling household names has no agreement
   band. Proposed: label blind, then a second blind pass (owner or a second model) on a
   100-company sample, gate >= 0.95 L1 as with CIP gold v1. Is that acceptable as the
   "curated" tier's provenance, or must it stay a separate `frontier` tier?
3. **Where should fired votes live now?** `industry/llm_proposals.jsonl` at module root was
   what got lost. Recommend `industry/results/votes/*.jsonl` with gitignore + a backup rule
   before I3 fires anything.
4. **Should the headless Claude route be used on company evidence at all?** It sends
   company names, employee titles and up to 3 free-text job descriptions per company to a
   cloud model. The June design kept cloud jurors to gold-calibration only ("no scraped PII
   leaves Anthropic" was about vendor-intra panels; METHODS 2.9 says the production run was
   local-only). Descriptions are self-written profile text. I3 as costed assumes it is
   permitted; if not, I3 collapses into I4 (local lanes, +1-2 days, $0).
5. **Is the `sector` axis a product requirement?** If FOUNDATION's "employer type" message
   needs public/nonprofit/private, I8 + E1 are the path and the current column must be
   withdrawn from any chart (46.97% of rows are 'private' by default).
6. **Downstream refresh cadence.** Six artifacts are stale (A.2), two of them (enrichment,
   cohorts analyses) by six weeks and one full data rebuild. Should `scripts/refresh_downstream.sh`
   include them, and should a refresh be mandatory after any normalized rebuild?
7. **I6 (singleton tail) value.** 93% of employers in the windowed cohort are singletons; if
   the sector chart at year 10 is drawn on per-person steps, the singleton tail matters for
   humanities more than for the corpus. A one-query measurement on the windowed cohort's
   year-10 steps (share sitting in freq-1/2 companies) decides whether I6 is worth 4 days of
   local compute.

---

## Appendix: queries

All scripts and raw outputs are in this directory
(`<session scratchpad>/green/`):

| Script | Output | Covers |
|---|---|---|
| q01_schema_headline.py | q01_out.txt | schemas; H1-H4 headline verification |
| q02_industry_curve.py | q02_out.txt | C0 baseline, C1 target table, C2 evidence by bucket, C3 top-60, C4 cum rows at N, C5 persons |
| q03_household_sector.py | q03_out.txt | N1-N3 household names, curated lookups (S-queries crashed there; rerun in q04) |
| q04_sector_fix.py | q04_out.txt | N4 promoted, S1-S11 sector/method/name-rule/siblings |
| q05_humanities.py | q05_out.txt | HU0-HU7 humanities coverage, heads, curve |
| q06_employer1.py | q06_out.txt | E1-E13 company_method, raw head, placeholders, gap, employment_type, dates, source_table, positions reconciliation, duplicates (E6/E7 there used a wrong normalization; corrected in q09) |
| q07b_employer2.py | q07b_out.txt | P1-P6 parsed signals, L1-L4 location, Z1 size proxy, F1-F2 first employer, T0-T2 tenure, PH1-PH3 placeholder ids |
| q08b_occprior.py | q08b_out.txt | OP1-OP5 occupation prior extension, XDV, dotted-l1 leak, NR1-NR2 name-rule head |
| q09_rawlink_evidence.py | q09_out.txt | E5-E10 raw linkage (correct normalization), EV1 evidence size |
| q10_idless.py | q10_out.txt | A1-A11 id-less rows, school urls, logo, positions.subtitle, paths tenure |
| q11b.py | q11b_out.txt | G3-G8c logo dead-end, school-slug keying/IPEDS, TR1 transitions |
| q12_geo.py | q12_out.txt | GEO1-2 geography imputation, INT1 internship |

Key SQL (verbatim from the scripts):

```sql
-- C1: companies needed per target (u = unresolved companies with running sums)
CREATE TEMP TABLE u AS
  SELECT c.key, c.company_id, c.display, c.freq, c.n_persons, v.modal_occ, v.occ_coded_frac,
         len(v.titles) n_titles, len(v.descriptions) n_desc,
         row_number() OVER (ORDER BY c.freq DESC, c.key) rn,
         sum(c.freq) OVER (ORDER BY c.freq DESC, c.key ROWS UNBOUNDED PRECEDING) cum_rows
  FROM read_parquet('industry/results/company_industry.parquet') c
  LEFT JOIN read_parquet('industry/cache/company_vocab.parquet') v USING (key)
  WHERE c.method='unresolved';
-- per target t: need = t/100*10798794 - 5726073; SELECT min(rn) FROM u WHERE cum_rows >= need

-- HU1: humanities coverage
SELECT count(*), round(100.0*avg(CASE WHEN l1<>'XOT' THEN 1 ELSE 0 END),2), count(DISTINCT linkedin_id)
FROM read_parquet('industry/results/step_industry.parquet') s
JOIN read_parquet('normalized/education_person.parquet') h USING (linkedin_id) WHERE h.hum_l1_any;

-- E6: raw-name linkage (normalization: regexp_replace(lower(trim(company_raw)), '[^a-z0-9]+', '', 'g'))
-- idnames_agg = per normalized name on id-bearing rows: n_ids, n_rows, top_n, top_cid
-- rawnames    = per normalized name on company_method='raw' rows: n_rows, persons
SELECT CASE WHEN a.nrm IS NULL THEN 'no id-bearing match' WHEN a.n_ids=1 THEN 'match: single id'
            WHEN a.top_n*1.0/a.n_rows>=0.9 THEN 'match: dominant id >=90%' ELSE 'match: ambiguous ids' END,
       count(*), sum(r.n_rows), sum(r.persons)
FROM rawnames r LEFT JOIN idnames_agg a USING (nrm) GROUP BY 1;

-- A7: id-less experience rows recoverable from a school url
SELECT count(*), count(DISTINCT regexp_extract(url, 'linkedin\.com/(?:company|school)/([^/?]+)', 1)), count(DISTINCT linkedin_id)
FROM read_parquet('parsed/experience/*.parquet')
WHERE company_id IS NULL AND url IS NOT NULL AND url LIKE '%linkedin.com/%';

-- OP1: occupation prior on pooled SOC (cm = per company: n, n_pooled, modal_major_pooled, top_cnt)
SELECT sum(CASE WHEN m.n_pooled*1.0/m.n >= 0.5 AND substr(m.modal_major_pooled,1,2) IN
  ('21','23','25','27','29','31','33','35','45','47','51','53','55') AND m.top_cnt*1.0/m.n_pooled >= 0.6
  THEN c.freq ELSE 0 END)
FROM read_parquet('industry/results/company_industry.parquet') c JOIN cm m ON m.k=c.key WHERE c.method='unresolved';

-- GEO1: employer-modal-state imputation headroom (cst = per company: n_loc, top_c, top_state)
SELECT count(*), sum(CASE WHEN c.n_loc>=5 AND c.top_c*1.0/c.n_loc>=0.8 THEN 1 ELSE 0 END),
       sum(CASE WHEN c.n_loc>=10 AND c.top_c*1.0/c.n_loc>=0.9 THEN 1 ELSE 0 END)
FROM read_parquet('normalized/career_steps.parquet') s LEFT JOIN cst c ON c.k=s.company_canonical_id
WHERE s.location_us_state IS NULL;
```

Doc claims relied on and not re-measurable today: METHODS.md June run outcome (2,023,473
classified, jury L1 P 0.96, ~2.3 items/s); promoted_eval.log agreement bands (unanimous 1.0
n=24, majority 0.941 n=34); qwen3-4b L1 0.889 (n=72); memory notes on lane status and headless
vote stability (67-81%). Headless $/string figures are measured
(`career_clean/results/headless_bench.json`, 2026-09-02) but on SOC strings, not company
evidence.
