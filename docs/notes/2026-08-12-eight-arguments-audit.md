# The eight arguments, audited against the data — 2026-08-12

Four analysts audited the eight arguments colleagues want to make, two each, paired so they
shared data inputs. Unlike the audience-needs exercise, these had full repo access, and all
four ran their own queries against the committed parquets.

## Verification status — read this before quoting any number

Numbers below fall into three classes, and they are **not** equally trustworthy:

- **[COMMITTED]** — read from pipeline outputs that have tests and bias checks
  (`portal/results/portal_data.json`, `portal/FINDINGS.md`, `archetypes/FINDINGS.md`).
- **[AD-HOC]** — computed by an analyst during this audit via throwaway DuckDB queries.
  No tests, no bias check, no review. One analyst flagged this explicitly about its own
  headline. **Treat as directional pending reproduction in the pipeline.**
- **[VERIFIED]** — I checked it myself this session.

The single most consequential finding (§2) is [VERIFIED]. Most of the rest is [AD-HOC], and
several [AD-HOC] results contradict things I have been asserting — see §5.

---

## 1. Scorecard

| # | Argument | Verdict |
|---|---|---|
| A1 | Possibility space, not a pipeline | **PARTLY** — the comparative form is refuted by our own committed data |
| A2 | Careers unfold over time | **PARTLY** — unfalsifiable as stated; one sharpened version is strong |
| A3 | Reach unexpected destinations | **SUPPORTABLE** for History/Comm/English/Phil&Rel — **NOT** for Arts |
| A4 | Transferable skills enable moves | **NOT SUPPORTABLE** — no skills measurement exists in the corpus |
| A5 | Chart a course, seize opportunities | **NOT SUPPORTABLE AS STATED** — rhetoric, not a claim; restatable |
| A6 | Paths converge in leadership | **NOT SUPPORTABLE** — refuted by our own data |
| A7 | Coursework skills translate | **NOT SUPPORTABLE** — 5.6% coverage, and the coursework is mostly not humanities |
| A8 | Concrete career pathways | **PARTLY** — supportable at named employer × occupation, on one axis only |

Two of eight survive largely intact. Three are refuted or unsupportable. Three need
restatement. That is a more useful result than eight green lights.

---

## 2. Blocking issue: two core panels are stale [VERIFIED]

`paths/common.py:37-43` documents a snapshot-date correction — the anchor was wrong by a
year (2025-02-19 → 2026-02-19). Under the old anchor **182,634 steps were dropped as
`bad_future_start`, 167,368 of them a person's most recent step.**

`paths/steps.parquet` was rebuilt **2026-08-05**. But:

| file | mtime | status |
|---|---|---|
| `paths/steps.parquet` | 2026-08-05 12:35 | rebuilt, correct |
| `cohorts/panel.parquet` | 2026-07-21 10:44 | **predates the fix** |
| `archetypes/results/person_year_archetype.parquet` | 2026-07-22 09:07 | **predates the fix** |

**Consequence:** every figure in `archetypes/FINDINGS.md` §3–4 — the entry-cohort window
table, the 86.4% year-over-year stay rate, and the 8.4%-vs-10.9% generational headline — was
computed on a panel that systematically truncates recent cohorts' most recent year. So were
most of the [AD-HOC] numbers in this audit.

**Rebuild both panels before any of these arguments ship, and re-run the affected findings.**
This is now the top of the queue, ahead of everything in `NARRATIVE_FRAMING_PLAN.md` §8.

---

## 3. Three arguments our own data refutes

This is the hard part, and it is worth more than the parts that worked.

### A1 — the comparative breadth claim is false in committed output

`portal/results/portal_data.json → diversity.effective_destinations` (inverse Simpson over
year-10 occupation groups) **[COMMITTED]**:

| English | History | Phil&Rel | Comm&Media | Arts | **Baseline** |
|---|---|---|---|---|---|
| 7.01 | 8.04 | 7.86 | 6.42 | 4.18 | **8.25** |

**All five humanities cohorts are at or below the all-graduate baseline.** Humanities
destinations are *equal or narrower*, not wider. If we publish "the humanities open a wider
possibility space," a reviewer can cite our own committed JSON against us.

