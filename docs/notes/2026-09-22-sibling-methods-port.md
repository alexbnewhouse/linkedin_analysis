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

**Post-review 1 (fresh subagent, 2026-09-22): VERDICT: LAND AS PROPOSE-ONLY.** Verbatim: "plain-stratum
strict precision is 0.86 against a 0.90 bar and the misses concentrate in two fixable mechanisms
(compound program names, bare parentheticals) whose largest case, CSE, is the table's most frequent
'double major'". Blind score n=100: strict 0.870 overall; plain 0.860 (43 pass, 3 fail, 4 unsure);
marker 0.880. Failed rows: "Computer Science & Engineering" split 14 + 11; "Criminology, Law & Society"
split 22 + 45; "Radio/TV/Film" left only Film; "Chemistry (Biochemistry)"-type parentheticals promoted
to a second major; "Economics (Business) & Psychology" where the parenthetical displaced Psychology;
"Business Administration and Management, Minor" split a CIP title; "Statistics and Data Science".
All headline numbers reproduced exactly; deterministic and pooled columns verified untouched.
Labels: `coding/labels/comajors.reviewer.jsonl`.

**Fixes (same day):** a curated `COMPOUND_PROGRAMS` stoplist of single-program names checked on the
normalized whole string before splitting (CSE, EECS, ECE, PPE, Statistics and Data Science,
Criminology Law and Society, Radio/TV/Film, ... ~70 names); a bare parenthetical is always a
concentration, never a second major; a trailing ", Minor" first tries the whole head as one
program; "with second major" is consumed by the major marker; the blind draw requires a secondary or
a minor (7,928 split rows are concentration-only and never carry a co-major: consumers filter on
`cip_secondary`). Tests added for each. Re-run: split 134,452 / no_primary 5,681 / conflict 3,708;
`double_major_any` 89,088; `hum_l1_comajor_any` 24,463; L1 bachelor's holders with a double major
17,682 of 184,529; L1 bachelor OR L1 co-major 202,152 (+17,623). Sample redrawn (salt v2) for a
second blind review.

**Post-review 2 (fresh subagent, 2026-09-22): VERDICT: LAND.** Verbatim: "The plain-stratum gate passes
at 0.94 strict (0.92 overall), the deterministic and pooled columns are verified untouched, and the
remaining misses are a 0.6% trailing-concentration class plus stoplist gaps that are bounded". Blind
score n=100: strict 0.920 overall; plain 0.940 (47 pass, 1 fail, 2 unsure); marker 0.900. Failed rows:
"Liberal Arts/ Social and Behavioral Sciences" (one track; second component cut to "Behavioral
Sciences"), "Sociology/Psychology emphasis", "Business Administration and Management, IT Focus",
"Liberal Studies, Psychology concentration" (trailing concentration word did not demote the preceding
component), "Communication, Media and Theatre (CMT)", two graduate degrees in one string. All headline
numbers reproduced exactly (0 stoplisted names still split). Stoplist review: "criminology and
criminal justice" (647 rows) and embedded longer forms (~500 rows) missing; ~25 entries moot under
family dedupe. Tooling: positional sample ids collided across draws. Labels:
`coding/labels/comajors.reviewer2.jsonl` (round 1 in `coding/labels/superseded/`).

**Follow-ups (same day, all conservative, no third review):** a trailing concentration word demotes
the preceding component (mirror of the trailing-minor rule); a head that is one program (resolves
whole or stoplisted) followed only by a parenthetical or a minor/concentration marker never splits,
but keeps a resolved minor or concentration; stoplist gains "criminology and criminal justice" and the
embedded forms; sample ids carry the draw's salt. Re-run: split 133,904 / no_primary 5,806 / conflict
3,695; `double_major_any` 87,702; `hum_l1_comajor_any` 24,367; L1 bachelor's holders with a double
major 17,589 of 184,529; L1 bachelor OR L1 co-major 202,071 (+17,542); 14,260 split rows are
minor-only (a stoplisted head with a resolved minor). Decision: LANDED; the person flags
`double_major_any` / `hum_l1_comajor_any` may be consumed.

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

**Post-review (fresh subagent, 2026-09-22): VERDICT: LAND AS PROPOSE-ONLY.** Verbatim: "the three
landed strata clear the blind gate only at 0.87 and the largest one (higher_ed_faculty) fails its own
step-weighted gold precision on a known class (postdocs/researchers -> 25)". Blind score n=100: strict
0.870, lenient 0.916; fails: "Faculty Affairs", "Planetarium Presenter", "Senior Faculty Support
Coordinator", "Sales Line Producer" at Allstate, "Postdoctoral Research Fellow", "Assistant to Executive
Producer", "Professor of Journalism and French language" landed as 27, "Visiting Scholar/Senior
Researcher". Gate audit: every per-stratum number reproduced to four decimals; the functional
families' failures are "both" the classifier (developer/dealer/brand catch-alls) and the gold's
conventions (engineer -> 17 regardless of software, coordinator/officer -> 11). Also noted: commit
c38c103's Makefile referenced P5 modules that landed in the next commit (history artifact; the branch
is consistent).

