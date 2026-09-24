# Audit C: data sufficiency for the undergraduate user journey

Auditor lens: can the underlying data honestly support the journey's claims at the granularity the journey needs. Repository: /home/alex/linkedin-analysis, branch recovery-refactor, working tree as of 2026-09-13. All counts below were produced by queries run during this audit; the queries are reproduced next to the tables they produced. Nothing in this report is taken from project notes or memory.

Conventions. "Humanities bachelor population" means one row per person holding a bachelor's-level education row (degree_level_pooled, else degree_level, = 4) whose pooled field coding is NHA tier 1 or 2 (nha_level_pooled IN (1,2)), which is the union of the portal's five major bundles plus the remaining L1/L2 CIP families. "Anchor" means the portal's graduation anchor: earliest usable end_year in [1950, 2025] not in_progress (A1), else start_year + 3 where end_year is null (A2), exactly as edu_clean/anchors.py:92-110. "Windowed at year N" means anchor <= 2025 - N (portal/common.py:54, analyses.py:15-16). "SOC major" is the 23-group pooled column steps.soc_major (deterministic 6-digit prefix else the LLM jury 2-digit label, build_normalized.py:937-945). "Title" is role_canonical. Every statistic is marked VERIFIED (query run or lines read) or INFERRED.

## 1. Method

Order of work:

1. Read in full the four permitted journey documents (docs/design/2026-09-10-user-journey.md, -narrative.md, -plain.md, 2026-09-10-site-concept.md) and listed every number and every data-dependent promise in them.
2. Read the pipeline code that defines the data: parse_linkedin.py (raw JSONL to star schema), build_normalized.py (education, education_person, career_steps), paths/common.py and paths/build_spine.py (steps, transitions, snapshot anchoring), edu_clean/anchors.py (graduation anchors), portal/common.py, portal/build.py, portal/analyses.py (the fan, thresholds, window rule), cohorts/common.py and cohorts/build_panel.py (career-entry axis), archetypes/common.py, archetypes/archetype_spec.py, archetypes/yearwise.py (the 15-archetype grain), cert_clean/run_cert.py, and the manifests under parsed/, normalized/, paths/, portal/, cohorts/, archetypes/results/.
3. Described the schemas of normalized/education.parquet, education_person.parquet, career_steps.parquet, paths/steps.parquet, paths/transitions.parquet, cohorts/profiles.parquet, cohorts/panel.parquet, normalized/certifications_person.parquet, reference/cip_humanities.parquet, industry/results/step_industry.parquet, and the cached portal substrate portal/results/_cache/{membership,panel}.parquet.
4. Established the snapshot from the data itself: profile counts, country mix, monthly counts of job starts and ends near the snapshot, post dates, certification issue months, one raw JSONL record's key list.
5. Built an audit substrate in the scratchpad (never in the repo): the humanities bachelor population with anchors per person, per field group, per CIP2 and per CIP4; a person-year panel for that population from paths/steps.parquet using the portal's primary-step rule (build.py:209-239); then the endpoint at years 1, 5 and 10. Scripts: scratchpad/audit/q_cells.py, q_cells2.py, q_q3.py, q_q3b.py, q_panels.py; outputs beside them as .out files.
6. Computed cell counts at three bars (10, 30, 100) for four grains (SOC major, SOC 6-digit, job title, industry L1) and four origins (all humanities, field group, CIP2, CIP4); corridor cells; the Band 4 panels (ways in, what they studied, credentials, employers, state); the backward direction with two denominators; the career-entry axis for the same population; sample skew.
7. Cross-checked against the portal's own committed output portal/results/portal_data.json and the archetype outputs so that every journey number could be traced to a definition or declared irreproducible.

Not run: any make target, build script, LLM call, or write into the repo.

## 2. Inventory

### 2.1 What a snapshot is

| Fact | Value | Status |
|---|---|---|
| Raw files | 8 JSONL files data/snap_mlsi9jwqziij1k8zq.{1..8}.jsonl, all mtime 2026-02-19, 25.8 GB | VERIFIED (ls) |
| Profiles | 2,000,000 rows; 1,999,952 distinct non-null linkedin_id; 1 null id | VERIFIED |
| Country | country_code = US for 2,000,000 of 2,000,000 | VERIFIED |
| Sections present | 1 profile lacks an education section, 1 lacks an experience section | VERIFIED |
| Per-profile capture timestamp | none; the raw record has 42 top-level keys and no scrape time | VERIFIED |
| Latest post date | 2026-02-05 | VERIFIED |
| Latest certification issue month | Feb 2026 (1,160 records), Jan 2026 (5,105) | VERIFIED |
| Latest job start month | Feb 2026 (13 steps), Jan 2026 (41), Dec 2025 (19), Nov 2025 (334), Oct 2025 (10,630), Sep 2025 (18,772) | VERIFIED |
| Constants | SNAPSHOT_DATE = "2026-02-19" (paths/common.py:43, portal/common.py:47); LAST_COMPLETE_YEAR = 2025 (paths/common.py:55, portal/common.py:54, edu_clean/anchors.py:62, cohorts/common.py:29, archetypes/common.py:18); EDU_LAST_COMPLETE_YEAR = 2025 (build_normalized.py:58) | VERIFIED |

Queries:

```
SELECT count(*), count(DISTINCT linkedin_id), count(DISTINCT source_file) FROM 'parsed/profiles/*.parquet'
SELECT country_code, count(*) FROM 'parsed/profiles/*.parquet' GROUP BY 1
SELECT start_date, count(*) FROM 'parsed/experience/*.parquet' WHERE start_date IN ('Sep 2025','Oct 2025','Nov 2025','Dec 2025','Jan 2026','Feb 2026') GROUP BY 1
-- result: Sep 14376 | Oct 7794 | Nov 265 | Dec 13 | Jan 33 | Feb 9 (experience); positions: 4397 | 2836 | 69 | 6 | 8 | 4
SELECT start_year, start_month, count(*) FROM 'normalized/career_steps.parquet' WHERE start_year IN (2024,2025) AND start_month IS NOT NULL GROUP BY 1,2 ORDER BY 1,2
-- 2025: Mar 27926 | Apr 25984 | May 26706 | Jun 27226 | Jul 23492 | Aug 22232 | Sep 18772 | Oct 10630 | Nov 334 | Dec 19
SELECT regexp_extract(meta,'Issued ([A-Z][a-z]{2} [0-9]{4})',1), count(*) FROM 'parsed/certifications/*.parquet' WHERE meta LIKE 'Issued%' AND meta LIKE '%2026%' GROUP BY 1
```

Late-capture test (profiles proven captured in 2026 because they carry a Jan/Feb 2026 certification or a 2026 post: 6,090 profiles):

```
CREATE TEMP TABLE late AS SELECT DISTINCT linkedin_id FROM 'parsed/certifications/*.parquet' WHERE meta LIKE 'Issued Jan 2026%' OR meta LIKE 'Issued Feb 2026%'
  UNION SELECT DISTINCT linkedin_id FROM 'parsed/posts/*.parquet' WHERE created_at LIKE '2026-%' OR created_at LIKE '% 2026 %';
SELECT s.start_year, s.start_month, count(*) FROM 'normalized/career_steps.parquet' s JOIN late USING (linkedin_id) WHERE s.start_year>=2025 AND s.start_month IS NOT NULL GROUP BY 1,2 ORDER BY 1,2
-- 2025: Jun 224 | Jul 216 | Aug 213 | Sep 189 | Oct 140 | Nov 14 | Dec 6 ; 2026: Jan 11 | Feb 1
```

### 2.2 What parsed/ and normalized/ contain

