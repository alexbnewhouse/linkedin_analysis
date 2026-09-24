# Audit A (demand side): what the user journey needs from the pipeline, and what the pipeline can supply

Repository: /home/alex/linkedin-analysis, branch recovery-refactor, working tree clean. Audit date 2026-09-13. All queries were run read-only with DuckDB against the committed parquet and JSON outputs on disk; nothing in the repository was modified.

## 1. Method

What I read, in order:

1. The four allowed journey documents in full: docs/design/2026-09-10-user-journey.md (the section 5 chart, section 6 copy, section 7 rules), 2026-09-10-user-journey-narrative.md, 2026-09-10-user-journey-plain.md, 2026-09-10-site-concept.md.
2. Repository orientation: Makefile, pyproject.toml, .gitignore, git ls-files, the directory listings of every output directory (normalized/, paths/, portal/results/, cohorts/, archetypes/results/, transition_network/, industry/results/, enrichment/results/, reference/, share/).
3. The portal module in full (portal/common.py, run_portal_data.py, build.py, analyses.py, pathways.py, launchboard.py, choices.py, run_share_build.py, portal/_manifest.json, the check list of portal_tests.py), because portal/results/portal_data.json is the only output a website could consume today.
4. The spine and cohort layers: paths/common.py, paths/_manifest.json, the step SELECT of paths/build_spine.py, cohorts/common.py, cohorts/build_panel.py, cohorts/_panel_manifest.json.
5. The archetypes layer: archetypes/common.py, archetype_spec.py (lines 1-200), yearwise.py, and the three result manifests.
6. transition_network/common.py and the header of build_network.py plus the three axis manifests; cert_clean/run_cert.py header; enrichment/build_enrichment.py header; edu_clean/humanities.py tier table; the location columns of build_normalized.py; share/system-schema.mmd; scripts/refresh_downstream.sh.

What I queried (DuckDB, read-only), in order: schemas and row counts of the eight main parquet tables; the structure of portal_data.json; the humanities cohort under every definition the data supports; the title-tail statistics under six candidate definitions; year-10 archetype occupancy; the policy-to-management corridor; industry L1 and SOC major group counts; US-state and institution-type coverage; certification schema, coverage and named-credential support; degree levels and field groups; transition-network edge schemas; top-destination shares under the portal and archetype framings; prototype "ways in", "backward origins" and "elapsed years" queries for one destination; the Classics worked example; state coverage at the year-10 step.

Evidence tags: VERIFIED means I ran the query or read the cited lines; INFERRED means reasoned from verified facts but not directly checked.

Two figures I use throughout and their sources (VERIFIED):

- The journey's "486,000 with a humanities degree" is `education_person.nha_level IN (1,2,3)` = 485,781 persons. Query: `SELECT count(*) FILTER (WHERE nha_level IN (1,2,3)) FROM 'normalized/education_person.parquet'`. This is the terminal-degree field under the deterministic crosswalk, at the L3 "liberal arts" tier.
- The journey's "407,000 observable across career years 1 to 15" is that same set restricted to `cohorts/profiles.valid_cohort` (entry year 1990-2020) = 407,872. Query: join education_person to cohorts/profiles on linkedin_id, `WHERE nha_level IN (1,2,3) AND valid_cohort`.

## 2. Inventory: the coverage matrix

Status vocabulary: SERVABLE = exists as a stable output with a discoverable schema a website could read without re-running analysis (today that means portal/results/portal_data.json, or a small committed parquet/JSON); PRODUCED-NOT-SERVABLE = exists in a parquet or in-memory temp table but not in a shape a site could read (person-grain, corpus-wide, or needs a join and suppression at query time); PARTIAL = part of the element exists; ABSENT = nothing in the pipeline produces it.

Column "Producer" names the module, file and table/column. Lines cited were read.

### Band 0 (arrive) and the state model (STATE, METER, ROUTE, TRAIL)

| Journey node | Data element required | Producer | Status |
|---|---|---|---|
| AR1-AR5, STATE | A query surface taking (origin, destination, horizon, grain, like-me filters, sort, relaxed rungs) from the URL and returning a cell | None. portal/run_portal_data.py:90-186 writes one static JSON for five majors; share/system-schema.mmd marks "Live aggregate DB (TARGET, to build)" and "Read API (to build)" | ABSENT |
| METER | Person-support n of the named cell in the exact state, against MIN_SUPPORT=10 | portal/common.py:131 MIN_SUPPORT; portal_data.json `min_support`; n on every fan cell (analyses.py:78) but only for the precomputed cuts | PARTIAL (fixed cuts only) |
| STALE | "Does the linked cell still clear ten in this build" (release versioning) | portal_data.json `generated`, `snapshot_date` (run_portal_data.py:91-92); no release id, no previous-build comparison | PARTIAL |
| AR4/SKEP | Population statement: 2.0M profiles, 486,000 humanities, 407,000 followable | cohorts/_panel_manifest.json profiles=1,999,916; 485,781 and 407,872 derivable by query (see Method) but not emitted; portal_data.json `boundaries` emits 210,495 / 358,675 / 579,325 (l1/l2/l3 persons on education.parquet), none of which is 486,000 | PRODUCED-NOT-SERVABLE, and the definitions disagree |

### Band 1 (the field, Q0)

