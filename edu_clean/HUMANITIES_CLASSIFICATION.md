# NHA Field-of-Study Classification (humanities hierarchy)

A deterministic, CIP-2020-grounded classifier (`edu_clean/humanities.py`) that
labels a degree program with **three nested boolean flags** and a short field
group, given the `cip_code` produced by the `edu_clean` field-resolution pipeline.

```
L1  is_humanities                      strictest: the humanities, narrowly defined
L2  is_humanistic_social_science_incl  L1 + humanistic/interpretive social sciences
L3  is_liberal_arts                    L2 + math & natural sciences; minus
                                       professional/vocational/applied programs
```

The levels are **nested and enforced**: `L1 => L2 => L3`. A program is assigned
the innermost level it qualifies for (`nha_level` 1/2/3, or 0 = none), and the
booleans are derived from it, so the nesting cannot be violated. The invariant is
asserted on every CIP 2020 code by `humanities_tests.py`.

## How it works

CIP is hierarchical: 2-digit family -> 4-digit -> 6-digit. The classifier is a
**2-digit-series base map** (`FAMILY_MAP`) plus **explicit 4-/6-digit overrides**
(`OVERRIDES`). Resolution is longest-prefix-wins: a 6-digit override beats a
4-digit one beats the family default. Input may be bare (`54.0101`) or
`cip:`-prefixed (`cip:54.0101`). All groupings were verified against
`reference/cip_codes.csv` (CIP 2020, 2,318 distinct codes) with duckdb.

## Sources

- **HIP** — Humanities Indicators Project, American Academy of Arts & Sciences,
  "The Definition of the 'Humanities'":
  https://www.amacad.org/humanities-indicators/scope-of-humanities
- **ACLS** — American Council of Learned Societies member societies
  ("humanities and interpretive social sciences"):
  https://www.acls.org/acls-member-societies/
- **PBK** — Phi Beta Kappa membership stipulations:
  https://www.pbk.org/membership/membership-stipulations
- **CIP 2020** — NCES Classification of Instructional Programs:
  https://nces.ed.gov/ipeds/cipcode/

## Level 1 — Humanities (HIP core + methodology additions)

| CIP | discipline | source |
|---|---|---|
| 54 | History | HIP core |
| 23 | English & Literature | HIP core |
| 16 | Foreign Languages, Literatures & Linguistics (incl. 16.12 Classics) | HIP core |
| 38 | Philosophy & Religious Studies (secular) | HIP core |
| 05 | Area, Ethnic, Cultural, Gender & Group Studies | HIP core |
| 24 | Liberal Arts & Humanities / General Studies | HIP (general humanities) |
| 39 | Theology & Religious Vocations | **methodology add** (theology/seminary) |
| 50 | Visual & Performing Arts (all of it) | **methodology add** (HIP counts only the *academic study* of the arts; the project owner adds all fine & performing arts) |
| 30.12 | Historic Preservation & Conservation | HIP "selected interdisciplinary" |
| 30.13 | Medieval & Renaissance Studies | HIP |
| 30.21 | Holocaust & Related Studies | HIP |
| 30.22 | Classical & Ancient Studies | HIP |
| 30.23 | Intercultural/Multicultural & Diversity Studies | HIP |
| 30.26 | Cultural Studies / Critical Theory | HIP |

## Level 2 — + Humanistic Social Sciences (ACLS)

The ACLS is the federation of "the humanities and **interpretive social
sciences**." Confirmed member societies place the following at L2:

| CIP | discipline | ACLS member society |
|---|---|---|
| 45.11 | Sociology | American Sociological Association |
| 45.02 | Anthropology | American Anthropological Association |
| 45.03 | Archeology | Archaeological Institute of America |
| 45.10 | Political Science & Government | American Political Science Association |
| 45.07 | Geography & Cartography | American Association of Geographers |
| 09 (whole family) | Communication, Journalism & Media | National Communication Association; Society for Cinema & Media Studies |

Plus the methodology's named interpretive branches of otherwise quantitative /
professional fields:

| CIP | discipline | source |
|---|---|---|
| 45.09 | International Relations / National Security (international affairs) | methodology |
| 45.05 | Demography & Population Studies (historical demography) | methodology |
| 42.21 | Environmental Psychology | methodology (only this psych branch) |
| 25 (family) | Library & Information Science | methodology |
| 30.14 | Museology / Museum Studies | methodology |
| 30.15 | Science, Technology & Society (STS) | methodology / ACLS-adjacent |
| 30.20 | International / Global Studies | methodology (international affairs) |
| 30.05 | Peace Studies & Conflict Resolution | methodology |
| 30.28 | Dispute Resolution | methodology (peace-studies adjacent) |
| 45.01 | Social Sciences, General | family default (ACLS-aligned) |
| 45.13 / 45.14 / 45.99 | Sociology & Anthropology / Rural Sociology / other | family default |

