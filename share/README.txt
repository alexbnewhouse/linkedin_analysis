Humanities Workforce — shareable portal build
==============================================

Current build: Humanities-Workforce-portal.html  (zip: same, compressed)

Open the .html in any modern browser (double-click; no server or internet
connection required — the file is fully self-contained).

What it is
----------
A working build of the NHA Humanities Workforce toolset, computed from the
LinkedIn career-trajectory analysis (~2M profiles):

  * Stories        - guided, branching walks through a major's possibility
                     space, with NHA staff gloss at every step
  * Portal         - the explorable data engine (major picker, destination
                     fan, long view, sectors, success pillars)
  * Data & methods - dataset facts, boundaries, cohort funnel, validation,
                     and the project's honesty commitments

How to read the numbers
-----------------------
Every figure is badged:

  * PIPELINE DATA (green) - computed by the portal pipeline
                            (portal/run_portal_data) from the committed spine
  * EDITORIAL (amber)     - NHA-staff narrative: the named story routes and
                            glosses. No counted 3-4-step route clears the
                            n>=40 publication bar at today's ~21.5%
                            occupation coverage, so routes are illustrative
                            until coverage grows.

How to regenerate
-----------------
  uv run python -m portal.run_portal_data   # recompute the numbers
  uv run python -m portal.run_share_build   # re-inject them into this page

The page is built by token injection from portal/results/portal_data.json —
its numbers cannot drift from the pipeline output.

deprecated/ holds the earlier "NHA Pathways" design prototype (illustrative
numbers; superseded by this build on 2026-07-08).

Working build for collaborators. Not for public distribution.
