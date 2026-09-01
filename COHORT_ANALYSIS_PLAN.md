# Cohort analysis plan — research-grounded

> **Status: ALL PHASES BUILT** in `cohorts/` (see `cohorts/README.md`). Phase 0
> panel (1.996M profiles, 1.65M valid cohorts, 40.2M annual rows) + tests; Phase 1
> equal-age profiles; Phase 2 scarring (−0.004 scar fading ~4.5yr, hedged); Phase 3
> survival; Phase 4 typologies (cohort differences ~vanish at equal observation);
> Phase 5 generational (job-hopping gap = documentation artifact). Headline: the
> robust findings are null/artifact results — selection & backfill dominate raw
> gradients, exactly as the literature warns; the scarring coefficient is the only
> positive (and explicitly hedged) signal.

Goal: analyze how **career outcomes evolve for groups that share a starting
point** — entry-year, graduation-year, occupation-entry, or employer-join cohorts
— and separate, as far as the data honestly allows, the effects of **career age
(experience), calendar period, and cohort**. This consumes the spine
(`paths/`), the typed transitions, the fused `seniority_score`, and the
occupation/Job-Zone axes already built; it is the *longitudinal* complement to
the cross-sectional transition network.

Everything is measured on our data and tied to existing artifacts. The headline
caveat — **observational LinkedIn data is left-truncated and survivorship-biased**
— shapes the entire design and is stated up front, not buried.

---

## 1. What we can define as a cohort (measured)

| cohort axis | definition in our data | coverage | notes |
|---|---|---|---|
| **entry-year** (primary) | `min(year(start_dt))` over a profile's datable primary steps (`paths/steps.parquet`) | ~65k profiles/yr across **2000–2018**, tailing off after 2019 (right-censoring) | the workhorse cohort; well-populated |
| **graduation-year** | education `end_year` (`normalized/education.parquet`) | sparse (~21% have an end_year; `CAREER_PATHS_PLAN` §6) | enables the recession-scarring design (best instrument) but on a reduced sample |
| **occupation-entry** | first SOC the person held | ~22% (SOC-coding ceiling) | cohort = "people who started as a Software Developer in year Y" |
| **employer-join** | first `company_canonical_id` + its start year | ~70% on a `company_id` | "joined Google in 2015" cohorts |
| **generational / birth** | **proxied** (graduation_year − ~22, or entry_year − ~22) | derived, imprecise | no birth date exists; label as proxy, never as truth |

Career age (experience time) for any step = `year(start_dt) − entry_year`. This is
the **Age** axis of APC; entry_year is the **Cohort**; calendar year is the
**Period**.

---

## 2. Research synthesis — best practices & the core identification trap

