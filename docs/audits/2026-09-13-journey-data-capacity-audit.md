# Journey data-capacity audit: can the pipeline feed the user journey?

**Date:** 2026-09-13. **Branch:** `recovery-refactor` @ 7bd1733 (clean).
**Method:** three parallel read-only audits, each siloed from every project note except the four
2026-09-10 user-journey documents in `docs/design/` (no `FOUNDATION.md`, `PIPELINE.md`, module
`FINDINGS`/`PLAN`/`README`, `docs/` outside those four, or git history). Lens A traced the journey
to its data requirements; lens B inventoried the pipeline's outputs and the handoff mechanics;
lens C tested whether the data can honestly support the journey's claims at the granularity it
needs. Each ran its own DuckDB queries. Then a full round-robin peer review: every auditor
re-ran the evidence behind every finding in the other two reports (94 verdicts) and recorded
corrections to its own. Finally the coordinator re-verified the headline claims and every
round-two addition quoted below. Nothing was built, fired, or edited. Team reports and reviews,
with the queries that produced each number, are in `docs/audits/2026-09-13-teams/`.
**Focus, per the owner:** our capacity to feed data pipeline and analysis work into the user
journey, and what capacity is missing from the data or the pipeline.
**Silo caveat:** subagents may receive project memory through the harness; they were told to
disregard anything that arrived that way, and every claim below carries a query or file:line
that at least two independent runs reproduced.

---

## 1. The picture

The journey is a two-pole canvas: set an origin (a field of study, a kind of work, or a job
title), set a destination or leave it open, pick a horizon, apply like-me filters, and read a
named cell whose support meter shows how many people are inside it. The pipeline today serves
none of that. Its only website-consumable output is `portal/results/portal_data.json`, one
static 896 KB file for five majors at four fixed horizons, built for a different product (a
per-major dashboard), keyed on the graduation-year axis, gitignored, with no release id, no
title grain, no origin-to-destination cells, no credentials, no state, and two cells below ten
people emitted by design. The schema page that would describe the site's data still says the
bar is 40. `share/system-schema.mmd` marks the aggregate database and read API as "to build".

Behind that gap sit two undecided definitions that move every number in the journey by a
factor of four to six. The time axis: the portal anchors on graduation year, which only 18.6
percent of humanities bachelor's holders have; the cohort and archetype layers anchor on the
first recorded job, which 84.4 percent have; for the people on both, the anchors agree within
a year only 25.5 percent of the time, because for 47.4 percent the first recorded job began two
or more years before the degree. The cohort: the journey's "486,000 people who studied
humanities" is the terminal-field L1 to L3 tier, which includes 99,094 Psychology, 70,566
Biological Sciences, 34,431 Economics and 27,434 Mathematics majors; its title-tail figures come
from a second definition and its corridor figures from a third; and 38 percent of the
any-degree L1 population the entry-axis layers use never took a humanities bachelor's at all.
The journey already mixes both axes and all three cohorts in one document.

Two further things are wrong in the data rather than merely missing. The job-history section
of the snapshot was frozen around the end of October 2025 (job starts fall from 10,630 in
October to 334 in November), while the code closes every ongoing job at 2026-02-19 and treats
2025 as fully observed, so every current-holder count and tenure is about three and a half
months long. And the modal named Management job in every exported cell is "Chief Executives"
because 42,606 vice-president titles are coded 11-1011.

The good news is that most of what the journey asks for is one query away from tables that
already exist. Corridors, backward origins, ways-in panels, horizon pooling and a pooled
all-humanities field can all be computed from `cohorts/panel.parquet` and
`archetypes/results/person_year_archetype.parquet` in seconds; the reviewers ran those queries.
US state, institution control and display-ready titles exist upstream and just never reach
the spine. A person-level current state resolves for 90.8 percent of profiles with the
pipeline's own parser and nobody calls it. What does not exist anywhere, and cannot be queried
into existence, is the "eleven kinds of work" grain the journey's second door and third ladder
rung depend on, a canonical credential name, and a stage that composites job descriptions.

The order of work follows from that: two decisions (axis, cohort) and one policy line
(aggregate-only handoff), then a handful of small substrate fixes, then a precomputed cell
cube with its own disclosure rule and release stamp, and only then the copy.

---

## 2. Findings, consolidated

Forty-seven findings across three reports collapsed into thirteen themes. Severity is the
peer-review consensus. Each theme lists the finding ids it draws on; the ids are section
headings in the team reports.

### 2.1 No cell-serving layer and no data contract (A1, B1, B9, B-missed 4). BLOCKING.

