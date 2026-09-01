# Foundation, messages, and website storyboard

**Date:** 2026-08-24. **Status:** proposal, written to be argued with.
**Companion:** `docs/notes/2026-08-24-product-review.md` is the evidence review behind this.
This document is the one to hand outward.

## How to read this

Three parts, and they are meant to be read in order because each one depends on the one
before it.

**Part 1** fixes the concepts. Not a glossary for its own sake. We currently have five
different populations all called "the humanities cohort," two different meanings for
`SNAPSHOT_YEAR`, and at least three things called a "pathway." Every disagreement we have
had about what a number means traces back to one of those.

**Part 2** states the eight messages, in the form each one can actually be said, and routes
each to an input (which pipeline produces it) and an output (report, website, or both).

**Part 3** is the website storyboard. It is written for the design firm: screen by screen,
what each screen is for, what it shows, where the data comes from, what happens when there
is no data, and whether the data exists today.

A note on Part 3's traffic lights, because they are the thing a design firm will care about
most:

| | Meaning |
|---|---|
| **Ready** | The number exists, is tested, and is in `portal_data.json` today |
| **Built, unwired** | The dataset exists and is finished. Needs a query and a panel, no new modelling |
| **Needs a build** | Real work. Estimate given where I have one |
| **Write, do not build** | A text task. Nothing to compute |

---

# Part 1 — Shared concepts

## 1.1 What the corpus is, and what it is a sample of

2,000,000 LinkedIn profiles, downloaded 2026-02-19. From them: 10,798,352 career steps,
6,179,130 transitions between steps, and education records for most people.

**It is a sample of people who maintain a public professional profile.** That is not a
population, and it never becomes one. Everything downstream inherits this, so it belongs in
the first paragraph of anything we publish.

The bias has a direction, and we should be the ones to say so. People whose degree led
somewhere legible are over-represented by construction. K-12 teaching is one of the largest
humanities destinations and teachers are among the least likely to keep an active profile,
so our best story is probably undercounted while our error runs in the flattering direction
on nearly everything else.

**The governing rule that follows from this, and it should be a firing-level rule:** every
claim is comparative within the sample, never a population level. "Among people in this
sample who hold an English bachelor's, 42% did X" is defensible. "42% of English majors do
X" ends the project's usefulness the first time a provost repeats it.

## 1.2 The unit ladder

Six units. Confusing two of them is how a number gets quoted at the wrong grain.

| Unit | Grain | Count | Where it lives |
|---|---|---|---|
| **Person** | one human | 1,999,974 | `normalized/education_person.parquet` |
| **Degree record** | one credential | many per person | `normalized/education.parquet` |
| **Career step** | one continuous job at one employer with one title | 10,798,352 | `paths/steps.parquet` |
| **Transition** | the edge between two consecutive primary steps | 6,179,130 | `paths/transitions.parquet` |
| **Person-year** | one person, one calendar year, their primary role that year | 40.2M all / 6.84M in the archetype panel | `cohorts/panel.parquet` |
| **Cell** | a reported number, e.g. one employer × occupation group | varies | the reporting layer |

Two rules that matter and are easy to get wrong.

**A person-year picks one role.** When someone holds two jobs at once, the panel keeps the
one with the highest seniority and drops the other. So every movement rate we report is a
**lower bound**, and portfolio careers are structurally invisible. `paths/_concurrency.parquet`
holds the 2,538,405 concurrent secondary steps and has never been read.

**Never mix step-weighted and person-weighted numbers.** The archetype assignment manifest
is role-occupancy weighted and roughly 4.7× double-counts people. The credible shares come
from panel person-years. Both exist in the repo; they are not interchangeable.

## 1.3 The two time axes, and the word that collides

Every longitudinal number in this project is measured on one of two clocks. Which one is not
a detail. It changes the answerable questions and the sample by an order of magnitude.

| | **Career entry** | **Graduation** |
|---|---|---|
| Zero point | first datable job | verified degree end year |
| Column name | `career_age` in `cohorts/`, `career_year` in `archetypes/` (same thing) | "years since anchor" |
| Who qualifies | essentially everyone with a job | ~20% of CIP-coded bachelor records |
| Sentence it licenses | "in the first five years of working life" | "five years after graduating" |

**Why we cannot just derive one from the other.** Measured on the 60,563 people who have
both, first-job year and true bachelor-end year land in a different five-year bin **60.5% of
the time**. Median gap is −2 years, because first jobs often predate the degree. No constant
offset fixes it: the best offset still only puts 41% in the same bin.

**What the axis choice costs.** Same population, same n≥10 bar, first five career years:

