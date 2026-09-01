# What do we actually need from the LinkedIn data? — three-audience synthesis

**Method and its limits, first.** Three siloed AI personas were run independently against an
identical, neutral inventory of what the corpus contains and structurally cannot contain.
None could see the others' reports, and all three were blocked from reading this repo's
planning documents so they could not re-derive our existing conclusions. The personas:

1. **The wary undergraduate** — 19, second-year, drawn to English, loan-carrying, anxious
   parents, allergic to the "you can do anything" pitch.
2. **The career services associate director** — eleven years in, large public flagship,
   ~35k undergraduates, chronically under-resourced, burned by prior career-tech tools.
3. **The humanities advocacy director** — national organization, argues in front of
   legislators, provosts, trustees, and hostile journalists.

> **This is a structured brainstorm, not user research.** Simulated personas cannot tell us
> what real students want; they surface hypotheses and blind spots. Treating this as
> evidence would be exactly the overreach the advocate persona warns against. It does not
> replace the think-aloud round proposed in `NARRATIVE_FRAMING_PLAN.md` §7 — if anything it
> sharpens what to ask in it.

---

## 1. The unanimous verdict: cut the archetypes as a public-facing object

All three, independently, named the same thing as their "one thing to cut." This is the
strongest signal in the exercise.

- **Undergrad:** "Telling me my likely career is a 'shape,' or that I'd end up in 'Creatives
  & Media Makers,' is a horoscope with a sample size. Keep the archetypes as internal
  plumbing for measuring movement — but don't hand me the label."
- **Career services:** "No student has ever wanted to know their trajectory shape, and a
  network graph of career movement is the exact artifact that makes a dean's eyes glaze.
  Use the taxonomy to compute; do not make anyone learn it."
- **Advocate:** "It is a taxonomy you invented, and constructed classifications are the
  first thing a hostile reviewer attacks — 'you drew the boxes to get the answer.' Report in
  standard industry and occupation categories people already recognize."

**What this changes.** Not the archetype program — its *position*. All three explicitly
endorsed keeping it as internal machinery for measuring movement; what they reject is
archetype vocabulary as the thing a user reads. That is a sharper version of what the plan
already half-proposed (internal 15 / public 9): the finding here is that **no
archetype-shaped vocabulary should be public at all**, in any count.

Consequence for `NARRATIVE_FRAMING_PLAN.md` §3: the four-dimension adoption survives as a
**data-model fix** and loses its rationale as a naming fix. Public-facing output should
speak in industry, occupation, job title, and employer — categories people already own. Note
the advocate's specific warning: an invented taxonomy is a *liability* in an adversarial
venue, not a neutral choice.

The atlas prototype is the surface most affected. It is built almost entirely on archetype
vocabulary as the reading experience.

## 2. The three most-wanted assets — and two of them are unwired

