# Product maps: the student site, the advisor portal, and where the writing goes

**For Visual Dialogue. 1 September 2026.** Written to be designed from, not admired.

Four maps. The first two describe the undergraduate-facing site, the third describes the
advisor-facing portal, and the fourth traces every panel in both back to the dataset that
feeds it and the person who writes the words around it.

**How this document was built, because it matters to how you read it.** The maps are derived
from the data, not from the prototypes. Every structural decision below was tested against
the corpus first, and two of them contradict what our own planning documents assumed. Where
that happened I kept the measurement and changed the plan. Nothing here is drawn because it
would look good.

**Status vocabulary**, used on every node in every map:

| | Meaning |
|---|---|
| **Ready** | Computed, tested, in `portal_data.json` today |
| **Built, unwired** | The dataset is finished. Needs a query and a panel. No new modelling |
| **Needs a build** | Real analytical work, sized where I have a number |
| **Write, don't build** | A writing task. Nothing to compute |

---

# Part 0 — What the data licenses

Five findings shaped every map that follows. Four of them are load-bearing; one is an honest
negative that changes a headline we have been planning to use.

## 0.1 The corridor is dense

The second question we want the site to answer — *how do I get to X from where I am?* — needs
origin→destination cells with real support behind them. Measured on the canonical cohort
(narrow humanities or humanistic social science on a bachelor's, windowed, **355,437 people /
4,205,058 person-years**), taking the kind of work someone was in at career year 1 against the
kind of work they were in at career year 10:

| | cells | |
|---|---|---|
| all origin → destination cells | 144 | 267,001 people have both endpoints |
| clearing n ≥ 10 | **144 of 144** | nothing suppressed |
| clearing n ≥ 100 | 133 | |
| clearing n ≥ 900 | 58 | |
| median cell | 614 people | |

**Nothing is suppressed at this grain.** The corridor view is buildable today with no new
modelling, and it is the piece that turns a browsing tool into an answering one. Our own
planning documents had recorded a ceiling of eight people on multi-step named routes — true,
but that is at *job-title* grain. At the grain a student actually reasons in, the map is full.

## 0.2 The straight line is common — and our planned headline is wrong

We have been intending to lead the decade screen with *almost nobody's first ten years is a
straight line*. Measured on 238,967 people observed for all ten years:

| distinct kinds of work over ten years | 1 | 2 | 3 | 4+ |
|---|---|---|---|---|
| share of people | **41.7%** | 35.1% | 17.2% | 6.0% |

Mean 1.89. Fused seniority never moved for 24.8%. 89.2% held one employment type throughout.
Split by what people studied, the range is wide:

| | one kind of work for ten years |
|---|---|
| Theology | 51.7% |
| Fine & Performing Arts | 51.4% |
| English & Literature | 44.3% |
| History | 40.4% |
| Communication & Media | 40.3% |
| Humanistic Social Science | 36.0% |

Two in five stayed put. The planned sentence is refutable from our own panel, and worse, it
tells 41.7% of our readers that they are the anomaly.

**The sentence that is both true and kinder: three in five people changed the kind of work
they do, two in five did not, and both of those are ordinary.** Design the decade screen for
a distribution with two modes, not for a slogan about churn.

## 0.3 There are eleven doors, not nine

The framework gives nine first-person orientations. Crosswalked against what the corpus
actually contains, two large populations have no door, and both of them carry an argument:

| Door | year 1 | year 5 | year 10 |
|---|---|---|---|
| Leaders & Organizers | 24.0% | 23.9% | 25.1% |
| Communicators & Creators | 15.6% | 16.6% | 17.0% |
| Researchers & Educators | 7.6% | 7.1% | 6.7% |
| Analysts & Strategists | 5.3% | 6.8% | **7.7%** |
| Helpers & Service Professionals | 7.4% | 7.6% | 6.9% |
| Connectors & Relationship Builders | 7.2% | 6.8% | 6.6% |
| Advocates & Advisors | 6.7% | 6.2% | 6.0% |
| Builders & Technologists | 4.7% | 5.2% | 5.2% |
| Financial & Resource Stewards | 2.5% | 2.6% | 2.8% |
| **Frontline Service** — no door in the framework | 4.0% | 2.5% | **1.5%** |
| **Founders & Independent** — the framework calls this a work *context* | 2.4% | 3.0% | **3.8%** |
| Unclassified | 12.6% | 11.6% | 10.9% |