**Fixes (same day):** postdocs, visiting scholars, research/visiting fellows and senior researchers
route to `research` (19) ahead of the faculty rule (three ported assertions updated to say so);
"professor/lecturer of X" wins over the journalism block; "assistant to" is admin support; insurance
producers are `banking_insurance`; "planetarium" is `museum_library`; faculty-affairs/support strings
are `higher_ed_staff`; the gate now also requires the STEP-WEIGHTED precision >= 0.85 on both
populations; the bootstrap regression check covers the two new optional mappings. Re-gate:
higher_ed_faculty/staff gold 1.00 (n=289) jury 0.93 (n=3,137); journalism_media/staff 0.90 / 0.88;
legal_attorney/staff 0.98 / 0.94; landable title values 74,676. Rebuilt: `occupation_source = 'family'`
on 58,282 rows (journalism_media 27,350; higher_ed_faculty 21,668; legal_attorney 9,264); pooled major
61.96%. Sample redrawn (salt v2, ids carry the salt) for a second blind review; the first reviewer's
labels are in `coding/labels/superseded/`.

**Post-review 2 (fresh subagent, 2026-09-22): P4 VERDICT: LAND AS PROPOSE-ONLY.** Verbatim: "the three
landed strata reproduce their gate (step-weighted >= 0.94 on both populations) and clear the blind bar
at strict 0.89, but the producer/faculty catch-alls and intern-seniority landings (roughly 3-4% of
family rows) mean the family major should stay out of portal.SOC_SOURCES until those guards land".
Blind score n=100: strict 0.890, lenient 0.947; fails: "Sales Associate/... Correspondent" at IKEA,
"Global Learning Leader - Design & Faculty Excellence" at GE, "Insurance Agent / Producer", "Research
Assistant for Professor McGuire", "Lead Generation top producer". No mechanical or contract defects.
Labels: `coding/labels/family.reviewer2.jsonl`.

**Guards (same day, no third review):** "producer"/"correspondent" with insurance, sales, lead, loan
or mortgage words anywhere in the title is `banking_insurance` / `sales`, not media; "research
assistant for/to/under" is `research`; an intern SENIORITY never lands a major even inside a landable
family (data-checked). Re-gate unchanged (three strata); landable title values 73,219; rebuilt:
`occupation_source = 'family'` on 56,614 rows (journalism_media 26,103; higher_ed_faculty 21,420;
legal_attorney 9,091); pooled major 61.95%. **Decision:** the family major stays landed on
`career_steps` as its own `occupation_source` value (the portal admits only det and jury by
`portal.common.SOC_SOURCES`, so it is excluded there by construction); `title_family`,
`title_family_confidence` and `title_seniority9` are on every step for any consumer that opts in.

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

**Post-review (fresh subagent, 2026-09-22): VERDICT: LAND.** Verbatim: "every reason clears the gate
(0.96 / 0.98 / 0.98), all claimed numbers and the det-major contract reproduce exactly, and the one real
defect is the occupation_source='override' labeling on unchanged-major det rows, which will NULL 33,187
det-coded steps in the portal panel and break portal_tests on the next spine rebuild". Blind score
n=150: strict 0.973, lenient 1.000 (four unsures: two volunteer-board "Vice-president"s, a Bible
academy principal, a self-employed "Principal"). Every landed override re-derived from the rule on the
row's own evidence (0 mismatches).

