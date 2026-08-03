# Atlas — educational provenance layer (prototype only)

**Date:** 2026-08-03
**Target:** `prototype/atlas.html` only
**Status:** implemented 2026-08-03; §4.1 records one placement change made during the build

Adds educational background to the career atlas as *provenance* — a descriptive
reading of who arrives at each kind of work — without adding a new argument to
the page's thesis.

---

## 1. Scope

**In scope.** Three additions to `prototype/atlas.html`:

1. A markpage figure, **"Who arrives here"** — field of study + degree level.
2. A markpage figure, **"Institutional landmarks"** — named register, built to the
   same grammar as the existing Employer landmarks figure.
3. A scroller step, **"what people studied"**, carrying the degree-level table and
   shading the marks on the sticky field along the graduate-degree gradient.

Plus the honesty apparatus in §5 and the correction in §6.

**Out of scope, explicitly.** No `archetypes/yearwise.py` facet re-cut. No new
parquet. No changes to `portal/`. No institution-type / Carnegie / region
breakdown. No CIP4 drill-down. No fourth field layout. The atlas remains a static
page; the education numbers land as hardcoded literals.

**Why prototype-only.** The purpose is to judge what an education layer would look
like when fed, using real numbers as the evidence that the shape is reachable.
Wiring the pipeline is a separate decision that this prototype should inform.

---

## 2. Editorial frame

Education enters as **provenance, plainly** — descriptive, encyclopedic, no thesis
of its own. It does not argue that background predicts destination, nor that it
fails to. It reports who is standing where.

Two properties of the data do the editorial work without being asserted:

- **Background concentration varies enormously by station.** Top field share runs
  from 59.5% (Creatives & Media Makers, Fine & Performing Arts) to 13.4%
  (Educators & Academics, Fine & Performing Arts). Sharp signature at a few marks,
  near-flat at most.
- **The institutional register self-corrects.** Specialized stations draw
  distinctive institutions (Creatives: Art Institute, FIT, School of Visual Arts,
  SCAD); unspecialized ones draw the biggest publics (Tech & Product: Berkeley,
  Minnesota, Washington, UT Austin, ASU). The contrast is visible by flipping
  between marks and needs no over-representation math.

---

## 3. Measured findings

All figures: the 551,560-person archetype panel, **career year 10**, `in_window`,
`archetype_id <> 0`.

### 3.1 Degree level by station

Percent of arrivals at each station holding each highest level. Four buckets, so
rows close to 100.0: `highest_degree_level_pooled <= 3` / `= 4` / `>= 5` / NULL.
Level 5 is "graduate, unclear between master's and doctorate" per
`edu_clean/dlevel_taxonomy.py` and belongs in the graduate bucket. NULL is a real
category — no level recorded — and must not be folded into sub-bachelor.

| Station | sub-bachelor | bachelor's | graduate | not recorded | n |
|---|---:|---:|---:|---:|---:|
| Educators & Academics | 2.5 | 24.2 | **72.1** | 1.3 | 27,478 |
| Legal, Policy & Research | 2.2 | 26.5 | **70.1** | 1.2 | 20,991 |
| Healthcare & Human Services | 6.5 | 31.7 | 60.0 | 1.8 | 28,319 |
| Nonprofit, Public Service & Advocacy | 6.0 | 47.0 | 44.6 | 2.4 | 3,493 |
| Business & Strategy Analysts / Consultants | 5.8 | 51.6 | 40.7 | 1.9 | 31,538 |
| Tech & Product | 7.4 | 51.1 | 39.3 | 2.2 | 21,473 |
| Finance & Accounting | 6.9 | 52.4 | 39.0 | 1.7 | 11,423 |
| Managers & Operations Leaders | 6.8 | 51.8 | 38.7 | 2.7 | 65,847 |
| Writers, Editors & Content | 3.4 | 58.3 | 35.5 | 2.7 | 14,142 |
| Communications, PR & Marketing | 3.9 | 62.6 | 30.8 | 2.6 | 24,101 |
| Founders & Independent Practitioners | 11.4 | 54.3 | 29.4 | 4.8 | 15,414 |
| Administrative & Coordination | 14.7 | 56.6 | 25.7 | 2.9 | 37,134 |
| Creatives & Media Makers | 9.7 | 65.3 | 20.9 | 4.1 | 31,454 |
| Sales & Business Development | 11.1 | 67.7 | 17.6 | 3.6 | 27,220 |
| Hospitality, Retail & Service | 22.8 | 56.3 | **16.0** | 4.9 | 6,132 |

