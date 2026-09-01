# Career archetypes — findings

Build of 2026-07-16. Pipeline: `run_role_features` → `run_assign` → `run_yearwise`
(+ `validate`). Design in `ARCHETYPES_PLAN.md` (repo root). This documents what
was built, the numbers, and the honest caveats. Three audit passes (red-team,
math/methodology, refactor) were run on the assignment feature and their findings
implemented (see §6).

## 1. What this produces

A **role/skillset state archetype** for every career step, and a graduation-anchored,
cohort-windowed yearwise panel + flow tensors for the humanities cohort — the
substrate for a Sankey/alluvial narrative. 15 substantive archetypes + an honest
`OTHER` residual (id 0):

1 Educators & Academics · 2 Creatives & Media Makers · 3 Writers, Editors & Content ·
4 Communications, PR & Marketing · 5 Sales & Business Development · 6 Managers &
Operations Leaders · 7 Business & Strategy Analysts / Consultants · 8 Finance &
Accounting · 9 Tech & Product · 10 Administrative & Coordination · 11 Legal, Policy &
Research · 12 Healthcare & Human Services · 13 Nonprofit, Public Service & Advocacy ·
14 Hospitality, Retail & Service · 15 Founders & Independent Practitioners.

### Outputs (`archetypes/results/`)
- `role_features.parquet` — 2,605,247 roles; per-role modal SOC (with **support**),
  industry L1, owner share, seniority, role text.
- `role_archetype.parquet` — the role→archetype crosswalk (also mirrored to
  `normalized/mappings/role_archetype.parquet`). Columns: `archetype_id/key/label,
  assign_method, embed_cosine, n_persons, n_steps`.
- `person_year_archetype.parquet` — **407,265 humanities persons**, 5.03M person-years
  (career-year 1–15), one row per person-year with `entry_cohort, career_year, grad_year,
  anchor_tier, in_window`.
- `occupancy.parquet` — stock: distinct persons per (entry_cohort, career_year, archetype) + share.
- `state_flows.parquet` — **primary Sankey tensor**: population year-over-year archetype
  flow (person at career_year t → t+1), incl. diagonal (stayers).
- `job_flows.parquet` — secondary: actual job-change transitions (event-based).
- `validation.json`, `unsupervised_crosscheck.json`, `_*_manifest.json`.

## 2. How a role gets its archetype (`archetype_spec.assign_role`)

Precedence, most-specific structured signal first:
0. **Generic self-employed** term with no functional trade in the text → Founders
   (a bare "owner"/"founder" aggregates unrelated businesses; its modal SOC is noise).
1. **SOC detailed code** (6-digit) via longest-prefix crosswalk. A code routing to a
   trades/uniformed major that is clearly a white-collar title (e.g. "Project Manager"
   miscoded 47-xxxx) is rescued by keyword.
2. **SOC major** (2-digit) default, refined by keyword only within a split major's
   allowed set (27 creatives/writers/comms; 13 analysts/finance; 11 managers/comms/…).
3. **Keyword** on role text (no SOC signal).
4. **Founders residual** (self-employed, no resolved trade).
5. **Embedding fallback** — nearest archetype descriptor cosine (≥0.45, margin ≥0.05),
   else OTHER.

**A SOC code is trusted only with support** ≥10 modal steps and ≥5% of the role's steps
— this stops a code resting on a handful of steps from mislabelling a huge role
(e.g. `owner`→Healthcare from 5 coded steps of thousands). Coverage of the role→archetype
crosswalk, role-occupancy weighted: ~69% SOC-driven, ~22% keyword, ~0.4% embed, OTHER
~10–12%.

## 3. Timeline & cohorts (ARCHETYPES_PLAN.md §3, §3a)

**The axis is career-ENTRY, not graduation — a deliberate, data-forced choice.** The plan
aimed for "years since graduation," but graduation year is only cleanly known for ~15% of
the cohort, and it **cannot be recovered from career onset**: measured on the 60,563 people
who have both, first-job year vs true bachelor-end-year lands in a *different* 5-year cohort
**60.5% of the time**, median gap −2 years (first jobs often predate the degree —
student/intern roles), and **no constant offset fixes it** (best offset still ~41% same-bin,
~27% within ±1yr). This reproduces edu_clean's own rejected-A3 finding. Binning 85% of people
by a proxy that misfires 60% of the time would fabricate the cohort axis.

So the primary timeline is **`career_year = calendar_year − entry_year`** = years since first
datable job (identical to `panel.career_age`, the repo-standard axis), and cohorts are
**career-entry cohorts** (5-year bins of first-job year). This is universal, clean, and — since
it marks when someone actually enters the workforce — arguably a better frame for a "possibility
space" story than graduation. The true A1/A2 **graduation anchor is carried as optional metadata**
(`grad_year`, `anchor_tier` — non-null for 62,442 people, A1 56,461 + A2 5,981) for anyone who
wants a clean graduation-anchored re-cut on that subset.

**Entry-cohort windows** (derived from the censoring horizon `2025 − latest_entry_in_bin`,
capped 15) so every member is fully observable across the window — verified: within the
2010–2014 window, persons-per-year falls only 82,049→78,045 across years 1–11 (~5% attrition,
i.e. real job-gaps, **not** censoring):

| entry cohort | window | in-window persons |
|---|---|---|
| ≤2004 | 1–15 | 157,081 |
| 2005–2009 | 1–15 | 77,950 |
| 2010–2014 | 1–11 | 84,100 |
| 2015–2019 | 1–6 | 78,537 |
| 2020+ | 1–5 | 9,579 |