Frontline service falls by more than half over the decade. That decline *is* the resilience
argument, and you cannot draw people moving up and out of a door that is not on the map.
Independent practice grows by half again — and employment type is the only axis in the whole
corpus with complete coverage, so it is the claim we can defend most easily and the one we
have been burying inside a framework dimension.

**Practical rule: eleven doors on the page, plus a named and explained residual.** Never
twelve with "Unclassified" drawn as a door; never nine with two real populations hidden.

## 0.4 The axes are not peers, and the design must not draw them as peers

The framework proposes four dimensions — kind of work, career pathway, sector, work context.
They have wildly unequal evidence behind them. Measured coverage:

| Axis | Column | Coverage |
|---|---|---|
| **Employment type** (→ work context) | `steps.employment_type` | **100%** |
| Seniority, fused | `steps.seniority_score` | 95.2% |
| Education field, person-level | `education_person.cip2_pooled` | 87.0% |
| Location text present | `career_steps.location` | 63.8% |
| Education field, record-level | `education.cip2` | 58.8% |
| **Industry L1** (→ sector) | `step_industry.l1`, excluding the unresolved sentinel | **53.0%** |
| Free-text job description | `career_steps.description` | 50.8% |
| Industry L3 | | 23.7% |
| **SOC occupation** | `steps.occupation_code` | **21.5%** |
| Industry L4 | | 2.0% |

Two consequences for the design.

**Sector is a filter, not a spine.** At 53% resolved it cannot carry a screen. The unresolved
share appears beside every sector chart, and the unresolved bucket is never drawn as a slice.

**Work context is stronger than we have been treating it.** Founder, freelancer, employee is
the one thing we know about everybody. Two of our three audience personas independently called
employment type underrated. Give it a real surface.

## 0.5 Geography is cheaper than we thought

Location keeps getting deferred because state coverage reads as 51.6% of all steps. But
conditional on a resolved US location, **94.9% resolve to a state** (5,568,459 of 5,866,794).
The gap is missing location text, not a parsing failure — which means the geography feature
career services called their students' most concrete need is a query against an existing
column, not a project. Coverage still has to appear on the face of any map we draw.

## 0.6 The tail is most of the map

The canonical cohort held **638,368 distinct job titles**. 86.4% of those titles were held by
exactly one person, and singleton titles account for **29.2% of all the jobs anybody in the
cohort ever held**. Meanwhile 13,933 titles clear the ten-person reporting bar, so we can name
twelve thousand specific unexpected destinations without ever breaching suppression.

This reframes our central claim. The possibility space is not wide because graduates reach
twenty-three occupation groups. It is wide because they reach six hundred thousand distinct
jobs, and a third of the observed working life happens in jobs held by exactly one of them.
Full treatment and the five design devices in §1.8.

## 0.7 What we can never say

Inherited by every node in every map that follows, and stated on the site rather than
footnoted:

- **No wages, no earnings, no ROI.** Not a gap to close later. External earnings sources are
  cited, never recomputed against our data.
- **No unemployment.** A gap between jobs is unknown, never inferred joblessness.
- **No prediction.** We describe where people went. We never say where a reader will go.
- **No representativeness.** This is people who maintain a public professional profile, and
  the bias runs in the direction of our own argument. K-12 teaching is one of the largest
  humanities destinations and teachers are among the least likely to keep an active profile,
  so our best story is probably undercounted and our error flatters us nearly everywhere else.
- **No demographics, no individual profiles, no verbatim quotation.**
- **No skills measurement.** LinkedIn's skills section was never captured. Skills language on
  the site is NHA's assertion, visibly badged as such, and never dressed as a measurement.

---

# Map 1 — The student site as a state machine

The site is not a screen sequence. A sequence answers *where can I go* and then stops, and a
student who arrives already knowing they want to work in publishing has to sit through the
introduction to get nowhere. What the two questions actually describe is one explorer with two
poles.