`portal/run_portal_data.py:90-186` writes one JSON for the five majors in
`portal/common.py:165-171` at horizons 1, 3, 5 (`launchboard.py:34`) and 10 (`common.py:123`);
`run_share_build.py:19-33` injects it at the single token on `share_template.html:857`. No
server code exists (grep for flask, fastapi, http.server, express: nothing). The template is a
four-view per-major dashboard, not a two-pole canvas. The export carries `generated`,
`snapshot_date` and `min_support` but no release id, code version or input hash (grep for
release_id, schema_version, build_id across portal, scripts, paths, cohorts, archetypes:
nothing); it and the share HTML are gitignored, so no history of releases exists.
`share/system-schema.mmd:96,127` and `share/System-Schema.html:432,542` still state n >= 40
while `MIN_SUPPORT = 10` (`portal/common.py:131`). The STALE node ("does the linked cell still
clear ten in this build") cannot be served without a build id in the URL.

One constraint decides the shape of the fix. Every candidate substrate (`paths/steps`,
`cohorts/panel`, `person_year_archetype`, the portal cache) is person-grain, keyed on
`linkedin_id` (the public handle; `parsed/profiles` carries name and url) and carries
`title_raw`, `company_raw` and `description` free text. The site concept, section 8, forbids
any individual person on screen. A DuckDB read API over a person-year table on the partner's
server would put that data on infrastructure outside our terms. The contract has to be an
aggregate cube built here.

Recommendation (L): a new export package, not an extension of `portal_data.json`. Three
suppressed, versioned tables: destination cells keyed (population, origin grain, origin,
destination grain, destination, horizon, filters) with n and the shown/suppressed/people-inside
triple; per-destination panels (ways-in at year 1, fields of study, credentials, employers,
states); and a `numbers.json` with one row per headline figure carrying its population,
horizon, grain, bar, SQL and build id. Stamp every file with a release id (snapshot id from the
raw file names, build timestamp, git commit, the parameter block from `portal/_manifest.json`).
Fix or delete the two schema pages.

### 2.2 The time axis is undecided and the two axes disagree for the same people (A4, B2, C1). BLOCKING.

The portal computes year N as graduation anchor + N (`edu_clean/anchors.py:92-110`,
`portal/build.py:145-164`, `analyses.py:43`; A1 = observed bachelor end year, A2 = start + 3).
Cohorts and archetypes compute career_age = calendar year minus the year of the first datable
primary job (`cohorts/build_panel.py:96,150`; `archetypes/yearwise.py:39`).

| Measure | Graduation axis (portal) | Career-entry axis (cohorts, archetypes) |
|---|---|---|
| Humanities bachelor's holders placeable (of 375,028 bachelor-level pooled L1+L2) | 69,766 (18.6%) | 316,456 (84.4%) |
| Bachelor education rows with an end year | 301,480 of 1,555,454 (19.4%) | n/a |
| Persons windowed at year 10 | 42,813 | 258,436 (272,772 without requiring a panel row) |
| With a SOC major at year 10 | 22,372 | 159,440 |
| Five portal majors windowed at year 10 | 23,897 | no export exists |
| Any step at year 1 | 64.9% of windowed | 100% by construction |

For the 59,429 people placeable on both axes, entry year and graduation anchor agree within
one year for 25.5 percent; for 47.4 percent the first datable job precedes the graduation
anchor by two or more years (student and part-time work); for 27.1 percent it follows by two
or more. "Career year 10" on the entry axis is frequently year five to eight after the degree.
`archetypes/common.py:140-146` records the same fact in its own words (a different five-year
bin 60 percent of the time).

The journey draws from both frames without saying so. "One in eight", "23 occupation groups"
and "98.5 percent of people sit in a group large enough to describe" reproduce only in the
portal's graduation frame (98.5 percent is exactly field group × SOC major at year 10, 229
cells, 149 at ten or more). "407,000 observable across career years 1 to 15" is an entry-axis
filter (`valid_cohort`, entry year 1990 to 2020) applied to a terminal-field cohort. "5,088 in
legal and policy work" and "1,021 from policy or research to management" use archetype labels
that exist only on the entry-axis table. The site concept, section 9, lists the axis as open
decision 2 and says the exit step is blocked on it.

Recommendation (S to decide, M to rebase): decide before the cube is built and print the axis
name in every claim object. If career entry wins (coverage argues for it), the copy changes
from "ten years after the degree" to "ten years into working life", year 1 is described as the
first recorded job, the graduation anchor is carried as a labelled subset (it exists as
`grad_year` and `anchor_tier` on the archetype table), and the portal's window rule is re-based
on `cohorts/panel.career_age` with an equal-window cut per horizon. If graduation wins, the
population line must say that four in five humanities graduates in the sample cannot be placed.

### 2.3 The cohort is undecided, the journey mixes three, and the widest includes non-humanities majors (A5, B3, C6, C-missed 1). BLOCKING.

The journey's population figures reproduce exactly from one undocumented definition:

| Journey figure | Definition | Value |
|---|---|---|
| 486,000 "with a humanities degree" | `education_person.nha_level IN (1,2,3)`, terminal field, deterministic coder, L3 "liberal arts" tier | 485,781 |
| 407,000 "observable across years 1 to 15" | that set restricted to `cohorts/profiles.valid_cohort` | 407,872 |
| of those, with a ten-year window / panel row at year 10 / SOC major at year 10 / panel row at year 15 | | 336,735 / 330,707 / 208,498 / 249,697 |

