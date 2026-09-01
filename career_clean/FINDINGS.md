# Career field cleaning: three approaches, benchmarked + a hybrid

Goal: canonicalize the three career fields — **organization** (`company`),
**position title** (`title`), and **description** — maximizing how often we
recognize *the same value* (AT&T / AT&T Mobility, "Sr. Software Engineer" /
"Senior Software Engineer") while keeping *distinct values* apart (Citizens Bank
vs First Citizens Bank, "Software Engineer" vs "Senior Software Engineer").
Title additionally carries an **occupation** axis (O*NET-SOC) so semantic job
families ("Software Engineer" ≈ "Software Developer") group even though their
literal canonicals stay distinct.

Built, run, and measured on the parsed `experience` (9.08M) + `positions`
(2.79M) tables. This is the career counterpart of `edu_clean/`; it deliberately
reuses that effort's conventions and conclusions (see "Priors"). The data
profile and the three strategic plans live in `../PLAN.md`; this document is the
*built and measured* version.

## How to reproduce

```bash
# benchmark A, B, C per field (GPU for C); writes results/<field>.json
uv run python -m career_clean.run_eval all
uv run python -m career_clean.run_eval company --no-embed   # CPU only

# benchmark the occupation (O*NET-SOC) backstop on the title vocab
uv run python -m career_clean.run_occupation

# build + measure the production hybrid on the FULL vocab; writes final_compare.json
uv run python -m career_clean.run_final_compare
```

Code layout (`career_clean/`): `common.py` (vocab export incl. the modal
`company_id`, normalization, metrics), `gold.py` (labeled same/distinct pairs),
`approach_a_rules.py`, `approach_b_fuzzy.py`, `approach_c_embed.py`,
`occupation.py` (O*NET-SOC backstop), `final_hybrid.py`, runners, `results/*.json`.
Reference data: `reference/onet_alternate_titles.txt` (O*NET-SOC 29.1, ~55k
title→code), `reference/onet_occupation_data.txt`. Data-model and profiling live
in `exploration/career_explore.py`.

## Audit hardening update — 2026-06-03

The production path now incorporates the follow-up audit fixes:

- Latin diacritics are folded before ASCII matching, and technology tokens such
  as `C++`, `C#`, `F#`, and `R&D` are protected before punctuation stripping.
  This keeps `C++ Developer`, `C# Developer`, and `C Developer` distinct while
  allowing `R&D Engineer` to align with `Research and Development Engineer`.
- Company canonicalization now exposes a row-level helper that can use the
  actual row `company_id` instead of only the modal id attached to a distinct
  company value. Placeholder buckets still win before ids.
- `PM` is no longer expanded to `Project Manager`; it remains literal because it
  is ambiguous across project/product/program manager.
- The deterministic O*NET index now adds parenthetical-stripped and simple
  singular variants while still dropping keys that map to multiple SOCs. This
  raises full-vocabulary SOC row coverage from 19.6% to 21.9% and fixes common
  misses such as `Registered Nurse` and `Chief Executive Officer`.
- `normalization_regression_checks.py` covers these high-value edge cases.

## The data-model fact everything rests on

LinkedIn uses a grouped-position model. For a **single-role** experience,
`experience.title` is the job title; for a **multi-role** experience (one with
`positions` children) `experience.title` is the **company name** (verified 100%)
and the real titles live in `positions.title`. So the clean job-title vocabulary
is `single-role experience.title` ∪ `positions.title` (~10.8M instances). This is
encoded once in `common.JOB_TITLES`; ignoring it mislabels 1.06M rows.

## Benchmark method

Canonicalization operates on the **distinct values** of a field (weighted by
frequency); each approach emits a `value -> canonical_id` map. We measure:

- **Same-vs-distinct quality** on a hand-labeled gold set of `(a, b, merge?)`
  pairs drawn from observed values, stressing the hard boundary: pairwise
  **precision / recall / F1** of the "should-merge" decision.
- **Reduction** = `1 - n_canonical/n_distinct`.
- **Reference coverage** = share of rows mapped to a known reference key
  (`company_id` for organization; a parsed `title:level|base` for title).
- **Runtime** and (for C) GPU footprint.

Because `company` and `title` each have **millions** of distinct values and the
GPU cluster method is O(n²), the head-to-head (`run_eval`) runs all approaches on
a frequency-capped vocab (top 200k + every gold endpoint); the CPU hybrid
(`run_final_compare`) then runs on the **full** vocabulary.

## Calibration (why no single method can win)