```
                          state = { origin?, destination?, horizon, grain, like-me filters }

     ORIGIN not set                                    ORIGIN set
   ┌────────────────────────────────────┬────────────────────────────────────┐
D  │  THE FIELD                         │  FORWARD FAN                       │
E  │  every destination at once,        │  "Where people who started here    │
S  │  nothing ranked, nothing largest   │   were, ten years later"           │
T  │                                    │                                    │
n  │  answers: is there anything        │  answers: WHERE CAN I GO           │
o  │  out there at all                  │                                    │
t  │  Ready                             │  Ready                             │
   ├────────────────────────────────────┼────────────────────────────────────┤
D  │  BACKWARD ORIGINS                  │  THE CORRIDOR                      │
E  │  "People doing this work came      │  the 144 cells, plus what people   │
S  │   from these places"               │   carried, how long it took, and   │
T  │                                    │   how crowded the door was         │
s  │  answers: WHO IS ALREADY THERE     │                                    │
e  │                                    │  answers: HOW DO I GET TO X        │
t  │  Built, unwired                    │  Built, unwired                    │
   └────────────────────────────────────┴────────────────────────────────────┘
```

Four modes, one screen, one vocabulary. The mode is a consequence of what the reader has
picked, never a navigation choice they have to understand.

## 1.1 Three front doors

All three set a pole and drop the reader into the explorer. None of them is a quiz and none
returns a verdict.

| Door | Sets | Data | Status |
|---|---|---|---|
| **What I studied** | origin = a field of study | `education_person`, five CIP bundles today, extensible | Ready |
| **What I like doing** | origin = one of eleven doors | framework orientations ⋈ archetype panel | Needs a build — the pathway lexicon |
| **A job I'm curious about** | destination = a role or kind of work | role vocabulary, 2.6M canonical titles | Built, unwired |

The second door is the framework's own first-person orientations — *I turn ideas into
messages, stories, and experiences that engage an audience* — used as a self-selection prompt.
The reader is never told what they are. They can open as many doors as they like, and the
interface should make opening a second one feel normal rather than like starting over.

The third door is the one nothing in our prototypes has ever offered and the one the brief
most directly asks for. It is also the door that makes the site useful to a senior rather than
only to a sophomore.

## 1.2 Every noun is a door

This is the single mechanic that turns the site from a report with tabs into a place where
discovery happens.

```
  a destination      ──click──▶  becomes the origin  (what comes after this?)
  a destination      ──click──▶  becomes the destination  (who is already there?)
  an employer        ──click──▶  destination = that employer
  a field of study   ──click──▶  origin = that field
  a credential       ──click──▶  destination = people who hold it
  a graduate degree  ──click──▶  origin = that undergrad+grad combination
```

Every route in the map is therefore a cycle, not a leaf. The reader who follows their
curiosity three hops out never hits a dead end and never has to press Back. **The design
consequence: there is no "results page."** There is one canvas whose two poles keep changing,
with a visible trail of where the reader has been so they can step back into any earlier state.

## 1.3 The zoom axis

The explorer works at two grains, and the reader moves between them the way they would zoom a
map. Both are already computed.

| Grain | Vocabulary | Coverage | Answers | Status |
|---|---|---|---|---|
| **Coarse** | 11 doors + residual | ~89% | "where can I go" | Built, unwired |
| **Fine** | real job titles | essentially complete | "how do I get to *this*" | Built, unwired |

The fine grain sits on `transition_network/role_backbone_edges.parquet` — **4,318,913
title-to-title edges** with relative risk and a disparity filter already applied, against the
occupation vocabulary we currently use, which covers 21.5% of steps. Nothing queries it today.
This is the largest single unspent asset in the repository and it is exactly the thing a
student wants when they have stopped asking about categories and started asking about jobs.

**Design rule for the zoom.** Coarse grain shows shape and never a ranked list. Fine grain
shows named things and always shows counts. The reader should feel the resolution increase,
not feel that they changed tools.

## 1.4 The "people like me" ladder

The brief asks that a reader see how people *like them* reached a destination. That is the
right ask and it is where sample size falls off a cliff. Measured, adding one condition at a
time to a destination:

| Conditioning | cells | ≥ 100 | ≥ 10 | below the bar | median n |
|---|---|---|---|---|---|
| destination only | 12 | 12 | 12 | 0 | min cell 4,418 |
| + where they started | 144 | 133 | 144 | 0 | 614 |
| + what they studied | 2,489 | 433 | 1,341 | **1,148** | 12 |

Forty-six per cent of three-way cells fall below the reporting bar. **But 98.5% of people sit
in a cell that clears it** — the combinations that fail are the rare ones, not the ones a
typical reader will construct. That asymmetry is the argument for building this view rather
than fearing it, and it is also the reason the interface has to handle failure gracefully
instead of rarely.

**A worked example, real numbers.** Reader studied English & Literature, wants to reach
advocacy, policy and legal work. Where did people who got there start?

