# Making sense of the data for interactive career-path illustration

Goal: render **career paths** interactively — a person (or a cohort) as an
ordered, timed sequence of career states, with the flows between them
explorable. The entity-resolution work in `career_clean/` and `edu_clean/`
cleaned the *fields of a single step* (company, title, occupation, school,
degree). A **path** is a different object: it is *steps in time, in sequence,
with transitions between them*. Almost none of that spine exists yet.

Self-employment (see `career_clean/SELF_EMPLOYED_PLAN.md`) is **one node-attribute
problem**. This document is the superset: every other artifact and problem you
must handle to go from cleaned fields to drawable paths. Everything below is
measured on the parsed tables.

---

## 1. What a "career path" actually requires

A path is a graph: **nodes** (career states) connected by **edges**
(transitions), laid out on a **time axis**, optionally **aggregated** across
people for flow visualization (Sankey / alluvial / timeline). That decomposes
into six problem layers, in dependency order:

```
6. Aggregation & visualization grain   (flows across people)
5. Transitions / edges                 (job -> job, promotion vs move vs gap)
4. Sequence & concurrency              (order, overlap, gaps within one person)
3. Temporal model                      (parse dates -> intervals; anchor "Present")
2. Node attributes / axes              (org, role, occupation, seniority, type,
                                         industry, location)  <- mostly done
1. The record model                    (grouped positions; one clean step table) <- done
```

Layers 1–2 are largely solved (the `career_clean` backbone + the self-employed
axis). **Layers 3–6 are the new work, and 3 is the foundation everything else
stands on.** Below, each layer with what the data forces you to handle.

---

## 2. Layer 3 — Temporal model (the spine; currently untouched)

Dates are stored as **raw strings** and never parsed. Measured on 9.08M
experience rows:

| fact | value | consequence |
|---|---|---|
| start & end present | 87.4% | **12.6% of steps cannot be placed in time at all** |
| `"Mon YYYY"` (e.g. `Jan 2022`) | 74.6% | month precision |
| `"YYYY"` only (e.g. `2005`) | 12.8% | **year precision — granularity flag needed** |
| `end_date == "Present"` | 20.1% (1.82M) | **open intervals — need a snapshot anchor date** |
| `duration` free text (`"4 years 3 months"`) | present | redundant cross-check on the interval |

**What to build:** a date parser → `(start_date, end_date, start_granularity,
end_granularity, is_ongoing)` typed interval per step. Decisions it must encode:

- **"Present" anchor.** Open intervals must be closed at the **snapshot date**
  (the scrape time, ~Feb 2025 per the raw files), not "today" — otherwise every
  ongoing role silently lengthens. Store the anchor explicitly.
- **Year-only granularity.** `2005`–`2008` and `Mar 2005`–`Feb 2008` should not
  be compared as if equally precise; carry a granularity flag and, for overlap
  math, treat a year as `[Jan..Dec]` with an `imprecise` marker.
- **Missing dates (12.6%).** A step with no dates can still be a node but has no
  position on the time axis. Decide: place by sequence-order only, or exclude
  from the timeline view. Don't silently drop.
- **Sanity bounds.** Negative durations (end < start), future starts, and the
  696-experiences-per-profile outliers are data errors to flag, not plot.
- Cross-check parsed interval against the `duration` string to catch parse bugs.

This layer unlocks tenure, ordering, gaps, age-of-career, and time-binning — i.e.
everything visual.

---

## 3. Layer 4 — Sequence & concurrency (paths are not linear chains)

Average 4.5 steps per profile (median 4). But careers **overlap**:

- **281,004 profiles (14% of those with a current role) have ≥2 concurrent
  "Present" roles** — a main job + a side gig / board seat / advisory / their own
  LLC. A path is a set of *overlapping intervals*, not a single chain.
- The **grouped-position model** (already documented): a multi-role experience is
  a *within-company progression* (promotions). Its `positions` children are an
  inner sub-path — promotions, not job changes.

**What to build:** a per-profile sequencer that (a) orders steps by start date,
(b) detects **overlap** (concurrent roles) vs **succession** (one ends, next
begins) vs **gaps** (gap between end and next start — possible unemployment /
break / missing data — *can't tell which*, so label as "gap", don't infer), and
(c) distinguishes **promotion** (same company / same `company_id`, role level
changes, via the positions children or back-to-back same-employer steps) from a
**move** (employer changes). Concurrency must be a first-class output — the viz
needs to show parallel tracks, and naive "next job" edges across concurrent roles
produce garbage flows.

