# Sibling-methods port: running notes

**Date started:** 2026-09-22. **Spec:** `docs/superpowers/specs/2026-09-22-sibling-methods-port-design.md`.
**Branch:** `sibling-methods-port` (worktree). **Source project:** `~/from_scratch_humanities_workforce`.

Each piece records: pre-review verdict, before numbers, what was built, after numbers,
post-review verdict, and the decision (landed / propose-only / dropped). Numbers are measured,
with the query or command that produced them.

## Baseline (worktree, before any change)

Data: mutable parquet outputs copied from the main checkout (rsync, 2026-09-22); `parsed/`,
`data/` and the three vote caches are symlinks. `make test`: all suites pass (7 s).

Measured on `normalized/career_steps.parquet` (10,800,787 rows):

| axis | coverage |
|---|---|
| `occupation_code` (deterministic 6-digit) | 21.5% |
| `occupation_major_pooled` (det + jury) | 61.3% |
| `functional_cluster` | 4.3% |
| named `seniority_level` token | 30.4% |

Measured on `normalized/education.parquet` (3,577,659 rows): `degree_level_pooled` NULL on
647,041 rows; of those 265,995 carry a real `cip2_pooled` (not 53) and 95,563 persons would gain
their first degree level from an imputed-bachelor tier before any school gate. `field_raw`
contains a separator token (`and`, `/`, `,`, `&`, `;`, `double`, `minor`) on 44.5% of rows, an
upper bound that includes CIP titles.

Query: see `persons/` checks once built; until then the numbers above came from ad-hoc DuckDB
in the assessment session (2026-09-22).

## P1. External benchmarks

**Pre-review (fresh subagent, 2026-09-22): VERDICT: BUILD WITH CHANGES.** Verbatim core: "the 13%
history fallback is not defensible as specified. The Digest itself prints history bachelor's
separately: d22 Table 325.92 ... history's share is 19.6% (1990-91) ... 14.3% (2020-21). A flat 0.13
understates history by 10-35%"; "the plan is right to compare CORE6 against the NCES core proxy;
comparing L1 to it would print ratios of 1.3-1.4 and read as 'LinkedIn over-represents the
humanities', which is the opposite of the truth"; "the advanced-degree comparison is confounded by
cohort ... restricted to bachelor_end_year <= LAST_COMPLETE_YEAR - 10 (n = 21,597) the rate is 42.9%,
right on the HI figure". Changes adopted: printed history counts from Table 325.92 (verified by fetch;
2021-22 estimated at the 2020-21 share 0.143 and flagged); `l1_proxy` (core6 + theology 39 + visual
and performing arts 50) reported beside `core6`; advanced-degree primary line restricted to cohorts
<= 2015 with the all-persons line secondary; education fingerprint and stated biases in the output.

**Sources verified 2026-09-22 by fetch:** Digest d23 Table 322.10 (all 17 lines, six years; several
2020-21 values differ from the sibling's d22 hand entry); Digest d22 Table 325.92 (history bachelor's
1990-91 through 2020-21); Humanities Indicators: 42% of humanities majors held an advanced degree in
2021 (ACS); all graduates 37% (2018).

**Built:** `validation/` (common, external_benchmarks, validation_tests, benchmark_checks),
`reference/nces_bachelors_by_field.json`, `reference/humanities_indicators.json`,
`validation/results/external_benchmarks.json`. Command: `uv run python -m validation.external_benchmarks`.

**After (measured):**

| Digest year | LinkedIn n | core6 LinkedIn | core6 NCES | ratio | l1_proxy ratio |
|---|---|---|---|---|---|
| 1991 | 5,953 | 10.06% | 12.08% | 0.83 | 0.94 |
| 2001 | 10,103 | 8.53% | 11.68% | 0.73 | 0.87 |
| 2006 | 16,131 | 8.80% | 11.67% | 0.75 | 0.88 |
| 2016 | 33,756 | 6.30% | 7.83% | 0.80 | 0.91 |
| 2021 | 29,643 | 5.19% | 6.55% | 0.79 | 0.86 |
| 2022 (history est.) | 29,534 | 4.56% | 6.19% | 0.74 | 0.80 |