| Table | Rows | Grain | Key columns for the journey | Status |
|---|---|---|---|---|
| parsed/profiles | 2,000,000 | profile | city (100% populated, "City, State, United States" pattern for 75.8%), location (75.8%), connections, current_company | VERIFIED |
| parsed/education | 3,577,659 | (profile, idx) | title (school), degree, field, start_year, end_year | VERIFIED |
| parsed/experience + positions | 9,076,606 + 2,788,549 | job, nested role | company, title, location, start_date, end_date ("Mon YYYY", "YYYY", "Present") | VERIFIED |
| parsed/certifications | 1,673,732 | (profile, idx) | title, subtitle (issuer, 100%), meta ("Issued Mon YYYY" on 95.5%) | VERIFIED |
| normalized/education | 3,577,659 | education row | degree_level, degree_level_pooled, cip_code/cip2/cip4 (det), cip2_pooled, nha_level, nha_level_pooled, humanities_field_group(_pooled), start_year, end_year, in_progress, is_duplicate | VERIFIED |
| normalized/education_person | 1,999,974 | person | highest_degree_level(_pooled), bachelor_end_year, terminal cip/nha, hum_l1_any/hum_l2_any/hum_l3_any, hum_l1_bachelor_any, hum_l1_bachelor_pooled_any, school_slug, inst_* (IPEDS) | VERIFIED |
| normalized/career_steps | 10,800,787 | job step | company_canonical_id, employment_type, role_canonical, seniority_level, occupation_code (6-digit det), occupation_major_pooled, occupation_source, location_country/us_state/city, start_year/month, end_year/month, is_current, description | VERIFIED |
| paths/steps | 10,798,352 (1,999,961 profiles; profiles with >100 steps dropped, paths/common.py:61) | job step | start_dt, end_dt, datable, is_ongoing, tenure_months, seniority_ordinal, seniority_score, soc_major, soc_source, in_workforce | VERIFIED |
| paths/transitions | 6,180,324 | consecutive primary steps | from_/to_ role, occupation, soc_major, company, kind, transition_type | VERIFIED |
| industry/results/step_industry | 10,800,787 | job step | l1 (17 sectors incl. XOT unresolved) | VERIFIED |
| cohorts/profiles, cohorts/panel | 1,999,916 / 41,979,550 | person / person-calendar-year | entry_year = first datable primary step year (build_panel.py:96), career_age (build_panel.py:150), valid_cohort (entry 1990-2020) | VERIFIED |
| archetypes/results/person_year_archetype | 8,287,608 | person-career-year | archetype_id (0-15), career_year on the entry axis | VERIFIED |
| normalized/certifications_person | 545,409 | person | n_certs, n_certs_classified, 18 has_<domain> booleans, top_domain; no title, issuer or date | VERIFIED |

How a person, a degree, a job step and a transition are represented: a person is a linkedin_id; a degree is one education row with a canonical school slug, a degree-level ordinal (1 HS .. 4 bachelor .. 6 master 7 doctorate), a CIP code (mixed 2/4/6 digit) and an NHA tier from reference/cip_humanities.parquet (330 L1 codes in 9 field groups, 88 L2 codes in 5 groups, 328 L3 codes; joined at build_normalized.py:581-582); a job step is one experience or nested position row with a typed interval (build_spine.py:68-92), a primary/secondary flag from the concurrency self-join (build_spine.py:188-219) and the axes listed above; a transition is a pair of successive primary steps (build_spine.py:227-365).

How "humanities" is identified: by CIP code through reference/cip_humanities.parquet (nha_level 1 = core humanities, 2 = humanistic social science incl. communication, 3 = liberal arts). The deterministic crosswalk codes 58.8% of education rows; the pooled column adds an LLM jury at CIP2 grain to reach 82.5% (normalized/_cip_pooled_manifest.json). Person-level membership flags are ANY-degree (build_normalized.py:647-655).

### 2.3 Humanities cohort under every definition found in code

| Definition | Where | Persons | Status |
|---|---|---|---|
| Terminal field, deterministic, L1 (education_person.nha_level = 1) | build_normalized.py:665-672 | 165,854 | VERIFIED |
| Terminal field, pooled, L1 (nha_level_pooled = 1) | build_normalized.py:673-685 | 210,315 | VERIFIED |
| Any education row L1, deterministic (portal "boundaries" l1) | portal/build.py:242-252 | 210,495 | VERIFIED |
| Any row L1, pooled (hum_l1_any) | build_normalized.py:647 | 293,808 | VERIFIED |
| Any row L1 at bachelor level, pooled (hum_l1_bachelor_pooled_any) | build_normalized.py:653-655 | 181,767 | VERIFIED |
| Any row L1+L2, deterministic (portal l2) | build.py:247 | 358,675 | VERIFIED |
| Any row L1+L2, pooled (hum_l2_any) | build_normalized.py:648 | 510,306 | VERIFIED |
| Any row L1+L2+L3, pooled (hum_l3_any) | build_normalized.py:649 | 776,769 | VERIFIED |
| Archetype cohort: L1-L3 any-row pooled AND valid entry cohort 1990-2020 | archetypes/common.py:31, 135-185 | 647,784 (L1 246,292; L2 182,466; L3 219,026) | VERIFIED (person_year_archetype) |
| Portal majors: five CIP2 bundles at bachelor level with A1/A2 anchor | portal/common.py:165-171, build.py:145-164 | english 6,831; history 3,584; philrel 2,287; arts 13,598; commmedia 12,647 anchored | VERIFIED (portal/_manifest.json, membership cache) |
| This audit's "humanities bachelor population" (bachelor level, pooled L1+L2) | scratchpad/audit/q_cells.py | 375,028 (L1 181,767; L2 195,637) | VERIFIED |

Query for the person-level flags:

```
SELECT count(*), count(*) FILTER (WHERE hum_l1_any), count(*) FILTER (WHERE hum_l2_any), count(*) FILTER (WHERE hum_l3_any),
       count(*) FILTER (WHERE hum_l1_bachelor_pooled_any), count(*) FILTER (WHERE nha_level=1), count(*) FILTER (WHERE nha_level_pooled=1)
FROM 'normalized/education_person.parquet'
-- 1999974 | 293808 | 510306 | 776769 | 181767 | 165854 | 210315
```

The journey's 486,000 "with a humanities degree" matches none of these. The journey's title-tail figures (638,368 titles, 355,437 people, 86.4% singletons, 29.2% of working life, 13,933 titles at ten) are closest to the deterministic any-row L1+L2 cohort at role_canonical grain on the current build: 622,196 titles, 358,666 people with steps, 86.4% singletons, 26.9% of tenure months, 13,709 titles at ten. The remaining difference is consistent with a build between July and September (career_steps.parquet was rebuilt 2026-09-02) but I could not confirm which.

```
WITH pop AS (SELECT DISTINCT linkedin_id FROM 'normalized/education.parquet' WHERE nha_level IN (1,2)),
 t AS (SELECT s.role_canonical k, count(DISTINCT s.linkedin_id) n, sum(s.tenure_months) mo FROM 'paths/steps.parquet' s JOIN pop USING (linkedin_id) WHERE s.role_canonical IS NOT NULL GROUP BY 1)
SELECT (SELECT count(DISTINCT s.linkedin_id) FROM 'paths/steps.parquet' s JOIN pop USING (linkedin_id)), count(*), round(100.0*count(*) FILTER (WHERE n=1)/count(*),1),
       round(100.0*sum(mo) FILTER (WHERE n=1)/sum(mo),1), count(*) FILTER (WHERE n>=10) FROM t
-- 358666 | 622196 | 86.4 | 26.9 | 13709
```