| Asset | Coverage | Who wants it | Status |
|---|---|---|---|
| **Named employers** | 100% | all three (undergrad #1, CS #3, advocate #1) | **built, unwired** |
| **Employment type** (employee / self-employed / owner) | 100% | CS + advocate both named it *underrated* | **built, unwired** |
| **Certifications** | 545k people | CS ("the only thing a student can act on before finals"), advocate (rebuts obsolescence), undergrad (#4) | **built, unwired** |

**Employment type is the surprise.** Two personas independently flagged it as the most
underrated thing in the inventory, for the same reason: self-employment and business
ownership across fifteen years, against a matched baseline, is *complete* rather than
sparse, directly answers "will I be freelancing forever," and is legible to the most hostile
audience. The advocate: "Nobody else has it in this form." The career services memo notes
their own first-destination survey destroys this signal by coding everyone as "employed."

**Certifications are the actionability asset.** Every other finding in the corpus is
descriptive; this is the only one that converts into a next step, and next steps are what a
30-minute appointment trades in.

## 3. Geography is the binding constraint, and it is nobody's current priority

Two of three named geographic coverage as their **single biggest disappointment**, in nearly
identical language:

- **Career services:** "'Employers in my state' is therefore a half-sample question, and my
  students' most concrete need is the geographic one."
- **Advocate:** "State-level geography on 51.6% is not enough for my most important venue.
  Flag this hard rather than papering over it."

The advocate's point is structural: the programs actually being closed are at regional
comprehensives and directional publics, and every national number is contaminated by
flagships. "That's Michigan, we're not Michigan" is the first thing a skeptical trustee
says. Institution-type breakout (Carnegie/control, 70.9%) is workable; state-level
geography (51.6%) is the weak joint.

Geography sits at #6 in `PORTAL_NEXT_STEPS.md` and appears nowhere in the plan's tiers. On
this evidence it should be near the top — at minimum, a coverage investigation to find out
whether 51.6% can be improved before we design around it.

## 4. Correction: recommendations are not the skills asset I claimed

`NARRATIVE_FRAMING_PLAN.md` §4.2 called colleague-written recommendations "the surprise and
probably the most valuable" skills signal. Two of three personas reject them outright:

- **Undergrad:** "Recommendations written by colleagues are worse; that's flattery data."
  And on self-written job descriptions: "that's self-branding, and summarizing it back to me
  is a hall of mirrors."
- **Career services:** "Leave the colleague-written recommendations alone entirely — the
  yield is low and the creep factor, in a room where a student is already asking whether
  their own profile is in your data, is high."

That is a straightforward correction to §4.2 and I'd take it. **Demote recommendations.**

The reconciliation on descriptions is more interesting, because the same asset the undergrad
distrusts, career services calls "fully met, and underused" — but for a different purpose.
Not as a source of *claims about people*, as a **vocabulary and translation layer**: five
million examples of how people who did this degree describe their own work, which is exactly
the bridge between "I wrote a thesis on Milton" and a search box. Use descriptions to supply
language, never to make claims. That distinction resolves the conflict cleanly.

## 5. The earnings question: three-way agreement on option (c)

All three independently converged on the plan's §1.2 recommendation, which is the strongest
confirmation in the exercise.

- **Advocate:** proxies are "a computed earnings estimate wearing a costume... their
  economists will take it apart line by line and they will be right, and the collateral
  damage takes the trajectory findings with it." Pair-and-cite, recompute nothing, and
  accept permanently ceding the headline number. Blending our destinations with external
  wage tables must be "a firing-level rule."
- **Career services** adds a distinction we did not have: **survivable student-facing,
  near-disqualifying administration-facing.** For students, position it as a *routing layer
  to* wage data rather than a wage source. For a provost, concede the ROI category entirely
  — "this is not an ROI instrument and should never be sold as one. It is a destination and
  durability instrument."
- **Undergrad:** "I don't need a dollar figure — I need a rank and a floor... Say 'we can
  tell you where you'd work, not what you'd be paid' and I'll respect the rest more."

Notable: the undergrad considers **survivorship bias the more serious problem**, not missing
salary. "Missing salary is a known absence. Survivorship makes everything you *do* show look
better than the truth."

## 6. Selection bias: one specific, checkable, and dangerous claim

The advocate sharpened our general bias statement into something testable:

> "K-12 teaching is one of the largest humanities destinations, and teachers are among the
> least likely to maintain active LinkedIn profiles. Our best story is probably
> *undercounted*, and our error runs in the flattering direction on everything else."

Two concrete research tasks fall out, neither of which we have:

1. **Differential attrition test.** If humanities profiles go dormant at different rates than
   the baseline population, the "common-mode bias cancels in comparison" defense weakens. We
   need to know by how much.
2. **Verified-graduation-year sensitivity check.** Re-run headline results on the ~62,442
   people with true A1/A2 anchors and show they hold. We have this subset already
   (`archetypes/FINDINGS.md` §3); we have never used it this way.

And one governing rule, which I would adopt verbatim as a project constraint:

> **Every claim comparative, drawn from within the same sample, never a population level.**
> "Among people who maintain public professional profiles, humanities graduates at career
> year 10 versus business graduates at career year 10" is defensible. "62% of humanities
> majors are in management" ends the project's usefulness.

## 7. Where they diverge — and what it says about the deliverable (Q3)

This is the part that bears on the charter.

| | Undergrad | Career services | Advocate |
|---|---|---|---|
| **Form wanted** | Something on a phone, on the bus | Two things: a <60-second student view *and* a citable versioned artifact | A one-pager, one chart, ≤4 pages |
| **Interactive?** | Yes, briefly | Yes for students, no for chairs | **"Nobody opens a link in a hearing"** |
| **Depth** | Specific and personal | Fast, then exportable | Comparative, defensible |

**The advocate would not use a portal at all.** Explicitly: interactive dashboards, network
diagrams, anything over four pages, and invented terminology all get ignored. What survives
a hearing is "one sentence containing one number and one source, robust to being read aloud
by someone trying to trap me," plus one black-and-white chart.

**Career services independently arrived at the audience-split conclusion** — and went
further than the plan's §1.6, which proposed two entrances on one site. They want two
*artifacts*: "This is a genuinely different product with different failure conditions, and
conflating them is how these things die." Student-facing tolerates "here's what people like
you did"; provost-facing does not, because a provost will hear a percentage and assume it is
a percentage *of our graduates*, which this can never be.

**Implication for the charter (§1.3):** the deliverable is probably not one thing, and the
portal is the right answer for at most one of three audiences. A written report with a
handful of defensible comparative findings serves the advocate and the provost conversation;
the portal serves students and advisors, and only if it clears §8's operational bar below.

## 8. Failure modes we had not considered

The career services memo contributed most of these, and they are the kind of thing that only
comes from someone who has watched tools die.

- **Suppression can actively harm a student.** "If a student asks about Classics and gets an
  empty screen because of the minimum-ten rule, they conclude nobody with their degree gets
  a job, and I have actively harmed them." Our `MIN_SUPPORT = 10` rule is methodologically
  correct and has a user-facing failure mode we have never designed for. An empty cell must
  say *why* it is empty.
- **"Is my profile in this?"** Without a crisp, pre-written, correct answer — for the
  student and for campus counsel — career services "cannot put it in front of students at
  all." We have no such document.
- **Redundancy with LinkedIn's own Alumni tool.** Staff will ask why not just use that.
  There must be a one-sentence answer.
- **Staleness without a visible date is fatal; staleness with an honest date is survivable.**
- **The champion leaves.** Single-adopter tools die within eighteen months. If it takes more
  than one 45-minute staff meeting to teach, only one person will ever use it.
- **One bad moment in front of a dean** retires the tool permanently from the rooms where it
  mattered most.

## 9. Both non-student audiences want us to publish findings that hurt

- **Undergrad:** "Show me the bad outcome honestly and I'll trust the good one... If nothing
  in the findings is bad news, it isn't findings."
- **Advocate:** on the cross-cohort decline question — "I need to know the answer before
  anyone else does, including if the answer is bad for us." And among their conditions for
  putting their organization's name on it: "the team publishes findings that hurt us if it
  finds them."

This is the same instinct from opposite ends: falsifiability is what buys credibility. It
argues for the cross-cohort generational comparison as a **priority finding**, not a
nice-to-have — and for committing to publish it before we know which way it comes out.

---

## 10. What I'd change in the plan

| Change | From | To |
|---|---|---|
| Archetype vocabulary | public taxonomy, 9 names | **internal only**; publish in industry/occupation/title |
| Named employers | §2.2 wiring, mid-list | **top of substrate tier** — most-wanted, 100% covered |
| Employment type | not in the plan | **new headline candidate**; 100% covered, twice flagged underrated |
| Certifications | §4.3 third leg | **promoted** — the only actionable asset |
| Geography | absent | **coverage investigation now**; binding constraint for 2 of 3 |
| Recommendations as skills | "probably the most valuable" | **demoted** — rejected 2 of 3 |
| Descriptions | claim source | **vocabulary/translation layer only** |
| Cross-cohort comparison | not prioritized | **priority finding**, publish regardless of result |
| Suppression UX | honesty feature | **also a harm vector** — empty cells must explain themselves |
| Privacy Q&A | absent | **prerequisite** to any student-facing use |
| Deliverable | one portal | **probably a report + a tool**, not one artifact |

## 11. Open questions this raises for the charter

1. If all three audiences reject the archetype vocabulary publicly, **what is the atlas
   prototype for?** It is the surface most exposed by this finding.
2. Can geographic coverage be improved beyond 51.6%, or do we design around it? This should
   be answered before, not after, we choose a deliverable.
3. Do we commit now to publishing the cross-cohort result regardless of direction?
4. Who writes the privacy answer, and does it clear counsel?