**The inversion.** The destinations the atlas places furthest from expectation
(Analysts 40.7, Tech 39.3, Finance 39.0) are *more* graduate-credentialed than the
expected ones (Writers 35.5, Comms 30.8, Creatives 20.9). See §6.

### 3.2 Background concentration by station

Top field group share, `Other` excluded from the denominator (see §7).

| Station | top field | share |
|---|---|---:|
| Creatives & Media Makers | Fine & Performing Arts | 59.5 |
| Communications, PR & Marketing | Communication & Media | 44.2 |
| Writers, Editors & Content | Communication & Media | 35.3 |
| Healthcare & Human Services | Psychology | 31.6 |
| Sales & Business Development | Communication & Media | 24.5 |
| Founders & Independent Practitioners | Fine & Performing Arts | 24.2 |
| Legal, Policy & Research | Biological Sciences | 23.5 |
| Finance & Accounting | Economics | 21.4 |
| Nonprofit, Public Service & Advocacy | Humanistic Social Science | 20.7 |
| Hospitality, Retail & Service | Fine & Performing Arts | 19.2 |
| Administrative & Coordination | Communication & Media | 17.2 |
| Business & Strategy Analysts / Consultants | Humanistic Social Science | 16.5 |
| Managers & Operations Leaders | Communication & Media | 16.4 |
| Tech & Product | Math & Statistics | 15.7 |
| Educators & Academics | Fine & Performing Arts | 13.4 |

### 3.3 Institutional recurrence

Institutions appearing in the **top ten of each station's register**:

| Institution | stations (of 15) |
|---|---:|
| UCLA | 14 |
| Arizona State University | 12 |
| UT Austin | 11 |
| New York University | 10 |
| University of Phoenix | 10 |
| University of Minnesota | 10 |

Cell counts are ample: every station has 58–1,108 named institutions at n≥10.
School slug coverage on the panel is **97.1%**.

---

## 4. The three additions

### 4.1 Markpage figure — "Who arrives here"

Slots into `renderMarkPage()` as its own two-column row, immediately after the
row holding the ladder and Employer landmarks. Uses the established `figure()`
helper and `table.reg` grammar.

**Placement, as built.** The approved design put this figure *before* Employer
landmarks. In implementation the two education figures were kept together as one
row instead, giving the plate: flow → ladder | employers → provenance |
institutional. This keeps the two measured figures adjacent, keeps the two
named-organisation registers aligned in the same column on consecutive rows, and
avoids orphaning "Institutional landmarks" in a half-empty row. Figure numbering
is assigned by DOM order at the end of `renderMarkPage()`, so it stays correct.

**One new CSS rule was needed.** A `.mp-grid` nested inside a `.fig-body` inherited
the section-level `margin-top` and, being a stretch grid, distributed its table
rows to fill the taller column — the two tables rendered at different row pitches.
Scoped fix: `.fig-body .mp-grid{margin-top:0}` and `.fig-body .mp-grid > *{align-self:start}`.

```
Fig n   Who arrives here
        What the people standing here studied, and how far they took it.

        FIELD OF STUDY                          share
        Fine & Performing Arts                  55.0%
        Communication & Media                   17.4%
        Other fields                             7.6%
        English & Literature                     3.8%
        Humanistic Social Science                3.3%
        Psychology                               3.2%
        ... 16 further groups                    9.7%

        HOW FAR THEY TOOK IT                    share
        Below a bachelor's                       9.7%
        Bachelor's                              65.3%
        Graduate degree                         20.9%
        Not recorded                             4.1%

        Note: shares are of arrivals at this mark in career year 10.
        Source: person_year_archetype joined to education_person.
```

**Which share the dek quotes.** Two different denominators are in play and the
figure must not mix them silently. The ranked list is `Other`-inclusive, so
Creatives reads 55.0%. The cross-station ranking in §3.2 is `Other`-exclusive, so
Creatives reads 59.5% there. **The dek quotes the in-list number** — the reader
must be able to find it in the table directly beneath — and uses the
`Other`-exclusive figure only for the comparative clause, which names no number:

> *"Fine & Performing Arts accounts for 55.0% of arrivals here — the sharpest
> background signature on the map."*

For a flat station the dek says so, again quoting the in-list number:

> *"No single background accounts for more than one in seven arrivals here, the
> flattest distribution on the map."*

