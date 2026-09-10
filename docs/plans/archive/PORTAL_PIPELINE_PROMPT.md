# Implementation prompt: build the pipelines behind the Pathways portal

You are working in `/home/alex/linkedin-analysis`, a research codebase that analyzes ~2M LinkedIn
career profiles. A design prototype of an interactive "career possibility space" portal for
humanities advocacy (the NHA "Pathways" toolset) exists, and every per-major number in it is
currently an **illustrative placeholder**. Your job is to build the missing pipeline — the
education→career join and the per-major analyses — so that every placeholder can be replaced with
a computed, validated number. The end deliverable is a single JSON payload (contract below) plus
the code, tests, and documentation that produce it.

Work module-by-module, verify every column name against the actual parquet schemas before using
it, and follow this repo's established conventions: a package directory with `common.py`, small
single-purpose modules, `run_*.py` drivers, `results/*.json` outputs, a `_manifest.json` recording
inputs/outputs/row counts, a `*_tests.py` file, and a `FINDINGS.md` written after the numbers are
in. Read `METHODOLOGY.md` and `docs/audits/2026-06-10-edu-clean-audit.md` first.

## What already exists (verified against the repo as of 2026-07-07)

- `normalized/education.parquet` (~3.58M rows): per-degree records with resolved CIP codes on
  49.1% of rows, NHA humanities flags (`nha_level`: L1 narrow humanities ⇒ L2 +humanistic social
  sciences ⇒ L3 liberal arts, enforced nested) and `humanities_field_group`. **The audit found
  these flags have zero downstream consumers — the education→career join has never been built.**
  Tier counts (as of the 2026-07-07 build — see `edu_clean/results/tier_counts.json`,
  computed at 58.8% CIP coverage): L1 = 240,277; L2 = 415,908; L3 = 689,836.
- `paths/steps.parquet`: 10,798,352 career steps across 1,999,961 profiles, keyed on the same
  `linkedin_id` as education. 99.25% datable. Carries `seniority_score` ∈ [0,1] (93.3% coverage),
  SOC occupation codes (~22% of titles deterministically coded — a known ceiling), role canonicals
  (97.5% coverage), employment type. `SNAPSHOT_DATE = 2025-02-19` in `paths/common.py`.
- `paths/transitions.parquet`: 6,018,391 person-level edges with `transition_type` (promotion,
  employer_move_up/lateral/down, occupation_change_*, into/out_of_self_employment, …),
  `relative_risk` (weight/expected, the size-controlled over-representation measure), and
  `p_transition`.
- `transition_network/`: the directed network per axis (occupation: 824 nodes / 39,310 edges;
  role: ~1.9M nodes). Node tables carry degree, strength, PageRank, SpringRank; a 1,495-edge
  disparity-filter backbone exists for the occupation axis.
- `industry/`: 4-level custom taxonomy crosswalked to NAICS (17 L1 macro-sectors), deterministic
  coverage L1 ≈ 42% of steps.
- `cohorts/`: existing machinery for equal-observation-window panels (entry-year anchoring,
  fully-observed-window logic). Reuse its patterns for the year-N horizon logic.

## The five majors in the prototype (extensible design required)

Define majors as named CIP-family bundles so new majors are config, not code:

| Portal major | CIP families |
|---|---|
| English & Literature | 23 |
| History | 54 |
| Philosophy & Religion | 38 + 39 |
| Fine & Performing Arts | 50 |
| Communication & Media | 09 (this one is L2, not L1 — the portal labels boundaries explicitly) |

## Core design decisions you must make and document (proposals given; improve if the data says otherwise)

1. **Person↔degree assignment.** One person may hold several degrees. Propose: analysis unit is
   (person, qualifying degree); a person enters a major's population if they hold a bachelor's-level
   degree in that major's CIP bundle. Document handling of double majors (appear in both), graduate
   degrees, and missing degree levels.
2. **Graduation anchor.** The qualifying degree's end year. Drop records without a usable end year;
   report the drop rate.
3. **Equal observation windows.** For any "year-10" statistic, include only people whose anchor is
   ≥10 years before `SNAPSHOT_DATE` (i.e., graduation ≤ 2015) so every subject has a full window.
   Same discipline per horizon. This is non-negotiable — it's the repo's core comparison rule.
4. **Baseline population.** "All graduates" = all persons with any CIP-coded bachelor's record and
   a usable anchor, under the same window discipline. All `vs chance` / parity numbers use this
   baseline, computed by the same code path.
5. **Occupation grain.** SOC major group (23 groups) for the destination fan; role canonicals for
   pathway mining (SOC's 22% coding ceiling under-represents the tail — state this coverage number
   next to every occupation-grain result).

## What to compute (each item maps to a placeholder in the portal)

For each major AND the baseline, under equal-window discipline:

1. **Record and person counts** — exact degree-record and distinct-person counts per major, per
   boundary tier (the tier totals above are already computed; reconcile against them).
2. **Destination fan** — primary occupation group at year 10: share of the major's population, plus
   relative risk vs the baseline share. Report the share of the population that is unclassifiable at
   that horizon (no codable step) as its own honest bucket, not silently dropped.
3. **Breadth** — distinct occupation-network nodes (of 824) reached by the major's population at any
   point post-anchor, with a minimum person-support per node (propose n ≥ 5) so one wanderer doesn't
   inflate breadth.