The L3 tier contains Psychology (99,094 persons by pooled field group), Biological Sciences
(70,566), Economics (34,431), Physical Sciences (29,266), Mathematics and Statistics (27,434)
and Natural Sciences (16,764). The title-tail figures (638,368 titles, 355,437 people, 86.4
percent singletons, 29.2 percent of working life, 13,933 at ten) reproduce approximately from a
different definition, any-row deterministic L1+L2 on `education.parquet` crossed with
`paths/steps.role_canonical` (622,196 / 357,934 / 86.4 / 26.9 / 13,709 on the current build;
the residual is consistent with an earlier spine build; the June `education.parquet.bak` gives identical numbers, so the education rebuild is not the cause). The corridor figures reproduce from neither: archetype
11 at year 10 in window is 24,531 on L1 to L3 and 5,395 on L1; SOC 23 on the L1 valid cohort is
2,821; the 11-to-6 corridor is 3,390 (L1 to L3) or 620 (L1). The definitions in code range from
165,854 (terminal deterministic L1) to 776,769 (any-row pooled L1 to L3); the portal boundaries
are 210,495 / 358,675 / 579,325; the archetype cohort is 647,784; the bachelor-level pooled
L1+L2 population is 375,028 and L1 alone is 181,767.

The entry-axis layers define humanities on any-degree flags (`build_panel.py:82-91`,
`archetypes/common.py:164-183`). `hum_l1_any` is true for 293,808 persons and
`hum_l1_bachelor_pooled_any` for 181,767; the 112,041 in between (38.1 percent) hold their
humanities credential at another level: associate 46,847, master's 16,823, high school 10,955,
doctorate 3,410, unknown 24,158. For a site whose premise is "people with your degree", the
bachelor-level flag is the only defensible membership rule, and it shrinks every entry-axis
number accordingly.

Recommendation (S to decide, M to propagate): one canonical cohort, bachelor-level, with the
tier printed on the population line; emit its count from the pipeline into `numbers.json`
rather than from a document; regenerate every figure in journey section 3 from it. The site
concept lists this as open decision 1. Whatever tier is chosen, the current landing-page
number is 2.6 times the L1 bachelor population.

### 2.4 The "eleven kinds of work" do not exist (A3, B4, C9). BLOCKING for D2, DNONE and LAD4.

No code, config, mapping or output defines an eleven-way grouping (grep "eleven" over .py,
.html, .json: company names and a number-word array). The coarse grains that exist are 23 SOC
major groups (`transition_network/common.py:57-68`, 61 percent step coverage), 15 archetypes
plus Other (`archetypes/archetype_spec.py:24-57`, 10.7 percent Other at year 10) and 17
industry L1 sectors (`industry/taxonomy.json`, 58 percent resolved). The site concept, section
8, bans the archetype vocabulary on screen, yet the journey's corridor copy ("legal and policy
work", "management role") uses archetype labels (`archetype_spec.py:37,47`). The second door and
the third ladder rung have no data behind them.

Recommendation (M): write the eleven, commit a crosswalk from SOC major (and role keyword
rules for the uncoded 39 percent) with display labels and measured coverage, and add the grain
to the cube. The archetype module's `KEYWORD_RULES` is the pattern to reuse.

### 2.5 Job-title grain is mostly below the bar, and titles are not display-ready (A9, B5, C2). BLOCKING for D3, P2, RARE, TAILSTATE.

| View, year 10 | Cells | Cells at 10 or more | Share of people in a nameable cell |
|---|---|---|---|
| All humanities × title (graduation axis) | 16,831 | 337 | 36.1% |
| Field group × title | 21,709 | 286 | 21.3% |
| CIP4 major × title | 16,738 | 117 | 11.4% |
| Field group × (year-1 title to year-10 title) | 19,474 | 31 | 3.1% |
| Ways in to Management, year-1 titles | 2,063 | 31 | 19.9% |
| Ways in to Management, English filter | 1,334 | 5 | 5.4% |
| L1 valid cohort at career year 10 (entry axis) | 81,577 | 1,900 | 49% |
| Field group × SOC major (for comparison) | 229 | 149 | 98.5% |

Thirteen of 23 destinations have no nameable year-1 title at all. The "13,933 titles that
cleared the ten-person bar" is a corpus-wide count of titles held by ten people anywhere in a
whole career; it is not a cell in any state the reader will be in. `role_canonical` is a
stemmed key ("assistantresearch", "clerklaw"); the display name `role_display` is 1:1 with it
on `normalized/career_steps.parquet` (2,605,247 roles) and absent from `paths/steps.parquet`,
`cohorts/panel.parquet` and the network nodes (`build_spine.py:110-129`). The journey's own
TAILSTATE example (214 shown, 1,908 suppressed holding 4,412 people) implies the suppressed
region is a minority; on the data it holds the majority.

Recommendation (M): SOC major is the default grain wherever a pole is set; 6-digit and titles
are drill-downs inside a cell, with the coded-subset caveat the portal already emits. Carry
`role_display` through the spine. Precompute, per (origin, horizon) state, the set of titles
that clear ten, and let D3 search only that set. Rewrite TAILSTATE with real proportions.

### 2.6 The central sentence is a denominator artifact, and the copy contradicts itself (A6, B13 upgraded, C3, C4). SIGNIFICANT.

`analyses.py:73-78` computes share = n / d with d = every windowed person; 45 to 49 percent of
each windowed cohort has no SOC major at year 10 and stays in the denominator.