| Nameable cells | Graduation-anchored | Career-entry |
|---|---|---|
| Named employers | 142 | 3,788 |
| Employer × occupation group | 41 | 1,716 |
| Employer × US state | 15 | 1,513 |
| Employer × city | 3 | 983 |

**Recommendation: career entry is the primary axis. The graduation subset (62,442 people
with a verified A1 or A2 anchor) is a labelled sensitivity check, not a second headline.**
A provost will ask why we cannot say "five years after graduating." The honest answer is
that we can, for one person in five, and that we would rather describe 3,788 employers than
142. What must never happen is one screen mixing both axes without saying which is which.

**The name collision to fix in code.** `SNAPSHOT_YEAR` means 2026 in `paths/common.py` (the
calendar ceiling on observed data) and 2025 in `portal/common.py` (the last fully observed
year, which is what window arithmetic needs). Both files document their choice correctly and
the values are both right for their own purpose. The name is still a trap. `paths/` already
has the better vocabulary: `SNAPSHOT_YEAR` for the ceiling, `LAST_COMPLETE_YEAR` for the
window bound. Standardize on those two names everywhere.

**Windowing, stated once.** A statistic about career-year N may only include people who
could possibly have reached year N. So a year-10 number requires an anchor at or before
`LAST_COMPLETE_YEAR − 10`. This is why the year-0 cohort is bigger than the year-10 cohort.
That is correct, not a bug, and it is non-negotiable.

## 1.4 Who counts as humanities — the five-definitions problem

This is the most important item in Part 1 and the one with a live error behind it.

The field classifier (`edu_clean/humanities.py`) is good, published-source-grounded, and
nested: L1 implies L2 implies L3.

| Tier | Definition | Source |
|---|---|---|
| **L1** | The humanities, narrowly | Humanities Indicators Project core, plus theology and all fine & performing arts as project additions |
| **L2** | L1 plus the humanistic and interpretive social sciences | ACLS member societies |
| **L3** | L2 plus math and the natural sciences. A College of Arts & Sciences, minus professional and vocational programs | Phi Beta Kappa |

The classifier is not the problem. The problem is that **each module picks a different tier
and a different degree-level rule, and they all say "humanities cohort" in their output.**

| Module | Rule it actually applies | Persons |
|---|---|---|
| `edu_clean` universe | every person | 1,999,974 |
| **`archetypes/`** | **L1, L2 or L3 on any degree** | **551,560** |
| `edu_clean` L3 | L3, any degree | 658,824 |
| `edu_clean` L2 | L2, any degree | 421,082 |
| **`enrichment/`** | **L1, any degree** | **246,482** |
| `edu_clean` L1 bachelor's | L1 on a bachelor's | 140,548 |
| **`portal/`** | **bachelor's-level, in one of five CIP bundles, with a usable graduation anchor, windowed to year 10** | **22,427** |

A 25× spread between the two numbers we quote most often, both labelled "humanities."

**The live error.** The archetype panel is the substrate for every movement finding we have,
for the atlas, and for the whole possibility-space story. Broken down by tier:

| Tier in the archetype panel | Persons | Share |
|---|---|---|
| L1 humanities | 207,821 | 37.7% |
| L2 humanistic social science | 147,631 | 26.8% |
| L3 liberal arts only | 196,108 | 35.6% |

**Roughly six in ten people in our "humanities" panel are not humanities under our own
strictest definition, and more than a third are not even humanistic social science.** They
are mathematicians, biologists, chemists, psychologists, and economists. This shows through
in the output and reads as a finding when it is an artifact: the atlas plate reports that
the largest single undergraduate feeder into Legal & Policy work is Biological Sciences at
18.4%, into Healthcare is Psychology at 20.9%, into Tech is Math & Statistics at 12.0%.
Those are true statements about a liberal-arts panel and misleading ones about humanities
graduates.

You already caught this in one place: the paths plate was restricted to L1/L2 bachelor's
last week. The rest of the layer was not.

**The standard I would adopt, and it needs one decision from NHA rather than from me:**

1. **One canonical cohort, named and used everywhere.** My recommendation is **L1 or L2 on a
   bachelor's degree**, on the career-entry axis. L1-only loses Communication & Media, which
   is one of our two largest groups and squarely part of the story NHA tells. L3 lets in the
   natural sciences and is indefensible in a sentence beginning "humanities graduates."
   Bachelor's-level matters because the argument is about what an undergraduate degree opens.
2. **Every other cut is a named variant, never the default.** L1-strict for the advocacy
   venue where the definition will be challenged. L3 only for explicit "liberal arts"
   framing, labelled as such.
3. **Every reported figure carries its cohort definition in the data, not in a footnote.**
   If the JSON does not say which population a number describes, the number is not shippable.

