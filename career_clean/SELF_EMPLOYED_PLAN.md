# Making sense of self-employed / freelance career steps

## Audit + clustering update — 2026-06-04

Phases 1–3 (the `employment_type` axis and title status-strip occupation
recovery) shipped. An audit then asked the harder question this plan exists to
answer: of the self-employment population, how many get a usable **functional /
industry cluster** (the unit we actually want to group on)? Measured on the
9.34M career-step vocab (`exploration/self_employed_audit.py`):

- **Self-employment population** (`employment_type ∈ {self_employed,
  business_owner}`) = **459,120 rows / 4.25%** of all steps.
- **Only 11.9%** of them got any O*NET-SOC code. The uncoded 88% split into
  owner (45.9%), freelance/contractor "other" (25.2%), founder (22.2%),
  consultant (6.7%). Two distinct failure modes: the head noun is a generic
  *status* word ("Owner", "Consultant") O*NET blocks, **or** a real occupation
  noun survives but is O*NET-*ambiguous* ("Designer", "Editor" → many SOCs).

**Key reframing:** for *clustering*, the SOC code is the wrong target — too
granular and ambiguity-blocked. The target is the **functional cluster = SOC
major group** (2-digit), the standard coarsening, which tolerates the ambiguity
that blocks exact SOC. Four recs (3 from title/company below, plus description
inference in the next subsection), all deterministic / CPU / precision-first /
TDD, compose into one cluster per step (`career_clean/se_cluster.py`,
`se_qualifier.py`, `se_personal_brand.py`, `se_description.py`; tests in
`se_tests.py`; evaluated by `run_self_employed.py` + `run_se_description.py`):