## Level 3 — Liberal Arts (PBK)

PBK defines the liberal arts and sciences as "the traditional disciplines of the
natural sciences, mathematics, social sciences, and humanities," and explicitly
excludes applied/pre-professional/vocational coursework. L3 therefore adds
mathematics and the natural sciences to everything in L1+L2:

| CIP | discipline | source |
|---|---|---|
| 27 | Mathematics & Statistics | PBK: mathematics |
| 26 | Biological & Biomedical Sciences | PBK: natural sciences |
| 40 | Physical Sciences | PBK: natural sciences |
| 03 | Natural Resources & Conservation (environmental science) | PBK: natural sciences |
| 42 (family) | Psychology, General & most branches | PBK: a liberal-art social science (L3); only 42.21 lifts to L2 |
| 45.06 | Economics | quantitative social science: L3, not an ACLS humanistic field |
| 45.04 / 45.12 | Criminology / Urban Studies | applied social science: L3 |
| 30 (family default) | Multi/Interdisciplinary Studies | L3, with many sub-codes overridden up/down |
| 30.01/30.06/30.08/30.10/30.18/30.19/30.24/30.25/30.27/30.30/30.32 | interdisciplinary natural-science / math / cognitive science | PBK |

## Excluded (all three flags false) — professional / vocational / applied

Per PBK's exclusion of applied/pre-professional/vocational programs:
01 Agriculture, 04 Architecture, 10 Communications technologies, 11 Computer &
information sciences, 12 Personal/culinary services, 13 Education (pedagogy),
14 Engineering, 15 Engineering technologies, 19 Family & consumer sciences,
21 Technology education, 22 Legal professions, 28/29 Military, 31 Parks &
recreation, 32 Remedial, 33 Citizenship, 34 Health knowledge, 35 Social skills,
36 Leisure, 37 Self-improvement, 41 Science technicians, 43 Homeland security/
law enforcement, 44 Public administration & social services, 46 Construction,
47 Mechanic/repair, 48 Precision production, 49 Transportation, 51 Health
professions, 52 Business/management/marketing, 53 HS diplomas, 60 Residencies.
Also the within-family overrides 30.16 (Accounting & CS), 30.31 (HCI), and 50.10
(Arts/Entertainment Management — a business program inside the arts family).

## Deviations from the base schemas (judgment calls)

1. **All visual & performing arts at L1.** HIP counts only the *academic study*
   of the arts (art history, musicology) and excludes performance/technique. The
   project owner's methodology explicitly adds fine & performing arts wholesale,
   so the entire CIP 50 family is L1 (Fine & Performing Arts), except 50.10
   (Arts/Entertainment Management), which is a business program -> excluded.
2. **Theology at L1.** HIP includes only *secular* religious studies (CIP 38.02)
   and excludes theology/ministry; the methodology adds theology/seminary, so
   CIP 39 is L1.
3. **Communication family (09) entirely at L2.** ACLS includes communication and
   cinema/media studies; the methodology lists communication at both L2 and L3.
   We place the whole family at L2 (the strictest qualifying level), which by
   nesting also makes it L3. Journalism/PR/advertising sub-codes are kept with
   the family rather than split out as vocational, matching ACLS's broad
   communication scope.
4. **Economics (45.06) is L3, not L2.** Economics has no ACLS humanistic society
   in the methodology's list and is quantitative; it is a liberal art but not a
   humanistic social science.
5. **Psychology (42) is L3 by default**, with only the single named interpretive
   branch — Environmental Psychology (42.21) — lifted to L2, exactly as the
   methodology specifies. (General/clinical/experimental psychology stay L3.)
6. **Library & Information Science (CIP 25) at L2.** The methodology names LIS as
   an L2 add; we apply it to the whole small family.
7. **Multi/interdisciplinary (30) handled per-subcode.** The family default is L3
   (most 30.xx are interdisciplinary sciences), with explicit overrides pulling
   the humanities sub-codes up to L1, the social-science/STS/peace/museum
   sub-codes to L2, and the two applied sub-codes (30.16, 30.31) out entirely.

## Coverage on `normalized/education.parquet`

**Current numbers (58.8% CIP coverage build).** Single source of truth:
`edu_clean/results/tier_counts.json`, produced by
`uv run python -m edu_clean.run_tier_counts`. Do not hand-edit that JSON or this
table separately from it — re-run the driver and let it overwrite both the file
and (by copy) this table.

