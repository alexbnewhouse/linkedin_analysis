# A 4-level, multi-method industry classifier

> **Status — implemented (2026-06-08).** This design is built in `industry/`; see
> `industry/README.md` for the as-built reference. Shipped: the frozen 4-level
> taxonomy (`taxonomy.py`/`taxonomy.json`, 162 nodes, NAICS crosswalk,
> structured-output enum), the deterministic backbone M1 curated + M3 name rules +
> M4/M5 occupation prior with depth-truncating fusion (`classify.py`), the
> propose-only LLM batch layer behind a frozen cache (`llm.py`), the gold/eval/test
> harness (`gold.py`, `run_industry.py`, `tests.py`), and the assembler
> (`build_industry.py`). Measured deterministic coverage: **42% of career steps on a
> real industry at L2 precision 1.0** before any LLM/curation; gold L2–L4 precision
> 1.0. The sections below are the original design; open decisions in §7 were
> resolved as: custom-over-NAICS spine, single stable industry per company (v1,
> giants → `XDV`), LLM external Batch API + propose-only + always human-gated.

Industry is Layer 6a of `CAREER_PATHS_PLAN.md` — the org-side axis career-flow
diagrams are most often drawn on ("who moves from finance to tech?"). This
document designs (a) a **4-level hierarchical industry schema** and (b) a
**multi-method classifier** that *infers* industry from the many signals in the
data, because the in-data field is unusable.

## 0. The finding that drives the whole design

The in-data industry field is a **dead end**, measured:

- `cc_industry` is populated on **106 of 2,000,000 profiles (0.005%)**, and the
  values are **company names, not industries** ("Bank of America", "AT&T",
  "Self-employed"). It is unrecoverable. (The README already flagged it noisy.)
- There is **no industry reference asset in-repo** (we have CIP for fields of
  study and O\*NET for occupations, but nothing for industry).

So industry is **~100% an inference problem**. The good news is the strongest
lever is cheap and concentrated:

- `company_id` is present on **62.0%** of the 9.08M experience rows
  (1.07M distinct ids). Industry is a **property of the company**, so we resolve
  it **once per company, then propagate to every row sharing that id** — we label
  *companies*, not rows.
- The head is tiny and dominant: top **10,000** company_ids cover **30.1% of all
  rows**, top **25,000 → 36.1%**, top **50,000 → 40.7%**. A curated head table of
  a few tens of thousands of companies covers a third-plus of all career steps at
  precision ≈ 1.0. Company *names* (for the no-id tail) are similar: top 50k names
  → 45.6% of rows.

That concentration is the architecture: **a small curated/bootstrapped backbone
at the company grain + propagation, then lexical name rules for the tail, then
weak inferential priors for the residual** — the same precision-first +
curation-ratchet shape the rest of the repo uses.

---

## 1. The 4-level hierarchical schema

Don't invent the taxonomy from scratch — **anchor the lower levels on a standard
crosswalk** so codes are stable, externally joinable, and bootstrappable from
public data; put an **analytically friendly macro level on top**. Four levels:

```
L1  Macro-sector   ~10–12   broad, presentation-friendly buckets
L2  Sector         ~25      ≈ NAICS subsector / LinkedIn "industry group"
L3  Industry       ~120–150 ≈ NAICS 4-digit / LinkedIn "industry"
L4  Sub-industry   ~300–700 ≈ NAICS 5–6-digit / GICS sub-industry
```

Example path:

```
L1 Finance
 └ L2 Banking
    └ L3 Commercial Banking
       └ L4 Retail / Consumer Banking
L1 Technology
 └ L2 Software & IT Services
    └ L3 Application Software
       └ L4 SaaS / B2B Software
L1 Public Sector
 └ L2 Government Administration
    └ L3 Defense & Military
       └ L4 Armed Forces (Active)
```

### Which standard to anchor on

| backbone | native levels | pro | con |
|---|---|---|---|
| **NAICS** (2→3→4→6 digit) | 5 | official, hierarchical, US-centric (matches a US-heavy dataset + O\*NET-SOC crosswalks) | establishment-based; bottom is very granular; some awkward buckets |
| **ISIC / NACE** (Section→Division→Group→Class) | 4 | exactly 4 levels; international/multilingual | less familiar in US business context |
| **GICS** (Sector→Group→Industry→Sub-Industry) | 4 | clean 4 levels, market-friendly labels | skewed to investable/public firms; weak on public sector, nonprofits, SMB |
| **LinkedIn industry taxonomy v2** | 2 (group→industry) | matches the source platform's mental model | only 2 levels; proprietary; flat |

