# Precedent & inspiration set — interactive narrative + data-exploration portals

Curated 2026-07-14 for the Humanities Workforce redesign. 15 exemplars across five
categories, each with the one technique worth stealing; cross-cutting lessons at the end.
Link notes: several publishers (NYT, WaPo, Bloomberg, FT, FlowingData) block automated
fetchers — those were confirmed live via secondary sources.

## A. Canonical scrollytelling / guided data narrative

**1. The Fallen of World War II — Neil Halloran** — http://www.fallen.io/ww2/
Data-driven documentary; at key moments the film pauses and hands you the controls to
explore the data before resuming.
**Steal:** the pause-and-explore beat — a guided narrative that periodically opens a door
into the explorable portal, then resumes. The best existing answer to our tripartite
problem: put explicit "pause here and poke at this fan yourself" moments in walkthroughs.

**2. What's Really Warming the World? — Bloomberg Graphics (2015)** —
https://www.bloomberg.com/graphics/2015-whats-warming-the-world/
Scroll-driven elimination of rival explanations, curve by curve, until only one fits.
**Steal:** the elimination stepper as myth-busting rhetoric — walk the reader through each
rival explanation of the scary anecdote ("it's survivorship," "it's just grad school")
and show, chart by chart, why each fails.

**3. A Visual Introduction to Machine Learning — R2D3** —
http://www.r2d3.us/visual-intro-to-machine-learning-part-1/ (intermittent; archived)
Scrolling literally builds a decision tree as prose explains each split.
**Steal:** scroll-constructs-the-structure — grow the destination fan branch by branch as
the story advances, so the final explorable object is one the reader watched being
assembled and therefore trusts.

## B. "You drive the choices" narratives