**This has to be settled before anything else on the list, because it changes numbers we
have already shown people.**

## 1.5 The vocabularies, and which ones are public

Five classification axes. They are not alternatives; they are different questions.

| Axis | Grain | Coverage | Public? |
|---|---|---|---|
| **SOC occupation** | 23 major groups, 824 detailed nodes | ~53% of year-10 endpoints classified | **Yes.** Standard, external, recognizable |
| **Industry** | 4 levels, 17 L1 macro-sectors | **53.03% informative.** The rest is `XOT`, an unresolved bucket | **Yes, with the coverage stated where the chart is** |
| **Employment type** | employee / self-employed / business owner / student / retired | **100%** | **Yes.** Our best-covered axis by a distance |
| **Seniority** | ordinal band plus a continuous revealed score | 46.1% ordinal, 95.2% fused | **Carefully.** Missingness correlates with the outcome |
| **Archetype** | 15 buckets plus an `OTHER` residual | ~89% | **No. Internal only** |

Two things to be clear about.

**`XOT` is not a sector.** It is the absence of a resolved sector, and it is 46.97% of steps.
It must never be drawn as a slice, ranked in a list, or encoded as a category. Where a sector
chart appears, the unresolved share appears next to it.

**The archetype vocabulary does not go on the page.** Every audience we have modelled
rejected it independently: a student does not want to be told they are a shape, and an
advocate knows that an invented taxonomy is the first thing a hostile reviewer attacks. The
15 stay as internal machinery, which is what they are good at. Part 3 shows how to get the
navigational benefit without the label.

## 1.6 Three words that currently mean three things each

**"Pathway."** Used across 15 files for at least three different objects.

| What it means | Where | Size |
|---|---|---|
| A 2-stage occupation-group route between year 1 and year 10 | `portal/` | 6 to 8 per major |
| A 3-stage archetype triple across years 1, 5 and 10 | `archetypes/` | 3,837 distinct, dozens above n=900 |
| A named family of job titles, e.g. "Project Management" | the director's framework | ~70 |

Proposal: **"route"** for a measured sequence of destinations. **"pathway"** reserved for
the framework's named title families, because that is the sense a career-services reader
already has and the one a student finds legible. Never use "pathway" for a measured object.

**"Cohort."** At least five senses in active use: the humanities cohort (a population), an
entry cohort (a five-year bin of first-job year), the windowed cohort (who survives the
window at year N), a graduation cohort, and `valid_cohort` (a boolean about entry-year
sanity). Proposal: **population** for who is in scope, **entry cohort** for the time bin,
**windowed at year N** for the observability cut. Retire the bare word.

**"Destination."** Sometimes a SOC major group, sometimes a detailed occupation, sometimes
an employer, sometimes an archetype. Always say which.

## 1.7 Evidence grades

We already ship a green and amber badge. Formalize it to four grades, because two is not
enough to keep an assertion apart from an unreproduced query.

| Grade | Means | Shippable where |
|---|---|---|
| **Measured** | Produced by a tested pipeline stage with a bias check. Byte-reproducible | Anywhere |
| **Provisional** | Computed, but by an ad-hoc query with no test and no bias check | Internal only. Not spoken aloud outside the team |
| **Asserted** | NHA's claim, authored by a person, not derived from data | Anywhere, if visibly badged as NHA's position |
| **Editorial** | Illustrative, composite, or invented | Prototypes only, labelled on the element |

The middle grade is the one we are missing and the one we most need. Several of our sharpest
numbers are currently provisional: the self-employment bands, the occupation-versus-industry
change rates, the management gap by career age, and the employer-cell counts. They should
drive what we build. None of them should reach a slide.

**Suppression.** `MIN_SUPPORT = 10` distinct people for any named cell, a facet floor of 5,
one global knob read by every consumer and every test. Suppression has a user-facing failure
mode we have never designed for: a student who asks about Classics and gets a blank screen
concludes that nobody with their degree gets a job. **An empty cell must say why it is
empty.** See Part 3's global rules.

## 1.8 The envelope: what this corpus can never say

Worth writing down once so every downstream claim inherits it, and so we stop relitigating.

- **No wages. Ever.** No earnings, no ROI, no "is this a good job." Any earnings claim must
  come from an external source by citation, and we recompute nothing. This is not a gap to
  be closed later.
- **No unemployment.** A gap between steps is unobservable, not measurable. Gaps are
  "unknown," never inferred joblessness.
- **No satisfaction, meaning, or wellbeing.**
- **No demographics.** Absent, and out of scope by policy.
- **No skills.** LinkedIn's skills and endorsements section was not captured. There is no
  skills field. Every proxy is a title, a self-written description, or a certification, and
  a title-inferred skill is collinear with the move it is meant to explain. See message 4.