| pair | relationship | what catches it |
|---|---|---|
| AT&T / AT&T Mobility | **same** (sub-brand) | only `company_id` |
| EY / Ernst & Young | **same** (acronym) | only `company_id` (lexical & embeddings miss) |
| Self-employed / Self Employed | **same** (placeholder) | only the placeholder dictionary (their ids are *noise*) |
| Citizens Bank / First Citizens Bank | **distinct** | `company_id`; embeddings **merge** them (cosine high) |
| "Sr. Software Engineer" / "Senior Software Engineer" | **same** (abbrev) | rule expansion (lexical & embeddings miss) |
| "Software Engineer" / "Senior Software Engineer" | **distinct** (level) | the level signature; embeddings **merge** them |

The in-data `company_id` is the single strongest signal and behaves like
education's school slug. Placeholder `company_id`s are garbage ("Self-employed" →
id `conscience-vc`; "Self Employed" → `indpendent-contractor`), so placeholders
**must be bucketed before** any id lookup.

## Results

### company — the in-data `company_id` key wins outright

(eval vocab: top-200k + gold, 5.24M rows)

| approach | reduction | P | R | F1 | runtime | note |
|---|---|---|---|---|---|---|
| **A rules (id + placeholder)** | 0.15 | **1.00** | **1.00** | **1.00** | 0.6s | **88.4% id coverage** |
| B fuzzy | 0.05 | 1.00 | 0.39 | 0.56 | 0.8s | cannot expand acronyms / sub-brands |
| C embed @0.88 | 0.14 | 0.90 | 0.69 | 0.78 | 12s | **false-merges Citizens Bank ⇔ First Citizens Bank** |
| C embed @0.92 | 0.08 | 1.00 | 0.54 | 0.70 | 8s | misses every acronym/sub-brand |
| C anchored @0.80 | 0.20 | 1.00 | 0.85 | 0.92 | 14s | 95.9% id coverage; misses only placeholders |

The id key collapses spellings, acronyms (EY → `ernstandyoung`), and sub-brands
(AT&T Mobility → `att`) and keeps siblings apart — none of which lexical or
embedding methods do. Embeddings are blind to acronyms and **over-merge sibling
banks** (the "Boston University ⇔ Boston College" failure from education,
reproduced exactly). The **anchored** variant (trust the id, embed only the
no-id tail) is the one useful embedding mode — it just can't bucket placeholders,
which is the rule layer's job. So `A` already wins, and `anchored` only adds
tail recall behind the same id key.

### title — the seniority/role rule parser wins; embeddings are catastrophic

(eval vocab: top-200k + gold, 7.24M rows)

| approach | reduction | P | R | F1 | runtime | note |
|---|---|---|---|---|---|---|
| **A rules (level \| base)** | 0.27 | **1.00** | 0.89 | **0.94** | 0.4s | 97.8% parsed; only miss "Co-Founder"/"Cofounder" |
| B fuzzy | 0.24 | 1.00 | 0.33 | 0.50 | 0.8s | cannot expand Sr→Senior, VP, CEO, RN |
| C embed @0.88 | 0.68 | **0.40** | 0.67 | 0.50 | 13s | **9 false-merges** (see below) |
| C embed @0.92 | 0.44 | 0.83 | 0.56 | 0.67 | 8s | still merges Founder ⇔ Co-Founder |

Title decomposes into a **(seniority level, base role)** pair — the level axis is
education's "degree level" all over again. The rule parser expands abbreviations
(Sr→Senior, VP→Vice President, CEO→Chief Executive Officer, RN→Registered Nurse),
pulls level/roman-numeral markers into a sorted signature, and canonicalizes on
the base, so "Sr. Software Engineer" == "Senior Software Engineer" but ≠ "Software
Engineer". Embeddings at 0.88 fused **Software Engineer ⇔ Senior Software
Engineer**, **Project Manager ⇔ Product Manager**, **Account Manager ⇔ Account
Executive**, **Owner ⇔ Founder**, **Registered Nurse ⇔ Nurse Practitioner** — the
exact seniority/role distinctions that matter. Embeddings have **no usable margin**
on this boundary; they are unsafe as an autonomous merger.

### occupation — the O*NET-SOC backstop (a separate axis on titles)

The literal title parser keeps "Software Engineer" and "Software Developer"
distinct (different base tokens), yet they are the *same occupation*. The
occupation axis maps a title to an O*NET-SOC family code via the ~55k-entry
alternate-title lexicon — the title analogue of education's CIP, and it behaves
the same way. (eval vocab: top-200k titles + gold, 7.24M rows; 8 gold pairs)