The same statistic on the other cohorts (persons with steps / distinct titles / pct singleton / pct months in singletons / titles >= 10): all profiles 1,999,961 / 2,604,792 / 86.3 / 22.1 / 54,760; hum_l1_any 293,799 / 530,028 / 86.7 / 27.9 / 11,396; hum_l2_any 510,295 / 902,948 / 86.8 / 26.6 / 18,677; hum_l1_bachelor_any 181,043 / 360,076 / 86.9 / 29.5 / 7,549.

### 2.4 Humanities bachelor population, anchors, and window sizes (graduation axis)

Table T1. Persons with a humanities (L1+L2) bachelor's, by field group (pooled coverage), the share with a usable graduation anchor, and how many remain inside the equal-observation window at years 1, 5, 10.

| Field group | Tier | Persons | Anchored (A1+A2) | Pct anchored | Windowed y1 (anchor<=2024) | y5 (<=2020) | y10 (<=2015) |
|---|---|---|---|---|---|---|---|
| All L1+L2 (person grain) | | 375,028 | 69,766 (A1 63,728, A2 6,038) | 18.6 | 67,825 | 56,612 | 42,813 |
| All L1 only | | 181,767 | 37,119 | 20.4 | 36,160 | 30,584 | 23,348 |
| Communication & Media | 2 | 100,550 | 14,756 | 14.7 | 14,293 | 11,809 | 8,810 |
| Humanistic Social Science | 2 | 95,182 | 18,514 | 19.5 | 17,968 | 14,676 | 10,957 |
| Fine & Performing Arts | 1 | 72,999 | 15,520 | 21.3 | 15,024 | 12,419 | 9,215 |
| English & Literature | 1 | 46,327 | 8,031 | 17.3 | 7,874 | 6,914 | 5,450 |
| History | 1 | 20,357 | 4,194 | 20.6 | 4,109 | 3,560 | 2,897 |
| Liberal Arts & Humanities | 1 | 15,534 | 3,075 | 19.8 | 2,987 | 2,441 | 1,812 |
| Languages & Linguistics | 1 | 11,551 | 2,544 | 22.0 | 2,489 | 2,124 | 1,610 |
| Philosophy & Religion | 1 | 7,026 | 1,676 | 23.9 | 1,632 | 1,372 | 1,048 |
| Area & Cultural Studies | 1 | 6,214 | 1,350 | 21.7 | 1,320 | 1,101 | 808 |
| Theology | 1 | 3,001 | 1,015 | 33.8 | 997 | 857 | 646 |
| Library & Information Science | 2 | 165 | 46 | 27.9 | 45 | 40 | 29 |
| Science, Technology & Society | 2 | 79 | 17 | 21.5 | 17 | 12 | 6 |
| Museum Studies | 2 | 25 | 11 | 44.0 | 10 | 5 | 3 |

VERIFIED. Query (q_cells.py, hb table definition then):

```
CREATE TEMP TABLE hb AS SELECT linkedin_id, idx, coalesce(degree_level_pooled, degree_level) dl, nha_level_pooled nha, humanities_field_group_pooled fg, cip2_pooled cip2, start_year, end_year, in_progress,
  CASE WHEN end_year BETWEEN 1950 AND 2025 AND NOT coalesce(in_progress,FALSE) THEN end_year END a1,
  CASE WHEN end_year IS NULL AND NOT coalesce(in_progress,FALSE) AND start_year BETWEEN 1900 AND 2025 AND start_year+3<=2025 THEN start_year+3 END a2
FROM 'normalized/education.parquet' WHERE NOT is_duplicate AND coalesce(degree_level_pooled, degree_level)=4 AND nha_level_pooled IN (1,2);
SELECT fg, min(nha), count(*), count(anchor), count(*) FILTER (WHERE anchor<=2024), count(*) FILTER (WHERE anchor<=2020), count(*) FILTER (WHERE anchor<=2015)
FROM (SELECT linkedin_id, fg, min(nha) nha, coalesce(min(a1),min(a2)) anchor FROM hb GROUP BY 1,2) GROUP BY 1 ORDER BY 3 DESC
```

Specific majors (CIP2 and CIP4): 13 CIP2 families carry L1/L2 bachelor's; the largest are 09 (100,550), 45 (92,979), 50 (72,999), 23 (46,327), 54 (20,324), 24 (15,534), 16 (11,441), 38 (7,026), 05 (6,101), 39 (3,001), 30 (2,614), 25 (165), 42 (9). At CIP4 grain (deterministic codes only) there are 74 specific majors; 46 have >= 10 persons windowed at year 10, 39 have >= 30, 30 have >= 100, 8 have >= 1,000 (09.01 3,780; 45.10 3,188; 23.01 3,231; 50.04 2,265; 54.01 2,255; 45.11 1,958; 50.07 1,388; 24.01 1,232). VERIFIED.

### 2.5 Endpoint coverage at years 1, 5, 10 (graduation axis)

Table T4. For windowed humanities bachelor persons, what is known about them at anchor + N.

| Year N | Windowed persons | Any step active that year | Has SOC major (pooled) | Has SOC 6-digit (det) | Has industry L1 (not XOT) | Has US state |
|---|---|---|---|---|---|---|
| 1 | 67,825 | 44,046 (64.9%) | 29,563 (43.6%) | 11,608 (17.1%) | 23,783 (35.1%) | 23,253 (34.3%) |
| 5 | 56,612 | 42,521 (75.1%) | 28,801 (50.9%) | 11,269 (19.9%) | 23,655 (41.8%) | 21,123 (37.3%) |
| 10 | 42,813 | 33,875 (79.1%) | 22,372 (52.3%) | 8,636 (20.2%) | 18,979 (44.3%) | 16,171 (37.8%) |

VERIFIED (q_cells2.py, T4 all_hum). Panel construction mirrors portal/build.py:188-239 (datable, not bad, primary = max seniority_score then tenure per calendar year), with industry L1 and the location gazetteer joined.

### 2.6 Occupation distribution at years 1, 5, 10 under both denominators

Table T48. All-humanities (L1+L2 bachelor, anchored), top 8 SOC major groups.

| Year | Group | n | Pct of classified | Pct of windowed |
|---|---|---|---|---|
| 1 | Arts/Design/Media | 6,668 | 22.6 | 9.8 |
| 1 | Management | 4,483 | 15.2 | 6.6 |
| 1 | Education | 3,765 | 12.7 | 5.6 |
| 1 | Office & Admin Support | 2,960 | 10.0 | 4.4 |
| 1 | Business & Financial | 2,416 | 8.2 | 3.6 |
| 5 | Arts/Design/Media | 5,854 | 20.3 | 10.3 |
| 5 | Management | 5,436 | 18.9 | 9.6 |
| 5 | Education | 3,711 | 12.9 | 6.6 |
| 10 | Management | 5,269 | 23.6 | 12.3 |
| 10 | Arts/Design/Media | 4,058 | 18.1 | 9.5 |
| 10 | Education | 2,882 | 12.9 | 6.7 |
| 10 | Business & Financial | 1,930 | 8.6 | 4.5 |
| 10 | Legal | 1,344 | 6.0 | 3.1 |
| 10 | Office & Admin Support | 1,260 | 5.6 | 2.9 |

Denominators: year 1 windowed 67,825 / classified 29,563 (56.4% unclassified); year 5 56,612 / 28,801 (49.1%); year 10 42,813 / 22,372 (47.7%). VERIFIED.