**Fixes (same day):** `occupation_source` names who supplied the MAJOR, so a det row whose major an
override leaves unchanged stays `'det'` (the VP re-route is visible in `occupation_code_source =
'override'` and `override_reason`); `'override'` as a major source now means only "code added where
the coder abstained" (17,816 rows); `soc_data_checks` re-tightened; new `override_data_checks`
re-applies the pure rule to every landed row; `override()` takes the spec's argument order; the SQL
prefilter normalizes punctuation ("Partner." reaches the rule). Rebuilt: 51,008 override rows
(vice_president 33,971; law_firm_partner 8,798; k12_principal 8,239); 11-1011 178,911 -> 149,424;
11-1021 -> 78,211; 11-9032 -> 12,223; 23-1011 -> 37,584. Sample redrawn (salt v2).

**Post-review 2 (fresh subagent, 2026-09-22): P5 VERDICT: LAND.** Verbatim: "every reason clears 0.90
strict (0.92 / 0.96 / 1.00, zero fails), all counts reproduce exactly, det rows keep occupation_source
= 'det' so the portal simulation NULLs zero det-coded steps". Blind score n=150: strict 0.960,
lenient 1.000; unsures are student-organization officers (Pi Sigma Epsilon, Wharton club) and a
preschool-plus-elementary operator. Defects taken: no-op overrides (det already carried the code:
2,988 law-firm and 717 K-12 rows) are no longer written, so `override_reason` now means "the code
changed". Logged for follow-up: student-organization and association "Vice-president"s (~3.6% of the
VP reason, already wrong at 11-1011 before) want an employer-name guard; `EDU` with an unresolved L2
(221 rows) is accepted as K-12. Rebuilt: 47,303 override rows (vice_president 33,971; k12_principal
7,522; law_firm_partner 5,810); 11-1011 149,424 and 11-1021 78,211 unchanged.

## P6. Person summary and metrics cube v0

**Pre-review (fresh subagent, 2026-09-22): VERDICT: BUILD WITH CHANGES.** Verbatim core: "The step join
as written drops 74% of steps ... position_idx is NULL on 8,010,124 of 10,798,352 steps; an
equality/USING join returns 2,788,244 rows"; "tier:l1 in the cube must be defined as
hum_l1_bachelor_pooled_any (the ANY-row rule) ... 6,307 L1 persons are lost by the choice" of one
bachelor row; "'Current' step rule: not consistent with build_panel ... use the panel's ordering";
"neither the spec nor Task 12 states the windowing rule for at_k_*"; "Disclosure rule: not enough ...
when a panel has exactly one cell below the bar, also suppress the next-smallest cell"; release stamp
fields listed; `profiles.parquet` and `paths/steps.parquet` are stale relative to P4/P5 so the person
table must derive career columns from `career_steps`. All adopted (see `persons/README.md`).

**Built:** `persons/` (`common.py` with the two-cell suppression rule, `build_person.py`,
`build_metrics.py`, `person_tests.py`, `person_checks.py`, `README.md`); `make persons`; a `persons`
stage in `scripts/refresh_downstream.sh` after archetypes; a `persons` stage in
`scripts/check_freshness.py`; `/persons/*.parquet` ignored, manifest and `results/metrics.json` kept.

**After (measured):**

| measure | value |
|---|---|
| persons / with a bachelor's row | 1,999,974 / 1,497,978 |
| tier L1 / L2 / L3 (bachelor rung, ANY-row) | 184,529 / 380,283 / 602,584 |
| entry axis / grad axis persons | 1,999,916 / 279,671 (both: 274,428) |
| spine steps joined (asserted equal to the spine) | 10,717,451 |
| persons with a current pooled major | 1,064,580 |
| groups in the cube | 62 (all, 3 tiers, field groups, cip2 >= 300) |
| build time | person 12 s; metrics 49 s |