| Started in | n |
|---|---|
| Advocates & Advisors | 402 |
| Leaders & Organizers | 196 |
| Communicators & Creators | 107 |
| Researchers & Educators | 46 |
| Analysts & Strategists | 35 |
| Connectors & Relationship Builders | 23 |
| Helpers & Service | 13 |
| Frontline Service | 13 |
| *below the bar:* Financial & Resource Stewards (7), Builders & Technologists (7), Founders & Independent (5) | |

Eight named routes, three suppressed, and the suppressed ones are named as suppressed with
their count of cells rather than silently dropped.

### The support meter, always visible

Every conditioned view carries a live count and a state. This is not a caveat; it is the
primary reading of the panel.

```
  n ≥ 100    describable      named routes, employers, credentials, timing
  10 ≤ n < 99  countable      counts and ranks only; no named employers
  n < 10     below the bar    the cell is named, the count is not shown,
                              and the interface says what it would take to see it
```

### The fallback ladder

When a condition drops the reader below the bar, the tool relaxes the least informative
condition automatically and **says so on the face of the panel.** It never returns a blank.

```
  rung 1   your field + your starting point + your destination
             │  below the bar?
             ▼
  rung 2   all humanities fields + your starting point + your destination
             │  ( in the worked example: 402 → 5,088 )
             ▼
  rung 3   all humanities fields + any starting point + your destination
             │  ( smallest destination cell in the whole map: 4,418 )
             ▼
  floor    never empty
```

**The words that go with rung 2, and they need writing before the component is built:**

> Fewer than ten people who studied Classics started in frontline service and were in legal
> and policy work ten years later — too few for us to describe honestly. Widening to all
> humanities graduates: 5,088 people reached this work, and here is where they started.

That is honest and it is reassuring. A blank screen is neither, and a student who asks about
Classics and gets nothing concludes that nobody with their degree gets a job.

## 1.5 What sits inside a destination

When the reader fixes a destination, five panels, in this order. The order is the argument:
what the work is, then how people got in, then what they carried, then how long it took, then
where it happened.

| Panel | Content | Source | Status |
|---|---|---|---|
| **What this work involves** | plain description of the work, composited from how people describe it themselves — never verbatim | `career_description_cluster_proposals`, 859,857 rows / **528,001 people** | Built, unwired |
| **Ways in** | the backward origins view, conditioned by the ladder above | corridor cells + role edges | Built, unwired |
| **What they studied** | field, level, and institution type of the people doing this work | `person_year_archetype` ⋈ `education_person` | Built, unwired |
| **What they carried** | credentials that show up, ranked | `parsed/certifications`, 1,673,732 rows / 545,414 people | Needs a build, small |
| **Where it happened** | employers with dispersion shown, and US state | `steps`, employer field + location | Ready pooled; state needs a query |

**Lead with "ways in."** Every audience exercise we have run said the same thing: a category
is only useful if opening it produces something a person can act on. Leading with the
category's share of the population tells a student nothing.

## 1.6 The register rule

Past tense, count first, no second person, population before number. This is the hardest rule
on the site and the one most likely to erode during design.

| Never | Instead |
|---|---|
| "The path from coordinator to program manager" | "1,021 people in this sample held a policy or research role at year 1 and a management role at year 10" |
| "Top employers for English majors" | "Employers where ten or more graduates in this sample worked in their first five years. 93% of employers hired exactly one" |
| "This pathway leads to…" | "People who reached this work most often came from…" |
| "42% of English majors" | "Among English graduates in this sample who maintain professional profiles, 42%" |

## 1.7 Empty states are a deliverable

Write them before the components that contain them. Every empty cell explains itself, gives a
number, and offers the next rung.

- **Below the bar:** *"Fewer than ten graduates in this sample worked at any single employer
  in this field, so we cannot name one. 2,682 employers appear once each."*
- **Suppressed within a list:** *"Three more starting points reached this work. Each had fewer
  than ten people, so they are counted here but not named."*
- **Not measurable at all:** *"We did not capture this. Here is what we have instead."*

## 1.8 The tail is the argument

Everything above describes the well-populated middle. The rare, quirky, unexpected routes are
not an edge case to be tolerated after the main work is done — measured, they are most of what
is out there, and they are the most persuasive thing we own.

Every distinct job title held by anyone in the canonical cohort, counted by how many people
held it:

| Held by | Distinct titles | Share of titles | Share of all jobs held |
|---|---|---|---|
| 1,000+ people | 144 | 0.0% | 20.6% |
| 100–999 | 1,527 | 0.2% | 20.8% |
| 10–99 | 12,262 | 1.9% | 17.0% |
| 2–9 *(below the bar)* | 72,651 | 11.4% | 12.4% |
| **exactly 1** *(below the bar)* | **551,784** | **86.4%** | **29.2%** |

**638,368 distinct job titles across 355,437 people.** Eighty-six per cent of them were held
by exactly one person, and those singleton jobs account for 29.2% of all the working life we
observe. The possibility space is not wide because there are twenty-three occupation groups.
It is wide because there are six hundred thousand different things people called their job,
and nearly a third of the mass sits in titles that occur once.

**The nameable tail is enormous.** 13,933 titles clear the ten-person bar, 12,262 of them in
the 10–99 band. We can name twelve thousand specific, unexpected jobs without ever going below
suppression. Nothing in any prototype has ever shown one of them. A sample of the 10–14 band,
drawn at random: children's book illustrator (11), town administrator (10), geographic
information systems manager (13), picture editor (12), journeyman carpenter (11), teaching
fellow in English (11), workers' compensation claims adjuster (12), airframe and powerplant
mechanic (10), wine sales (13), instructional design consultant (10).

### Five devices for the tail

**1. Rarity is a sort order, not a filter.** Every fan and every corridor carries three
orders, and the reader can flip between them at any time.

```
   most common first     ─  what most people did
   most distinctive first ─  highest relative risk against the all-graduate baseline:
                            where humanities graduates are over-represented, common or not
   rarest describable first ─ the n ≥ 10 floor, ascending: the twelve thousand
                            specific jobs nobody has ever shown a student
```

The middle order is the one that produces the genuinely surprising results, because a
destination can be small in absolute terms and still be somewhere humanities graduates land at
several times the baseline rate. The portal already computes relative risk in the fan; it is
currently a toggle nobody has a reason to press. Give it one.

**2. Draw what you cannot name.** Below ten people a cell is never dropped and never blanked —
it is rendered as an unlabelled mark. The employer dot cloud already does this: singletons
render as legible stipple, so the sparseness *is* the picture rather than a caveat underneath
it. Generalize that grammar to every rarity surface. The reader can see that the field extends
far past the labelled region, which is true, and cannot read a name off it, which is required.

**3. Raise the grain until the tail clears the bar.** A specific rare destination that fails
suppression usually belongs to a *kind* of move that does not. This is the second fallback
ladder and it runs alongside the "people like me" one:

> No one in this sample went from a Classics degree into marine archaeology. Widening to the
> kind of move: 214 people went from a humanities bachelor's into scientific and technical
> work without holding a science degree.

The reader's curiosity is answered at the resolution the data can support, and the sentence
says which resolution that is.

**4. Every view states its own tail.** A count of what is shown, a count of what is suppressed,
and the number of people inside the suppressed cells. In the three-way conditioned corridor:

| | cells | people | share |
|---|---|---|---|
| n ≥ 100 | 433 | 231,181 | 86.6% |
| 10–99 | 908 | 31,907 | 12.0% |
| 2–9, suppressed | 805 | 3,570 | 1.3% |
| exactly 1, suppressed | 343 | 343 | 0.1% |

Nearly half the cells are suppressed and they hold 1.5% of people. Say both numbers. The
suppressed cells are not a failure of the data; they are 1,148 routes that somebody actually
took.

**5. Uncommon is not unwise.** A thin route is labelled rare and real, never hedged and never
dressed up. *Fourteen people in this sample did this* is a complete, honest, encouraging
sentence. Deficit framing — "only fourteen" — is banned in the same way wage claims are.

### Two constraints on the tail surfaces

**Privacy.** The ten-person bar applies to any named cell, and rarity surfaces are where it is
easiest to breach by accident. A rare job title crossed with a named employer crossed with a
city can identify a person even when each facet alone clears the bar. **Rule: a rarity surface
names the kind of work, and never stacks a third facet below a raised bar.**

**Display strings.** `role_canonical` is a normalized token bag — the children's book
illustrator above is stored as `bookchildrenillustrators`. Any surface that shows a job title
to a human reads the modal `title_raw` for that canonical key. This is a one-line join and it
is the difference between a delightful surface and an unreadable one.