Advanced-degree rate among L1 bachelor's holders with bachelor's year <= 2015: 42.9% (n=21,597) vs
Humanities Indicators 42% (ratio 1.02); all persons 32.3% (n=181,767). Rung subset: dated rows
n=288,856 core6 6.81% vs undated n=1,190,936 core6 7.48%. Tests: `validation.validation_tests`
(logic) and `validation.benchmark_checks` (data) pass. Finding: LinkedIn under-represents core
humanities bachelor's by about a fifth, consistently across three decades.

## P2. Imputed bachelor's tier

**Pre-review (fresh subagent, 2026-09-22): VERDICT: BUILD WITH CHANGES.** Verbatim core: "Condition 4 is
false in-data ... degree_raw is non-blank on 99.97% of candidate rows"; "IPEDS guard defaults to pass on
half the rows"; "27.8% of post-guard rows belong to a person who already has a pooled bachelor's at a
different school"; "as specified it is not an improvement: it would set level 4 on ~212k rows at roughly
30% precision"; STRICT variant "(a) require degree_method = 'cip_from_degree' ... (b) negative-token
regex on degree_raw ... (c) exclude persons who hold a pooled bachelor's at any other school ... (d)
require an IPEDS-resolved iclevel_label = '4yr+' with carnegie_label not in bacc_associates_* / assoc_*"
at "~28k rows / ~12.5k first-level persons / ~3.2k L1 persons at an estimated >= 0.90"; gate "use 200
rows ... with a written rubric ... both strict and lenient scores". All adopted. Also flagged for
later, not part of this tier: ~13,600 rows with unparsed bachelor abbreviations (BSMET, BSEd, B.B.A.,
B.A.Sc.) are a `final_hybrid` abbreviation-table gap and should land as `det`, not as imputation.

**Built:** `edu_clean/imputed_bachelor.py` (predicate pieces), `edu_clean/apply_bachelor_imputed.py`
(apply; runs inside `build_normalized` after the CIP apply; `--sample`, `--unland`),
`edu_clean/imputed_tests.py` (logic), `edu_clean/imputed_data_checks.py` (data);
`education_person.bachelor_imputed_any`; PIPELINE.md row. Coding workflow: `coding/` (Label Studio
export, ingest, precision + Cohen's kappa; `coding/README.md`), sample registered as `imputed_bachelor`.

**Before -> after (measured, `normalized/education.parquet` and `education_person.parquet`):**

| measure | before | after |
|---|---|---|
| rows with `degree_level_source = 'imputed_bachelor'` | 0 | 25,536 |
| persons with any pooled degree level | 1,881,303 | 1,893,656 (+12,353) |
| persons with pooled level >= bachelor's | 1,621,046 | 1,641,688 |
| `hum_l1_bachelor_pooled_any` persons | 181,767 | 184,575 (+2,808) |
| `bachelor_imputed_any` persons | n/a | 24,376 |

Top schools among imputed rows: Penn State (199), UCF (186), SNHU (185), Houston (178), FIU (173).
By field group: Other 16,361; Fine & Performing Arts 1,453; Communication & Media 1,398; Psychology
1,378; Humanistic Social Science 1,202; English & Literature 377. Apply asserts: row count, degree
fingerprint, CIP fingerprint, det/jury pooled fingerprint. Blind sample: 200 rows by salted hash,
`edu_clean/results/imputed_bachelor_sample.jsonl`, rubric in the header line; Label Studio project in
`coding/label_studio/imputed_bachelor.*`. Side effect: the P1 benchmark rung now includes imputed rows;
`make benchmarks` re-run and recommitted (the fingerprint tripwire fired as designed; shares moved by
< 0.1 pp).

**Post-review (fresh subagent, 2026-09-22): VERDICT: LAND.** Verbatim: "every invariant re-derives
exactly, det/jury rows are byte-identical to the main checkout, idempotence holds, and strict
precision meets the 0.90 bar at the point estimate". Blind score on the 200-row sample: "pass=180
unsure=15 fail=5 -> strict = 0.900, lenient = 0.973; the Wilson 95% interval is 0.851-0.934". Failed
rows: SANS Technology Institute one-year program; Point Park "additional schooling"; Rhode Island
College "did not complete degree program"; "Eastfield college" whose `school_slug` resolves to UNT (an
upstream slug error); Clarkson "transferred out". Defects taken now: (2) the negative-token regex now
also runs on `field_raw` and a non-completion regex (`did not complete`, `transferred out`, `dropped
out`, `withdrew`, ...) runs on `description`; (3) the same-school graduate guard is `> 4`, not `>= 6`.
Re-run: 25,175 rows (from 25,536), 12,100 persons gain a first level, +2,762 L1 bachelor's persons.
Re-scoring the reviewer's labels on the 197 sample rows that survive the tightened predicate (the
three dropped rows were labeled pass, pass, fail): strict 0.904, lenient 0.978. Labels file:
`coding/labels/imputed_bachelor.reviewer.jsonl` (the human coder's labels go beside it; see
`coding/README.md`). Deferred defects, recorded for follow-up: the slug map has wrong exact matches
("Eastfield college" -> UNT, "College" -> SIU, "Western" -> WGU) that P2 is the first consumer to turn
into a degree level; 770 persons carry imputed rows at two schools (one is usually a transfer-out);
the word "propose-only" here means excludable through `degree_level_source`, not unlanded.

