# LinkedIn career-transition analysis

End-to-end pipeline that turns raw LinkedIn profile snapshots into an
entity-resolved career dataset and, from it, **career-transition networks**
(who moves from what role/occupation/employer to what).

## Pipeline (run in order)

```
data/*.jsonl
  │  parse_linkedin.py                 ~hours    -> parsed/         (Parquet star schema)
  ▼
parsed/  +  career_clean/ + edu_clean/ canonicalizers
  │  build_normalized.py               ~15 min   -> normalized/     (career_steps.parquet, education.parquet, mappings/)
  ▼
normalized/career_steps.parquet
  │  python -m paths.build_spine        ~20 s    -> paths/          (steps.parquet + transitions.parquet: the edge list)
  ▼
paths/transitions.parquet
  │  python -m transition_network.build_network <grain>   <1 s     -> transition_network/  (<axis>_edges/_nodes.parquet)
  │  python -m transition_network.analyze       <grain>   <1 s     -> backbone, centrality, communities
  ▼
career-transition network (occupation | role | company | employment_type | seniority)
```

| stage | command | input → output | runtime |
|---|---|---|---|
| parse | `uv run python parse_linkedin.py` | `data/*.jsonl` → `parsed/` | hours |
| normalize | `uv run python build_normalized.py` | `parsed/` + cleaners → `normalized/` | ~15 min |
| spine | `uv run python -m paths.build_spine` | `normalized/career_steps.parquet` → `paths/` | ~20 s |
| network | `uv run python -m transition_network.build_network occupation` | `paths/transitions.parquet` → edges/nodes | <1 s |
| analyze | `uv run --group graph python -m transition_network.analyze occupation` | edges/nodes → backbone/centrality/communities/SpringRank | <1 s |
| seniority | `uv run --group graph python -m paths.seniority` | role SpringRank → `paths/seniority_scores.parquet` | ~2 s |
| sequences | `uv run --group graph python -m transition_network.sequences` | trajectories → memory test/motifs/archetypes | ~20 s |

Setup: `uv sync` (Python 3.14, pinned in `.python-version`). The `analyze` /
`seniority` / `sequences` stages need the `graph` dependency group
(`--group graph`); the embedding passes need `--group embed`.

### Seniority & transition typing is a bootstrap (two spine passes)

Revealed seniority (SpringRank) is *learned from the edges the spine emits*, then
fed back to type those edges — so the spine runs twice. Full order from a built
`normalized/`:

```bash
uv run python -m paths.build_spine --force                       # pass 1: edges (untyped)
uv run python -m transition_network.build_network role           # role + occupation grains
uv run python -m transition_network.build_network occupation
uv run --group graph python -m transition_network.analyze role   # SpringRank revealed ranks
uv run --group graph python -m transition_network.analyze occupation
uv run --group graph python -m paths.seniority                   # fuse -> seniority_scores.parquet
uv run python -m paths.build_spine --force                       # pass 2: now emits transition_type
uv run python -m transition_network.build_network occupation --force   # typed edges
uv run --group graph python -m transition_network.analyze occupation --force
uv run --group graph python -m transition_network.sequences      # Phase 5
uv run --group graph python -m transition_network.temporal       # Phase 6: time-sliced drift
```

Layer B (cross-occupation status anchor) is static reference data, built once:
`uv run python reference/build_soc_status.py` (O*NET Job Zone → `reference/soc_status.parquet`).
Tune the typing threshold τ against the lexical layer:
`uv run --group graph python -m paths.tune_thresholds`.

**Cohort analysis** (`cohorts/`, longitudinal complement to the network):
`reference/build_bls_unemployment.py` → `cohorts.build_panel` →
`cohorts.{profiles,scarring,survival,typologies,generational}` (the `scarring`
and `survival` phases need `--group cohort`). See `cohorts/README.md`.

Pass 1 is bootstrap-tolerant: with no `seniority_scores.parquet` yet it emits
NULL revealed scores; pass 2 fills `seniority_score` + `transition_type`.

## The parser (stage 1)

Each input line is one LinkedIn profile: scalar fields, a nested
`current_company` object, and ~17 one-to-many nested lists (one of which,
`experience`, is itself doubly nested via `positions`). The parser flattens
all of this into typed, columnar tables linked by `linkedin_id`. Everything
lives in one self-contained script, `parse_linkedin.py`.

```bash
uv run python parse_linkedin.py          # parse ./data -> ./parsed
uv run python parse_linkedin.py --help   # options (data dir, output, workers, batch size)
```