---

# Map 2 — Storyboard: one session, eight frames

One reader, one sitting, on a phone. Each frame names what the interface does, the query
underneath it, and the sentence NHA has to write.

| # | Frame | What the reader does | Underneath | NHA writes |
|---|---|---|---|---|
| 1 | **Arrival** | reads one sentence and sees the whole field of destinations at once, nothing ranked | pooled year-10 fan | the opening claim, and the population statement in the same viewport |
| 2 | **Commit** | says what they expect the most common destination to be, before seeing it | none — a UI device | the prompt, and the response to being wrong |
| 3 | **Reveal** | sees the largest single destination is about one in eight, and the field stays wide | `diversity`, `fan` | the gloss on being wrong, written to be encouraging rather than smug |
| 4 | **Pick a door** | chooses what they like doing, or their major | orientation → door crosswalk | the eleven orientations, in the reader's own voice |
| 5 | **The fan** | sees where people who started there went, and can flip the arrow | corridor, forward | the caption, in past tense |
| 6 | **Turn it around** | fixes a destination that surprised them and asks who is already there | corridor, backward | the direction rule, said in one line |
| 7 | **The far edge** | flips the sort to rarest-describable and scrolls a list of twelve thousand specific, odd, real jobs | role vocabulary at the n ≥ 10 floor | the pioneer line — rare and real, never "only" |
| 8 | **Narrow to me** | adds their field of study; watches the count fall and the ladder catch it | the "like me" ladder | the fallback sentences — all three rungs |
| 9 | **Something to do** | leaves with the credential, the graduate step, or the employer list for their state | certifications, `grad_track`, geography | what each choice meant for the people who made it, with the self-selection caveat given room |

**Frame 2 is the one to spend budget on.** Commit-before-reveal has been catalogued in our
inspiration file and never used. It is the single most effective device for the
expectation-inversion findings we already have, and it converts our best evidence from a
statistic the reader skims into a correction they participate in.

**Frame 7 is the one that will get shared.** It is also the cheapest thing on this list — the
vocabulary exists, the counts exist, and the only build is a join to a display string. A
student who finds one job on that list they had never heard of has had the experience the
whole site is for, and they will send it to someone.

**Frame 8 is the one that decides whether the site is worth building.** A student who leaves
with a feeling has been entertained. A student who leaves with a certification name, an
application deadline, or three employers in their state has been helped.

---

# Map 3 — The advisor portal as a separate instrument

Career services asked for two artifacts, not two doors on one site — and the advocate's
constraint is blunter still: *nobody opens a link in a hearing.* One surface trying to be a
research instrument and a reassurance instrument at once is the root of the cohesion problem
we already have. The honesty apparatus that makes a skeptic trust us reads to an anxious
sophomore as hedging.

**The portal's job:** let a person who is helping someone else answer a question in the room,
and leave with something they can hand over, cite, or put on a departmental website.

```
                        ┌─────────────────────────────────────┐
                        │            THE INSTRUMENT           │
                        └─────────────────────────────────────┘
                                          │
        ┌─────────────────┬───────────────┴─────────┬────────────────────┐
        ▼                 ▼                         ▼                    ▼
   ┌──────────┐    ┌─────────────┐         ┌──────────────┐      ┌──────────────┐
   │ LOOK UP  │    │  BRIEF ME   │         │ TAKE IT AWAY │      │  SHOW ME THE │
   │          │    │             │         │              │      │   METHOD     │
   │ any cell │    │ one sentence│         │ per-major    │      │ coverage,    │
   │ any facet│    │ one number  │         │ pack, print  │      │ suppression, │
   │ n shown  │    │ one source  │         │ and embed    │      │ bias, dates  │
   └──────────┘    └─────────────┘         └──────────────┘      └──────────────┘
        │                 │                         │                    │
        └─────────────────┴─────────────────────────┴────────────────────┘
                                          │
                                   every output carries
                            population · n · date · evidence grade
```

## 3.1 Look up

The same two-pole model as the student site, with the guardrails removed and the facets
exposed: institution type, US state, employment type, seniority band, entry cohort, degree
level. An advisor is a trained reader; they get the controls a student should not have to
understand.

Everything an advisor sees carries its own denominator, and suppression is reported in place —
the number of cells suppressed and the number of people in them, not a blank.

