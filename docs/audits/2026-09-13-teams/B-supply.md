# Audit B (supply side): what the pipeline can feed into the user journey

Auditor lens: inventory the pipeline's outputs and the handoff mechanics, from the code and the data only. Repo: /home/alex/linkedin-analysis, branch recovery-refactor, working tree clean at start. Date of audit: 2026-09-13. All paths below are relative to the repo root unless absolute.

Evidence convention. VERIFIED means I read the cited lines or ran the cited query and am reporting its output. INFERRED means the claim is reasoned from verified facts but the claim itself was not directly tested. Every count in this report came from a query or a file I ran or read in this session; nothing is estimated.

## 1. Method

Order of work:

1. Read the four permitted journey documents in full: docs/design/2026-09-10-user-journey.md (chart, copy table, rules 7.1 to 7.10, section 8 refusals), 2026-09-10-user-journey-narrative.md (15 steps with a "the data is" line each), 2026-09-10-user-journey-plain.md (step table with "the data behind it"), 2026-09-10-site-concept.md (sections 6 and 9 name the open decisions). Nothing else under docs/ was opened, and no root or module markdown was opened.
2. Read the drivers: Makefile (all 80 lines), scripts/refresh_downstream.sh, scripts/check_freshness.py, scripts/overnight_followups.sh, pyproject.toml, .gitignore. Ran scripts/check_freshness.py (read-only; it only stats files) and read refresh.log and .build_status.
3. Read every manifest JSON: parsed/_manifest.json, normalized/_manifest.json and the four normalized/_*_manifest.json, industry/results/build_manifest.json, paths/_manifest.json, the six transition_network/*_manifest.json, cohorts/_panel_manifest.json, archetypes/results/_*_manifest.json, portal/_manifest.json.
4. Read the portal package in full (common.py, run_portal_data.py, run_share_build.py, build.py, analyses.py, pathways.py, pillars.py, launchboard.py, first 120 lines of choices.py, portal_tests.py lines 20 to 140), share/system-schema.mmd, the headings and the JSON-contract and update-cycle sections of share/System-Map.html and share/System-Schema.html, and the structural parts of portal/share_template.html (views, the __PORTAL_DATA_JSON__ token, and every PORTAL.* / m.* field the template reads).
5. Skimmed the upstream code for inputs, outputs and parameters: parse_linkedin.py (schema section and run()), build_normalized.py (header, function list, main), paths/common.py, cohorts/common.py and build_panel.py, archetypes/archetype_spec.py and common.py, cert_clean/run_cert.py, enrichment/build_enrichment.py, edu_clean/anchors.py (A1/A2 rules), transition_network/common.py (SOC_MAJOR) and build_network.py (min_support), industry/build_industry.py flags.
6. Ran DuckDB DESCRIBE and count(*) on 31 parquet files (listed in section 2.3) and about 30 aggregate queries against normalized/, paths/, cohorts/, archetypes/results/, parsed/certifications and portal/results/portal_data.json. Queries and results are quoted inline where they support a finding.
7. Grepped for downstream consumers of every intermediate output to identify dead ends.

Not done: no make target, no build script, no LLM call, no git log/show/diff, no file created or changed inside the repo.

## 2. Inventory

### 2.1 Stage table

Row counts are from manifests (M) or from count(*) queries I ran (Q). Freshness is the file mtime versus its inputs as of 2026-09-13; the freshness checker result is quoted where the stage is covered by it.

| Stage | Driver / entry point | Inputs | Outputs (files) | Key parameters and thresholds | Row counts | Freshness | Tests |
|---|---|---|---|---|---|---|---|
| parse | `make parse` -> parse_linkedin.py | data/snap_mlsi9jwqziij1k8zq.{1..8}.jsonl (25 GB, all dated 2026-02-19, VERIFIED ls) | parsed/<table>/<shard>.parquet for 19 tables + parsed/_manifest.json | schema fixed in code (parse_linkedin.py lines 100 to 384); no skills table exists (grep -i skill returns nothing, VERIFIED) | 2,000,000 profiles; experience 9,076,606; positions 2,788,549; education 3,577,659; certifications 1,673,732 (M) | 2026-06-01; manifest has no snapshot id field, only the file names carry `snap_mlsi9jwqziij1k8zq` (VERIFIED parsed/_manifest.json) | none specific; normalization_regression_checks.py downstream |
| normalize | `make normalize` / `normalize-fast` -> build_normalized.py; integrates edu_clean.apply_degree_level_pooled, apply_cip_pooled, apply_institution_meta (build_normalized.py lines 1076 to 1096, VERIFIED) | parsed/education, experience, positions; normalized/mappings/*.parquet (22 files, VERIFIED ls), including LLM-jury mappings field_cip_jury, role_soc_jury, degree_level_jury that are produced outside any make target | normalized/education.parquet, education_person.parquet, career_steps.parquet, mappings/*, _manifest.json plus _cip_pooled/_dlevel_pooled/_institution_meta manifests | EDU_LAST_COMPLETE_YEAR = 2025 (build_normalized.py line 58); CIP pooled coverage 58.83 -> 82.53 % (normalized/_cip_pooled_manifest.json); degree level pooled 79.69 -> 81.91 % | education 3,577,659; education_person 1,999,974; career_steps 10,800,787 (Q) | education 2026-09-01, career_steps 2026-09-02; last run was `--sections career` only (normalized/_manifest.json "sections": "career", VERIFIED) | edu_clean.humanities_tests, dlevel_tests, tier_tests, cip_tests; career_clean.se_tests, company_tests, soc_tests, soc_data_checks; normalization_regression_checks.py (Makefile lines 59 to 77) |
| cert | `make cert` -> cert_clean.run_cert | parsed/certifications | normalized/mappings/cert_domain.parquet (530,237 rows Q), normalized/certifications_person.parquet, normalized/_cert_manifest.json | deterministic curated head + keyword rules; 18 domains; row coverage 58.93 % (manifest) | 545,409 persons (M and Q) | 2026-09-01; NOT in refresh_downstream.sh and NOT in check_freshness.py STAGES (VERIFIED lines 24 to 52) | cert_clean.cert_tests |
| industry | refresh stage 1 -> industry.build_industry --propagate --force-vocab | normalized/career_steps.parquet, industry/curated*.py, name_rules.py, occupation_prior.py, taxonomy.json (17 L1 codes incl. XOT unresolved, 162 nodes, Q) | industry/results/company_industry.parquet, step_industry.parquet, build_manifest.json | L1 row coverage 59.2 %, step propagation L1 58.35 % (build_manifest.json); LLM jury cache merged only if present (llm_candidates 0 in this build) | company_industry 3,110,970; step_industry 10,800,787 (Q) | 2026-09-02, ok | industry.tests |
| paths (spine) | refresh stages 2 and 6 -> paths.build_spine --force | normalized/career_steps.parquet, paths/seniority_scores.parquet, reference/soc_status.parquet | paths/steps.parquet, transitions.parquet, _manifest.json | SNAPSHOT_DATE 2026-02-19, LAST_COMPLETE_YEAR 2025 (paths/common.py lines 43, 55); MAX_STEPS_PER_PROFILE 100; TAU_UP 0.08, TAU_DOWN 0.12, CONF_MIN 0.3 (lines 148 to 150) | steps 10,798,352; transitions 6,180,324; 1,999,961 profiles; 95.23 % of steps carry a seniority score (M) | 2026-09-02, ok | paths.spine_tests (in make test); paths.seniority_tests exists but is in no make target (VERIFIED Makefile) |
| network (role, occupation, soc_major) | refresh stages 3,4,7,8,9,10,11,12 -> transition_network.build_network / analyze | paths/transitions.parquet | transition_network/{axis}_nodes, _edges, _backbone_edges, _nodes_analyzed.parquet, _communities.json, manifests | min_support 1; alpha 0.05; role axis: 1,947,652 nodes, 4,387,447 edges, coverage 97.46 %; occupation axis: 824 nodes, 39,825 edges, coverage 7.84 %; soc_major: 23 nodes, 529 edges, coverage 42.4 % (manifests) | as stated | 2026-09-02, ok | none in Makefile |
| seniority | refresh stage 5 -> paths.seniority | transition_network/role_nodes_analyzed.parquet | paths/seniority_scores.parquet | SpringRank revealed seniority | 1,947,652 roles (Q) | 2026-09-02; checked against nothing by design (check_freshness.py lines 32 to 36) | paths.seniority_tests (not in Makefile) |
| cohorts | refresh stage 13 -> cohorts.build_panel --force | paths/steps, transitions, normalized/education_person, reference/bls_unemployment | cohorts/profiles.parquet, panel.parquet, _panel_manifest.json | career_age = calendar_year - entry_year (build_panel.py line 150); valid cohort entry years 1990 to 2020 (cohorts/common.py lines 35 to 36); COMMON_WINDOW_YEARS 8 | profiles 1,999,916; panel 41,979,550 person-years (M and Q) | 2026-09-02, ok | cohorts.cohort_tests |
| cohorts analyses | manual: cohorts.profiles, scarring, survival, generational, typologies | panel, profiles, transition_network/trajectory_features | cohorts/age_profiles.parquet, generational.json, typologies.json, three manifests | | age_profiles 120 rows | 2026-07-22, older than the 2026-09-02 spine; not in refresh or freshness (VERIFIED) | none |
| archetypes | refresh stage 14 -> archetypes.run_all | career_steps, step_industry, paths/steps, transitions, cohorts/panel, education_person | archetypes/results/role_features, role_archetype, person_year_archetype, occupancy, job_flows, state_flows.parquet + manifests | 15 archetypes + Other (archetype_spec.py lines 24 to 57); soc_min_support 10; embed_min_cosine 0.45 | person_year 8,287,608 rows / 647,784 persons; role_archetype 2,605,247 (Q) | 2026-09-02, ok | archetypes.archetype_tests |
| portal data | refresh stage 15 / `make portal` -> portal.run_portal_data | normalized/education.parquet, paths/steps, transitions, transition_network/occupation_nodes_analyzed, industry/results/step_industry, reference/soc_status, cip_humanities, industry/taxonomy.json, plus mappings/field_cip_jury and role_soc_jury (portal/common.py lines 31 to 38, 97, 117) | portal/results/portal_data.json (896,190 bytes), portal/_manifest.json, cache portal/results/_cache/{membership,panel}.parquet | MIN_SUPPORT 10, DETAIL_MIN_SUPPORT 10, BREADTH_MIN_PERSONS 5, DISTINCTIVE_RR 1.5, FAN_YEAR 10, CURVE_YEARS 0..20 step 2, PATH_TOP 8, SECTOR_TOP 8, EMPLOYER_WINDOW_YEARS 5, ANCHOR_TIERS (A1, A2), five MAJORS (portal/common.py lines 121 to 172; analyses.py lines 355 to 357) | membership 308,154 rows; panel 4,212,153 person-years (Q on cache) | 2026-09-02, ok | portal.portal_tests (make test-data) |
| share build | refresh stage 16 / `make portal` -> portal.run_share_build | portal_data.json + portal/share_template.html | share/Humanities-Workforce-portal.html (1,049,727 bytes) and .zip (152,424 bytes) | injects JSON at the single __PORTAL_DATA_JSON__ token (run_share_build.py lines 22 to 33) | | 2026-09-02, ok | none |
| enrichment | manual: enrichment.build_enrichment (no make target) | education_person, parsed volunteer/publications/languages/organizations/honors | enrichment/results/enrichment.json | | | 2026-07-22 | enrichment.enrichment_tests |
| freshness | refresh stage 17 / `make check-freshness` | mtimes of 14 stage manifests and their declared inputs | exit code | mtime comparison only (check_freshness.py lines 55 to 62) | | all 14 stages "ok" on 2026-09-13 (VERIFIED run) | |

### 2.2 Lineage table: raw snapshot to each terminal output

| Terminal output | Lineage (left to right) | Consumed by anything downstream? |
|---|---|---|
| share/Humanities-Workforce-portal.html (+ .zip) | data/*.jsonl -> parsed/* -> normalized/{education, career_steps} (+ jury mappings) -> industry/results/step_industry -> paths/{steps, transitions} (with seniority loop via transition_network role axis) -> transition_network/occupation_nodes_analyzed (labels only) -> portal substrate (membership, panel) -> portal/results/portal_data.json -> template injection | No. This is the only UI-facing terminal. |
| portal/results/portal_data.json | as above, minus the last step | share build only (run_share_build.py line 26); gitignored (.gitignore line "/portal/results/portal_data.json", VERIFIED) |
| archetypes/results/{person_year_archetype, occupancy, job_flows, state_flows}.parquet | ... -> paths -> cohorts/panel -> archetypes | Nothing outside archetypes/ reads them (grep, VERIFIED); gitignored |
| cohorts/{panel, profiles}.parquet | ... -> paths/steps, transitions + education_person -> cohorts.build_panel | panel: archetypes only; profiles: nothing (grep, VERIFIED) |
| transition_network/{role,occupation,soc_major}_{edges,backbone_edges,communities} | ... -> paths/transitions -> build_network -> analyze | role_nodes_analyzed feeds paths.seniority; occupation_nodes_analyzed feeds portal labels; every edge, backbone and community file is a dead end (grep, VERIFIED) |
| normalized/certifications_person.parquet | parsed/certifications -> cert_clean.run_cert | Nothing (grep, VERIFIED) |
| enrichment/results/enrichment.json | education_person + parsed enrichment tables | Nothing |
| cohorts/{typologies, generational}.json, age_profiles.parquet; transition_network/{sequences, temporal}.json, trajectory_features.parquet | analysis passes on the spine and panel | Nothing; dated 2026-06-04 and 2026-07-22, before the 2026-09-02 spine rebuild; not covered by check_freshness (VERIFIED ls and STAGES) |

### 2.3 Schema listing for every terminal or substrate output a website could plausibly consume

All schemas below are DuckDB DESCRIBE output, VERIFIED. Row counts are count(*).

portal/results/portal_data.json (the only export built for a UI; 896,190 bytes; generated 2026-09-02; snapshot_date 2026-02-19; min_support 10). Top-level keys: anchor_tiers_note, baseline, baseline_def, boundaries, boundaries_note, choices_not_measured, choices_notes, choices_pooled, diversity_note, fan_detail_note, generated, launchboard_notes, majors, min_support, occupation_coverage_note, snapshot_date, window_rule. `majors` has exactly five keys: arts, commmedia, english, history, philrel (portal/common.py lines 165 to 171). Per major: name, cip_families, nha_tier, records, persons, persons_anchored, persons_anchored_a1, anchor_drop_rate, anchor_method_mix, cip_source_mix, persons_windowed_y10, kpi{breadth, breadth_of, distinctive, up_share, dwell_median_mo}, fan[ {group (SOC major label), share, rr, n, detail{group_total, detail_coded, roles[{role, n, share_of_group}], roles_shown_n, other_coded_n, no_detail_n}} ], unclassified_share, soc_source_mix, sectors[{sector, share, n}] (industry L1, top 8 + Other), industry_unresolved_share, curve{years[11], median_seniority[11], n[11]}, pillars{growth, stability, skill, direction} (percentile vs baseline), paths[ up to 8 {stages[{group}], n_persons, terminal_group, unexpected} ], paths_suppressed_count, paths_grain ("soc_major_pooled"), launchboard{first_destinations{cohort, fan, unclassified_share}, outlook{y3, y5}, stability{0,1,2+ mover classes}, grad_track{horizon 5, cohort, any, by_level, by_type, detail_bar, min_support}}, employer_field{window_years 5, employer_relationships, n_employers, singleton_employer_share, top10_share_of_cohort, size_buckets[5], labeled[{name, n}]}, diversity{classified_n, unclassified_share, effective_destinations, groups_reached, groups_of 23, top_bucket_share, top3_classified_share}, choices{cohort, double_major, grad_school, internship, military, self_employment, service_year}. `baseline` has the same shape minus kpi/sectors/paths. Granularity: one row-set per major, destination grain = 23 SOC major groups at year 10 after graduation anchor, with a 6-digit O*NET drill-down for the deterministically coded slice only. Sample values: english persons 38,450 -> persons_anchored 6,831 -> persons_windowed_y10 4,612; fan 16 cells, top Education share 0.1271 n 586; employer_field n_employers 9,314 of which 8,641 singletons, 18 named at n >= 10 (first: Freelance 201, Starbucks 23, Teach For America 22).

normalized/career_steps.parquet (10,800,787 rows): source_table, linkedin_id, experience_idx, position_idx, company_raw, company_id_raw, company_canonical_id, company_id_canonical, company_method, company_confidence, employment_type (+method, confidence), title_raw, title_canonical_id, seniority_level, role_canonical, role_display, seniority_rank_token, title_method, title_confidence, occupation_canonical_id, occupation_code, occupation_method, occupation_confidence, occupation_major_pooled, occupation_source, functional_cluster (+method, confidence), location, location_country, location_us_state, location_city, location_method, start_date, end_date, start_year, start_month, end_year, end_month, is_current, duration, duration_short, description, is_duplicate.

paths/steps.parquet (10,798,352): row_id, linkedin_id, source_table, experience_idx, position_idx, profile_step_count, company_canonical_id, company_id_canonical, company_raw, employment_type, title_raw, role_canonical, seniority_level, seniority_ordinal, occupation_code, soc_major, soc_source, location, revealed_pct, job_zone_norm, seniority_score, seniority_confidence, start_date_raw, end_date_raw, start_dt, end_dt, start_granularity, end_granularity, is_ongoing, datable, tenure_months, bad_negative_duration, bad_future_start, in_workforce. Note: no role_display and no location_us_state on the spine.

paths/transitions.parquet (6,180,324): linkedin_id, from_row_id, to_row_id, from_start_dt, from_end_dt, to_start_dt, dwell_months, gap_months, overlap_months, has_gap, has_overlap, seniority_direction, kind, delta_sen, seniority_score_confidence, transition_type, direction_from_lexical, transition_confidence, from/to_employment_type, from/to_company, from/to_company_id, from/to_role, from/to_seniority, from/to_seniority_ordinal, from/to_sen_score, from/to_occupation, from/to_soc_major, from/to_location.

cohorts/panel.parquet (41,979,550 person-years): linkedin_id, calendar_year, career_age, entry_year, entry_cohort_bin, entry_unemployment, generation, valid_cohort, nha_level_any, hum_l1_any, hum_l1_bachelor_any, humanities_field_group, seniority_score, seniority_confidence, occupation_code, soc_major (2-digit code), soc_source, job_zone_norm, employment_type, role_canonical. This is the only materialized person-year table on the career-entry axis.

cohorts/profiles.parquet (1,999,916): linkedin_id, entry_year, last_year, observed_max_career_age, n_steps, first_occupation, first_soc_major, first_role, right_censored, graduation_year, birth_year_proxy, generation, entry_unemployment, valid_cohort, entry_cohort_bin, nha_level_any, hum_l1_any, hum_l1_bachelor_any, humanities_field_group.

normalized/education.parquet (3,577,659): linkedin_id, idx, school_raw, school_canonical_id, school_slug, school_method, school_confidence, degree_raw, degree_canonical_id, degree_level, degree_type, degree_method, degree_confidence, field_raw, field_canonical_id, cip_code, cip2, cip4, field_method, field_confidence, nha_level, humanities_field_group, start_year, end_year, in_progress, is_duplicate, description, description_html, institute_logo_url, url, degree_level_pooled, degree_level_source, cip2_pooled, cip_source, nha_level_pooled, humanities_field_group_pooled.

normalized/education_person.parquet (1,999,974): linkedin_id, n_edu_rows, highest_degree_level, highest_degree_level_pooled, highest_degree_year, bachelor_end_year, any_end_year_min, any_end_year_max, cip_code, cip2, cip4, nha_level, humanities_field_group, cip2_pooled, nha_level_pooled, humanities_field_group_pooled, hum_l1_any, hum_l2_any, hum_l3_any, hum_l1_bachelor_any, hum_l1_bachelor_pooled_any, school_slug, inst_unitid, inst_control_label, inst_carnegie_label, inst_iclevel_label, inst_state, inst_region, inst_cbsa_metro.

normalized/certifications_person.parquet (545,409): linkedin_id, n_certs, n_certs_classified, domains VARCHAR[], top_domain, and 18 booleans has_pm, has_fin, has_health, has_it_cloud, has_it_sec, has_it_net, has_data, has_swdev, has_hr, has_sales_mkt, has_edu, has_trades, has_food, has_fitness, has_legal, has_lang, has_design, has_mgmt. No credential name, provider or date. parsed/certifications (1,673,732) carries linkedin_id, idx, title, subtitle (provider), meta (free text such as "Issued Dec 2014 Expires Dec 2016"), credential_id, credential_url.

industry/results/step_industry.parquet (10,800,787): linkedin_id, experience_idx, position_idx, source_table, key, industry_code, l1, l2, l3, l4, depth, method, confidence, sector, needs_review.

transition_network/role_edges.parquet (4,387,447) and occupation_edges (39,825) and soc_major_edges (529): from_node, to_node, from_label, to_label, weight, n_persons, is_self_loop, modal_kind, modal_transition_type, mean_delta_sen, mean_transition_confidence, out_strength, in_strength, expected, relative_risk, p_transition, z, mean_dwell_months, mean_gap_months, frac_with_gap, frac_up, frac_flat, frac_down, in_backbone_support. *_nodes_analyzed: node, label, out/in_strength, out/in_degree, self_loops, out_persons, net_flow, pagerank, (betweenness, hub_score, authority_score on the two small axes), springrank, springrank_support, infomap_community, leiden_community, soc_major. Note: on the role axis label == node (e.g. 'grantsmanager'), VERIFIED.

archetypes/results: person_year_archetype (8,287,608): linkedin_id, career_year, archetype_id, archetype_label, seniority_score, employment_type, nha_level, humanities_field_group, entry_year, entry_cohort, grad_year, anchor_tier, in_window. state_flows (11,969): entry_cohort, year_from, from_archetype, to_archetype, n_persons. job_flows (13,173): entry_cohort, career_year, from_archetype, to_archetype, n_moves. occupancy (832): entry_cohort, career_year, archetype_id, archetype_label, n_persons, share. role_archetype (2,605,247): role_canonical, archetype_id, archetype_key, archetype_label, assign_method, embed_cosine, n_persons, n_steps.

reference: soc_status (798: soc_code, job_zone, svp_low, svp_high, job_zone_norm), cip_humanities (2,327: cip_code, nha_level, is_humanities, is_humanistic_social_science_incl, is_liberal_arts, humanities_field_group), institution_meta (6,163 IPEDS: unitid, instnm, control, control_label, iclevel, iclevel_label, carnegie_c21basic, carnegie_label, state, region, cbsa_metro, city), bls_unemployment (50: year, unemployment_rate, is_estimate). No BLS wage (OES/OEWS) table exists (grep -i "oes|wage|oews" over reference/ and portal/ finds only "no wage claims" comments, VERIFIED).

## 3. Findings

### B1. There is no data contract for the journey; the only UI export is a different product's aggregate

Severity: BLOCKING. Journey steps affected: every band; specifically FIELD (Q0), Q1/Q2/Q3, D3, P2 to P5, LAD2 to LAD6, SORT/RARE/TAILSTATE, GEO, CARD, TAKE.

Evidence (VERIFIED):
- The only artifact the pipeline emits for a UI is portal/results/portal_data.json, injected verbatim into portal/share_template.html (portal/run_share_build.py lines 19 to 33). Its shape is fixed by portal/run_portal_data.py lines 90 to 186.
- It is keyed on five majors plus a baseline (portal/common.py lines 165 to 172: english, history, philrel, arts, commmedia). There is no pooled all-humanities group, so the journey's opening FIELD ("407,000 people ... this is what they were doing at year ten. All of it") has no cell to read.
- Destination grain is the 23 SOC major groups (analyses.py lines 33 to 90) with a 6-digit drill-down only for the deterministically coded slice (analyses.py lines 93 to 158; english Education cell: group_total 586, detail_coded 139, no_detail_n 447). There is no job-title grain anywhere in the export; D3 ("from the 13,933 titles that cleared the bar"), P2 ("jobs at year one, named"), RARE and TAILSTATE cannot be served.
- There are no origin-to-destination cells. The nearest thing is `paths`: at most 8 SOC-major n-gram chains per major (pathways.py lines 42 to 114; english: 8 emitted, 180 suppressed). Q2 (corridor) and Q3 (backward origins) cannot be served.
- No certifications (grep of run_portal_data.py and analyses.py for "cert" returns nothing), no US state (the portal never reads location_us_state; portal/build.py lines 188 to 200 select only `location`-free columns), no institution facet, no horizon pooling, no rarity sort.
- The template reads only PORTAL.majors, boundaries, baseline, choices_*, snapshot_date, min_support, generated (grep of share_template.html, VERIFIED); it is a per-major dashboard with four views (Overview, Stories, Portal, Methods; share_template.html lines 485 to 490), not a two-pole canvas.

Recommendation (L): define a new export package for the journey rather than extending portal_data.json. At minimum three suppressed, versioned tables: (a) destination cells by (population, origin_kind, origin_id, horizon, grain, destination_id, filters) with n; (b) per-destination panels (ways-in titles at year 1, fields of study, credentials, employers, states) each with n and the shown/suppressed/people-suppressed triple; (c) a numbers table for every headline figure with the exact query. Because the state space is combinatorial (origin x destination x horizon x grain x filters x rungs), this is a query service or a precomputed cube with a documented key, not one JSON file; the System-Map page already sketches the "live aggregate DB" and "read API" as "to build" (share/System-Map.html, JSON contract and update-cycle sections; share/system-schema.mmd Diagram 1 is marked PROPOSAL).

### B2. The export is on the graduation-anchor axis and keeps about a fifth of the people; the journey is written on the career-entry axis, for which no export exists

Severity: BLOCKING. Journey steps affected: FIELD, Q1, Q2, Q3, METER, CARD ("Horizon: career year 10"), ACT2, and the site-concept section 9 decision 2.

Evidence (VERIFIED):
- The portal substrate anchors every person on a bachelor's graduation year (portal/build.py lines 145 to 164 via edu_clean/anchors.py group_anchor_sql lines 142 onward; A1 = observed end_year, A2 = start_year + fitted duration; ANCHOR_TIERS = (A1, A2), portal/common.py line 75). Year-N is `cal_year = anchor + N` (analyses.py line 43).
- Bachelor rows carrying an end_year: 301,480 of 1,555,454 (19.4 %). Query: `SELECT count(*), count(end_year) FROM 'normalized/education.parquet' WHERE degree_level=4`.
- The funnel in portal/_manifest.json: english persons 38,450 -> persons_anchored 6,831 (anchor_drop_rate 0.8223) -> persons_windowed_y10 4,612; baseline 1,254,934 -> 269,207 -> 144,045. All five majors together hold 22,297 windowed year-10 persons (4,612 + 2,465 + 1,446 + 7,915 + 7,459; Q on portal_data.json).
- The journey's copy uses "career year" throughout (user-journey.md lines 360, 370 to 372, 390). The only materialized person-year table on that axis is cohorts/panel.parquet (career_age = calendar_year - entry_year, cohorts/build_panel.py line 150), and the archetype table built on it (person_year_archetype, career_year 1 to 15, 647,784 persons). Neither has an export, a suppression layer, or a right-censoring rule for horizon N: at career_age 10, L1 persons come from entry years 1900 to 2016 (query on panel), so a valid_cohort filter (1990 to 2020, cohorts/common.py lines 35 to 36) plus an equal-window cut per horizon would have to be added.
- Sizes differ by an order of magnitude: L1 valid_cohort persons at career_age 10 = 205,032 (201,965 with a title, 128,874 with a SOC major); the portal's five-major year-10 population is 22,297.

Recommendation (M): pick the axis (site-concept section 9 decision 2) and build the journey's substrate on it. If career entry wins, add to cohorts/build_panel or a new module: equal-window cut (entry_year <= LAST_COMPLETE_YEAR - N), the population flags at the chosen humanities definition, role_display, location_us_state and institution facets, and a suppression layer identical in spirit to portal/analyses.py. If graduation wins, the population statement in the journey must shrink to what survives anchoring.

### B3. The journey's "measured" headline numbers cannot be re-derived from any materialized artifact, and they are not pinned to a build

Severity: BLOCKING for CARD, FIELD, FIELDTAIL, SKEP, Q1 to Q3 copy (rule 7.1 requires every number to carry population, n, horizon, bar); SIGNIFICANT elsewhere.

Evidence:
- 2.0M profiles: matches parsed/_manifest.json total_profiles 2,000,000 (VERIFIED).
- 4.3M title-to-title moves: matches role_manifest.json edges 4,387,447 (VERIFIED). 1.67M certification records / 545,000 people: 1,673,732 and 545,409 (VERIFIED).
- 486,000 with a humanities degree and 407,000 observable across years 1 to 15: no materialized definition I tested reproduces either. Persons by tier on education_person: hum_l1_any 293,808; hum_l2_any 510,306; hum_l3_any 776,769; deterministic nha_level 1 / 1-2 / 1-3: 210,495 / 358,675 / 579,325; bachelor-only variants 181,767 / 375,028 / 593,877 (pooled) and 115,799 / 239,705 / 415,226 (det). Persons observed at career_age 1 to 15 in cohorts/panel: 293,056 (L1), 509,209 (L1-2), 774,968 (L1-3). observed_max_career_age >= 15 in cohorts/profiles: 197,319 / 344,219 / 507,143 (VERIFIED queries). The closest number to 407,000 anywhere is cohorts/_panel_manifest.json with_graduation_year 406,010, which is all profiles, not humanities (INFERRED that this is the source).
- 638,368 distinct titles across 355,437 people, 13,933 at ten: nine population-by-column combinations tested (role_canonical and title_canonical_id on paths/steps and career_steps, for L1/L2/L3 pooled and deterministic, the archetype panel and hum_l1_bachelor_any) give title counts of 290,263 to 1,107,888 and ten-plus counts of 6,689 to 23,265; none matches. The singleton share is 86.2 to 86.9 % everywhere, so that ratio is robust (VERIFIED queries).
- 5,088 in legal and policy work at career year 10: the current build gives 5,395 for the closest definition (person_year_archetype, nha_level 1, in_window, career_year 10, archetype 11 "Legal, Policy & Research") and 2,821 at SOC major 23 "Legal" for L1 valid_cohort on cohorts/panel. 1,021 from policy/research at year 1 to management at year 10: 3,616 (any) / 3,390 (both in_window) on the same table (VERIFIED queries). The archetype table was rebuilt on 2026-09-02, so any figure measured earlier has moved.
- No export carries these numbers; portal_data.json's boundaries are 210,495 / 358,675 / 579,325 persons (VERIFIED).

Recommendation (S to M): add a `numbers.json` (or table) emitted by the refresh, one row per headline figure with population definition, horizon, grain, bar, the SQL used, and the build id. The journey's section 3 asks for exactly this ("replace every daggered figure with a queried one"), but the undaggered ones need it too.

### B4. The journey uses three destination grains, one of which does not exist in the pipeline, and the copy uses archetype labels the concept bans

Severity: SIGNIFICANT. Journey steps affected: D2 (eleven descriptions), LAD4 (rung 3: "raise the grain ... to the eleven kinds of work"), Q1 copy ("23 occupation groups"), Q2/Q3/CARD copy ("legal and policy work", "policy or research role", "management role").

Evidence (VERIFIED):
- 23 occupation groups exist: transition_network/common.py lines 57 to 68 (SOC_MAJOR) and analyses.py line 170 (SOC_GROUPS_OF = 23).
- No eleven-way taxonomy exists in code: grep -i "eleven" over *.py/*.html/*.json finds only company names and a number-word array in the template; the archetypes are 15 plus Other (archetype_spec.py lines 24 to 57); industry L1 has 17 codes; functional_cluster on career_steps is SOC-major-coded and 96 % null.
- "Legal, Policy & Research" and "Managers & Operations Leaders" are archetype labels (archetype_spec.py lines 37, 47), and the journey's 5,088 and 1,021 are only reachable on the archetype table (B3). The site-concept section 8 bans "the internal archetype vocabulary, anywhere on screen".

Recommendation (M): decide and materialize the coarse grain (a mapping from role_canonical or SOC major to the eleven kinds, with display labels and the first-person descriptions as a reference table) before any cell counts are quoted; re-run every copy number at the chosen grain.

### B5. Title grain is real but mostly below the bar, and titles are not display-ready on the spine or panel

Severity: SIGNIFICANT. Journey steps affected: D3, P2 (Ways in), RARE, TAILSTATE, LAD4, SORT (rarest that clears ten).

Evidence (VERIFIED queries on cohorts/panel.parquet, hum_l1_any AND valid_cohort):
- At career_age 10: 81,577 distinct role_canonical values; 1,900 have >= 10 persons; 103,125 of 201,965 titled persons (51 %) are inside titles below ten.
- Ways in to SOC 23 (Legal) at year 10, titles held at career_age 1: 1,195 distinct titles, 23 shown at >= 10, 1,497 of 2,593 persons (58 %) suppressed.
- Origin title at year 1 crossed with SOC major at year 10: 60,263 cells, 1,228 clear ten. Origin SOC major x destination SOC major: 503 cells, 333 clear ten, 94,327 persons covered.
- role_canonical is a compressed key ('grantsmanager', 'grantwriter'); role_display ('Grants Manager', 'Grant Writer') exists only on normalized/career_steps.parquet and is 1:1 with role_canonical (0 roles with more than one display, query). paths/steps.parquet, cohorts/panel.parquet and transition_network/role_nodes_analyzed.parquet carry only the key (label == node).

Recommendation (S for the lookup, M for the export): carry role_display onto the spine/panel or ship a role dictionary; materialize per-view shown/suppressed/people-in-suppressed so TAILSTATE and STIPPLE are read from data rather than computed on the client.

### B6. Credentials exist in the raw data but only as person-level domain flags after normalization; nothing names a credential with a count

Severity: SIGNIFICANT. Journey steps affected: P4 ("Certifications and licences, named, with counts"), NCRED, ACT1, TAKE block 4, step 13.

Evidence (VERIFIED):
- parsed/certifications: 1,673,732 rows; 1,673,396 have a provider string (subtitle); 1,249,976 have a parsable "Issued Mon YYYY" in meta. Top raw titles show the same credential under several strings ("Project Management Professional (PMP)" 9,189 and "... (PMP)®" 3,738).
- cert_clean/run_cert.py (lines 1 to 14) emits only cert_domain.parquet (value -> one of 18 domains) and certifications_person.parquet (n_certs, domain list, has_* booleans). No canonical credential id, no provider, no date, no join to career year or destination.
- No downstream code reads certifications_person (grep). The cert target is outside `make refresh` and check_freshness.

Recommendation (M): a cert canonicalization (title + provider -> credential id, with display name), a dated credential-by-person table, and a per-destination credential panel under the ten-person bar. ACT1's "next enrolment date" is outside the sample by design and must come from a hand-maintained provider table.

### B7. US state and institution facets exist upstream but are not carried onto the substrate the aggregates read

Severity: SIGNIFICANT. Journey steps affected: P5, NGEO, GEO (rule 7.9), LAD2 (rung 1: drop institution type or US state), TAKE block 4 (employers in this state), ACT3.

Evidence (VERIFIED):
- normalized/career_steps.location_us_state is populated on 51.6 % of 10,800,787 step rows (this is the source of the journey's 51.6 %, which is a row rate, not a person rate: 1,521,073 of 1,999,974 persons have a state on at least one step; 233,647 of 293,808 L1 persons).
- paths/steps.parquet carries only `location` (raw string); cohorts/panel.parquet carries no location at all; the portal never reads location_us_state.
- education_person carries inst_control_label (public 867,652; private_nonprofit 438,724; private_forprofit 39,730; null 653,868), inst_carnegie_label, inst_state; institution coverage 67.3 % (normalized/_institution_meta_manifest.json). Nothing in portal reads these.
- Employer naming: company_canonical_id is non-null on 100 % of steps (it falls back to a raw key), company_id_canonical on 73.7 %. The portal names an employer only at n >= 10 within a major's first five years (analyses.py lines 355 to 422); english names 18, philrel names 2.

Recommendation (S to M): add location_us_state, inst_control_label and inst_carnegie_label to the journey substrate and restate the denominator per state as rule 7.9 requires. Expect named-employer cells to be sparse: 8,641 of english's 9,314 employers are singletons.

### B8. Panel P1 ("what this work involved, composited from how people described it") has no pipeline stage

Severity: SIGNIFICANT. Journey steps affected: P1, LIMITS, narrative step 9.

Evidence (VERIFIED): career_steps.description is non-empty on 50.8 % of steps. No module summarises, clusters or composites descriptions per destination (career_clean/se_description.py is a self-employment classifier; industry/ classifies companies). The site-concept section 8 forbids verbatim quotation, so this needs a generative or extractive stage plus editorial review, which does not exist.

Recommendation (L): scope it as a separate LLM stage with a review gate, keyed on the destination grain chosen in B4; until then P1 falls back to the SOC/O*NET label text.

### B9. The export carries no release identity; the schema documents are stale; deep-link staleness cannot be checked

Severity: SIGNIFICANT. Journey steps affected: AR5 -> STALE, CARD (link back to this exact state), TAKE block 7 (return code), rule 7.7.

Evidence (VERIFIED):
- portal_data.json carries `generated` (calendar date), `snapshot_date`, `min_support` and prose notes (run_portal_data.py lines 90 to 95) but no release id, code version, input hash or gate result; grep for schema_version/release_id/version across portal/, scripts/, paths/build_spine.py, cohorts/build_panel.py, archetypes/run_all.py finds nothing.
- portal_data.json and share/*.html are gitignored (.gitignore), so no history of releases exists; the mtime-keyed substrate cache (build.py lines 41 to 59) is the only provenance of inputs and it is also gitignored.
- share/system-schema.mmd lines 96 and 127 and share/System-Schema.html lines 432 and 542 still state "n >= 40"; the bar has been 10 since 2026-07-13 (portal/common.py lines 126 to 131). The erDiagram there is labelled PROPOSAL and includes release_id, gate_results and published, none of which exist.
- STALE ("does the linked cell still clear ten people in this build") needs the build id in the URL and a lookup of that cell in the current build; nothing provides either.

Recommendation (S): stamp every export with a release id (snapshot id from the raw file names, build timestamp, git commit, the parameter block from portal/_manifest.json) and keep exports as immutable versioned files; fix the two schema pages or delete them.

### B10. A refresh after a new snapshot is four separate drivers, two of them outside every checker, and no consistency check exists between outputs

Severity: SIGNIFICANT. Journey steps affected: all (the site's numbers must move together).

Evidence (VERIFIED):
- Chain: `make parse` (parse_linkedin.py, about 20 min per Makefile line 8) -> `make normalize` (build_normalized.py --sections all, "hours", Makefile line 11; it reads the LLM-jury mapping parquets as inputs and applies the pooled columns, lines 1076 to 1096) -> `make cert` (separate, Makefile line 52) -> `make refresh` (17 stages, scripts/refresh_downstream.sh lines 38 to 64; measured 2026-09-02 16:22:14 to 16:32:04 in refresh.log, about 10 minutes) -> `make portal` is inside refresh. The jury runs that feed normalize (edu_clean.run_cip_jury, career_clean.run_soc_jury, industry LLM cache) are fired by hand or by scripts/overnight_followups.sh (about 21 h per its comment) and are keyed on strings, so new strings in a new snapshot fall to deterministic coverage until re-fired.
- check_freshness.py (lines 24 to 52) covers 14 stages by mtime only; it does not cover cert, enrichment, the education-side pooled manifests, cohorts/profiles or any analysis JSON. It reports "ok" today while transition_network/sequences.json, temporal.json, trajectory_features.parquet (2026-06-04) and cohorts/typologies.json, generational.json, age_profiles.parquet (2026-07-22) predate the 2026-09-02 spine.
- No test compares the share HTML to the JSON it embeds, or the JSON cells to the substrate they came from; portal_tests (lines 20 to 140) checks join integrity, window discipline and suppression on a fresh substrate, which is the right kind of check but only for this product.

Recommendation (M): one `make release` that runs the whole chain, writes a release manifest, and runs a cross-output consistency suite (every cell n >= bar, sums per view equal the population, shown + suppressed = total, HTML embeds the current JSON, headline numbers equal their queries).

### B11. The wage door can be fed a SOC code but the pipeline has no BLS series reference and 6-digit coverage is thin

Severity: MINOR to SIGNIFICANT. Journey steps affected: WAGE.

Evidence (VERIFIED): at career_age 10 among L1 persons in cohorts/panel, 147,575 of 236,421 have a 2-digit soc_major and 54,816 an occupation_code (6-digit). reference/ holds soc_status (job zones) and bls_unemployment only; no OES/OEWS series identifiers. The SOC major label table (transition_network/common.py lines 57 to 68) has no code-to-series field.

Recommendation (S): a small hand-built reference table (SOC major code -> BLS OEWS series id and year) exported alongside the destination grain.

### B12. Large analysis-only dead ends, and large parts of the existing export the journey does not use

Severity: MINOR (capacity, not correctness).

Evidence (VERIFIED grep and ls):
- Dead ends: archetypes/results/* (8.3M person-years, 225 MB, read by nothing outside archetypes/); transition_network role/occupation/soc_major edges, backbone and communities (only role_nodes_analyzed and occupation_nodes_analyzed are consumed); cohorts/profiles.parquet; certifications_person.parquet; enrichment.json; sequences/temporal/typologies/trajectory_features (stale).
- Unused by the journey inside portal_data.json: pillars, launchboard.stability (mover classes), choices, curve (seniority by horizon), diversity, employer size buckets, kpi (breadth, distinctive, up_share, dwell). The journey's section 8 refuses scores and rankings, so pillars and the mover-class comparisons are not just unused but excluded.
- Journey-relevant things that exist only on the fly: the portal substrate (membership + panel, cached parquet under portal/results/_cache, gitignored); every year-1 to year-10 corridor (computable from cohorts/panel in seconds, as my queries show, but not materialized); TAILSTATE triples; state and institution denominators.

Recommendation (S): mark the dead ends explicitly as analysis-only in the refresh driver, and route the journey's substrate through cohorts/panel plus paths/transitions rather than through the portal cache.

### B13. The "one in eight" copy is true for one of the five exported majors

Severity: MINOR (copy), but it is a supply fact.

Evidence (VERIFIED from portal_data.json): top fan cell share, year 10: english Education 0.1271; history Management 0.1302; philrel Community & Social Service 0.1210; commmedia Management 0.1531; arts Arts/Design/Media 0.2379; baseline Management 0.1452. The BEST copy ("the largest single destination for any one field of study was about one in eight") and ONELINE need a per-field number from the export.

### B14. The journey's worked example (Classics to grants management) sits below the bar at every step in the data

Severity: MINOR (example choice), SIGNIFICANT if the example is used for design QA.

Evidence (VERIFIED queries): CIP 16.12 (Classics) is coded on 276 education rows / 247 persons (a further 1,564 rows have "classic" in field_raw and no CIP code); 179 of those persons appear in cohorts/panel at career_age 10; 0 of them hold a role containing "grant". Grants roles at career_age 10 among L1 valid_cohort: grantsmanager 33, grantwriter 29, coordinatorgrants 11, then single digits. Classics is not one of the portal's five majors.

Recommendation (S): pick design examples from cells that clear ten in the export, and keep the Classics case as the LAD1 test case it already is.

## 4. Capacity gaps

What the journey asks for that the pipeline cannot supply in a servable form today:

| Journey need | Nearest existing capacity | Gap | Effort |
|---|---|---|---|
| Q0 pooled all-humanities destination field at year 10 | per-major fans in portal_data.json; cohorts/panel can be aggregated | no pooled cohort in the export; humanities definition unfixed (five candidate counts in B3) | S once the definition is fixed |
| Q1 forward fan from a field of study | five CIP-2 majors on the graduation axis | other fields (Languages 19,455 L1 persons, Liberal Arts 66,272, Area Studies 9,992, Theology, Classics) absent; wrong axis (B2) | M |
| Q1 forward fan from a starting occupation or an orientation | none | requires y1 origin x y10 destination cube (computable from cohorts/panel: 503 SOC-major cells, 333 clear ten) | M |
| Q2 corridors, Q3 backward origins | none | same cube read both ways; title-grain origins mostly suppressed (B5) | M |
| Eleven kinds of work | none (23 SOC majors, 15+1 archetypes, 17 industry L1) | taxonomy and mapping do not exist (B4) | M |
| P1 what the work involved | career_steps.description on 50.8 % of steps | no compositing stage (B8) | L |
| P2 ways in, named titles with counts and elapsed years | cohorts/panel role_canonical by career_age; role_display only on career_steps | not materialized; heavy suppression (B5) | M |
| P3 what they studied | education, education_person | joinable; not exported per destination | S |
| P4 credentials named with counts | parsed certifications (title, provider, date) | no canonical credential, no per-destination table (B6) | M |
| P5 employers and US state | career_steps.company_canonical_id, location_us_state | not on the spine or panel; not in export (B7) | S to M |
| Like-me filters: institution type, US state, field of study | education_person inst_*, career_steps state, education cip4 | not on the substrate; no denominator restatement | S |
| LAD5 horizon pooling (years 8 to 12) | cohorts/panel | not materialized | S |
| SORT distinctive vs all graduates | portal rr per SOC-major cell vs baseline | baseline is "any CIP-coded bachelor" on the graduation axis only | S |
| SORT rarest that clears ten; TAILSTATE; STIPPLE | none | shown/suppressed/people-in-suppressed per view not materialized | S |
| METER support of the named cell in this exact state | portal cells carry n | only for portal's cells | with the cube |
| NGRAD graduate degree as destination, ACT2 count and career year | launchboard grad_track (within 5 years of graduation, per major); transitions kind education_entry 14,471 | grad start_year present on 24.1 % of grad-level education rows (177,114 of 736,264, query); no career-year distribution | M |
| WAGE SOC code and BLS series | soc_major on 62 % of L1 year-10 person-years | no BLS series reference (B11) | S |
| STALE deep-link check, CARD link back to exact state | none | no release id (B9) | S |
| Headline numbers with provenance (rule 7.1) | none | B3 | S to M |
| CLASSAGG, RET (class aggregate, device memory) | none, out of pipeline scope | site-side | n/a |

Pipeline capacity the journey does not use: pillars, launchboard mover-class stability, choices (internship, military, service year, self-employment, double major), seniority curve, diversity indices, employer size buckets, transition_network communities and backbones, archetypes occupancy and flows, cohort scarring/survival/generational analyses, enrichment.json. The refusals in user-journey.md section 8 and site-concept section 8 exclude the pillars, archetype labels and any ranking, so these are not merely unused but unusable on the site.

## 5. What I could not verify, and why

- Where the journey's 486,000 / 407,000 / 638,368 / 355,437 / 13,933 / 5,088 / 1,021 / 2,682 figures were computed. The journey attributes them to docs/design/2026-09-01-product-maps.md and docs/NARRATIVE_FRAMING_PLAN.md, which the silo forbids. I tested the definitions the code exposes (section 3, B3) and none reproduces them; a definition I did not think of may.
- Whether the LLM-jury mappings (field_cip_jury, role_soc_jury, degree_level_jury, industry cache) would be re-fired on a new snapshot, and how long that takes. I read the drivers (overnight_followups.sh says about 21 h for one tranche) but did not run anything.
- Runtime of `make parse` and `make normalize`; I quote the Makefile's own estimates (about 20 min; hours).
- The launchboard.py comment (lines 42 to 44) that about 95 % of post-bachelor grad rows carry a start_year; my query on all grad-level rows gives 24.1 %. The comment may refer to a narrower population; I did not reproduce its population.
- Whether portal_data.json is byte-reproducible across days (it embeds `generated: date.today()`, run_portal_data.py line 91); I did not rebuild it.
- The share/deprecated prototype and share/README.txt were not opened (non-code text under the silo rule), so I cannot say whether an earlier prototype exported anything closer to the journey.

## 6. Top 5

1. B1. No data contract for the journey exists; the only UI export (portal_data.json, five majors, 23 SOC groups at year 10, gitignored) has none of the journey's primitives: no pooled field, no origin-to-destination cells, no title grain, no credentials, no state.
2. B2. The export is on the graduation-anchor axis, which keeps about a fifth of people (english 6,831 of 38,450; five majors total 22,297 at year 10), while the journey is written on the career-entry axis, where the only substrate (cohorts/panel, 205,032 L1 valid-cohort persons at career year 10) has no export, suppression or window rule.
3. B3. None of the journey's "measured" population and tail numbers can be re-derived from a materialized artifact; the closest current-build values differ (5,395 or 2,821 for "5,088"), and no export pins any number to a build, grain or cohort definition.
4. B4 and B5. The destination grain is unsettled (23 SOC groups exist; the "eleven kinds of work" do not; the copy's numbers come from the banned archetype labels) and the title grain is 51 to 58 percent suppressed at ten with display names living only on career_steps.
5. B9 and B10. No release id, no versioned exports, stale schema pages still saying n >= 40, and a four-driver refresh (parse, normalize, cert, refresh) with an mtime-only freshness check and no cross-output consistency test.
