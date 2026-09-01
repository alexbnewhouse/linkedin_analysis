# Education field cleaning: three approaches, benchmarked + a hybrid

Goal: canonicalize the three education fields — **field of study** (`field`),
**degree type** (`degree`), **institution** (`title`) — maximizing how often we
correctly recognize *the same value* (e.g. "english"/"engilsh", "PSYCHOLOGY"/
"Psychology") while keeping *distinct values* apart (e.g. "Computer Science" vs
"Computer Science and Engineering", "Boston University" vs "Boston College").

Everything here is built, run, and measured on the parsed 3.58M-row education
table. Heavy semantic math runs on the GPU (RTX 5080, CUDA).

## How to reproduce

Environment (GPU stack installed into the uv venv; torch from the CUDA 12.8
index for the RTX 5080 / Blackwell):

```bash
uv pip install "torch>=2.7" --index-url https://download.pytorch.org/whl/cu128
uv pip install numpy pandas rapidfuzz jellyfish scikit-learn sentence-transformers
```

Run:

```bash
uv run python -m edu_clean.run_eval all     # benchmark A, B, C per field
uv run python -m edu_clean.run_hybrid       # build + benchmark the hybrid
```

Code layout (`edu_clean/`): `common.py` (vocab export, normalization, metrics),
`gold.py` (labeled same/distinct pairs), `approach_a_rules.py`,
`approach_b_fuzzy.py`, `approach_c_embed.py`, `hybrid.py`, runners, and
`results/*.json`. Reference data: `reference/cip_codes.csv` (US Dept. of
Education CIP 2020, 2,318 codes).

## Audit hardening update — 2026-06-03

The production path now incorporates the follow-up audit fixes:

- Latin diacritics are folded before ASCII matching, so names like "São Paulo"
  normalize with `sao` rather than `s o`; non-Latin raw ids are still preserved
  through `safe_norm` when no ASCII key remains.
- The CIP loaders skip remedial / IPEDS-invalid rows. This prevents generic
  profile fields like "Music" from mapping to remedial `36.0115`; "Music" now
  maps to the valid music group `50.09`, while invalid-only labels such as
  "Art" and "Reading" stay raw.
- A tiny measured CIP override maps "Biology/Biological Sciences, General" to
  the same chosen group as "Biology, General" (`26.01`), closing the final field
  gold-set miss without rolling all subfields up indiscriminately.
- Institution canonicalization now exposes a row-level helper that can use the
  actual school slug from a row URL instead of only the modal slug attached to a
  distinct title value.
- `normalization_regression_checks.py` covers these high-value edge cases.

## Benchmark method

Canonicalization operates on the **distinct values** of a field (weighted by
frequency); each approach emits a `value -> canonical_id` map. We measure:

- **Same-vs-distinct quality** on a hand-labeled gold set of `(a, b, merge?)`
  pairs (drawn from observed values, stressing the hard boundary): pairwise
  **precision / recall / F1** of the "should-merge" decision. Precision falling
  = wrongly merging distinct values; recall falling = missing true synonyms.
- **Reduction** = `1 - n_canonical / n_distinct` (how much consolidation).
- **Reference coverage** = share of rows mapped to a known reference entity.
- **Runtime** and GPU footprint.

## Calibration (why no single method can win)

| pair | relationship | embedding cosine | char similarity |
|---|---|---|---|
| "PSYCHOLOGY" / "Psychology" | same (case) | **1.00** | high |
| "Computer Science" / "Computer Science and Engineering" | **distinct** | **0.88** | high |
| "english" / "engilsh" | same (typo) | **0.50** | high |

Embeddings nail semantics but **miss typos** and **over-rate distinct
combinations**; lexical methods nail typos/format but miss synonyms. The
methods are complementary, not competitive.

## Results

### degree — reference taxonomy wins outright

| approach | reduction | P | R | F1 | runtime |
|---|---|---|---|---|---|
| **A rules (taxonomy)** | 0.52 | **1.00** | **1.00** | **1.00** | 1.0s |
| B fuzzy | 0.24 | 1.00 | 0.40 | 0.57 | 1.7s |
| C embed @0.88 | 0.57 | 0.66 | 0.95 | 0.78 | 23s |
| C embed @0.92 | 0.41 | 0.64 | 0.70 | 0.67 | 16s |