Headline reads, tier L1 (bachelor's, pooled): graduate degree 32.0%, ever director+ 41.5%,
double major 9.5%; current SOC major top 5: 27 (26,955), 11 (24,928), 25 (10,358), 13 (9,381),
43 (5,316); plus-10 eligible on the entry axis 156,570 (147,400 with a step) vs 21,596 (17,393) on
the grad axis, the FOUNDATION 1.3 seven-to-one gap made concrete. `person_checks`: one row per person;
tiers nest; axes independent (entry-only 1,724,691, grad-only 66, both 274,428); entry_year agrees
with `cohorts/profiles` on all 1,999,916; attainment matches `max(seniority_ordinal)`; no printed cell
below the floor and no panel exposes a single suppressed cell. The suppressed-cell total (2.58M) is
dominated by employer cells and is reported per panel only when >= 2.

**Post-review (fresh subagent, 2026-09-22): VERDICT: LAND.** Verbatim: "all five gate metrics reconcile
exactly against direct source-table queries, the stamp is present and the step join keeps every spine
row". Reconciled: L1/L2/L3 184,529 / 380,283 / 602,584; L1 graduate-degree rate 0.3202; L1 current
SOC-major top 5 identical; plus-10 eligible/with-step 156,570 / 147,400 (entry) and 21,596 / 17,393
(grad); suppression re-derived on three panels; a JSON-wide scan of 1,116 panels found no cell below
10 and no single suppressed cell. Defects taken: the step-join dedupe over the 70 tied duplicate step
keys now has a deterministic tie-break (counts moved by single digits between builds before);
counts serialize as integers; every panel carries `n_total` / `n_kept` / `n_printed`;
`suppressed_cells_by_panel` and `total_suppressed_cells_excluding_employers` separate the employer long
tail (99.4% of the old headline total) from the substantive panels; `person_checks` scans every panel
including `at_k` and `stage`; the README documents that `has_master` includes MBA/M.Ed/MSW rows.
The dirty flag on the first results build is superseded by the rebuild at the final commit.

## Summary (2026-09-22)

| piece | before | after | gate (blind, strict) | reviews | decision |
|---|---|---|---|---|---|
| P1 benchmarks | no external check | core6 share 0.73-0.83x NCES across six Digest years; L1 advanced-degree rate 42.9% vs HI 42% | n/a (reporting) | pre BUILD WITH CHANGES; post LAND | landed (reporting) |
| P2 imputed bachelor's | 0 rows | 25,175 rows; 12,100 persons gain a first level; +2,762 L1 bachelor's | 0.900 on 200 (0.904 on the 197 survivors) vs 0.90 | pre BUILD WITH CHANGES (strict variant); post LAND | landed, excludable via `degree_level_source` |
| P3 co-majors | none | 133,904 rows split; `double_major_any` 87,702; +17,542 L1 via a second major | plain 0.86 -> 0.94 vs 0.90 | pre BUILD WITH CHANGES; post 1 PROPOSE-ONLY; post 2 LAND | landed; flags consumable |
| P4 family tier | SOC major 61.3% | 61.95% (+56,614 rows, 3 of 104 strata); `title_family` on 97% of steps; seniority marked on 55% vs 30% | 0.87 -> 0.89 vs 0.85 | pre BUILD WITH CHANGES; post 1 PROPOSE-ONLY; post 2 PROPOSE-ONLY | landed on career_steps as `occupation_source='family'`; excluded from the portal |
| P5 overrides | VPs on 11-1011 | 47,303 rows; 11-1011 178,911 -> 149,424; K-12 principals 4,701 -> 12,223; lawyers 31,774 -> 37,584 | 0.96/0.98/0.98 then 0.92/0.96/1.00 vs 0.90 | pre BUILD WITH CHANGES; post LAND; post 2 LAND | landed |
| P6 persons + cube | no person table | 1,999,974 rows, both axes, all tiers; 62-group cube with release stamp | five metrics reconciled | pre BUILD WITH CHANGES; post LAND | landed |

Coding workflow: `coding/` (Label Studio export, ingest, precision + kappa) with reviewer labels for
every sample. Downstream stages now STALE and to be refreshed in the main checkout after merge:
industry, paths, cohorts, archetypes, portal (`make refresh`).