**4. The Uber Game — Financial Times (2017)** — https://ig.ft.com/uber-game/
Choose-your-own-adventure news game built from dozens of real driver interviews; every
branch decision costs something. Prototyped in Ink (Inkle's narrative scripting language).
**Steal:** choices with felt trade-offs grounded in real material; and script branching
narratives in Ink or similar so writers iterate without engineering in the loop.

**5. You Draw It: Family Income vs College Chances — NYT Upshot (2015)** —
https://www.nytimes.com/interactive/2015/05/28/upshot/you-draw-it-how-family-income-affects-childrens-college-chances.html
You draw the relationship you believe exists before the reveal, then see other readers' guesses.
**Steal:** commit-before-reveal — have students draw what they think the humanities
outcome curve looks like first; the gap between their pen line and the data is the entire
advocacy argument, personalized. Showing peers' guesses normalizes the anxiety itself.

**6. OECD Better Life Index — OECD / Moritz Stefaner** — https://www.oecdbetterlifeindex.org/
Country flowers re-rank live as you weight the well-being dimensions you care about.
**Steal:** user-weighted rankings — let students weight salary vs meaning vs stability vs
flexibility and watch paths reorder. Converts "which major wins?" (myth-shaped) into
"what do you value?" (advocacy-shaped).

## C. Career / education-outcome explorers

**7. PSEO Explorer — U.S. Census Bureau (LEHD)** —
https://lehd.ces.census.gov/data/pseo_explorer.html
Graduate earnings/employment by institution, degree, field from linked administrative
microdata; Sankey flows into destination industries; explicit about coverage.
**Steal:** degree→destination Sankeys backed by linked microdata, and coverage candor —
wear the denominators openly in the methods layer.

**8. Data USA — Deloitte + Datawheel** — https://datausa.io/profile/soc/economists
Uniform, deeply-linked profile pages for every occupation/major/place; "Add Comparison"
on every chart.
**Steal:** the profile-page grammar with universal comparison — one page skeleton for
every major and destination so drill-down never disorients.

**9. Humanities Indicators — American Academy of Arts & Sciences** —
https://www.amacad.org/humanities-indicators
The statistical clearinghouse on the humanities workforce, explicitly framed against the
no-jobs myth; pairs the salary gap concession with satisfaction/well-being parity.
**Steal:** the two-axis honesty move — concede the pay gap while reframing what "outcome"
means; borrow its survey-sourcing register for methods.

**10. Jobs by College Major (ACS Sankey) — Ben Schmidt** — https://benschmidt.org/jobs/
Two-column Sankey majors→professions; click any node to isolate; color encodes
more/fewer-than-expected.
**Steal:** click-to-isolate (the fix for the Sankey hairball) + coloring by deviation from
expectation, which turns a flow chart into a myth-buster.

## D. Possibility-space / trajectory visualization

**11. A Day in the Life of Americans — Nathan Yau, FlowingData (2015)** —
https://flowingdata.com/2015/12/15/a-day-in-the-life-of-americans/
1,000 dots simulated from ATUS Markov transition matrices move through a day.
**Steal:** unit visualization of simulated individuals — a cohort of 1,000 humanities-grad
dots flowing through the first post-grad decade. Anxiety attaches to "what will happen to
*me*"; a swarm of individual trajectories answers that better than a stacked area. The
Markov-from-transition-probabilities method maps directly onto our transitions data.

**12. 512 Paths to the White House — NYT (Bostock & Carter, 2012)** —
https://archive.nytimes.com/www.nytimes.com/interactive/2012/11/02/us/politics/paths-to-the-white-house.html
The complete branching possibility space as a navigable tree; choices gray out sub-trees.
**Steal:** conditioning as pruning — when a student makes a choice, dim foreclosed
branches instead of redrawing; shows both consequence and how much possibility space
remains (the emotional payload for career-launch anxiety).

**13. The Unlikely Odds of Making It Big — The Pudding (2017)** —
https://pudding.cool/2017/01/making-it-big/
~7,000 bands tracked up (mostly not) the venue ladder; search any band's trajectory.
**Steal:** the honest base-rate with a search-yourself layer — the full distribution
including stagnation is the survivorship-bias antidote; proof the genre doesn't sugarcoat.

## E. Myth-busting / perception-vs-reality / explorable arguments

**14. Parable of the Polygons — Vi Hart & Nicky Case (2014)** — https://ncase.me/polygons/
Playable post on Schelling segregation: scripted micro-interaction → guided simulation →
open sandbox; the reader generates the counterintuitive result themselves.
**Steal:** the staged ramp (our walkthrough→portal ramp in miniature) and the emotional
architecture — never scold the misconception; let the reader discover the correction.

**15. Corona Simulator ("flatten the curve") — Washington Post (Harry Stevens, 2020)** —
https://www.washingtonpost.com/graphics/2020/world/corona-simulator/
Live simulations run in front of the reader; every reader's run differs, and it says so.
**Steal:** re-rollable randomness as an honesty device — "run it again" teaches
distribution-not-destiny, so uncertainty is texture rather than a footnote.

## Cross-cutting design lessons

1. **Narrative and portal are the same object at different throttle settings.** The
   walkthrough drives the same visualization the explorer exposes; control is handed over
   gradually (watch → pause-and-poke → sandbox), so trust earned in the story transfers
   to the tool.
2. **Elicit the misconception before correcting it.** Commit-before-reveal (draw the
   line, set the slider) converts myth-busting from lecture to self-discovery; showing
   peers' guesses normalizes the anxiety.
3. **Show individuals inside aggregates.** Every aggregate view should offer a "zoom to
   one plausible life"; every narrative persona should trace back into the aggregate.
4. **Treat uncertainty and unflattering data as features.** Full distributions including
   failures, visible coverage gaps, deviation-from-expected coloring, conceded trade-offs
   — one hidden denominator costs the skeptical reader an advocacy product most needs.
5. **Choices should prune, not repaint.** Keep foreclosed branches visible but dimmed.
6. **Standardize the drill-down grammar; separate authoring from engineering.** One page
   skeleton per entity; a narrative DSL (e.g. Ink) so NHA staff can write branches
   without engineering.