### 2.1 The Age–Period–Cohort (APC) identification problem
`career_age = period − entry_year` is a deterministic identity, so age, period and
cohort effects **cannot all be separated** from levels alone without an external
constraint — the century-old APC identification problem ([Fosse & Winship 2019,
*JRSS-A* practical guide](https://academic.oup.com/jrsssa/article/182/2/715/7070179);
[Fosse & Winship bounding methods](https://cwinship.scholars.harvard.edu/age-period-cohort)).
**Implication for us:** do *not* report a three-way APC decomposition as if
identified. Use one of the principled escapes below.

### 2.2 The escape we should lead with — entry-conditions / "scarring" design
The cleanest, most-cited career-cohort design uses an **exogenous cohort
characteristic** — the unemployment rate *at labor-market entry* — and estimates
its effect on later outcomes, controlling for current period and career age. This
breaks the APC identity because the entry-condition is not a linear function of
age/period. Graduating in a recession causes large initial losses that **fade
over ~8–10 years**, with effects on **job mobility and employer quality**, not
just pay ([Oreopoulos, von Wachter & Heisz 2012, *AEJ: Applied*](https://oreopoulos.faculty.economics.utoronto.ca/wp-content/uploads/2020/05/oreopoulos-et-al-the-short-and-long-term-career-effects-of-graduating-in-a-recession-aej-applied-2012.pdf);
[SIEPR brief](https://siepr.stanford.edu/publications/policy-brief/recession-graduates-long-lasting-effects-unlucky-draw)).
We have entry year per profile and can join an external **US annual unemployment
rate** (BLS) as the cohort instrument — a flagship analysis that is *identified*.

### 2.3 Event-history / survival analysis for "time-to-X"
Time-to-first-promotion, time-to-management, time-to-exit, time-to-self-employment
are **time-to-event** outcomes. Use **Kaplan–Meier** by cohort and **Cox
proportional-hazards** with cohort + entry-conditions + covariates
([Cox PH for career progression](https://methods.sagepub.com/book/introducing-survival-and-event-history-analysis/n5.xml)).
Survival models **natively handle right-censoring** (ongoing roles at the
snapshot) — the correct tool for our open intervals. They also force us to
confront **left-truncation** explicitly (§4).

### 2.4 Sequence analysis for whole-trajectory cohort typologies
Social **sequence analysis** (optimal-matching distances → trajectory clusters)
characterizes and compares trajectory *shapes* across cohorts — the standard tool
for occupational careers ([TraMineR](https://traminer.unige.ch/);
[Aisenbrey & Fasang; OM best-practice in career research](https://www.sciencedirect.com/science/article/abs/pii/S0001879115000408)).
We already produce trajectory archetypes (`transition_network/sequences.py`,
Phase 5) — stratifying their distribution by cohort is the immediate, scalable
version (full OM is O(n²) on 1.3M sequences — subsample or use the existing
feature-based clustering).

### 2.5 What the generational-mobility literature warns
Apparent generational "job-hopping" differences **mostly reflect economic
conditions and career stage, not cohort attitudes** — younger workers' shorter
tenure largely tracks being early-career, and the switching wage premium itself
moves with the cycle ([NIRS/debunking](https://www.nirsonline.org/articles/new-research-debunks-job-hopping-myth-about-millennials-and-gen-z/);
[Revelio Labs](https://www.reveliolabs.com/news/macro/job-hopping-is-a-feature-not-a-bug-for-gen-zers/)).
**Lesson:** always compare cohorts **at the same career age**, never raw, or
age/period will masquerade as a cohort effect.

---

## 3. The dominant threat in *our* data — selection (read before any result)

LinkedIn is a **present-day snapshot of survivors**, which creates biases that are
*more severe for cohort analysis than for anything we have built so far*:

1. **Left-truncation / immortal-time / survivorship.** An older cohort appears
   only if its members are *still observable on LinkedIn in 2025* — i.e. still
   professionally active, successful, and online. People whose careers ended
   (retired, died, left white-collar work, never adopted LinkedIn) are absent.
   So a "1995 entry cohort" is a heavily selected set of long-survivors, and will
   look spuriously senior/successful. Left-truncation is a known source of serious
   bias and must be modeled, not ignored ([left-truncation selection bias](https://pmc.ncbi.nlm.nih.gov/articles/PMC6151356/);
   [occupational cohort left-truncation](https://pmc.ncbi.nlm.nih.gov/articles/PMC4153398/)).
   **Mitigations:** (a) prefer **within-cohort** variation (the entry-conditions
   design) over cross-cohort level comparisons; (b) compare cohorts only over a
   **career-age window observable for all** of them (e.g. years 0–8), truncating
   the long right tail that only old cohorts have; (c) survival models with a
   left-truncation/delayed-entry term; (d) report cohort sizes and an explicit
   survivorship caveat on every chart.
2. **Right-censoring.** Recent cohorts' careers are incomplete and ongoing roles
   are open at the snapshot — handled correctly only by survival analysis (censor
   at the 2025-02-19 anchor).
3. **Recency / backfill bias.** Older steps lose dates and detail; older cohorts'
   early-career records are sparser and noisier (visible already in
   `transition_network/temporal.py`: 21k moves in 2005-09 vs 54k in 2020-25).
4. **No wages.** Outcomes are proxied by `seniority_score`, occupation **Job
   Zone/status**, `transition_type` mix, and mobility/exit rates — not earnings.
   State this; don't imply pay.
5. **Proxied age.** Generational labels rest on a graduation/entry → age proxy;
   carry the imprecision.

These are not footnotes — they bound what each analysis can claim, and the plan
below is ordered to lead with the designs most robust to them.

---

## 4. Analyses, mapped to our columns (most-robust first)

All consume `paths/steps.parquet` (career age, seniority_score, occupation, Job
Zone) and `paths/transitions.parquet` (typed transitions, Δseniority), plus an
external **BLS annual unemployment-rate** table (the only new reference needed).

1. **Entry-conditions ("scarring") — the identified flagship.** Outcome (e.g.
   `seniority_score`, or `job_zone` of occupation, or promoted-within-5-years)
   regressed on the **entry-year unemployment rate**, controlling for career age
   and calendar period, clustered by entry-year. Test whether bad-entry cohorts
   sit lower early and converge over ~8–10 years (the literature's signature).
   Robust to survivorship because it uses *within-cohort* exogenous variation.
2. **Time-to-first-promotion / time-to-management (survival).** Kaplan–Meier
   curves by entry cohort + Cox PH with entry-conditions and covariates
   (occupation, Job Zone, first-employer type). Event = first `promotion` /
   first management-track `transition_type`; **censor** at snapshot; include a
   **delayed-entry** term for left-truncation. Also time-to-exit and
   time-to-self-employment (first `into_self_employment`).
3. **Career-age profiles, compared at equal age.** Mean `seniority_score`,
   occupation Job Zone, cumulative #employers, and `transition_type` rates as a
   function of career age, one curve per cohort, **clipped to a common 0–N-year
   window**. Reveals cohort divergence without the level-bias of raw comparisons.
4. **Cohort trajectory typologies (sequence analysis).** Stratify the Phase-5
   trajectory archetypes by cohort; test whether the archetype mix shifts across
   cohorts at equal observation length. (Optional true OM on a per-cohort
   subsample for distance-based typologies.)
5. **Cohort × mobility-network.** Build the transition network per entry-cohort
   (the `temporal.py` machinery, re-binned by cohort instead of period) and
   compare structure — e.g. is the IC→management bridge weaker for later cohorts?
   Separates cohort from the period drift `temporal.py` already measured.
6. **Generational mobility (framed carefully).** Tenure/job-hopping and the
   switching-direction (`employer_move_up` share) by proxied generation, **only
   at matched career ages**, explicitly testing the literature's "it's the
   economy, not the cohort" null.

---

## 5. Integration & build

- **New module `cohorts/`** mirroring `paths/`/`transition_network/`: `common.py`
  (cohort definitions, career-age helper, observation-window knobs), a builder
  that emits a per-(profile, career-age) **panel** from `steps`/`transitions`
  with cohort keys + outcomes, and analysis scripts (scarring regression,
  survival, age-profiles). CPU/DuckDB for the panel; `lifelines` (survival) and
  `statsmodels`/`scikit-learn` for models (add a `cohort` dependency group).
- **New reference**: `reference/bls_unemployment.{csv→parquet}` (US annual
  unemployment rate by year; document provenance in `reference/README.md`, like
  the O*NET/CIP entries). The entry-conditions instrument.
- **Reuse**: `temporal.py` for cohort-sliced networks (parameterize its binning by
  cohort), Phase-5 archetypes for trajectory typologies, `seniority_score` /
  `transition_type` / `soc_status.job_zone` as outcomes.
- **Validation/tests** (`cohorts/cohort_tests.py`): panel integrity (one row per
  profile×career-age; career-age ≥ 0; no rows past snapshot), a known sanity check
  (mean seniority rises with career age within a cohort), and a left-truncation
  guard (flag cross-cohort comparisons outside the common observation window).

---

## 6. Phased plan

- **Phase 0 — cohort panel + BLS reference.** Emit the `(profile, career_age)`
  panel with cohort keys and outcomes; fetch BLS unemployment. *Foundational.*
- **Phase 1 — career-age profiles at equal age** (analysis #3) — cheapest, and it
  immediately exposes the survivorship pattern, calibrating expectations.
- **Phase 2 — entry-conditions / scarring regression** (analysis #1) — the
  identified flagship.
- **Phase 3 — survival models** (analysis #2) — KM + Cox with delayed entry.
- **Phase 4 — cohort trajectory typologies + cohort×network** (analyses #4–5).
- **Phase 5 — generational framing** (analysis #6) — last, because it is the most
  bias-prone and needs all the guards above.

Recommended first build: **Phase 0 → Phase 1 → Phase 2.** Phase 1 makes the
selection bias visible and honest; Phase 2 is the one design that is genuinely
identified and matches the strongest literature.

---

## 7. Open decisions

1. **Cohort key for v1** — entry-year (well-populated) vs graduation-year (sparser
   but the cleaner scarring instrument). Recommend entry-year primary,
   graduation-year for the scarring design on its subsample.
2. **Common observation window** N for equal-age comparisons (recommend 0–8 years,
   matching the scarring horizon and maximizing comparable cohorts).
3. **Entry-condition instrument** — national unemployment rate (simple) vs
   occupation/region-specific (richer, needs region resolution — Layer 6).
4. **Generational boundaries** and whether to report them at all given the proxy.
5. **Left-truncation handling** — delayed-entry survival term vs window-clipping
   vs both (recommend both, as sensitivity analyses).
6. **Outcome set** — which proxies are "headline" (recommend `seniority_score`
   trajectory + promotion hazard + occupation Job Zone).

---

## 8. References

- Fosse & Winship (2019), *Practical Guide to APC Analysis: the Identification
  Problem and Beyond*, JRSS-A. https://academic.oup.com/jrsssa/article/182/2/715/7070179
- Oreopoulos, von Wachter & Heisz (2012), *The Short- and Long-Term Career Effects
  of Graduating in a Recession*, AEJ: Applied. https://oreopoulos.faculty.economics.utoronto.ca/wp-content/uploads/2020/05/oreopoulos-et-al-the-short-and-long-term-career-effects-of-graduating-in-a-recession-aej-applied-2012.pdf
- Aisenbrey & Fasang; *Optimal matching in career research* (best practice). https://www.sciencedirect.com/science/article/abs/pii/S0001879115000408
- Gabadinho et al., *TraMineR* sequence-analysis toolkit. https://traminer.unige.ch/
- Cox proportional hazards / event-history for careers. https://methods.sagepub.com/book/introducing-survival-and-event-history-analysis/n5.xml
- Left-truncation selection bias in cohort studies. https://pmc.ncbi.nlm.nih.gov/articles/PMC6151356/
- Generational job-mobility myth (economy, not cohort). https://www.nirsonline.org/articles/new-research-debunks-job-hopping-myth-about-millennials-and-gen-z/
