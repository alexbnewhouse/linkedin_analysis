# Product review — what we have built, what it argues, and what the site should do

**Date:** 2026-08-24. **Scope:** every analysis module, both review surfaces, and the
planning stack, read against the eight messages we want to communicate and the eleven
functions the website is supposed to serve.

**Method.** I re-read the repo and re-ran the load-bearing checks rather than quoting
prior documents. Three things verified this session and used throughout:

| Check | Result |
|---|---|
| Industry L1 informative share | 5,726,073 of 10,798,794 steps. **53.03%**, not ~100% |
| `cohorts/panel.parquet` | mtime 2026-07-21. **Predates the 08-05 spine rebuild** |
| `archetypes/results/person_year_archetype.parquet` | mtime 2026-07-22. **Also predates it** |

Everything else marked with a number below comes from a committed manifest or from
`portal/results/portal_data.json` in the working tree.

**Superseded in one respect.** `FOUNDATION.md` (written after this review, same day)
establishes the shared concept model and turned up a population error that changes how
several figures below should be read: **the archetype panel's 551,560 "humanities" people
are L1, L2 or L3 on any degree, and only 207,821 of them (37.7%) are L1 humanities.**
196,108 (35.6%) are liberal-arts-only, meaning mathematicians, biologists, chemists,
psychologists and economists. Every archetype-derived figure in this review — the 14.4%
Managers share, the 86.4% stay rate, the three-stage route counts, and the educational
provenance plate — describes a liberal-arts population rather than a humanities one. The
findings hold as statements about that population. They must be re-cut on the canonical
cohort before any of them is called a humanities finding. Portal figures are unaffected;
they use a bachelor's-level, five-bundle definition.

**One provenance warning, because it applies to several of the sharpest numbers here.** A
handful of figures I use come from the 08-12 audit's throwaway DuckDB queries rather than
from a tested pipeline stage: the self-employment bands, the occupation-versus-industry
change rates, the management gap by career age, the 52/32/57 movement shares, and the
employer-cell counts in §2.8. They are directional and they were computed on the stale
panel. **Nothing in that set should be spoken aloud outside this room until it has been
reproduced in the pipeline with tests and a bias check.** I have kept them because they
shape what we should build, not because they are ready to publish.

---

## 0. The shape of it

We have built a great deal, and most of it is good. The problem is not quality and it is
not coverage. It is that **the pipeline has ten stages and the surface consumes five
columns**, and that **one page is trying to be a research instrument and a reassurance
instrument at the same time**.

Three findings organize this review.

**First: the split is real and it is overdue.** The advocacy argument and the student
tool are different products with different failure conditions, and almost every
unresolved argument in the planning stack dissolves once you assign each claim to one of
them. Comparison, relative risk, baselines, and coverage caveats belong to the report.
Description, names, places, and routes belong to the site.

**Second: reducing comparison to non-humanities paths is the right call, and it is worth
more than a tone adjustment.** Three of our eight messages are refuted or weakened
specifically in their comparative form and survive intact in their descriptive form. The
comparative claim "humanities open a wider possibility space" is contradicted by our own
committed JSON. The descriptive claim "nothing here is a pipeline, and the largest single
destination holds one in eight people" is true, is ours, and cannot be taken apart.
Dropping the comparison is not a retreat. It moves us onto ground where the data is
strongest.

**Third: the message we can support best has the least surface.** Graduate study. It is
message seven on nobody's list, it is measured, it is clean, it is the one thing a
humanities BA demonstrably does at scale across every field, and it currently occupies
one panel inside a walkthrough step.

---

## 1. Two products, not one

The inventory, sorted by which product each piece belongs to. "Wired" means a human
outside this repo can currently see it.

### 1.1 Research-report products (advocate, provost, press, researcher)

