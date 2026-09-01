# Career-path / transition-network spine (Layers 3-5)

Turns `normalized/career_steps.parquet` (entity-resolved steps from
`career_clean`) into the temporal + sequenced **edge list** that every
career-transition-network grain aggregates from. This is the shared prerequisite
called out in `../CAREER_TRANSITION_NETWORK_PLAN.md` §3 and
`../CAREER_PATHS_PLAN.md` Layers 3-5.

## Run

```bash
uv run python -m paths.build_spine            # -> paths/steps.parquet, transitions.parquet, _manifest.json
uv run python -m paths.build_spine --force    # overwrite
```

All-CPU DuckDB; **~17s** on the full 10.8M steps (the per-profile concurrency
self-join hashes on `linkedin_id`, so it stays cheap). The GPU is intentionally
not used here — this is relational date-parse + window + bounded self-join. The
GPU payoff is downstream and this output is built to feed it: `transitions.parquet`
is the input to GPU graph algorithms (cuGraph centrality / community detection,
Phases 3-4) and the propose-only torch embedding layer (Phase 8).

## Outputs (full run, snapshot anchor 2025-02-19)

| | rows | notes |
|---|---|---|
| `steps.parquet` | 10,798,352 | 1,999,961 profiles; **99.25% datable**; 21.5% ongoing |
| `transitions.parquet` | 6,018,391 | edges between successive **primary** steps |

`steps`: 165,665 negative-duration + 182,634 future-start rows **flagged**
(`bad_*`) and excluded from edges, not dropped; ~2.5M steps (23%) flagged
`is_concurrent_secondary` (side-gigs/board seats removed from the primary
timeline). Transition kinds: move 74.6%, lateral 18.3%, into-self-employment
3.2%, out-of-self-employment 1.7%, promotion 1.3%, demotion 0.4%, exit 0.3%,
education-entry 0.2%. Of the edges, 1,767,538 carry a real gap (`has_gap`,
≥1 empty month) and 892,268 a genuine interval overlap (`has_overlap`,
≥2 months — concurrency that slipped under the Layer-4 threshold).

> Promotion/demotion are intentionally *small*: a move is only scored
> directional when **both** endpoints carry an explicit seniority word. Most
> LinkedIn titles do not (the empty string is a real title with no marker), so
> the honest count is ~100k directional moves; the rest of the same-employer
> moves are `lateral` (direction unknown), not silently up/down.

## What each layer does

- **Layer 3 (temporal).** Date strings → typed interval. `"Mon YYYY"` = month
  precision, `"YYYY"` = year precision widened to `[Jan 1 .. Dec 31]`,
  `"Present"` closed at `SNAPSHOT_DATE`, NULL → undatable. Carries
  `start/end_granularity`, `is_ongoing`, `datable`, `tenure_months`, and sanity
  flags (`bad_negative_duration`, `bad_future_start`).
- **Layer 3b (seniority ordinal).** career_clean stores `seniority_level` as a
  comma-joined token *set* (`chief,executive`); collapsed here to one ordinal =
  rank of the most-senior **named** token, or **NULL** when there is no named
  token (the empty string, or only numeric `lvlN` bands). Direction is scored
  only when both endpoints are non-NULL, so unmarked titles never fake an
  up/down. See `common.SENIORITY_RANK`.
- **Layer 4 (sequence + concurrency).** A datable step is
  `is_concurrent_secondary` when another datable step of the same person overlaps
  it by ≥ `CONCURRENCY_OVERLAP_FRAC` of the shorter interval **and** outranks it
  (in-workforce → dwell → seniority → earlier start → row_id). Those are dropped
  from the primary timeline.