Per field group at year 10 (T6): pct classified 48.9-54.2%; largest cell as share of classified: Fine & Performing Arts 43.0% (2,147 in Arts/Design/Media), Theology 35.4%, Communication & Media 29.5%, Humanistic Social Science 26.8%, Liberal Arts 23.9%, English 23.7% (683 in Management), History 23.6%, Area Studies 23.5%, Languages 22.8%, Philosophy & Religion 16.1%; as share of windowed: Arts 23.3%, Theology 18.9%, Comm & Media 15.4%, HSS 13.6%, History 12.7%, English 12.5%, Area 12.0%, Languages 12.1%, Liberal Arts 11.7%, PhilRel 7.9%. VERIFIED. The portal's committed output agrees: majors.arts.diversity.top_bucket_share = 0.2379, english 0.1271, history 0.1302, commmedia 0.1531, philrel 0.121 (portal/results/portal_data.json).

### 2.7 Cells surviving the bar, by grain and origin (graduation axis)

Table T5. Number of (origin, destination) cells and the share of classified persons who sit in a cell of at least 10 / 30 / 100. Pipeline bar: MIN_SUPPORT = 10 (portal/common.py:131), DETAIL_MIN_SUPPORT = 10 (:143), BREADTH_MIN_PERSONS = 5 (:132), PATH_SUPPRESS_FLOOR = 2 (:149); archetypes soc_min_support 10 and support_floor_embed 5 (archetypes/results/_assign_manifest.json).

| Origin x grain | Year | Cells | Persons | Cells >= 10 | Pct persons in >= 10 | Cells >= 30 | Pct in >= 30 | Cells >= 100 | Pct in >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| all-hum x SOC major | 10 | 23 | 22,372 | 23 | 100.0 | 21 | 99.8 | 18 | 98.7 |
| all-hum x SOC 6-digit | 10 | 481 | 8,636 | 151 | 88.0 | 57 | 69.6 | 16 | 45.3 |
| all-hum x title | 10 | 16,831 | 33,875 | 337 | 36.1 | 102 | 25.3 | 23 | 13.3 |
| all-hum x industry L1 | 10 | 17 | 34,428 | 17 | 100.0 | 17 | 100.0 | 15 | 99.7 |
| field group x SOC major | 1 | 249 | 30,024 | 175 | 99.1 | 122 | 96.0 | 62 | 85.2 |
| field group x SOC major | 5 | 244 | 29,192 | 165 | 98.9 | 117 | 96.0 | 59 | 84.8 |
| field group x SOC major | 10 | 229 | 22,628 | 149 | 98.5 | 104 | 94.8 | 45 | 80.1 |
| field group x SOC 6-digit | 10 | 1,712 | 8,731 | 171 | 60.5 | 43 | 37.7 | 11 | 20.2 |
| field group x title | 1 | 26,082 | 44,763 | 418 | 24.6 | 103 | 13.7 | 11 | 4.1 |
| field group x title | 10 | 21,709 | 34,288 | 286 | 21.3 | 60 | 11.0 | 7 | 3.3 |
| field group x industry L1 | 10 | 182 | 34,847 | 138 | 99.5 | 104 | 97.8 | 64 | 91.4 |
| CIP2 x SOC major | 10 | 242 | 22,633 | 153 | 98.3 | 104 | 94.2 | 45 | 79.6 |
| CIP2 x title | 10 | 21,790 | 34,296 | 284 | 21.1 | 60 | 11.0 | 7 | 3.2 |
| CIP4 x SOC major | 10 | 723 | 15,251 | 236 | 90.1 | 111 | 76.3 | 36 | 52.0 |
| CIP4 x SOC 6-digit | 10 | 2,267 | 5,984 | 89 | 37.4 | 15 | 18.0 | 2 | 6.2 |
| CIP4 x title | 10 | 16,738 | 22,716 | 117 | 11.4 | 20 | 4.7 | 2 | 1.1 |
| CIP4 x industry L1 | 10 | 634 | 23,066 | 267 | 95.3 | 139 | 85.4 | 48 | 64.6 |

VERIFIED (q_cells2.py, function cells()). The journey's "roughly 98.5% of people sit in a group large enough to describe" reproduces exactly as field group x SOC major at year 10 (98.5%), and only at that grain.

```
WITH c AS (SELECT origin, yr, role_canonical g, count(*) n FROM ep_field_group WHERE role_canonical IS NOT NULL GROUP BY 1,2,3)
SELECT yr, count(*), sum(n), count(*) FILTER (WHERE n>=10), round(100.0*sum(n) FILTER (WHERE n>=10)/sum(n),1), ... FROM c GROUP BY 1
```

English (CIP2 23) at year 10 alone: SOC major 23 cells, 16 >= 10 covering 2,847 of 2,883; SOC 6-digit 208 cells, 23 >= 10 covering 637 of 1,079; title 2,678 cells, 32 >= 10 covering 797 of 4,200 (largest title cell 88). VERIFIED.

### 2.8 Routes (corridors) with enough people

| Corridor definition | Cells | Persons | Cells >= 10 | Pct persons in >= 10 | Largest |
|---|---|---|---|---|---|
| all-hum: year-1 SOC major -> year-10 SOC major | 372 | 10,084 | 126 | 92.4 | 1,723 |
| field group x (y1 SOC major -> y10 SOC major) | 1,465 | 10,217 | 189 | 71.2 | |
| English x (y1 SOC major -> y10 SOC major) | 164 | 1,224 | 24 | 69.1 | 209 |
| field group x (y1 title -> y10 title) | 19,474 | 20,980 | 31 | 3.1 | 71 |
| per field group, SOC-major corridors, pct persons in >= 10 | Arts 84.5, HSS 74.1, Comm 81.6, English 69.2, History 50.2, Liberal Arts 46.2, Languages 37.1, PhilRel 20.6, Theology 46.6, Area 18.7, LIS/STS/Museum none | | | | |

VERIFIED (q_cells2.py T9, T9b, T9c, T9d; q_panels.py T36). Portal named routes (portal/pathways.py, soc_major_pooled grain, 2-4 stages): 8 emitted per major with 102-270 suppressed per major (portal_data.json majors.*.paths_suppressed_count). VERIFIED.

### 2.9 Band 4 panels for a destination (all-humanities, year 10 destination = SOC major)

| Panel | Measure | Result | Status |
|---|---|---|---|
| P2 Ways in (title grain) | Management destination: year-1 titles | 2,063 titles, 31 >= 10, covering 639 of 3,215 (19.9%), largest 73 | VERIFIED |
| P2 Ways in (title grain) | destinations with zero nameable year-1 title | 15 of 23 | VERIFIED |
| P2 Ways in (title grain), English filter | | 1,334 titles, 5 >= 10, 5.4% of 1,647 | VERIFIED |
| P2 Ways in (SOC-major grain) | Management destination | 22 cells, 19 >= 10, 99.3% named; below 70% named for 11 of the smaller destinations | VERIFIED |
| P3 What they studied (CIP2, all anchored bachelors) | Management | 40 cells, 33 >= 10, 99.9% of persons in named cells; Legal 31 cells, 24 >= 10, 99.0% | VERIFIED |
| P4 Credentials | anchored humanities persons with any certification | 15,654 of 69,766 (22.4%) | VERIFIED |
| P4 Credentials | raw title cells | 26,318 titles, 394 >= 10, 21.2% of 43,666 person-certs, 6 titles >= 100 | VERIFIED |
| P4 Credentials | top titles | notary public 228, cpr/aed/first aid 180, BLS 140, PMP 137, Series 7 110, mental health first aid 100 | VERIFIED |
| P5 Employers at year 10 by destination | | 19,214 cells, 17 >= 10 (1.4% of 21,426 persons), 18,066 singleton cells | VERIFIED |
| P5 Employers over all years | employers of anchored humanities persons | 154,597 employers; 134,979 appear once; 1,769 have >= 10 (47,176 person-employer pairs) | VERIFIED |
| P5 State at year 10 by destination | | 10,433 of 22,372 with a state (46.6%); 817 dest x state cells, 251 >= 10 | VERIFIED |
| Field x destination x state | | 2,945 cells, 205 >= 10, 43.0% of 10,578 persons | VERIFIED |
| ACT2 Graduate step | anchored humanities persons with a dated later graduate degree | 21,648 of 69,766 (31.0%); 20,347 within 15 years; level x CIP2 cells 100, 62 >= 10 covering 99.5% | VERIFIED |