- **No causation.** Everything is a descriptive association among self-selected people.

---

# Part 2 — The eight messages

## 2.0 The routing table

Each message, in the form it can be said, with the pipeline that produces it and the surface
it belongs on.

| # | Message | Input | Output | Status |
|---|---|---|---|---|
| 1 | Opens a possibility space, not a pipeline | `portal.analyses.diversity`, destination fan, employer field | **Both.** Website leads with it | **Ready** |
| 2 | Careers unfold over time | Panel, state flows, transitions. Plus a linearity typology | **Both** | Needs a build, small |
| 3 | Reaches unexpected destinations | Fan drill-down, distinctive destinations, employer landmarks | **Website** leads. Report carries the Arts exception | **Ready**, needs reframing |
| 4 | Transferable skills enable moves | No skills pipeline exists. Substitutes below | **Website** as asserted, **report** as moves | Split required |
| 5 | Chart a course, stay open to what arrives | State flows read backwards from destination | **Website** | Built, unwired |
| 6 | Paths converge in leadership | Seniority curve, Admin-to-management routes | **Report** only, descriptive form only | Reframe required |
| 7 | Coursework translates to careers | Courses table fails. Educational provenance replaces it | **Website** | Built, unwired |
| 8 | Concrete career pathways | Employer × occupation × geography, career-entry axis | **Both** | Blocked on the axis decision |

## 2.1 Message by message

### 1. A humanities degree opens a possibility space, not a single pipeline

**Say:** nothing here is a pipeline. The largest single destination holds about one in eight
people, so seven in eight are somewhere else. Employers are so dispersed that 93% of them
hired exactly one graduate in this sample.

**Do not say:** that the space is wider than other majors'. Our own committed
`diversity.effective_destinations` reads English 7.01, History 8.04, Philosophy & Religion
7.86, Communication & Media 6.42, Arts 4.18, against an all-graduate baseline of 8.25. Every
humanities cohort is at or below baseline. The comparative form is refutable from our own
JSON; the descriptive form is unassailable and says the thing we actually mean.

**The Arts exception, which recurs in almost every message.** Effective destinations 4.18,
top bucket 24.2%, and the only cohort whose year-1 to year-10 change rate sits below
baseline. Arts is the most pipeline-like group in the set and it is 7,519 windowed people.
Any sentence about "the humanities" as a bloc will be wrong about them.

**Input:** `portal.analyses.diversity`, `destination_fan`, `employer_field`. All tested.
**Output:** both. This is the website's opening screen and the report's opening finding.

### 2. Careers unfold over time

**Say:** almost nobody's first decade is a straight line.

**The number that makes this a finding does not exist yet**, and it is the cheapest high-value
thing on our list. Not "how much movement happens" in aggregate, but how rare the straight
line is: the share of people who held one occupation group for ten straight years, the share
who held one employer, the share whose seniority never moved. My expectation is that all
three are small. If they are, this stops being a slogan.

**Input:** `cohorts/panel.parquet` plus `archetypes/state_flows.parquet`, and a new
linearity typology. **Blocked** on the stale panel: both were built before the snapshot-date
fix restored 182,634 steps, 167,368 of them somebody's most recent one. Recency truncation
is exactly the bias that understates movement.
**Output:** both.

### 3. Humanities careers frequently reach unexpected destinations

**Say:** the destinations people assume are taken by a minority. Here is who else is out
there.

**"Unexpected" is a comparison to a stereotype, not to another major.** That is the good kind
of comparison and we keep it. The expectation-inversion machinery already built in the portal
works unchanged; we just point it at the reader's assumption instead of at business majors.

**Two honesty obligations.** Arts again, where the argument is weak and we should say so
rather than let a reader find it. And the employer list: measured honestly on the
career-entry axis, the largest first-five-year employers are Self-employed, US Army, US Navy,
Target, Air Force, Walmart, Starbucks, then Wells Fargo, AT&T, Amazon, Apple, Disney, IBM.
Legible cells sit underneath: U.S. House of Representatives in DC at 133, NYU at 147, NYC
Public Schools at 119, Condé Nast in NY at 114. **The moment we reorder that list to lead
with Condé Nast we have stopped being descriptive.** Show the whole shape instead: the big
employers are big because they are big, and the interesting cells are underneath them.

**Input:** `destination_fan_detail`, distinctive destinations, `career_steps ⋈ role_archetype`.
**Output:** website leads. Report carries the exception and the employer honesty.

### 4. Transferable skills enable career moves

**This is the one message with no pipeline behind it and no prospect of one from this corpus.**
A hostile reviewer needs one sentence: you never measured a skill.