| Product | State | What it carries |
|---|---|---|
| `portal/FINDINGS.md` | mature, current | Per-major year-10 destinations, sectors, seniority curve, every design decision and its cost |
| `archetypes/FINDINGS.md` | mature, **numbers stale, population wrong** | 15-bucket panel, 551,560 persons, 6.84M person-years, movement rates, validation and its limits. Only 37.7% of the panel is L1 humanities |
| `industry/METHODS.md` | mature | 4-level classifier, LLM jury, calibration. Our most defensible methods writeup |
| `edu_clean/HUMANITIES_CLASSIFICATION.md` | mature | The L1/L2/L3 boundary. Anyone who asks "who counts as humanities" is answered here |
| `METHODOLOGY.md` + `docs/audits/` | mature | Entity resolution, gold sets, benchmark scores |
| `cohorts/` (5 phases) | built, **stale panel** | Entry cohorts, scarring, survival, typologies, generational |
| `transition_network/` | built, unread | Backbone, centrality, communities, SpringRank, motifs, temporal drift |
| `enrichment/results/enrichment.json` | built, **no consumer** | Volunteering 16.1% vs 13.0%, publication 5.6% vs 3.6%, honors 10.7% vs 8.5%, professional multilingualism 10.8% vs 8.7% |
| `docs/notes/2026-08-12-eight-arguments-audit.md` | current | The falsification pass. The most valuable document we have for the advocacy venue |

### 1.2 Website products (student, advisor)

| Product | State | What it carries |
|---|---|---|
| Overview plate | shipped | "There is no default job. There is a field of real destinations." The best sentence on the site |
| Destination fan + drill-down | shipped | 23 SOC groups, share/RR toggle, each cell opens into 6-digit roles |
| Employer field | shipped | The dot cloud. 93% of employers hired exactly one graduate, drawn honestly as stipple |
| Sectors reached | shipped | Industry L1, and it is carrying a 52-63% unresolved share it does not disclose loudly enough |
| Snapshots scrubber | shipped | Y1 / Y3 / Y5 / Y10 |
| The long view | shipped | Median seniority by years since anchor |
| Mobility styles | shipped | Early movers vs stayers |
| Well-trodden pathways | shipped, thin | 2-stage routes. 8 each for arts/commmedia/english/history, 6 for philrel |
| The graduate-school step | shipped, buried | English 35.1% enroll within 5 years. JD ×2.8, MFA ×8.5. History 39%, JD ×5.2 |
| Six myth cards | shipped | All computed at render, no hand-typed numbers |
| Choices | shipped, near the bottom | Double major, grad school, internship, military, service year, self-employment |
| Data & methods | shipped, strong | Corpus, boundary, evidence bar, honesty commitments, funnel |
| `prototype/atlas.html` | prototype, mostly invented | 16 archetype marks. Two measured plates: educational provenance and the undergraduate-to-graduate paths plate |

### 1.3 Built, finished, and invisible

This is the list that matters most, because none of it needs new modeling.

| Asset | Size | Consumers |
|---|---|---|
| Archetype occupancy + state flows + job flows | 551,560 persons (37.7% L1), 5.8M person-steps | **zero** (Phase 5 was never built) |
| Enrichment layer | 246,482 humanities persons | **zero** |
| Institution metadata (IPEDS control, Carnegie, region, metro) | 70.9% of humanities persons | **zero** |
| Certifications | 60,510 humanities persons, 185,466 credentials | **zero** |
| Geography (`location_us_state`, `from_location`→`to_location`) | 51.6% state, full edge list | **zero** |
| Free-text work descriptions | 5.2M steps, 50.9% of non-duplicates | one, unrelated |
| Concurrency (two jobs at once) | `paths/_concurrency.parquet`, built 06-04 | **zero** |
| Transition richness (dwell, gap, overlap, type) | 6.18M transitions | stability slice only |

### 1.4 The one thing to fix before any of it

The redesign is **still uncommitted**: 57,326 insertions across 15 tracked files, plus 172
untracked paths including the whole `archetypes/`, `career_clean/` self-employment work,
and every plan document. A mid-session kill during this same body of work already cost us
a render bug once. Nothing below should start on top of this tree.

---

## 2. The eight messages, message by message

Read these as arguments, not as thresholds. In every case the message is worth making.
What changes is the sentence that carries it, and whether it is comparative.

### 1. A humanities degree opens a possibility space, not a single pipeline

**This is our strongest message and it is already the site's headline.** Keep it. Change
one thing about how we say it.

The evidence is dispersion, and dispersion is what we measure best. The largest single
year-10 destination bucket holds 12.5% to 15.2% of a cohort depending on the major, so
roughly seven in eight people are somewhere else. Employers are so dispersed that 93% of
them hired exactly one graduate. Sixteen SOC major groups are reached by English alone.
None of that depends on anyone else's numbers.