### 2.10 Spine coverage (all profiles)

| Axis | Coverage of 10,798,352 steps | Source line | Status |
|---|---|---|---|
| Datable (start and end parse) | 99.25% | build_spine.py:164 | VERIFIED |
| Start at month grain / year grain | 86.16% / 13.84% | build_spine.py:74-77 | VERIFIED |
| Ongoing ("Present", closed at SNAPSHOT_DATE) | 21.45% | build_spine.py:79-81 | VERIFIED |
| Missing start / missing end string | 0.74% / 0.74% | | VERIFIED |
| role_canonical | 98.49% | | VERIFIED |
| SOC 6-digit (deterministic) | 21.46% | build_normalized.py:930 | VERIFIED |
| SOC major pooled (det 35.0% of pooled, jury 65.0%) | 61.27% | build_normalized.py:937-945 | VERIFIED |
| Lexical seniority ordinal / fused seniority score | 46.06% / 95.23% | build_spine.py:102-155 | VERIFIED |
| Industry L1 resolved (not XOT) | 58.35% | industry/results/step_industry.parquet | VERIFIED |
| Raw location string / parsed country / US state / city | 63.81% / 56.88% / 51.56% / 51.86% | build_normalized.py:955-958 | VERIFIED |
| Company id / canonical company | 73.74% / 99.98% | | VERIFIED |
| Description text | 50.83% | | VERIFIED |
| Employment type employee / business_owner / self_employed / student / retired | 94.56 / 2.47 / 1.84 / 0.49 / 0.32% | | VERIFIED |
| Most common roles with no occupation code at all | managerproject 78,395; owner 68,878; sales 53,928; administrativeassistant 47,109; customerrepresentativeservice 31,741; assistantmanager 26,238; marketing 25,822; founder 25,199 | | VERIFIED |

### 2.11 Backward direction (Q3: who is already there)

Table T13. Current job holders (primary ongoing step, 1,709,814 persons; 1,054,718 with a SOC major), by SOC major, with the humanities share on two definitions.

| SOC major | n all | n hum L1 | pct L1 | n hum L1+L2 | pct L1+L2 |
|---|---|---|---|---|---|
| 11 Management | 334,369 | 38,193 | 11.4 | 78,086 | 23.4 |
| 13 Business & Financial | 135,864 | 14,811 | 10.9 | 31,094 | 22.9 |
| 15 Computer & Math | 94,942 | 6,611 | 7.0 | 11,089 | 11.7 |
| 27 Arts/Design/Media | 79,658 | 36,789 | 46.2 | 51,284 | 64.4 |
| 29 Healthcare Practitioners | 64,297 | 3,952 | 6.1 | 5,940 | 9.2 |
| 25 Education | 61,639 | 14,401 | 23.4 | 20,593 | 33.4 |
| 43 Office & Admin | 60,424 | 9,817 | 16.2 | 16,301 | 27.0 |
| 41 Sales | 54,143 | 7,232 | 13.4 | 12,937 | 23.9 |
| 21 Community & Social Service | 31,893 | 5,538 | 17.4 | 9,173 | 28.8 |
| 23 Legal | 16,873 | 3,208 | 19.0 | 7,297 | 43.2 |

VERIFIED. At 6-digit grain, current job: 816 occupations, 642 with >= 10 people of any field, 383 with >= 10 humanities-L1 people, 240 with >= 30, 102 with >= 100. At title grain: 477,313 titles, 12,426 with >= 10 people, 2,288 with >= 10 humanities-L1 people, 205 with >= 100. VERIFIED.

In the portal's windowed frame (year-10 destination among all anchored bachelors, 144,045 windowed; T16): Legal 2,018 people of whom 1,123 (55.6%) hold an L1+L2 humanities bachelor's; Arts/Design/Media 5,056, 68.9%; Education 7,273, 33.3%; Management 20,916, 21.4%; Computer & Math 8,979, 9.2%. VERIFIED.

### 2.12 Time-axis fork

| Measure | Graduation axis (portal) | Career-entry axis (cohorts/archetypes) | Status |
|---|---|---|---|
| Definition | anchor = bachelor end_year (A1) or start+3 (A2); year N = anchor + N | entry_year = first datable primary step (build_panel.py:96); career_age = calendar_year - entry_year (:150); valid_cohort entry 1990-2020 | VERIFIED |
| Humanities bachelor persons placeable | 69,766 of 375,028 (18.6%) | 316,456 of 375,028 (84.4%) | VERIFIED |
| Placeable on both | 59,429 (15.8%) | | VERIFIED |
| Persons in window at year 10 | 42,813 | 258,436 | VERIFIED |
| With SOC major at year 10 | 22,372 (52.3%) | 159,440 (61.7%) | VERIFIED |
| Field group x SOC major cells >= 10 at year 10 | 149 of 229 (98.5% of persons) | 205 of 251 (99.9%) | VERIFIED |
| Field group x title cells >= 10 at year 10 | 286 of 21,709 (21.3%) | 2,312 of 132,065 (36.0%) | VERIFIED |
| Agreement for the same person | entry within +/- 1 year of graduation anchor: 25.5%; entry 2+ years before graduation: 47.4%; entry 2+ years after: 27.1% | | VERIFIED |
| Archetype cohort observable (L1-L3, entry axis) | | 647,784 persons; 636,151 at career year 1; 487,071 at year 10; 361,774 at year 15 | VERIFIED |

```
SELECT round(100.0*avg((abs(p.entry_year - h.anchor) <= 1)::INT),1), round(100.0*avg((p.entry_year < h.anchor - 1)::INT),1), round(100.0*avg((p.entry_year > h.anchor + 1)::INT),1)
FROM hb h JOIN 'cohorts/profiles.parquet' p USING (linkedin_id) WHERE h.anchor IS NOT NULL AND p.valid_cohort
-- 25.5 | 47.4 | 27.1
```

### 2.13 Sample skew

| Dimension | Result | Status |
|---|---|---|
| Geography | 100% US country_code; 95.5% of steps with a parsed country are US | VERIFIED |
| Section selection | every profile has both an education and an experience section (1 exception each); 48.6% list exactly one education row and 9.0% exactly one experience row (20,000-profile sample) | VERIFIED |
| Currently employed | 85.5% of persons have a "Present" step; 88.0% have a step reaching 2025 | VERIFIED |
| Activity | 96.8% show a connection count, median 201, 28.1% at 500+; 33.9% default avatar | VERIFIED |
| Bachelor end years (persons with one, all fields) | <1980 9,462; 1980s 15,424; 1990s 22,679; 2000s 48,078; 2010s 101,470; 2020+ 82,558 (65.8% in 2010 or later; year-10 windows need <= 2015) | VERIFIED |
| Humanities anchors by decade | 1960s 473; 1970s 2,250; 1980s 4,128; 1990s 7,011; 2000s 14,236; 2010s 25,537; 2020s 16,087 | VERIFIED |
| Highest degree, humanities L1 any | HS 7,447; assoc 30,783; bachelor 145,698; master 70,659; doctorate 18,839; unknown 12,221 (graduate degree held by 30.5% of L1 persons) | VERIFIED |
| Institution (IPEDS join, 67.3% matched) | humanities L1 vs all: public 42.5% vs 43.4%; private nonprofit 26.5% vs 21.9%; R1 24.1% vs 22.8%; masters_larger 11.9% vs 12.3% | VERIFIED |
| Profile-level current location | city field is 100% populated; it carries "City, State, United States" for 75.8% of profiles (California 202,241; Texas 130,046; New York 112,807; Florida 109,840), and the pipeline's own parser career_clean.location.parse_location resolves 1,815,504 profiles (90.8%) to a US state (metro strings such as "Greater Chicago Area" included); nothing in the pipeline applies it to this field | VERIFIED |

