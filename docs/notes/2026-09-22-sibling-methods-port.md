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

## P6. Person summary and metrics cube v0