---

## 4. Layer 5 — Transitions / edges (what flows in the diagram)

The edge is the unit of an interactive flow view ("what do Software Engineers do
next?"). Define a transition as an ordered pair of *successive primary steps* for
one person, after concurrency is resolved (pick the primary role when several
overlap — e.g. longest / most-senior / non-side-gig). Each edge carries:

- **from-state → to-state** on a chosen axis (occupation, seniority, industry,
  employer, location — see Layer 6 grain);
- **kind**: promotion (within employer) | lateral | move (employer change) |
  into/out-of self-employment | exit (to retired/unemployed/education) | gap;
- **dwell time** (tenure in the from-state), **gap length**, and **direction** on
  the seniority axis (up/flat/down).

Edge cases the rules must handle: the same-company multi-role promotion chain;
overlapping roles (collapse to the primary, or emit parallel edges intentionally);
self-employment entry/exit (the `employment_type` axis from the self-employed
plan **is** a path state — "left BigCo → went freelance" is a key transition
type); education interleaved mid-career (a degree is a node too, Layer 6).

---

## 5. Layer 6 — Axes you still need to resolve (node attributes beyond the title)

Paths are drawn on a chosen axis. `career_clean` gives **role / seniority /
occupation**; the self-employed plan adds **employment_type**. Two high-value
axes remain only partially resolved:

### 5a. Industry / sector (mostly missing, high value for flows)
`cc_industry` is sparse and noisy (FINDINGS notes it). Industry is the most common
axis for career-flow diagrams ("who moves from finance to tech?"). **Build a
`company_id → industry` crosswalk** (from the in-data industry where present, or
an external NAICS/LinkedIn-industry reference), so each step inherits an industry.
This is the org-side analogue of occupation on the title side.

### 5b. Geography / location (present but very messy — its own ER problem)
`experience.location` is 64.7% present and badly inconsistent — the *same* place
appears as `Greater New York City Area`, `New York, NY`, `New York, New York,
United States`, `New York City Metropolitan Area`. Geographic mobility is a path
dimension (relocations). **Build a place canonicalizer** to a hierarchy
(city → metro → region → country); profile `city`/`country_code` are 100%
populated and a useful backstop/default. Treat free-text metro aliases as a
curated crosswalk (same ratchet pattern as company aliases). Geocoding here is a
real sub-project; scope it explicitly.

### 5c. Seniority progression
The seniority axis already exists (`title:level|base`). Over the time axis it
becomes the **advancement** signal (IC → manager → director). No new resolution
needed — it just needs the temporal model under it.

---

## 6. The other artifacts (the non-spine tables)

The star schema has many one-to-many tables besides `experience`. For path
illustration they are **timeline enrichments**, not the spine — place them on the
time axis as annotations, normalize them lightly, don't entity-resolve them to
the same depth:

| table | role in a path | has a date? | treatment |
|---|---|---|---|
| `education` | nodes on the spine (school↔work bridge) | start/end_year (sparse: 25.6% / 21.6%) | already cleaned in `edu_clean`; **link graduation → first job** where dated |
| `certifications` | skill/credential milestones | `date_issued` | normalize issuer + name; plot as markers |
| `volunteer_experience` | parallel unpaid track | start/end_date | same shape as experience; optional concurrent track |
| `organizations` | memberships | start/end | markers |
| `honors_and_awards` | milestones | `date` | markers |
| `projects`, `publications`, `patents` | output/impact over time | start/end / date | markers, optional density-over-time |
| `courses`, `languages` | static skills | none | profile-level attributes, not timeline |
| `posts`, `activity`, `recommendations` | engagement, not career structure | — | out of scope for paths |
| `people_also_viewed`, `similar_profiles` | graph neighbors | — | possible cohort/similarity feature, not a path element |

The `about` (65.5%) and `position` (98.6%) profile headline fields are
free-text summaries — useful for labeling/validation, not structure.

**Key point:** these need only **date parsing (reuse Layer 3) + light
normalization**, not their own ER stack. Education is the exception — it is a
genuine spine node and the school→work bridge is worth building (all 2.0M
profiles with experience also have education rows), limited only by edu date
sparsity.

---

## 7. Data-quality & honesty caveats (must be visible in the UI)

Interactive illustration invites over-reading. Bake these in:

- **Selection bias.** LinkedIn profiles skew to white-collar, English-speaking,
  professional-class, and the recently-active. Paths are *not* a population
  sample. Label cohorts, never imply representativeness.
- **Recency / backfill bias.** People document recent roles more fully; old steps
  lose dates and detail (12.8% year-only skews older). Time-trend reads are
  confounded.
- **"Present" staleness.** 20% of steps are open at the snapshot; a profile last
  edited years before the scrape shows a stale "current" job.
- **Unobservable gaps.** A gap between steps may be unemployment, caregiving,
  travel, or just a missing entry — the data **cannot** distinguish them. Render
  as "gap (unknown)", never "unemployed".
- **Truncation.** Titles cap at 100 chars; headline-style titles are clipped.
- **Garbage profiles.** 696-step profiles, duplicate steps (0.35%) — filter with
  sanity bounds before plotting.
- **Survivorship in occupation coding.** Only ~22% of titles get a deterministic
  SOC code (FINDINGS); flows on the occupation axis under-represent the uncoded
  tail unless the review-queue coverage is filled.

---

## 8. Phased plan

**Phase A — Temporal spine (Layer 3).** Date-string → typed interval with
granularity + `is_ongoing` + explicit snapshot anchor; sanity bounds; duration
cross-check. *Foundational — do first.* Add to a new `paths/` module mirroring
`career_clean/` conventions; benchmark coverage and parse-error rate.

**Phase B — Per-profile sequencing (Layer 4).** Order steps, classify
overlap/succession/gap, fold the grouped-position promotion chains, pick the
primary role among concurrent ones. Emit a clean per-profile step sequence.

**Phase C — Transitions (Layer 5).** Edge table (from-state, to-state, kind,
dwell, gap, seniority-direction), parameterized by the axis. Wire in the
`employment_type` self-employment entries/exits as first-class transition kinds.

**Phase D — Missing axes (Layer 6).** `company_id → industry` crosswalk; location
canonicalizer to a place hierarchy. Both are curation-ratchet jobs (the FINDINGS
pattern), not models. Industry first (higher analytic value, cleaner source).

**Phase E — Aggregation & viz grain (Layer 6 top).** Choose the drawable grain —
you cannot plot 2M unique paths. Aggregate edges into **flows between canonical
states** on a selectable axis (occupation×seniority, industry, employer, region),
with min-support thresholds. Output a transition matrix / Sankey-ready edge list
+ a per-profile timeline payload. This is the layer the interactive UI binds to.

**Phase F — Enrichment artifacts (§6).** Date-parse and light-normalize the
auxiliary tables; build the education→first-job bridge; expose as timeline
markers / parallel tracks.

**Phase G — Quality gating (§7).** Sanity filters, bias/uncertainty flags surfaced
as UI affordances (gap = unknown, ongoing = as-of-snapshot, uncoded = excluded).

Recommended order: **A → B → C** is the critical path to a *minimal* drawable
career path (timed, sequenced, with transitions). D/E broaden the axes and make
it aggregate-explorable; F/G enrich and keep it honest. Each phase is CPU,
deterministic, and benchmarked the same way the existing modules are — no new ML
on the critical path.

---

## 9. Open decisions to confirm

1. **Snapshot anchor date** — confirm the exact scrape date to close "Present"
   intervals consistently.
2. **Primary-role policy** for concurrent steps — longest? most senior?
   non-side-gig? (drives every transition).
3. **Default visualization axis & grain** — occupation×seniority vs industry vs
   employer vs geography; and the min-support threshold for a flow to render.
4. **Gap semantics** — minimum gap length to surface; how to render unknown gaps.
5. **Industry reference** — in-data `cc_industry` only, or adopt NAICS / the
   LinkedIn industry taxonomy?
6. **Geography depth** — full geocoded hierarchy vs a curated metro/country
   crosswalk only?
7. **Scope of enrichment artifacts** — which auxiliary tables make it onto the
   timeline for v1 (recommend: education + certifications + volunteer).
8. **Person vs cohort view** — is v1 single-profile timelines, aggregate flows,
   or both? (changes what Phase E must emit first).