Adopted because the distribution is right-skewed: a fixed 15-year window would keep only
251,932/407,872 people (−38%) and describe only the oldest entrants. Cohort windows use all
407,265 people **and** make entry-cohort a clean generational comparison axis.

## 4. Headline results

**In-window person-year distribution** (honest person-year weighting — not the
role-occupancy weighting in `_assign_manifest.json`, which ~4.7× double-counts people):
Managers 14.4% · OTHER 11.5% · Admin 10.6% · Creatives 8.0% · Sales 7.4% · Analysts 6.9%
· Educators 6.5% · Healthcare 6.2% · Comms 5.7% · Legal 5.3% · Tech 4.8% · Writers 3.6% ·
Founders 3.4% · Finance 2.5% · Hospitality 2.4% · Nonprofit 0.9%.

**Movement:** year-over-year, **86.4% stay** in their archetype, 13.6% switch. Admin is
the early-career **hub** — the largest off-diagonal flows run Admin<->OTHER and
Admin->Managers/Analysts/Healthcare. (The panel picks one primary role per person-year, so a
person doing two things at once shows only the dominant one — switching is a lower bound.)

**Generational signal (the payoff of the cohort design):** year-1 entry mix differs across
entry cohorts — 2015–2019 entrants are in Managers less (8.4% vs 10.9% for 2005–2009, a
seniority/age effect) and show Healthcare (8.1%) and Hospitality (8.0%) more prominently at
entry than the older cohort.

## 5. Validation (`validate.py`)

- **Within-archetype SOC-major purity** (steps-weighted), mean **0.65**. High for
  SOC-anchored buckets: Educators 0.94, Creatives 0.99, Writers 0.99, Managers 0.90,
  Sales 0.73, Tech 0.68, Admin 0.63. Lower — *by design* — for cross-major buckets:
  Healthcare (spans SOC 29/31/21) 0.53, Hospitality (35/37/39/41-2) 0.47, Nonprofit
  (industry-anchored, cross-function) 0.44.
- **SOC-major → archetype concentration:** clean majors map near-1:1 (43→0.92, 15→0.91,
  25→0.94, 29→0.91, 19/17→0.91); the intentionally-split majors are low (11→0.48,
  13→0.39, 27→0.47) — that is the split-refinement doing its job, not incoherence.
- **keyword-vs-SOC agreement 0.41** — moderate; expected, since keyword refinements
  deliberately override SOC-major defaults for split majors.
- **Unsupervised cross-check (headline "do the data back the anchors?"):** KMeans(k=15)
  on MiniLM embeddings of the top-15k roles vs rule labels → **adjusted Rand 0.16,
  NMI 0.26 — LOW.** Honest read: short 2–3-word role strings embed weakly and cluster on
  surface form, while the rules lean on structured SOC signal the text lacks; this is a
  *weak lower bound*, not a refutation. A fuller **fused-vector** validation (structured
  priors + text, per the plan's Approach B/C) would be the fair test and is the main
  deferred validation item.
- **OTHER (~11% of person-years)** is ~39% SOC-coded (out-of-scope majors: 33 protective,
  53 transport, 49 repair, 51 production, 47 construction, 55 military) and ~61% genuinely
  uncoded/generic tail (student, member, generic titles, gaps). It is **not** absorbing
  white-collar humanities roles.

## 6. Audit findings implemented (three parallel teams)

Red-team (correctness), math/methodology, refactor — all run on Phases 0–3. Key fixes:
- **Regex over-capture:** `market` was swallowing supermarket/capital-markets/farmers-market
  → anchored to marketing/marketer/market-research; nonprofit `development` was eating
  R&D/L&D/business/land development → replaced with unambiguous fundraising/advancement
  cues; `producer` (insurance/sales) and `research` (UX/clinical) narrowed.
- **Thin-SOC trust:** added the support gate (§2) — `owner`→Healthcare and similar thin-code
  mislabels eliminated.
- **SOC 11-2022** relabelled Sales Managers (was miscoded Comms); Managers-magnet reduced by
  routing function-qualified service managers (kitchen/store/shift) to Hospitality; customer
  service → Admin; personal banker → Finance.
- **Weighting honesty:** the assign manifest is now labelled `role_occupancy` (not persons);
  the credible person/cohort shares come from the panel person-years.
- **Window horizon:** cohort windows derived from the censoring horizon (fixes a 2020–2024
  over-reach); **join fan-out** in role_features removed by pre-collapsing industry/steps;
  `device="cuda"` auto-detects; misleading `assign_confidence` split into `assign_method` +
  nullable `embed_cosine`.

Tests: `python -m archetypes.archetype_tests` — 49/49 (incl. a regression per audit finding).

## 7. Known limitations / deferred

- **Not a graduation axis:** the timeline is career-entry (first job), not graduation — a
  data-forced reframe (§3). A true graduation-anchored view is possible only on the 62,442
  A1/A2-anchored people; graduation cohort is not recoverable for the other 85%.
- **Unsupervised agreement is low** (§5) — needs fused-vector validation to test fairly.
- **Managers** remains the largest bucket, partly a generic-title catch-all; the clear
  functional cases are routed out, but bare "manager" stays.
- **Nonprofit** is small and fragile (industry-anchored, cross-function) — an open question
  (per plan §11) whether it should be a node or an attribute.
- **Phase 5 (visualization)** is not built — this is the dataset + tensors only.