The message is still worth making. It splits into three honest pieces, and I would ship all
three, badged differently:

| Piece | Grade | Substance |
|---|---|---|
| The skills themselves | **Asserted** | The framework already writes them in coursework language: close reading, rhetorical analysis, source evaluation, archival research. NHA is entitled to this claim. We are not entitled to present it as a measurement |
| The moves | **Measured** | 52% of job changes moved into a different kind of work, 32% into a different industry, 57% held more than one kind of work in ten years. Then: we measure the moves, we do not measure skills, and we cannot say what caused any move |
| The next step | **Measured** | Certifications. PMP 746, notary 802, Series 7 357, Security+ 304, real estate 290, ScrumMaster 272, UX 255, RN 244. The only asset in the corpus a student can act on this semester |

**Drop the comparative half entirely.** "Bigger leaps than technical backgrounds" needs a
skills measurement we do not have, on a population we cannot compare fairly, about a future
trend we cannot observe.

**Input:** framework (asserted), transitions (moves, provisional pending pipeline
reproduction), `parsed/certifications` (needs a build).
**Output:** website for asserted skills and certifications. Report for the moves.

### 5. You can chart a course, and also be ready for what arrives

As written this is a headline, not a caption. It becomes measurable when run backwards.

**The data supports exactly one direction: from a destination back to its origins.** "People
who reached this work most often came from these places" is describable. "This path leads to
that job" is a prescription the data cannot license. The measurable form of "stay open" is
origin dispersion: people who started in the same place were, ten years later, in N different
kinds of work.

**Input:** `archetypes/state_flows.parquet`, finished and rendered by nothing.
**Output:** website.

### 6. Many career paths converge in leadership positions

**Report only, descriptive only, and never with earnings attached.**

The comparative form fails twice over. Humanities sit below the all-graduate baseline in SOC
major group 11 at every career age and the gap widens with age. And 28% of humanities
management person-years at year 1, rising to 40% by year 15, carry SOC 11-1011 "Chief
Executives," a documented lexicon artifact collapsing founder, owner, "Chief" and "Head." A
large share of measured leadership is self-employment wearing a management code.

The convergence half only works in the vocabulary we are not using publicly. Among humanities
in management at year 10, on the public SOC axis 70.3% were already in management at year 1;
on our internal archetype axis, 36.5% were. A reviewer who sees both will say we chose the
taxonomy that gave the answer, and they will be right.

**What survives, within humanities and without comparison:** responsibility accumulates, and
administration is a real door into it. Admin-to-management is among the largest measured
year-over-year flows, and three-stage routes ending in management clear n≥900 in quantity:
Admin→Admin→Managers 2,433, Sales→Sales→Managers 1,647, Analysts→Managers→Managers 1,257,
Legal/Policy→Legal/Policy→Managers 1,021, Educators→Educators→Managers 978,
Creatives→Creatives→Managers 959. Reframing the 10.6% of person-years sitting in
"Administrative & Coordination" as being on a recognized route into organizational leadership,
rather than parked in a residual bucket, is one of the strongest and kindest true things we
can say.

**On earnings: out, permanently.** No wages in the corpus, and the mid-career catch-up claim
cannot be made from it in any form. Pair with external earnings sources by citation and
recompute nothing.

### 7. Your coursework gives you skills that translate to careers

**The courses table cannot carry this.** 13,854 of 246,482 humanities people. No date, no
institution, no foreign key to an education row, so a course cannot be attached to a degree,
a year, or a school. After windowing, 1,329 people remain at career-year 10. And the content
runs against us: the most-listed courses among humanities majors are Project Management,
Public Speaking, Typography, Marketing, Statistics, and Financial Accounting. Humanities
majors who list coursework mostly list their non-humanities coursework.

**The honest replacement is already measured: educational provenance.** Not "your coursework
gives you skills," but "the people doing this work studied these things, to this level, at
these kinds of places." Creatives are 65.3% bachelor's-terminal and 55.0% Fine & Performing
Arts. Educators are 72.1% graduate-degreed. Legal & Policy is 70.1% graduate-degreed.

That is a stronger version of the same message, because it answers the question a student is
actually asking, which is not "what will I learn" but "what did the people who got there
study." **It must be recomputed on the canonical cohort first** (§1.4). On the current L3
panel it reports biologists and psychologists as humanities provenance.

**Input:** `person_year_archetype ⋈ education_person`. Measured, needs the cohort fix.
**Output:** website.

### 8. These are concrete career pathways

**Say:** here is where people in this sample actually worked, with the dispersion shown.

**Entirely gated on the axis decision** (§1.3). Career entry gives 1,716 employer ×
occupation-group cells clearing the bar; graduation gives 41.