The run is parallel (one worker process per input file) and streams each file,
so memory stays bounded regardless of input size. A `parsed/_manifest.json`
records per-file profile counts, errors, timing, and total row counts per table.

## Output layout

```
parsed/
  _manifest.json
  profiles/snap_*.parquet      # one row per profile
  experience/snap_*.parquet    # child tables, linked by linkedin_id
  positions/snap_*.parquet     # child of experience (linkedin_id, experience_idx)
  education/ ... etc.
```

Every table is split into one Parquet shard per input file, all sharing one
schema, so a table is read as a single dataset by globbing its directory.

### Tables

| Table | Grain | Key |
| --- | --- | --- |
| `profiles` | one per profile | `linkedin_id` (+ `source_file`, `source_row`) |
| `experience` | one per job | `linkedin_id`, `experience_idx` |
| `positions` | one per role within a job | `linkedin_id`, `experience_idx`, `position_idx` |
| `recommendations` | one per recommendation (free text) | `linkedin_id`, `idx` |
| `education`, `certifications`, `courses`, `languages`, `activity`, `bio_links`, `honors_and_awards`, `organizations`, `patents`, `people_also_viewed`, `posts`, `projects`, `publications`, `similar_profiles`, `volunteer_experience` | one per list element | `linkedin_id`, `idx` |

`profiles` also carries the flattened `current_company` object as `cc_*`
columns.

## Reading the output

```python
import duckdb
con = duckdb.connect()

con.sql("""
    SELECT p.name, e.company, e.title
    FROM read_parquet('parsed/profiles/*.parquet')   p
    JOIN read_parquet('parsed/experience/*.parquet')  e USING (linkedin_id)
    LIMIT 10
""").show()
```

Any Parquet-aware tool works (`pyarrow.dataset`, pandas, Polars, Spark, ...).

## Notes

- **Type coercion is defensive**: values are forced to each column's declared
  type (string / int64 / bool); anything unexpected becomes `NULL` rather than
  aborting the run. No JSON errors occurred on the full 2M-record dataset.
- **Duplicate ids**: ~48 `linkedin_id` values repeat across the snapshots.
  Rows remain individually traceable via `source_file` + `source_row`.
- **`cc_industry`** is rarely populated and noisy in the *source* data; it is
  preserved verbatim rather than cleaned.

## Project layout

```
parse_linkedin.py     # stage 1: raw *.jsonl -> parsed/ star schema (one script)
build_normalized.py   # stage 2: parsed/ + cleaners -> normalized/ row-level tables
data/                 # raw *.jsonl input (gitignored)
parsed/               # generated Parquet star schema + _manifest.json (gitignored)
normalized/           # career_steps.parquet, education.parquet, mappings/ + _manifest.json
edu_clean/            # education entity resolution (school/degree/field); see FINDINGS.md
career_clean/         # career entity resolution (company/title/occupation/employment_type);
                      #   PLAN.md, FINDINGS.md, SELF_EMPLOYED_PLAN.md
paths/                # stage 3: temporal + sequencing spine -> transitions edge list; README.md
transition_network/   # stages 4-5: build + analyze transition networks; README.md
cohorts/              # cohort analysis (entry/grad cohorts, scarring, survival); README.md
industry/             # Layer 6a: 4-level industry classifier (taxonomy + M1/M3/M5 + LLM); README.md
reference/            # external taxonomies (O*NET-SOC, CIP, BLS); see reference/README.md
exploration/          # read-only data-profiling scripts
*_PLAN.md             # design docs: CAREER_PATHS, CAREER_TRANSITION_NETWORK, INDUSTRY, ...
normalization_regression_checks.py   # fast CPU checks for normalization edge cases
```

## Tests & checks

```bash
uv run python normalization_regression_checks.py          # normalization edge cases
uv run python -m career_clean.se_tests                    # self-employment classifier
uv run python -m paths.spine_tests                        # spine: kind ladder, gaps, seniority
uv run --group graph python -m paths.seniority_tests      # revealed seniority + transition typing
uv run python -m cohorts.cohort_tests                     # cohort panel integrity + sanity
uv run python -m industry.tests                           # industry taxonomy + classifier
uv run python -m industry.run_industry                    # industry gold eval (per-level P/R)
uv run python -m career_clean.run_final_compare           # career ER benchmark
uv run python -m edu_clean.run_final_compare --single-threshold   # education ER benchmark
```
