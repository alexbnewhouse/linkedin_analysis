# Pipeline entry points. See PIPELINE.md for the DAG and conventions.
UV := uv run

.PHONY: parse normalize normalize-fast normalize-education normalize-career \
        industry archetypes portal test test-data lint cert \
        paths network seniority cohorts refresh check-freshness

parse:            ## raw JSONL -> parsed/ star schema (~20 min)
	$(UV) python parse_linkedin.py

normalize:        ## full rebuild incl. value mappings (hours)
	$(UV) --with numpy python build_normalized.py --sections all

normalize-fast:   ## row-level tables only, reuse existing mappings (minutes)
	$(UV) --with numpy python build_normalized.py --sections all --skip-mappings

normalize-education:
	$(UV) --with numpy python build_normalized.py --sections education --skip-mappings

normalize-career:
	$(UV) --with numpy python build_normalized.py --sections career --skip-mappings

industry:
	$(UV) python -m industry.build_industry --propagate

archetypes:      ## reads career_steps, step_industry, paths/*, cohorts/panel -- run after cohorts
	$(UV) python -m archetypes.run_all

paths:            ## the career spine (steps + transitions); second pass after `seniority`
	$(UV) --with numpy python -m paths.build_spine --force

network:          ## transition networks on every axis + analysis (backbone, communities)
	$(UV) --group graph python -m transition_network.build_network role
	$(UV) --group graph python -m transition_network.analyze role
	$(UV) --group graph python -m transition_network.build_network occupation
	$(UV) --group graph python -m transition_network.analyze occupation
	$(UV) --group graph python -m transition_network.build_network soc_major
	$(UV) --group graph python -m transition_network.analyze soc_major

seniority:        ## revealed-seniority scores from the analyzed role network
	$(UV) python -m paths.seniority

cohorts:
	$(UV) --group cohort python -m cohorts.build_panel --force

refresh:          ## every downstream layer, in true dependency order (see scripts/refresh_downstream.sh)
	bash scripts/refresh_downstream.sh

check-freshness:  ## exit 1 if any downstream output is older than its inputs
	$(UV) python scripts/check_freshness.py

cert:             ## certifications skills axis (audit R6)
	$(UV) python -m cert_clean.run_cert

portal:
	$(UV) python -m portal.run_portal_data
	$(UV) python -m portal.run_share_build

test:             ## data-independent logic suites (no built parquet needed)
	$(UV) python -m edu_clean.humanities_tests
	$(UV) python -m edu_clean.dlevel_tests
	$(UV) python -m career_clean.se_tests
	$(UV) python -m career_clean.company_tests
	$(UV) python -m career_clean.soc_tests
	$(UV) python -m industry.tests
	$(UV) python -m archetypes.archetype_tests
	$(UV) python -m cert_clean.cert_tests
	$(UV) python -m paths.spine_tests
	$(UV) --with numpy python normalization_regression_checks.py

test-data:        ## suites that read built parquet
	$(UV) python -m career_clean.soc_data_checks
	$(UV) python -m edu_clean.tier_tests
	$(UV) python -m enrichment.enrichment_tests
	$(UV) python -m edu_clean.cip_tests
	$(UV) python -m portal.portal_tests
	$(UV) python -m cohorts.cohort_tests

lint:
	uvx ruff check .
