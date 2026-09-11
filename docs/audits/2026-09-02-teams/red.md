# RED TEAM REPORT — employer / industry path, SOC pooled column, parsed dates

Audited 2026-09-02 on branch `recovery-refactor` (HEAD 9990a7a, clean). Read-only; no builds, no LLM.
`make test` and `make lint` (coordinator log `../make_test.log`): both exit 0 — all 8 suites pass, ruff clean.
All numbers below were re-derived from the committed parquet with DuckDB; scripts and raw outputs are in this
directory (`q1_canon.py` … `q11_more.py`, `*.out`). Appendix D lists the load-bearing queries.

Severity scale: CRITICAL = wrong numbers reach the portal/share build; HIGH = wrong data in a normalized/industry
table; MEDIUM = fragile, untested, or misleading; LOW = hygiene.

---

## A. Findings, ranked

### C1 — CRITICAL — Value-level modal-id inheritance glues 631k no-id rows to ids taken from a handful of rows (universities, placeholders); curated entries were then built on the contaminated displays

**Mechanism.** `career_clean/common.py:export_vocab` attaches to every distinct company string the `arg_max`
company_id over *only the rows that carry an id* — no minimum share, no minimum count. `final_hybrid.canon_company_value`
(line 109) turns that into `id:<modal_id>` with method `company_id` and confidence 1.0. In `build_normalized.py:822-841`
a row without its own `company_id` falls through to `company.canonical_id`, so it inherits the value's modal id.
`_name_to_id_crosswalk` (approach_a_rules.py:252-263, `setdefault` first-seen) has the same defect.

**Measured** (`q1b_canon.out`, `q9_inherit.out`, `q11_more.out`):

- 631,105 rows have `company_method='company_id'` but `company_id_raw` NULL/blank (139,968 distinct ids), all with `company_confidence=1.0`.
- By the value's own id share: <10% → 143,793 rows; 10–25% → 55,531; 25–50% → 92,993. Total 292,317 rows from strings where the majority of rows carry no id.
- 25,933 `id:` keys are *majority inherited* (>50% of their rows have no own id); they hold 333,928 rows.
- University employers are the biggest victims (LinkedIn links university employers to `/school/` pages, so `company_id` is empty; one or two stray sub-page rows decide the id for thousands):
  `University of Michigan` → `id:center-for-managing-chronic-disease` (2,872 rows, 2 with an id); `Stanford University` → `id:stanfordbloodcenter` (2,718/1); `New York University` → `id:nyu-wasserman-center-for-career-development` (2,487/1); `Harvard University` → `id:harvardcid` (2,232/1); `Cornell University` → `id:tandingonyourown` (1,869/2); `Duke University` → `id:clickit-inc-` (1,318/4); `Caltech` → `id:integris-for-banks` (394/0); `Wellesley College` → `id:jackson-walnut-park-schools`; `Rice University` → `id:rice-universityewrwerwerewrew`.
- Placeholders become "employers": `Independent` → `id:region-vii-area-agency-on-aging` (2,324 rows; 90 real rows of that agency); `Home` → `id:home_60` (1,938); `Consultant` → `id:consultant_66` (1,742); `Contract` → `id:salesforce` (308); `Private Family` → `id:ios-app-development-service` (556); `Contractor` → `id:contractor` (409); `.` → `id:vip-cinema-seating` (753); `-` → `id:business` (586); `--` → `id:ppd` (114, PPD is a real CRO); `me` → `id:mcafeeenterprise` (82, via name_crosswalk).