| approach | reduction | SOC coverage | P | R | F1 | runtime |
|---|---|---|---|---|---|---|
| **A O\*NET (exact/token/de-leveled)** | 0.22 | 31.6% | **1.00** | **1.00** | **1.00** | 4s |
| C anchored @0.70 | 0.84 | **92.6%** | 1.00 | 1.00 | 1.00 | 26s |
| C anchored @0.80 | 0.55 | 75.1% | 1.00 | 0.75 | 0.86 | 21s |

Exactly the education CIP story: the deterministic lexicon is a **precision-1.0
backbone with modest coverage** (31.6% of head rows / **21.9% of the full title
vocab** get a code after alias expansion; generic cross-cutting titles like
"Project Manager", "Account Manager", "Consultant" map to many SOCs and are
correctly left uncoded), and the **anchored embedding extends coverage to 92%**
as a propose-only layer.
The P=1.0 for the embedding here is on only 8 gold pairs — education's larger
anchored-CIP set landed at P≈0.80, so treat anchored SOC as review-queue
candidates, not autonomous truth. De-leveling lets "Senior Software Engineer"
find "Software Engineer" → 15-1252, so occupation groups across seniority while
the literal axis keeps seniorities apart.

### description — not an entity-resolution field

`description` is ~unique free text (4.10M distinct of 4.17M), present on **45.9%**
of experience rows, and already HTML-stripped (the parser keeps markup in
`description_html`). "Cleaning" = **normalization only**: NFKC, control-char
strip, whitespace collapse — which changed **35.3%** of a 200k sample (mostly
unicode/whitespace and multilingual content; 31.7% is non-ASCII). There is no
same-vs-distinct target here, so no gold/coverage metric applies.

## Per-approach tradeoffs

- **A — rules + in-data key.** Highest precision (1.0 on both fields), fastest
  (<1s, CPU), fully auditable. Wins outright: `company_id` for organization,
  the seniority/role parser for title. Weakness: 38% of org rows carry no id
  (the tail), and the parser misses one compaction case ("Cofounder").
- **B — guarded fuzzy.** Precision 1.0, adds typo/spacing tolerance on the tail,
  but **cannot expand acronyms or sub-brands** (recall 0.39 company / 0.33 title)
  — it is a tail tool, not a primary.
- **C — embeddings (GPU).** Reproduces every education failure: blind to
  acronyms/typos, over-merges sibling organizations and adjacent seniorities
  (title precision 0.40 @0.88). The only safe use is the **anchored** mode behind
  the id key, as a *candidate generator for review* — never an autonomous merger.

## The hybrid (production), measured on the FULL vocabulary

Precedence — highest-precision layer that fires decides:

```
company:    placeholder bucket -> company_id (+ rebrand alias) -> name->id
            crosswalk -> guarded typo tail (to an id if possible) -> raw
title:      seniority/role parse (level | compact base) -> guarded typo tail -> raw
occupation: O*NET-SOC exact/token/de-leveled -> uncoded   (separate axis on titles)
description: normalize only (NFKC, control-char strip, whitespace)
```

A cleaned title therefore carries three orthogonal outputs: `seniority_level`,
`role_canonical` (literal), and `occupation_code` (SOC family).

| field | values → canonical | reduction | P | R | F1 | reference coverage | runtime |
|---|---|---|---|---|---|---|---|
| **company** | 3,396,043 → 2,974,747 | 0.124 | **1.00** | **1.00** | **1.00** | **69.7% on a company_id** | 64s |
| **title** | 3,507,500 → 2,916,756 | 0.168 | **1.00** | **1.00** | **1.00** | **98.5% parsed** | 69s |
| **occupation** | 3,507,500 → 3,180,449 | 0.093 | **1.00** | **1.00** | **1.00** | **21.9% on a SOC code** | 90s |

Method breakdown by row %:

- **company**: `company_id` 68.0, raw (no-id tail) 27.6, placeholder 1.7,
  name_crosswalk 1.2, typo 1.0, typo_to_id 0.5.
- **title**: `title_base` 67.9, `title_leveled` 30.5, raw 1.5, typo ~0.
- **occupation**: `onet_exact` 17.6, de-leveled 1.7, de-leveled-token 1.7,
  token 1.0, uncoded 78.1.