| Journey node | Data element required | Producer | Status |
|---|---|---|---|
| FIELD | Every year-10 destination for the whole humanities cohort, unranked, with counts | portal: `baseline.fan` is all CIP-coded bachelors (144,045 windowed), not humanities; per-major fans exist for 5 majors only (common.py:165-171). archetypes/results/occupancy.parquet gives (entry_cohort, career_year, archetype) counts for the pooled L1-L3 cohort (647,784 persons) at 16-archetype grain | PARTIAL: pooled humanities field exists only at archetype grain in a parquet, not in portal_data.json |
| FIELD copy "407,000 ... what they were doing at year ten" | Year-10 count for the 407k | Derivable: of 407,872, 336,735 have a year-10 window, 330,707 a panel row at year 10, 208,498 a SOC major at year 10 (query in A5) | PRODUCED-NOT-SERVABLE |
| FIELDTAIL, TAILSTATE | Distinct titles, singleton share, share of working life in singletons, titles clearing ten | Not produced by any module. Closest reproduction: L2 tier x role_canonical on paths/steps.parquet = 622,196 titles across 357,934 people, 86.4% singletons, 26.9% of tenure-months, 13,709 titles at >=10 (journey says 638,368 / 355,437 / 86.4% / 29.2% / 13,933) | ABSENT as an output; approximately reproducible |
| ONELINE | Largest single destination share for the field | portal `diversity.top_bucket_share` per major (analyses.py:201); baseline 0.1452; English 0.1271; Arts 0.2379 | SERVABLE for 5 majors; the "one in eight" sentence is not a constant (A6) |

### Band 2 (narrow: the three doors)

| Journey node | Data element required | Producer | Status |
|---|---|---|---|
| D1 "What I studied" | Every field of study as an origin | education.parquet cip2 (41 families at bachelor level), cip4 (362), humanities_field_group_pooled (22 labels; edu_clean/humanities.py:113-138). Portal serves 5 CIP2 bundles. Field-group grain lives in cohorts/panel.humanities_field_group and archetypes person_year_archetype.humanities_field_group (terminal pooled field, so a JD/MBA overwrites the BA) | PARTIAL: 5 of 41 families servable |
| D2 "What I like doing. Eleven first-person descriptions" | An eleven-way grouping of work | None. Grains that exist: 23 SOC major groups (transition_network/common.py:57-68), 15 archetypes + Other (archetypes/archetype_spec.py:24-57), 17 industry L1 (industry/taxonomy.json) | ABSENT |
| D3 "A job I am curious about, from the 13,933 titles that cleared the bar" | Title list with person counts >= 10, display names | role_canonical + role_display 1:1 on normalized/career_steps.parquet (2,605,247 roles); role_display is not on paths/steps.parquet or cohorts/panel.parquet (build_spine.py:110-129 carries role_canonical only) | PRODUCED-NOT-SERVABLE |
| DNONE | Search box over titles | same as D3 | PRODUCED-NOT-SERVABLE |

### Band 3 (the canvas: Q1, Q2, Q3)

| Journey node | Data element required | Producer | Status |
|---|---|---|---|
| Q1 forward fan: origin set, destination open, year-10 shares with counts | portal `majors[*].fan` (SOC major grain, n, share, rr, per-cell `detail` roles) for 5 majors at year 10; launchboard fans at years 1/3/5 (launchboard.py:34) | SERVABLE for 5 majors x 4 horizons at SOC-major grain |
| Q1 copy "23 occupation groups were recorded at career year 10 for people who started here" | groups_reached per origin | portal `diversity.groups_reached` (English 16, baseline 23) | SERVABLE; the copy's 23 is the baseline, not a humanities field |
| Q2 corridor: both poles set, "N people held X at year 1 and Y at year 10" | (position at year 1) x (position at year 10) joint counts per origin field | None. transition_network edges are adjacent job-to-job moves corpus-wide (build_network.py docstring; role axis 4,387,447 edges); archetypes/results/state_flows.parquet is year t to t+1; portal `paths` are 2-4-stage SOC-major chains, max 8 per major (common.py:159-161) | ABSENT; derivable from cohorts/panel + archetype panel (A7) |
| Q3 backward origins: destination set, "what they studied and where they began" | destination -> field of study distribution; destination -> year-1 role distribution | None emitted. Prototype on archetype panel works (A8) | ABSENT |
| TRAIL | none (interface) | — | n/a |

### Band 4 (inside a destination: five panels)

| Journey node | Data element required | Producer | Status |
|---|---|---|---|
| P2 "Ways in: jobs held at year one, named, with counts" | For a destination cell, the year-1 role distribution with n >= 10 | None emitted. cohorts/panel.parquet has (linkedin_id, career_age, role_canonical) so it is one query away; suppression at title grain removes most people (A9) | ABSENT |
| P2 / TAKE block 3 "typical elapsed years" | Years from career start to first entry into the destination | None emitted; derivable from person_year_archetype (median 2, IQR 1-7 for archetype 11) | ABSENT |
| P1 "What this work involved. Composited from how people described it" | Step descriptions per destination | normalized/career_steps.parquet `description` (build_normalized.py: normalize_description) at step grain; career_clean/results/se_description_eval.json for self-employed only | PRODUCED-NOT-SERVABLE; no compositing step exists |
| P3 "What they studied" | destination -> field distribution | same as Q3 | ABSENT |
| P4 "What they carried. Certifications and licences, named, with counts" | destination x named credential counts | normalized/certifications_person.parquet is a per-person 19-domain rollup (cert_clean/run_cert.py:6-10); named credential + issuer only in parsed/certifications (title, subtitle), uncanonicalized; not joined to any destination | PARTIAL (domain flags at person grain) |
| P5 "Where it happened. Employers, and a US state" | destination x employer counts; destination x state counts with denominator | portal `employer_field` is major x employer in years 0-5 (analyses.py:355), names only at n >= 10; state: location_us_state is on career_steps (build_normalized.py:956) but not on paths/steps.parquet (build_spine.py:129 carries raw `location` only), so panel and portal have no state | PARTIAL / ABSENT |

