# External reference taxonomies

Static lookup tables used as high-precision backbones by the entity-resolution
and network modules. None are derived from the LinkedIn data; all are public
government/standards datasets. Re-fetch from the sources below if updating.

| file | what | version | source | license | consumed by |
|---|---|---|---|---|---|
| `onet_alternate_titles.txt` | ~55k real-world job-title strings → O\*NET-SOC code | O\*NET-SOC **29.1** | [onetcenter.org/database](https://www.onetcenter.org/database.html) (Alternate Titles) | CC BY 4.0 (O\*NET) | `career_clean/occupation.py`, `transition_network/analyze.py` (labels) |
| `onet_occupation_data.txt` | ~1k SOC occupation titles + descriptions | O\*NET-SOC **29.1** | [onetcenter.org/database](https://www.onetcenter.org/database.html) (Occupation Data) | CC BY 4.0 (O\*NET) | `career_clean/occupation.py`, `transition_network` node labels + SOC major-group cross-tab |
| `onet_skills.txt` | ~1k O\*NET-SOC occupations × 35 Basic/Cross-Functional skills (Importance + Level scales) | O\*NET-SOC **29.3** | [onetcenter.org/database](https://www.onetcenter.org/database.html) (Skills) | CC BY 4.0 (O\*NET) | `skill_breadth/onet_skills.py` (SOC × 35 skill matrix) |
| `onet_occupation_data_29_3.txt` | ~1k SOC occupation titles + descriptions | O\*NET-SOC **29.3** | [onetcenter.org/database](https://www.onetcenter.org/database.html) (Occupation Data) | CC BY 4.0 (O\*NET) | `skill_breadth/onet_skills.py` (occupation Title strings feeding the nearest-SOC title candidate pool; newer release than `onet_occupation_data.txt` to match `onet_skills.txt`'s taxonomy) |
| `onet_alternate_titles_29_3.txt` | ~55k real-world job-title strings → O\*NET-SOC code | O\*NET-SOC **29.3** | [onetcenter.org/database](https://www.onetcenter.org/database.html) (Alternate Titles) | CC BY 4.0 (O\*NET) | `skill_breadth/onet_skills.py` (nearest-SOC title candidate pool, title-vs-title matching; newer release than `onet_alternate_titles.txt`, kept separate rather than reused per the 2026-09-24 controller ruling) |
| `onet_2010_to_2019_crosswalk.csv` | O\*NET-SOC 2010 code → O\*NET-SOC 2019 code (1,164 rows, many-to-many) | O\*NET taxonomy **2010→2019** | [onetcenter.org/taxonomy/2019/walk](https://www.onetcenter.org/taxonomy/2019/walk.html) (`?fmt=csv`) -- note: `.../taxonomy/2019/soc/2010_to_2019_Crosswalk.csv` looks like the obvious URL but actually serves an HTML page or (with `?fmt=csv`) a *different* crosswalk (O\*NET-SOC 2019→2018 SOC); the real 2010→2019 file is at the `walk/` path used here | CC BY 4.0 (O\*NET) | `skill_breadth/onet_skills.py` (finds each 29.3-Skills.txt-missing SOC's O\*NET-SOC 2010 predecessor codes, to backfill from O\*NET 22.0) |
| `onet_skills_29_3_backfill_source.txt` | **derived**: O\*NET 22.0 `Skills.txt` Scale ID='IM' rows for the O\*NET-SOC 2010 codes needed to backfill every 2019-taxonomy SOC missing from 29.3 Skills.txt (104 missing; 27 backfillable, see the file's own header comment for the current split) | O\*NET-SOC **22.0** (source rows), backfilling **29.3** skills-table gaps | [onetcenter.org/database](https://www.onetcenter.org/database.html) (Skills, db_22_0_text release) | CC BY 4.0 (O\*NET) | `skill_breadth/onet_skills.py` (`build_crosswalk_backfill`: for each missing SOC, averages its crosswalk-mapped 2010 codes' Data Value per skill, joined to 29.3 skill names by Element ID, and inserts the result as that SOC's row before z-scoring; generalizes a 2026-09-24 round-2 fix that special-cased only 15-1252 "Software Developers" -- now one case of 27, including 13-2051 "Financial and Investment Analysts") |
| `cip_codes.csv` | 2,318 Classification of Instructional Programs codes | CIP **2020** | [nces.ed.gov/ipeds/cipcode](https://nces.ed.gov/ipeds/cipcode/) | US Gov public domain | `edu_clean/` field-of-study resolution |
| `Job_Zones.txt` | O\*NET-SOC → Job Zone (1-5) | O\*NET-SOC **29.1** | [onetcenter.org/database](https://www.onetcenter.org/database.html) (Job Zones) | CC BY 4.0 (O\*NET) | `reference/build_soc_status.py` |
| `Job_Zone_Reference.txt` | Job Zone → SVP range | O\*NET-SOC **29.1** | onetcenter.org/database (Job Zone Reference) | CC BY 4.0 (O\*NET) | `reference/build_soc_status.py` |
| `soc_status.parquet` | **derived**: 6-digit SOC → job_zone, svp_low/high, job_zone_norm | from the two above | `uv run python reference/build_soc_status.py` | — | seniority Layer B (`paths/build_spine.py`) |
| `cip_humanities.parquet` | **derived**: CIP 2020 code → NHA humanities hierarchy (`nha_level`, `is_humanities`/`is_humanistic_social_science_incl`/`is_liberal_arts`, `humanities_field_group`) | from `cip_codes.csv`; classification grounded in HIP / ACLS / PBK schemas | `uv run python -m edu_clean.humanities build` | — | `edu_clean/humanities.py`; join onto `normalized/education.parquet` on `cip_code` |
| `bls_unemployment.parquet` | US civilian unemployment rate by year (annual avg) | BLS LNS14000000, 1976-2025 | `uv run python reference/build_bls_unemployment.py` (hardcoded from [bls.gov/cps](https://www.bls.gov/cps/)) | US Gov public domain | cohort scarring instrument (`cohorts/`) |

The Job Zone (a preparation/experience ladder keyed directly on SOC) is the
cross-occupation **status anchor** (Layer B) in the fused seniority model — it lets
the model compare seniority/status across occupations even with no shared title.
ISEI/SIOPS (socioeconomic status, via an O\*NET-SOC→ISCO crosswalk) is the planned
secondary anchor (`SENIORITY_TRANSITIONS_PLAN.md` §2), not yet built.

Notes:
- O\*NET is **US/English**; non-English titles (~0.5% of the data) go uncoded.
  ESCO (multilingual, ISCO-linked) is the alternative if that tail matters.
- The CIP loaders skip remedial / IPEDS-invalid rows (see `edu_clean/FINDINGS.md`).
- SOC **major groups** (2-digit prefix labels) are hardcoded in
  `transition_network/analyze.py` (`SOC_MAJOR`), not stored here.
- `cip_humanities.parquet` implements the **NHA (National Humanities Alliance)
  3-level field-of-study classification**: L1 humanities (Humanities Indicators
  Project core + theology + fine/performing arts), L2 + humanistic social sciences
  (ACLS), L3 liberal arts (Phi Beta Kappa: + math & natural sciences, − applied/
  vocational). Levels are nested (L1⇒L2⇒L3). Full schema, source CIP groupings,
  deviations, and coverage stats: `edu_clean/HUMANITIES_CLASSIFICATION.md`.

## External benchmarks (validation/, 2026-09-22)

- `nces_bachelors_by_field.json`: NCES Digest Table 322.10 (d23) bachelor's degrees by field for six
  academic years, plus history bachelor's from Table 325.92 (d22). Every number verified against the
  live tables on the date in `verified_on`. Consumed by `validation/external_benchmarks.py`.
- `humanities_indicators.json`: Humanities Indicators figures (advanced-degree rate among humanities
  majors, 42% in 2021, ACS) with source URLs.
