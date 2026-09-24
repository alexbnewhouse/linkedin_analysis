# Skillset breadth by field of study — implementation plan

Spec: none separate; the design agreed in conversation 2026-09-24 is recorded under
Global Constraints below and is binding.

Goal: an easy-to-read figure comparing how broad the range of work is for bachelor's
graduates of four field groups: Humanities, Humanistic social sciences, STEM, Finance.
Two independent breadth measures (text embeddings of job descriptions; O*NET skill
profiles) so the ranking can be checked against writing style.

## Global Constraints

- New module `skill_breadth/` at repo root, same idiom as `archetype_methods/`:
  `common.py` for paths/constants, `run_*.py` entry points runnable as
  `uv run python -m skill_breadth.<name>`, tests in `skill_breadth/skill_breadth_tests.py`
  as plain `check(...)`-style functions runnable with
  `uv run python -m skill_breadth.skill_breadth_tests`. Outputs to `skill_breadth/results/`
  (parquet/JSON), embedding cache in `skill_breadth/cache/` (git-ignored, add to .gitignore).
- DuckDB over parquet for all data work. No pandas-heavy loops over millions of rows.
- Encoder: reuse `archetype_methods.common.encode` pattern — `BAAI/bge-base-en-v1.5`,
  normalized, CUDA, cached by content hash. Import `ENCODER` from there; do not
  duplicate the constant. Copying the ~15-line `encode` helper into `skill_breadth/common.py`
  with its own CACHE dir is acceptable.
- American spelling in all prose and labels.
- Field groups (exactly these four, assigned from the person's bachelor's field):
  - `humanities`: `nha_level_pooled = 1`
  - `humanistic_social_sciences`: `nha_level_pooled = 2`
  - `stem`: `cip2_pooled IN ('11','14','15','26','27','40','41')` and `nha_level_pooled NOT IN (1,2)`
  - `finance`: `cip_code LIKE '52.08%'`
  Display labels: "Humanities", "Humanistic social sciences", "STEM", "Finance".
- Sanity-check fields (not in the headline figure, reported in results JSON):
  `nursing` = `cip_code LIKE '51.38%'`, `accounting` = `cip_code LIKE '52.03%'`,
  `liberal_arts` = `cip_code LIKE '24.01%'`.
- Bachelor's field: rows of `normalized/education.parquet` with `degree_level_pooled = 4`
  and `NOT is_duplicate`. A person whose bachelor rows map to more than one group
  (among the 4 + 3 sanity groups) is excluded. Bachelor year = the person's
  `bachelor_end_year` from `normalized/education_person.parquet`.
- Cohort window: `bachelor_end_year BETWEEN 2000 AND 2014` (so a full 10-year window
  is observed before the Oct 2025 experience freeze).
- Roles: `normalized/career_steps.parquet`, `NOT is_duplicate`,
  `start_year BETWEEN bachelor_end_year AND bachelor_end_year + 10`,
  `length(trim(description)) >= 50`. Role text for embedding =
  `title_raw || '. ' || description`, truncated by the encoder at 256 tokens.
- Breadth metric: Vendi score with cosine (linear, L2-normalized) kernel, computed as
  exp(Shannon entropy of the eigenvalues of X^T X / n), X = n×d normalized rows.
  Equal-n bootstrap: each replicate samples `N_PEOPLE = 500` people per group
  without replacement, then ONE random role per sampled person; `N_BOOT = 200`;
  seed 20260924. Report median and 2.5/97.5 percentiles.
- O*NET skills basis: O*NET 29.3 `Skills.txt` (Importance scale, `Scale ID = 'IM'`),
  35 skills per O*NET-SOC; aggregate to 6-digit SOC by mean. Each role maps to a SOC:
  `occupation_code_pooled` when present and in the skills table, else nearest O*NET
  occupation by cosine between the role-text embedding and the O*NET
  `Title. Description` embedding. Skill vectors are z-scored per skill across the
  O*NET occupation table, then L2-normalized, before the Vendi computation.
- Secondary within-person metric: for people with >= 3 described roles in window,
  mean pairwise cosine distance among their role-text embeddings, reported per group
  stratified by role count (3, 4, 5+).

## Task 1: Cohort and role table

Create `skill_breadth/common.py` (paths, constants above, `encode`) and
`skill_breadth/build_cohort.py` producing:
- `results/persons.parquet`: linkedin_id, group, bachelor_end_year, bachelor_cip
- `results/roles.parquet`: linkedin_id, group, experience_idx, position_idx, start_year,
  title_raw, occupation_code_pooled, role_text
- `results/_cohort_manifest.json`: counts of persons and roles per group, excluded
  multi-group persons count.
Tests: group assignment SQL on a tiny in-memory fixture (one person per group, one
multi-group person excluded, one out-of-window role dropped, one short description dropped).
Add `skill_breadth/cache/` to .gitignore; commit results only if < 5 MB, otherwise
git-ignore `skill_breadth/results/*.parquet` too.

## Task 2: Embeddings and O*NET skill mapping

`skill_breadth/embed_roles.py`: embed every role_text in roles.parquet (cached),
save row-aligned `cache/role_emb.npy` plus the role key order.
`skill_breadth/onet_skills.py`: download O*NET 29.3 Skills.txt to
`reference/onet_skills.txt` (URL
`https://www.onetcenter.org/dl_files/database/db_29_3_text/Skills.txt`) if absent;
build the SOC × 35 skill matrix; map each role to a SOC per the Global Constraints;
write `results/role_soc.parquet` (role key, soc, soc_source in {'pooled','nearest'},
nearest_cos). Tests: SOC truncation "15-1252.00" -> "15-1252"; z-score + normalize
produces unit rows; a role with a known pooled SOC keeps it.

## Task 3: Breadth metrics

`skill_breadth/metrics.py` (pure functions: `vendi(X)`, `bootstrap_vendi(...)`,
`within_person_spread(...)`) and `skill_breadth/run_breadth.py` writing
`results/breadth.json`: per group (4 headline + 3 sanity) for both bases
(`text`, `onet_skills`): median, lo, hi, n_people_available; within-person spread
table; Spearman rank agreement between the two bases across the 7 groups.
Tests: vendi of n identical rows = 1; vendi of d orthonormal rows = d; bootstrap is
deterministic given the seed.

## Task 4: Figure

A standalone HTML page `skill_breadth/figure/index.html` built by
`skill_breadth/build_figure.py` from breadth.json (data inlined). Ranked dot plot:
two side-by-side panels sharing the row order (ranked by the text basis), each with
its own x axis because the two Vendi scales are not commensurable: left panel
"Job descriptions" (x = "Effective number of distinct jobs"), right panel
"O*NET skill profiles" (x = "Effective number of distinct skill profiles"). Point
with CI whisker per row. Humanities and Humanistic social sciences in
the accent color, STEM and Finance muted. Numbered figure grammar (Fig. 1, title,
one-line dek, source/note figcaption under a rule). House style: no italics, no
letterspaced uppercase, no accent-rail cards, few em-dashes, light and dark themes.