### Band 5 (every noun is a door)

| Journey node | Data element required | Producer | Status |
|---|---|---|---|
| NDEST job title / occupation / industry as destination | cells at title, SOC-major, and industry L1 grain | SOC-major: portal fans; industry L1: portal `sectors` at year 10 per major (analyses.py:304); title: none | PARTIAL |
| NEMP employer as filter or destination | employer-conditioned cells | none beyond employer_field | ABSENT |
| NFOS field of study as origin or like-me filter | field dimension on every cell | 5 majors in portal; 22 field groups in panels | PARTIAL |
| NGRAD graduate degree as filter or destination ("people whose next step was this degree") | grad enrolment by level/type with the career year taken | portal `launchboard.grad_track`: share within 5 years of the bachelor anchor by level and type (launchboard.py:49-70); no per-year timing, no grad-as-destination view | PARTIAL |
| NCRED credential as filter | person-level has_<domain> flags | certifications_person.parquet (19 domains) | PRODUCED-NOT-SERVABLE |
| NGEO US state as filter | state on the step | career_steps.location_us_state; education_person.inst_state (74.1% of cohort) | PRODUCED-NOT-SERVABLE |
| SECOND / SWAP / compare (two columns) | two cells side by side | any two precomputed cells | follows the cell layer |

### Band 6 (when it is thin: the ladder)

| Journey node | Data element required | Producer | Status |
|---|---|---|---|
| LAD1 below-bar detection and the count of people inside the suppressed region | n for every cell including those < 10 | portal emits only cells >= 10 (analyses.py:73) plus `paths_suppressed_count`, `unclassified_share`; below-bar counts are not emitted | PARTIAL |
| LAD2 rung 1: drop institution type or US state | institution type and state as filter dimensions | education_person.inst_control_label / inst_carnegie_label / inst_iclevel_label (74.1% coverage in the 486k cohort) and career_steps.location_us_state; neither is consumed by portal, cohorts or archetypes (grep: no hits) | ABSENT as a dimension |
| LAD3 rung 2: widen the field of study | nested field grain (CIP4 -> CIP2 -> field group -> tier) | edu_clean/humanities.py tiers; education.parquet cip4/cip2 | PRODUCED-NOT-SERVABLE |
| LAD4 rung 3: titles -> "the eleven kinds of work" | an eleven-way grain | none (see D2) | ABSENT |
| LAD5 rung 4: pool years 8-12 | fans at every career year, poolable at person grain | portal fans only at 1/3/5/10; archetypes occupancy.parquet at years 1-15 per entry cohort but aggregated per year (distinct persons cannot be pooled from it); person_year_archetype.parquet is person grain | PARTIAL |
| LAD6 rung 5: drop the origin -> Q3 | destination-only cell | same as Q3 | ABSENT |
| STIPPLE | number of people inside the suppressed region | not emitted | ABSENT |

### Band 7 (the tail is the argument)

| Journey node | Data element required | Producer | Status |
|---|---|---|---|
| SORT most common / most distinctive / rarest >= 10 | share, rr vs baseline, n per cell | portal fan cells carry share, rr, n (analyses.py:78); baseline is all CIP-coded bachelors (run_portal_data.py:100-103) | SERVABLE for 5 majors |
| TAILSTATE "titles shown, suppressed, people inside" per view | tail block per cell | not emitted | ABSENT |
| RARE | n for a rare title as a destination | title-grain cells absent | ABSENT |

### Band 8 (standing doors)

| Journey node | Data element required | Producer | Status |
|---|---|---|---|
| WAGE: the federal occupation code for the destination | SOC code per destination | soc_major (2-digit) on 61.3% of steps, occupation_code (6-digit) on 21.5% (paths/steps.parquet); SOC-major labels in transition_network/common.py:57-68; no code for an archetype (archetype 11 = SOC 19 + 23, archetype_spec.py:96-97) | SERVABLE at SOC-major grain only |
| GEO "N of these M had a US state recorded" | state coverage per destination with denominator | not emitted (state absent from spine) | ABSENT |
| LIMITS "what this sample cannot see" | provenance strings | portal_data.json `window_rule`, `baseline_def`, `occupation_coverage_note`, `fan_detail_note`, `anchor_tiers_note`, `launchboard_notes`, `diversity_note` | SERVABLE (prose, per release) |

### Band 9 and 10 (leave with something; after)