4. **Distinctive destinations** — count of destination occupations with RR ≥ 1.5 and person-support
   ≥ 40.
5. **Upward-move share** — share of the major's post-anchor transition edges typed upward
   (promotion, employer_move_up, occupation_change_up). Do NOT compute downward equivalents as
   headline numbers — the repo's validation found revealed "down" direction is near-chance (~50%);
   if you must report it, carry that caveat in the output.
6. **Median dwell** — median months per step, post-anchor.
7. **Long view** — median `seniority_score` at years 0,2,4,…,20 since anchor, major vs baseline,
   with per-point n. Handle right-censoring by only including people observable at each horizon
   (report n per point; suppress points with n < 40).
8. **Sectors reached** — industry L1 distribution at year 10 (top 8 + other), with the ~58%
   industry-unresolved tail reported explicitly.
9. **Named pathways** — frequent within-major route mining on the role axis: contiguous 3–4-step
   role-canonical chains, ranked by distinct-person support, with median dwell per stage. Emit the
   top routes with n ≥ 40; report the count of routes suppressed below threshold (the UI displays
   this). **Unexpected pathways**: routes whose terminal occupation group is NOT among the major's
   top-5 fan destinations but whose support still clears n ≥ 40 — flag these `"unexpected": true`.
   Propose and document a better definition if mining suggests one (e.g., terminal-sector RR below
   1 overall but route-level support high).
10. **Four pillars** — Growth / Stability / Skill / Direction, 0–100 with 50 = baseline parity.
    Substrates: Growth = seniority_score gain over the first 10 years; Stability = median dwell and
    gap-freedom; Skill = mean O*NET Job Zone of occupations reached (`reference/soc_status.parquet`,
    `job_zone_norm`); Direction = upward + deliberate-pivot share of moves. Propose the exact
    normalization (percentile of the baseline distribution is a good candidate), document it, and
    mark the framework as *constructed* in FINDINGS — it is a new framework, not a validated one.

## Output contract

Write `portal/results/portal_data.json`. The example `l1` count below is
illustrative of the field shape only — use the current tier counts (as of the
2026-07-07 build — see `edu_clean/results/tier_counts.json`, 58.8% CIP
coverage: L1 = 240,277 / L2 = 415,908 / L3 = 689,836), not a hard-coded number
that will drift at the next CIP ratchet:

```json
{
  "generated": "<ISO date>", "snapshot_date": "2025-02-19",
  "window_rule": "<one sentence>", "baseline_def": "<one sentence>",
  "boundaries": { "l1": {"records": 240277, "persons": 0}, "l2": {}, "l3": {} },
  "majors": {
    "english": {
      "name": "English & Literature", "cip_families": ["23"],
      "records": 0, "persons": 0, "persons_windowed_y10": 0,
      "kpi": { "breadth": 0, "breadth_of": 824, "distinctive": 0, "up_share": 0.0, "dwell_median_mo": 0 },
      "fan": [ {"group": "Education", "share": 0.0, "rr": 0.0, "n": 0} ],
      "unclassified_share": 0.0,
      "sectors": [ {"sector": "Education", "share": 0.0, "n": 0} ],
      "industry_unresolved_share": 0.0,
      "curve": { "years": [0,2,4,6,8,10,12,14,16,18,20], "median_seniority": [], "n": [] },
      "pillars": { "growth": 0, "stability": 0, "skill": 0, "direction": 0 },
      "paths": [ {"name": null, "stages": [{"role": "", "median_dwell_mo": 0}], "n_persons": 0, "unexpected": false} ],
      "paths_suppressed_count": 0
    }
  },
  "baseline": { "fan": [], "curve": {}, "up_share": 0.0 }
}
```

Numbers only — leave `"name"` on paths null (human naming is editorial, done later). Suppress any
cell with person-support < 40 (emit it as suppressed counts, never as a value). The JSON must be
byte-reproducible from a single driver: `python -m portal.run_portal_data`.

## Guardrails (from this repo's own methodology — violations are bugs)

- Equal observation windows everywhere; never compare a 2019 graduate's year-10 to a 2005 graduate's.
- Gaps are rendered "gap (unknown)" — never inferred unemployment.
- No wage claims, no representativeness claims; these are cohort statistics of LinkedIn survivors.
- Prefer re-derived numbers over stale manifests (a documented drift exists: transition-typed share
  is 65.6%, not the 72.3% an old manifest claims).
- Every module gets tests (`portal/portal_tests.py`) covering: join key integrity (no fan-out on
  linkedin_id), window discipline (no partially-observed person in a windowed stat), suppression
  (inject a tiny cell, assert it's suppressed), nested-tier consistency (L1 ⊆ L2 ⊆ L3), and RR
  sanity (baseline RR ≡ 1.0).
- Write `portal/FINDINGS.md` when done: the real numbers for the five majors, the drop rates at
  each filter, coverage caveats, and anything that surprised you or contradicts the prototype's
  illustrative values.

## Definition of done

`python -m portal.run_portal_data` produces `portal/results/portal_data.json` with all five majors
populated, tests pass, FINDINGS.md is written, and the manifest records inputs and row counts. Do
not modify the prototype HTML; the JSON contract is the interface.
