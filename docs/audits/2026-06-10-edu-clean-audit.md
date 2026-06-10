# Audit: `edu_clean/` — raw-signal extraction & output usability

*Full-scale read-only audit, 2026-06-10. All numbers measured against the real data.*

**Scope inspected:** all 16 modules in `edu_clean/` + `FINDINGS.md`, `HUMANITIES_CLASSIFICATION.md`; producer `build_normalized.py`; raw `data/*.jsonl` (20K-profile sample), `parsed/education/*.parquet` (3,577,659 rows), `normalized/education.parquet` (3,577,659 rows / 1,999,974 profiles / 241 MB); downstream `cohorts/`, `paths/`, `transition_network/`, `industry/`, `exploration/`; plan docs.

**Baseline state (measured):** Raw education JSON has exactly 9 keys; the parser captures all of them — no raw fields are dropped. Canonicalization quality is genuinely strong: school slug 87.0% + crosswalk/typo → 88.1% with a slug; degree taxonomy 79.3% (taxonomy + abbrev); field CIP-coded 49.1% of all rows (60% of the 81.8% with a non-null field). Profile-level `educations_details` adds nothing (0 profiles have it without education rows). Description mining for field backfill is negligible (375 recoverable rows out of 121,942 field-empty-with-description) — correctly not pursued.

## Findings (prioritized)

### 1. The output is row-level only; downstream uses exactly one column of it — no person-level rollup exists (HIGH)
**Today:** `normalized/education.parquet` has exactly **one** downstream consumer: `cohorts/build_panel.py:64`, which computes `graduation_year = min(try_cast(end_year AS INT))` — re-casting VARCHAR and taking the *earliest* credential end (high school/associate count as "graduation"). Of 2.0M profiles, 406,834 (20.3%) have any usable graduation year but only 276,682 (13.8%) have a *bachelor-specific* one — the min() conflates them, which matters for the recession-scarring design in `COHORT_ANALYSIS_PLAN.md` §31. Meanwhile `cip_code`, `degree_canonical_id`, `school_slug`, and the entire NHA humanities classification have **zero** consumers (verified by grep across all modules). `CAREER_PATHS_PLAN.md` §6 ("link graduation → first job", education nodes Layer 6) is unimplemented.
**Left on the table:** the module's best signal (degree level, field/CIP, humanities flags) never reaches any analysis.
**Recommendation:** emit `normalized/education_person.parquet` (one row per profile): `highest_degree_level` (ordinal int), `highest_degree_year`, `bachelor_end_year`, `any_end_year_min/max`, terminal `cip_code` + `nha_level`/flags + `humanities_field_group`, `n_edu_rows`, primary `school_slug`. This makes the cohort join trivial and unlocks field-of-study/degree-level cuts in cohorts, paths, and the transition network.
**Effort: S** (one DuckDB query in `build_normalized.py`).