Top six groups plus a rolled tail row. `Other` stays in the list (§7).

### 4.2 Markpage figure — "Institutional landmarks"

Placed beside "Who arrives here" (see the placement note above), deliberately
mirroring Employer landmarks: same `table.reg`, same two-column register, same
caption structure, and sitting directly beneath it in the same column.

```
Fig n   Institutional landmarks
        Schools that turn out to be full of graduates doing this kind of work.

        Institution                          Graduates
        Art Institute                              603
        New York University                        449
        Fashion Institute of Technology            356
        University of California–Los Angeles       305
        School of Visual Arts                      294
        Savannah College of Art and Design         276

        Note: these are the largest suppliers, not the most distinctive.
        The same institutions top nearly every mark — UCLA appears in the
        top ten of fourteen of the fifteen. Where a mark's register looks
        different from that pattern, the difference is the finding.
        Source: person_year_archetype joined to education_person.
```

That note is the figure's honesty apparatus and is **not optional** — without it
the register reads as a ranking of schools by outcome, which the data does not
support and the atlas's thesis resists.

### 4.3 Scroller step — "what people studied"

New `<section class="step" data-focus="background">` inserted between step 5
("enterprise & the room") and the crossings step. Renumbers the existing steps 6→7
and 7→8.

Carries the §3.1 degree-level table as its single figure, ranked by graduate share.
Prose states the inversion plainly and points at the correction in §6.

**Field shading.** While this step is active, the marks on the sticky field are
shaded along the graduate-degree gradient rather than dimmed by membership.

Implementation, against the existing drawing code:

- Add `gradShare` to each entry in `STATIONS` (15 literals from §3.1).
- Add `shade: null` to `state` (`prototype/atlas.html:1244`).
- In the step handler (`:1935`), `data-focus="background"` sets
  `state.shade = "gradschool"` and clears `domain` / `station`; every other focus
  value clears `state.shade`.
- In `draw()` (`:1713` station marks), when `state.shade` is set, replace the
  binary `isActive ? 1 : dimAlpha` with a continuous alpha: linearly map
  `gradShare` from the observed range **[16.0, 72.1]** onto alpha **[0.28, 1.0]**,
  so the faintest mark stays legible rather than vanishing. Clamp both ends.
- In the label pass (`:1740`), when `state.shade` is set, remove the `.dim`/`.mute`
  classes and set a matching continuous `style.opacity`; clear the inline opacity
  when shading ends.
- Add a ramp legend to the existing `.layout-note` element while the step is
  active: *"Darker marks are the ones more of whose arrivals hold a graduate
  degree — from 16% at Hospitality to 72% at Educators."*

**Accessibility.** Shading is never the only channel: the step's own figure carries
every number in a table. The ramp is static alpha, not motion, so
`prefers-reduced-motion` needs no special case beyond honouring the existing
transition suppression.

---

## 5. Honesty apparatus

The colophon's "What is invented here" list currently opens with *"Every count,
share, and employer figure."* That becomes false the moment real education numbers
land, so:

- Amend that bullet to except the education layer.
- Add a **"What is measured here"** block naming the three figures, the population
  (551,560-person panel, career year 10), and pointing at this document for the
  queries.
- The masthead ribbon stays **"Prototype, placeholder data"** — the page is still
  overwhelmingly placeholder, and the per-block colophon statement is the precise
  claim.

Every new figure's `figcaption` names its source as `person_year_archetype` joined
to `education_person`.

---

## 6. The correction

Step 4 ("systems & ledger") currently reads:

> The route to them is usually lateral and credential-shaped: **a certificate, not
> a master's**.

This is backwards — see §3.1. Analysts (40.7%), Tech (39.3%) and Finance (39.0%)
all sit *above* Writers (35.5%), Comms (30.8%) and Creatives (20.9%) on graduate
attainment. Rewrite the sentence to state what was measured, and let the new step
carry the full table.

The adjacent `.aside` in that step — which flags the credential ladder as
"measurable today and shown nowhere" — stays as-is. Certifications remain unbuilt
and unmeasured here; only the degree claim is corrected.

---

## 7. Known wrinkles, handled not hidden

**`Other` is the largest field group on most stations** (21–29%: Educators 29.2,
Tech 23.5, Legal 21.8). It is *readable but not humanities-core* — business,
engineering and education degrees held by people inside the L1/L2/L3 cohort — not
unreadable. So, unlike the unreadable person-years excluded from the fifteen marks
in step 5, it stays in the ranked list, labelled **"Other fields"**. It is excluded
only from the concentration statistic in the dek, and the dek says so.