## 3. Findings

### C1. The journey's time axis is undecided, the pipeline has two, and they disagree for the same people

Severity: BLOCKING. Affects: FIELD, Q1, Q2, Q3, P2, LAD5, CARD, TAKE block 2 and 3, ACT2, narrative steps 2, 6, 7, 9, 11.

Evidence (VERIFIED). The portal computes every year-N cell on a graduation anchor (analyses.py:43 joins panel at cal_year = anchor + FAN_YEAR; anchors.py:92-110), and only 18.6% of humanities bachelor persons have one (T1). The cohorts and archetypes modules compute the same statistics on a career-entry anchor (build_panel.py:96, :150; archetypes/common.py:135-185) which places 84.4% of them. For the 59,429 people on both axes the anchors agree within one year for 25.5%; for 47.4% the first datable job precedes the graduation anchor by two or more years (student and part-time jobs), so "career year 10" on the entry axis is frequently year 5-8 after the degree (2.12). Cell counts differ by roughly six times at year 10 (22,372 vs 159,440 classified). The journey's copy draws from both: "23 occupation groups", "one in eight", "98.5%" reproduce only in the portal (graduation) frame; "407,000 observable across career years 1 to 15" and "5,088 in legal and policy work at career year 10" are shaped like the archetype (entry) frame (archetype cohort 647,784; Legal, Policy & Research at year 10 = 24,531 all tiers, 5,395 L1-only; neither equals the journey's figure). The site concept (section 9, decision 2) records this as open.

Recommendation. Decide the axis before the partner builds the claim object, and encode the decision in one constant with the name of the axis printed in every claim. If the entry axis is chosen for coverage, the copy "ten years later" and "after the degree" must change to "ten years into working life", year 1 must be described as the first recorded job (it is by construction), and the graduation anchor should be carried as a labelled subset (it exists as grad_year/anchor_tier on the archetype cohort, archetypes/common.py:175-178). If the graduation axis is chosen, the population statement must say that four in five humanities graduates in the sample cannot be placed. Effort M.

### C2. Job-title grain does not clear the bar for most people in the journey's default views

Severity: BLOCKING for D3, P2, SORT/RARE at title grain, TAILSTATE; SIGNIFICANT for Q1/Q2 if the grain toggle defaults to titles.

Evidence (VERIFIED, 2.7-2.9). At year 10, all-humanities x title: 337 of 16,831 cells clear 10, holding 36.1% of the people with a title that year. Add a field-of-study filter: 21.3%. Add a CIP4 major: 11.4%. The "Ways in" panel at title grain for the largest destination (Management) names 31 year-1 titles covering 19.9% of the people; 15 of 23 destinations have no nameable year-1 title at all; with an English filter the panel names 5 titles covering 5.4%. Title-to-title corridors by field: 31 of 19,474 cells clear 10 (3.1% of people). The "13,933 titles that cleared the ten-person bar" (D3, FIELDTAIL) are titles held by ten people anywhere in a whole career across the whole cohort; they are not cells in any state the reader will be in. A reader who opens one of them as a destination will, in most states, land below the bar.

Recommendation. Make SOC major the default grain everywhere a pole is set; expose SOC 6-digit (deterministic-coded, 20% of endpoints) and titles only as a drill-down inside a cell, with the coded-subset caveat the portal already emits (analyses.py:93-111, fan_detail_note). Precompute the set of titles that clear 10 within each (origin, horizon) state rather than corpus-wide, and let D3 search only that set. Effort M.

### C3. The "one in eight" claim depends on a denominator that includes the half of the cohort with no occupation

Severity: SIGNIFICANT. Affects: ONELINE, PREDICT, REVEAL, Q1 copy, BEST, CLASSAGG, narrative steps 2 and 5, site concept section 7.

Evidence (VERIFIED). analyses.py:73-78 computes share = n / d where d is every windowed person (analyses.py:46-47), and 47.7% of windowed humanities persons have no SOC major at year 10 (T48b; per major unclassified_share 0.45-0.49 in portal_data.json). Under that denominator Management is 12.3% of the pooled cohort (one in eight). Among people who were actually classified it is 23.6% (one in four). Per field, the largest destination as a share of the classified is 43.0% for Fine & Performing Arts, 35.4% for Theology, 29.5% for Communication & Media, 23.7% for English (T6); even on the windowed denominator Arts is 23.3% and the portal's own top_bucket_share for arts is 0.2379. The BEST copy "The largest single destination for any one field of study was about one in eight" is therefore not supported for the largest L1 field in the sample.

Recommendation. The claim object (rule 7.1) needs two denominators, "people we could place" and "people with a coded occupation", and the reveal must be generated per field from the classified share. Retire the universal one-in-eight sentence; the honest pooled statement is "about one in four of those we could classify, and we could classify about half". Effort S in data, but it changes the site's central sentence.

### C4. Occupation coverage at the endpoint is about half at group grain and one fifth at named-role grain

Severity: SIGNIFICANT. Affects: Q1, Q3, P1, P2, METER, TAILSTATE, WAGE (federal code hand-off).

Evidence (VERIFIED). 61.3% of steps carry a SOC major and 21.5% a 6-digit code (2.10); at the year-10 endpoint of the humanities cohort 52.3% and 20.2% (T4). Of the pooled coverage, 65% comes from the LLM jury at 2-digit grain, so the drill-down to a named occupation, the WAGE hand-off ("that occupation carries a federal code") and any 6-digit view describe one fifth of the cohort. The uncoded remainder is not random: the most common uncoded roles are project manager, owner, sales, administrative assistant, customer service representative, marketing, founder, operations, realtor (2.10), which are ordinary humanities destinations. The portal states this per major (occupation_coverage_note, unclassified_share) but the journey copy never carries an unclassified count next to a number.

Recommendation. Every claim object should carry n_windowed, n_classified and n_coded_6digit. Add deterministic O*NET lexicon entries for the top uncoded roles (project manager to 11-9199/13-1082, administrative assistant to 43-6014, customer service representative to 43-4051, owner/founder to a self-employment bucket) and re-measure; each of these alone is tens of thousands of steps. Effort M.

### C5. The experience section was captured around the end of October 2025, not on the 2026-02-19 snapshot date the code uses

Severity: SIGNIFICANT. Affects: every "current" view (Q3 on current holders), tenure and "how long it took" (P2, TAKE block 3), the year-N window edge, the CARD's snapshot date.

Evidence (VERIFIED, 2.1). Job starts collapse from 10,630 in Oct 2025 to 334 in Nov 2025, 19 in Dec, 41 in Jan 2026 and 13 in Feb 2026, while 2024-2025 months run 18,000-40,000; job ends show the same cliff (Oct 2025 12,203, Nov 347). The raw strings show it directly (experience start_date 'Nov 2025' = 265 rows, 'Oct 2025' = 7,794). Posts and certifications continue at normal volume through Jan 2026 (certs issued Jan 2026: 5,105), and among 6,090 profiles demonstrably captured in 2026 the Nov 2025-Feb 2026 job starts are 14, 6, 11 and 1 against about 200 per month before. So the job history was frozen roughly four months before the file date. paths/common.py:43 sets SNAPSHOT_DATE = "2026-02-19" and build_spine.py:81 closes every "Present" step (21.45% of steps) at that date, lengthening ongoing tenures by about 3.5 months; LAST_COMPLETE_YEAR = 2025 (portal/common.py:54 and five sibling constants) treats 2025 as fully observed, but the experience section observes it through October. The year is right; the month is not, and it is the month that governs tenure and currency.