The hybrid keeps all three at gold **F1 1.0 on the full data** while compaction
in the title base key closes A's lone "Cofounder" miss. The combined sample shows
the axes working together — "Software Engineer", "Senior Software Engineer", and
"Sr. Software Engineer" get **distinct literal canonicals** (seniority kept) but
the **same `soc:15-1252`** (occupation grouped). Every value carries a `method`
and `confidence`, so the low-confidence bands — the ≈28% no-id company tail and
the ≈80% uncoded occupation tail — feed a human review queue (the anchored
embedding pass populates the SOC candidates at 92% coverage).

## Priors carried over from education (confirmed here)

- **An in-data reference key beats everything** — slug there, `company_id` here
  (F1 1.0). 
- **Lexical/fuzzy owns typos but can't expand abbreviations** — confirmed
  (B recall 0.33–0.39).
- **Embeddings are a poor autonomous merger** — sibling-org and seniority
  over-merges reproduced precisely (title P 0.40). Value only as a guarded,
  anchored candidate generator.
- **Coverage to ~100% comes from curation + a review queue, not a bigger model.**

## Recommended production approach

1. **Restructure & normalize once:** build `JOB_TITLES`, drop `experience.subtitle`
   (100% null), NFKC/case/`&`→and/punctuation, parse dates, run the placeholder
   dictionary → `NON_ORG` status.
2. **Backbone (precision 1.0, CPU, ~seconds):** `company_id` (+ name→id crosswalk)
   for organization; the seniority/role parser for title. This *is* the whole
   story for the head — F1 1.0 on both.
3. **Typo tail (B):** guarded equal-cardinality matching on the residual no-id /
   unparsed tail.
4. **Coverage beyond the backbone (curation-first):** the org tail (≈28% of rows
   with no id) is closed by **curated name→id aliases** fed from a review queue,
   not a model. Production row-level application should pass the actual
   `company_id` when present; the modal value-level id is only a benchmark/cache
   convenience. Optionally run the **anchored** embedding pass
   (`run_anchored_company`) purely to *propose* tail→id matches into that queue
   with a `confidence`.
5. **Occupation axis (built):** O*NET-SOC via the alternate-title lexicon gives
   job-family grouping (Software Engineer ≈ Software Developer) on a separate
   axis from the literal title and seniority. Deterministic = precision-1.0
   backbone (21.9% of rows coded after alias expansion); the guarded
   anchored-embedding pass
   (`run_anchored_occupation`) proposes the rest (92% coverage) into the review
   queue. Higher *deterministic* coverage is a curation problem (curated
   profile-title aliases and family decisions), not a model problem.

Net: immediate **F1 1.0** on organization, title, and occupation from the
backbone — ~70% of org rows on a stable `company_id`, ~98% of title rows on a
structured key, 21.9% of title rows on a precise SOC code (92% via the review
queue) — with a curation-driven path (not a model-driven one) to higher coverage.

## Limitations / next steps

- Gold is modest (23 company + 18 title + 8 occupation pairs) and targets
  known-hard cases; a larger labeled set (or active-learning from the typo/raw/
  uncoded bands) would tighten estimates — most urgently for the occupation
  anchored-embedding precision, where 8 pairs is too few to trust P=1.0.
- **Rebrand policy: handled via a curated cross-id alias table.**
  `company_id` already merges acquired sub-brands that LinkedIn folds into one id
  (BellSouth → `att`), but keeps separate ids where LinkedIn does (Facebook vs
  Meta, Alphabet vs Google). `approach_a.ENTITY_ALIASES` resolves these rebrands
  onto the family's dominant id (`facebook`/`metafacebook` → `meta`,
  `alphabet-inc` → `google`); it is intentionally limited to *rebrands*, not
  distinct product brands (Instagram, WhatsApp, YouTube, DeepMind stay separate —
  rolling subsidiaries up to a parent is a separate unit-of-analysis choice).
  Extend the table from the review queue as more equivalences are confirmed.
- **Occupation coverage and consistency** are curation-bound. O*NET is
  US/English, so multilingual titles (~0.5%) go uncoded; deterministic coverage
  on the full vocab is 21.9% because generic titles are (correctly) ambiguous and
  many common profile phrases are absent from the reference. Parenthetical
  stripping and final-word singularization now recover examples like "Registered
  Nurse" and "Chief Executive Officer"; further gains should come from curated
  aliases and reviewed proposals. **ESCO** (multilingual, ISCO-linked) is the
  alternative reference if the non-English tail matters.
- The embedding layer used `all-MiniLM-L6-v2`; per the education encoder study a
  larger model buys little here and never fixes the precision problem, so it
  stays out of the default path.
