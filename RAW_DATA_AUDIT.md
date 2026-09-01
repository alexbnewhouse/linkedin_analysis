# Raw-data audit — what else the corpus can say about the humanities possibility space

**Date:** 2026-07-27. **Question asked:** where is there unextracted value in the raw
data for illustrating the *career possibility space* of humanities majors?

Every number below was measured against the committed parquets during this audit
(DuckDB, whole-table scans, humanities = `education_person.hum_l1_any`, **246,482
persons**). Nothing here is estimated.

**Headline:** the pipeline is deep but narrow. Ten stages of careful normalization feed
a portal that consumes essentially five columns of it — SOC group, industry, seniority,
employment type, dates. The largest untapped assets are not new levers on the same
columns; they are **whole dimensions of the corpus that no analysis module reads at
all**: free-text work descriptions, geography, institution type, credentials, and the
archetype layer built two weeks ago that nothing renders.

---

## Tier 1 — big, cheap, directly serves "illustrate the possibility space"

### 1. Archetype × employer is nameable where major × employer was not

The portal's employer feature concluded, correctly, that **the dispersion is the
finding**: at `major × employer` over years 0–5, English's 8,335 employer relationships
spread over 7,196 employers (93% hired exactly one graduate), so almost nothing could be
named above the bar. That conclusion is an artifact of the *grain*, not of the data.

Pool the five majors and cut by **archetype** instead, and named employers appear with
counts one to three orders of magnitude above any suppression bar (measured, distinct
humanities persons, all career steps):

| Archetype | Employer landmarks (distinct humanities persons) |
|---|---|
| Hospitality, Retail & Service | Starbucks 1,110 · Target 308 · Walmart 244 · McDonald's 186 |
| Creatives & Media Makers | Freelance 9,198 · SAG-AFTRA 286 · NBCUniversal 272 · Apple 232 · Disney 224 |
| Educators & Academics | NYC Dept. of Education 369 · NYU 257 · LA Unified 253 |
| Legal, Policy & Research | U.S. House of Representatives 122 · DOJ 116 · U.S. Attorneys' Offices 73 · State Dept. 70 |
| Writers, Editors & Content | Freelance 5,338 · Microsoft 141 · NBCUniversal 130 · Pearson 129 · Condé Nast 114 |
| Finance & Accounting | Wells Fargo 434 · Bank of America 258 · JPMorgan 194 · Citi 130 |
| Tech & Product | Apple 227 · IBM 201 · Microsoft 160 · AT&T 156 |
| Nonprofit, Public Service & Advocacy | Peace Corps 47 · American Red Cross 37 |

This answers the question the current portal structurally cannot — *"who actually
employs people like me?"* — with concrete, checkable names, while staying aggregate.
It is also the single most legible piece of evidence against the no-jobs myth.

Two caveats to carry: the military and self-employment markers dominate several rows
(US Army is top-6 in eight archetypes; "Freelance"/"Self-employed" leads four), which is
itself a finding, not noise; and these are all-career counts, so a windowed version is
needed before publication.

### 2. Archetype pathways are richly populated — the documented "named pathways" gap closes

`portal/FINDINGS.md` records named pathways as a data limitation: 3–4-stage chains of
distinct occupation groups miss the bar, so `PATH_MIN_STAGES` was dropped to 2 and
history/philrel ship an honest empty state.

At archetype grain, pooled, on the in-window humanities panel:

- **391,817 persons** have a classified archetype at career-years 1, 5 *and* 10.
- **3,837 distinct** y1→y5→y10 triples; 154,470 persons (39.4%) hold one archetype
  throughout, the rest move.
- Dozens of *changing* three-stage routes clear n≥900 — e.g. Admin→Admin→Managers
  (2,433), Sales→Sales→Managers (1,647), Analysts→Managers→Managers (1,257),
  Legal/Policy→Legal/Policy→Managers (1,021), Educators→Educators→Managers (978),
  Creatives→Creatives→Managers (959).

Three-stage narrative pathways — the exact object the portal wanted and could not build
— exist in quantity. They were unavailable at `major × SOC-group` grain and are
abundant at `pooled × archetype` grain.

### 3. Free-text work descriptions — 5.2M of them, unread

`career_steps.description` survives normalization: **48.2% of 10.8M steps** carry >40
characters. On the 1.4M humanities steps joined to archetypes, 38–53% carry >120
characters (highest in Comms 52.8%, Writers 50.1%, Tech 49.3%).

No analysis module reads this column (the only consumer anywhere is
`career_clean/se_description.py`, for self-employment disambiguation). It is the
richest qualitative asset in the corpus and the natural substrate for:

- **what the work actually is** behind a generic title — "Coordinator" at a museum and
  at a hospital are different jobs, and the descriptions say so;
- **skill and verb extraction** — the evidence base for "what humanities graduates do
  all day", which no SOC code can carry;
- **per-step embeddings**, explicitly deferred in `ARCHETYPES_PLAN.md` §10.6 as a
  Phase-2 enrichment if role-level coherence proved weak (it is weak: unsupervised
  cross-check ARI 0.16);
- **vignette material** — with the privacy rule that quotations must be composited or
  paraphrased, never lifted verbatim from an identifiable profile.

`profiles.about` is the companion asset: **58.5%** of humanities persons wrote a
self-summary over 80 characters. That is the corpus's only record of how people
*describe themselves*, as against how a taxonomy codes them.

### 4. Geography — carried through the whole pipeline, consumed by nothing