What must go is the comparative form. Our own committed `diversity.effective_destinations`
reads English 7.01, History 8.04, Philosophy & Religion 7.86, Communication & Media 6.42,
Arts 4.18, against a baseline of 8.25. **Every humanities cohort is at or below the
all-graduate baseline.** If we publish "wider than other majors," a reviewer opens our
JSON and ends the conversation. If we publish "nothing here is a pipeline," we are simply
right, and the same table becomes supporting evidence rather than a liability.

One carve-out to hold: **Arts is not like the others.** Effective destinations 4.18, top
bucket 24.2%, and the only cohort whose year-1 to year-10 change rate sits below baseline.
Arts is the most pipeline-like group in the set. Any sentence written for "the humanities"
as a bloc will be wrong about Arts, and Arts is 7,519 windowed people, our second-largest
cohort.

### 2. Careers unfold over time

Supportable, well-built, and currently invisible as a claim because it is spread across
four separate panels.

We have the decade curve, the Y1/Y3/Y5/Y10 scrubber, the launchboard's first-destination
to outlook sequence, year-over-year state flows, dwell and gap on 6.18M transitions, and
five phases of cohort analysis. What we do not have is the single number that makes the
point: **the share of people whose first decade is not linear.** Not "how much movement
happens" in aggregate, but "how rare is the straight line."

That number is cheap and we have never computed it. Share of people who held one occupation
group for ten straight years. Share who held one employer. Share whose seniority is
monotone. My expectation is that all three are small, and if they are, "linear careers are
exceedingly rare" stops being a slogan and becomes a measured finding with no comparison
in it at all. **This is the single highest-value uncomputed number in the project.**

Blocking: the panel is stale. Every movement figure we currently quote was computed before
the snapshot-date fix restored 182,634 steps, 167,368 of them somebody's most recent one.
Recency truncation is exactly the bias that would understate movement.

### 3. Humanities careers frequently reach unexpected destinations

Supportable, and it survives the comparison cut better than it looks, because
**"unexpected" is a comparison to a stereotype, not to another major.** That is the good
kind of comparison and we should keep it. The reader's own expectation is the baseline.

The portal already built the machinery for this in the expectation-inversion pass. Keep the
relative-risk apparatus, and point it at the stereotype instead of at business majors.
History to Legal at ×4.1 is a fact about what people assume history graduates do, not a
race against economics.

Two honesty obligations come with it.

The first is Arts again. Arts destinations are concentrated. The unexpected-destination
argument is strong for History, Communication & Media, English, and Philosophy & Religion,
and weak for Arts, and we should say so on the page rather than let a reader discover it.

The second is the employer list. Measured honestly on the career-entry axis, the largest
first-five-year employers of humanities graduates are Self-employed, US Army, US Navy,
Target, Air Force, Walmart, Starbucks, then Wells Fargo, AT&T, Amazon, Apple, Disney, IBM.
Legible cells exist underneath: U.S. House of Representatives in DC at 133, Condé Nast in
NY at 114, NYC Public Schools at 119, NYU at 147. **The moment we reorder that list to lead
with Condé Nast we have stopped being descriptive.** The answer is to publish the whole
shape: the big employers are big because they are big, and the interesting cells are
underneath them. That framing is both true and more useful to a student than either list
alone.

### 4. Transferable skills enable career moves

**This is the one message with no pipeline behind it, and no prospect of one from this
corpus.** LinkedIn's skills and endorsements section was not captured. There is no skills
field. Every candidate proxy is a title, a self-written description, a certification, or an
assertion from the framework, and a title-inferred skill is collinear with the move it is
supposed to explain. A hostile reviewer needs one sentence: you never measured a skill.

The message is still worth making. It just has to be made by somebody else, or made about
something we did measure. Three honest routes, and I would take all three:

- **Assert the skills, badge them amber, and own the authorship.** The director's framework
  already writes them in coursework language: close reading, rhetorical analysis, source
  evaluation, archival research. NHA is entitled to make a claim about what a humanities
  education builds. We are not entitled to present it as a measurement, and the badge
  discipline we already ship is exactly the mechanism for keeping those apart.
- **Replace "skills" with "moves" wherever a number is attached.** 52% of job changes moved
  into a different kind of work; 32% moved into a different industry; 57% held more than one
  kind of work in the first ten years. Then the credibility purchase: we measure the moves,
  we do not measure skills, and we cannot say what caused any move.