What survives: no destination *dominates* — top-bucket share runs 12.5–15.2% against a
baseline of 14.3%. Nothing is a pipeline for anyone, including business majors. That is a
rebuttal to a stereotype, not an argument for the humanities, and it belongs in the
myth-card layer rather than standing as a plank.

### A6 — humanities are below baseline in management at every career age

**[AD-HOC]**, measured on SOC major group 11:

| career age | humanities | baseline | gap |
|---|---|---|---|
| 1 | 15.0% | 22.0% | −7.0 |
| 10 | 20.7% | 32.0% | −11.3 |
| 20 | 25.6% | 39.6% | −13.9 |

The gap **widens** with career age. This is consistent with committed output
(`portal/FINDINGS.md`: Management RR 0.51–1.0 across all five majors).

Worse, the "convergence" half depends entirely on which vocabulary we use. Among humanities
in management at year 10: on the public SOC axis, **70.3% were already in management at
year 1** (effective origin diversity 1.98). On the internal archetype axis, only **36.5%**
were (diversity 5.81). The analyst's summary is exact:

> "A6b is true in the vocabulary you cannot use and false in the one you can... A reviewer
> who sees inverse-Simpson 1.98 on SOC and 5.81 on your invented taxonomy will say you chose
> the taxonomy that gave the answer. That charge is correct and unanswerable."

Also: **28% of humanities management person-years at year 1, rising to 40% by year 15, carry
SOC 11-1011 "Chief Executives"** — a documented lexicon artifact collapsing
founder/owner/"Chief"/"Head". A large share of measured "leadership" is self-employment
wearing a management code.

**Do not lead with A6 in any venue.** It invites "then why are they below baseline?" and we
have no answer.

### A7 — the coursework data cannot carry it

`parsed/courses` covers **13,854 of 246,482 humanities people (5.6%)**. It has no date, no
institution, and no foreign key to an education row — a course cannot be attached to a
degree, a year, or a school. After anchoring and windowing, **1,329 people** remain observed
at career-year 10. Any cut by field or course type falls below `MIN_SUPPORT`.

And the content audit found the opposite problem from the one we feared. It is mostly real
college coursework (28.9% of subtitles are genuine course codes; MOOC contamination is
small) — but the most-listed courses among humanities majors are **Project Management (179),
Public Speaking (178), Typography (167), Marketing (150), Statistics (148), Financial
Accounting (148)**. Humanities-flavoured titles: 10,968 rows. Business/STEM: 14,345.

> Humanities majors who list coursework mostly list their non-humanities coursework. A7
> would be evidenced by the courses that least support it.

Selection on *who lists* is severe and outcome-correlated: listers have 31% more career
steps, and at career-year 5 are 16.0% in creative/media work vs 8.5% for non-listers.
Course-listing is a marker of self-branding intensity and creative-field norms.

---

## 4. A4 is unfalsifiable, not merely unproven

There is **no skills field in this corpus.** LinkedIn's skills/endorsements section was not
captured. Every "skill" is inferred from a title, a self-written description, a
certification, or asserted by the director's framework.

> "A title-inferred skill is definitionally collinear with the move it is supposed to
> explain — you would be regressing job titles on job titles."

We observe moves. We do not observe skills, and we cannot observe skills *causing* moves. A
hostile reviewer needs one line: *"You never measured a skill."*

The honest replacement, proposed by the analyst and worth adopting close to verbatim:

> "The kind of work a humanities graduate does is not fixed by their major, and it is not
> fixed by their first job. Among humanities graduates in this sample, 52% of job changes
> moved into a different kind of work and 32% moved into a different industry; over the
> first ten years 57% held more than one kind of work. Some kinds of work travel across
> nearly every sector — management, administration, business analysis, technology — and some
> stay put; teaching, healthcare, food service and law are each concentrated in a single
> industry. **We measure the moves. We do not measure skills, and we cannot say what caused
> any move.**"

That last sentence is the credibility purchase.

---

## 5. Two corrections to the data inventory I have been circulating