| Group | Top cell | Share of windowed | Share of classified | Unclassified |
|---|---|---|---|---|
| English | Education | 0.1271 | 0.2378 | 0.4657 |
| History | Management | 0.1302 | 0.2401 | 0.4576 |
| Philosophy & Religion | Community & Social Service | 0.1210 | 0.2394 | 0.4945 |
| Fine & Performing Arts | Arts/Design/Media | 0.2379 | 0.4360 | 0.4543 |
| Communication & Media | Management | 0.1531 | 0.2924 | 0.4765 |
| All bachelors (baseline) | Management | 0.1452 | 0.2649 | |
| Pooled humanities (C's substrate) | Management | 0.123 | 0.236 | 0.477 |

"One in eight" holds for three of five majors, only on the windowed denominator, and fails for
the largest L1 field even there. The unclassified half is two different things: at year 10,
8,938 of 42,813 windowed persons (20.9 percent) have no step active that year and 11,503 (26.9
percent) have a step with no occupation group. The pipeline's own rule forbids labelling the
first as unemployment (`portal/common.py:10`); the second is a coding gap whose most common
members are ordinary humanities destinations: project manager 78,395 steps, owner 68,878,
sales 53,928, administrative assistant 47,109, customer service representative 31,741. Of the
pooled SOC coverage, 65 percent comes from the LLM jury at 2-digit grain, so 6-digit views and
the WAGE hand-off describe one fifth of endpoints.

Separately, REVEAL says English's largest destination "was education" and CLASSAGG says "it
was not teaching"; the English Education cell's named roles are Librarians 29, Secondary School
Teachers 24, Teaching Assistants 18, Postsecondary English Teachers 14, Instructional
Coordinators 11. It is teaching.

Recommendation (S in data; a copy change): the claim object carries three counts (windowed,
classified, coded 6-digit) and the reveal is generated per field from the classified share.
Retire the universal sentence; the honest pooled version is "about one in four of those we
could classify, and we could classify about half". Add deterministic O*NET lexicon entries for
the top uncoded roles and re-measure; each is tens of thousands of steps.

### 2.7 Corridors and backward origins have no producer, and the panels carry the wrong degree (A7, A8, C11, C13). SIGNIFICANT.

Nothing emits (position at year 1) × (position at year 10). `transition_network/*_edges` are
adjacent job-to-job moves over all two million profiles with no field dimension (the role axis
has 4,387,447 edges, the journey's "4.3 million moves"); `state_flows.parquet` is year t to
t+1; portal `paths` are at most eight SOC-major chains per major (`common.py:161`), origin-keyed,
without elapsed time; the role-grain `mine()` that carries median dwell is never called
(`run_portal_data.py:47` calls `mine_soc`). The shape is one query away: for the Legal, Policy
and Research destination at year 10, the year-1 roles are attorney 1,239, paralegal 490,
research assistant 480, scientist 469, legal assistant 266, with a median first entry at career
year 2 (IQR 1 to 7). At SOC-major grain, field × (year-1 group to year-10 group) has 1,465
cells, 189 at ten or more, covering 71.2 percent of people (Arts 84.5, English 69.1, History
50.2, Philosophy & Religion 20.6, Area Studies 18.7).

The backward direction has two problems. First, both materialized panels carry
`humanities_field_group` as the terminal pooled field (`archetypes/common.py:173-174`,
`build_panel.py:82-91`), so a History BA who took a JD reads as "Other"; for Legal, Policy and
Research at year 10 the largest field cell is Other, 9,110 of 24,531 (37 percent), followed by
Biological Sciences 3,930 and Physical Sciences 2,225, which are there because archetype 11
folds SOC 19 (scientists) in with SOC 23 (`archetype_spec.py:96-97`). Second, the journey's Q3
copy names a humanities-only numerator with no denominator. Both frames are computable: among
current job holders, Legal has 16,873 people of whom 19.0 percent hold an L1 humanities degree
(43.2 percent L1+L2); in the portal's windowed frame among all anchored bachelors, Legal at
year 10 has 2,018 people of whom 55.6 percent hold an L1+L2 humanities bachelor's. P3 ("what
they studied") is meaningful only on the all-bachelors denominator, where it clears the bar
well (Management: 33 of 40 CIP2 cells, 99.9 percent of people).

Recommendation (M): a corridor table keyed (origin grain, origin, destination grain,
destination, horizon) with n, the year-1 list at the bar and median years to first entry;
carry the bachelor-level field group onto the person-year panel; the Q3 claim object carries
n_all, n_humanities and the frame; use SOC-major grain for anything the journey calls "legal".

### 2.8 The job-history section was frozen around October 2025, and the snapshot constants are copied into six modules (C5, B-missed 5, C-missed 4). SIGNIFICANT.

| Month | Job starts (`career_steps`) | Job ends | Certifications issued |
|---|---|---|---|
| Sep 2025 | 18,772 | 19,477 | |
| Oct 2025 | 10,630 | 12,203 | 8,096 |
| Nov 2025 | 334 | 347 | 5,976 |
| Dec 2025 | 19 | 40 | 5,931 |
| Jan 2026 | 41 | 24 | 5,105 |
| Feb 2026 | 13 | 5 | 1,160 |

Months in 2024 and early 2025 run 20,000 to 57,000 starts. The raw strings show the same cliff
(experience `start_date` "Oct 2025" 7,794 rows, "Nov 2025" 265). Posts and certifications
continue at normal volume into 2026, and among the 6,090 profiles demonstrably captured in 2026
(a January or February 2026 certification, or a 2026 post) job starts in November 2025 through
February 2026 are 14, 6, 11 and 1 against about 200 per month before. The experience section
observes 2025 through October. `paths/common.py:43` sets `SNAPSHOT_DATE = "2026-02-19"` and
`build_spine.py:81` closes every ongoing step (21.45 percent of steps) at that date, so every
current tenure is about three and a half months long; `LAST_COMPLETE_YEAR = 2025` treats 2025
as fully observed. The two constants are separately declared in `paths/common.py:43,55`,
`portal/common.py:47,54`, `cohorts/common.py:29`, `archetypes/common.py:37`,
`edu_clean/anchors.py:62` and `build_normalized.py:58`, and nothing derives them from the data.

Recommendation (S): derive a per-section observed-through month at parse time (the last month
with a normal volume of job starts) and write it to `parsed/_manifest.json`; add an
`EXPERIENCE_SNAPSHOT_DATE` distinct from the file date and close "Present" at it; consolidate
the constants into one module; print both dates on CARD and TAKE; add the check to the
consistency suite so it runs on every refresh.

### 2.9 The exit step's concrete leads are thin or unbuilt (A10, A11, A12, A13, A14, B6, B7, C7, C8, C10). SIGNIFICANT.

Credentials (P4, NCRED, ACT1). `normalized/certifications_person.parquet` is one row per person
with `n_certs` and 18 `has_<domain>` booleans (`cert_clean/run_cert.py:1-14`); no name, issuer
or date. `parsed/certifications` (1,673,732 rows) has title, issuer on 100 percent, and a
parsable "Issued Mon YYYY" on 1,249,976 rows (74.7 percent of all rows; 95.5 percent of rows
with a `meta`). Names are uncanonicalized ("Project Management Professional (PMP)" and the same
with a registered mark are separate rows). 22.4 percent of anchored humanities persons hold any
certification; 394 raw titles clear ten, led by notary public, CPR, BLS, PMP and Series 7. The
cert target is outside `make refresh` and `check_freshness.py`. Effort M: canonicalize
title + issuer to a credential id, keep the issue year, join to destination at the bar.

Geography (P5, GEO, NGEO, LAD2, ACT3). `location_us_state` is written on 51.56 percent of
`career_steps` rows (the source of the journey's "51.6 percent", a corpus-wide step rate),
present on 78.9 percent of persons in the 486k cohort on at least one step, and on 37.8 percent
of windowed persons at year 10. `paths/build_spine.py:129` carries only the raw `location`
string; the panel and the portal carry no location at all; nothing reads `location_us_state`
downstream. `education_person.inst_state` is present for 74.1 percent and likewise unused.
`parsed/profiles.city` is populated on every profile and the pipeline's own
`career_clean.location.parse_location` resolves 1,815,504 profiles (90.8 percent) to a US
state; no code applies it. Effort S: carry state through the spine and panels with the
denominator restated per rule 7.9; parse the profile city into a person-level "location on the
profile at capture" for the NGEO filter and ACT3.

Institution type (LAD2 rung 1). `education_person.inst_control_label` is present for the 486k
cohort as public 237,288, private nonprofit 115,871, for-profit 6,564, null 126,058, with
Carnegie class alongside; no downstream module reads any of it (grep). The ladder's first rung
has nothing to drop. Effort S.

Employers (P5, JOBS, NEMP, ACT3). At the year-10 destination, 17 of 19,214 (destination,
employer) cells clear ten, holding 1.4 percent of people (28 cells, 5.1 percent, if
non-organisation ids are kept); 134,979 of 154,597 employers of anchored humanities people
appear once. The portal's named employers for English at the loosened bar are Freelance 201,
Starbucks 23, Teach For America 22. The journey's "2,682 employers appear exactly once" matches
no bucket on this build. "Three named employers in this state" cannot be delivered. Effort S:
ship the dispersion statement the pipeline already computes and name employers only where a
cell clears at the chosen state; make the TAKE line conditional.

Graduate step (NGRAD, ACT2). `launchboard.grad_track` gives the share enrolling within five
years by level and type (English any 35.1 percent, Law 243, MFA 153) but no per-year timing and
no grad-as-destination view. Within the anchored humanities set, 93.7 percent of graduate rows
carry a start year (the `launchboard.py:42-44` comment is right for that set); corpus-wide it is
24.1 percent (177,114 of 736,264), so three quarters of graduate degrees are undated and fall
out of "the career year they took it". Effort S to M; carry an undated count beside the dated.

### 2.10 Vice Presidents are coded as Chief Executives (C12). SIGNIFICANT.

88,867 steps carry `occupation_code` 11-1011 with `role_canonical` "president"; their raw
titles are President 45,156, Vice President 26,016, Senior Vice President 7,236, Executive Vice
President 3,441, VP 1,629, Associate Vice President 687; 42,606 carry a "vice" seniority token.
Chief Executives is the top named Management role for every portal major and the baseline
(English 56, Arts 112, baseline 2,884). A student opening Management for English graduates
reads that the modal management job is Chief Executive. Effort S: route titles with a "vice"
token to a separate role in `career_clean`'s occupation mapping and re-run the drill-down.

### 2.11 Disclosure control is per cell only, and the export already breaks the ten-person promise (A-missed 1, B-missed 2, B-missed 3). SIGNIFICANT.

Every emitter suppresses its own cells independently (`analyses.py:73` fan, `:144` roles,
`:334-336` sectors, `:418` employers; `launchboard.py:128,136-140`) and reports the suppressed
remainder in aggregate. There is no complementary suppression, no minimum on the remainder and
no rounding (grep for complement, secondary suppression across portal, cohorts, archetypes:
nothing). The journey shows the wider cell beside the narrower one (LAD2, LAD3, rule 7.9),
offers small-domain filters (institution control has three values), and STIPPLE and TAILSTATE
print "the number of people inside the suppressed region". With a three-valued filter, "English
× Legal = 173" beside "English × Legal × public = 165" discloses private = 8 without rendering a
below-bar cell; with one suppressed title, the STIPPLE count is that title's count.

Separately, `launchboard.py:70` sets `GRAD_MEDICINE_FLOOR = 5` and lines 135 to 140 emit
Medicine (MD) at n >= 5 with `below_bar: true`; the current export carries Arts n = 9 and
Philosophy & Religion n = 7. The journey's rule is absolute ("it never describes fewer than ten
people", rule 7.8), so any reuse of the launchboard payload or its policy breaks the site's
central promise.

Recommendation (S in code once the cube exists; a design rule): secondary suppression at
cube-build time (suppress the complement when a filter has a small domain and exactly one
value is below the bar; emit STIPPLE counts only when at least two cells are suppressed), write
it into rule 7.8, and remove the medicine floor from anything the site reads.

### 2.12 Refresh and provenance are not trustworthy enough for a public site (B9, B10, B-missed 1). SIGNIFICANT.

A refresh after a new snapshot is four separate drivers: `make parse` (about 20 minutes),
`make normalize` (hours; reads the LLM-jury mapping parquets as inputs), `make cert`, and
`make refresh` (17 stages, about 10 minutes on 2026-09-02 per `refresh.log`); the jury runs
that feed normalize are fired by hand or by `scripts/overnight_followups.sh` (about 21 hours)
and are keyed on strings, so new strings in a new snapshot fall to deterministic coverage until
re-fired. `check_freshness.py` covers 14 stages by mtime only, without cert, enrichment or any
analysis JSON; it reports "ok" while `transition_network/{sequences,temporal}.json`,
`trajectory_features.parquet` (2026-06-04) and `cohorts/{typologies,generational}.json`,
`age_profiles.parquet` (2026-07-22) predate the 2026-09-02 spine. No test compares the share
HTML to the JSON it embeds, the JSON cells to the substrate, or headline numbers to their
queries. And `parse_linkedin.py:614` names each shard by the input file stem and never removes
existing shards, while every downstream reader globs the directory; a new snapshot file
`snap_<newid>.1.jsonl` would add shards beside the old ones and normalize would read four
million profiles.

Recommendation (M): one `make release` that runs the whole chain, clears or versions the
parsed root per snapshot id, writes a release manifest, and runs a cross-output consistency
suite (every cell n >= bar, sums per view equal the population, shown + suppressed = total,
HTML embeds the current JSON, headline numbers equal their queries, observed-through month
matches the snapshot constants).

### 2.13 Smaller findings. MINOR to SIGNIFICANT.

Observation decays with cohort age (C-missed 2). Among humanities bachelor's holders windowed
at year 10, a step is present in the year after graduation for 76.1 percent of 2010 to 2015
graduates, 54.5 percent of 2000s, 34.3 percent of 1990s and 22.2 percent of pre-1990; the
year-10 step itself is present for 90.0, 86.7, 72.5 and 55.0 percent. Profiles are
retrospective self-reports and older users omit early jobs. Every year-1 panel and corridor is
weighted toward recent graduates, and "typical elapsed years" is biased short for older
cohorts; the cohort composition of every cell should be stated.

Named majors are split by the field coder (A2, B14, C-missed 3). Classics, the journey's worked
example, is CIP 16.12 or 30.22 on 427 persons (364 in a valid cohort); at year 10 six SOC
groups clear ten and Legal has 6; none holds a grant role (grants roles at year 10 in the L1
valid cohort: grants manager 33, grant writer 29). The plain string "classics" (176 rows) has no
deterministic code and the jury assigns it CIP2 24 (Liberal Arts) while "classical studies"
goes to 16, so Classics is not one addressable origin. Any door that offers a major by name
needs a field-string crosswalk checked against both coders. Pick design examples from cells
that clear ten and keep Classics as the LAD1 test case.

P1 has no stage (B8). `career_steps.description` is non-empty on 50.8 percent of steps; nothing
composites descriptions per destination, and the O*NET label fallback exists only for the 20
percent of endpoints with a 6-digit code. Effort L: an LLM stage with a review gate, scoped
after the destination grain is chosen.

The wage door (A17, B11). Every SOC major has a 2-digit code; archetype grain has none
(archetype 11 folds SOC 19 and 23); 6-digit codes exist on 21.5 percent of steps.
`reference/` holds `soc_status` and `bls_unemployment` only, no OEWS series ids. Hand over
codes at SOC-major grain and add a small SOC-to-series reference table. Effort S.

Horizon pooling (A15) and the claim object (A16). Fans exist at years 1, 3, 5, 10 only;
`occupancy.parquet` is an aggregate so years 8 to 12 cannot be pooled from it, but
`person_year_archetype` can. Fan cells carry group, share, rr, n and detail; horizon lives in
the key name; population and not_observed strings are absent. Both are S once the cube exists.

Date-grain noise (C15) and the sample statement (C14). 13.84 percent of steps have year-only
starts widened to the calendar year, and A2 anchors (8.7 percent of anchored persons) are
within a year for 80.4 percent, so elapsed-years figures need a median, an n and a stated plus
or minus one year. Every profile is US and has both an education and an experience section
(vendor selection); 85.5 percent have a current job; 65.8 percent of bachelor end years are
2010 or later while year-10 windows need 2015 or earlier; 30.5 percent of L1 persons hold a
graduate degree. Population statement: "two million US LinkedIn profiles that list both
education and work history, captured [date]".

---

## 3. Capacity gaps

What the journey asks for, the nearest thing the pipeline has, and the gap.

| Journey need | Nearest existing capacity | Gap | Effort |
|---|---|---|---|
| A cell at any (origin, destination, horizon, grain, filters) with the support meter | `portal_data.json`, five majors, fixed cuts | no cube, no API, no release id (2.1) | L |
| Aggregate-only handoff | none; every substrate is person-grain with `linkedin_id` | policy line plus the cube (2.1) | S + L |
| One time axis | two, disagreeing for the same people | decision, then rebase (2.2) | S + M |
| One cohort, bachelor-level, with its count emitted | six definitions; journey uses three | decision, then `numbers.json` (2.3) | S + M |
| Pooled all-humanities field at year 10 (Q0) | per-major fans; `cohorts/panel` aggregable | not in any export | S once cohort fixed |
| Origins beyond five majors (D1) | 22 field groups, 41 CIP2, 362 CIP4 on `education.parquet`; portal MAJORS is config | five served; named majors split by coder (2.13) | M |
| Eleven kinds of work (D2, LAD4) | 23 SOC majors, 15+1 archetypes, 17 industries | taxonomy and crosswalk do not exist (2.4) | M |
| Title grain with display names (D3, P2, RARE) | `role_canonical` on the spine; `role_display` on `career_steps` only | mostly below the bar; not display-ready (2.5) | S + M |
| Corridors (Q2), ways in (P2), elapsed years | `cohorts/panel`, `person_year_archetype`, `transitions.dwell_months` | not materialized (2.7) | M |
| Backward origins (Q3, P3) | same tables; bachelor-level field on `education.parquet` | panels carry terminal field; no denominator rule (2.7) | M |
| Named credentials with counts (P4) | `parsed/certifications` title, issuer, issue month | no canonical id; nothing joined to destinations (2.9) | M |
| US state on cells, with denominator (P5, GEO, NGEO) | `career_steps.location_us_state`; `profiles.city` unparsed | not on spine or panel (2.9) | S |
| Institution type as a filter (LAD2) | `education_person.inst_*` | read by nothing (2.9) | S |
| Employers by destination and state (P5, ACT3) | portal `employer_field` per major | cells almost empty at ten (2.9) | S, conditional copy |
| Grad-step timing and grad-as-destination (NGRAD, ACT2) | `launchboard.grad_track` | no per-year timing; 24 percent dated corpus-wide (2.9) | S to M |
| Horizon pooling (LAD5) | `person_year_archetype` | not materialized | S with cube |
| Tail block per view (TAILSTATE, STIPPLE) and below-bar counts | `paths_suppressed_count` per major | not per view; disclosure rule missing (2.5, 2.11) | S with cube |
| Claim object: population, n, horizon, bar, not_observed, denominators | n and bar present | rest absent (2.6, 2.13) | S with cube |
| Deep-link staleness (STALE) | none | needs release id in URL (2.1) | S |
| "What this work involved" (P1) | `career_steps.description` on 50.8 percent | no compositing stage (2.13) | L |
| Wage door code (WAGE) | SOC major on 61 percent of steps | archetype grain has no code; no OEWS table (2.13) | S |
| A correct "as of" date | file date only | experience section frozen Oct 2025 (2.8) | S |
| Headline numbers pinned to a build (rule 7.1) | none | `numbers.json` (2.1, 2.3) | S to M |

Pipeline capacity the journey does not use: the seniority curve and fused score, the
launchboard stability and mover classes, pillars, choices (internship, military, service year,
self-employment, double major), industry L1 sectors at the endpoint (138 of 182 field × sector
cells clear ten, a coarser second grain for LAD4), the all-bachelors baseline with relative
risk and distinctiveness (which SORT "most distinctive against all graduates" could use),
transition-network communities and backbones, the archetype flows, cohort scarring and survival
analyses, enrichment (volunteering, publications, honours, languages). The journey's section 8
refusals exclude pillars, archetype labels and any ranking, so several of these are not merely
unused but unusable on the site.

---

## 4. Peer review record

Each auditor re-ran the evidence behind every finding in the other two reports.

| Reviewer | Report reviewed | Confirmed | Refined | Disputed | Cannot verify |
|---|---|---|---|---|---|
| A | B (14 findings) | 9 | 5 (B2, B3, B4, B12, B13) | 0 | 0 |
| A | C (15) | 11 | 4 (C2, C6, C7, C9) | 0 | 0 |
| B | A (18) | 16 | 2 (A2, A11) | 0 | 0 |
| B | C (15) | 12 | 3 (C2, C6, C10) | 0 | 0 |
| C | A (18) | 14 | 4 (A2, A6, A9, A14) | 0 | 0 |
| C | B (14) | 10 | 4 (B2, B3, B11, B13) | 0 | 0 |

Corrections the authors accepted, in order of weight:

1. B3 and C6 both said the journey's 486,000 and 407,000 match no definition. A found the
   definition (terminal deterministic L1 to L3, and its valid-cohort subset); both reviewers
   reproduced it and corrected their own reports. B's inferred source (406,010 all-field
   profiles with a graduation year) was wrong.
2. B2 summed the five majors' windowed year-10 persons as 22,297; the sum is 23,897.
3. B13 ("one in eight" is MINOR copy) was raised to SIGNIFICANT by both reviewers, since the
   sentence is ONELINE, PREDICT, REVEAL and BEST.
4. A3, B4 and C9 (eleven kinds) settled on BLOCKING for D2 and LAD4, since two nodes have no
   grain at all.
5. A11 said the journey's 51.6 percent state coverage was not reproducible; it is the
   corpus-wide step-row rate of `location_us_state`. B7 said the only state signal is at step
   level; the profile city field resolves for 90.8 percent of profiles.
6. C2 said 15 of 23 destinations have no nameable year-1 title; its own output shows 13.
7. C10 and B6 quoted the "Issued" date coverage as 95.5 percent; that is of rows with a
   non-null `meta`, and 74.7 percent of all rows.
8. B14 counted Classics on CIP 16.12 only (247 persons); with 30.22 it is 427. C11 called the
   Classics example "plausible in size"; the coder splits it across two CIP families.
9. C13 adopted A8's point that both materialized panels carry the terminal field.
10. B11 used the L1 population without the valid-cohort filter that B2 uses; one population
    should be used throughout.

Items raised in review that no original report contained, all verified by the coordinator:
no complementary suppression and the differencing risk (A and B independently); the
`GRAD_MEDICINE_FLOOR` cells below ten in the live export (B); the person-grain substrate
constraint on the handoff (B); new snapshot shards unioned in `parsed/` (B); snapshot
constants in six modules (B); 38.1 percent of any-degree L1 persons without a humanities
bachelor's (C); observation decay by cohort age (C); named majors split by the coder (C); the
observed-through date belongs in the release stamp (C); the unclassified half is two things (A);
the grad-timing comment resolved (A).

---

## 5. What remains unverified

1. The exact build and definition behind the journey's tail figures (638,368 / 355,437 / 29.2
   percent / 13,933), the corridor figures (5,088 / 1,021) and the singleton-employer figure
   (2,682). All three auditors reproduced the tail approximately and the rest not at all; the
   journey attributes them to documents outside the silo. `numbers.json` makes the question
   moot going forward.
2. The vendor's capture window per profile. No per-record timestamp exists; the October 2025
   cliff is robust across three independent runs but the exact date, and why posts and
   certifications extend later, are not knowable from the files.
3. Accuracy of the LLM-jury occupation labels on the humanities cohort. The jury keys roles the
   deterministic coder abstained on, so no in-data agreement check exists;
   `career_clean/results/soc_calibration.json` holds a held-out calibration nobody audited.
4. Whether the sample undersamples people who left the professional track; 85.5 percent are
   currently employed but there is no comparison population.
5. Byte-reproducibility of `portal_data.json` across days (it embeds `date.today()`); nobody
   rebuilt it.
6. Whether an eleven-way taxonomy exists in a document outside the four the auditors could
   read. It does not exist in code, config or data.

---

## 6. Recommended order of work

The dependencies are strict: nothing in the cube is worth building on an undecided axis and
cohort, and nothing in the copy is worth regenerating before the cube.

1. Decisions, this week (S). Time axis (2.2). Canonical cohort at bachelor level, with the tier
   (2.3). The aggregate-only handoff as a written policy line (2.1). These are the site
   concept's open decisions 1 and 2 plus the constraint that settles cube-versus-API.
2. Substrate fixes, each small and independent (S each). Derive the observed-through month at
   parse time and consolidate the snapshot constants (2.8). Carry `role_display`,
   `location_us_state`, `location_country` and `inst_control_label` through `build_spine` and
   `build_panel` (2.5, 2.9). Put the bachelor-level field group on the person-year panel
   (2.7). Parse `profiles.city` into a person-level current state (2.9). Route "vice" titles
   off 11-1011 (2.10). Add deterministic O*NET entries for the top uncoded roles (2.6). Clear
   or version the parsed root per snapshot id (2.12). Remove the medicine floor from anything
   the site reads (2.11).
3. The cube (L). One build keyed (population, origin grain, origin, destination grain,
   destination, horizon, filters) with SOC major as the default grain, titles and 6-digit as
   in-cell drill-downs, corridors and backward origins from the same table read both ways,
   per-destination panels, per-view tail blocks, secondary suppression, three-count claim
   objects, `numbers.json`, a release id on every file, and a `make release` with the
   consistency suite (2.1, 2.5, 2.7, 2.11, 2.12).
4. Content prerequisites that are not pipeline work (M to L). The eleven kinds and their
   crosswalk (2.4). Credential canonicalization (2.9). The P1 compositing stage (2.13). The
   SOC-to-OEWS reference table (2.13). Then regenerate every number in journey section 3 from
   `numbers.json` and rewrite ONELINE, REVEAL, BEST, CLASSAGG, TAILSTATE and the TAKE lines
   from the claim objects (2.6).
