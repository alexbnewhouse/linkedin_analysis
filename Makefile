# Pipeline entry points. See PIPELINE.md for the DAG and conventions.
UV := uv run

.PHONY: parse normalize normalize-fast normalize-education normalize-career \
        industry archetypes portal test test-data lint cert

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

archetypes:
	$(UV) python -m archetypes.run_all

cert:             ## certifications skills axis (audit R6)
	$(UV) python -m cert_clean.run_cert

portal:
	$(UV) python -m portal.run_portal_data
	$(UV) python -m portal.run_share_build

test:             ## data-independent logic suites
	$(UV) python -m edu_clean.humanities_tests
	$(UV) python -m edu_clean.tier_tests
	$(UV) python -m edu_clean.dlevel_tests
	$(UV) python -m career_clean.se_tests
	$(UV) python -m industry.tests
	$(UV) python -m archetypes.archetype_tests
	$(UV) python -m enrichment.enrichment_tests
	$(UV) python -m cert_clean.cert_tests

test-data:        ## suites that read built parquet
	$(UV) python -m edu_clean.cip_tests
	$(UV) python -m career_clean.soc_tests
	$(UV) python -m portal.portal_tests
	$(UV) python -m cohorts.cohort_tests
	$(UV) python normalization_regression_checks.py

lint:
	uvx ruff check .