**The recommended unit is employer × occupation group.** Ship three numbers with any named
list: the cell n, the suppressed-cell count, and the singleton share. **The dispersion is not
a caveat, it is the finding**, and it is what stops "here are the employers" from reading as
"here is the funnel."

Multi-step named routes at role grain are not available; the pipeline's documented ceiling is
8 people. Three-stage routes exist in quantity at archetype grain and are unwired.

---

# Part 3 — Website storyboard

## 3.1 What this site is, in one sentence

**A place where a humanities undergraduate can see the actual range of work that people with
their degree went into, follow specific routes into the ones that interest them, and come
away understanding that the open-endedness of that picture is normal rather than a warning.**

**Audience:** undergraduates first, their advisors second. Not provosts, not legislators, not
journalists. Those readers are served by the written report, and the site should link to it
rather than try to be it.

**This split is the single most important decision in this document.** One surface currently
tries to be a research instrument and a reassurance instrument at once. The honesty apparatus
that makes a skeptic trust us reads to an anxious sophomore as hedging. Both audiences are
real; neither is served well by the compromise.

**The job to be done, in the student's words:** "Is there anything out there for me, and can
you show me something specific enough that I believe you?"

## 3.2 The screen sequence

Nine screens. The first four are the spine and a student who reads only those has got the
message. Screens 5 to 8 are depth for the ones who want it.

---

### Screen 1 — The field

**Message:** 1. **Serves:** possibility space, not a pipeline.

**What it says.** There is no default job. There is a field of real destinations.

**What it shows.** The full spread of year-10 destinations at once, as a field rather than a
ranked list, so that no single destination reads as the answer. Then one number in plain
language: the largest single destination holds about one in eight people.

**Why a field and not a bar chart.** A ranked bar chart answers "what is the most common
job," which is the question we are trying to dislodge. The form has to carry the argument.

**Data:** `majors.*.fan`, `majors.*.diversity`. **Ready.**

**Interaction.** Choose your field of study, or view all humanities pooled. Nothing else.
This screen has one job.

**Design note.** This screen currently exists and works. It is the best thing we have shipped.
The brief for the design firm is to make it more confident, not to redesign it.

---

### Screen 2 — What kind of work interests you

**Message:** 3, and the entry point into everything below.
**Serves:** archetypes as an entry point, and choose-your-own-adventure.

**What it says.** Nine doors, phrased as things a person might like doing rather than
identities they might have. The framework's first-person orientations were written for
exactly this.

**The design constraint that matters most on this screen.** A door is not a label. The
student is never told what they are, never given a result, never assigned a shape. Choosing
a door is a statement about what they want, and they can open as many as they like.
**Returning a single answer would undo the whole message of Screen 1.**

**Naming.** The nine macro doors organize the page. The names a student reads are the ~70
pathway names underneath them, because those are already plain: Writing & Editorial, Project
Management, Fundraising & Development, Learning & Development, Libraries & Archives. Nobody
has to learn those. **The internal 15-archetype vocabulary never appears on screen.**

**One thing not to hide.** Frontline service work needs a named door of its own. It is 2.4%
of person-years, concentrated in the first three years, and folding it into something
nicer-sounding would cost us the resilience argument, since you cannot show people moving up
and out of frontline work if frontline work is not on the map.

**Data:** the framework supplies the doors and the copy today. The measured contents of each
door need the pathway lexicon. **Needs a build:** match the framework's ~600 curated titles
against the 2.6M-role vocabulary. String plus embedding work we have done before.

---

### Screen 3 — Inside one kind of work

**Message:** 3, 4, 7, 8. The workhorse screen, and the one the site currently has no version
of.

**Five panels, in this order.** The order is the argument: what the work is, then how people
get in, then who is there, then what they studied, then where.

| Panel | Content | Source | Status |
|---|---|---|---|
| What this work involves | Plain description of the actual work, drawn from how people describe it themselves | 5.2M free-text descriptions | **Needs a build.** Composite or paraphrase only, never verbatim |
| Ways in | Entry roles, entry employers, entry credentials | `career_steps` at career-years 1 to 3 | **Built, unwired** |
| Who is here | Employer × occupation cells with dispersion shown | Career-entry axis, n≥10 | **Blocked on the axis decision** |
| What they studied | Field, level, and institution type of the people doing this work | Educational provenance | **Built, unwired.** Needs the cohort fix first |
| Certifications that show up | Named credentials, ranked | `parsed/certifications` | **Built, unwired** |

**The panel to lead with is "ways in."** Every audience exercise we ran said the same thing:
the archetype is useful as a door, and the door has to open onto something actionable. Leading
with the bucket's share of the population tells a student nothing.