| Journey node | Data element required | Producer | Status |
|---|---|---|---|
| CARD / 7.1 claim contract: population, n, horizon, bar, not_observed | five fields per cell | n and bar present; horizon only implied by the key name (`fan` = year 10 via common.py:123, not carried in the payload); population string and not_observed absent | PARTIAL |
| TAKE block 2: snapshot date | `snapshot_date` = 2026-02-19 | SERVABLE |
| TAKE block 3: three named routes with counts and elapsed years | routes into a destination | portal `paths`: 2-4-stage SOC-major chains per major, origin-keyed not destination-keyed, no elapsed years (pathways.py:42-114); the role-grain `mine()` variant with median dwell exists but is not called (run_portal_data.py:47 calls mine_soc) | PARTIAL |
| TAKE block 4 / ACT1: a credential with provider and next enrolment date | named credential, issuer, provider date | parsed/certifications title+subtitle; no provider dates (out of scope of this corpus by the journey's own rule) | PARTIAL |
| ACT2: graduate step, count and the career year taken | grad_track (5-year window, no per-year timing) | PARTIAL |
| ACT3: employers in this state, and "2,682 employers appear exactly once" | employer x state; singleton employer counts | employer_field singleton buckets per major (English 8,641; History 4,292; Phil&Rel 2,837); no state dimension; 2,682 not reproducible | PARTIAL |
| ADV / BACK / RET / CLASSAGG | interface state only | — | n/a |

## 3. Findings

### A1. There is no query layer; the only servable output is one static JSON for five majors

Severity: BLOCKING. Journey steps: STATE, METER, ROUTE, every band that follows.

The journey's load-bearing decision is `mode = f(origin?, destination?)` with a support meter on "the named cell in this exact state" (section 5, STATE and METER nodes; rule 7.1). That is a request for a cell at arbitrary (origin, destination, horizon, grain, filters). The pipeline's servable output is portal/results/portal_data.json, written once per refresh by portal/run_portal_data.py:90-190 for the five CIP2 bundles in portal/common.py:165-171 plus a baseline, at horizons 1, 3, 5 (launchboard.py:34) and 10 (common.py:123). It is injected verbatim into a static HTML page (run_share_build.py:5-9, share_template.html:857 `const PORTAL = __PORTAL_DATA_JSON__`). share/system-schema.mmd draws "Live aggregate DB (TARGET, to build)" and "Read API (to build)". A grep for flask/fastapi/http.server/express across the repo returns nothing.

VERIFIED (files read; grep run).

Recommendation: decide between (a) a precomputed cell cube at the grains the journey names, with suppression baked in and a static-JSON-per-cell layout the site can fetch, or (b) a small DuckDB-backed read API applying MIN_SUPPORT at query time over a person-year table. Either way the cube's dimensions must be fixed first (A2-A5). Effort L.

### A2. "What I studied" means any field; the pipeline serves five majors

Severity: BLOCKING. Journey steps: D1, NFOS, LAD3, AR2, LAD1, CHOICE.

The journey's origin door is any field of study (D1; narrative step 4 "fields of study"), and its worked example is Classics (AR2, LAD1, CHOICE). The portal serves English, History, Philosophy & Religion, Fine & Performing Arts, Communication & Media (portal/common.py:165-171). Education carries 41 CIP2 families and 362 CIP4 codes at bachelor level (`SELECT count(DISTINCT cip2), count(DISTINCT cip4) FROM 'normalized/education.parquet' WHERE degree_level=4` -> 41, 362) and 22 humanities_field_group labels. Classics is CIP 16.12 / 30.22, mapped to the "Languages & Linguistics" group (reference/cip_humanities.parquet), which is not one of the five portal majors. There are 427 Classics persons in the corpus (cip4 IN ('16.12','30.22')), 364 in a valid cohort, 309 with a year-10 panel row, 188 with a SOC major at year 10; six SOC major groups clear ten (11: 42, 25: 40, 27: 23, 15: 14, 13: 14, 43: 10) and Legal (23) is 6. So the journey's own example origin is (a) unservable today and (b) mostly below the bar at year 10 once a destination is fixed, which is consistent with the LAD1 copy but means the ladder is the common case for small fields, not the 1.5% case the site concept assumes (section 7 of the site concept).

VERIFIED (queries above).

Recommendation: fix the origin grain (recommend humanities_field_group for the door, CIP2 family for the alternate, CIP4 only inside the ladder) and generate fans for every value, not five. Effort M (the portal machinery is parametrised by MAJORS; extending it to 22 groups is mostly config and runtime).

### A3. The "eleven kinds of work" do not exist in the pipeline

Severity: BLOCKING. Journey steps: D2, DNONE, LAD4 (rung 3), narrative step 4, site-concept section 9 ("the eleven first-person descriptions ... do not exist yet").

The journey's second door and the third rung of the ladder assume an eleven-way coarse grain of work. No such grouping exists. The coarse grains that exist are 23 SOC major groups (transition_network/common.py:57-68; portal fans), 15 archetypes plus "Other / Unclassified" (archetypes/archetype_spec.py:24-57), and 17 industry L1 sectors (industry/taxonomy.json, level 1). A grep for "eleven" across code and templates finds only unrelated hits. The site concept separately bans the archetype vocabulary on screen (section 8), so the 15-archetype grain cannot be the eleven as-is.

VERIFIED (files read; taxonomy counted; grep run).

Recommendation: write the eleven and commit a crosswalk from SOC major group (and archetype, for the self-employed residue) to them, then add the grain to the cell cube. Until that exists LAD4 has no rung to climb to. Effort M.

### A4. The journey's time axis is undecided, and the pipeline has two different ones

Severity: BLOCKING. Journey steps: every copy string with "career year N"; FIELD, Q1, Q2, Q3, CARD, LAD5, ACT2; site-concept section 9 decision 2.

The journey says "career year 1", "career year 10", "career years 1 to 15", and section 9 of the build doc notes the axis is "absolute career-year". The pipeline computes two different things under that name:

- Portal: `career_age = calendar_year - group anchor` where the anchor is the bachelor's graduation year (A1 observed end_year or A2 start+duration; portal/build.py:13-14, portal/common.py:68-75, 119-123). Year 10 means ten years after graduation.
- Cohorts and archetypes: `career_age = calendar_year - entry_year` where entry_year is the first datable primary job (cohorts/build_panel.py:9-16 and :96; archetypes/yearwise.py:3 and :39). Year 10 means ten years after the first job.

The graduation anchor is available for a minority of the humanities cohort: cohorts/profiles.graduation_year is non-null for 101,176 of 485,762 (20.8%) and archetypes/results/_yearwise_manifest.json reports anchor_tier_persons null=562,325 of 647,784. archetypes/common.py:140-146 states the rationale: entry-vs-graduation lands in a different five-year bin 60% of the time. The site concept (section 9) records that the axis decision is open and that the exit step (message 8) is blocked on it. Every number in the journey changes with the axis. The portal fans are on the graduation axis (VERIFIED). The 5,088 / 1,021 figures use the archetype vocabulary ("legal and policy", "policy or research", "management") and so were most likely computed on the entry-axis archetype panel (INFERRED from the labels; no output emits them).

VERIFIED (lines read; queries run) except where marked.

Recommendation: decide the axis before the cube is built. If career entry is primary (the standing recommendation in the site concept), the portal fans must be re-run on cohorts/panel.career_age rather than membership.anchor; the launchboard grad-track (bachelor-anchored by construction, launchboard.py:75-93) stays as a labelled sensitivity view. Effort S to decide, M to re-base the portal.

### A5. Five cohort definitions, and the journey's population statement uses the widest tier without saying so

Severity: BLOCKING. Journey steps: AR4/SKEP, FIELD, CARD, every "in this sample" sentence.

The journey's "486,000 people who studied humanities" is `education_person.nha_level IN (1,2,3)` = 485,781 (VERIFIED). That tier (L3, "liberal arts", edu_clean/humanities.py:127-136) includes Psychology (99,094 persons in education.parquet at the pooled field group), Biological Sciences (70,566), Economics (34,431), Physical Sciences (29,266), Math & Statistics (27,434) and Natural Sciences (16,764). The other definitions in play:

| Definition | Where | Persons |
|---|---|---|
| terminal nha_level 1-3, deterministic | education_person.nha_level | 485,781 |
| terminal nha_level 1-3, pooled with CIP jury | education_person.nha_level_pooled | 590,772 |
| any-degree flags, pooled, L1-3 (archetypes cohort) | education_person.hum_l3_any; archetypes/common.py:31 | 776,769 flagged; 647,784 in the archetype panel |
| any row nha_level 1-3 (portal boundaries) | portal_data.json boundaries.l3 | 579,325 (l1 210,495; l2 358,675) |
| bachelor-level CIP2 bundle with a usable graduation anchor (portal majors) | portal membership | English 6,831 anchored, 4,612 windowed at year 10 |

The "407,000 observable across career years 1 to 15" is 485,781 restricted to valid_cohort = 407,872, which is not the same as "can be followed across their first fifteen years": of those, 336,735 have a full ten-year window (entry_year <= 2015), 330,707 have a panel row at year 10, 208,498 carry a SOC major at year 10, and 249,697 have a panel row at year 15 (VERIFIED, query in section 1 form: education_person join cohorts/profiles join cohorts/panel at career_age 10 and 15).

Consequence for the daggered and measured example figures: "5,088 people in legal and policy work at career year 10" has no exact match on the current build. Archetype 11 ("Legal, Policy & Research") at career_year 10, in_window, is 24,531 persons on the L1-3 cohort and 5,395 on L1 only; "1,021 from a policy or research role at year 1 to a management role at year 10" is 3,390 (L1-3) or 620 (L1). The cohort choice moves the headline claims by four to five times.

VERIFIED.

Recommendation: pick one canonical cohort for the site (the site concept lists this as open decision 1), state its tier on the population line, and emit that count from the pipeline into the release payload rather than from a document. If "humanities" on screen must mean L1 or L1+L2, every number in the journey docs is currently drawn from a set that is 2-4 times larger. Effort S to decide, S to emit.

### A6. "One in eight" is a property of one field and one denominator, not of the sample

Severity: SIGNIFICANT. Journey steps: ONELINE, PREDICT, REVEAL, CLASSAGG, Q1, BEST.

The copy asserts, for the field as a whole and "for any one field of study", that the largest destination is about one in eight. In portal_data.json (VERIFIED):

| Group | Top cell | Share of windowed cohort | Share of classified | Unclassified share |
|---|---|---|---|---|
| English | Education | 0.1271 | 0.2378 | 0.4657 |
| History | Management | 0.1302 | 0.2401 | 0.4576 |
| Phil & Rel | Community & Social Service | 0.1210 | 0.2394 | 0.4945 |
| Fine & Performing Arts | Arts/Design/Media | 0.2379 | 0.4360 | 0.4543 |
| Comm & Media | Management | 0.1531 | 0.2924 | 0.4765 |
| Baseline (all bachelors) | Management | 0.1452 | 0.2649 | — |

"One in eight" holds for English, History and Phil & Rel only because 45-49% of each windowed cohort has no classified occupation at year 10 and stays in the denominator (analyses.py:75 `share = n / d` with d = all windowed persons). Among people with a known occupation the top cell is one in four, and for Arts it is 44%. On the archetype axis (L1-3, in_window, year 10) the top archetype is Managers at 16.5% including Other and 18.5% excluding it; by field group, Fine & Performing Arts is 37.5% Creatives and Math & Statistics 31.5% Tech.

A second inconsistency inside the copy: REVEAL says "the largest single answer for this field was education" and CLASSAGG says "the largest single destination for English graduates was about one in eight, and it was not teaching". The English Education cell (n=586) is SOC major 25, whose named roles in the payload are Librarians 29, Secondary School Teachers 24, Teaching Assistants 18, Postsecondary English Teachers 14, Instructional Coordinators 11 (fan[0].detail.roles). It is teaching.

VERIFIED.

Recommendation: generate the ONELINE/REVEAL/BEST sentence from the claim object of the origin actually set, with the denominator named (share of everyone followed, or share of those with a known occupation), and remove the universal "for any one field" form. Effort S.

### A7. Question 2 (the corridor) and "Ways in" have no producer

Severity: SIGNIFICANT. Journey steps: Q2, P2, TAKE block 3, YES.

The corridor sentence "N people held X at career year 1 and Y at career year 10" is a joint count of positions at two horizons. Nothing emits it. transition_network/*_edges.parquet are adjacent job-to-job moves over all 2M profiles with no field-of-study dimension (build_network.py docstring: "conditional on a move occurring"); the role axis has 4,387,447 edges, which is the journey's "4.3 million title-to-title moves", but they are corpus-wide, not humanities, and not year-1-to-year-10. archetypes/results/state_flows.parquet is year t to t+1 (yearwise.py:85-113). Portal `paths` are origin-keyed SOC-major n-grams, at most eight per major (common.py:161), with no elapsed time; the role-grain `mine()` that carries median dwell (pathways.py:117-182) is not called (run_portal_data.py:47 calls mine_soc).

The shape is one query away from cohorts/panel.parquet plus archetypes/results/person_year_archetype.parquet. For destination archetype 11 at year 10 (24,531 persons) the year-1 role distribution is attorney 1,239, paralegal 490, research assistant 480, research 478, scientist 469, legal assistant 266 (display names via career_steps.role_display); median career year of first entry into the archetype is 2 (IQR 1-7). VERIFIED.

Recommendation: build a corridor table keyed (origin grain, origin, destination grain, destination, horizon) carrying n, the year-1 role list with counts >= 10, and median years-to-first-entry, for every origin the site offers. Effort M.

### A8. Question 3 (backward origins) has no producer, and the field label on the panels is the wrong degree

Severity: SIGNIFICANT. Journey steps: Q3, P3, LAD6, BACK.

No output tabulates destination -> field of study. The portal fan is origin -> destination for five majors and cannot be read backwards across the whole field. Prototyping it on the archetype panel exposes a second problem: humanities_field_group there is the pooled terminal field (archetypes/common.py:173-174 `ep.humanities_field_group_pooled`), so for Legal/Policy/Research at year 10 the largest "what they studied" cell is "Other" with 9,110 of 24,531 (37%), the JD or MBA having overwritten the bachelor's field. The next cells are Biological Sciences 3,930 and Physical Sciences 2,225, which are there because archetype 11 folds SOC 19 (scientists) in with SOC 23 (archetype_spec.py:96-97). VERIFIED.

Recommendation: carry the bachelor-level field group onto the person-year panel (education.parquet already has degree_level and cip2 per row) and emit a destination -> field table at the same suppression bar. Use SOC-major grain, not archetype, for any destination the journey calls "legal". Effort M.

### A9. At job-title grain the suppressed part holds most of the people, and the tail statistics are not produced

Severity: SIGNIFICANT. Journey steps: FIELDTAIL, TAILSTATE, RARE, STIPPLE, D3, P2.

The journey's example tail line ("shows 214 titles and suppresses 1,908, which hold 4,412 people") implies the suppressed region is a minority. On the data it is the majority even for a large destination: for the 24,531 people in archetype 11 at year 10, the year-1 role_canonical distribution has 221 cells >= 10 and 9,991 cells below, and the below-bar cells hold 12,854 of 23,990 people with a year-1 row (54%). VERIFIED.

The FIELDTAIL figures are not emitted by any module. The closest reproduction on the current build is the L2 tier (education.parquet nha_level IN (1,2)) x role_canonical on paths/steps.parquet: 622,196 titles across 357,934 people, 86.4% singletons, 26.9% of tenure-months in singletons, 13,709 titles at >= 10 (journey: 638,368 / 355,437 / 86.4% / 29.2% / 13,933). The same query on the June education.parquet.bak gives identical numbers, so the difference is not the education rebuild; the exact provenance of the journey's figures is unknown to me (INFERRED: an earlier spine build or a variant title column). The June 10 title_canonical_id variant gives 692,827 / 358,671 / 86.5% / 29.1% / 14,794, which matches the 29.2% but not the rest.

Also: role_canonical is a stemmed token key ("assistantresearch", "clerklaw", "psychologistschool"); the display name role_display is a 1:1 mapping (2,605,247 roles, 2,605,247 pairs) that lives on normalized/career_steps.parquet only, not on paths/steps.parquet or cohorts/panel.parquet (build_spine.py:110-129). VERIFIED.

Recommendation: emit a tail block per release and per cell (titles shown, suppressed, persons inside suppressed) from the pipeline, and carry role_display through the spine. Rewrite the TAILSTATE example with real proportions. Effort S.

### A10. Certifications: a domain rollup exists, named credentials with counts do not

Severity: SIGNIFICANT. Journey steps: P4, NCRED, ACT1, TAKE block 4, narrative step 9 and 13.

normalized/certifications_person.parquet is one row per person with n_certs, a 19-domain list and has_<domain> booleans (cert_clean/run_cert.py:6-10). Named credentials exist only in parsed/certifications/*.parquet (title, subtitle = issuer, meta with "Issued Mon YYYY" on 1,249,988 of 1,673,732 rows) and are not canonicalized: "Project Management Professional (PMP)" and "Project Management Professional (PMP)®" are separate rows (1,826 and 738 persons in the 486k cohort). Nothing joins credentials to a destination. The journey's "1.67 million certification records across 545,000 people" is the whole corpus (545,409 persons); within the 486k humanities cohort it is 360,957 records across 121,069 people (24.9%). 4,315 distinct raw titles clear ten persons in the cohort. VERIFIED.

Recommendation: a credential-name canonicalization (curated head like industry/curated_head.py) plus a destination x credential table with counts >= 10 and issuer. Provider enrolment dates are, by the journey's own rule, not from this sample. Effort M.

### A11. Geography: the parsed US state never reaches the spine, the panel, or the portal

Severity: SIGNIFICANT. Journey steps: P5, GEO, NGEO, LAD2, ACT3, rule 7.9.

build_normalized.py:953-959 writes location_country, location_us_state, location_city onto normalized/career_steps.parquet. paths/build_spine.py:129 carries only the raw `location` string; cohorts/panel.parquet and the portal panel (build.py:189-239) carry no location at all; nothing in portal/, cohorts/ or archetypes/ reads location_us_state (grep). Coverage in the 486k cohort: 53.7% of steps carry a US state, 78.9% of persons have at least one such step, and for the archetype-11 year-10 destination 57.9% (14,207 of 24,531) have a state on a step covering year 10. The journey's 51.6% is not reproduced exactly (INFERRED: a different cohort or an earlier build). Institution state (education_person.inst_state) is present for 74.1% of the cohort and is likewise unused. VERIFIED.

Recommendation: carry location_us_state and location_country through build_spine and both panels; emit per-cell state counts with the denominator stated (rule 7.9). Effort S-M.

### A12. Institution type is available but is not a dimension anywhere

Severity: SIGNIFICANT. Journey steps: LAD2 (rung 1 names "institution type"), CHOICE.

education_person.parquet carries inst_control_label (public 237,288; private_nonprofit 115,871; private_forprofit 6,564; null 126,058 in the 486k cohort), inst_carnegie_label and inst_iclevel_label (edu_clean/apply_institution_meta.py:31-59; reference/institution_meta.parquet, 6,163 rows). No downstream module reads them (grep across portal, archetypes, cohorts, paths, transition_network, enrichment: no hits). The ladder's first rung therefore has nothing to drop. VERIFIED.

Recommendation: add institution control (and optionally Carnegie class) as a filter dimension on the person-year substrate. Effort S.

### A13. Employers: a dispersion summary exists; employer-by-destination and employer-by-state do not

Severity: SIGNIFICANT. Journey steps: P5, JOBS, NEMP, ACT3, TAKE block 4.

portal `employer_field` is major x employer over years 0-5 (analyses.py:355), reporting size buckets and names only at n >= 10 (analyses.py:418). English has 18 named employers led by "Freelance" (201), then Starbucks 23, Teach For America 22; History 9; Phil & Rel 2. The "2,682 employers appear exactly once" line (ACT3) does not match any current bucket (English 8,641, History 4,292, Phil & Rel 2,837, Arts 17,159, Comm & Media 15,396, baseline 167,411). Employers conditioned on a destination, and employers by state, are not produced. VERIFIED.

Recommendation: employer x destination counts at the bar, with the "Various ..." and self-employment markers handled as analyses.py:414-421 already does; the state cut depends on A11. Effort M.

### A14. Graduate step: the share exists, the timing and the destination view do not

Severity: SIGNIFICANT. Journey steps: NGRAD, ACT2, TAKE block 4.

launchboard `grad_track` gives, per major, the share enrolling in a graduate or professional degree within five years of the bachelor anchor by level and type (launchboard.py:49-70, 75-152; English any 35.1%, Law 243, MFA 153). The journey wants "the career year they took it" (ACT2) and a destination view "people whose next step was this degree" (NGRAD alternate). Neither is emitted; the per-year timing is one query on education.start_year minus the anchor. VERIFIED.

Recommendation: emit the enrolment-year distribution and a grad-degree-as-destination cell. Effort S-M.

### A15. Horizon pooling and the year scrub have no per-year fan below archetype grain

Severity: SIGNIFICANT. Journey steps: LAD5, STATE (horizon), section 9 note on year 15.

Portal fans exist at years 1, 3, 5, 10 only. archetypes/results/occupancy.parquet has every career year 1-15 per entry cohort at archetype grain, but it is an aggregate (distinct persons per year), so "years 8 to 12 together" cannot be computed from it without double counting; person_year_archetype.parquet can, at person grain. VERIFIED.

Recommendation: compute pooled-horizon cells from the person-year table in the cube build. Effort S once the cube exists.

### A16. The claim contract fields are only partly present in the payload

Severity: MINOR. Journey steps: rule 7.1, CARD, every caption.

portal_data.json supplies n and min_support on every cell, snapshot_date and window_rule at the top; the horizon of the year-10 fan is implied by the key (common.py:123) and not carried on the cell; `population` and `not_observed` strings are absent. VERIFIED (run_portal_data.py:90-186).

Recommendation: emit each cell as a claim object with all five fields. Effort S.

### A17. The wage door needs a federal code; archetype-grain destinations do not have one

Severity: MINOR. Journey steps: WAGE.

At SOC-major grain every destination has a 2-digit code (transition_network/common.py:57-68), and 6-digit codes exist on 21.5% of steps. At archetype grain there is no single code: archetype 11 maps SOC 19 and 23 (archetype_spec.py:96-97), 12 maps 21, 29, 31. The journey's example hands over "23-0000" for a cell that, if drawn from the archetype table, contains 3,930 Biological Sciences and 2,225 Physical Sciences graduates working as scientists. VERIFIED.

Recommendation: make SOC-major grain the destination grain for anything that hands over a code. Effort S.

### A18. The daggered figures cannot all be replaced from existing outputs

Severity: MINOR. Journey steps: CLASSAGG, METER, PERSON, RARE, TAILSTATE, JOBS, RET.

Section 3 of the build doc instructs that every daggered figure be replaced by a queried one before build. Of the daggered lines: METER counts, PERSON/RARE counts and JOBS employer counts are cell-specific and follow from A1; TAILSTATE follows from A9; CLASSAGG and RET are interface state. None can be produced today except by ad-hoc query. VERIFIED by absence.

## 4. Capacity gaps

What the journey asks for that the data or pipeline cannot currently supply:

1. A cell-serving layer for arbitrary (origin, destination, horizon, grain, filters) with the support meter applied at query time (A1).
2. Origins beyond five majors: 22 field groups, 41 CIP2 families, CIP4 in the ladder (A2).
3. An eleven-way coarse grain of work and its crosswalk (A3).
4. One time axis, with the portal re-based on it if career entry wins (A4).
5. One cohort definition emitted by the pipeline, with the population statement generated from it (A5).
6. Corridor cells: position at year 1 by position at year 10 per origin, with years-to-entry (A7).
7. Backward origins: destination by bachelor-level field of study (A8).
8. Title-grain cells with display names, and per-cell tail statistics (A9).
9. Canonical credential names joined to destinations (A10).
10. US state carried through the spine and panels, with per-cell coverage denominators (A11).
11. Institution type as a filter dimension (A12).
12. Employer by destination and by state (A13).
13. Graduate-step timing and grad-as-destination (A14).
14. Pooled-horizon cells and per-year fans below archetype grain (A15).
15. Claim objects with population, horizon and not_observed strings (A16).
16. Below-bar cell counts (people inside the suppressed region) for STIPPLE and the ladder (LAD1, STIPPLE).
17. "What this work involved", composited from step descriptions: no compositing step exists (P1).

What the pipeline supplies that the journey does not use:

1. The seniority curve and fused seniority_score (portal `curve`, paths/seniority.py) and the up-move share and dwell KPIs (`kpi.up_share`, `dwell_median_mo`): the journey never shows seniority or promotion.
2. The launchboard stability block (mover classes, gap-adjacency, exploration breadth; launchboard.py:206-289).
3. The pillars block (portal/pillars.py).
4. The choices block (internship, military, service year, self-employment, double major; portal/choices.py) beyond the grad-school flag.
5. Industry L1 sectors at year 10 (`sectors`): the journey's NDEST names industry as a noun but no panel draws it.
6. Distinctiveness vs the all-bachelors baseline (`rr`, `kpi.distinctive`): the journey's "most distinctive against all graduates" sort could use it; nothing else does.
7. The transition-network analyses (backbone, communities, SpringRank): not referenced by any journey step.
8. Enrichment (volunteering, publications, honours, languages; enrichment/results/enrichment.json): not referenced.
9. Recession-scarring and survival analyses (cohorts/scarring.py, survival.py): not referenced.

## 5. What I could not verify, and why

1. The exact provenance of the FIELDTAIL figures (638,368 / 355,437 / 29.2% / 13,933), the 5,088 and 1,021 corridor figures, the 2,682 singleton-employer figure and the 51.6% state coverage. They are attributed by the journey to two documents I was instructed not to read. I reproduced each approximately (section 3) but no committed output emits them, so I cannot say which build or which cohort produced the published numbers.
2. Whether the "98.5% land in a group large enough to describe" claim was measured at SOC-major grain with the major as the only filter. On portal_data.json the share of classified persons in named cells is 92.8-99.8% across the five majors (English 98.66%), which is consistent with that reading; at title grain the proportion inverts (A9).
3. The "eleven first-person descriptions" and any eleven-way taxonomy: they may exist in a document outside the four I was allowed to read; they do not exist in code, config, or data.
4. The state-at-year-10 coverage (57.9%) is approximate: cohorts/panel.parquet does not carry row_id, so I matched steps by calendar-year coverage rather than by the primary step the panel chose.
5. I did not run any make target or build script, so I cannot confirm that the 17-stage refresh (scripts/refresh_downstream.sh) reproduces portal_data.json byte-for-byte on this machine; the manifest (portal/_manifest.json, generated 2026-09-02, substrate "built") and .build_status ("refresh done 17/17") say it last did.

## 6. Top 5

1. A1. Nothing serves cells on demand: the only website-consumable output is one static JSON for five majors at four fixed horizons, while the journey's whole architecture is "the named cell in this exact state" for any origin, destination, horizon, grain and filter; the schema file itself marks the DB and API as "to build".
2. A4 and A5 together. The journey's numbers are drawn from an L1-L3 cohort (485,781, which includes Psychology, Biology, Economics and Math) on the career-entry axis, while the portal computes L1 majors at bachelor level on the graduation axis; the same "legal and policy at year 10" claim is 24,531 or 5,395 depending on tier, and neither axis nor tier is decided.
3. A3. The "eleven kinds of work" that drive the second door and the third ladder rung do not exist in code, config or data; the pipeline offers 23 SOC majors, 15 archetypes and 17 industries.
4. A6. "One in eight" is true only for English, History and Phil & Rel and only because 45-49% of each cohort is unclassified at year 10 and left in the denominator; for Fine & Performing Arts it is one in four of the cohort and 44% of the classified, and the CLASSAGG line contradicts the REVEAL line on whether English's largest destination is teaching.
5. A7 and A8. The corridor (Q2) and backward origins (Q3) have no producer; the transition network is adjacent moves over all 2M profiles with no field dimension, and the archetype panel's field label is the terminal degree, so "what they studied" for legal work comes back "Other" 37% of the time.