Recommendation. Add an EXPERIENCE_SNAPSHOT_DATE (approximately 2025-10-31, to be confirmed with the vendor) distinct from the file date; close "Present" at it; either set the window bound to 2024 for experience-based statistics or document that year-N cells whose year N is 2025 (2,522 humanities anchors at 2024 for year 1; 2,602 at 2015 for year 10) are observed for ten months. Print both dates on CARD and TAKE block 2. Effort S.

### C6. Six humanities cohort definitions exist; the journey's population figures match none of them and its tail figures are one build stale

Severity: SIGNIFICANT. Affects: AR1 population statement, FIELD, SKEP, CARD, FIELDTAIL, D3, narrative step 1.

Evidence (VERIFIED, 2.3). Person-level definitions in code range from 165,854 (terminal L1, deterministic) to 776,769 (any-row L1-L3, pooled); the archetype cohort is 647,784 and the portal names five major bundles covering six of the 13 CIP2 families (portal/common.py:165-171). The journey's 486,000 reproduces from none; its 407,000 does not reproduce on either axis (closest: 406,010 profiles of any field with a graduation year, cohorts/_panel_manifest.json, which is not a humanities count); 638,368 / 355,437 / 13,933 reproduce approximately (622,196 / 358,666 / 13,709) from the deterministic any-row L1+L2 cohort at role grain, a definition the site concept does not list as a candidate. The site concept (section 9, decision 1) says the canonical cohort is undecided.

Recommendation. Fix one definition (this audit's bachelor-level pooled L1+L2 is the one the portal's window logic already assumes; print the tier), regenerate every number in journey section 3 from it with the queries in section 2 of this report, and stamp the build id on the page. Effort S.

### C7. Employers cannot be named inside a destination, and "employers in your state" cannot be delivered

Severity: SIGNIFICANT. Affects: P5, JOBS, NEMP, ACT3, TAKE block 4, narrative step 13.

Evidence (VERIFIED, 2.9). At the year-10 destination, 17 of 19,214 (destination, employer) cells clear 10, holding 1.4% of the people; 18,066 of the cells are one person. Over whole careers, 134,979 of 154,597 employers of anchored humanities people appear once. The portal's own named employers at the loosened bar are Freelance, Starbucks, Target, Amazon, US Army, Teach For America (portal_data.json employer_field.labeled), because only early-career mass employers reach ten. The journey's "three named employers in this state with counts" would require (destination, state, employer) cells; the (field, destination, state) cells alone clear 10 for 43% of people.

Recommendation. Ship P5 as the dispersion statement the pipeline already computes (size buckets, singleton share, top-10 share; analyses.py:355-447) and name employers only where a cell clears 10 at the state the reader has chosen; remove "three named employers in this state" from TAKE or make it conditional. Effort S.

### C8. US state is known for half of steps and a third of windowed people; the pipeline holds an unused person-level current state

Severity: SIGNIFICANT. Affects: NGEO, GEO, P5, LAD2 rung 1, ACT3, rule 7.9.

