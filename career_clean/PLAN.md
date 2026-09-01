# Career / employment data: profile, quality assessment, and three cleaning plans

Goal: canonicalize the three career fields — **organization** (employer),
**position title**, and **description** — across the `experience` (9.08M rows)
and `positions` (2.79M rows) tables, maximizing how often we recognize *the same
value* while keeping *distinct values* apart, toward ~100% coverage of that
same-vs-distinct decision.

Everything below is measured on the parsed data. Reproduce with:

```bash
uv run --group dev python exploration/career_explore.py all
# sections: overview model orgkey placeholders titles descriptions coverage integrity
```

This is the **career analogue of the education effort** (`edu_clean/FINDINGS.md`),
and the education results give us strong, transferable priors (see "Priors").

---

## 1. The data model (must be respected before any cleaning)

`experience` is one row per company-stint; `positions` is one row per role
*within* a stint. LinkedIn uses a **grouped-position model**, which creates the
single most important gotcha:

- **Single-role stint** (8.01M rows, no `positions` children): `experience.title`
  is the **job title**, `experience.company` is the employer. Normal case.
- **Multi-role stint** (1.06M stints with `positions` children):
  `experience.title` is the **company name** (verified: `title == company` for
  **100.0%** of these rows). The real job titles live in `positions.title`;
  `positions.subtitle` repeats the company.

**Consequence:** the clean "position title" column is
`single-role experience.title` ∪ `positions.title` (≈10.8M title instances).
Treating `experience.title` uniformly as a job title would mislabel 1.06M rows
with company names. The exploration script encodes this as the `JOB_TITLES` view.

Field inventory (the three targets in **bold**):

| field | table | role |
|---|---|---|
| **company** | experience | employer name — TARGET (organization) |
| company_id | experience | LinkedIn company slug — **canonical org key**, 62% coverage |
| url | experience | `linkedin.com/company/<slug>` — same key, redundant w/ company_id |
| **title** | experience + positions | position title — TARGET (conditional source, see above) |
| **description** | experience + positions | free-text role summary — TARGET |
| subtitle (experience) | experience | **100% NULL — drop** |
| subtitle (positions) | positions | company name (redundant with parent) |
| start/end_date, duration | both | semi-structured `"Mon YYYY"` / `"YYYY"` / `"Present"` |

---

## 2. Quality & integrity assessment

**Integrity — clean.** 0 dangling positions, 0 experience rows without a parent
profile, 0 JSON parse errors on 2M profiles. Only 15,603 duplicate experience
groups (31,908 rows, **0.35%**) — same person/company/title/dates repeated.

**Organization (`company`) — 3.40M distinct over 9.07M rows.** Issues:

1. **Placeholders dominate the head.** The #1 and #2 "companies" are
   `Self-employed` (41,936) and `Freelance` (27,519), with many case/punct
   variants (`Self Employed` 14,751, `Self-Employed` 8,583, …) plus `Retired`,
   `Unemployed`, `N/A`, `None`, `Various`, `Independent Contractor`,
   `Stealth Startup`, `Homemaker`. These are **not organizations** and must be
   routed to a dedicated `NON_ORG` bucket — otherwise they corrupt every metric
   and cause one name to map to *hundreds* of company_ids (`Self-employed` → 209
   distinct ids).
2. **`company_id` is a strong canonical key** (62% coverage, 1.07M distinct). It
   collapses spelling variants *and* sub-brands automatically: `att` merges
   `AT&T`, `AT&T Mobility`, `AT&T Wireless`; `citi` merges `Citi`/`Citigroup`;
   `pwc` merges 4+ `PricewaterhouseCoopers` spellings. **The same url slug is
   embedded in `url`** — redundant, a good cross-check.