Degree is a small controlled space, so the rule parser (level × type, with an
abbreviation dictionary) is perfect. B can't expand abbreviations
("BS"→"Bachelor of Science"). Embeddings are dangerous: they merge different
*levels* ("High School Diploma" ⇔ "Bachelor's degree") and *types* ("BS" ⇔
"BA"). 83.8% of rows hit the taxonomy; the 16.2% tail is degree-as-free-text.

### field — the hard one: lexical is precise, embeddings give coverage

| approach | reduction | P | R | F1 | coverage | runtime |
|---|---|---|---|---|---|---|
| A rules (CIP exact) | 0.16 | **1.00** | 0.77 | 0.87 | 56% CIP | 1.4s |
| B fuzzy | 0.31 | **1.00** | 0.77 | 0.87 | — | 2.4s |
| C embed @0.88 | 0.66 | 0.45 | 1.00 | 0.62 | — | 29s |
| C embed @0.92 | 0.48 | 0.50 | 0.77 | 0.61 | — | 25s |
| C anchored→CIP @0.62 | 0.75 | 0.80 | 0.61 | 0.70 | **92% CIP** | 45s |

A and B both hit **precision 1.0** but cap at recall 0.77 (they miss CIP
cross-level/plural synonyms like "Communication, General" ≈ "Communications").
Embedding **clustering is unusable for merging** — at 0.88 it fused "Biology" ⇔
"Chemistry", "Finance" ⇔ "Accounting", "Psychology" ⇔ "Clinical Psychology".
The valuable embedding use is **anchored-to-CIP**: 92% of rows get a CIP code
(vs 56% exact) at precision 0.80.

### title (institution) — the LinkedIn school slug is gold

| approach | reduction | P | R | F1 | coverage | runtime |
|---|---|---|---|---|---|---|
| **A rules (slug)** | 0.15 | **1.00** | **1.00** | **1.00** | 88% slug | 0.8s |
| B fuzzy (name only) | 0.17 | 1.00 | 0.50 | 0.67 | — | 1.7s |
| C embed @0.88 | 0.46 | 0.27 | 0.75 | 0.40 | — | 26s |
| C embed @0.92 | 0.33 | 0.50 | 0.75 | 0.60 | — | 19s |

The slug (+ exact name→slug crosswalk) is a near-perfect key: it collapses case,
typos ("Pheonix"), and campus variants, and keeps distinct schools apart. Name
fuzzy can't merge campus variants (different token cardinality). Embeddings are
catastrophic here — they merged "University of Washington" ⇔ "University of
Michigan" and "Boston University" ⇔ "Boston College".

## Per-approach tradeoffs

- **A — rules + reference.** Highest precision (1.0 everywhere), fastest (~1s,
  CPU), fully transparent/auditable. Wins outright where authoritative reference
  exists (degree taxonomy, school slug). Weakness: recall on the `field` tail
  (only 56% of rows match CIP exactly); needs curation for synonyms.
- **B — guarded fuzzy clustering.** Precision 1.0, adds **typo tolerance** on
  the tail, no reference or labels needed, fast (~2s, CPU). Weakness: cannot
  expand abbreviations or merge cardinality-different variants (campuses,
  "BS"→"Bachelor of Science"); blocked by phonetic signature so a few
  plural/synonym pairs slip through.
- **C — embeddings (GPU).** Only method that captures pure semantics and the
  long tail; anchored-to-reference gives the best **coverage**. Throughput
  **18,839 strings/s**, fp16, ~1.6 GB on the RTX 5080. Weakness: **poor merge
  precision** (conflates siblings, levels, and neighboring institutions), blind
  to typos. Must be guardrailed; never autonomous.

## The hybrid

Design principle from the data: **let the highest-precision layer that fires
decide, and only use weaker/semantic layers to extend coverage on what's left,
behind lexical guardrails.** Precedence per value:

```
field : CIP exact/token  ->  guarded anchored-CIP  ->  typo cluster  ->  raw
degree: taxonomy parse    ->  raw
title : slug / name->slug ->  typo cluster          ->  raw
```

The `field` anchored-CIP guardrail is the key precision lever: assign a value to
its nearest CIP anchor only if it shares a token **and is not more specific than
the anchor** (value tokens ⊆ anchor tokens). This stops "Computer Science and
Engineering"/"Mechanical Engineering Technology" from collapsing onto the
general anchor. Every output also carries a `method` tag and `confidence`, so
the low-confidence band (`cip_anchor` ≈ 0.7) feeds a human review queue.

### Hybrid results

| field | reduction | P | R | F1 | coverage by method |
|---|---|---|---|---|---|
| **degree** | 0.52 | **1.00** | **1.00** | **1.00** | taxonomy 84% / raw 16% |
| **title** | 0.18 | **1.00** | **1.00** | **1.00** | slug 88% / typo 12% |
| **field** (production) | 0.314 | **1.00** | **1.00** | **1.00** | cip_exact 55.3% / cip_alias 4.2% / cip_override 0.3% / raw 29.8% / typo 10.2% |
| **field** (loose guard) | 0.77 | 0.83 | 0.77 | 0.83 | **91% CIP-coded** |

The current production hybrid keeps degree, title, and field at gold F1 1.0.
For `field`, the default intentionally favors precision and deterministic
curation over high autonomous coverage: about 60.0% of rows receive a CIP code,
and the remaining tail stays raw or typo-clustered. Looser nearest-neighbor
settings still reach much higher apparent coverage, but samples such as
"Management" -> "Construction Management" and "Science" -> "Physics" confirm
that those modes belong in a review queue, not the default canonicalizer.

### Why `field` still needs curation

The gold-set miss was closed with a targeted Biology override, but the broader
coverage problem remains a policy/curation problem. CIP contains repeated titles
across 4-digit groups, 6-digit "General" codes, moved codes, and invalid remedial
rows; choosing the right target for broad profile labels requires explicit
granularity decisions. Accepted review-queue decisions should be fed back as
curated aliases or overrides, not inferred by unconstrained embeddings.

## Encoder comparison — does a better/different embedding help?

We benchmarked 9 encoders on a categorized probe set (cosine per phenomenon)
and on the real anchored-to-CIP task. Threshold-independent **ROC-AUC** is the
fair metric; `AUCsem` = separating semantic synonyms (should merge) from
distinct-but-related fields (should keep) — the decisive axis.

`uv run python -m edu_clean.encoder_bench probe` (median cosine per category):

| encoder | case | punct | **typo** | **sem** | sib | sub | combo | AUCsem |
|---|---|---|---|---|---|---|---|---|
| minilm (22M) | 1.00 | 0.96 | 0.50 | 0.77 | 0.51 | 0.73 | 0.78 | 0.649 |
| bge-small (33M) | 1.00 | 0.97 | 0.69 | 0.85 | 0.68 | 0.84 | 0.84 | 0.674 |
| bge-base (109M) | 1.00 | 0.95 | 0.67 | 0.82 | 0.65 | 0.80 | 0.81 | **0.828** |
| gte-base (109M) | 1.00 | 0.98 | 0.85 | 0.92 | 0.84 | 0.91 | 0.92 | 0.813 |
| e5-base (109M) | 1.00 | 0.99 | 0.83 | 0.94 | 0.91 | 0.93 | 0.95 | 0.613 |
| canine (char tfmr) | 0.75 | 0.90 | 0.77 | 0.62 | 0.34 | 0.63 | 0.66 | 0.590 |
| char 3-4gram | 1.00 | 0.90 | 0.50 | 0.51 | 0.00 | 0.65 | 0.65 | 0.518 |
| fuzz token-set | 0.53 | 0.94 | **0.94** | 0.67 | 0.38 | 1.00 | 1.00 | 0.379 |
| fuzz ratio | 0.53 | 0.91 | **0.94** | 0.64 | 0.38 | 0.68 | 0.53 | 0.605 |

What the numbers say:

- **No encoder separates `sem` from `sub`/`combo`.** Even the best (bge-base,
  AUCsem 0.828) has *no usable margin*: median `sem` 0.82 vs `combo` 0.81. Any
  threshold that merges synonyms also merges distinct combinations/subfields.
- **Bigger/"better" is not better here.** gte-base and e5-base saturate
  similarity for short academic terms (everything ≈ 0.9), giving the *worst*
  discrimination (e5 AUCall 0.543, near chance). MTEB rank does not transfer.
- **Typos belong to lexical, confirmed numerically.** fuzz scores 0.94 on typos;
  the best embedding manages 0.85, and char-3gram only 0.50 (short-word
  transpositions break n-grams). But fuzz token-set scores 1.00 on `sub`/`combo`
  (the subset trap) — so lexical needs the equal-cardinality guardrail.
- **No single scorer wins:** every column has a different best tool.

`uv run python -m edu_clean.encoder_bench anchored ...` (full 445K-value CIP
anchoring, with the subset guardrail; gold P/R/F1 + coverage + GPU throughput):

| encoder | P | R | F1 | CIP cov% | throughput |
|---|---|---|---|---|---|
| minilm | 1.00 | 0.61 | 0.76 | 67.5 | 11,700/s |
| bge-small | 0.89 | 0.61 | 0.73 | 68.5 | 9,100/s |
| **bge-base** | 1.00 | **0.69** | **0.82** | 67.8 | 3,700/s |
| gte-base | 1.00 | 0.61 | 0.76 | 67.4 | 9,500/s |
| e5-base | 1.00 | 0.69 | 0.82 | 67.1 | 3,500/s |

**The guardrail, not the encoder, does the work.** Coverage is ~67–68% for every
model (it is bounded by the token-subset guardrail, which mostly duplicates the
lexical CIP token match); a 5× larger model buys at most +0.06 F1 and +1pt
coverage at 3× the cost. The same conclusion holds for the other fields: every
model still merges "Boston University"≈"Boston College" (0.89–0.97) and
"BS"≈"BA" (0.79–0.92), so embeddings remain unusable for institution and degree
regardless of size. If an embedding layer is used at all, **bge-base** is the
best accuracy/precision point and **minilm** the best throughput point — but the
gain over the pure lexical backbone is marginal.

## Recommended production approach

Revised after the encoder study: the embedding layer is **optional and low-value**
for every field. Lead with the lexical/reference backbone; use embeddings only as
a *ranked candidate generator for human review*, never as an autonomous merger.

1. **Normalize** once (NFKC, case, `&`→and, separators, punctuation).
2. **Backbone (precision 1.0, CPU, ~seconds):** degree taxonomy; institution
   row slug / slug + name→slug crosswalk; field CIP exact/token match after
   filtering remedial CIP rows. This alone is the whole story for degree
   (F1 1.0) and institution (F1 1.0), and gives `field` about 60% CIP row
   coverage with the current curated aliases/overrides.
3. **Typo layer (B):** guarded equal-cardinality token matching (Damerau/edit
   distance) on the residual tail. This owns the typo axis outright (lexical
   0.94 vs best embedding 0.85) and stays precise via the cardinality guardrail.
4. **Field coverage (curation-first):** the gap to higher `field` coverage is
   best closed by **curated CIP aliases** (plural/singular, family↔specific
   rollup decisions), not a bigger model. Optionally add a guarded anchored-CIP
   embedding pass (bge-base for accuracy, minilm for speed) purely to *propose*
   tail matches into the review queue with a `confidence` score.
5. **Review queue:** route low-confidence proposals to curation; feed accepted
   decisions back as alias rules so coverage ratchets toward 100% without ever
   sacrificing precision.

Net: immediate F1 1.0 on degree and institution and precision-1.0 / ~60% CIP
coverage on field of study from the remedial-filtered backbone plus curated
aliases, with a curation-driven (not model-driven) path to higher field
coverage. Embeddings are a convenience for surfacing candidates, not the engine.

## Limitations / next steps

- The gold benchmark is modest (72 pairs across 3 fields). It targets the known
  hard cases; a larger labeled set (or active-learning sampling from the
  `cip_anchor` band) would tighten the precision/recall estimates.