**Industry L1 is not ~100% covered.** I have repeated that figure in the plan and in every
briefing this session. Two analysts independently found that **47% of rows are
`method='unresolved'` / `XOT`** — real resolution is ~53%, and at the year-10 endpoint
specifically it is 52–63% unresolved. This materially weakens the "portability" headline I
called cheap in `NARRATIVE_FRAMING_PLAN.md` §1.2.2. It is still the best-covered axis we
have; it is not a free one.

**Seniority coverage is better than I said and worse than it looks.** Not ~30% ordinal —
**46.1% ordinal, 95.2% fused**. But the missingness is correlated with the outcome *and*
differs between the groups being compared: SOC 11 (Management) is 86.1% coded, SOC 25
(Education) **7.9%**; employees 47.7%, self-employed 10.7%; and the baseline is coded ~5
points more often than humanities at year 10. The analyst demonstrated the consequence:

> A known-denominator run showed humanities **above** baseline (80.9% vs 80.6%); the
> all-denominator run showed them **below** (37.0% vs 40.8%). That reversal is the whole
> argument against reporting on the coded subset.

**Also:** the cross-cohort generational comparison is weaker than the audience synthesis
implied. The measured decline is monotone, near-parallel, and common-mode across humanities
*and* baseline — the signature of differential backfill, not a generational effect, matching
`cohorts/README.md` Phase 5 ("cannot cleanly confirm or refute"). The only defensible object
is the humanities−baseline **gap**, which narrows from −5.2 points (1990) to −2.9 (2010).
Publish the difference-in-differences; state that the level decline is not interpretable.

---

## 6. The anchor decision, finally quantified

`PORTAL_NEXT_STEPS.md` calls the graduation-vs-career-entry axis "the one decision that gates
the biggest step." Here is the price, same population, same n≥10 bar, first five career
years **[AD-HOC]**:

| unit | graduation-anchored (23,666 persons) | career-entry (234,416 persons) |
|---|---|---|
| named employers | 142 | **3,788** |
| employer × occupation group | 41 | **1,716** |
| employer × US state | 15 | **1,513** |
| employer × city | 3 | **983** |

**A 25–300× difference produced entirely by the anchor choice, not by the suppression bar.**
A8 — the most-wanted argument per the audience research — lives or dies on this. The
graduation anchor drops ~90% of humanities people.

The cost of choosing career-entry: we can only say "in the first five years of working life,"
never "five years after graduating." A provost will ask why. That is a smaller price than
having nothing concrete to show.

---

## 7. The strongest arguments nobody proposed

Three analysts independently landed near the same territory, and none of it is on the list
of eight.

**Employment type — the best-covered claim available [AD-HOC].** 100% coverage, no SOC code,
no seniority word, no graduation anchor, no model layer:

| career band | humanities self-emp/owner | baseline |
|---|---|---|
| y1–3 | 7.9% | 4.4% |
| y4–7 | 9.3% | 5.2% |
| y8–12 | 10.7% | 6.2% |
| y13–20 | 12.0% | 7.3% |

Humanities run **1.7–1.8× baseline at every career stage**, and the ratio holds while both
rise. It is immune to every objection that sinks A6, and it answers the anxiety students
actually voice — *"will I be freelancing forever?"* No: 88% are not, and the independent
share grows with age rather than collapsing.

**Occupation moves, sector stays [AD-HOC].** Humanities change occupation group between year
1 and year 10 well above baseline (History 54.5% vs 42.1%) while industry change sits *at*
baseline (37.6% vs 33.8%). Humanities graduates carry the same sector into different work.
Sharper and more defensible than "possibility space."

**But portability is conditional, and it fails where the framework needs it most.** The
director's framework asserts that a skill archetype "travels across sectors." Measured, that
holds for some work and not others — Management spans an effective 11.4 of 24 industries,
Office/Admin 10.1, Business/Financial 8.2 — while **Education is 1.28 (88.4% in a single
industry)**, Food Service 1.29, Healthcare 1.60, Legal 1.78, Arts/Design/Media 2.08. The
portability thesis is weakest for the most stereotypically humanities destinations.