**Register rule, and it is the hardest one on the site.** Everything here is past tense and
count-first. "1,021 people in this sample held a policy or research role at year 1 and a
management role at year 10." Never "the path from coordinator to program manager."

---

### Screen 4 — The first decade

**Message:** 2, 5. **Serves:** careers unfold over time, linear paths are rare.

**What it says.** Almost nobody's decade is a straight line, and that is the normal case
rather than a bad outcome.

**What it shows.** Two things, and the second is the one that lands.

The first is the existing year-1 / 3 / 5 / 10 scrubber, which shows the population
redistributing over the decade.

The second does not exist yet: **the linearity number.** The share of people whose first ten
years is one occupation group, or one employer, or a flat seniority line. If those shares are
small, this screen has a headline instead of an animation.

**The interaction worth spending budget on.** Commit before reveal. Ask the student to say
what they expect before showing them what happened. It is catalogued in
`PORTAL_INSPIRATION.md` §5, never used, and it is the single most effective device for the
expectation-inversion findings we already have.

**Data:** scrubber **Ready**. Linearity typology **needs a build**, small. Both blocked on the
stale panel.

**A caveat the design must carry, not bury.** Our movement numbers are a lower bound, because
the panel keeps one role per person per year and drops concurrent work.

---

### Screen 5 — Where people came from

**Message:** 5, 7. **Serves:** unexpected destinations, and provenance as the honest
replacement for the coursework claim.

**What it says.** People who reached this work most often came from these places.

**The direction is not a stylistic choice.** Backwards from the destination is the only
direction this data supports. Forwards is a prediction, and we cannot make one. Every caption
on this screen reads "people who reached X came from Y," never "Y leads to X."

**Data:** `state_flows.parquet` plus educational provenance. **Built, unwired.** Needs the
cohort fix.

---

### Screen 6 — The graduate step

**Message:** 7, and the strongest evidence-to-surface ratio on the whole site.

**This is currently one panel inside step five of a walkthrough. It should be its own screen.**

Measured, window-clean, on start-dated enrollment within five years of the anchor:

| Cohort | Enrolls in any graduate or professional degree | Signature concentration |
|---|---|---|
| History | **39.2%** | Law (JD) n=208, 5.2× the all-graduate rate |
| English & Literature | **35.1%** | Law 2.8×, Fine arts (MFA) 8.5× |
| Philosophy & Religion | **34.1%** | Law (JD) n=73, 2.9× |
| Communication & Media | 16.9% | Business (MBA) n=190 |
| Fine & Performing Arts | 16.3% | Fine arts (MFA) n=299, 9.3× |

**The split changes the sentence, and the design has to respect it.** "An ideal foundation for
graduate study" is true of History, English, and Philosophy & Religion, where a third to
two-fifths continue within five years. It is not true of Arts and Communication & Media, where
roughly one in six do. Written as a claim about "the humanities" it is wrong about 14,564 of
our 22,427 windowed people. **Written per cohort it is strong, specific, and useful.**

**What the screen shows.** Undergraduate field on one side, graduate field on the other,
destination on the third, enterable from any of them. The atlas paths plate is a working
prototype of exactly this on 40,388 people across 15 graduate field families.

**Data:** `launchboard.grad_track` **Ready**. Paths plate **measured**, needs promotion out of
the prototype.

---

### Screen 7 — Concrete places

**Message:** 8. **Serves:** concrete career pathways, and the most-wanted asset in every
audience exercise we ran.

**What it says.** Employers where ten or more graduates in this sample worked in their first
five years, and where in the country they were.

**The honesty is the design problem here, and it is not solvable with a footnote.** 93% of
employers hired exactly one graduate. The list of biggest employers is Self-employed, the US
military, and large retail. Both facts have to be visible in the same view as the interesting
cells, or the screen becomes a funnel diagram by implication.

The existing employer dot cloud already solves half of this: singletons render as legible
stipple, so the sparseness is the picture rather than a caveat under it. Extend that.

**Geography.** Named by two of three audiences as their biggest disappointment, and currently
nobody's priority. `career_steps` carries a US state on 51.6% of steps and
`transitions.parquet` carries a ready-made migration edge list. **Before designing around
51.6%, someone should find out whether it can be improved.**

**Data:** `employer_field` **Ready** at pooled grain. Employer × occupation × geography
**blocked on the axis decision**, then a build.

---

### Screen 8 — What people did along the way

**Message:** 4, 8. **Serves:** actionability.

**What it shows.** The six measured choices we already compute on the windowed cohort: double
major, graduate school, internship, military service, service year, self-employment. Plus
certifications as a seventh, which is the only one a student can act on before finals.