1. **Qualifier recovery** (`se_qualifier`) — strip the ownership/founder/exec/
   consulting/freelance shell off the title and cluster the *qualifier*: O*NET
   if unambiguous (keeps the SOC), else a curated industry gazetteer ("IT
   Consultant"→15, "Restaurant Owner"→35, "Freelance Designer"→27). Guards
   against the O*NET "management"/"general"→55 (Military) false hit.
2. **Personal-brand company trade** (`se_personal_brand`, propose-only) — for
   bare-owner titles, read the trade out of the *no-id* company name ("Smith
   Photography"→27, "Klean Cut Lawn Care"→37). Suppressed when a real
   `company_id` is present (franchise/MLM employers are not personal brands).
3. **Functional-cluster rollup** (`se_cluster`) — composes SOC → qualifier →
   title-keyword → company-brand → an **honest** `*_unspecified` residue keyed by
   `employment_type` (never silently dropped). Shared gazetteer = one taxonomy,
   three consumers. Production entry point:
   `final_hybrid.canon_functional_cluster_value`.

**Result (`results/self_employed_eval.json`):** functional-cluster coverage on
the self-employment population **11.9% → 40.6% (+28.7pp, 3.4×)**. Contribution by
method (row %): qualifier 13.7, soc 11.9, company_brand 9.9, title_keyword 5.1;
residue 59.4. Top recovered clusters: Arts/Design/Media (27) 18.0%, Business/
Financial (13) 4.7%, Management (11) 2.6%, Computer (15) 2.5%, Personal Care (39)
2.3%, Sales (41) 2.1%.

### Rec 4 — free-text description inference (the next lever)

The ~59% title+company residue is bare "Business Owner"/"Consultant"/"Founder"
on placeholder employers — no signal in title or company. But **47% of those
rows carry a `description`**, and self-employed people routinely name their
trade there ("artisan letterpress shop", "professional pet sitting and dog
walking", "create Mac applications software"). `se_description.py` mines it,
**propose-only** (free text is noisy → lowest confidence tier, review-queue
grade). Grounding (`exploration/se_description_explore.py`) fixed the two naive-
voting failures: generic boilerplate ("manage operations", "marketing",
"software expertise") is a **WEAK** word set that may never decide alone, and
the trade is usually in the **lead sentence**. Two stages: `desc_lead` (first
strong keyword in the lead window, conf 0.50) → `desc_vote` (≥2 distinct strong
keywords win the whole text, conf 0.40). A description-only token hazard — the
gazetteer key `it` (Information Technology) matching the English pronoun "it" in
prose — is excluded (it cut a real ~2.1K false-positive Computer block).

Evaluated **row-level** over `experience` (descriptions are per-row, so the
deduped vocab can't carry them; `run_se_description.py`,
`results/se_description_eval.json`): of 252,781 residue rows, 59.8% have a
description and the lever clusters **43,723 of them (28.9% of described residue,
+17.3pp of all residue)** at clean precision. **End-to-end this lifts overall
self-employment functional-cluster coverage 40.1% → 50.5% (+10.4pp)** on the
row-level basis (the 40.1% cross-validates the 40.6% vocab measurement). Top
recovered clusters: Arts (27) 8.4K, Business (13) 6.4K, Sales (41) 5.9K,
Construction (47) 3.6K, Education (25) 3.5K, Personal Care (39) 3.1K.

The remaining residue is genuinely uninformative (bare status, empty/garbage, or
non-English descriptions); further gains are a curation/translation problem, not
more parsing. All four recs' cases are in `normalization_regression_checks.py`;
production entry point `final_hybrid.canon_functional_cluster_value` now takes an
optional `description`.

---

The career cleaner (`FINDINGS.md`) currently routes self-employed / freelance
employer values into a single `nonorg:self_employed` bucket and stops there. That
is the right move for the **organization** axis — these strings are not
employers — but it throws away everything else the row is telling us. This
document is the plan for the *next* problem: turning that discarded population
into structured signal.

The thesis, in one line: **self-employment is an employment-status axis,
orthogonal to occupation — not an organization.** The existing system already
thinks in orthogonal axes (literal role, seniority level, O\*NET occupation); the
fix is to add a fourth axis (`employment_type`) and *re-route the occupation
signal out of the title*, because for these rows the title — not the employer
line — is where the real job lives.

---

## 1. Why the current handling is lossy

For a normal row, `company` is the employer and `title` is the job. For a
self-employed row the employer line is a **status declaration** ("Self-employed",
"Freelance"), and the occupation has moved into the title ("Freelance Graphic
Designer", "Independent Consultant", "Private Tutor"). Collapsing the employer to
`nonorg:self_employed` is correct, but if we don't then mine the title we lose:

- **the occupation** (graphic designer, writer, photographer, tutor, …),
- **the employment type** (solo freelance vs. business owner vs. retiree
  freelancing vs. stealth founder),
- **the tenure** (93% of these rows carry start/end dates — see §2).

These rows are also a measurement trap: prior work (Statistics Canada; *Journal
of Labor Economics* on reconciling survey vs. administrative self-employment)
shows self-employment is systematically **mis-recorded and under-counted**, and
that the only durable signal is the **occupation coded from the title**, with
self-employment treated as a **flag orthogonal to that occupation**. That is
exactly the axis model this repo already uses — we are extending it, not
inventing it.

---

## 2. Empirical profile (measured on the parsed tables)

Scale of the explicit placeholder population (`company` normalizes to a
self-employment placeholder), out of 9.07M non-null `company` rows:

| bucket | rows | % of all company rows | distinct spellings |
|---|---|---|---|
| **self_employed** (freelance, independent contractor, sole proprietor, …) | **121,137** | **1.33%** | 5,072 |
| various / multiple clients | 9,660 | 0.11% | 2,911 |
| retired | 8,127 | 0.09% | 1,939 |
| none / n-a | 7,118 | 0.08% | 53 |
| confidential / private | 2,720 | 0.03% | 38 |
| unemployed | 1,558 | 0.02% | 231 |
| stealth | 1,433 | 0.02% | 197 |
| **all NON_ORG** | **152,040** | **1.68%** | — |

But the company line **understates** the true population, because the
self-employment signal also lives in the **title**. Over 10.80M job-title
instances (`JOB_TITLES` = single-role `experience.title` ∪ `positions.title`):

| title marker | instances | % of titles |
|---|---|---|
| `consultant` | 356,107 | 3.30% |
| `owner` | 186,030 | 1.72% |
| `founder` / `co-founder` | 95,123 | 0.88% |
| `freelance*` | 51,790 | 0.48% |
| `independent` | 35,289 | 0.33% |
| `contractor` | 23,888 | 0.22% |
| `self-employed` (in title) | 5,330 | 0.05% |
| **strong solo markers (union)** | **74,254** | **0.69%** |

What a self-employed-company row actually carries (the 121,137 `self_employed`
rows):

| signal | coverage | reading |
|---|---|---|
| **title present** | **100.0%** | the occupation is in the title, always |
| start & end dates | 93.1% | tenure is usable |
| description | 47.4% | half carry free text (skills, client list) |
| company_id | 14.8% | **noise** — "Self-employed" → `conscience-vc` etc.; do not trust |
| multi-role (has `positions`) | 4.4% | almost always a single role |

Top titles on self-employed rows confirm the picture — they are **occupations
overloaded with a status prefix**: Consultant (2,002), Independent Consultant
(1,592), Freelance Writer (1,480), Owner (1,040), Freelance Graphic Designer
(970), Graphic Designer (849), Writer (822), Private Tutor (637), Artist (583),
Photographer (486), … and a notable share of **Retired / Semi-Retired (2,329)**
sitting in the self-employed company bucket (status, not occupation).

The hidden tail: **2.13M distinct no-id company names / 2.77M rows / 1.96M
singletons.** Some fraction are personal-brand sole proprietorships ("Jane Doe
Photography", "Smith Consulting LLC") that read as a company but are really one
self-employed person. These will never get a `company_id`; they are only
resolvable from the name shape + title.

---

## 3. Research priors (how this is handled elsewhere)

- **BLS / O\*NET-SOC** is the standard occupation backbone; self-employment is a
  **worker-class flag** (`SOC` codes the *what*, class-of-worker codes the
  *how*), never folded into the occupation. → keep `employment_type` separate
  from `occupation_code`.
- **Statistics Canada & JLE reconciliation studies**: self-employment is
  under-/mis-reported and the employer field is unreliable; the **title-derived
  occupation** is the stable measure. → trust the title, distrust the
  self-employed company_id (matches our 14.8%-and-noisy finding).
- **Gig/tax-data work (BFI Chicago)**: distinguishes *solo gig* from *business
  owner* — they behave differently. → our taxonomy must split solo-freelance from
  owner/founder, not lump them.
- Career best-practice guides (and ATS behavior) confirm the *data-generating
  process*: people are told to write "Freelance / Self-Employed" on the employer
  line and put the real role in the title — which is exactly the structure we
  measured.

---

## 4. The model: a fourth orthogonal axis

A cleaned career step already emits `role_canonical` (literal title),
`seniority_level`, and `occupation_code` (SOC). Add:

```
employment_type ∈ {
  employee,            # default — has a real employer / company_id
  self_employed,       # solo: freelance, independent contractor, sole proprietor, gig
  business_owner,      # owner/founder of a (possibly real) small business
  consultant,          # independent consulting (overlaps self_employed; see §6)
  retired, unemployed, homemaker, student,   # not-currently-working statuses
  stealth, confidential, various, unknown
}
```

This axis is computed from **both** the employer line and the title (§6), and is
deliberately *separate* from occupation: a "Freelance Graphic Designer" is
`employment_type=self_employed` **and** `occupation=27-1024 (Graphic Designers)`.
Today we capture neither for that row; the plan captures both.

Key sub-decision — **solo vs. owner.** Freelance/independent/sole-proprietor →
`self_employed` (one person selling their labor). Owner/Founder/Co-Founder →
`business_owner` (an entity, may have employees, may even have a real
`company_id`). The gig-economy literature says these diverge; we keep them
distinct and let analysis collapse them if it wants.

---

## 5. Signal-routing rules

For every career step, resolve the four axes by precedence, **status first**:

```
employment_type:
  1. company normalizes to a placeholder  -> that bucket           (self_employed, retired, …)
  2. else title carries a solo marker      -> self_employed         (freelance/independent/sole-prop/private-practice)
  3. else title carries owner/founder       -> business_owner        (guarded; see §6 caveat)
  4. else                                    -> employee

organization (company axis):
  - if employment_type ∈ {self_employed, retired, unemployed, …}: org = NULL,
    status = the bucket. The self-employed company_id is discarded (it is noise).
  - business_owner MAY keep a real company_id if one is present and non-placeholder
    (an owner of a registered company is a legitimate org link) — policy decision, §8.

occupation (SOC axis):  ** the new work **
  - source title = positions.title for multi-role else experience.title (already in JOB_TITLES)
  - try O*NET match on the RAW title first;
  - if unmatched OR the only match is a generic-ownership false hit, ALSO try the
    STATUS-STRIPPED title (remove leading freelance/independent/self-employed/
    contractor/private), and take the first surface that yields an UNAMBIGUOUS code.
  - keep BOTH the literal role_canonical (with the marker) and the occupation_code.
```

Why "try both surfaces, prefer the unambiguous code" rather than always
stripping — measured on the head self-employed titles:

| title | raw → SOC | stripped → SOC | lesson |
|---|---|---|---|
| Freelance Graphic Designer | — (no match) | **27-1024** | stripping *recovers* |
| Freelance Writer | 27-3043 | 27-3043 | stable either way |
| Freelance Artist | **27-1013** | — (Artist ambiguous) | stripping *loses* |
| Private Tutor | **25-3041** | — (Tutor ambiguous) | stripping *loses* |
| Owner | 29-1229 *(Physicians!)* | 29-1229 | **false hit — guard generic ownership** |

So neither raw-only nor strip-only is correct; the union (prefer unambiguous,
guard generic owner/founder/consultant against noisy O\*NET alternates) is. This
is the same precision-first, deterministic-backbone philosophy as the existing
occupation coder — extended with a status-strip fallback.

---

## 6. Edge cases the rules must handle

- **Retired-in-self-employed.** ~2,329 rows say company "Self-employed" but title
  "Retired/Semi-Retired" (or vice versa). Status should win from **whichever
  field declares it**; title "Retired" → `employment_type=retired`, no
  occupation.
- **Consultant ambiguity.** "Consultant" is `employment_type` ambiguous (a
  salaried consultant at Deloitte vs. an independent consultant) **and**
  occupation-ambiguous (maps to many SOCs). Rule: only mark `self_employed` from
  "Consultant" when corroborated (company is a placeholder, or title says
  "Independent/Freelance Consultant"); otherwise leave `employee` and uncoded.
- **Owner/Founder false occupation hits.** O\*NET alternates contain "Owner"
  under specific SOCs (e.g. Physicians). Generic single-word owner/founder titles
  must be **blocked from O\*NET matching** unless a real occupation token is
  present ("Restaurant Owner" → food-service management is fine; bare "Owner" is
  not).
- **Personal-brand companies (the 1.96M singleton no-id tail).** A no-id company
  whose name pattern looks like `PersonName + {Photography, Consulting, Design,
  LLC, Studio, …}` is a soft `self_employed`/`business_owner` signal. Treat as a
  **propose-only** heuristic feeding the review queue — never an autonomous merge
  — because it is name-shape inference, not a key.
- **Multilingual markers.** "Autónomo", "Freelance" (universal), "Independiente",
  "por cuenta propia", "Selbständig". Extend the placeholder/marker dictionaries;
  this is curation, not modeling (consistent with the FINDINGS conclusion).
- **Various / multiple clients** (9,660 rows) is a self-employment *signal* too
  ("Various clients" ≈ freelancer) — currently its own bucket; consider folding
  into `self_employed` with a `multi_client` flag.

---

## 7. Phased implementation

**Phase 0 — instrument (½ day).** Land the measurements in this doc as a
reproducible `exploration/self_employed_explore.py` section (placeholder rows,
title-marker rows, signal coverage, raw-vs-stripped occupation recovery), so
every later change is benchmarked, mirroring `career_explore.py`.

**Phase 1 — the `employment_type` axis (deterministic, CPU, precision-first).**
Add the status taxonomy (§4) and the status-resolution rule (§5 steps 1–4) to
`approach_a_rules` / `final_hybrid`. Reuse `_PLACEHOLDER_EXACT` /
`_PLACEHOLDER_RE`; add the title-marker pass and the solo-vs-owner split. Output
`employment_type` + `confidence` + `method` on every row. No new dependencies.

**Phase 2 — occupation recovery from self-employed titles.** Add the
"try-both-surfaces, prefer-unambiguous, guard-generic-ownership" fallback to
`occupation.match`. This is the high-value step: it converts ~74K+ strong-marker
title instances (plus the 121K placeholder-company rows, all title-bearing) from
*uncoded* to *SOC-coded*. Measure the lift in SOC row-coverage on this
sub-population specifically.

**Phase 3 — gold + evaluation.** Extend `gold.py` with an `employment_type`
labeled set and self-employed occupation pairs that stress the boundaries:
- `Freelance Graphic Designer` ↔ `Graphic Designer` → **same occupation**,
  **different employment_type**;
- `Independent Consultant` ↔ `Consultant at Deloitte` → **same literal-ish role**,
  **different employment_type**;
- `Owner` (bare) must **not** code to Physicians;
- `Retired` in either field → `retired`, no occupation.
Report precision/recall/F1 on the `employment_type` decision and the
occupation-coverage lift, same harness as the other axes
(`run_final_compare`, `normalization_regression_checks.py`).

**Phase 4 — tail & curation (optional, follow the FINDINGS playbook).**
Personal-brand name-shape proposals and multilingual markers feed the **review
queue / alias ratchet**, not an autonomous model. The anchored-embedding
occupation proposer already exists (`approach_c.run_anchored_occupation`) and can
populate SOC candidates for the self-employed tail into the same queue. No
embeddings in the default path (the title precision argument from FINDINGS holds
here too).

---

## 8. Open decisions to confirm

1. **Solo vs. owner granularity** — keep `self_employed` and `business_owner`
   separate (recommended, per gig-economy literature), or one `self_employed`
   flag with an `is_owner` sub-bit?
2. **business_owner org link** — when an owner/founder row *does* carry a real
   non-placeholder `company_id`, keep the org link (they own a registered entity)
   or null it like solo freelancers? (Affects employer-side counts.)
3. **Consultant default** — when uncorroborated, lean `employee` (precision) or
   `self_employed` (recall)? Recommend `employee` + review-queue, matching the
   precision-first house style.
4. **Retired/unemployed/homemaker/student** — are these in scope as
   `employment_type` values (status of the *person*, not a job), or filtered out
   of the career-step analysis entirely? They currently share the NON_ORG path.
5. **Unit of analysis for `various`/`multiple clients`** — fold into
   `self_employed` (with `multi_client`) or keep distinct?
6. **Multilingual marker coverage** — how far to extend the dictionaries now vs.
   defer non-English solo markers to the review queue (~consistent with the
   occupation multilingual stance).

---

## 9. Expected outcome

A career step that today reads `company = "Freelance"`, occupation *uncoded*,
status *lost* will instead carry:
`employment_type = self_employed`, `organization = NULL (status: self_employed)`,
`role_canonical = "freelance graphic designer"` (literal, preserved),
`occupation_code = 27-1024 (Graphic Designers)`, with start/end tenure intact —
turning ~150K explicit NON_ORG rows plus the ~74K title-marked rows from a
discarded bucket into a measurable, SOC-coded, status-flagged population, on the
same deterministic precision-1.0 backbone + curation-ratchet model the rest of
the cleaner already uses.