## P3. Co-majors and minors

**Pre-review (fresh subagent, 2026-09-22): VERDICT: BUILD WITH CHANGES.** Verbatim core: "Whole-string-first
via `_field_cip_lookup` is not the same as 'the value already resolves deterministically'. The
typo_to_cip tier resolves 2,872 values that `_field_cip_lookup` does not, and 135 of them split into two
resolving halves (1,607 rows)"; "Primary = first-in-order, must equal cip2_pooled, is the wrong conflict
rule ... 16,049 split rows (11%) have the jury's cip2 on the second component ... Rule should be: if
cip2_pooled equals the family of ANY resolved major component, that component is primary and the other
is secondary"; "cip2 dedupe collapses within-family pairs and breaks the plan's own concentration test";
"Primary filling cip2_pooled where NULL: keep it secondary-only for P3 ... set comajor_source =
'no_primary'"; gate: "stratify 50/50 between the plain-separator class and the marker class ... with the
gate applied to the plain class". Sweep by the reviewer of the plan's splitter over every compound
value: split 72,683 values / 141,558 rows (4.0% of education rows); 0 of 2,328 CIP titles split; 23,724
persons would gain an L1 bachelor co-major under the corrected primary rule (18,782 under the plan's).
All changes adopted.

**Built:** `edu_clean/comajors.py` (splitter; whole-string-first, deterministic method wins, majors
deduped per family, primary chosen per row by the pooled family), `edu_clean/run_comajors.py`
(value mapping `normalized/mappings/edu_field_components.parquet`, 445,336 values in 3.4 s),
`edu_clean/apply_comajors.py` (columns `cip_secondary`, `cip2_secondary`, `nha_level_secondary`,
`minor_cip`, `minor_cip2`, `nha_level_minor`, `field_components_n`, `comajor_source`; runs inside
`build_normalized` after the imputed apply), `edu_clean/comajor_tests.py` (logic, incl. the sweep over
all 2,328 CIP titles: 0 split), `edu_clean/comajor_data_checks.py` (data); person flags
`double_major_any`, `hum_l1_comajor_any`, `minor_hum_l1_any`. Coding sample registered as `comajors`
(50 plain-separator + 50 marker rows, gate on the plain stratum).

**After (measured):**

| measure | value |
|---|---|
| values by status (row-weighted, non-duplicate rows) | single 1,974,908; unresolved 795,982; split 146,942 |
| education rows by `comajor_source` | split 137,497; no_primary 5,877; conflict 3,769 |
| persons `double_major_any` (bachelor rung) | 92,392 |
| persons `hum_l1_comajor_any` | 24,914 |
| persons `minor_hum_l1_any` | 3,517 |
| L1 bachelor's holders with a double major | 17,883 of 184,575 (9.7%) |
| persons gaining an L1 bachelor's field only through the secondary | 17,993 (L1 bachelor OR L1 co-major = 202,568) |

Top L1 pairs (pooled + secondary): 45+54 (2,969), 23+09 (1,907), 09+50 (1,663), 45+16 (1,516),
50+09 (1,272), 09+23 (1,163), 23+45 (1,049), 23+50 (931), 52+16 (921), 45+38 (918). Same-family
pairs (e.g. finance + marketing) collapse by design. Blind sample:
`edu_clean/results/comajors_sample.jsonl` (100 rows, stratified); Label Studio project in
`coding/label_studio/comajors.*`.

## P4. Occupation-family tier

**Pre-review (fresh subagent, 2026-09-22): VERDICT: BUILD WITH CHANGES.** Verbatim core: the residue
(4,183,996 rows with no pooled major) is "81.8% strings the jury never labeled, and its head is exactly
what a rules classifier handles"; but "the gold ... is off-distribution by construction (lexicon-matchable
strings only; the landing strings are absent from the lexicon), its mixed-string labels are noise from
tiny coded minorities, and it is role-unweighted"; "at p=0.85, n=30 gives a Wilson 95% interval of roughly
0.69-0.94"; mechanical breakage: "`cohorts/cohort_tests.py:44` fails the moment a `family` row exists";
"`archetypes/common.py` ingests family majors via `coalesce` with a NULL method"; "`founder_owner -> 11`
would ... override `functional_cluster` on ~85k rows". Anchors to forbid regardless of gate:
`trades_logistics`, `founder_owner`, `hospitality_food`, `banking_insurance`. Change: "Gate each family on
two populations and two strata ... (a) the det gold with the 1,586 mixed roles removed and (b) the
jury-accepted mapping (298,942 roles) ... require precision >= 0.85 with n >= 100 on both ... stamp
`landable` per (family, stratum)". Precedence det > jury > family confirmed. All adopted; the family
tier lands only where `functional_cluster` is NULL.

**Built:** `career_clean/families/` (`taxonomy.py` with FAMILIES + SENIORITY verbatim and NEVER_LAND;
`classify.py` verbatim; `family_tests.py` verbatim plus the taxonomy contract, 634 assertions pass),
`career_clean/run_families.py` (classify 3,507,500 title values in 11 s; gate on det gold minus mixed
roles and on the 298,942-role jury mapping, per (family, stratum), n >= 100 and p >= 0.85 on both;
sample), `career_clean/family_data_checks.py`; `build_normalized` joins the optional
`title_family` mapping and lands `title_family`, `title_family_confidence`, `title_seniority9` on
every step and the family's SOC-major anchor as `occupation_source = 'family'` only where landable,
high-confidence, no det, no jury, no `functional_cluster`; `archetypes/common.py` and
`cohorts/cohort_tests.py` accept the new source values. Gate file:
`career_clean/results/family_gate.json`.

**Gate result (the important finding):** only three (family, stratum) pairs clear 0.85 on both
populations: `higher_ed_faculty`/staff (gold 0.97, jury 0.89), `journalism_media`/staff (0.89, 0.88),
`legal_attorney`/staff (0.98, 0.94). Every functional family fails on the managerial stratum by SOC
convention (managers are 11), and most fail on staff too, because a single 2-digit anchor per family
is not how SOC codes titles: `software` misses "Full Stack Engineer" (gold 17), `sales` misses bare
"Sales" (gold 11) and "Business Development Specialist" (13), `teaching_k12` misses "School Counselor"
(21) and "School Psychologist" (19), `marketing` misses "Brand Ambassador" (41) and "Content Creator"
(15). Some of those gold labels are themselves conventions of the deterministic coder, but the tier
cannot clear a gate it disagrees with. Landable title values: 77,091 of 3,507,500.

**Before -> after (measured, `normalized/career_steps.parquet`):**

| measure | before | after |
|---|---|---|
| `occupation_major_pooled` coverage | 61.3% | 61.83% (+61,110 rows, `occupation_source = 'family'`) |
| landed rows by family | n/a | journalism_media 27,817 (27); higher_ed_faculty 23,924 (25); legal_attorney 9,369 (23) |
| `title_family` present (not `unclassified`) | n/a | 97.07% of steps |
| `title_family_confidence = 'high'` | n/a | 83.24% |
| `title_seniority9` marked (not `mid`) | 30.4% named tokens | 54.98% |

So the SOC-proposer use of the family tier is nearly a bust (+0.5 pp), and that is the honest result
of gating it; the family axis itself is on every step as a propose-only column, and the nine-level
seniority marks 55% of steps versus 30% for the token parser. Blind sample of landed steps:
`career_clean/results/family_sample.jsonl` (100 rows). Follow-ups logged: `assistantmanager` (25k
rows) and the residue head (Project Manager 78k, Owner 69k, Sales 54k, Administrative Assistant 47k)
still have no pooled major; a per-title anchor keyed on (family x seniority9), or a re-fire of the
jury on the residue head, is the next step, not a wider gate.

## P5. Employer-keyed overrides

**Pre-review (fresh subagent, 2026-09-22): VERDICT: BUILD WITH CHANGES.** Verbatim core: "The plan's
`_VP` regex is the serious problem ... fires on 267,730 rows: 51,549 currently 11-1011, 210,113 currently
uncoded, and 6,068 currently carrying a correct functional det code"; "11-1021 becomes 318,101 rows, the
largest 6-digit code in the management major by 2.5x"; O*NET lists EVP and "Finance Vice President" under
11-1011, so senior/executive VPs are correct today; `k12_principal` "clearly yes" (8,230 rows);
`law_firm_partner` "yes" (8,550 rows; 95.7% of PRO.LEGAL Associates hold a JD); `firm_principal` "expect
it to fail the 0.90 gate"; XOT is 40-64% of every candidate title so overrides reach at most half; the
four step keys repeat on 88 rows. Change: "fire `vice_president` when 'vice' in seniority tokens and
role_canonical in ('president', 'assistantpresident'), and never otherwise"; drop `firm_principal`; add
`principal` to the PRO.LEGAL title set; DISTINCT the mapping on the four keys. Assistant manager: leave
alone; logged as a P4 follow-up (`assistantmanager` has no pooled major on 25k rows). All adopted;
senior/executive VPs stay at 11-1011 and the bare-VP routing is documented as a convention.

**Built:** `career_clean/overrides.py` (pure rule table: `vice_president` on the seniority-token form
only, `k12_principal`, `law_firm_partner` incl. `principal` under PRO.LEGAL; `firm_principal` dropped),
`career_clean/override_tests.py`, `career_clean/run_overrides.py` (row-level mapping
`normalized/mappings/career_occupation_override.parquet`, DISTINCT on the four step keys, never lands
on a row whose det major differs), `build_normalized` precedence override > det > jury > family for
the pooled major and override > det for the new `occupation_code_pooled` / `occupation_code_source`
plus `override_reason`; `career_clean/soc_data_checks.py` extended for the new sources.

**After (measured, `normalized/career_steps.parquet`):**

| measure | before | after |
|---|---|---|
| override rows by reason | n/a | vice_president 33,971; law_firm_partner 8,792; k12_principal 8,230 (50,993; 42 candidates skipped for a det-major conflict) |
| steps on 11-1011 Chief Executives | 178,911 | 149,424 |
| steps on 11-1021 General and Operations Managers | 44,240 | 78,211 |
| steps on 11-9032 K-12 administrators | 4,701 | 12,214 |
| steps on 23-1011 Lawyers | 31,774 | 37,583 |
| 6-digit code coverage | 21.46% | 21.62% |
| pooled major coverage | 61.83% (after P4) | 61.99% |
| top management codes, L1 bachelor's holders | 11-1011 14,684; 11-2022 5,299; 11-2011 3,823; 11-1021 3,136 | 11-1011 12,404; 11-1021 5,710; 11-2022 5,299; 11-2011 3,823 |

Chief Executives stays the modal 6-digit management code for the humanities cohort because
President (45k), CEO and Executive Director titles are legitimately 11-1011; the audit's remedy is a
display split (senior VPs stay per O*NET). XOT industry caps the reach of the principal and law-firm
rules at roughly half of each title's rows. Blind sample: `career_clean/results/override_sample.jsonl`
(50 per reason); Label Studio project `coding/label_studio/overrides.*`.

## P6. Person summary and metrics cube v0
