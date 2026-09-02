# CIP field coding: measured precision (blind gold v1)

Source of truth for every number: `edu_clean/results/frontier_gold_v1_report.json`
(regenerate with `uv run python -m edu_clean.gold_v1 report`). Measured
2026-09-01 against `normalized/education.parquet` at 82.53% pooled row coverage.

## What was measured

Field-of-study strings are mapped to CIP 2020 two-digit families by five tiers,
applied in strict precedence (a lower tier fills only where every higher tier
is empty): deterministic string match (`det`), the local LLM jury
(`jury_llm`), frontier-model adjudication of the jury's disagreement band
(`frontier`), head-component matching of compound strings against labeled
strings (`knn_head`), and a degree-type fallback for subject-bearing degrees
such as MBA or JD (`degree_type`). A sixth row-level tier codes uncoded
high-school-diploma rows as CIP 53 (`degree_level`); it is correct by
construction and was not sampled.

The gold set is 400 distinct field strings drawn by salted hash, 60 from each
landed tier and 100 from the uncoded residual, labeled blind (no system code
visible) with a primary family, an optional defensible secondary family, and
an unsure flag. Strings are held out and re-scorable against the live table.

## Per-tier precision (string level, modal-degree row)

| tier | rows | share of coded rows | n graded | strict | lenient | humanities level |
|---|---:|---:|---:|---|---|---|
| det | 2,104,692 | 71.3% | 46 | 0.89 (0.77–0.95) | 0.96 (0.86–0.99) | 0.98 (0.89–1.00) |
| jury_llm | 407,265 | 13.8% | 59 | 0.93 (0.84–0.97) | 0.97 (0.89–0.99) | 0.98 (0.91–1.00) |
| frontier | 83,798 | 2.8% | 58 | 0.93 (0.84–0.97) | 0.98 (0.91–1.00) | 0.98 (0.91–1.00) |
| knn_head | 214,106 | 7.3% | 60 | 0.93 (0.84–0.97) | 0.97 (0.89–0.99) | 0.97 (0.89–0.99) |
| degree_type | 85,742 | 2.9% | 54 | 0.89 (0.78–0.95) | 0.96 (0.88–0.99) | 0.93 (0.82–0.97) |
| degree_level | 56,929 | 1.9% | — | by construction | | |

Parentheses are Wilson 95% intervals. Strict = primary family; lenient =
primary or secondary; humanities level = agreement at the L0–L3 grain the
analysis actually uses.

## Overall

Weighted by row share over the five measured tiers (2,895,603 rows):

| | strict | lenient | humanities level |
|---|---|---|---|
| row-weighted precision | 0.90 | 0.96 | 0.98 |

The lenient-minus-strict gap (0.03–0.07 per tier) is taxonomy ambiguity, not
error: every gap case is a pair of families that both fit the string, and each
pair appears once in the sample (14 vs 11, 51 vs 52, 51 vs 15, 43 vs 11, 01 vs
04, 13 vs 51, 11 vs 52, 45 vs 26, 51 vs 60, 51 vs 13, 45 vs 30). None of them
crosses a humanities level.

Placeholder strings (GPA, honors, institution names) are a separate class:
the field string carries no signal, and the correct behaviour is to code the
row from the degree line or abstain. In the sample, det coded 21 such rows
from the degree line and abstained on 16; string-keyed tiers mislabeled two
placeholder strings ("all studies", "MARINE CORPS"), which is the recorded
baseline the regression test holds.

## Recall bound

Of 625,127 uncoded rows, 195,777 carry field text. The residual sample is 85%
codeable (by strings and by rows), so at most **166,606 rows (4.7% of all
rows)** still carry recoverable field signal. The residual is flat: the top
5,000 residual strings cover 20% of those rows and the head is GPA, honors and
"General". A further adjudication tranche would land under 1% of rows.

## Can anything cheaper code the residual?

Two candidates were tested on the same gold (`frontier_gold_v1_knn_sweep.json`,
`frontier_gold_v1_calibration.json`):

- **Embedding kNN** (bge-base, nearest labeled string, self excluded): on
  residual strings strict precision is 0.64–0.67 at every threshold from 0.80
  to 0.95, lenient 0.80–0.91, and coverage collapses to 11 strings at 0.95.
  The propose-only kNN paths stay propose-only. The landed `head_exact` path
  re-measures at 0.93 strict, consistent with its judged sample.
- **The incumbent 4B lane juror** (qwen3-4b-q4, solo): residual 0.65 strict /
  0.81 lenient with 82% vote rate; on the frontier band it scores 0.29 strict,
  which is why that band needed a frontier model.

Any future local juror should be calibrated the same way before it is
trusted: `uv run python -m edu_clean.gold_v1 calibrate ollama/<model> "<hosts>"`.
Three local jurors, solo, on the same gold (strict / lenient among voted
strings; vote rate on graded strings):

| juror | residual | frontier band | knn_head | vote rate (residual) |
|---|---|---|---|---|
| qwen3-4b-q4 (incumbent lane) | 0.65 / 0.81 | 0.29 / 0.48 | 0.81 / 0.91 | 82% |
| gemma3:12b (disjoint family) | 0.63 / 0.78 | 0.36 / 0.64 | 0.80 / 0.92 | 82% |
| phi4:14b (disjoint family) | 0.69 / 0.86 | 0.66 / 0.78 | 0.80 / 0.91 | 77% |

phi4:14b is the strongest of the three and still 20 points short of the bar on
the residual. No juror at this size closes the tail; the frontier band in
particular needed a frontier model (phi4 reaches 0.66 where the others sit at
0.29–0.36).

## Limits

- One annotator (Fable 5.1). A blind double-label sheet of 100 strings
  (stratified: 15 per tier, 25 residual) is at
  `edu_clean/results/frontier_gold_v1_double_label_sheet.txt`; score it with
  `uv run python -m edu_clean.gold_v1 agree FILE` to get raw agreement,
  lenient agreement and Cohen's kappa per tier.
- Sixty strings per tier: intervals are roughly ±7 points at 0.93.
- Stratified by string, not row, so per-tier numbers are string precision;
  the overall figure is row-weighted by tier share, not by within-tier row
  weight.

## Drop-in methods paragraph

Field-of-study strings were mapped to CIP 2020 two-digit families in five
tiers applied in strict precedence: deterministic string matching, a local
two-model LLM jury accepting only unanimous votes, frontier-model adjudication
of the jury's disagreement band, head-component matching of compound strings
against labeled strings, and a degree-type fallback for subject-bearing
degrees; uncoded high-school-diploma rows were assigned the secondary-diploma
family. We measured precision on a held-out sample of 400 distinct strings
stratified by tier (60 per tier and 100 from the uncoded residual), labeled
blind with a primary family and an optional defensible secondary family.
Lenient precision (primary or secondary) was 0.96 (95% CI 0.86–0.99) for
deterministic matches, 0.97 (0.89–0.99) for the jury, 0.98 (0.91–1.00) for
frontier adjudication, 0.97 (0.89–0.99) for head-component matching and 0.96
(0.88–0.99) for the degree-type fallback; agreement at the humanities-level
grain used in the analysis was 0.93–0.98. Weighted by row share, pooled CIP
precision is 0.90 strict and 0.96 lenient at 82.5% row coverage. The residual
sample implies that at most 4.7% of education rows carry recoverable field
text, spread across a flat tail of rare strings.