- **Use certifications as the measured, actionable half.** PMP 746, notary 802, Series 7 357,
  CompTIA Security+ 304, real estate 290, Certified ScrumMaster 272, UX foundations 255,
  RN 244. This is the only asset in the corpus a student can act on this semester, and it
  is a genuine record of humanities graduates converting a degree into a specific
  occupational entry. It is not a skills measurement, but it is the closest true thing.

Drop the comparative half of this message entirely. "Bigger leaps than technical
backgrounds" requires a skills measurement we do not have, on a population we cannot
compare fairly, about a trend we cannot observe.

### 5. You can chart a course, and also be ready for what arrives

As written this is rhetoric rather than a claim, which is fine for a headline and unusable
as a caption. It becomes measurable when you run it backwards.

The data supports exactly one direction: **from a destination, back to its origins.**
"People who reached this work most often came from these places" is describable. "This
path leads to that job" is a prescription the data cannot license. The state-flow tensor
already holds this and nothing renders it.

The measurable version of "chart a course and stay open" is origin dispersion: people who
started in the same place were, ten years later, in N different kinds of work. That is a
real number, it is a possibility-space argument rather than a movement argument, and it is
the correct evidence for the feeling this message is trying to produce.

### 6. Many career paths converge in leadership positions

**Do not lead with this anywhere, and never attach earnings to it.**

Two separate problems. On the comparative side, humanities sit below the all-graduate
baseline in SOC major group 11 at every career age, and the gap widens with age. On the
construct side, 28% of humanities management person-years at year 1, rising to 40% by year
15, carry SOC 11-1011 "Chief Executives", which is a documented lexicon artifact collapsing
founder, owner, "Chief" and "Head". A large share of what we would be calling leadership is
self-employment wearing a management code.

And the convergence half only works in the vocabulary we have been told not to use
publicly. Among humanities in management at year 10, on the public SOC axis 70.3% were
already in management at year 1. On our internal archetype axis, 36.5% were. A reviewer who
sees both will say we picked the taxonomy that gave the answer, and they will be right.

What survives, descriptively and within humanities only: **responsibility accumulates, and
administration is a real door into it.** Admin to Managers is among the largest measured
year-over-year flows, and three-stage routes ending in management clear n≥900 in quantity:
Admin→Admin→Managers 2,433; Sales→Sales→Managers 1,647; Analysts→Managers→Managers 1,257;
Legal/Policy→Legal/Policy→Managers 1,021; Educators→Educators→Managers 978;
Creatives→Creatives→Managers 959. Reframing the 10.6% of person-years sitting in
"Administrative & Coordination" as being on a recognized entry route into organizational
leadership, rather than parked in a residual bucket, is one of the strongest and kindest
true things we could tell a nervous graduate.

On earnings: we have no wages, we will never have wages, and the mid-career catch-up claim
cannot be made from this corpus in any form. The right move is to pair our destination data
with external earnings sources by citation and recompute nothing. Every audience we have
consulted, real and simulated, arrived at the same answer independently.

### 7. Your coursework gives you skills that translate to careers

Not supportable from the coursework table, and the reason is worth knowing because it
points at the replacement.

`parsed/courses` covers 13,854 of 246,482 humanities people. There is no date, no
institution, and no foreign key to an education row, so a course cannot be attached to a
degree, a year, or a school. After anchoring and windowing, 1,329 people remain at
career-year 10. And the content runs against us: the most-listed courses among humanities
majors are Project Management, Public Speaking, Typography, Marketing, Statistics, and
Financial Accounting. Humanities-flavored titles total 10,968 rows against 14,345
business and STEM. Humanities majors who list coursework mostly list their non-humanities
coursework. Selection on who lists is severe and correlated with outcomes.

**The honest replacement is already built and already measured: educational provenance.**
One correction before any of these numbers is quoted: they are computed on the L3 panel, so
the "largest undergraduate feeder" figures below currently report biologists into legal work
and psychologists into healthcare. Those are true of a liberal-arts panel and misleading
about humanities graduates. Re-cut first, then use.
Not "your coursework gives you skills," but "the people doing this work studied these
things, to this level, at these places." The atlas plate has it for all fifteen marks:
Creatives are 65.3% bachelor's-terminal and 55.0% Fine & Performing Arts; Educators are
72.1% graduate-degreed; Legal/Policy is 70.1% graduate-degreed with Biological Sciences as
its largest single undergraduate feeder at 18.4%; Healthcare 60.0% graduate.

