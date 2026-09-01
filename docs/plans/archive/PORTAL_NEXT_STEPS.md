# `portal/` — state of play and next steps

**Date:** 2026-07-27. Companion to `RAW_DATA_AUDIT.md`. Reviewed: the `portal/` package,
`share_template.html`, `portal_data.json`, `_manifest.json`, `FINDINGS.md`, and the
plan docs that name portal work as outstanding.

## Where it actually stands

The package is in good shape and does what its plans said it would. Generated build
(`share_template.html` + `run_share_build.py` → `share/Humanities-Workforce-portal.html`),
every displayed figure computed, green/amber badge discipline, `MIN_SUPPORT = 10` as a
single knob read by every consumer and test, byte-reproducible runs, 43 checks, ~98s full
rebuild with the substrate cache. The 07-13/07-15 redesign landed the tripartite IA
(Overview | Stories & narratives | Portal | Data & methods), six computed myth cards,
`analyses.diversity`, `portal/choices.py`, and snapshot drill-downs.

**Two things are true at once:** the surface is mature, and it is fed by a narrow slice
of the pipeline. `portal/*.py` contains no reference to `archetypes`, `enrichment`,
`institution_meta`, or `education_person`; `share_template.html` mentions `archetype`
zero times. Four finished datasets have no surface at all.

**Immediate housekeeping (do this first):** the entire redesign is **uncommitted** —
`share_template.html` +2,978 lines, `portal_data.json` +30,813, `analyses.py`,
`choices.py` (untracked), `common.py`, `launchboard.py`, `portal_tests.py`,
`run_portal_data.py`, plus the regenerated share build. A mid-session kill during this
same body of work already cost a `renderStories` render bug once. Commit and tag it
before starting anything below.

---

## The one decision that gates the biggest step

The portal and the archetype layer **disagree about time**, deliberately and for good
reasons on both sides:

| | Portal | Archetypes |
|---|---|---|
| Anchor | Graduation (A1/A2) | Career entry (first datable job) |
| Population | 18–22% of persons survive anchoring | All 407k (grad anchor kept as optional metadata) |
| Window | y10 fan, equal observation windows | Entry-cohort windows to each cohort's censoring horizon |

`archetypes/FINDINGS.md` §3 shows why the archetype layer cannot use the graduation axis
for everyone: first-job year lands in a different 5-year bin 60.5% of the time. But
`person_year_archetype.parquet` carries `grad_year` + `anchor_tier` for **62,442**
persons (A1 56,461 + A2 5,981), so a graduation-anchored re-cut *is* available on that
subset.

**Recommendation: do both, and label them.** Re-cut the archetype tensors on the A1/A2
subset for anything that sits beside existing portal numbers (so the y1/y5/y10 scrubber
stays on one axis), and keep the full career-entry cut as its own view with its own axis
label — it is the larger, cleaner dataset and, as the plan argues, arguably the better
frame for a possibility-space story. What must not happen is one page mixing the two
axes without saying so.

---

## Ranked next steps

**1. Commit the redesign.** See above.

**2. Archetype layer → portal (ARCHETYPES_PLAN.md Phase 5, "not built").**
The single largest gap: a finished 407k-person panel, occupancy tensor, and two flow
tensors with zero surface. It delivers three things the current portal cannot:
nameable employers (Tier-1 §1 of the audit), three-stage pathways that close the
documented named-pathways limitation (§2), and a state-flow Sankey/alluvial of the first
decade. Prerequisites: the axis decision above; re-run `run_yearwise` on the corrected
552k cohort (flagged ⟳ in `EDU_PIPELINE_UPGRADE_PLAN.md`); add `humanities_field_group`
as a facet so the layer can be cut per major rather than pooled-only.

**3. Wire the enrichment layer.** `enrichment/results/enrichment.json` is finished
analysis with no consumer — volunteer causes, publications, honors, org leadership,
multilingualism, per sub-field against a non-humanities baseline. It is the portal's best
answer to "outcome means more than a job title", and it is a JSON read plus a panel.

**4. Institution-type facet** (☐ in `EDU_PIPELINE_UPGRADE_PLAN.md`). 70.9% coverage of
IPEDS control / Carnegie / region / metro on humanities persons. Highest-value moderator
available and the first question an institutional audience asks. Suppression needs a
fresh look here: institution type × major × destination is a narrow cell.

**5. Certifications as the seventh choice card.** Fits `portal/choices.py` exactly as
built (person-level flag on the membership spine, participation share, subset fan), and
it is the most *actionable* thing in the corpus for a student — PMP, Series 7, CompTIA,
UX, notary, real estate, RN.

**6. Geography.** Either a facet on the fan or its own view. `transitions.parquet`
already carries `from_location`→`to_location`; `career_steps` carries parsed state/city
on 51.6% of steps. The "what if I stay near home" question is unanswered by anything the
portal currently shows.

**7. Descriptions → a qualitative layer.** The largest build and the biggest register
shift: 5.2M free-text work descriptions that can say what the work *is*. Start narrow —
one archetype, extract the verb/object pairs, ship a "what this work actually involves"
panel — before contemplating anything embedding-scale. Privacy rule up front: composite
or paraphrased, never verbatim from an identifiable profile.

**8. Front-end techniques not yet spent.** `PORTAL_INSPIRATION.md` catalogued 15
exemplars; the redesign used the honesty and pruning lessons but not the interaction
ones. Unspent and well-matched: commit-before-reveal (§5 — have the student draw the
outcome curve they expect before the reveal), the unit-dot cohort (§11 — 1,000 dots
walking the first decade, which answers "what happens to *me*" far better than a stacked
share), and pause-and-explore beats inside the walkthrough (§1).

**9. Infrastructure, when the audience grows.** The built page is ~1.03MB with
`portal_data.json` (875KB) inlined — fine for a share build, at the edge for mobile. The
documented direction (versioned aggregate-only releases behind a read API, per
`share/System-Map.html`) is the right answer, but only when there is a second consumer.
`portal_tests.py` is still a manual run; a pre-commit or CI hook is cheap insurance for a
pipeline whose main historical failure mode was a stale test masking everything after it.

---

## Editorial note

The redesign moved the portal from comparison to comprehension, and the remaining gap is
now register rather than architecture. Everything on the page is a *distribution* — fans,
curves, shares, meters. Nothing on the page is a *person*. The audit's Tier-1 assets
(employers, three-stage paths, descriptions) are precisely the material for the missing
register, and `prototype/` is a placeholder-data sketch of what that register looks like
before any of it is wired to the pipeline.