**Relatedly: Arts is the exception throughout.** Lowest destination diversity (4.18 vs 8.25),
highest top-bucket concentration (24.2%), and the only cohort whose year-1→year-10 change
rate (37.7%) is *below* baseline (42.1%). Arts is the most pipeline-like group in the set.
Any argument written for "the humanities" as a bloc will be wrong about Arts.

---

## 8. The uncomfortable finding

On the career-entry axis, the honest list of largest named employers of humanities graduates
in their first five years reads: **Self-employed (11,418), US Army (2,806), US Navy, Target,
Air Force, Walmart, Starbucks**, then Wells Fargo, AT&T, Amazon, Apple, Disney, IBM,
NBCUniversal, U.S. Dept. of State. Legible cells do exist — U.S. House of Representatives ·
DC (133), Condé Nast · NY (114), NYC Public Schools · NY (119), NYU · NY (147).

> "Concrete, checkable, and not the list the advocacy argument wants... the moment we reorder
> it to lead with Condé Nast, we have stopped being descriptive."

Both non-student audiences in the earlier exercise asked us to publish findings that hurt.
This is the first real test of that commitment.

---

## 9. How concrete we can responsibly get

Measured, humanities, first five career years, n≥10, career-entry axis **[AD-HOC]**:

| level | cells clearing 10 | verdict |
|---|---|---|
| industry L1 | 16 of 21 | safe, uninformative |
| SOC major group | 23 of 23 | safe, still abstract |
| job title | 4,353 | **safe and legible** |
| named employer | 3,788 | **safe; publish with dispersion** |
| **employer × occupation group** | **1,716** | **the recommended unit** |
| employer × state | 1,513 | publishable, half-sample caveat |
| employer × city | 983 | thin; top-20 metros only |

Ship three numbers with any named list: the cell n, the suppressed-cell count, and the
singleton share (**92.6–95.5% of employers hired exactly one graduate** [COMMITTED]). The
dispersion is not a caveat — it is the finding, and it is what stops "here are the employers"
from reading as "here is the funnel."

Multi-step named routes at role grain are **not** available: the pipeline's own documented
ceiling is 8 persons (`portal/pathways.py`), which is why `PATH_MIN_STAGES` was dropped to 2.

---

## 10. Language discipline

Two mechanical rules from the A5/A8 analyst, worth adopting as project standard:

1. **Every sentence names its population before its number.** Never "42% of English majors";
   always "Among English graduates in this sample who maintain professional profiles, 42%…"
2. **Past tense, count-first, no second person.** "N people did X" is describable; "you can
   do X" is a prescription the data cannot license.

| never | instead |
|---|---|
| "The path from coordinator to program manager" | "1,021 people in this sample held a policy/research role at year 1 and a management role at year 10." |
| "Top employers for English majors" | "Employers where 10 or more graduates in this sample worked in their first five years. 93% of employers hired exactly one — this is the dense corner of a very sparse field." |
| "A common route into management" | "Where people who started here were ten years later, most common answer first. This describes what happened to them, not what will happen to you." |
| "This pathway leads to…" | "People who reached [destination] most often came from [origins]" — backwards from the destination, the only direction this data supports. |
| *(empty screen)* "Only 2 employers meet our bar" | "Fewer than 10 graduates worked at any single employer in this field, so we cannot name one. 2,682 employers appear once each." |

And the standing sentence for the advocacy venue: *"We can tell you where these graduates
worked. We cannot tell you what they were paid, and we do not claim this is every graduate."*

---

## 11. What I'd do next

1. **Rebuild `cohorts/panel.parquet` and `person_year_archetype.parquet`** (§2). Blocking.
   Re-run everything in `archetypes/FINDINGS.md` §3–4 afterward.
2. **Decide the anchor** (§6). It gates the most-wanted argument. Recommend career-entry,
   with the graduation subset as a labelled sensitivity check.
3. **Reproduce the [AD-HOC] findings in the pipeline** with tests and bias checks —
   specifically employment type, occupation-vs-industry change, and the leadership gap.
   Nothing in §3–§7 should be spoken aloud until this is done.
4. **Take A4, A6, A7 off the list**, and replace A1 with its survivable form. Bring
   employment type and "occupation moves, sector stays" onto it.
5. **Correct the coverage figures** I have been circulating (§5) wherever they appear.