**The tail matters more here than on the student site, not less.** An advisor's hardest
conversations are with the student whose interest has no obvious route, and the answer they
currently give is improvised. Give them a rare-destination lookup: type any of the 13,933
nameable job titles, get who reached it, from where, with what, and how few. An advisor who can
say *eleven people in this dataset are children's book illustrators, and here is what they
studied* has something no alumni browser and no salary table can offer.

## 3.2 Brief me

One sentence, one number, one source, robust to being read aloud by someone trying to trap the
speaker. Generated, not written, so it can never drift from the data.

> Among the 22,427 graduates in this sample with a history bachelor's and a usable graduation
> anchor, 39.2% enrolled in a graduate or professional degree within five years. Source:
> NHA Humanities Workforce dataset, snapshot 19 February 2026, n = 22,427.

Every claim on the site has one of these, and the button that produces it is next to the chart
rather than on a separate page.

## 3.3 Take it away

Per-major and per-destination packs: the fan, the distinctive destinations, the ways in, the
credentials, the employers, the coverage box. Print-clean and embeddable, so a department can
quote it in recruitment material **with the caveats attached.** This is the mechanism that
turns departments from an audience into distribution, and it is the deliverable most likely to
outlive the grant.

## 3.4 Show me the method

Not an appendix. The first thing an advisor needs before they will put anything in front of a
student, and it contains one item that is currently on nobody's list and blocks all use:

**"Is my profile in this?"** — a written, correct, campus-counsel-approved answer. Without it
career services cannot deploy the tool at all. *Write, don't build.* It is on the critical
path and it is a paragraph.

Second item, nearly as urgent: **"why not just use LinkedIn's own alumni tool?"** Staff will
ask on day one. The answer exists — trajectory over a decade at role grain with education
attached, which no alumni browser offers — but nobody has written it down.

## 3.5 What the portal must not become

- Not an ROI instrument. A provost will hear a percentage and assume it is a percentage *of
  our graduates*, which this can never be. Concede the category out loud.
- Not a ranking of majors against each other.
- Not a place where a comparison to other majors appears without its caveats in full.
- Not something that takes more than one 45-minute staff meeting to teach. Single-adopter
  tools die when the champion leaves.

---

# Map 4 — The supply map: data in, words in, product out

Every panel in both products, traced to the dataset that feeds it and the person who writes
the words around it. **Nine finished datasets currently have no consumer at all.** The pipeline
has ten stages and the surface reads five columns; most of what follows is wiring, not
research.

## 4.1 Surface → source → status

| Surface | Input | Analysis | Status | Notes |
|---|---|---|---|---|
| The field | `education` ⋈ `steps` | `portal.analyses.destination_fan`, `diversity` | **Ready** | the best thing we have shipped |
| Forward fan | same | `destination_fan`, `fan_detail` | **Ready** | |
| Backward origins | `person_year_archetype` | corridor query, 144 cells | **Built, unwired** | §0.1 |
| The corridor | same + `role_backbone_edges` | corridor + 4.3M title edges | **Built, unwired** | largest unspent asset |
| "People like me" ladder | same, three-way conditioned | new query, one afternoon | **Needs a build, small** | §1.4 |
| **The far edge** — rare destinations | `steps.role_canonical` + modal `title_raw` | count + display join | **Needs a build, small** | §1.8; 13,933 titles clear n ≥ 10 |
| **Distinctiveness order** | `fan[].rr` | already computed | **Ready, unused** | the surprise generator; currently a toggle with no reason to press it |
| What this work involves | `career_description_cluster_proposals` | composite paraphrase | **Built, unwired** | 528,001 people; never verbatim |
| What they studied | `person_year_archetype` ⋈ `education_person` | provenance | **Built, unwired** | recompute on canonical cohort first |
| What they carried | `parsed/certifications` | new module | **Needs a build** | 545,414 people; untouched since parsing |
| The graduate step | `launchboard.grad_track` | Ready | **Ready** | strongest evidence-to-surface ratio on the site |
| Employers | `employer_field` | Ready pooled | **Ready** / blocked finer | dispersion is the finding |
| Geography | `steps.location_us_state` | single query | **Needs a build, small** | §0.5; most-wanted, cheapest |
| The decade distribution | `panel` + `trajectory_features` | linearity typology | **Needs a build, small** | 1,337,321 people already classified |
| Work context | `steps.employment_type` | new panel | **Needs a build, small** | the only 100%-covered axis |
| Institution type | `education_person.inst_*` | new facet | **Built, unwired** | 70.9%; first question an institutional reader asks |
| Rising and falling work | `temporal.json`, `temporal_occupation_nodes` | Ready | **Built, unwired** | era-sliced, 2005→2025 |
| Beyond the job | `enrichment.json` | Ready | **Built, unwired** | volunteering, publications, honors, languages |
| Portfolio work | `paths/_concurrency.parquet` | one query | **Needs a build, tiny** | 2,524,265 secondary steps; 23.4% of all steps |