`career_steps` carries parsed `location_country` / `location_us_state` / `location_city`
(**63.8% any location, 51.6% a US state**), and `transitions.parquet` carries
`from_location` → `to_location` on every edge: a ready-made migration edge list. The
only code that touches location is the parser's own regression test.

Measured destinations (distinct humanities persons with a state-coded step): CA 42,518 ·
NY 34,128 · TX 17,570 · FL 15,191 · IL 12,383 · MA 10,394 · PA 9,582 · **DC 8,587** ·
WA 8,556 · VA 8,544. DC ranking eighth — above Washington and Virginia, on a population
base an order of magnitude smaller — is a humanities-specific signal worth its own card.

Three products fall straight out: destination geography per major/archetype; the
stay-or-move question ("what does the space look like if I stay in Ohio?"), which is
among the most concrete anxieties a student has; and migration flows between metros.

### 5. Institution metadata — 70.9% coverage, wired into nothing

`education_person` gained IPEDS columns on 2026-07-24: `inst_unitid`,
`inst_control_label`, `inst_carnegie_label`, `inst_iclevel_label`, `inst_state`,
`inst_region`, `inst_cbsa_metro` — present for **70.9% of humanities persons**. No
consumer reads them (`EDU_PIPELINE_UPGRADE_PLAN.md` lists the portal facet as ☐ and the
archetypes/cohorts wiring as ⟳).

This is the highest-value *moderator* available: does the possibility space differ for a
liberal-arts college, an R1, a regional public? It is also the axis NHA's audience —
institutions — will ask about first.

### 6. Certifications — the credential ladder, 60,510 humanities persons

Untouched table; 185,466 credentials. Top credentials among humanities graduates
(distinct persons): notary public 802 · PMP 746 · CPR/AED/first aid 419 · BLS 387 ·
Foundations of Project Management 365 · Series 7 357 · CompTIA Security+ 304 · real
estate broker/sales agent 290 · Series 63 274 · CompTIA A+ 273 · Certified ScrumMaster
272 · Foundations of UX Design 255 · registered nurse 244 · Google Ads 237.

This is a map of the *cheap, concrete, post-graduation moves* that convert a humanities
BA into a specific occupation — project management, securities, security, UX, real
estate, nursing. It belongs in the portal's existing **Choices** framework as a seventh
choice, and unlike most choices it is directly actionable by a student.

---

## Tier 2 — real value, more work or thinner coverage

| Asset | Coverage (humanities persons) | What it buys |
|---|---|---|
| **Recommendations** (`text`) | 45,465 persons / 72,784 texts | Third-party descriptions of a person's work — the highest-signal qualitative evidence of what humanities skills look like in practice. Same privacy rule as descriptions. |
| **`people_also_viewed` / `similar_profiles`** | 173,461 / 29,454 persons | LinkedIn's own similarity graph. Two uses: an *external* validation of the archetype assignment (do platform-similar people share an archetype?), which is exactly the fair test `archetypes/FINDINGS.md` §5 says is missing; and a "people like this" navigation primitive. |
| **`bio_links`** | 34,584 persons | A personal site/portfolio link is a hard behavioral indicator of independent practice that `employment_type` misses entirely. |
| **Transitions richness** | full | `dwell_months`, `gap_months`, `has_gap`, `has_overlap`, `overlap_months`, `transition_type` — the portal uses only the stability slice. Overlaps + the unused `paths/_concurrency.parquet` are the portfolio-career story (two jobs at once), which the panel's one-role-per-year rule currently hides. |
| **Enrichment layer** | built 2026-07-22 | `enrichment/results/enrichment.json` (volunteer causes, publications, honors, org leadership, multilingualism vs a non-humanities baseline) exists and **is not wired into the portal**. Humanities volunteer 16.1% vs 13.0%, publish 5.6% vs 3.6%, multilingual 10.8% vs 8.7%. Finished analysis, zero surface. |
| **Projects / courses / posts** | 14,754 / 13,854 / 11,372 | Thin, but `posts.title` is the only record of public voice; projects are portfolio evidence for creative archetypes. |
| **Patents** | 654 persons | Too small for a statistic, perfect as a myth-busting aside. |
| **Profile network fields** | 96.8% have `followers` | Audience size. Legitimate as an *enrichment* signal for creative/independent practice; must not be framed as a career outcome. |

---

## Tier 3 — honest non-levers (documented so they stay rejected)

- **Minors and study abroad** — free text only (~50–60k and ~9–13k persons mention them);
  already documented as `choices_not_measured`.
- **Wages** — absent from the corpus. The no-wage-claims rule stands.
- **Demographics** — absent, and out of policy scope.
- **Graduation year for the other 85%** — `archetypes/FINDINGS.md` §3 settles this:
  first-job year lands in a different 5-year bin 60.5% of the time and no constant offset
  fixes it. Career-entry is the honest axis for anything outside the A1/A2 subset.
- **`activity`** (2.0GB, 169k persons) — engagement noise; low information per byte.

---

## What this implies about sequencing

The three Tier-1 items that need no new modeling — **archetype × employer**,
**three-stage archetype pathways**, and **the institution facet** — are the fastest
route from "the pipeline knows this" to "a student can see this". Descriptions and
geography are a larger build with a larger payoff, and both are prerequisites for the
qualitative register the portal is moving toward. See `PORTAL_NEXT_STEPS.md` for the
ordering and the one architectural decision (which time axis) that gates the first item.