**Industry damage** (this is what reaches `step_industry` and the portal's sector bars):

- `University of Pittsburgh` (1,562 rows) → `id:upmc` → **curated `HLT.PROV.HOSP`** (university staff counted as hospital sector).
- `University of Rhode Island` (528 rows) → `id:cbrealty` → `RE.REST.RES`.
- The 2026-07-07 promotion pass labeled ids by their (inherited) display, so `curated_promoted.py` now contains: `ucsdhealth` → `EDU.HED.UNIV` (2,137 of 2,788 rows are inherited "UC San Diego"; UCSD Health staff become universities), `uc-irvine-medical-center` → `EDU.HED.UNIV` (1,293/1,626), `consultant_66` "Consultant" → `PRO.CONSL` (1,647/1,766), `thebeach2` "Volunteer" → `NPO`, `kentucky-department-of-education` "Education" → `EDU.K12`, `integris-for-banks` "Caltech" → `EDU.HED.UNIV`, `kpn` (a Dutch telecom) "Wang Laboratories" → `TEC.SOF.ITSV.INTG`, `berkeley-rha` "UC Berkeley" → `EDU.HED.UNIV`. Full list: `q9_inherit.out` ("curated/promoted keys fired mostly on INHERITED rows").
- Among the 292,317 rows from <50%-share strings: 60,494 got a curated code, 143,754 a name-rule code, 85,986 XOT; 11,191 rows carry an L1 that contradicts the name rule on the row's *own* raw name (EDU→HLT 2,104; EDU→PUB 636; HLT→PUB 574; EDU→RE 530 …).

**Downstream.** Every consumer keyed on `company_canonical_id`/`company_id_canonical`: `company_industry` (display, modal_occ, curated lookup), `step_industry`, portal sectors (Education vs Healthcare split for humanities cohorts), portal `employer_field`, `paths/transitions` employer-move typing, archetypes.

**Minimal fix.** In `export_vocab('company')` also emit `n_with_id`; in `canon_company_value` accept `modal_id` only when `n_with_id >= max(3, 0.5*freq)` (else `raw:`); apply the same gate in `_name_to_id_crosswalk`; add `independent`, `home`, `consultant`, `consulting`, `contractor`, `contract`, `private family`, `volunteer`, `education`, `.`, `-`, `--`, `tbd`, `myself`, `me` to `_PLACEHOLDER_EXACT`; set `company_confidence` < 1.0 for inherited rows; regenerate `curated_promoted.py` after the vocab is clean (or drop the seven contaminated keys above by hand). Test: "no value with id-share < 50% maps to `id:`"; "no curated key whose display differs token-wise from its id has > 50% inherited rows".

---

### C2 — CRITICAL — Name rules (3.34M step rows, 31% of all steps) misfire at scale; rule order shadows more specific rules; never precision-tested on the data

`industry/name_rules.py` is a single ordered list scanned first-match (`match()`, lines 268-280). Multiword phrases come first, then finance, healthcare, education, public, construction, … so a generic token in an early section beats a specific phrase in a later one. Evidence from `company_industry.matched` (`q2_rules.out`; rows = career steps):

| rule → code | rows | what it actually hits (rows) | verdict |
|---|---|---|---|
| `electric` → RE.CNST.TRADE | 21,809 | Pacific Gas and Electric 1,735; Schneider Electric 1,544; Westinghouse Electric 783; American Electric Power 692; GD Electric Boat 351; Portland General Electric 241; Tampa Electric 60 | wrong L1 for the bulk; **`electric power` (ENR.UTIL.POWR) fires 0 times — dead, shadowed** |
| `city of` → PUB.GOV.SLOC | 51,730 | "Columbia University in the City of New York" 1,207; Museum of the City of New York 44; YWCA of the City of NY 20; 960 companies / 2,872 rows do not start with "city of" | wrong L1; precedes `university` |
| `department of` → PUB.GOV | 83,056 | United States Department of Defense 3,503 + 938; DoDEA 292 (EDU); Ohio State Dept of Athletics 39; university departments | wrong L2 (PUB.DEF) / L1 |
| `school` → EDU.K12 | 87,543 | Icahn School of Medicine 1,196; The New School 476; Harvard Business School 474; School of the Art Institute of Chicago 462; Mitchell Hamline School of Law 56; School of Rock 146 | wrong L2 for graduate/professional schools |
| `medical` → HLT.PROV.AMB | 59,381 | Medical University of South Carolina 920; Harvard Medical School 908; U Colorado Anschutz Medical Campus 608 (EDU); St. Jude Medical 703 (MDEV); medical staffing agencies 461 | wrong L1/L2 |
| `health` → HLT.PROV | 242,978 | Cardinal Health 3,183 (distributor); Elevance Health 1,962, Health Net 807, WPS (payers) | wrong L2 (largest rule after `university`) |
| `academy` → EDU.K12 | 37,498 | Academy Sports + Outdoors 796; The Recording Academy 234; Academy of Motion Picture Arts 180; US Naval/Military Academy 246 (HED) | wrong L1/L2 |
| `farm` → AGR.FARM | 14,501 | State Farm Agent 323 + State Farm 77+; Bob Evans Farms 228; Perdue Farms 225; Pepperidge Farm 180; Knott's Berry Farm 159; Farm Credit 227; Farm Bureau (insurance) | wrong L1 for most large hits |
| `dairy` → AGR.LIVE | 2,188 | Dairy Queen 675+; Dairy Farmers of America 191; Borden 55 | wrong L1 |
| `bank` → FIN.BNK | 112,485 | Food banks 1,496 rows (312 cos); blood banks 193 | wrong L1 |
| `industries` → MFG.IND | 29,226 | Goodwill Industries 2,071 (NPO); ABM Industries 715 (services); Medline 1,047 (distribution); Green Thumb (cannabis retail) | wrong L1 |
| `motors` → CON.RET.SPEC | 3,467 | Lucid Motors 295; Kia Motors America 171; Peterbilt 93; Tata/Mitsubishi Motors 148; General Motors variants 592 | OEMs coded as dealerships: wrong L1 |
| `systems` → TEC.SOF.ITSV | 66,336 | BAE Systems 2,629 + GD Mission Systems 768 (defense); Apex Systems 1,260 (staffing); UTC Aerospace Systems 361; NCI Building Systems 50 | wrong L1 |
| `foundation` → NPO.PHIL | 36,610 | National Science Foundation 599 (PUB.GOV.FED); Foundation Medicine 189 (biotech); Hazelden Betty Ford 194 (HLT); Foundation Building Materials 35 | wrong L1 |
| `capital` → FIN.ASM | 39,353 | Capital University 114; Capital Health 90; Capital Blue Cross 145; Capital One 360 / Public Funding raw → FIN.ASM while `id:capital-one` is curated FIN.BNK.COM.RET | wrong L1/L2 |
| `ventures` → FIN.ASM.PE | 7,702 | Red Ventures 371 (media); Pepsi Bottling Ventures 89; ~4k "X Ventures LLC" one-offs | mostly wrong |
| `equity` → FIN.ASM.PE | 4,769 | Equity Residential 339 (REIT); Actors' Equity Association 234 (union); Leadership for Educational Equity 78 | wrong |
| `homes` → RE.CNST.BLDG | 15,802 | Dignity Memorial Funeral Homes 129; Aimco Apartment Homes 230; children's homes; "Nursing Homes" (plural escapes the `nursing home` phrase) | mixed |
| `records` → MED.FILM | 4,016 | National Archives and Records Administration 190 | wrong L1 for archives |
| `transportation` → TRN | — | Transportation Security Administration 781+ (PUB) | wrong L1 |
| `energy` → ENR | 38,471 | Monster Energy 228 | minor |
| `pharmacy` → HLT.PROV | — | "CVS Pharmacy" raw rows 3,180 → HLT.PROV while `id:cvshealth` is curated XDV | same employer, two industries |
| `salon` → PRO.BPO | 5,633 | hair/nail salons coded as Business Process Outsourcing | nonsense L2 |
| `spa`/`fitness`/`gym` → HOS.TRVL | 22,167 | LA Fitness 1,188; 24 Hour Fitness 1,118; Planet Fitness 751 | "Travel, Tourism & Leisure" — defensible, but not travel |

Stratified 6-per-rule samples (`q2_rules.out`, bottom) confirm the pattern: `bank` sample includes "Atlanta Community Food Bank"; `electric` sample is 5/6 supply/utility/manufacturing; `school` sample is 3/6 professional schools; `academy` 4/6 non-K12; `foundation` 2/6 non-philanthropy.

Conservative count of rows with a *wrong L1* from the probes alone: ≈40k (electric ~20k, systems-defense 3.8k, motors 3k, Goodwill 2k, medical schools 2.4k, food/blood banks 1.7k, farm 1.5k, Columbia 1.2k, TSA 0.8k, Academy Sports 0.8k, dairy 0.7k, NSF 0.6k). Rows with a wrong L2 are an order of magnitude larger (`health`, `school`, `capital`, `systems`, `department of`).

Also: `needs_review` is set on a name-rule company only when the M5 prior disagrees at L1 (38,421 rows); none of the misfires above are flagged because the prior abstains on agnostic occupations.

**Downstream.** `step_industry.l1` → portal `sectors` ("Real Estate & Construction" inflated by utilities/manufacturers; "Finance" by food banks, Capital University; "Public Sector" by Columbia University; "Education" by Academy Sports; "Agriculture" by State Farm/Dairy Queen), `career_clean/soc_candidates.industry_l1_label` (jury context), archetypes `industry_l1` purity.

**Minimal fix.** (1) Add a reachability test: every `_RULES` entry must be the rule that fires on its own keyword string (`electric power` fails today). (2) Reorder: move `university`, `college`, `school of (medicine|business|law|management|nursing|public health|dentistry)`, `department of defense`, `food bank`/`blood bank` (→ NPO.SOCS), `goodwill` (→ NPO.SOCS) into the multiword block ahead of `city of`/`department of`/`bank`/`medical`/`school`; put `electric power` before `electric`. (3) Disable the tokens whose large hits are mostly wrong: `electric`, `farm` (keep `farms`), `dairy`, `motors`, `ventures`, `equity`, `records`, `academy`, `school` (keep the phrase rules), `industries`, `salon`, `systems` (or restrict to `\bsystems? (inc|llc|corp)`), `capital` unless followed by `management|partners|markets|group`. (4) Re-run `industry.run_industry` and add its gold scoring to `make test` (see M8).

---

### H1 — HIGH — `step_industry.l1` carries dotted L2/L3 codes with `depth=1`, `l2=NULL` on 5,020 nonorg rows

`industry/build_industry.py:126-142` (nonorg branch) writes `coalesce(o.code, m.code, 'XOT') AS l1`, `NULL AS l2`, `1 AS depth`, where `o.code`/`m.code` come straight from `_SOC_OVERRIDE`/`_MAJOR_TO_INDUSTRY` and are L2/L3 codes.
Measured (`q10_portal.out`): l1 ∈ {HLT.PROV 2,426, NPO.SOCS 1,171, PRO.LEGAL 801, HOS.FOOD 247, RE.CNST 194, PUB.JUST 102, PUB.DEF.AF 46, EDU.K12 29, NPO.RSCH 4}. `portal/build.py:184-189` papers over it (`min(split_part(l1,'.',1))`, comment "a few rows leak dotted subcodes"); `archetypes/role_features.py:47` reads `i.l1` raw, so `mode(industry_l1)` can return `HLT.PROV` as a category distinct from `HLT`; `career_clean/soc_candidates.py:149` splits.
Fix: `l1 = split_part(code,'.',1)`, `l2 = truncate(code,2)`, `depth = level_of(code)`; assert `l1 NOT LIKE '%.%'` and `depth = 1 + length(code) - length(replace(code,'.',''))` in a propagation test.

### H2 — HIGH — 1,993 career steps silently vanish in propagation; the 164k company_industry gap is undocumented

`career_steps` has 1,993 rows with `company_raw` NULL/blank *and* `company_id_raw` blank → `company_canonical_id` NULL, `company_method` NULL (`q1_canon.out`). In `propagate_to_steps` the org branch is an inner join `USING (key)` and the nonorg branch filters `s.key NOT LIKE 'id:%' AND s.key NOT LIKE 'raw:%'`, which is NULL for a NULL key → excluded. Exactly 10,800,787 − 10,798,794 = 1,993. No row-count assertion exists.
The 164,243-row gap between `career_steps` and `sum(company_industry.freq)` = 162,250 `nonorg:` rows (excluded from the vocab by design, `industry/common.py:73`) + these 1,993; `build_manifest.json.total_rows` (10,636,544) is presented without that caveat. Step-level unresolved (5,072,721) = company-level unresolved rows (4,933,342) + nonorg rows with no occupation prior (139,379); occupation_prior 287,345 = 264,474 org + 22,871 nonorg — reconciled.
Fix: `WHERE s.key IS NULL OR (…)` in the nonorg branch; assert `count(step_industry) == count(career_steps)`; record `nonorg_rows` and `null_key_rows` in the manifest.

### H3 — HIGH — "Curated ≈ precision 1.0" is false for the 1,982 machine-promoted keys; contaminated by C1

- `classify.py:28` gives every curated hit `confidence=1.0`, including `PROMOTED` (1,982 of 2,075 keys; 2.10M rows).
- Scoring the deterministic stack on the repo's own `GOLD_RESIDUAL` (61 companies, all present in the vocab): 37 curated hits, per-level precision **L2 0.919, L3 0.815, L4 0.5** (Vonage TEC.SOF.APP.SAAS vs TEC; Janney Montgomery Scott FIN.ASM.WM vs FIN.BNK.INV; Bridgestone MFG.AUTO.PARTS vs MFG; Swagelok, Public Storage, Sogeti over-deep). `industry/README.md:155` claims "Precision is 1.0 at L2–L4".
- Spot check of 40 random PROMOTED entries: 1 clear L1 error (`americorps` → NPO.SOCS; it is a federal agency), several L2 quibbles (`northwestern-mutual` → FIN.ASM, is life insurance; `nokia` → TEC.TELE, is equipment; `veteransunited` → FIN.BNK, is a mortgage lender; `jpmorgan` → FIN vs hand-curated `jpmorganchase` → FIN.BNK.COM).
- Seven promoted keys are labeled by an inherited display (C1 list). Hand-curated `xerox` → TEC.HRDW.COMP and `abbott-` → HLT.PHRM.PHARMA are debatable but harmless at L1.
- No duplicate keys in either dict; 0 hand-vs-promoted conflicts; every curated key is present in the vocab (2,075/2,075).
Fix: give PROMOTED entries `confidence = jury agreement` (≤0.95); regenerate after C1; add residual-gold scoring to `make test` with a floor (L2 ≥ 0.9).

### H4 — HIGH — SOC jury pooled labels include non-occupations ("Student" → 25, "Team"/"Program" → 11) and a healthcare-context bias; no fingerprint assert on the career side

`occupation_major_pooled` mechanics are sound: `role_soc_jury` is unique on `role_canonical` (299,787), `det` rows equal the 2-digit prefix on all 2,317,425 rows, 0 jury rows overlap a det code, 0 mixed strings, career_steps row count equals parsed steps (10,800,787) so the LEFT JOIN did not fan out (`q6_soc.out`).
But the labels (all `unanimous` two-juror votes) include, by rows: `student` → 25 (12,452); `team` → 11 (7,448); `program` → 11 (9,196); `research` → 19 (15,209); `creative` → 27 (12,144); `managing` → 11 (14,559); `Nursing Student`/`Student Nurse`/`Medical Student`/`Student Physical Therapist`/`Physician Assistant Student`/`Extern` → 29 (≈4.7k); and healthcare-adjacent admin titles coded as practitioners: `Service Coordinator` 1,655, `Intake Specialist` 780, `Patient Access Specialist` 753, `Documentation Specialist` 546, `Healthcare Consultant` 850, `Laboratory Manager` 851, `Clinical Consultant` 450 → 29. `run_soc_jury._non_occupation` only filters `EMPLOYMENT_FORMS` (8 strings) and empty bases (lines 45-61); "student" is not in it. The known "Intern → 29-1216" class is *not* present (det 29-1216 = 62 rows, all internists).
The portal reads `role_soc_jury` directly (`portal/build.py:170-183`), so the Education and Healthcare fan cells, launchboard year-1 fans, and `paths_grain=soc_major_pooled` routes absorb these.
PIPELINE.md ("deterministic columns are never mutated (fingerprint-asserted)") and plan R1 ("fingerprint assert, mirror apply_cip_pooled") promise a career-side fingerprint; none exists — the jury is an inline LEFT JOIN in `build_normalized.py:896-906`, and only `edu_clean/apply_cip_pooled.py:219` asserts.
Fix: extend `_non_occupation` with bare status nouns (`student`, `extern`, `team`, `program`, `research`, `creative`, `managing`, `volunteer`) and `% student`/`student %` patterns, re-run `run_soc_jury merge` (no LLM needed); add a det-fingerprint check (bit_xor(hash(linkedin_id, experience_idx, position_idx, occupation_code))) to `career_clean/soc_tests.py`.

### H5 — HIGH (interpretive) — Portal sector shares use "all windowed persons" as denominator, and `industry_unresolved_share` lumps "no job observed at year 10" with XOT; unresolved rates differ by major

`portal/analyses.py:304-339`: denominator `d` = all members with `anchor <= 2015`; a LEFT JOIN to `panel` at `anchor+10`; NULL and `XOT` both count as unresolved. Decomposition (`q10_portal.out`):

| group | windowed n | no year-10 step | XOT | resolved | XOT among observed |
|---|---|---|---|---|---|
| arts | 7,915 | 17.9% | 45.2% | 36.9% | 55.1% |
| commmedia | 7,459 | 18.7% | 38.7% | 42.6% | 47.6% |
| english | 4,612 | 22.1% | 34.2% | 43.7% | 43.8% |
| history | 2,465 | 18.7% | 33.1% | 48.1% | 40.7% |
| philrel | 1,446 | 20.5% | 35.6% | 44.0% | 44.7% |
| baseline | 144,045 | 19.1% | 34.7% | 46.2% | 42.9% |

Published arts `industry_unresolved_share` = 0.6311 is 0.179 no-step + 0.452 XOT. Arts' XOT-among-observed (55%) is 12 points above baseline (43%), so every arts sector bar is depressed relative to other majors by *resolution rate* (small studios, self-branded employers), not by employment: arts MED share is 9.9% of the cohort but 27.0% of resolved persons. The share template (`share_template.html:1853-1858`) says "of the year-10 cohort" and "X% has no resolved employer sector at year 10 … not redistributed", which is literally true but does not separate the two components. `needs_review`/`confidence` are read by no consumer (grep across portal/archetypes/cohorts/paths: none), and unresolved companies carry `sector='private'` (4.93M rows, `T.sector_of('XOT')`).
Fix: emit `no_step_share` and `industry_unresolved_share` separately; add a "share among resolved (n)" column; never print `sector` for XOT.

### M1 — MEDIUM — Published portal/share build predates the last education rebuild; no provenance check

mtimes (`ls --time-style=full-iso`): `portal/results/portal_data.json` 2026-09-01 21:15:58, `share/Humanities-Workforce-portal.html` 21:15:58; `normalized/education.parquet` 21:27:54 and `education_person.parquet` 21:27:57 (the `sections: education` run in `normalized/_manifest.json`, after commits 2922bc9/39d8471 "CIP tier reconfiguration"). The substrate cache key (`portal/build.py:50-57`) will invalidate on the next run, but nothing flags the shipped HTML as stale, and `portal/_manifest.json` records paths, not mtimes/hashes. Boundaries in `portal_data.json` equal the deterministic tiers in `edu_clean/results/tier_counts.json` (240,277 / 415,908 / 689,836), so the det tiers did not move; the pooled membership may have.
Fix: record input `(mtime, size)` in `portal/_manifest.json` and have `portal_tests` (or `make portal`) fail when an input is newer than the manifest.

### M2 — MEDIUM — Manifests cannot establish currency

`normalized/_manifest.json` is overwritten by each sectioned run; it now describes only the education section (career_steps rows/runtime/mapping inputs are gone). `industry/results/build_manifest.json` has no timestamp, no input path/mtime, and `total_rows` excludes 164k rows without saying so. PIPELINE.md: "Every build writes a `_manifest.json` … Check it before assuming a table is current" cannot be honored.
Fix: merge per-section step lists instead of replacing; add `created_at`, input stats, and `nonorg_rows`/`null_key_rows` to the industry manifest.

### M3 — MEDIUM — Fuzzy `typo_to_id` tier merges non-Latin employers and 1–2-character strings onto one id

`career_company.parquet`: 1,344 `typo_to_id` values whose ASCII normalization is ≤2 chars map to 49 ids; 1,974 rows. `id:vip-cinema-seating` (display ".") absorbs 1,875 rows of Chinese/Korean/Cyrillic employer names (`Предприниматель`, `프리랜서`, `美國加州大學柏克萊分校`, `巨匠英文`, `_`, `__`) because `normalize()` strips them to nothing and the Metaphone block key is empty (`approach_b_fuzzy.py:41`). Other bad merges in the random-40 sample: `The University of Illinois` → `id:idaho-department-of-health-and-welfare`, `T Corporation` → `id:att`, `A+R` → `id:business`, `The Chamber` → `id:chamber-cardio`, `Createch` → `id:coretech-leasing-inc-`, `Intermedics` → `id:intermedix`. The `typo` (raw→raw) sample of 40 looked clean.
Fix: skip the fuzzy tier when `len(norm) < 4` or the phonetic signature is empty; require token-set Jaccard ≥ 0.8 for `typo_to_id`; route empty-norm values to `raw:<original>` (or a `nonlatin:` bucket) instead of merging.

### M4 — MEDIUM — Occupation-prior tier: 27-xxxx (design/media) mapping is the weak link; no circularity

Sample of 40 (`q9_inherit.out`): ≈9 wrong at L1 (Ivan Smith Furniture, HomeWell Senior Care, Competition Specialties → MED via graphic designers/PR; Dierbergs grocery → HLT via pharmacist; Army ROTC → TRN; The Beach Waterpark → PUB.JUST via lifeguard; Pediatric Endocrine Associates → NPO.SOCS; Rev.com → HLT via transcriptionist). 27-2012/27-1024/27-3043 alone drive 44,831 rows to MED. 172,558 of 174,558 prior-coded companies have freq ≤ 10 (132,988 have freq 1), i.e. the "modal occupation of the workforce" is one person's title. Threshold is `MIN_OCC_CODED_FRAC = 0.5` (`occupation_prior.py:69`), no minimum row count.
Circularity: none at the data level — the vocab's `modal_occ` uses the deterministic `occupation_code` only (`industry/common.py:97`), and the SOC jury reads `step_industry` purely as prompt context (`soc_llm.py:82`); `occupation_major_pooled` is never read by industry. Build order is acyclic: career_steps → industry → soc_candidates → jury mapping → career_steps.
Fix: require `freq >= 3` for the company-grain prior; drop major group 27 (or keep only 27-2xxx performers/broadcast) from `_MAJOR_TO_INDUSTRY`.

### M5 — MEDIUM — Placeholder list gaps (see C1); "Independent"/"Home"/"Consultant"/"Contract(or)" become employers

`approach_a_rules._PLACEHOLDER_EXACT` lacks the bare forms listed under C1; they total ≈9k rows and, worse, seed ids for inheritance.

### M6 — MEDIUM — Parsed dates: second parser survives; junk years unfiltered; 487 duration strings in `end_date`; no unit test

- `paths/build_spine.py:72-90` still parses `start_date`/`end_date` from the raw strings with `try_strptime` rather than reading `start_year`/`end_year` (R7 said "single parser"). The two agree on `Mon YYYY`/`YYYY`, but any future fix lands in one place only.
- Distributions (`q7_dates.out`): 1,131 rows `start_year < 1950` (410 exactly 1900) pass through; 57 rows start in 2026 (valid); 0 rows `end_year < start_year`; 0 `is_current` with an `end_year`; `Present` is the only current marker (2,299,824 rows, no case/space variants); 1,483,296 rows have a year but no month (bare years); 80,414 have no start date.
- 487 rows carry a *duration* in `end_date` (`'5 months'`, `'1 year 5 months'`, …) → `end_year` NULL, `is_current` FALSE, indistinguishable from "no end date". Nothing flags them.
- R7 claims "unit-tested": no suite references `_month_sql`, `start_year`, or `end_year` (grep across `*_tests.py`).
Fix: `paths` reads the materialized columns; add `date_parse_method` ('month','year','present','duration','none'); test the parser on the fixture set {`Jan 2019`, `2019`, `Present`, `5 months`, `Sept 2019`, `''`}.

### M7 — MEDIUM — `SNAPSHOT_YEAR` means 2026 in `paths/common.py` and 2025 everywhere else

`paths/common.py:54` `SNAPSHOT_YEAR = 2026`, `LAST_COMPLETE_YEAR = 2025`; `portal/common.py:54`, `cohorts/common.py:29`, `archetypes/common.py:37`, `edu_clean/anchors.py:62`, `build_normalized.py:58 (EDU_SNAPSHOT_YEAR)` all define `SNAPSHOT_YEAR = 2025` with the *last-complete-year* meaning. Same name, two values — exactly the trap class that produced the 182k-row slip. Current uses are internally consistent (checked every `SNAPSHOT_YEAR` reference in portal/cohorts/archetypes).
Fix: rename the four 2025 constants to `LAST_COMPLETE_YEAR` and import from `paths.common`.

### M8 — MEDIUM — Tests: `make test` is not data-independent; the industry classifier is never scored; abstention is counted as a false positive

- `edu_clean/tier_tests.py` reads `normalized/education.parquet` (drift checks); `edu_clean/dlevel_tests.py` reads `mappings/`. PIPELINE.md/README call `make test` "data-independent".
- `industry/tests.py` validates codes, precedence on 7 hand strings, and the LLM/pool plumbing (≈60 of its checks are about `llm_pool`, whose cache no longer exists); `test_gold_residual` checks shape only; `run_industry.eval_gold` is not in any Make target.
- `industry/common.level_scores` treats `XOT` as a prediction at L1, so an abstention is a false positive: GOLD_COMPANIES L1 precision prints 0.897 with 3 "fp" that are all XOT (Booz Allen, Rivian, Chobani). Excluding XOT, L1 precision is 26/26. README's "L1 misses" narrative is a metric artifact.
- Nothing tests: company key join integrity (row counts), NULL-key handling, `l1` dottedness, name-rule reachability/precision on real displays, vocab modal-id support, curated-display consistency, date parsing, `occupation_major_pooled` = prefix.
- `portal_tests`/`cohort_tests`/`spine_tests`/`seniority_tests` (not in `make test`) are substantive; none touches industry beyond "no sector cell below MIN_SUPPORT".

### M9 — MEDIUM — Docs describe a state that no longer exists (details in section C)

### L1 — LOW — Duplicate profiles: 69 of 88 duplicated step keys are *different jobs* sharing a key

48 duplicate `linkedin_id`s → 88 step keys with multiplicity 2 in `career_steps` (10,800,787 rows vs 10,800,699 distinct keys) and in `step_industry`. `is_duplicate` catches 19 (18 once, 1 twice); the other 69 differ in content (experience_idx restarts per profile row), so PIPELINE.md's "content-level duplicate flags catch their rows downstream" is false for them, and any join on the step key (`soc_candidates`, `archetypes/role_features`) fans out 2×2 on those keys. `education_person` has 1,999,974 distinct ids vs 1,999,952 distinct profile ids (22 education ids without a profile row). Negligible volume; wrong claim.

### L2 — LOW — Cruft / footguns

`edu_clean/rebuild_education_person.py` still exists and, run alone, rewrites `education_person.parquet` *without* `inst_*` columns (must be followed by `apply_institution_meta`); `build_normalized.py` now does both. `normalized/education.parquet.bak` (258 MB) left behind. `build_industry --cap N --propagate` would silently drop steps (inner join). `_cache_fresh` is mtime-based (a `touch`/checkout makes a stale vocab look fresh). `company_confidence = 1.0` on 631,105 inherited rows.

### Silent-failure / determinism hunt — nothing else found

No bare `except:` or `except … pass` in live code; the only broad catches are `build_normalized.py:1053` (SystemExit → skip IPEDS, prints) and `portal/build.py:81` (cache key parse). No hard-coded `/home/alex` or `/tmp` paths. Ordering in the industry path is deterministic (vocab `ORDER BY freq DESC, key`; display/occupation modes tie-broken by value; `CURATED = {**PROMOTED, **CURATED}`; rules are a list; `load_vocab` orders by `freq DESC, value ASC`; fuzzy blocks use sorted signatures).

---

## B. Tests to add on the employer/industry path

| # | Test | Where | Fails today on |
|---|---|---|---|
| 1 | Every `_RULES` entry fires on its own keyword (reachability) | `industry/tests.py` | `electric power` |
| 2 | Negative fixtures: Food Bank→not FIN; State Farm→not AGR; Dairy Queen→not AGR; Columbia University…City of New York→EDU; Dept of Defense→PUB.DEF; Harvard Business School→EDU.HED; PG&E→ENR; Goodwill Industries→NPO; BAE Systems→not TEC.SOF; Academy Sports→not EDU; NSF→PUB | `industry/tests.py` | all of them |
| 3 | Residual/gold scoring floor (`run_industry.eval_gold`, `GOLD_RESIDUAL`): L1 ≥ 0.95 (XOT excluded), L2 ≥ 0.90 | new `industry/gold_tests.py` in `make test` | L2 0.919 / L3 0.815 |
| 4 | `level_scores`: XOT is an abstention (fn), not fp | `industry/tests.py` | GOLD_COMPANIES L1 |
| 5 | Propagation: `count(step_industry) == count(career_steps)`; no NULL key dropped | `industry/tests.py --data` or `normalization_regression_checks.py` | 1,993 rows |
| 6 | `step_industry.l1` has no '.', `depth == level_of(industry_code)`, `l2` non-null when depth ≥ 2 | same | 5,020 rows |
| 7 | Vocab: no value maps to `id:` unless id-bearing rows ≥ max(3, 50%) | `career_clean/se_tests.py` or new `company_tests.py` | University of Michigan etc. |
| 8 | Curated keys: display of every curated `id:` key shares ≥1 token with the id, or ≥50% of its rows carry their own id | `industry/tests.py` (data) | ucsdhealth, consultant_66, integris-for-banks, kpn, thebeach2 |
| 9 | Placeholder fixtures: `Independent`, `Home`, `Consultant`, `Contract`, `.`, `-` → `nonorg:` | `normalization_regression_checks.py` | all |
| 10 | Fuzzy tier: values whose normalization is < 4 chars or non-Latin never `typo_to_id` | `normalization_regression_checks.py` | `프리랜서`→vip-cinema-seating |
| 11 | `occupation_major_pooled == left(occupation_code,2)` where det; det fingerprint unchanged across a `--skip-mappings` rebuild | `career_clean/soc_tests.py` | passes now; guards R1 promise |
| 12 | Jury merge excludes bare status nouns (`student`, `team`, `program`, …) | `career_clean/soc_tests.py` | `student`→25 |
| 13 | Date parser fixtures (`Jan 2019`, `2019`, `Present`, `5 months`, blank) and `end_year >= start_year` invariant | `normalization_regression_checks.py` | duration strings unflagged |
| 14 | Portal: `sectors[].share` sum + `no_step_share` + `industry_unresolved_share` == 1; unresolved decomposed | `portal/portal_tests.py` | field absent |
| 15 | Manifest freshness: every portal input older than `portal/_manifest.json` | `portal/portal_tests.py` | education.parquet newer |
| 16 | `make test` suites import no parquet (or move tier/dlevel tests to `test-data`) | Makefile | tier_tests |

---

## C. Doc corrections

| File:line | Claim | Reality |
|---|---|---|
| PIPELINE.md §Tests, README.md §Setup | "`make test` runs the data-independent suites" | `edu_clean/tier_tests.py` reads `normalized/education.parquet`; `dlevel_tests` reads `mappings/` |
| PIPELINE.md §Conventions | "48 duplicate linkedin_ids … content-level duplicate flags catch their rows downstream" | 69 of 88 duplicated step keys are unflagged (different jobs sharing a key) |
| PIPELINE.md §Jury | "deterministic columns are never mutated (fingerprint-asserted)" | only the CIP apply asserts; the SOC pooled join has no fingerprint |
| PIPELINE.md §Conventions | "Check `_manifest.json` before assuming a table is current" | `normalized/_manifest.json` records only the last section; `build_manifest.json` has no timestamp/inputs |
| PIPELINE.md DAG | `industry/build_industry.py company → industry (L1..L4) + step_industry` | omit that `nonorg:` (162,250) and NULL-key (1,993) rows are outside `company_industry`, and NULL keys are dropped from `step_industry` |
| industry/README.md:161-165 | coverage "L1 42.0%, L2 37.8%, L3 17.3%, L4 1.4%" | `build_manifest.json`: 53.6 / 48.7 / 23.7 / 2.0 |
| industry/README.md:155 | "Precision is 1.0 at L2–L4" | residual gold: L2 0.919, L3 0.815, L4 0.5 (curated only) |
| industry/README.md:50-54, name_rules.py docstring | "M3 fires only on unambiguous tokens" | see C2 |
| industry/README.md:7, industry/__init__.py:7, METHODS.md | `../INDUSTRY_PLAN.md` / "see INDUSTRY_PLAN.md" | file is `docs/plans/archive/INDUSTRY_PLAN.md` |
| industry/METHODS.md §2.8-2.9 | "row L1 coverage 41.9%"; "2,023,473 residual classified (99.82%)"; "All 2.02M votes are propose-only in `llm_*` columns"; "Offline = pure cache read"; "Frozen, content-hashed cache" | `llm_*` columns are all NULL (`llm_candidates: 0`); the cache was destroyed 2026-09-01 (SETUP.md says so; METHODS.md does not) |
| industry/SETUP.md §1 | "`run_industry` reads the committed `llm_proposals.jsonl` cache" | file absent; `llm.load_cache` returns `{}` silently (llm.py:143) |
| industry/classify.py:28 `_CONF_CURATED = 1.0` | curated = P≈1.0 | applies to 1,982 machine-promoted keys too |
| portal/common.py:70,78 | "COVERAGE_PLAN.md Plan 2", "PORTAL_REDESIGN_PLAN.md" | both in `docs/plans/archive/` |
| archetypes/common.py:27 | "ARCHETYPES_PLAN.md §3" | `docs/plans/archive/ARCHETYPES_PLAN.md` |
| docs/plans/2026-09-01 R1 | acceptance "deterministic fingerprint unchanged" | no assert implemented |
| docs/plans/2026-09-01 R7 | "single parser, unit-tested" | `paths/build_spine.py` re-parses; no test |
| docs/plans/2026-09-01 F2 / edu_clean/apply_institution_meta.py:10 | `rebuild_education_person` as a pipeline step | superseded by `build_normalized.write_education_person`; running it alone strips `inst_*` |
| build_normalized.py:896 comment | "unanimous role->SOC-major jury vote (…, 299,787 roles)" | true, but labels include non-occupations (H4) |
| portal share_template.html:1853 | "X% has no resolved employer sector at year 10" | 18–22 points of X are persons with no observed step at year 10 |

---

## D. Appendix — reproducing queries

All scripts run with `uv run python <script>`; outputs saved beside them.

- `q1_canon.py` / `q1_canon.out` — NULL-method rows; key-class reconciliation (`id` 7,829,820 / `raw` 2,806,724 / `nonorg` 162,250 / NULL 1,993); placeholder-like displays with ids; `id:vip-cinema-seating` and `id:region-vii-area-agency-on-aging` breakdowns.
- `q1b_canon.py` / `.out` — inherited-id rows (631,105) and id-share buckets; worst inherited values; degenerate typo merges; non-ASCII names; raw/id collisions; random raw sample; ids with many raw names.
- `q2_rules.py` / `.out` — rows per `matched` keyword; 50 misfire probes; 6-per-rule stratified samples (top 40 rules).
- `q3_prior_curated.py` / `.out` — occupation-prior by modal_occ, freq distribution, top-25; curated key presence, conflicts, duplicates, 40 random PROMOTED; top-40 unresolved; MetLife/Siemens/Netflix/Uber keys.
- `q6_soc.py` / `.out` — role_soc_jury uniqueness; det prefix check; top-60 jury roles; intern/student probes; major distribution; career_steps vs parsed row count.
- `q7_dates.py` / `.out` — date sanity counts; non-date end/start strings; year tails; Present variants; duplicate profiles and step keys; step_industry key uniqueness and dotted l1; education_person vs profiles.
- `q9_inherit.py` / `.out` — university/placeholder canonical ids and industries; `id:upmc` etc.; L1 conflicts on inherited rows; curated keys fired mostly on inherited rows; fixed random samples (typo_to_id, typo, occupation_prior).
- `q10_portal.py` / `.out` — decomposition of `industry_unresolved_share` from `portal/results/_cache/{membership,panel}.parquet`; arts sector shares renormalized; dotted-l1 codes; step_industry method × key class.
- `q11_more.py` / `.out` — `city of` / `department of` misfires; same-display id-vs-raw L1 disagreement; placeholder-like values glued to ids; duplicate-profile flag audit; Capital One keys; confidence on inherited rows.
- Gold scoring (inline): `industry.run_industry.eval_gold()` / `eval_rows()`; `GOLD_RESIDUAL` scored through `classify.classify_company` with the real vocab rows (`industry/cache/company_vocab.parquet`).

Key one-liners:

```sql
-- inherited modal ids
SELECT count(*), count(DISTINCT company_id_canonical) FROM read_parquet('normalized/career_steps.parquet')
WHERE company_method='company_id' AND (company_id_raw IS NULL OR trim(company_id_raw)='');            -- 631105, 139968
-- dropped NULL keys
SELECT count(*) FROM read_parquet('normalized/career_steps.parquet') WHERE company_canonical_id IS NULL; -- 1993
-- dotted l1
SELECT l1, count(*) FROM read_parquet('industry/results/step_industry.parquet') WHERE l1 LIKE '%.%' GROUP BY 1; -- 5020 rows
-- dead rule
SELECT count(*) FROM read_parquet('industry/results/company_industry.parquet') WHERE matched='electric power';   -- 0
-- Columbia University -> state/local government
SELECT display, industry_code, freq FROM read_parquet('industry/results/company_industry.parquet')
WHERE display LIKE 'Columbia University in the City%';                                                  -- PUB.GOV.SLOC, 1207
-- students coded as Education / Healthcare
SELECT role_display, occupation_major_pooled, count(*) FROM read_parquet('normalized/career_steps.parquet')
WHERE occupation_source='jury' AND lower(role_display) IN ('student','nursing student','medical student') GROUP BY ALL;
```