**The caveat is structural and must be in the design, not appended to it.** These are
self-selected people. Nothing here is the effect of a choice. The module already ships the
caveat text; the screen has to give it room rather than a footnote.

**Data:** `choices` **Ready** for six. Certifications **built, unwired.**

---

### Screen 9 — About this data

**Message:** the one that makes the other eight believable.
**Serves:** examine the underlying dataset.

The existing Data & Methods surface is genuinely strong and mostly needs reorganizing for a
student rather than rewriting. Four things it must carry:

1. **What this is a sample of**, in the first paragraph. Not a population. The bias runs in
   the flattering direction and we say so first.
2. **What we cannot tell you.** No pay, no satisfaction, no guarantee. Stated plainly and
   early. Every audience we consulted said the same thing: show the bad news and I will trust
   the good news.
3. **"Is my profile in this?"** **Write, do not build.** There is no written answer today, for
   the student or for campus counsel, and career services cannot put the tool in front of
   students without one. This is on the critical path.
4. **The date.** Staleness without a visible date is fatal. Staleness with an honest date is
   survivable.

## 3.3 Global rules for the design firm

**Empty states are a design deliverable, not an error case.** Our suppression rule is
methodologically correct and has a failure mode that actively harms the student it protects.
Every empty cell explains itself:

> Fewer than 10 graduates in this sample worked at any single employer in this field, so we
> cannot name one. 2,682 employers appear once each.

That is honest and reassuring. A blank is neither. **Write these before the components that
contain them.**

**Language rules, adopted as project standard.**

1. Every sentence names its population before its number. Never "42% of English majors."
   Always "Among English graduates in this sample who maintain professional profiles, 42%."
2. Past tense, count first, no second person. "N people did X" is describable. "You can do X"
   is a prescription the data cannot license.

| Never | Instead |
|---|---|
| "The path from coordinator to program manager" | "1,021 people in this sample held a policy or research role at year 1 and a management role at year 10." |
| "Top employers for English majors" | "Employers where 10 or more graduates in this sample worked in their first five years. 93% of employers hired exactly one." |
| "A common route into management" | "Where people who started here were ten years later, most common answer first. This describes what happened to them, not what will happen to you." |
| "This pathway leads to…" | "People who reached this work most often came from…" |

**Badges.** Four evidence grades (§1.7), visible on the element, not in a legend nobody
opens. Measured and asserted content must never share a visual treatment.

**Voice.** Earnest, evidence-forward, warm-professional. No snark, no deficit framing, no wage
claims. This applies to placeholder copy too: prototype copy sets the register the real copy
inherits.

**Form.** No italics for emphasis, weight and colour instead. Tabular data gets a real table
with right-aligned figures. Numbered figures with a title, a one-line dek, and a source line
under a rule. References: NYT and Washington Post interactives, Distill, FiveThirtyEight.

**Mobile is the primary target.** The student persona reads this on a phone, on a bus. The
current build is a 1.03MB single page with the data inlined, which is at the edge.

## 3.4 Explicitly out of scope

Say these out loud in the handoff so nobody designs a slot for them.

- Any salary, earnings, or ROI figure
- Any demographic breakdown
- Any individual person, profile, or verbatim quotation
- Any prediction, recommendation engine, or "jobs you might like" result
- Any single-answer quiz or assigned personality type
- The internal 15-archetype vocabulary, anywhere on screen
- `XOT` drawn as a sector
- Provost-facing and legislator-facing framing. That is the report

## 3.5 What must happen before design starts

**Decisions, from NHA.**

1. **The canonical cohort** (§1.4). Recommendation: L1 or L2, bachelor's-level, career-entry.
   This changes numbers already shown to people, so it needs saying out loud.
2. **The time axis** (§1.3). Recommendation: career entry primary, graduation as a labelled
   sensitivity check.
3. **Report and site are two products.** Recommendation: yes, and the site links out.

**Engineering, in order.**

1. Commit the tree. 57,326 insertions across 15 tracked files plus 172 untracked paths are
   currently uncommitted.
2. Rebuild `cohorts/panel.parquet` and `person_year_archetype.parquet`. Both predate the
   08-05 snapshot fix and every movement, occupancy, and provenance figure sits on them.
3. Re-cut the archetype layer onto the canonical cohort.
4. The linearity typology (Screen 4's headline).
5. The pathway lexicon (Screen 2's contents).
6. Wire what is already built: provenance, state flows, certifications, employers.

**Writing, and it is on the critical path.**

1. The privacy answer. Without it, career services cannot use the site at all.
2. The population statement.
3. Every empty state.

**One correction to make everywhere it appears:** industry L1 is 53.03% informative, not
~100%. It has been quoted at the higher figure in several documents and briefings.
