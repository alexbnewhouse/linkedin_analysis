# Narrative framing plan — answering the 2026-08-12 stakeholder feedback

**Status: proposal. No code written against this yet.**

Source notes: [`docs/notes/2026-08-12-stakeholder-feedback.md`](docs/notes/2026-08-12-stakeholder-feedback.md)
(items are referenced below by their `N` IDs).
Source framework: [`docs/notes/nha-career-skill-archetypes-framework.md`](docs/notes/nha-career-skill-archetypes-framework.md).
Companion state-of-play: `PORTAL_NEXT_STEPS.md`, `archetypes/FINDINGS.md`, `RAW_DATA_AUDIT.md`.

> **Amended 2026-08-12** by
> [`docs/notes/2026-08-12-audience-needs-synthesis.md`](docs/notes/2026-08-12-audience-needs-synthesis.md)
> — a three-audience needs exercise (student / career services / advocate). It confirms
> §1.2's earnings recommendation and materially changes §3, §4.2, and the sequencing in §8.
> Headline: all three audiences independently rejected **archetype vocabulary as
> public-facing output** while endorsing it as internal machinery. Read that synthesis's §10
> before acting on §2–§8 here.
>
> **Amended again 2026-08-12** by
> [`docs/notes/2026-08-12-eight-arguments-audit.md`](docs/notes/2026-08-12-eight-arguments-audit.md)
> — an audit of the eight arguments colleagues want to make, with queries run against the
> committed parquets. Three findings override this document:
> 1. **`cohorts/panel.parquet` and `person_year_archetype.parquet` are stale** — they predate
>    the 2026-08-05 snapshot-date fix and spine rebuild. Rebuilding them is now the top of
>    the queue, ahead of §8 here. Every figure in `archetypes/FINDINGS.md` §3–4 is affected.
> 2. **Two coverage figures quoted in this document are wrong.** Industry L1 is ~53%
>    resolved, not ~100% — which weakens the "cheap headline" claim in §1.2.2. Seniority is
>    46.1% ordinal / 95.2% fused, not ~30%, but its missingness is correlated with the
>    outcome and differs between comparison groups.
> 3. **Three of the eight arguments are refuted or unsupportable**, two of them by our own
>    committed output. See that audit's §3–§4.

---

## 0. TL;DR

N8 is a **project-level** question — what is this project doing and what does it produce —
not a portal-design question. So there are two tiers here, and the second is contingent on
the first.

**Tier 0 — the gate (§1).** Write a project charter answering the three questions at
project altitude: the corpus's capability envelope, NHA's actual argument, and the
deliverable. Nothing below is safely rankable until the deliverable is named.

**Tier 1 — the responses (§2–§7),** currently written *assuming the deliverable is the
portal*, because that is today's default. Marked by how they survive a change of
deliverable:

| # | Proposal | Answers | Size | Survives? |
|---|---|---|---|---|
| 1 | **Archetype fact sheets** — one measured page per archetype, generated not written (§6) | N1b, N1, N6 | medium | **Yes — needed under every deliverable** |
| 2 | Adopt the director's **four-dimension model** (Archetype × Pathway × Sector × Work Context) as a *derived layer* over the existing 15 (§3) | N3, N6, N6b, N2a | large | **Yes — it is a data-model fix** |
| 3 | Build the **skills layer** — asserted (framework) + measured (recommendations, projects, certifications, courses) (§4) | N4, N2b | large | **Mostly** — the measured half is substrate |
| 4 | **Strip the numbers out of the atlas for review** (§2) | N1a | small | Yes, but only matters if we keep reviewing prototypes |
| 5 | Promote and rebuild **"choose your own path"** (§5) | N5, N2a, N7 | medium | **Only if the deliverable is interactive** |
| 6 | Split the surfaces **by audience** rather than by depth (§1.6) | N1, N7 | medium | **Only if the deliverable is interactive** |

The one thing to *stop*: building new surfaces of any kind before the charter exists.

---

## 1. The three questions, at project level (N8)

> "What can we do with the data? What do we want to argue? How do we want to show it? …
> This effort in the portal was designed specifically to answer #3, but I think we need to
> back up and trace the connections between all three."

Read at project altitude, this asks what the project *is* and what it *produces*. There is
a mechanism worth naming, because it has already operated twice at two different scales:

> **Capability has been driving both the argument and the deliverable.** Movement became
> the portal's theme because the flow tensors were the newest and most visually striking
> asset — nobody decided it was the thesis; it won by being buildable. One level up, the
> same thing happened to the project: we are building a portal because a mature pipeline
> made a portal possible, not because anyone established that a portal is what NHA needs to
> produce.

The evidence for the second claim is in the repo's own shape: ~13 root-level plan documents,
nine analysis modules, and **four finished datasets with no consumer at all** (enrichment,
certifications, institution metadata, descriptions — `PORTAL_NEXT_STEPS.md`). Capability has
accumulated well ahead of any stated deliverable. That is not wasted work — it is a genuine
asset — but it does mean the project has never had to say what it is for.

### 1.1 Q1 — What can we do with the data?

This has been answered *locally* many times (`RAW_DATA_AUDIT.md`, `METHODOLOGY.md`, every
module's `FINDINGS.md`) and never *globally*. The global answer has two halves, and we have
only ever written the first.

**The capability.** 2.0M people; 486k humanities cohort; 407k observable across career-years
1–15; 5.03M person-years; 10.8M career steps; role, employer, industry, seniority, education,
and credential attached. Its **comparative advantage over every alternative source** —
ACS/Census, National Student Clearinghouse, BLS, Lightcast — is longitudinal *trajectory at
role grain with education attached*, plus named employer identity, at this n. Nothing else
available to NHA can show the shape of a career over a decade.

**The envelope.** What this corpus structurally cannot do, no matter how much we build:

- **No wages, ever.** No earnings, no ROI, no "is this a good job."
- **No unemployment or non-employment.** Gaps are unobservable, not measurable.
- **No satisfaction, meaning, or wellbeing.**
- **No representativeness claim.** This is a convenience sample of people who maintain a
  public professional profile.
- **Systematically undersamples** people who left the professional track, took
  non-professional work, or stopped curating a profile.

That last pair is the one that matters most at project level and the one I do not think we
have ever stated plainly: **the corpus is biased in the direction of the story NHA wants to
tell.** People whose humanities degree led somewhere legible are overrepresented, by
construction. Our honesty machinery is excellent at the level of individual numbers —
suppression, coverage badges, equal-window discipline — and silent at the level of *what
population all of it describes*. A hostile reviewer will start there, and they should.

This is not a reason to stop. It is a reason to write the envelope down once, at project
level, and let every downstream claim inherit it.

### 1.2 Q2 — What do we want to argue?

Not portal copy. NHA's position, and specifically its position **relative to the argument
actually being made against the humanities**, which is about earnings and employability.

We cannot measure either. So there is an unavoidable strategic choice that has never been
made explicitly:

**(a) Contest the earnings frame with proxies.** Seniority, employer prestige, occupational
mix as stand-ins for pay. *I'd reject this.* It is methodologically dishonest given we have
no wages, it invites exactly the critique we are least equipped to survive, and it concedes
that earnings is the right measure of a degree.

**(b) Refuse the frame and argue on different ground** — breadth, portability, adaptability,
non-linearity. Everything we can actually support. The risk is talking past the critique:
answering a question nobody asked.

**(c) Pair our trajectory data with external earnings data** — ACS/Census by major,
Hamilton Project, Georgetown CEW — citing rather than computing. We supply the shape of
careers; they supply the level of pay. *This is probably the strongest option, and it has
never been on the table because it lives outside the pipeline.* It is also cheap: it is a
literature and citation task, not an engineering one.

The charter should pick one. Most of what the portal currently says is (b) by default.

**What we can argue, with evidence in hand** — these hold under any deliverable:

1. **Breadth.** The same degree reaches every kind of work; the largest single destination
   is 14.4% of person-years, so nothing dominates (`archetypes/FINDINGS.md` §4).
2. **Portability across sectors** — the framework's own thesis and the one colleagues
   responded to (N6b). *Evidence:* archetype × industry-L1 cross-tab, not yet computed,
   cheap (L1 is ~100% covered). My candidate for the single headline finding.
3. **Accumulation.** A decade adds responsibility. *Evidence:* seniority by career-year.
4. **Entry accessibility.** Which doors are open at year 1, and what it took.
5. **Adaptability.** What moving costs and returns — where movement belongs, subordinated
   to resilience (N7.4, N7.5) rather than standing as a theme (N2).

### 1.3 Q3 — What are we producing?

The question the project has never answered. These are materially different projects:

| Deliverable | Primary audience | Rigor bar | Maintenance | Citable? |
|---|---|---|---|---|
| Public interactive portal | students, advisors | medium-high | **high, forever** | poorly |
| Written report / white paper | advocates, press, deans | high | none after publication | yes |
| Dataset + methodology release | researchers | **very high** | versioned | yes |
| Advisor-facing tool | career services | medium | high | no |
| Departmental messaging toolkit | faculty, chairs | low-medium | low | no |
| Academic paper | scholarly field | **very high** | none | yes |

Observations worth putting in front of the team:

- **The portal is the most expensive option to maintain and the least citable.** It is also
  the current default, by inertia rather than decision.
- **A report is the cheapest path to advocacy impact** and the one that best fits an
  argument built on a handful of strong findings rather than an explorable space.
- **The static and interactive outputs are not exclusive** — the same substrate can produce
  a report *and* a toolkit *and* an eventual portal. But that only works if sequenced
  deliberately; it fails if the portal is built first and the report is scraped from it.
- N7's five feelings are **product goals**, and they only make sense once a product exists.
  Three of them ("confidence," "engagement," "empowerment") presuppose something a person
  interacts with. Two ("adaptability," "non-linearity") could be delivered by a report.

### 1.4 Proposal: a project charter

One document, at repo root, ~2 pages, written with the director. Not a plan — a decision
record.

1. **What this project is** — one paragraph.
2. **The capability envelope** (§1.1) — what the corpus can and cannot answer, including the
   population-bias statement.
3. **The argument** (§1.2) — the position, and the frame decision (a/b/c).
4. **The deliverable(s)** (§1.3) — what we produce, for whom, by when, and what we are
   explicitly *not* producing.
5. **What that makes the portal** — flagship, prototype, or internal instrument. All three
   are legitimate; they imply very different amounts of remaining work.
6. **Known open research questions** — what we'd need to answer that we can't yet.

This is a writing and decision task, not an engineering one, which matches the note's own
call for "additional research and qualitative thought."

### 1.5 What this demotes

My earlier proposal — an `ARGUMENT.md` claims ledger tying each claim to evidence, surface,
audience, and intended feeling — was pitched at the wrong level. It is a **question-#3
instrument**: useful for keeping a *chosen* deliverable honest, useless for deciding what
the deliverable is. It stays on the list, downstream of the charter, and it is worth keeping
for one reason: it runs in reverse. "Evidence with no claim" is how the four unwired
datasets get either surfaced or formally retired, and that reverse pass is valuable under
every deliverable.

### 1.6 One structural finding that survives regardless (N1, N7)

The notes ask us to separate research arguments from affective impact. That distinction has
a structural consequence worth recording now: **one surface is currently trying to be a
research instrument and a reassurance instrument at once.**

The honesty machinery is load-bearing for the skeptic and essential to credibility; to an
anxious sophomore it reads as hedging. That tension is the likeliest root cause of the
cohesion problem (N1) — and note that it is *also* an argument for splitting the
deliverable rather than the page. A report for advocates and a tool for students are two
audiences that a single site has been struggling to serve in one voice.

If we do stay with one interactive surface: same data, two register-tuned entrances —
student/advisee leading with possibility and action, advocate/advisor leading with method
and limitations. The existing three-door IA (Stories / Portal / Data & methods) is close,
but its doors are sorted by *depth*, not *audience*, which is exactly what "may not be
communicating the correct stuff at the top" (N1) describes.

---

> **Everything from here down (§2–§7) assumes the deliverable is an interactive portal**,
> because that is the current default. If §1.3 resolves differently, re-read these as a
> menu rather than a plan. The parts that survive a change of deliverable are marked in the
> §0 table; §3 (taxonomy), §4.2 (measured skills), and §6 (fact sheets) are substrate and
> survive regardless.

## 2. Fixing the review process (N1a)

The director gets distracted by the fake data. Two fixes, do both:

**2.1 Review mode (do this first — it's small).** A toggle in `prototype/atlas.html` that
replaces every fabricated figure with a shape or a `[count]` chip, leaving structure,
labels, and interaction intact. A reviewer then *cannot* argue with a number, because there
are none. Pair it with a one-screen preamble: "this review is about structure; every number
here is invented; the numbers arrive in the next build." The current small "Prototype,
placeholder data" ribbon is not doing this job.

**2.2 Reduce the fake surface, fast.** The atlas is less invented than it looks. Its
colophon already lists what would feed it, and most of that exists today:

| Atlas element | Real source | Status |
|---|---|---|
| Mark sizes / occupancy | `archetypes/results/occupancy.parquet` | **built, unwired** |
| Crossings | `state_flows.parquet`, `job_flows.parquet` | **built, unwired** |
| Education provenance | `person_year_archetype` ⋈ `education_person` | **already measured & wired** |
| Employer landmarks | `career_steps` ⋈ `role_archetype` | computable, not built |
| What the work involves | `career_steps.description` (50.8%) | computable, not built |
| Credential ladder | `parsed/certifications` | computable, not built |

Wiring order by ratio of credibility gained to effort: occupancy → crossings → employers →
certifications → descriptions. After the first two, the only invented things left are the
six composite journeys and the radial placement — both of which are *editorial by design*
and can be labelled as such without embarrassment.

---

## 3. The taxonomy (N3, N6, N6b, N2a)

This is the big one, and the director's framework is more useful to us than a naming
suggestion: **it diagnoses our clusters.**

### 3.1 Why our clusters "stretch too broadly"

The framework separates four dimensions. Our 15 archetypes **mix three of them into one
axis**:

| Our archetype | What it actually is |
|---|---|
| Nonprofit, Public Service & Advocacy | a **sector** |
| Hospitality, Retail & Service | a **sector** |
| Founders & Independent Practitioners | a **work context** |
| Managers & Operations Leaders | mostly a **work context** (level), presented as a function |
| Administrative & Coordination | partly a level |

That is not a stylistic complaint — it predicts the exact failure we measured. The three
lowest-purity buckets in `archetypes/FINDINGS.md` §5 are Nonprofit (0.44), Hospitality
(0.47), and Healthcare (0.53), and the first two are precisely the sector-anchored ones.
Meanwhile **Managers (14.4%) + OTHER (11.5%) + Admin (10.6%) = 36.5% of all person-years**
sit in buckets that tell a student almost nothing about the *work*. `FINDINGS.md` §7 already
flags both problems in its own words ("Managers remains… partly a generic-title catch-all";
"Nonprofit is small and fragile"). The framework explains *why*: they are category errors,
not tuning problems.

### 3.2 Proposal: adopt the four-dimension model as a derived layer

Give every person-year four fields instead of one:

```
primary_archetype   (9)    secondary_archetype (9, nullable)
career_pathway      (~70)  sector              (10)
work_context        (5)
```

All four are reachable from data we already have:

| Dimension | Source | Coverage today |
|---|---|---|
| Sector (10) | `industry/results/step_industry.parquet` L1 (26 → 10 map) | ~100% |
| Work context (5) | `employment_type` (100%) for Founder/Freelancer + `seniority_ordinal`/`seniority_score` for IC/Manager/Executive | high |
| Primary archetype (9) | crosswalk from the existing 15 + existing SOC/keyword rules | ~89% (100% − OTHER) |
| Career pathway (~70) | **new**: the framework's ~600 representative role titles as a seed lexicon matched against `role_canonical` | to be measured |

The career-pathway lexicon is the cheapest high-value build on this list. The framework
hands us ~600 curated titles already grouped into ~70 durable pathways; matching them
against a 2.6M-role vocabulary (`role_features.parquet`) is string + embedding work we have
done before. Pathways are also the direct answer to N6: **9 legible macro nodes on top,
~70 specific pathways underneath.** "Creatives" stops stretching because underneath it are
Writing & Editorial, Content & Digital Media, Design & Creative, Film/Audio Production.

**Crucially, do this as a derived layer, not a rebuild.** Keep `archetype_id` (15) as an
internal field; ship the 9 as the public vocabulary. Nothing validated gets thrown away, and
we can compare the two taxonomies directly — which is itself a validation exercise we owe
ourselves, given that the framework is normative and AI-assisted while our 15 are
descriptive and data-fitted.

### 3.3 Draft crosswalk, ours → theirs

| Framework archetype | From our 15 |
|---|---|
| Communicators & Creators | creatives + writers + comms |
| Researchers & Educators | educators + the *research* half of legal |
| Analysts & Strategists | analysts |
| Advocates & Advisors | the *legal/policy* half of legal + advising & compliance roles now in admin |
| Helpers & Service Professionals | healthcare + customer-success roles now in admin + guest-experience half of hospitality |
| Connectors & Relationship Builders | sales + the *fundraising* half of nonprofit |
| Leaders & Organizers | managers + admin + the *operations* half of hospitality |
| Builders & Technologists | tech |
| Financial & Resource Stewards | finance |
| *(dissolved)* | founders → **work context**; nonprofit → **sector**; hospitality → split (see §3.4) |

Three of these fix known defects outright:

- **Fundraising & Development finally has a principled home** (Connectors), so "Nonprofit"
  can stop being a fragile industry-anchored node and become the sector it always was.
  Resolves the open question in `ARCHETYPES_PLAN.md` §11.
- **Founders dissolves into work context**, which is the correct fix for the documented
  "bare owner" problem — a person keeps their functional archetype *and* is marked
  independent, instead of being filed under an employment form.
- **Admin/coordination becomes a pathway inside Leaders & Organizers**, which is both more
  accurate and narratively much better: the 10.6% sitting in "Administrative &
  Coordination" are reframed as being on the recognized entry pathway into organizational
  leadership, rather than parked in a residual bucket. That is a real finding we can check
  (do coordinators actually flow to program/project/ops management?) — and if it holds it is
  one of the strongest things we could tell a nervous graduate.

### 3.4 Where the framework doesn't fit — decide, don't paper over

**Frontline service work has no home.** Food service, retail floor, warehouse, personal
service. The framework's nearest slot (Helpers → Hospitality & Guest Experience) is written
for guest-experience *management*, not line roles. In our panel this is 2.4% of person-years
and concentrated at career-years 1–3.

Options: (a) a 10th archetype; (b) an honest "Service & Frontline Work" node outside the
nine; (c) fold into Helpers and lose the distinction. **I'd take (b).** Quietly dissolving
the least flattering measured category into a nicer-sounding one would violate the honesty
rules the whole project rests on, and early service work is a *true and normal* part of the
first three years. Hiding it also costs us the resilience argument (N7.4): you cannot show
that people move up and out of frontline work if frontline work isn't on the map.

**Also to settle:**

- **OTHER (11.5%)** stays, and needs re-auditing under the new scheme. §5 of `FINDINGS.md`
  establishes it is not absorbing white-collar humanities roles; that check must be re-run.
- **Secondary archetype.** The framework explicitly allows one for hybrid roles, and it is
  the single most direct mechanical expression of N2a — a person who is 60/40 is *shown* as
  60/40 rather than being told what they are. We already compute embedding cosines in
  `assign.py`, so emitting a runner-up with a margin is a modest change. Worth doing partly
  *because* it de-essentializes the taxonomy.
- **Validation debt.** Any new assignment needs the same treatment the 15 got: purity,
  coherence, tail share, unsupervised cross-check, face validity. And the framework's ~600
  titles are curated prescriptively — they need an audit against real corpus vocabulary
  before they become a crosswalk. Expect real gaps; the corpus contains titles no
  career-services taxonomy anticipates.

### 3.5 Design consequence: the archetype is a door (N2a)

If we adopt this, the UI has to follow, or we'll have fixed the model and kept the framing:

- Never "you are a Communicator." Instead: "this kind of work is entered from…"
- Each archetype page **leads with ways in** — entry roles, entry credentials, entry
  employers, what people studied — rather than with its share of the population.
- **Movement is demoted from a layout default to one lens among several.** The atlas field's
  default becomes "what this work is and how you get into it."
- The first-person orientations ("I turn ideas into messages…") are a *self-selection
  prompt*, not a personality result.

---

## 4. Skills (N4, N2b)

The most-cited gap, and the framework hands us half of it for free. Ship it in three layers,
badged differently — the badge distinction is the whole point:

**4.1 Asserted skills (amber, NHA-authored, available immediately).** The framework's
signature-skill lists, attached to each archetype, phrased as the note asks: *what your
coursework builds → what this work asks for*. They are written in coursework language
already ("close reading," "rhetorical analysis," "source evaluation," "archival research").
Zero data risk, immediate, and the highest affective payoff for the career-services audience
(N7.3).

**4.2 Measured skills language (green).** I probed the parsed tables today for this, and it
is better stocked than I expected. Row counts and distinct people, over the full ~2.0M
person universe (**humanities-cohort coverage not yet measured — do that before quoting
any of these**):

| Table | Rows | People | Why it matters |
|---|---|---|---|
| `parsed/certifications` | 1,673,732 | 545,414 | the credential ladder — what people actually add |
| `parsed/recommendations` | 526,829 | 331,983 | **other people describing your skills in natural language** |
| `parsed/courses` | 664,834 | 102,167 | **actual course titles** — the only direct coursework↔career link in the corpus |
| `parsed/projects` | 365,253 | 85,065 | first-person "I did X" statements |
| `parsed/languages` | 606,206 | 325,625 | already used by `enrichment/` |

`recommendations` is the surprise and probably the most valuable: third-party skill
attestation in plain English ("analytical and detail oriented," "exceptional
problem-solving"). It is a better skills signal than self-authored job descriptions because
it is neither résumé-formatted nor self-serving. `courses` is thin (~5% of the universe) —
too thin for a headline number, potentially rich as a vocabulary layer.

Privacy rules carry over unchanged and one tightens: recommendations name both the subject
and the recommender, so **aggregate or paraphrase only, never verbatim, no exceptions.**

**4.3 Skill → evidence → action (the N2b triad).** For each archetype:

```
the skill            (coursework language, amber — from the framework)
     ↓
where it shows up    (measured, green — recommendations / descriptions / role vocabulary)
     ↓
what to do about it  (curated, amber — and partly measured already)
```

The third leg is not speculative: `portal/choices.py` already computes outcomes for
internships, double majors, grad school, service years, military service, and
self-employment on the windowed year-10 cohort. Certifications were already slated as the
seventh choice card (`PORTAL_NEXT_STEPS.md` §5). So "link skills language to actions" can
end on a list of actions whose *outcomes we have measured*, with the causal caveat that
module already ships. That closes the loop the note asks for using a built asset.

---

## 5. "Choose your own path" (N5)

The one thing colleagues liked. Invest in it, and note that it delivers three of the five
feelings on the N7 list (confidence, engagement, empowerment).

- **Move it up.** It currently sits near the bottom of the portal, which is why it reads as
  a bonus. Under the audience split (§1.6) it becomes the *student entrance*.
- **Enter through self-description, not major.** "What do you like doing?" — and the
  framework's nine first-person orientations are a ready-made picker, written for exactly
  this. Choosing a major is a fact about your past; choosing an orientation is a statement
  about what you want, which is the better hook.
- **Commit before reveal.** `PORTAL_INSPIRATION.md` §5, catalogued and never spent: have the
  user say what they expect before showing them what happened. It is the single most
  effective device for the expectation-inversion findings we already have.
- **Return a set of doors, not a verdict.** Multiple archetypes with real evidence behind
  each, explicitly reinforcing "a way in, not an identity" (N2a). A single-answer quiz would
  actively undercut the framing we just spent §3 fixing.
- **End on actions** — the third leg of §4.3.

---

## 6. Archetype fact sheets (N1b, N1)

A one-page measured brief per archetype, generated from the pipeline, no invented content:

- occupancy: share of person-years, and share at year 1 vs year 10
- top real roles by person-support
- top real employers (`career_steps` ⋈ `role_archetype`)
- **sector spread** (the portability claim, §1.2.2)
- work-context mix (IC / manager / executive / founder / freelancer)
- education provenance: what arrivals studied, how far, from where — *already measured*
- in-flows and out-flows: where people arrive from and go to
- certifications most commonly held

This is the cheapest fix for several notes at once. It gives the director something concrete
and data-true to react to (N1b), it forces copy to derive from one measured source instead
of two independent voices (N1), and it exposes which buckets are incoherent before we
redesign them (N6). It should be generated, not written, so it can never drift from the data.

**It is also the one build I would start before the charter.** Fact sheets are an input to
answering Q1 and Q2 — you cannot decide what to argue until you can see what each archetype
actually looks like in the data — and they are equally useful whether the deliverable ends
up being a portal, a report, or an advisor tool. Everything else in §2–§5 presumes an
answer to Q3.

---

## 7. Making the affective goals testable (N7)

Five feelings are listed. As written they can't be checked. Proposal: give each one a
surface, a moment, and a check. Note the dependency, though: **these are product goals, and
three of the five presuppose something a user interacts with** (§1.3). If the deliverable
turns out to be a report, this table needs rewriting, not just re-targeting.

| Feeling | Delivered by | Check |
|---|---|---|
| Confidence in finding *your* success | "choose your own path," entry-accessibility claim | Does a first-gen sophomore leave more confident than they arrived? |
| Engagement with paths like mine | orientation picker, archetype pages | Do users open more than one archetype? |
| Empowerment for career services | skills layer, fact sheets, methods page | Can an advisor cite one number from memory afterwards? |
| Long-term adaptability | accumulation + adaptability claims | Can a user state what a decade adds? |
| Careers are non-linear | movement, correctly subordinated | Do users accept lateral/backward moves as normal, not as failure? |

And, since these notes are ad-hoc reactions from colleagues, the note's own call for
"additional research and qualitative thought" deserves a real instrument: **5–8 think-aloud
sessions** — 2 students, 2 advisors, 2 faculty, 2 skeptics — on three fixed tasks. That is a
week of work and it would settle several arguments we are currently having from intuition.

---

## 8. Sequencing

**Tier 0 — the gate.**
1. **The charter** (§1.4), written with the director. Everything else waits on Q3.
2. **Archetype fact sheets** (§6) — the exception, because they are an *input* to the
   charter (you can't decide what to argue before seeing what each archetype looks like)
   and they are deliverable-agnostic.
3. **Atlas review mode** (§2.1) — small, and unblocks the next review whatever we decide.

**Tier 1 — substrate work, safe under any deliverable.** These are data-model fixes, not
presentation:
4. Sector + work-context derivation (§3.2) — cheap, ~100% coverage, and it enables the
   portability cross-tab that is my candidate for the headline finding (§1.2.2).
5. Career-pathway lexicon from the framework's ~600 titles (§3.2).
6. Humanities-cohort coverage measurement for the skills tables (§4.2).
7. Nine-archetype crosswalk + validation (§3.3–3.4).

**Tier 2 — presentation, and only once Q3 is answered.** Each of these is wasted work if
the deliverable turns out not to be an interactive site:
8. Asserted skills layer (§4.1) — cheap under any deliverable, but its *form* depends on Q3.
9. "Choose your own path" rebuilt as the student entrance (§5).
10. Audience split (§1.6).
11. Wiring the atlas to real occupancy and flows (§2.2).

**Independently, and now:** the redesign is still uncommitted (`PORTAL_NEXT_STEPS.md` §1 —
`share_template.html` +2,978 lines, `portal_data.json` +30,813, plus untracked modules).
Nothing above should start on top of an uncommitted tree.

---

## 9. Open questions for the team

**Project level (the charter — these gate everything else):**

1. **What are we producing?** (§1.3) No recommendation — this is NHA's to decide. But the
   portal is currently the default by inertia, and it is the most expensive to maintain and
   the least citable of the options.
2. **Do we contest the earnings frame, refuse it, or pair with external earnings data?**
   (§1.2) Recommend **(c) pair and cite** — it is the strongest position available and costs
   a literature review, not a build.
3. **Do we publish the population-bias statement** — that the corpus over-represents people
   whose degree led somewhere legible? (§1.1) Recommend yes, prominently. It is true, a
   reviewer will find it anyway, and stating it first is worth more than it costs.
4. **Is the portal the flagship, a prototype, or an internal instrument?** (§1.4.5) The
   answer changes how much of §2–§5 is worth doing at all.

**Below the charter:**

5. **Do we adopt the nine?** Recommend yes, as a derived layer over the 15 (§3.2).
6. **Where does frontline service work go?** Recommend a named node outside the nine (§3.4).
7. **Is movement demoted to one lens among several?** Recommend yes — evidence for
   adaptability rather than a theme in itself (§1.2.5).
8. **Secondary archetypes: ship or defer?** Recommend ship — it is the mechanical expression
   of "a way in, not an identity" (§3.4).
9. **Do we commit to a qualitative research round** before the next build (§7)? Depends
   entirely on Q3.
10. **Do we split surfaces by audience** instead of by depth? (§1.6) Only meaningful if the
    deliverable is interactive.