**Some slugs do not join to IPEDS.** `art-institute`, `university-of-phoenix` and
`arizona-state-university` carry no `inst_unitid`, so `instnm` is unavailable and
the raw slug would print. Hand-fix display names for the slugs that actually
surface in the fifteen registers; do not build a mapping layer.

**`art-institute` is a chain, not a campus.** It tops the Creatives register at 603.
Flag it in the figure note rather than dropping it — the collapse is real in the
school-resolution layer and worth showing.

**`university-of-phoenix` tops the Educators register.** A for-profit,
largely-online institution leading the register for teaching is a selection
artifact worth one clause in the note, not suppression.

---

## 8. Queries of record

Run once; results hardcoded as literals. `ROOT = /home/alex/linkedin-analysis`.

```sql
-- Common base: arrivals at each mark in career year 10.
WITH py AS (
  SELECT linkedin_id, archetype_label AS a, humanities_field_group AS f
  FROM read_parquet('archetypes/results/person_year_archetype.parquet')
  WHERE career_year = 10 AND in_window AND archetype_id <> 0
)

-- 8.1 Degree level by station (§3.1)
-- NOTE: `dl >= 5`, not `>= 6` — level 5 is graduate-but-unclear. And NULL is left
-- as NULL, never coalesced to 0, or the unrecorded 1–5% lands in sub-bachelor.
SELECT a,
  round(100.0*count(*) FILTER (WHERE dl <= 3)/count(*), 1) AS pct_sub_bachelor,
  round(100.0*count(*) FILTER (WHERE dl  = 4)/count(*), 1) AS pct_bachelor,
  round(100.0*count(*) FILTER (WHERE dl >= 5)/count(*), 1) AS pct_grad,
  round(100.0*count(*) FILTER (WHERE dl IS NULL)/count(*), 1) AS pct_unrecorded,
  count(*) AS n
FROM (SELECT py.a, ep.highest_degree_level_pooled AS dl
      FROM py JOIN read_parquet('normalized/education_person.parquet') ep
        USING (linkedin_id))
GROUP BY 1 ORDER BY pct_grad DESC;

-- 8.2 Field-of-study mix by station (§3.2, and the ranked list in §4.1)
SELECT a, f, n, pct, rk FROM (
  SELECT a, f, count(*) AS n,
    round(100.0*count(*) / sum(count(*)) OVER (PARTITION BY a), 1) AS pct,
    row_number() OVER (PARTITION BY a ORDER BY count(*) DESC) AS rk
  FROM py WHERE f IS NOT NULL GROUP BY 1, 2)
ORDER BY a, rk;
-- concentration statistic: same query with `AND f <> 'Other'`, take rk = 1.

-- 8.3 Institutional register by station (§3.3, §4.2)
SELECT a, nm, n, rk FROM (
  SELECT py.a, coalesce(im.instnm, ep.school_slug) AS nm, count(*) AS n,
    row_number() OVER (PARTITION BY py.a ORDER BY count(*) DESC) AS rk
  FROM py
  JOIN (SELECT linkedin_id, school_slug, inst_unitid
        FROM read_parquet('normalized/education_person.parquet')
        WHERE school_slug IS NOT NULL) ep USING (linkedin_id)
  LEFT JOIN (SELECT unitid, instnm
             FROM read_parquet('reference/institution_meta.parquet')) im
    ON im.unitid = ep.inst_unitid
  GROUP BY 1, 2)
WHERE rk <= 6 ORDER BY a, rk;
```

Note the `py` CTE above is written once for readability; each query repeats it.

---

## 9. Verification

- All 15 stations render both new figures; no station errors on empty data.
- Degree-level shares sum to 100 ± 0.2 per station across **all four** buckets,
  including "not recorded" — a three-bucket figure that appears to sum to 100 is
  the bug this spec was corrected for.
- Field-of-study list shows six rows plus a tail row whose share closes the gap.
- Institutional register prints display names, never a raw slug.
- Scrolling into the new step shades the marks; scrolling to any other step
  restores normal dim/mute behaviour with no residual inline opacity.
- Keyboard: the new step's figures are reachable and the shading does not trap or
  hide focus.
- Light and dark themes both legible at the 0.28 alpha floor.
- Colophon states the invented/measured split accurately.
- The step-4 "certificate, not a master's" sentence is gone.
