# Portal redesign — from comparison engine to possibility-space comprehension

**Date:** 2026-07-13. **Status:** approved direction from user; this doc is the
implementation contract for the parallel build.

## Why we're redesigning

The current portal (`portal/share_template.html`) is architecturally sound (generated
build, green/amber badge honesty system, suppression discipline) but editorially it is a
*comparison engine*: RR-vs-baseline leads the fan, pillars score majors against all
graduates, the launchboard benchmarks mover premiums. The user's new direction:

1. **Comprehension over comparison.** The headline product is the *career possibility
   space* of humanities majors — its intensely high diversity — not "humanities vs
   baseline" scorecards.
2. **Serve anxious undergrads.** A student considering a humanities major (or mid-degree
   with career-launch anxiety) should be able to see exactly what options look like at
   different points in a career: **snapshots** (year 1 / 3 / 5 / 10) and **arcs**
   (curves, pathways, mobility styles).
3. **Choices.** Show how concrete decisions — double majoring, grad school, internships,
   service years (Peace Corps / AmeriCorps / TFA…), military, self-employment — relate to
   the possibility space. (Minors and study abroad are free-text-only in the data:
   honest "not measurable yet" cards.)
4. **Myth disruption.** A dedicated surface that names common myths about humanities
   majors and answers each with a computed number.

Everything stays on the existing honesty rails: LinkedIn-survivor cohorts, equal
observation windows, no wage claims, no causal claims, green = pipeline / amber =
editorial.

**Suppression bar loosened (user directive, 2026-07-13): the global named-cell bar
drops from n≥40 to n≥10, across the board** (fan cells, pathways, distinctive
destinations, curve points, choice-subset fans, named employers). `MIN_SUPPORT` in
`portal/common.py` is the single knob; every consumer and test reads it. The below-bar
facet floor of 5 (grad degree types / Medicine) stays. Methods copy must be updated to
promise 10, not 40 — no surface may still claim the old bar.

---

## Part 1 — New information architecture (6 views)

| # | View (nav label) | Purpose | Fate of old content |
|---|---|---|---|
| 1 | **Overview** | Thesis: "there is no default job." Real-data hero (destination field seeded from actual fan/breadth data, replacing the decorative canvas). Door cards to the other views. | Rework hero + doors |
| 2 | **The possibility space** | Descriptive-first explorer per major: diversity stat band, destination fan (share-ordered), drill-downs, employer field, sectors. | Rework of "Portal" view |
| 3 | **The first decade** | Snapshots & arcs for the career-anxious: timeline scrubber (y1→y3→y5→y10 fans), long-view curve to y20, mobility-styles panel, named pathways, grad-timing. | Absorbs launchboard + curve + paths |
| 4 | **Choices** *(new)* | One card per choice: participation per major, destination shift where supported, selection-effect caveats. | New |
| 5 | **Myths** *(new)* | Myth cards: editorial myth statement + computed rebuttal (rendered from JSON at runtime, green) + link into the view that shows it. | New |
| 6 | **Data & methods** | Updated: choice definitions, new suppression notes, funnel table stays. | Extend |

**The Stories wizard is retired as a view.** Its launchboard panels move to "The first
decade"; its best amber glosses move inline next to the panels they annotate; its
editorial route walks (invented narrative chains) are dropped — the real 2-stage
pathways panel supersedes them. Old template remains in git history and
`share/deprecated/`.

### Comparative stance (goal 1)

- Fan default order = **share** (descriptive). RR moves from the bar label to a
  secondary chip revealed by an opt-in **"Context vs all graduates"** toggle (off by
  default; also governs the baseline overlay on the curve and RR chips elsewhere).
