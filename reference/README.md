# External reference taxonomies

Static lookup tables used as high-precision backbones by the entity-resolution
and network modules. None are derived from the LinkedIn data; all are public
government/standards datasets. Re-fetch from the sources below if updating.

| file | what | version | source | license | consumed by |
|---|---|---|---|---|---|
| `onet_alternate_titles.txt` | ~55k real-world job-title strings → O\*NET-SOC code | O\*NET-SOC **29.1** | [onetcenter.org/database](https://www.onetcenter.org/database.html) (Alternate Titles) | CC BY 4.0 (O\*NET) | `career_clean/occupation.py`, `transition_network/analyze.py` (labels) |
| `onet_occupation_data.txt` | ~1k SOC occupation titles + descriptions | O\*NET-SOC **29.1** | [onetcenter.org/database](https://www.onetcenter.org/database.html) (Occupation Data) | CC BY 4.0 (O\*NET) | `career_clean/occupation.py`, `transition_network` node labels + SOC major-group cross-tab |
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