That is a stronger version of the same message. It answers the question a student is
actually asking, which is not "what will I learn" but "what did the people who got there
study." And it is measured, not asserted.

### 8. These are concrete career pathways

Partly supportable, and **entirely gated on one decision nobody has made: the time axis.**

Same population, same n≥10 bar, first five career years:

| Unit | Graduation-anchored | Career-entry |
|---|---|---|
| Named employers | 142 | **3,788** |
| Employer × occupation group | 41 | **1,716** |
| Employer × US state | 15 | **1,513** |
| Employer × city | 3 | **983** |

A 25× to 300× difference produced by the anchor choice alone, not by the suppression bar.
The graduation anchor drops about 90% of humanities people because only ~20% of CIP-coded
bachelor records carry a usable end year.

I would take career-entry as the primary axis and keep the graduation subset as a labelled
sensitivity check, and I would accept the cost, which is that we can say "in the first five
years of working life" and never "five years after graduating." A provost will ask why. That
is a much smaller price than having nothing concrete to show.

**The recommended unit is employer × occupation group.** 1,716 cells clear the bar. Ship
three numbers with any named list: the cell n, the suppressed-cell count, and the singleton
share. The dispersion is not a caveat. It is the finding, and it is what stops "here are
the employers" from reading as "here is the funnel."

Multi-step named routes at role grain are not available. The pipeline's documented ceiling
is 8 persons, which is why `PATH_MIN_STAGES` was dropped to 2. Three-stage routes exist at
archetype grain in quantity and are unwired.

---

## 3. What reducing comparison costs, and what it buys

Worth being precise, because the comparative machinery is not decoration. Baseline
relative risk is computed by the same code path as every major, `baseline RR == 1.0` holds
by construction and is tested, and three bias-check modules exist solely to guard it.

**What it buys.** Three of the eight messages stop being falsifiable by our own output.
The seniority-coverage reversal problem disappears, since it only bites when you compare
groups whose missingness differs. The differential-attrition worry stops being load-bearing,
because "common-mode bias cancels in comparison" was the defense that needed it. And the
register problem resolves: a student does not want to know how they rank, and the honesty
apparatus that a comparison requires is precisely what reads to them as hedging.

**What it costs.** Two of our sharpest findings are comparative and would have to move to
the report rather than disappear:

- **Occupation moves, sector stays.** Humanities change occupation group between year 1 and
  year 10 well above baseline (History 54.5% vs 42.1%) while industry change sits at
  baseline (37.6% vs 33.8%). Humanities graduates carry the same sector into different work.
  Sharper and more defensible than "possibility space," and it is genuinely ours.
- **Independent practice.** Humanities run 1.7 to 1.8× baseline in self-employment and
  ownership at every career stage, rising from 7.9% in years 1-3 to 12.0% in years 13-20,
  against 4.4% to 7.3%. 100% coverage, no SOC code, no seniority word, no graduation
  anchor, no model layer. Immune to every objection that sinks the leadership argument, and
  it answers the anxiety students actually voice. The answer to "will I be freelancing
  forever" is no, 88% are not, and the independent share grows with age rather than
  collapsing.

**The rule I would write down.** Comparison lives in one place: the report's advocacy
section, where a trained reader is expecting it and the caveats can be stated in full. The
website compares to the reader's expectation and to nothing else. And crucially, reducing
comparison must never become a way of not publishing comparisons that came out badly. We
have computed the destination-diversity table and the management gap. Both go in the
report, plainly, in the same voice as everything else. Both non-advocacy audiences we
consulted asked us to publish findings that hurt, and this is the test of that commitment.

---

## 4. Website audit against the eleven functions

| Function | Built? | Verdict |
|---|---|---|
| Explore specific possibilities and pathways | partly | Aggregate grain only. A student means a name, a title, a place. We have none of those on the page |
| Possibility space, not a pipeline | **yes** | The strongest thing we have shipped. Leave it alone |
| Career Skill Archetypes as entry point | conflicted | See below |
| Unexpected destinations, assumed paths are a minority | partly | Drill-down and distinctive destinations exist. The myth layer should lead with this and does not |
| Choose your own adventure | partly | Choices is about decisions, not routes. The section colleagues liked is the Stories walkthrough, and it is at the bottom |
| Overall findings and advocacy points | **no** | This is the report. The portal should link to it, not contain it |
| Careers unfold over time, linear paths rare | partly | Four panels, no headline number. The linearity share is uncomputed |
| Transferable skills, bigger leaps than technical | **no** | No pipeline, and the comparative half is not achievable |
| Convergence in leadership, earnings catch-up | **no** | Leadership needs the descriptive reframe. Earnings is out permanently |
| Humanities as foundation for graduate study | **built, buried** | The best-supported message on the list, one panel deep in a walkthrough |
| Portal: examine the underlying data set | **yes**, with one gap | Data & methods is strong. There is no privacy answer |