**Recommendation:** a **custom 4-level spine that crosswalks down to NAICS**
(authoritative, joinable to BLS occupation×industry data — see method M5), with
L1 a curated ~10–12-bucket macro layer (Tech, Finance, Healthcare, Education,
Public Sector, Manufacturing, Consumer/Retail, Energy & Utilities, Media &
Entertainment, Professional Services, Nonprofit/Social, Real Estate, …) for
clean top-level flow diagrams. Keep a **stored crosswalk** `our_code ↔ naics ↔
linkedin_industry` so we can ingest bootstraps keyed in any of them. If the
non-US/multilingual tail becomes important, swap the lower-level anchor to
ISIC/NACE (its 4 levels map cleanly onto L1–L4).

### Design rules for the schema

- **Every node has a stable code** (`l1.l2.l3.l4`, e.g. `FIN.BNK.COM.RET`) plus a
  display label and a NAICS crosswalk — codes drive joins, labels drive the UI.
- **Partial assignment is first-class.** A company may be classified only to L1/L2
  if the evidence is shallow (see §3). The schema must allow a node at any depth,
  not force L4.
- **"Unclassifiable" buckets exist** at each level (e.g. `Conglomerate /
  Diversified`, `Other / Unknown`) so the long tail has a home and isn't
  force-fit.