3. **Over-merge policy question.** `company_id` also absorbs *acquired/renamed
   brands* (BellSouth, Cingular, SBC → `att`). Whether that is "correct" depends
   on the analysis goal: **current legal entity** (keep) vs **historical
   employer brand** (don't merge). This is a policy decision, not a bug — flag it.
4. **Long tail + 38% have no id.** Top-50k names cover only 45.6% of rows;
   2.75M distinct names are singletons. The 38% of rows lacking a `company_id`
   are exactly the tail that needs name-based resolution.
5. **Substring matching is unsafe.** `Citizens Bank`, `Citizens`, and
   `First Citizens Bank` look similar but are distinct entities (distinct ids) —
   the id disambiguates where names cannot.

**Position title — 2.42M distinct (single-role) + 1.30M (positions).** Issues:

1. **Same-vs-distinct tension is the core problem** (as with education's
   `field`). `Sr. Software Engineer` ≡ `Senior Software Engineer` (merge), but
   `Senior Software Engineer` ≠ `Software Engineer` (seniority is real — keep).
   Abbreviations (`Sr`→`Senior`), roman numerals (`II`), and modifiers all need
   structured handling, not blind clustering.
2. **No occupation reference in-repo.** Education had `reference/cip_codes.csv`;
   there is **no SOC/O*NET/ESCO occupation taxonomy** present. Acquiring one is
   the title analogue of CIP and is the lever for principled coverage.
3. **Multilingual.** ~0.5% of titles are non-ASCII, but they span many languages
   (Spanish `Diseñador gráfico`, Portuguese `Estagiário`, Chinese `销售经理`),
   plus the `Realtor®` symbol family. Pure English rules/taxonomy will miss these.
4. **Source truncation at 100 chars** (titles pile up at exactly len=100). Long
   "headline" titles (`Founder | CEO | Speaker`) are rare but present.
5. **Long tail** but lighter than company: top-50k titles cover 64%; 2.11M
   singletons.

**Description — 4.17M present (≈46%); the rest NULL.** Issues:

1. **Not an entity-resolution field.** Values are essentially unique free text
   (4.10M distinct of 4.17M). "Cleaning" here = **normalization**, not
   same-vs-distinct merging.
2. **HTML is already separated.** `description` is the plain-text variant;
   `description_html` keeps the markup (they differ for 4.10M rows, `description`
   carries no `<tag>`s). Use `description` for text analysis.
3. **31.7% non-ASCII** — multilingual content + emoji/bullets. Normalization
   (NFKC, whitespace, optional language tagging, boilerplate dedup) is the work.

---

## 3. Priors carried over from the education effort

The education benchmark (`edu_clean/FINDINGS.md`, incl. a 9-encoder study) is
directly relevant and saves us re-deriving it:

- **A reference/ID key beats everything when one exists** — institution `slug`
  hit P/R/F1 = 1.0. Here, **`company_id` is that key** for organizations.
- **Lexical/fuzzy owns the typo axis** (0.94 vs 0.85 best embedding) but **can't
  expand abbreviations or merge cardinality-different variants** without
  guardrails. Relevant to `Sr.`→`Senior` and campus/brand variants.
- **Embeddings are a poor *autonomous merger*** — they conflate siblings/levels
  ("Boston University" ≈ "Boston College", "BS" ≈ "BA"). They would likewise
  merge sibling companies and adjacent seniorities. Their value is as a
  **guarded candidate generator for review**, and for the multilingual/long tail.
- **Coverage to ~100% comes from curation + a review queue**, not a bigger model.

These priors shape all three plans below; the differences are how much machinery
each adds beyond the high-precision backbone.

---

## 4. Three plans

All three share **Phase 0 — Normalize & restructure** (cheap, no downside):
build the `JOB_TITLES` view (conditional title source), drop `experience.subtitle`,
NFKC + case/whitespace/`&`→`and`/punct normalization, parse dates to a canonical
form, and apply a **placeholder dictionary** that diverts self-employed / freelance
/ retired / n-a / various into a `NON_ORG` status field. They differ in how the
tail is closed.

We measure every plan the same way (mirroring `edu_clean/gold.py`): a hand-labeled
**gold set of (a, b, merge?) pairs** per field → pairwise **precision / recall /
F1**; plus **reduction** (`1 − n_canonical/n_distinct`), **reference coverage**,
and runtime. Gold pairs must stress the hard boundary (Sr↔Senior vs Senior↔base;
Citi↔Citigroup vs Citizens↔First-Citizens; military-branch variants).

### Plan A — Reference-key backbone (precision-first, CPU, fastest)

Lead with the keys the data already carries; accept tail gaps.

- **Organization:** canonical id = `company_id` (or url slug). Extend coverage
  with an **exact-name → id crosswalk** mined from rows that *do* have an id
  (high-confidence name↔id co-occurrence), then a **guarded fuzzy** pass
  (equal-cardinality token / Damerau) on the residual no-id tail. Placeholders →
  `NON_ORG`. Decide the acquired-brand policy once and encode it.
- **Title:** normalize + a **curated abbreviation/seniority parser**
  (Sr/Jr/roman-numeral/level expansion) producing `(seniority, base_title)`;
  canonicalize on `base_title` while preserving seniority so distinct levels stay
  distinct. No external taxonomy.
- **Description:** normalize only (NFKC, whitespace, language tag).

*Pros:* precision ≈1.0 where keys fire, ~seconds on CPU, fully auditable, no
model/GPU. *Cons:* organization tail (38% no id) and multilingual/synonym titles
(`Programmer` ≈ `Software Developer`) stay unresolved; recall capped.

### Plan B — Reference + lexical tail + curation loop (no ML; the edu "production" choice)

Plan A's backbone, then **close the tail without embeddings** and drive coverage
toward 100% by curation:

- **Add an external occupation taxonomy** (O*NET-SOC or ESCO) as the title
  analogue of CIP: exact + token match titles to occupation codes for a coverage
  metric and a synonym backbone; keep raw seniority.
- **Guarded fuzzy clustering** on org and title residuals (cardinality
  guardrail to avoid the subset trap).
- **Review queue + alias ratchet:** low-confidence/unmatched values are surfaced
  for human curation; accepted decisions become alias rules, so coverage
  *ratchets up over time without sacrificing precision* — the mechanism that
  actually reaches ~100% on the same-vs-distinct decision.

*Pros:* precision held high, transparent, principled coverage path, still
CPU-only. *Cons:* curation labor; cannot auto-merge semantic synonyms or
cross-language titles (those pile into the review queue).

### Plan C — Semantic-assisted (embeddings as guarded candidate generator + LLM adjudication)

Plan B, plus a **GPU embedding layer used only to *propose*** matches — never to
merge autonomously — targeting exactly what lexical can't reach: the 2.75M-name
org tail, multilingual titles, and semantic title synonyms.

- **Embeddings (e.g. bge-base; minilm for throughput)** anchored to reference
  anchors (company_id centroids / SOC occupation titles) behind a **token
  guardrail**, emitting ranked candidates with a `confidence` score into the
  review queue.
- **Optional LLM adjudication** on the low-confidence band: decide hard org
  same/distinct cases, normalize messy free-form orgs ("Freelance @ Acme" →
  org=Acme + self-employed flag), and map multilingual titles. LLM is the
  reviewer, not the merger.

*Pros:* best recall on the long tail + multilingual content; pushes
same-vs-distinct coverage closest to 100%. *Cons:* GPU + LLM cost; embeddings
carry the sibling/level over-merge risk proven in education, so guardrails and
human/LLM confirmation are mandatory; most complex to build and audit.

### How to choose

| | A | B | C |
|---|---|---|---|
| precision | highest | high | high (guarded) |
| org tail / multilingual coverage | low | medium | **high** |
| cost | seconds, CPU | minutes, CPU | GPU + LLM $ |
| auditability | full | full | partial |
| reaches ~100% same/distinct | no | via curation | via curation+semantics |

Recommended sequencing: **ship A immediately** (it is the precision engine and
settles the data-model + placeholder + policy decisions), **layer B's taxonomy +
curation loop** as the durable path to coverage, and **add C selectively** only
for the residual tail and multilingual titles where lexical demonstrably stalls —
exactly the conclusion the education study reached.

---

## 5. Open decisions to confirm before building

1. **Acquired-brand policy:** does `company_id` over-merging (BellSouth → AT&T)
   match the intended unit of analysis (current entity vs historical brand)?
2. **Title granularity / taxonomy:** adopt O*NET-SOC vs ESCO (multilingual)?
   How is seniority represented — folded into the canonical or a separate axis?
3. **Multilingual scope:** canonicalize non-English titles, or tag-and-defer?
4. **NON_ORG taxonomy:** what status buckets (self-employed, freelance, retired,
   student, unemployed, confidential/stealth, various) and do they keep any
   residual org signal?
5. **Description scope:** normalization only, or also dedup boilerplate / detect
   language / extract skills?