- Total education rows: **3,577,659**
- Rows with a resolved CIP code (deterministic backbone): **2,104,692 (58.8%)**.
- Rows with a CIP2 family under **pooled** coverage (deterministic + calibrated
  CIP jury, `cip2_pooled`; see `edu_clean/apply_cip_pooled.py`): **2,466,955 (69.0%)**.

Two nested tier layers, both re-derived by `run_tier_counts`. The **deterministic**
layer keys on the 6-digit `nha_level` (override-precise); the **pooled** layer keys
on `nha_level_pooled` (6-digit where present, else the CIP-jury family). The jury
passed a clean membership bias check (`portal/cip_bias_check.py`: no material
composition drift) and the deterministic backbone is preserved byte-for-byte.

| level | records (det) | persons (det) | records (pooled) | persons (pooled) |
|---|---|---|---|---|
| L1 humanities | 240,277 | 210,495 | **287,071** | **246,482** |
| L2 humanities + humanistic social sci (nested) | 415,908 | 358,675 | **498,786** | **421,082** |
| L3 liberal arts (nested) | 689,836 | 579,325 | **802,277** | **658,824** |

Note the pooled person-grain population (246,482 L1) also resolves the prior
person-table undercount: `education_person` now carries any-degree flags
(`hum_l1_any`/`hum_l2_any`/`hum_l3_any`) so a History-BA-then-MBA person is counted
as humanities (the terminal `nha_level` had dropped ~21% of true L1 persons).

See `edu_clean/results/tier_counts.json` (`tiers` + `tiers_pooled`) for the
coverage denominators, the input-parquet content fingerprint, and the generation
date these were computed at. **These counts are coverage-dependent** — they moved ~30% when CIP coverage
was ratcheted from 49.1% to 58.8%, and will move again with future CIP
ratchets, so always cite them "as of the `<generated>` build" rather than as
fixed facts. (Plan 2 in `COVERAGE_PLAN.md` — graduation-anchor recovery — does
not change these tier counts; it moves the *anchored/windowed cohort* sizes
computed downstream of them.)

### Superseded — original table at 49.1% CIP coverage (kept for provenance)

The table below was computed when only 49.1% of education rows carried a
resolved CIP code (1,756,585 of 3,577,659). It **no longer reflects the
committed `normalized/education.parquet`** and must not be cited as current;
it is kept only so the drift is auditable. The 58.8%-coverage numbers above
supersede it in every respect.

Computed by joining `reference/cip_humanities.parquet` on `cip_code`
(`uv run python -m edu_clean.humanities coverage`), at 49.1% CIP coverage:

| level | rows | % of coded | % of all |
|---|---|---|---|
| L1 humanities | 186,018 | 10.6% | 5.2% |
| L2 humanities + humanistic social sci (nested) | 341,113 | 19.4% | 9.5% |
| L3 liberal arts (nested) | 597,144 | 34.0% | 16.7% |

Largest field groups among coded rows, at the time of the 49.1%-coverage
computation: Other (professional/vocational) 1.16M, Psychology 93k,
Communication & Media 78k, Humanistic Social Science 74k, Fine & Performing
Arts 66k, Biological Sciences 58k, Liberal Arts & Humanities 49k, Economics
36k, Physical Sciences 26k, English & Literature 25k, Math & Statistics 23k,
History 20k. (Not re-verified at 58.8% coverage; kept for provenance only.)

## Limitations

- **Bounded by upstream CIP coverage.** Only 49.1% of education rows carry a
  resolved `cip_code` (see `edu_clean/FINDINGS.md`); the uncoded tail (raw / typo
  -clustered field strings) is unclassifiable until those are coded.
- **Granularity.** The upstream resolver often lands on a 2- or 4-digit code
  (e.g. `52.02`, `45.06`) rather than a 6-digit code; classification is correct
  at whatever granularity it receives, but the sub-code overrides only fire when
  the resolver produced a specific enough code.
- **Communication at L2 (not split L2/L3).** Following ACLS, the whole 09 family
  is treated as humanistic social science; a stricter reading might place
  journalism/PR/advertising at L3 only. This is a deliberate, documented choice.
- **The arts and theology additions are the project owner's, not HIP's.** L1 here
  is intentionally broader than the HIP humanities count; comparisons to
  published HIP degree shares should use the HIP-exact subset (exclude CIP 39 and
  CIP 50 performance/technique sub-codes).
- The schema reflects the *named* disciplines in the three sources; a handful of
  rare interdisciplinary sub-codes are placed by closest analogy and flagged in
  code comments.