- **A couple of cross-cutting flags** rather than separate branches: `sector ∈
  {private, public, nonprofit}`, `is_self_employment` (ties to the self-employed
  plan — a freelancer's "industry" is their craft, see §4).

---

## 2. The unit of analysis: classify companies, propagate to rows

Resolve industry at the **distinct-company grain** (`company_id`, else normalized
name), cache `company → industry_path`, then join onto experience rows. This is
~1.07M ids + ~2.1M no-id names to decide *once*, vs. 9.08M rows — cheaper, and it
guarantees the same company gets the same industry everywhere (consistency the
viz needs). A company's industry is treated as **stable over time** by default
(a known limitation — conglomerates and pivots get the `Diversified` bucket or a
review flag, not per-year industries, in v1).

---

## 3. The multi-method classifier (precedence + fusion)

Each method emits a candidate **`(industry_path, depth, confidence, method)`**,
where `depth` is how far down L1→L4 that method can justify. A fusion layer
(§3.8) combines them. Methods, highest precision first:

### M1 — Curated company_id → industry crosswalk *(backbone, P≈1.0)*
Hand-curated/reviewed industry for the **head company_ids** (start with top
~10–25k → ~30–36% of all rows). This is the ratchet table, analogous to
`ENTITY_ALIASES` in `approach_a_rules`. Resolves to **L4** for known firms.

### M2 — Bootstrapped company → industry from public data *(P high, propose→curate)*
Seed M1 at scale by joining company **name/id** against open sources that already
carry industry: Wikidata/Wikipedia infobox `industry`, NAICS business registries,
SEC/EDGAR SIC for public firms, open company datasets. Match on the cleaned name
(reuse `career_clean` normalization + the name→id crosswalk). High-confidence
joins auto-populate M1; ambiguous ones go to the review queue. This is how the
head table gets built without hand-labeling 25k firms from zero.

### M3 — Company-name lexical rules *(P high on self-describing names; covers the no-id tail)*
Many company names *are* their industry. Deterministic token rules resolve a
large share of the 2.1M no-id tail, typically to **L2/L3**:

| name pattern | → industry |
|---|---|
| `* Bank`, `Credit Union`, `Capital`, `Financial` | Finance |
| `* Hospital`, `Health`, `Clinic`, `Medical`, `Care` | Healthcare |
| `* University`, `College`, `School`, `ISD`, `Academy` | Education |
| `* Realty`, `Properties`, `Real Estate` | Real Estate |
| `City of *`, `County`, `Department of *`, `US Army/Navy/...` | Public Sector |
| `* Consulting`, `Advisors`, `Partners LLP` | Professional Services |
| `* Restaurant`, `Grill`, `Cafe`, `Catering` | Food & Hospitality |
| `* Construction`, `Builders`, `Contractors` | Construction |

Precision-first: only fire on **unambiguous** tokens (same discipline as the
O\*NET coder — drop tokens that map to multiple sectors). Curated + extensible.

### M4 — Self-employment → occupation-derived industry *(ties to SELF_EMPLOYED_PLAN)*
For `employment_type ∈ {self_employed, business_owner, …}` the org line is
status, not an employer, so industry must come from the **occupation/title**: a
freelance graphic designer → Media/Creative Services; an independent nurse →
Healthcare. Use the title's SOC code (M5) as the primary signal for these rows.

### M5 — Occupation (SOC) → industry prior *(probabilistic, propose-only)*
BLS/O\*NET publish **occupation × industry staffing matrices**. Map the row's SOC
(from `career_clean/occupation.py`) to a *distribution* over industries: a
"Petroleum Engineer" is ~Energy; a "Registered Nurse" is ~Healthcare. Use as a
**weak prior / tiebreaker only** — a "Software Engineer" or "Accountant" or
"Project Manager" is industry-agnostic, so this never decides alone. Resolves L1/L2
at best, with calibrated confidence from the staffing share.

### M6 — LLM / free-text inference on description / `about` *(propose-only; see §3.9)*
For the residual with no id, no self-describing name, and an ambiguous
occupation, the industry signal is **latent in unstructured text** — most acutely
for self-employed profiles, where there is no real employer and the only clue is
the description ("I design brand identities for restaurants") or the `about`
section. No deterministic method can reach this by construction. An LLM (or a
cheaper zero-shot/embedding classifier) reads the **title + description + `about`
+ skills** together and emits a schema path. It is **propose-only, review-queue,
never autonomous** — the FINDINGS embedding-precision argument applies and is in
fact *sharper* for LLMs (§3.9). It is the only method that handles the
multilingual and idiosyncratic tail. Because of its cost, precision, and
reproducibility tradeoffs, M6 has its own design section below and is
**sequenced last**.

### M7 — Education field (CIP) — weak person-level prior *(last resort)*
A profile's field of study weakly hints at industry (Nursing → Healthcare). Only
a final tiebreaker, person-level not step-level, lowest confidence.

### 3.8 — Fusion / arbitration (the interesting part)
The hierarchical schema and multi-method evidence fit together through **depth**:
different methods justify different depths, so the classifier emits the **deepest
node all corroborating evidence agrees on**, with **per-level confidence**:

```
resolve(company/row):
  collect candidates from M1..M7 (each a path + depth + confidence)
  if a high-precision method (M1/M2/M3) fires -> take its path as the spine
  walk L1->L4: at each level, accept the label if the spine asserts it OR
     the weak priors (M5/M7) agree above threshold; stop descending when
     evidence runs out -> emit a PARTIAL path (e.g. confident L1=Finance,
     L2=Banking, but L3/L4 unknown)
  disagreement between high-precision methods -> review queue
  nothing fires -> Other/Unknown at L1, queue for M6/curation
```

So the output is not "one of 700 leaves" but **a path truncated at the depth the
evidence supports**, with a confidence per level. The UI can then draw flows at
L1 (everyone classified) or drill to L4 (only the well-evidenced subset) — which
is exactly what an interactive multi-level explorer wants. The low-confidence /
shallow / disagreeing cases feed the same review-queue ratchet, so coverage and
depth **increase over time without sacrificing precision**.

### 3.9 — The LLM layer (M6): when, where, and how to use it

An LLM is the only method that reads industry signal **latent in unstructured
text**, so it is uniquely suited to the hardest residual — above all
**self-employed profiles, where industry lives only in the description/`about`,
not in any structured field**. But it cuts against this repo's deterministic,
precision-first, reproducible-pipeline contract, so its role must be tightly
bounded. The recommendation: **do not make the LLM an autonomous classifier; use
it in two disciplined modes, and sequence it last.**

**What it would actually target (measured).** The LLM only earns its cost on the
text-bearing residual the deterministic backbone (M1–M5) cannot reach:

- **Self-employed rows: ~123K, but only 47% (~58K) carry a description**
  (avg ~357 chars ≈ 90 tokens, median 253). The other **53% have only a title** —
  which the SOC/occupation method (M4/M5) already handles better and cheaper, so
  the LLM's incremental value here is bounded to the ~58K text-bearing rows.
- **No-id company tail: 2.1M distinct names, ~1.24M with description text** on
  some row — the large target, exactly where crosswalks (M1/M2) structurally
  can't reach and name rules (M3) only catch self-describing names.

Resolve at the **distinct grain** (per company, per unique description), never
per row — that is the difference between millions of calls and a tractable job.

**Pros (specific to this data).**

- *Only method that reads latent signal.* The self-employed case is the poster
  child; deterministic methods cannot reach "I design brand identities for
  restaurants." Same for the 1.24M description-bearing tail companies.
- *Synthesis across fields* — combines title + description + `about` + skills into
  one judgment (what a human reviewer does) and can emit the 4-level path **with a
  rationale**, which is auditable, unlike an embedding's cosine score.
- *Multilingual for free*, where O\*NET/NAICS lexicons are English-only.
- *Context disambiguation* embeddings miss: "Owner @ Smith Plumbing" vs "Owner @
  Smith Capital."
- *Highest-ROI use is as a bootstrap curator, not a hot-path classifier* — pointing
  it at the **head** company table (tens of thousands of ids → 30–40% of all rows)
  to propose industries for human spot-check collapses the cost of building the
  precision-≈1.0 M1/M2 backbone.

**Cons (and they map onto this repo's known ML failure modes).**

- *Violates the house thesis if put in the hot path.* It will confidently assign
  an industry from thin signal (bare "Consultant"/"Owner", buzzword descriptions)
  wrapped in convincing reasoning, so errors are **harder to detect** than a low
  cosine. Cannot be autonomous ground truth.
- *Non-determinism breaks reproducibility* — outputs drift across model versions
  and runs, while the rest of the pipeline is deterministic and re-runnable
  (`normalization_regression_checks.py`). Requires a **frozen result cache + a
  deterministic fallback** so the pipeline runs without it.
- *Uncalibrated confidence* — an LLM "0.9" ≠ 90% accuracy; needs an external gold
  set to map self-reported confidence onto real precision bands before any band is
  trusted.
- *Manufactured coverage* — much residual text is mission statements / buzzwords /
  not-about-industry; the LLM still emits a label, creating false coverage that
  looks like progress.
- *Cost is real but not prohibitive if scoped right* — at distinct grain with
  short inputs (median ~65 tokens), batch API, and a small model, ~2–3M items is
  plausibly low-hundreds-to-low-thousands of dollars **one-time**, but it
  **recurs on every schema change**, and naive per-row calling 3–4×'s it for
  nothing.
- *Governance* — sending individual profile text (PII from a scraped dataset) to
  an external API has ToS/privacy implications; a local open model fixes that but
  adds infra.

**Recommended role — two bounded modes, never the autonomous hot path:**

1. **Bootstrap curator for the head (feeds M1/M2).** LLM proposes industries for
   the head company table; humans spot-check. Bounded population (tens of
   thousands), one-time, high leverage on the precision-1.0 backbone.
2. **Tail proposer into the review queue (M6 proper).** Only on the residual where
   description text exists *and* deterministic methods abstain, emit
   `(path, depth, confidence, rationale)` as **candidates** — capped to the depth
   the evidence supports (prefer L1/L2 over guessing L4), gated by the calibration
   set. These are review-queue items, not truth.

**Sequence it last (after M1–M5)** so the LLM is paid only for the genuinely-hard
text-bearing residual, against a deterministic baseline that measures its lift and
serves as the reproducible fallback. Cache by distinct value, use the batch API,
a small model, and short prompts; keep a frozen cache so a pipeline re-run never
re-hits the API unless inputs or schema change.

---

## 4. Expected coverage (order-of-magnitude, to be measured)

| method | grain | est. row reach | precision | typical depth |
|---|---|---|---|---|
| M1 curated id head | company_id | ~30–40% | ≈1.0 | L4 |
| M2 bootstrap join | company_id/name | extends M1 toward 60%+ | high | L3–L4 |
| M3 name rules | no-id names | large share of the 2.1M-name tail | high (guarded) | L2–L3 |
| M4+M5 self-emp/occupation | title/SOC | the self-employed + agnostic tail | medium | L1–L2 |
| M6 LLM/text | description/about | ~58K text-bearing self-emp rows + ~1.24M no-id tail companies | review-only | varies |

Backbone (M1–M3) plausibly puts a **majority of rows on at least an L1–L2
industry at high precision**; depth and the tail are the curation/ML problem,
exactly as with occupation coverage in FINDINGS. M6's reachable population is the
**text-bearing** residual only (the 53% of self-employed rows with no description
fall to M4/M5, not M6).

---

## 5. Evaluation

Mirror the existing harness:

- **Gold set** of `company → industry_path` and a few `(row, expected L1/L2)`
  labels, stressing hard cases: conglomerates (Amazon = retail vs cloud vs
  media?), staffing/temp agencies (industry of the agency vs the client?),
  holding companies, universities-with-hospitals, gov vs gov-contractor,
  self-employed craft → industry.
- **Metrics:** per-level **precision/recall** (you can be right at L1 but wrong at
  L4 — report each level), **coverage at each depth** (% of rows with an L1 / L2 /
  L3 / L4 assignment), and the **review-queue size**. Report precision *per
  method* so M5/M6 stay propose-only until they earn trust.
- **LLM calibration (M6).** A dedicated labeled set mapping the LLM's
  self-reported confidence onto observed precision, so confidence bands can gate
  auto-accept vs. review. Also measure M6's **incremental lift over the M1–M5
  baseline** on the text-bearing residual — if the deterministic stack already
  resolves a case, M6 must not be paid for it.

---

## 6. Phased build

1. **Schema + crosswalk asset.** Freeze the 4-level node list with codes, labels,
   and the NAICS (and LinkedIn-industry) crosswalk. Pick the L1 macro buckets.
2. **M1+propagation.** Curated head table + company_id→row join. Ship the backbone.
3. **M2 bootstrap.** Public-data join to scale the head table into the review queue.
4. **M3 name rules.** Tail coverage on self-describing names.
5. **M4+M5.** Wire SOC→industry prior; route self-employed rows through occupation.
6. **Fusion + confidence + per-level coverage metric.** The arbitration layer (§3.8).
7. **LLM bootstrap curator** (§3.9 mode 1) — propose head-table industries for
   human spot-check, accelerating M1/M2. Optional but high-ROI; bounded, one-time.
8. **M6 LLM tail proposer** (§3.9 mode 2) — *last*, on the text-bearing residual
   only, propose-only into the review queue, behind a frozen cache + calibration
   set, with a deterministic fallback. Build only after M1–M5 set the baseline.
9. **Review-queue ratchet** feeding M1, same mechanism as company aliases.

Critical path to a usable axis: **steps 1–4** (schema + curated/bootstrapped head
+ name rules) already classify a majority of rows to L1/L2 deterministically. The
LLM (7–8) is a coverage/depth extender for the hard tail, **not** on the critical
path and **never** an autonomous classifier.

---

## 7. Open decisions

1. **Backbone standard** — custom-over-NAICS (recommended, US-heavy) vs
   ISIC/NACE (if multilingual/global) vs GICS (if finance-centric)?
2. **L1 macro buckets** — confirm the ~10–12 top-level list and where the
   ambiguous giants go (public sector vs gov contractors; nonprofit as L1 vs flag).
3. **Conglomerate / time-varying industry** — single stable industry per company
   (v1) vs per-segment or per-era? How to treat Amazon-type diversified firms.
4. **Staffing/PEO/holding companies** — classify as their own industry, or
   pass-through to the worksite industry (usually unknowable)?
5. **Self-employed industry source** — occupation-derived only (M4/M5), or also
   mine the description via the LLM (M6) for the ~58K text-bearing rows? (links to
   `SELF_EMPLOYED_PLAN.md`).
6. **Bootstrap sources** — which open datasets are lic-clean to ingest (Wikidata
   is permissive; others vary).
7. **Minimum depth to render** — does the default flow view bind to L1, L2, or the
   deepest-confident level per node?
8. **Is the LLM in scope at all for v1?** — the deterministic stack (M1–M5) may
   give enough coverage that M6 is deferred. Decide the trigger: build M6 only if
   measured residual coverage falls below target after M1–M5.
9. **LLM hosting & governance** — external batch API (cheaper, simpler) vs. a
   local open model (no PII leaves the environment, more infra), given the data is
   scraped profile text. Drives the cost and ToS/privacy posture of §3.9.
10. **LLM auto-accept policy** — do high-confidence, calibrated M6 proposals ever
    auto-apply, or is M6 *always* human-gated through the review queue? (Default:
    always gated until the calibration set proves a trustworthy band.)