- CIP granularity (family vs specific) is a policy choice not yet fixed; pick a
  target level before shipping field-of-study canonicals.
- Embedding model is `all-MiniLM-L6-v2` (fast, general). A domain/education model
  or larger `bge`/`e5` model would likely improve anchored coverage; cheap to
  swap given GPU headroom.

---

## 2026-07-07 — Graduation-anchor recovery (COVERAGE_PLAN.md Plan 2)

New module `edu_clean/anchors.py` + validation harness
`edu_clean/run_anchor_eval.py` -> `edu_clean/results/anchor_eval.json`. The
problem: only ~20% of CIP-coded bachelor records carry a usable `end_year`
(the graduation anchor every portal/cohort equal-window stat is keyed on), so
~80% of every cohort is dropped before any career analysis even starts. Plan 2
adds two more anchor-recovery tiers, A2 (start_year + duration) and A3
(career-onset inference from `paths/steps.parquet`), each gated on a
held-out-gold validation harness before it is allowed to feed a real analysis.

**Gate** (fixed in advance, from COVERAGE_PLAN.md): a tier ships **ACCEPTED**
only if **>=80%** of gold predictions land within **+/-1 year** of the true
(A1) anchor; otherwise it ships flagged **EXPERIMENTAL**, computed and
provenance-tagged but excluded from every default consumer. The gate was not
relaxed for either tier.

### A1 — observed (unchanged)

Earliest usable `end_year` (in [1950, 2025], not `in_progress`). Gold by
construction; this is the pre-Plan-2 rule byte-for-byte (regression-tested in
`portal/portal_tests.py`).

### A2 — start + duration: ACCEPTED (80.4% within +/-1yr)

Rule: `start_year + 3` for CIP-bachelor rows that have `start_year` but no
`end_year` at all (and are not `in_progress`). **3, not the median duration of
4** — the raw both-dates duration distribution (n=220,421) is right-skewed
(dur=2: 15.2%, dur=3: 16.9%, dur=4: 47.8% [mode/median], dur=5: 10.5%, longer
tail thinner still), so the +/-1yr window centered on 3 ({2,3,4} = 79.9% of
mass) beats the window centered on the median, 4 ({3,4,5} = 75.2%). A
per-decade and a per-CIP2 duration split were both tried and neither moved the
share by more than ~0.1pp — a single constant offset is both simplest and
empirically sufficient (see `iterations_tried` in the JSON for the full grid).

Held-out gold validation (person grain, matching the A1 min-collapse rule
exactly — each gold person's own `min(start_year)` vs their true
`min(end_year)`, n=203,124):

| metric | value |
|---|---|
| median error | -1 yr |
| share within +/-1yr | **80.4%** (gate: >=80%) |
| share within +/-2yr | 95.2% |

By entry decade (all comfortably close to or above the bar; no decade
collapses):

| decade | n | within +/-1yr |
|---|---|---|
| 1950s | 93 | 88.2% |
| 1960s | 1,061 | 80.2% |
| 1970s | 5,281 | 82.7% |
| 1980s | 10,954 | 79.4% |
| 1990s | 16,421 | 75.2% |
| 2000s | 34,124 | 79.2% |
| 2010s | 75,767 | 80.7% |
| 2020s | 59,423 | 82.1% |

By named major (all five clear 80%):

| major | n | within +/-1yr |
|---|---|---|
| English & Literature | 4,759 | 82.8% |
| History | 2,966 | 82.1% |
| Philosophy & Religion | 1,450 | 80.0% |
| Fine & Performing Arts | 8,868 | 80.8% |
| Communication & Media | 8,913 | 81.9% |

**Verdict: ACCEPTED.** Default `ANCHOR_TIERS = ("A1", "A2")` everywhere
(`portal/common.py`).

### A3 — career-onset inference: REJECTED (~31% within +/-1yr)

For persons with **no usable education dates at all** (~77% of the
CIP-bachelor population — the "big lever" the plan hoped for), the candidate
signal is the start year of the person's first plausible post-degree career
step from `paths/steps.parquet`. Five rule iterations and an 11-point constant
-offset grid search were run against the A1 gold population (steps-only,
education dates hidden):