## 4.2 Where NHA writes

This is the part that is usually left as "copy TBD" and then written badly at the end. Treat it
as a schema: every slot has an owner, a cadence, an evidence grade, and a length. Nothing on
either surface is unowned.

| # | Slot | Where | Grade | Cadence | Length |
|---|---|---|---|---|---|
| 1 | **The opening claim** | student site, frame 1 | Asserted | once, revisit yearly | 1 sentence |
| 2 | **The population statement** | both, above the fold | Measured, plain-language | on each data refresh | 2 sentences |
| 3 | **The eleven orientations** | front door 2 | Asserted, from the framework | once | 11 × 1 sentence |
| 4 | **Pathway descriptions** | inside each door | Asserted | as the lexicon lands | ~74 × 2 sentences |
| 5 | **Signature skills** | inside each door | **Asserted, badged** | once | 11 × a list |
| 6 | **"What this work involves"** | destination panel | Editorial over measured | as clusters land | 11 × 1 paragraph |
| 7 | **Fan and corridor captions** | every chart | Measured | generated, reviewed | 1 line each |
| 8 | **The three fallback sentences** | wherever the ladder fires | Measured | once, templated | 3 × 1 sentence |
| 9 | **Every empty state** | everywhere | Measured | once, templated | 1–2 sentences |
| 9a | **The pioneer line** | every rare destination | Asserted | once | 1 sentence, reused |
| 9b | **The grain-raising sentence** | wherever a rare cell fails | Measured | once, templated | 1 sentence |
| 10 | **The commit-before-reveal prompt and response** | frame 2–3 | Asserted | once | 2 short blocks |
| 11 | **Choice caveats** | frame 8 | Measured + asserted | once | 1 paragraph each |
| 12 | **"Is my profile in this?"** | portal, methods | Asserted, counsel-reviewed | on policy change | 1 paragraph |
| 13 | **"Why not LinkedIn's alumni tool?"** | portal, methods | Asserted | once | 1 paragraph |
| 14 | **What we cannot tell you** | both | Asserted | once | 6 bullets |
| 15 | **The snapshot date and what changed** | both, footer | Measured | every refresh | 1 line |
| 16 | **Advisor brief templates** | portal | Measured, generated | automatic | 1 sentence each |

**Two rules that make this maintainable.** Measured and asserted content never share a visual
treatment — an advocate has to be able to see at a glance which sentences are ours and which
are the data's. And the amber, asserted layer is the only layer a person edits: if updating a
number requires editing prose, the prose will go stale and the number will be wrong.

## 4.3 What blocks what

Three decisions, then six builds. The decisions are not engineering and they change numbers we
have already shown people.

**Decide:**

1. **The canonical population.** We currently have five different groups all called "the
   humanities cohort," spanning a 25× range. Recommendation: narrow humanities or humanistic
   social science, on a bachelor's degree. The panel behind our movement findings is currently
   only 37.7% narrow-humanities — six in ten are natural and social scientists — which shows
   through in the output as findings that are really artifacts.
2. **The time axis.** Career entry as primary, graduation as a labelled sensitivity check.
   Career entry gives 3,788 nameable employers; graduation gives 142.
3. **Two products or one.** Recommendation: two. Career services asked for it directly.

**Then build, in order:** the corridor query · the far edge, which is a count and a display
join · the "like me" ladder and its three fallback sentences · the linearity distribution ·
geography · certifications · the pathway lexicon.

**And write, on the critical path:** the privacy answer · the population statement · every
empty state. None of these require an engineer and all of them block deployment.

---

## What this document deliberately leaves out

Say these out loud in the handoff so nobody designs a slot for them: any salary or ROI figure;
any demographic breakdown; any individual person, profile, or quotation; any prediction or
recommendation engine; any single-answer quiz or assigned type; the internal fifteen-bucket
vocabulary, anywhere on screen; the unresolved industry bucket drawn as a sector; and
provost-facing framing, which belongs to the report.