- The "Most distinctive" fan ordering stays (it's a diversity story, not a scorecard).
- **Pillar meters are retired** from the main flow (FINDINGS already flags them as a
  constructed framing device); their parity message survives as a Myths card.
- Baseline never disappears from Methods; it's context, not the lead.

### Diversity as a first-class stat (goal 1)

New per-major (and baseline) `diversity` block drives the possibility-space stat band:

```
diversity: {
  classified_n,            # windowed persons with a classified y10 endpoint
  unclassified_share,      # restated here for honest adjacency
  effective_destinations,  # inverse-Simpson (1/Σp²) over classified fan shares, renormalized
  groups_reached,          # fan cells clearing MIN_SUPPORT (of 23)
  top_bucket_share,        # = fan[0].share (of whole windowed pop)
  top3_classified_share    # top-3 groups' share of classified endpoints
}
```

Front-end pairs this with existing breadth KPI (occupation nodes of 824) and
employer_field dispersion (singleton share, top-10 share) into one "how wide is this
field" band. The "plurality is a minority" computed lead stays.

---

## Part 2 — New pipeline work (`portal/choices.py` + `analyses.py` additions)

Feasibility (probed 2026-07-13 against committed parquets, distinct persons):

| Choice | Per-major viable? | Evidence |
|---|---|---|
| Double major (2+ distinct cip2, level 4) | **Yes** for participation; fan pooled-only | 211–602 anchored per major; 3,028 pooled A1+A2 |
| Grad school (level 6/7) | **Yes**, incl. level & field | 669–2,108 both-anchored per major |
| Internship (title_raw intern, early window) | **Yes** | 9,411 anchored humanities |
| Military (company_raw branch names) | **Yes** | 2,191 anchored humanities |
| Service year (Peace Corps/AmeriCorps/TFA/Fulbright/City Year) | **Pooled only** | 49–167 anchored pooled |
| Self-employment (employment_type) | **Yes** | ~459k SE steps repo-wide |
| Minors | No — free text only | ~50–60k persons mention, unparsed |
| Study abroad | No — free text only | ~9–13k persons mention |

### Rules (non-negotiable)

- All choice outcomes computed on the **windowed y10 cohort** under the existing window
  discipline; choice flags are person-level joins on the membership spine
  (`build_membership`) with **no fan-out** (tested).
- Named cells clear `MIN_SUPPORT=10` (the newly loosened global bar); a choice-subset
  fan that can't populate ships `null` + a suppressed-count, never a thinner bar. With
  the 10 bar, per-major fans should populate for most choices; service-year programs
  may clear per-major for the larger majors and stay pooled otherwise.
- Every choices surface carries the **selection caveat**: these are descriptive
  associations among LinkedIn survivors, not causal effects of the choice.
- Definitions documented in the JSON (`choices_notes`) and Methods: e.g. grad flag =
  grad degree **started ≤5y post-anchor** (aligns with existing `grad_track`);
  internship/military/service = matching step starting in [anchor−4, anchor+5] (probe
  and finalize; document the chosen window); self-employment = any post-anchor step with
  `employment_type IN ('business_owner','self_employed')`.
- Baseline gets the same participation stats (context sentence, not a scorecard).

### JSON contract additions

Per major (`majors.*` and `baseline` where meaningful):

```
diversity: {...as above}
choices: {
  double_major:   {n_windowed, participation_share, top_partners: null,  fan: null|[...], note}
  grad_school:    {participation_share, fan_grad: [...]|null, fan_nograd: [...]|null,
                   unclassified_share_grad, unclassified_share_nograd}   # grad_track stays as-is
  internship:     {n_windowed, participation_share, fan: [...]|null, unclassified_share, window}
  military:       {n_windowed, participation_share, fan: [...]|null, unclassified_share, window}
  self_employment:{ever_share, median_years_to_first, n_windowed}
}
```

Top-level:

```
choices_pooled: {          # union of the five majors' windowed cohorts, dedup'd
  population_def, n_windowed,
  double_major:  {n, participation_share, top_partners: [{cip2, label, n}], fan: [...]},
  service_year:  {programs: [{name, n}], n_any, fan: [...]|null, pooled_only: true},
  self_employment: {top_groups: [{group, share}]}   # from employment_type + SOC pooled
}
choices_not_measured: {minors: {persons_mentioning, note}, study_abroad: {...}}
choices_notes: {causal_caveat, definitions...}
```

Fan objects everywhere use the existing shape `{group, n, share, rr}` (rr retained for
the context toggle; share of the choice-subset population; unclassified reported
alongside).

Snapshots need **no new pipeline**: the front end assembles y1 (`launchboard.
first_destinations`), y3/y5 (`launchboard.outlook`), y10 (`fan`) into the scrubber.

### Tests (extend `portal/portal_tests.py`)

Choice-flag joins don't fan out; participation shares ∈ [0,1]; every named fan cell in
any choices block ≥ `MIN_SUPPORT`; per-major choice fans are null when unsupported;
tests reference `common.MIN_SUPPORT`, never a literal 40; diversity identities
(effective_destinations ≤ groups classified; baseline diversity present; top_bucket
matches fan[0]); byte-reproducibility preserved.

---

## Part 3 — Myths view (computed rebuttals)

Each card: **the myth** (amber, named plainly) → **the counted reality** (green,
computed at render time from PORTAL fields — never hard-coded) → link into the relevant
view. Where the data only partially rebuts, the card says so (voice: earnest,
evidence-forward, no snark).

| # | Myth | Computed rebuttal (fields) |
|---|---|---|
| M1 | "Humanities has one default job (teacher / barista)." | `fan[0]` share → complement ("87% are somewhere else"); groups_reached; per-major |
| M2 | "You won't advance." | `curve` y10/y20 vs baseline (converges); `kpi.up_share` vs baseline (~parity) |
| M3 | "Humanities careers are unstable drifting." | `launchboard.stability` mover y5 seniority ≥ stayers; late-move gap share lower |
| M4 | "The degree is only useful with grad school." | `grad_track.any` share → majority go straight to work; grad share shown honestly |
| M5 | "You end up in a narrow niche." | `diversity.effective_destinations`, `kpi.breadth`, employer singleton share |
| M6 | "You're locked out of business and tech." | fan shares for Management / Business & Financial / Computer & Mathematical (with honest RR<1 context where true) |

---

## Part 4 — Execution (parallel subagents)

- **Agent A — pipeline**: `portal/choices.py` (new), `analyses.diversity`, wiring in
  `build.py`/`run_portal_data.py`, tests, full run + bias sanity. Touches only
  `portal/*.py`.
- **Agent B — front-end**: restructure `share_template.html` to the new IA. Keeps the
  `__PORTAL_DATA_JSON__` seam, helper/chart layer, badge system, theming, a11y twins,
  suppression rendering. Adds hash routing. Develops against current
  `portal_data.json` + a mock of the new keys; **must render honest empty states when
  new keys are absent/null** (so the template is valid against both old and new JSON).
- **Integration (main session)**: run pipeline + 33-test suite + new tests, regenerate
  share build, headless Playwright verification, republish artifact (same URL), update
  FINDINGS.md / memory.

Visual identity unchanged: violet #4a3aa7/#9085e9, serif display, single self-contained
file, dark/light theming.