### 4.1 The archetypes conflict, and how I would resolve it

You want Career Skill Archetypes as the entry point. Every audience we modelled rejected
archetype vocabulary as a public-facing object, unanimously and independently, while
endorsing it as internal machinery. That is the sharpest disagreement between the brief and
the prior work, and it deserves a real answer rather than a deferral.

**I think both are right, and the conflict is about the label rather than the structure.**
What the audiences rejected was being told what they are: "you are a Communicator," a shape,
a horoscope with a sample size. What they did not reject, and what career services actively
wanted, is grouping work by what it involves rather than by industry. That grouping is the
useful part of the archetype idea and it is what the director's framework is actually for.

The resolution has three parts:

1. **Use the archetype as a door, never as a label.** The entry question is "what do you
   like doing," and the answer returns a set of doors with evidence behind each, not a
   verdict. The framework's nine first-person orientations were written for exactly this.
2. **Name the doors in the vocabulary underneath, not the vocabulary on top.** The
   framework already supplies roughly 70 career pathways with plain names: Writing &
   Editorial, Project Management, Fundraising & Development, Learning & Development,
   Libraries & Archives. Nobody has to learn those. They are recognizable, they are what a
   job posting says, and they are specific enough to be useful. The nine macro names can
   organize the page without ever being asserted about a person.
3. **Keep the fifteen internal.** They are validated, they are what the flow tensors are
   built on, and nothing downstream needs to be rebuilt. Ship a derived layer, not a
   replacement.

That gives you the archetype entry point you asked for and removes the thing the audiences
objected to. It also fixes the measured defect: the buckets that stretch too broadly are the
ones that mix dimensions. Nonprofit is a sector. Hospitality is a sector. Founders is a work
context. Managers is mostly a level. Those three have our three lowest purity scores, and
they are category errors rather than tuning problems.

One thing not to paper over: **frontline service work needs a home, and it should be a
named one.** It is 2.4% of person-years and concentrated in career-years 1 to 3. Folding it
into a nicer-sounding bucket would violate the honesty rules the whole project rests on, and
it would cost us the resilience argument, since you cannot show people moving up and out of
frontline work if frontline work is not on the map.

### 4.2 The graduate-study opportunity

This is the recommendation I feel most strongly about, because the gap between evidence and
surface is the widest here.

We have measured, window-clean, on start-dated enrollment within five years of the anchor:

| Cohort | Enrolls in any graduate or professional degree | Signature concentration |
|---|---|---|
| History | **39.2%** | Law (JD) n=208, ×5.2 |
| English & Literature | **35.1%** | Law ×2.8, Fine arts (MFA) ×8.5 |
| Philosophy & Religion | **34.1%** | Law (JD) n=73, ×2.9 |
| Communication & Media | 16.9% | Business (MBA) n=190 |
| Fine & Performing Arts | 16.3% | Fine arts (MFA) n=299, ×9.3 |

Note the split, because it changes the sentence. **"Ideal foundation for graduate study" is
true of History, English, and Philosophy & Religion, where a third to two-fifths continue
within five years. It is not true of Arts and Communication & Media, where roughly one in
six do.** That is the same Arts-shaped exception as everywhere else in this review, and
Communication & Media joins it here. Written as a claim about "the humanities" it is wrong
about 14,564 of our 22,427 windowed people. Written per cohort it is strong, specific, and
useful, and the concentrations are the interesting part: History graduates who continue go
to law school at five times the all-graduate rate, Arts graduates who continue go to an MFA
at nine times it.

And the atlas paths plate holds
40,388 people with a humanities or humanistic-social-science bachelor's plus a fielded
graduate degree, spread across fifteen graduate field families: business and management
7,736, education 7,370, communication and journalism 3,256, visual and performing arts
3,079, law 2,763, social sciences 2,380, health professions 1,986, public administration
and social work 2,134.