Evidence (VERIFIED). location_us_state is populated on 51.56% of steps (the journey's 51.6%), 46.6% of humanities year-10 endpoints with an occupation, 37.8% of all windowed persons (T4, T34). A state filter on top of field and destination leaves 205 of 2,945 cells above 10. Separately, parsed/profiles.city is 100% populated and carries "City, State, United States" for 75.8% of profiles (1,516,159); running the pipeline's own career_clean.location.parse_location over its 21,713 distinct values resolves 1,815,504 profiles (90.8%) to a US state, yet no code applies it: build_normalized.py:162-187 parses only experience and position locations, and parse_linkedin.py:115-157 carries city through untouched.

Recommendation. Parse profile city with career_clean.location.parse_location into a person-level current_state (verified: 90.8% of profiles resolve), label it "where they are now" rather than "where the work happened", and use it for the NGEO filter and ACT3 with the coverage count restated. Effort S.

### C9. The "eleven kinds of work" grain does not exist in the pipeline

Severity: SIGNIFICANT. Affects: D2, DNONE, LAD4 rung 3, SORT, narrative step 4, site concept section 9 writing list item 2.

Evidence (VERIFIED). No code, mapping or output defines an eleven-category grouping (grep for "eleven"/"orientation" across .py/.json/.html returns only unrelated strings). The groupings that exist are 23 SOC major groups (61% step coverage), 17 industry L1 sectors (58% resolved), and 15 archetypes plus Other (archetype_spec.py:24-56; 10.7% Other at career year 10), which the site concept bans from the screen.

Recommendation. Define the eleven buckets as a crosswalk from SOC major (and, for the uncoded 39%, from role keyword rules like archetype_spec.KEYWORD_RULES), implement it as a mapping table with a measured coverage and Other share, and make LAD4 raise the grain to it. Until then LAD4 and D2 have no data behind them. Effort M.

### C10. Credentials are thin, unnamed in the normalized layer, and undated in it

Severity: SIGNIFICANT. Affects: P4, NCRED, ACT1, TAKE block 4, narrative step 13.

Evidence (VERIFIED, 2.9). 22.4% of anchored humanities persons hold any certification; at raw title grain 394 of 26,318 titles clear 10, covering 21.2% of person-certs, and the leaders are notary public, CPR, BLS, PMP and Series 7. normalized/certifications_person carries only counts and 18 domain booleans (cert_clean/run_cert.py docstring lines 1-13, schema in 2.2); the issuer (100% of raw rows) and the issue month (95.5%) exist only in parsed/certifications. "The career year they took it" and "named provider" are therefore not computable from the normalized layer today.

Recommendation. Add a per-certification row table (canonical title, issuer, issue year) and derive cert year minus anchor; expect the named set to be a few hundred titles and state the 22% holder share on the panel. Effort M.

### C11. Corridors and named routes hold at SOC-major grain only, and only for the five portal majors today

Severity: SIGNIFICANT. Affects: Q2, P2, TAKE block 3 ("three named routes, counts, typical elapsed years"), LAD1 to LAD3 example.

Evidence (VERIFIED, 2.8). Field x (year-1 group to year-10 group): 189 of 1,465 cells clear 10 (71.2% of people); for English 24 of 164 (69.1%); Philosophy & Religion and Area Studies fall to 20.6% and 18.7%; title-grain corridors 3.1%. Named multi-stage routes exist only in portal/pathways.py for the five MAJORS, 8 per major with 102-270 suppressed each. The LAD1 example (Classics, frontline service, legal and policy) is plausible in size terms: Classics sits in Languages & Linguistics (CIP 16), 1,610 windowed at year 10.

Recommendation. Corridors at SOC-major grain with the ladder; extend pathways to all 13 field groups (config-driven at portal/common.py:165); "typical elapsed years" should be a median with an n, from transitions.dwell_months. Effort M.

### C12. Vice Presidents are coded as Chief Executives, and that is the first named role a reader would see

Severity: SIGNIFICANT. Affects: P1, the fan detail drill-down, Q3 at 6-digit grain.

Evidence (VERIFIED). Steps coded 11-1011 (Chief Executives) have role_canonical 'president' 88,861 times; of those, the raw titles are President 45,154, Vice President 26,016, Senior Vice President 7,236, Executive Vice President 3,441, VP 1,629, Associate VP 687 (seniority tokens 'vice' on 42,000+). Chief Executives is the top named role inside Management for every portal major and the baseline (portal_data.json fan detail). A student opening Management for English graduates would read that the modal management job is Chief Executive.

Recommendation. Route titles carrying a 'vice' seniority token to a separate role (or to 11-1021 General and Operations Managers with a "vice president" display) in career_clean's occupation mapping; re-run the drill-down. Effort S.

### C13. The backward direction needs an explicit denominator, and the journey copy does not say which

Severity: SIGNIFICANT. Affects: Q3, P3, CARD, BACK, narrative step 7.

Evidence (VERIFIED, 2.11). Both framings are computable. On all profiles' current jobs, Legal holds 16,873 people of whom 19.0% have an L1 humanities degree (43.2% L1+L2); in the portal's windowed frame, Legal at year 10 holds 2,018 anchored bachelors of whom 55.6% hold an L1+L2 humanities bachelor's. The journey's Q3 copy ("5,088 people who held a humanities degree were in legal and policy work") uses a humanities-only numerator with no denominator; P3 ("what they studied") is meaningless under a humanities-only denominator (every destination would be 100% humanities) and is well supported under the all-bachelors denominator (Management: 33 of 40 CIP2 cells clear 10, 99.9% of people). Note also a third frame, current job holders with no window, which is what "who is already there" most naturally means and which is four months stale (C5).

Recommendation. The Q3 claim object should carry n_all, n_humanities and the frame (current holders or year-N windowed); P3 always uses the all-bachelors denominator; the narrative's "same data read backwards" should be qualified as true only in the windowed frame. Effort S.

### C14. The sample statement understates the selection

Severity: MINOR. Affects: AR1, SKEP, CARD, LIMITS.

Evidence (VERIFIED, 2.13). Every profile is US and every profile has both an education and an experience section (vendor selection, not "public professional profiles" at large); 85.5% have a current job and 88% a job reaching 2025; bachelor end years skew to 2010 and later (65.8% of those with a year) while year-10 windows need 2015 or earlier anchors; 30.5% of humanities-L1 persons hold a graduate degree; institutions skew slightly to private nonprofit and R1 relative to the whole sample; IPEDS matched 67.3%. The claim "undersamples people who left the professional track" is consistent with the 85.5% currently employed but cannot be tested from this data.

Recommendation. Population statement: "two million US LinkedIn profiles that list both education and work history, captured [date]". Effort S.

### C15. Year-grain dates and A2 anchors add about a year of noise to "elapsed years"

Severity: MINOR. Affects: TAKE block 3, P2 "how long it took", ACT2 "the career year they took it".

Evidence (VERIFIED). 13.84% of steps have year-only starts, widened to Jan 1-Dec 31 (build_spine.py:72-91); the panel is calendar-year grain (build.py:211-212); A2 anchors (8.7% of anchored humanities persons) are within one year for 80.4% by the pipeline's own gate (anchors.py:23-27). Elapsed-years figures should be medians with an n and a stated +/- 1 year resolution. Effort S.

## 4. Capacity gaps

Claims or views the journey wants that the data cannot support at the needed granularity:

1. A default title-grain view of destinations, ways in, or corridors (C2): 21-36% of people sit in a nameable title cell at year 10; 3% for title corridors.
2. "Largest destination about one in eight" as a field-independent fact (C3): false for Fine & Performing Arts and for the classified denominator everywhere.
3. Named employers inside a destination or a state (C7): 1.4% of people at year 10 sit in an employer cell of ten.
4. Eleven kinds of work as a grain (C9): not defined anywhere.
5. Credentials with provider and career year (C10): not in the normalized layer; 22% of people hold any.
6. A federal occupation code for the person the reader is looking at (C4, WAGE): available for one fifth of endpoints.
7. "Where the work happened" for more than half the steps (C8); state as a third filter leaves 43% of people above the bar.
8. Year N "after the degree" for four in five humanities graduates (C1): only 18.6% have a graduation anchor.
9. Rarest-first at fine grain with any filter (SORT, GUARD): at CIP4 x title, 11.4% of people are in a cell of ten; the interlock at two filters is not enough, one filter already fails.
10. Numbers currently printed in the journey (486,000; 407,000; 5,088; 1,021; 2,682; 638,368; 355,437; 13,933): none reproduces exactly on this build (C6).

Data the pipeline holds that the journey does not use:

1. The all-bachelors baseline (269,207 anchored, 144,045 windowed at year 10) with relative-risk ratios, distinctive destinations and diversity statistics (analyses.py:62-66, 161-204): supports SORT "most distinctive against all graduates" and an honest P3.
2. The graduate-track and choice fans (portal/launchboard.py, choices.py): "graduate step, who took it, and at which career year" is computed per major with levels and degree types (portal_data.json launchboard.grad_track), and level x CIP2 grad cells clear the bar for 99.5% of people (T31b).
3. Industry L1 at the endpoint (resolved for 44% of windowed people at year 10, 58% of steps; 138 of 182 field x sector cells clear 10, holding 99.5% of the people with a sector): a coarser second grain for LAD4.
4. Transitions with dwell months, gap months and typed direction (paths/transitions.parquet, 6.18M rows): "how long it took" and "typical elapsed years" with an n.
5. Profile-level current state for 90.8% of profiles via the existing parser (C8).
6. Certification issuer and issue month in parsed/certifications (C10).
7. Institution control, Carnegie class and state for 67.3% of persons (education_person.inst_*): the journey's "institution type" rung (LAD2) has data behind it.
8. Step descriptions on 50.8% of steps for P1 "what this work involved".
9. The archetype person-year table (8.29M rows, 647,784 persons) as a ready-made entry-axis substrate if C1 goes that way.

## 5. What I could not verify, and why

1. The vendor's actual capture window per profile. No per-record timestamp exists; the October 2025 cliff is inferred from monthly volumes and is robust, but the exact date and the reason posts and certifications extend later (a later crawl pass or a merged feed) are not knowable from the files.
2. The provenance of the journey's headline numbers (486,000; 407,000; 5,088; 1,021; 2,682) and the exact build behind the tail figures. They reference docs I was not permitted to read; I reproduced the tail figures approximately and the rest not at all.
3. Accuracy of the LLM jury occupation labels on the humanities cohort. The jury mapping keys roles the deterministic coder abstained on (0 overlapping steps), so no in-data agreement check is possible; career_clean/results/soc_calibration.json holds a held-out calibration I did not audit.
4. Whether the sample undersamples people who left the professional track. The data shows 85.5% currently employed but has no comparison population.
5. The share of "hum_l1_any" persons whose humanities credential is not a bachelor's (associate or high school rows carry CIP codes: 30,783 L1 persons have an associate as highest level). I counted them but did not inspect the rows.
6. The 98.5% figure's exact provenance; it reproduces at field group x SOC major, year 10, but I did not confirm that is how it was originally computed.

## 6. Top 5

1. C1. Two time axes, undecided: graduation anchors place 18.6% of humanities graduates and career-entry places 84.4%, they agree within a year for only 25.5% of shared people, cell counts differ six-fold, and the journey quotes numbers from both.
2. C2. Job-title grain fails the ten-person bar for two thirds of people in the pooled year-10 view and for 79-89% once a field or major is set; "13,933 titles clear the bar" is a corpus-wide count, not a per-view one.
3. C3. "One in eight" is an artifact of counting the 48% unclassified in the denominator; among classified people the largest destination is one in four pooled and 43% for Fine & Performing Arts, so the site's central sentence is not supported as written.
4. C5. Job histories were captured around end of October 2025 while the code closes "Present" roles at 2026-02-19 and treats 2025 as fully observed; every current-job and tenure figure is about four months off.
5. C7/C8/C10. The exit step's concrete leads are thin: employers name for 1.4% of people inside a destination, US state exists for 38% of windowed people (a person-level current state for 91% of profiles sits unparsed), and credentials are held by 22% with no provider or date in the normalized layer.