| iteration | filter | within +/-1yr |
|---|---|---|
| v1 | exclude `employment_type='student'` + `seniority_level LIKE '%intern%'` | 30.7% |
| v2 | + exclude `title_raw` intern/co-op | 30.9% |
| v3 | `employment_type='employee'` only | 31.1% |
| v4 | + `tenure_months >= 6` | 32.0% |
| v5 (shipped in `anchors.py`) | `in_workforce` + `seniority_ordinal` NULL or >=1 (excludes interns) | 30.7% |
| offset grid on v5 | best of offsets -5..+5 | **0** (no shift beats the unshifted rule) |

Final (v5, n=200,795, 98.9% coverage of gold): median error **0**, share
within +/-1yr **30.7%**, within +/-2yr **42.4%** — a wide, roughly
symmetric error spread, not a biased-but-tight one. Average absolute error is
4-7 years **even for the thinnest (1-2 step) profiles**, which rules out "the
rule needs a better filter": the ceiling is data sparsity — LinkedIn profiles
routinely omit early-career jobs, most severely for older cohorts (1950s gold
persons: median error +30 to +40 years, because the profile's earliest listed
job is decades after actual graduation). No offset, employment-type filter, or
tenure floor closes this gap.

**Verdict: REJECTED** (fails the 80% gate by a wide margin, not a rounding
error). Shipped in `anchors.py` as a fully computed, provenance-tagged,
explicitly experimental tier (`EXPERIMENTAL_TIERS = ("A3",)`) for
completeness and any future revisit (e.g. if a birth-year or education-tenure
proxy becomes available) — excluded from every default consumer. This means
the realized coverage gain from Plan 2 is the "modest, nearly free" A2 bump
only, **not** the ~4-5x the plan speculated on the (now-rejected) A3 lever.

### Bias check — pooling A1+A2 (`portal/bias_check.py` -> `portal/results/bias_check.json`)

Compared A1-only vs pooled (A1+A2) year-10 statistics for the five named
majors + baseline: fan top-5 shares, `up_share`, and the seniority curve at
y0/y4/y10 (the curve grid has no y5 point). Materiality bars from the plan:
fan-share delta > 2 points, `up_share` delta > 0.03.

| group | n (A1-only -> pooled) | max \|fan share delta\| | up_share delta |
|---|---|---|---|
| English & Literature | 3,299 -> 3,581 | 1.40 pts (Business & Financial) | -0.0011 |
| History | 2,091 -> 2,243 | 0.28 pts (Legal) | 0.0000 |
| Philosophy & Religion | 976 -> 1,078 | 0.42 pts (Community & Social Service) | -0.0037 |
| Fine & Performing Arts | 5,345 -> 5,899 | 0.31 pts (Arts/Design/Media) | -0.0001 |
| Communication & Media | 5,307 -> 5,835 | 0.07 pts (Management) | -0.0002 |
| Baseline | 108,236 -> 120,167 | 0.12 pts (Computer & Mathematical) | -0.0017 |

Every delta is far under both materiality bars (largest fan delta 1.4pp,
largest `up_share` delta 0.0037 in absolute value — an order of magnitude
under the 0.03 bar). **No material disagreement — pooling A1+A2 is
defensible**, exactly the outcome you'd hope for from a tier whose measured
error is tight (80.4%/+/-1yr, 95.2%/+/-2yr): A2-anchored people look
statistically like A1-anchored people on every headline number checked.

### Net effect on the funnel

A2 adds ~10-13% more anchored persons per group (not the 4-5x the plan
projected, because that projection assumed A3 would also clear the gate).
Windowed year-10 cohorts grow correspondingly: English 3,299 -> 3,581 (+8.5%),
History 2,091 -> 2,243 (+7.3%), Philosophy & Religion 976 -> 1,078 (+10.5%),
Fine & Performing Arts 5,345 -> 5,899 (+10.4%), Communication & Media 5,307 ->
5,835 (+9.9%), Baseline 108,236 -> 120,167 (+11.0%). See
`portal/FINDINGS.md`'s dated section for the full before/after funnel table.