That is the message "a humanities background is an ideal foundation for graduate study
across all fields," and it is measured, current, non-comparative in its useful form, and
directly answers a question every anxious sophomore and every skeptical parent asks. It
occupies one panel inside step five of a walkthrough.

**It should be its own view.** Undergraduate field on one side, graduate field on the other,
destination on the third, and a student can enter from any of them.

### 4.3 What is missing from the site as a matter of register

Everything on the page is a distribution. Fans, curves, shares, meters, dot clouds. Nothing
on the page is a person, a place, or a piece of work. The assets for the missing register
are exactly the ones sitting unwired: employers, three-stage routes, geography, and 5.2M
descriptions of what the work actually involves.

Two operational gaps that will block adoption regardless of how good the page is:

- **An empty cell must explain itself.** A student who asks about Classics and gets a blank
  screen because of the minimum-ten rule concludes that nobody with their degree gets a job.
  Our suppression rule is methodologically correct and has a user-facing failure mode we
  have never designed for. "Fewer than 10 graduates worked at any single employer in this
  field, so we cannot name one. 2,682 employers appear once each" is both honest and
  reassuring. A blank is neither.
- **"Is my profile in this?"** There is no written answer, for the student or for campus
  counsel. Career services cannot put the tool in front of students without one. This is a
  writing task, not an engineering one, and it is a prerequisite.

---

## 5. Where we have no pipeline at all

Ranked by value to the eight messages, not by effort.

| # | Missing pipeline | Serves | Notes |
|---|---|---|---|
| 1 | **Career linearity typology** | Message 2 | Share of decades that are single-occupation, single-employer, monotone-seniority. Cheap. Non-comparative. The number that makes "linear careers are rare" a finding |
| 2 | **Archetype fact sheets, generated not written** | 1, 3, 6, 8 | One measured page per bucket: occupancy, top roles, top employers, sector spread, work-context mix, provenance, in-flows and out-flows, certifications. Deliverable-agnostic. Also the fastest way to see which buckets are incoherent |
| 3 | **Employer × occupation × geography surface** | 8, 1 | The most-wanted asset in every audience exercise. 1,716 cells at the recommended unit. Blocked only on the anchor decision |
| 4 | **Certifications module** | 4, 8 | The only actionable asset in the corpus. Fits `portal/choices.py` exactly as built |
| 5 | **Career-pathway lexicon** | 3, 8, and the archetype entry point | The framework's ~600 curated titles matched against the 2.6M-role vocabulary. Turns nine macro doors into ~70 specific ones |
| 6 | **Sector + work-context derived layer** | 1, 4, 6 | Dissolves Founders into a context and Nonprofit into a sector, which fixes three known defects at once |
| 7 | **Institution-type facet** | advocacy | 70.9% coverage. The first question an institutional audience asks, and the answer to "that's Michigan, we're not Michigan" |
| 8 | **Geography** | 1, 8 | Data fully present, zero consumers. Two of three audiences named it their biggest disappointment. 51.6% state coverage needs a look before we design around it |
| 9 | **Differential attrition test** | credibility | If humanities profiles go dormant at a different rate than baseline, the comparison defense weakens. We do not know by how much, and this is the bias a student said worries them more than missing salary |
| 10 | **Descriptions as a vocabulary layer** | 4, 7 | 5.2M examples of how people who did this degree describe their own work. Use it to supply language, never to make claims about people. Composite or paraphrase only |

---

## 6. Data with unused potential

Beyond the unwired list in §1.3, four assets nobody has proposed a use for.

**`people_also_viewed` and `similar_profiles`** (173,461 and 29,454 humanities persons).
LinkedIn's own similarity graph. This is an **external** validation of the archetype
assignment, which is precisely the fair test `archetypes/FINDINGS.md` §5 admits is missing.
Do platform-similar people share an archetype? Our current validation numbers are
self-agreement statistics, since SOC-detail, SOC-major, and the keyword tree are all
deterministic functions of the same ten-word title string. This is the only independent
arbiter available, and it is free.

**`profiles.about`** (58.5% of humanities persons wrote 80+ characters). The corpus's only
record of how people describe themselves, as against how a taxonomy codes them. That
contrast is interesting in itself, and it is a better answer to "what does a humanities
graduate bring" than any skills proxy, because it is what they say rather than what we infer.