- **Layer 5 (edges).** Successive primary steps → one transition row carrying
  **both endpoints on every axis** (occupation, role+seniority, employer,
  employment-type, location) plus `kind`, `seniority_direction`, `dwell_months`,
  `gap_months`/`has_gap`, and `overlap_months`/`has_overlap`. `kind` priority is
  **explicit**: `exit` (to retired/unemployed/homemaker) > `education_entry` (to
  student) > `into`/`out_of_self_employment` > same-employer `promotion`/`lateral`/
  `demotion` > `move`. Gaps/overlaps are computed from the **month-floors** of the
  two boundaries, so a same-month A-ends/B-starts handoff is neither. `exit` and
  `education_entry` are **edge labels, not graph sinks** — a person can have later
  edges (e.g. un-retiring).

## Seniority & transition typing (`seniority.py` + `build_spine` Layer 3b/5)

Each step also carries a fused **`seniority_score` ∈ [0,1]** (+ `seniority_confidence`):
the lexical within-role level (deterministic backbone) blended with a **revealed
cross-role level** learned by SpringRank on our own `role` transition graph
(`paths/seniority.py`, anchored in sign to the lexical layer). This covers the
~84% of moves that carry no seniority word — **93.5% of steps get a score**, vs
~16% from the lexical layer alone.

Each edge then carries `delta_sen`, **`transition_type`**, and
`transition_confidence` (additive — `kind`/`seniority_direction` are unchanged).
`transition_type` priority: `exit` > `education_entry` > `into`/`out_of_self_employment`
> `occupation_change[_up/_down]` (SOC major-group change) > same-employer
`promotion`/`demotion`/`lateral` > between-firm `employer_move_up`/`_down`/`_lateral`/
`employer_move` (neutral when seniority isn't confident). Δsen is on a common
cross-node scale, so up/down is **valid across companies** — the capability the
old lexical-only `kind` lacked. Result (calibrated asymmetric τ): **65.6% of edges
typed with a confident direction**, up from 15.8% — of which **15.8% are
high-trust** (`direction_from_lexical`, both endpoints carry a seniority word) and
the rest are revealed-only *proposals* (the `down` direction in particular is only
~chance-accurate vs lexical truth — treat as a proposal, filter on
`direction_from_lexical` for trustworthy direction). Built as a **bootstrap**
(SpringRank learns from the
emitted edges, then types them — two spine passes; see root README). Revealed
seniority is **propose-only** with calibrated confidence; the lexical layer stays
the precision backbone. Validate: `uv run --group graph python -m paths.seniority_tests`.

## Policy knobs (one place: `common.py`)

`SNAPSHOT_DATE`, `MAX_STEPS_PER_PROFILE` (garbage bound, 100),
`CONCURRENCY_OVERLAP_FRAC` (0.5), `GAP_MONTHS_MIN`, `WORKFORCE_TYPES`,
`SELF_EMPLOYED_TYPES`, `EXIT_TYPES`, `SENIORITY_RANK`. These are the
`CAREER_PATHS_PLAN` "open decisions"; change here and re-run.

## Known limitations (carry into any network read)

- **Primary-role policy is a choice** (dwell-first). Changing it changes every
  edge — it is a `common.py` knob, not a fact.
- **Concurrency that slips under the threshold becomes an edge.** Two roles
  overlapping by < `CONCURRENCY_OVERLAP_FRAC` of the shorter both stay primary and
  chain as a "move" though they were held simultaneously; `has_overlap` (≥2mo,
  892k edges) flags these so a network build can exclude them
  (`build_network ... --exclude-overlap`). Lower the fraction to be stricter.
- **Year-only intervals are widened to a full year**, so a year-granularity role
  can out-rank a shorter month-precision concurrent role on dwell (only exact-dwell
  ties are broken toward the finer record). Dwell on year-granularity steps is
  imprecise by construction; carry `start/end_granularity`.
- **Occupation grain inherits ~22% deterministic SOC coverage** from
  `career_clean`; occupation-axis flows under-represent the uncoded tail until the
  review queue is filled.
- **Industry & geography axes are not yet resolved** (`CAREER_PATHS_PLAN` Layer
  6); `from/to_location` is raw text, not canonicalized.
- All `CAREER_PATHS_PLAN §7` biases apply (LinkedIn selection, recency/backfill,
  "Present" staleness, unobservable gaps rendered as `has_gap`, not "unemployed").