### 2. ~118K degree cells are actually fields of study; 86K can backfill empty field cells (HIGH)
**Today:** 532,523 rows (14.9%) have `degree_method='raw'`. Of these, **118,088 rows' degree values exact/token-match a CIP title** (top raw "degrees": "Business Administration and Management, General" 8,254; "Computer Science" 3,369; "Psychology" 2,318+1,949 — i.e., degree/field column swaps). **86,413** of them sit on rows whose `field` is empty.
**Left on the table:** ~2.4 pp of absolute CIP row coverage recoverable with the existing CIP matcher, at the same precision (it's the identical exact/token match, just applied to the other column).
**Recommendation:** add a cross-field pass: when `degree` fails the taxonomy but matches CIP, emit it as a field signal (`method='cip_from_degree'`) and mark the degree blank; also extract the subject from "Bachelor of X **in Y**" strings the taxonomy currently discards after level/type.
**Effort: S.**

### 3. CIP reference/loader gaps block ~130K+ rows of easy field coverage (HIGH)
Three concrete, measured holes in the 1,171,007 raw/typo field rows:
- **2-digit family titles are excluded by the loader** (`approach_a_rules.py:35`, `len(code) < 4`): **31,398 rows** are *verbatim* CIP family titles — e.g. "BUSINESS, MANAGEMENT, MARKETING, AND RELATED SUPPORT SERVICES" (15,729 + 6,586 typo-clustered), "COMPUTER AND INFORMATION SCIENCES…" (3,644). These are LinkedIn's own dropdown strings sourced from CIP.
- **`reference/cip_codes.csv` (2,319 rows) is missing the CIP-2020 30.70 Data Science / 30.71 Data Analytics series** (file stops at 30.33): "data science" 2,597, "business analytics" 2,490, "cybersecurity"/"cyber security" 3,341, "data analytics" 1,320, ≈ **9,861 rows** of high-growth modern fields stay raw.
- **Alias list is only 20 entries** while curation leverage is steep: top 200 distinct raw values cover 256,491 rows (21.9% of the raw/typo tail); top 1,000 cover 404,616 (34.6%). Obvious misses: "English" 15,204 (→23.01), "Business" 21,463, "Management" 11,463, "Geology" 2,078 (→40.0601 "Geology/Earth Science, General"), "Theatre/Theater" 2,571 (→50.05).
**Recommendation:** admit 2-digit families as `cip:NN` targets; refresh/complete the CIP 2020 extract; run one curation sitting over the top ~200–1,000 values feeding `FIELD_CIP_ALIASES` (this is exactly the ratchet `FINDINGS.md` prescribes — it just hasn't been turned). Combined with Finding 2 this lifts CIP row coverage from 49.1% to roughly 57–60% of all rows (~70–75% of rows with a field) at backbone precision.
**Effort: S–M.**

### 4. Output dtypes/format force downstream re-parsing (MEDIUM)
**Today:** `start_year`/`end_year` are VARCHAR despite being 100% integer-castable (914,101 / 773,546 non-null, 0 cast failures) — cohorts `try_cast`s on every read. `cip_code` is mixed granularity with no rollup columns: 880,874 rows 4-digit ("26.01") vs 875,711 6-digit ("14.1001") — any grouping analysis must string-slice. `degree_canonical_id` encodes level only as a string prefix ("bachelor:science") — no sortable ordinal (HS=1 … doctorate=7), so "highest degree" requires string parsing. NHA flags exist only in `reference/cip_humanities.parquet`; a consumer must know to build and join it.
**Recommendation:** store years as INT16; add `cip2`, `cip4` columns; add `degree_level` (ordinal int8) + `degree_type` columns; materialize `nha_level`/`humanities_field_group` onto education.parquet (the join is 100% — all 1,756,585 coded rows match the crosswalk).
**Effort: S.**

### 5. Nullish/junk and taxonomy tail gaps (LOW-MEDIUM)
- **15,231** raw field rows are pure numerics ("4.0" 3,695, "12" 2,365 — GPA/grade junk) plus "A" 1,917 — none in `NULLISH_NORMS`, so they become distinct `field_raw:*` ids.
- Degree taxonomy misses common level words: "Undergraduate" 1,410, "Graduate" 2,020, "Postgraduate Degree" 1,354, "Minor" 4,242, "Study Abroad" 2,211 — all map to raw.
- Non-English degree strings (Licenciatura/Ingeniero/etc.) are only 5,552 raw rows — correctly deprioritized.
- 25,100 exact within-profile duplicate rows (same school/degree/field/years, 0.7%) carry no dedup flag.
- 6,856 rows have end_year 2027–2034 (expected graduation) — legitimate, but there's no `in_progress` flag; cohorts silently drops them.
**Recommendation:** extend nullish/junk regex (`^[0-9.]+$`, single letters), add the 4–5 level keywords + `minor`/`study_abroad` as explicit degree categories, add an `is_dup` or dedupe in the person rollup, add `in_progress`.
**Effort: S.**

### 6. School canonical is LinkedIn-slug-only; no external reference linkage (LOW, optional)
**Today:** slug coverage is excellent (88.1%) and precision-1.0 per the gold set; the unresolved 10.7% is a long thin tail (top miss: "Long Island University, C.W. Post Campus" at 442 rows). But the canonical id is a LinkedIn-internal key with no IPEDS/OPEID/ROR crosswalk, no country/type metadata — blocking selectivity/institution-tier analyses promised nowhere yet, so this is genuinely optional.
**Effort: M–L** (only if an analysis needs it).

### 7. Evaluation base remains thin (LOW, already documented)
Gold set is 72 pairs (`gold.py`, 137 lines); `FINDINGS.md` already flags this. The coverage expansions in Findings 2–3 should be accompanied by ~50 new labeled pairs drawn from the newly mapped strata to keep the precision claim honest.
**Effort: S.**

## TL;DR — top 3 highest-leverage improvements
1. **Ship a person-level rollup table** (highest degree ordinal, bachelor/any graduation years, terminal CIP + humanities flags, school slug). Today the only downstream use of 3.58M cleaned rows is one `min(try_cast(end_year))` in cohorts, which conflates high-school and college graduation (276,682 of 406,834 grad-year profiles have a true bachelor year). Effort S, unlocks every planned education-aware analysis.
2. **Turn the field-coverage ratchet that the module itself designed:** admit 2-digit CIP families (31,398 verbatim-title rows), fix the CIP csv's missing 30.70/30.71 Data Science/Analytics series (~9.9K rows), backfill field from the 86,413 CIP-matching degree cells, and curate aliases for the top ~200 raw values (21.9% of the 1.17M-row tail). Combined: CIP coverage 49.1% → ~57–60% at backbone precision. Effort S–M.
3. **Fix output dtypes/keys:** INT16 years (currently VARCHAR, 100% castable), `cip2`/`cip4` rollup columns (granularity is split 880,874 four-digit vs 875,711 six-digit), a numeric `degree_level` ordinal, and materialized NHA humanities flags — eliminating all downstream casting/string-slicing/secret-join requirements. Effort S.