**Concurrency and overlap.** `paths/_concurrency.parquet` has existed since 06-04 with zero
consumers, and 922,202 transitions carry an overlap. The panel's one-role-per-year rule
hides portfolio careers entirely, which means our movement rates are a lower bound and the
"two jobs at once" reality of creative and independent work is structurally invisible. Both
of those are findings, not noise.

**`bio_links`** (34,584 persons). A personal site or portfolio is a hard behavioral
indicator of independent practice that `employment_type` misses.

---

## 7. Three blockers, in order

**1. The stale panels.** Verified again today. `cohorts/panel.parquet` is dated 07-21 and
`person_year_archetype.parquet` 07-22; `paths/steps.parquet` was rebuilt 08-05. Under the
old snapshot anchor, 182,634 steps were dropped as future-dated, 167,368 of them a person's
most recent step. That systematically truncates recent cohorts at exactly the end of the
observation window. Every movement, occupancy, and generational figure we currently quote
sits on it, and so do both measured plates in the atlas. Rebuild both, then re-run.

**2. The anchor decision.** Career entry or graduation. It changes the number of nameable
cells by 25× to 300× and it gates the most-wanted argument on the list. My recommendation
is career-entry primary, graduation subset as a labelled sensitivity check.

**3. The industry coverage correction.** Informative L1 is 53.03%, and at the year-10
endpoint specifically it runs 52% to 63% unresolved by major. The site's "Sectors reached"
panel is drawn on that, and the portability argument leans on it. It is still the
best-covered axis we have. It is not a free one, and the page should say so where the chart
is, not only in the methods tab.

---

## 8. What I would do next

**Now, before anything else.** Commit the tree. Rebuild the two panels. Re-run the archetype
and cohort findings. Correct the industry coverage figure everywhere it appears.

**Then, and these are inputs to every remaining decision.**

1. **Archetype fact sheets, generated from the pipeline.** They give the director something
   data-true to react to, they force the copy to derive from one measured source instead of
   two independent voices, and they expose incoherent buckets before we redesign anything.
   Useful under every possible deliverable.
2. **The linearity typology.** One query set, one number, and it converts message 2 from a
   slogan into a finding.
3. **The anchor decision**, taken and written down.

**Then split the product.** A written report carrying the comparative findings and the
method, and a student-facing site carrying description, names, and routes. They share a
substrate and nothing else. The report is cheaper, more citable, and better matched to an
argument built on a handful of strong findings. The site is where the possibility-space
message lives, and it should stop trying to also be the defense.

**Then build the site's missing register**, in this order: employers and places, the
graduate-study view promoted to its own surface, the archetype doors named in pathway
vocabulary, certifications as a seventh choice, and the empty-cell copy that keeps
suppression from harming the student it was meant to protect.

**Two things to write rather than build**, and both are on the critical path: the privacy
answer, and the population statement. The corpus over-represents people whose degree led
somewhere legible, by construction. K-12 teaching is one of our largest destinations and
teachers are among the least likely to keep an active profile, which means our best story
is probably undercounted and our error runs in the flattering direction everywhere else. A
reviewer will find that. Stating it first is worth more than it costs, and it is the
precondition for every other claim being believed.

---

## Appendix. Language rules worth adopting as project standard

Two mechanical rules that resolve most of the register arguments before they start.

1. **Every sentence names its population before its number.** Never "42% of English
   majors." Always "Among English graduates in this sample who maintain professional
   profiles, 42%."
2. **Past tense, count first, no second person.** "N people did X" is describable. "You can
   do X" is a prescription the data cannot license.

| Never | Instead |
|---|---|
| "The path from coordinator to program manager" | "1,021 people in this sample held a policy or research role at year 1 and a management role at year 10." |
| "Top employers for English majors" | "Employers where 10 or more graduates in this sample worked in their first five years. 93% of employers hired exactly one. This is the dense corner of a very sparse field." |
| "A common route into management" | "Where people who started here were ten years later, most common answer first. This describes what happened to them, not what will happen to you." |
| "This pathway leads to..." | "People who reached this work most often came from..." |
| (a blank screen) | "Fewer than 10 graduates worked at any single employer in this field, so we cannot name one. 2,682 employers appear once each." |

And the standing sentence for the advocacy venue: we can tell you where these graduates
worked, we cannot tell you what they were paid, and we do not claim this is every graduate.
