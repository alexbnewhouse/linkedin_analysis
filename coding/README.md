# Human coding of gold and blind samples

Every propose-only tier in this repo is gated on a blind sample scored by a reviewer. This
folder makes those samples codeable by a person in Label Studio, keeps every annotator's
labels in one format, and scores precision and agreement the same way for everyone.

## Samples

| sample | drawn by | file |
|---|---|---|
| `imputed_bachelor` | `edu_clean.apply_bachelor_imputed --sample 200` | `edu_clean/results/imputed_bachelor_sample.jsonl` |
| `comajors` | `edu_clean.apply_comajors --sample 100` | `edu_clean/results/comajors_sample.jsonl` |
| `family` | `career_clean.run_families sample` | `career_clean/results/family_sample.jsonl` |
| `overrides` | `career_clean.run_overrides --sample 50` | `career_clean/results/override_sample.jsonl` |

The registry (`coding/common.py:SAMPLES`) records the question, the fields shown, and the
label set (`pass`, `fail`, `unsure`). Each sample file starts with a header line carrying the
rubric used by the reviewer, so the human sees the same rubric.

## Workflow

1. Install Label Studio once: `uv tool install label-studio` (or `pipx install label-studio`).
2. Start it: `label-studio start --port 8080`, open http://localhost:8080, create an account.
3. Export the sample: `uv run python -m coding.export imputed_bachelor` (or `--all`).
4. In Label Studio: Create project, name it after the sample, then Settings > Labeling
   Interface > Code and paste `coding/label_studio/<sample>.config.xml`. Import
   `coding/label_studio/<sample>.tasks.json`.
5. Code the rows. Do not look at the reviewer's labels first (they are in
   `coding/labels/<sample>.reviewer.jsonl`), so the agreement number means something.
6. Export > JSON from the project, then
   `uv run python -m coding.ingest imputed_bachelor alex ~/Downloads/project-1.json`.
   A CSV with `id,label,note` columns works too.
7. Score: `uv run python -m coding.score imputed_bachelor`. This prints strict and lenient
   precision per annotator and Cohen's kappa for every pair, with the disagreements listed.

The gate for each tier reads the strict precision against the bar in
`docs/notes/2026-09-22-sibling-methods-port.md`. If your coding disagrees with the
reviewer's on the gate outcome, the notes entry is what to update.

## Without Label Studio

Copy `coding/label_studio/<sample>.tasks.json` into any spreadsheet, add `label` and `note`
columns, save as CSV with an `id` column, and run `coding.ingest` on it.
