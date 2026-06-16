# Inferring Industry from LinkedIn Career Data — Methods

*A multi-method industry/sector classifier with an LLM-as-jury layer, served across a two-machine local GPU pool.*

This document has two halves. **Part 1** explains the pipeline for a general
reader, with diagrams. **Part 2** is the technical deep dive with every
parameter, model, and measured number. The system lives in `industry/`; the
original design is `INDUSTRY_PLAN.md`, the as-built reference is `README.md`,
and the operational setup is `SETUP.md`.

---

# Part 1 — The pipeline for a general reader

## The problem in one picture

We have ~2 million LinkedIn profiles containing ~9 million job experiences. We
want to know **what industry each job is in** — so we can draw flows like "who
moves from finance into tech?" But the industry field in the data is unusable:

```
   What we wanted                        What the data actually contains
   ┌─────────────────────┐              ┌─────────────────────────────────┐
   │ industry: "Banking" │   ✗   only   │ industry field: populated on     │
   │ industry: "Software"│   106 of     │   106 of 2,000,000 profiles      │
   │ industry: "Retail"  │  2,000,000   │   (0.005%) — and the values are  │
   └─────────────────────┘              │   company NAMES, not industries  │
                                        │   ("Bank of America", "AT&T")    │
                                        └─────────────────────────────────┘
```

So industry is **~100% an inference problem**. We have to *deduce* it from
everything else in the data: the company name, the job titles of people who work
there, the free-text descriptions, the occupation, and so on.

## The key insight: label companies, not jobs

Industry is a property of the *company*, not of each individual job row. The same
company appears in thousands of profiles. So instead of deciding 9 million times,
we decide **once per company** and copy the answer to every job at that company:

```
   9,000,000 job rows                 2,990,295 distinct companies
   ┌──────────────────┐               ┌──────────────────┐
   │ row 1  @ Acme     │──┐            │                  │   decide ONCE
   │ row 2  @ Acme     │──┼──────────► │  Acme → Finance  │ ◄── per company,
   │ row 3  @ Acme     │──┘            │                  │     then copy back
   │ row 4  @ Globex   │──────────────►│  Globex → Tech   │
   │  ... 9M rows ...  │               │  ... 3M cos ...  │
   └──────────────────┘               └──────────────────┘
```

This is ~3× less work, and it guarantees the same company gets the same industry
everywhere — which is exactly what consistent flow diagrams need.

## The industry "map" (taxonomy)

Every company is placed into a 4-level tree of **162 nodes**. The top level has
17 broad buckets; you can drill down to specific sub-industries:

```
   Level 1 (17 buckets)      Level 2          Level 3              Level 4
   ──────────────────────────────────────────────────────────────────────────
   Finance ─────────────► Banking ─────────► Commercial Bank ──► Retail Banking
   Technology ──────────► Software & IT ───► Application Sw ───► SaaS / B2B
   Public Sector ───────► Government ──────► Defense ──────────► Armed Forces
   Healthcare, Education, Manufacturing, Consumer & Retail, Energy, Media,
   Professional Services, Real Estate, Transportation, Hospitality,
   Agriculture, Nonprofit … plus "Diversified" and "Other/Unknown"
```

A company can be placed at **any depth**. If the evidence only supports "this is
Finance" but not which kind, we stop at Level 1 — we never guess deeper than the
evidence allows. Each level carries its own confidence.

## The cascade: cheap and certain first, expensive and clever last

We run a series of methods from most-reliable/cheapest to most-flexible/costliest.
Each company falls through until something can place it:

```
  ┌───────────────────────────────────────────────────────────────────────┐
  │  A company's name + employee titles + descriptions come in              │
  └───────────────────────────────────────────────────────────────────────┘
        │
        ▼
  ① Hand-curated table   "Wells Fargo → Retail Banking"      precision ≈ 100%
        │  (known big companies; covers a third of all rows)
        ▼  not found?
  ② Name rules           "* Bank", "* Hospital", "City of *"  precision high
        │  (names that ARE their industry)
        ▼  ambiguous name?
  ③ Occupation prior     mostly-nurses → Healthcare           weak hint only
        │  (a tiebreaker, never decides alone)
        ▼  still unresolved AND has text?
  ④ LLM JURY  ◄── the subject of the big run ──────────────►  propose-only
        │   reads the name + titles + descriptions and reasons to an answer
        ▼
  ┌───────────────────────────────────────────────────────────────────────┐
  │  Output: an industry path + a confidence at each level                 │
  └───────────────────────────────────────────────────────────────────────┘
```

The first three steps are **deterministic** — same input always gives the same
output, no AI, no randomness. They already place **42% of all job rows** at the
top level with near-perfect precision. The LLM only gets the genuinely hard
leftovers: companies with no match in any table whose only clue is free text.

## Why a "jury" of AI models, not a single one

A single language model will confidently hand you an answer even when it's
guessing — and its errors are *hard to catch* because they come wrapped in
fluent reasoning. So instead of trusting one model's vote, we poll a **panel**
and use their **agreement** as the real confidence signal:

```
        "Smith Plumbing & Heating, LLC"
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
     Juror A     Juror B     Juror C
   "Real Est/  "Real Est/  "Real Est/
    Construct"  Construct"  Services"
        └───────────┼───────────┘
                    ▼
   Walk the tree top-down, stop where the majority still agrees:
        Level 1: 3/3 say Real Estate & Construction  ✓ accept
        Level 2: 2/3 say Construction                ✓ accept (majority)
        Level 3: they split                          ✗ stop here
                    │
                    ▼
   Verdict: "Real Estate & Construction → Construction"  (agreement 2/3)
```

If the jurors can't even agree on Level 1, the company is sent to a human review
queue instead of being force-fit. **Agreement is something we can measure and
calibrate; a single model's self-reported "high confidence" is not.**

## Two computers, one job

The jury runs on local open-weight models (no profile text ever leaves our
machines). One job is ~2 million companies — far too much for one GPU run
serially. So we split the work across two machines connected over a private
network:

```
   ┌────────────────────────────┐         ┌────────────────────────────────┐
   │  This machine               │         │  Framework Desktop (over VPN)   │
   │  RTX 5080 GPU (16 GB)       │  ◄────► │  AMD Strix Halo, 128 GB memory  │
   │  16 parallel "lanes"        │         │  8 parallel "lanes"             │
   └────────────────────────────┘         └────────────────────────────────┘
                    │                                   │
                    └──────────────┬────────────────────┘
                                   ▼
            One orchestrator hands out companies to whichever
            machine has a free lane. If a machine drops off the
            network, its work is automatically re-handed to the
            other; nothing is lost, the run just resumes.
```

## How long, and where we are

The naive approach (one model, one company at a time) would have taken **~24
days**. Four compounding speedups brought it under a week:

```
   Naive serial ......................................... ~24 days
   + GPU acceleration on the 2nd machine (was CPU-only) .. 8.5× faster there
   + batched serving (many lanes at once, not one) ....... ~3× pooled
   + a better-AND-faster small model for the bulk work ... ~2×
   + doing the highest-coverage companies FIRST .......... 76% of value by day 3
   ─────────────────────────────────────────────────────────────────────────
   Result: usable coverage in ~3 days; full run ~10 days, mostly the rare tail
```

The most valuable 76% of the work (companies that appear in many profiles)
finished in the first ~2.5 days. The rest is the "long tail" of one-off
companies, which keeps filling in afterward.

---

# Part 2 — Technical deep dive

## 2.1 Scope and unit of analysis

- **Inputs:** `normalized/career_steps.parquet` — 10,636,544 organization-bearing
  career rows across 2,990,295 distinct companies (keyed `id:<canonical>` when a
  LinkedIn company_id exists, else `raw:<name>` / `nonorg:<...>`).
- **Grain:** classification is performed **per company** and propagated to rows.
  A company's industry is treated as stable over time in v1 (conglomerates →
  `XDV` Diversified; pivots get the review flag, not per-year labels).
- **Reproducibility contract:** the deterministic backbone needs no network and
  no API key; the LLM layer is **propose-only**, behind a **frozen,
  content-hashed cache**, and never overwrites a deterministic answer. A pipeline
  re-run with the cache present produces identical output with zero network.

## 2.2 The taxonomy

A custom 4-level spine that crosswalks down to NAICS, frozen in `taxonomy.py` /
`taxonomy.json`:

| Level | Count | Granularity |
|------:|------:|-------------|
| L1 Macro-sector | 17 | presentation buckets (incl. `XDV` Diversified, `XOT` Other) |
| L2 Sector | 68 | ≈ NAICS subsector |
| L3 Industry | 63 | ≈ NAICS 4-digit |
| L4 Sub-industry | 14 | ≈ NAICS 5–6-digit / GICS sub-industry |
| **Total** | **162** | |

- **L1 buckets:** Technology, Finance, Healthcare, Education, Public Sector,
  Manufacturing & Industrials, Consumer & Retail, Energy & Utilities, Media &
  Entertainment, Professional Services, Real Estate & Construction,
  Transportation & Logistics, Hospitality/Travel/Food, Agriculture & Natural
  Resources, Nonprofit & Social Sector, Diversified (`XDV`), Other/Unknown (`XOT`).
- Every node has a stable dotted code (`FIN.BNK.COM.RET`), a display label, and a
  NAICS crosswalk (`naics_of` falls back to the nearest coded ancestor).
- **Partial assignment is first-class:** `truncate(code, level)`, `level_of`,
  `ancestors`, `is_valid` all accept any-depth codes. Cross-cutting flags:
  `sector ∈ {private, public, nonprofit}` (e.g. a defense *contractor*
  `PUB.DEF.DCON` is flagged `private`).
- **Structured-output schema:** `T.output_json_schema()` emits a strict
  JSON-Schema whose `code` field is an **enum of all 162 codes** and whose first
  required property is `rationale` (reason-before-verdict ordering). A
  constrained decoder literally cannot emit an off-taxonomy code.

## 2.3 The deterministic backbone (methods M1–M5, M7)

Each method emits `(industry_path, depth, confidence, method)`. Fusion takes the
deepest node all corroborating evidence agrees on. Implemented in `classify.py`.

- **M1 — curated company → industry** (`curated.py`): hand-reviewed head companies,
  precision ≈ 1.0, resolves to L4. The ratchet table.
- **M2 — bootstrapped joins** (design): public-data joins (Wikidata/SEC SIC) to
  seed M1 at scale; high-confidence auto-populate, ambiguous → review queue.
- **M3 — company-name lexical rules** (`name_rules.py`): unambiguous tokens only
  (`* Bank`, `Credit Union`, `* Hospital`, `City of *`, `* Realty`). Generic
  corporate words ("Global Solutions Group") are deliberately dropped so the rule
  abstains rather than misfire. Typically L2/L3.
- **M4/M5 — occupation → industry prior** (`occupation_prior.py`): maps the
  modal SOC occupation of a company's employees to an industry distribution. A
  **weak prior / tiebreaker only** — industry-agnostic occupations (software
  engineer, accountant, project manager) must abstain, enforced by test.
- **M7 — education-field prior:** person-level last resort (lowest confidence).

**Fusion / arbitration (§3.8):** a high-precision method (M1/M2/M3) sets the
spine; then walk L1→L4 accepting a level if the spine asserts it OR the weak
priors agree above threshold; stop descending when evidence runs out → a partial
path. Disagreement between high-precision methods → review queue. Nothing fires →
`XOT` at L1, queued for the LLM/curation.

**Measured deterministic coverage** (no LLM, `build_industry --propagate`):

| Depth | % of all org rows placed |
|------:|-------------------------:|
| L1 | 42.0% |
| L2 | 37.8% |
| L3 | 17.3% |
| L4 | 1.4% |

2,055,072 companies remain in the review queue after the deterministic pass —
the population the LLM layer targets.

## 2.4 M6 — the LLM layer

The only method that reads industry signal **latent in unstructured text**. Used
in two bounded modes, never as an autonomous hot-path classifier:

1. **Tail proposer** — single cheap juror over the text-bearing residual the
   deterministic stack abstained on (the big run).
2. **Head curator** — a strong model over the head company table to grow M1.
3. **Jury** — a diverse panel over the high-frequency residual head, where errors
   propagate to many rows and ambiguity is worth resolving.

**Residual definition** (`fire_llm._residual`): companies whose deterministic
method ∈ {`unresolved`, `occupation_prior`} **and** that carry text
(title/description). Measured: **2,027,185 items** covering **6,448,149 rows
(60.6% of org rows)**. Evidence is short — median ~64 tokens, mean ~103, p90 ~200;
99.99% Latin script, ~87% confidently English.

**Prompt & request:** a ~2,500-token system prefix (`llm._SYSTEM`, 10,038 chars)
holds the rubric + the full labelled taxonomy catalog and is **shared verbatim**
across every request (so it prefix-caches). The volatile user turn is the
per-company evidence block (name + up to 8 modal titles + up to 3 longest
descriptions). Output is the enum-constrained reason-first schema. `PROMPT_VERSION
= 3`.

**Frozen cache** (`industry/llm_proposals.jsonl`): one JSON line per
`Proposal(key, code, confidence, rationale, model, input_hash)`. The
`input_hash = sha256(evidence + model + PROMPT_VERSION + schema_version +
n_codes)`. Any change to inputs/prompt/schema busts the entry; the loader is
torn-line tolerant (a crash mid-flush skips the partial line, that item simply
re-fires). **Backend-agnostic:** cloud `claude-*` and local `ollama/*` /
`llamacpp/*` jurors coexist in one file; the key embeds the model.

> **Determinism prerequisite caught & fixed:** the vocab export
> (`common.export_company_vocab`) ranked descriptions by length with no
> tiebreak, so a re-export reshuffled ties and changed the evidence hash —
> silently orphaning 5,003 of 5,014 cached votes. Fixed with full
> `ORDER BY … , <value>` tiebreaks and a deterministic `mode()` via
> `row_number()`; verified bit-identical evidence hash across two forced
> re-exports before launching the run.

## 2.5 LLM-as-jury aggregation (`jury.py`)

Pure, offline, unit-tested. Given `{model → code}` for one company:

```
consensus(paths, tau=0.5):
  for level in 1..4:
    among jurors whose path reaches `level` AND is consistent with the
    accepted parent, take the modal label; accept & descend iff its support
    as a fraction of ALL jurors (abstainers count against depth) > tau;
    else stop. No L1 majority → XOT.
```

This yields a `JuryVerdict(code, depth, agreement, n_jurors, per_level, jurors)`
where **agreement is the per-level support fraction** — an empirically
calibratable confidence (e.g. "3/3 at L1, 2/3 at L2"), far better than verbalized
high/med/low. Degrades gracefully: one juror → that juror's path at agreement 1.0.

## 2.6 Calibration & evaluation (`run_industry.py`, `gold.py`, `gold_residual.py`)

- **Gold sets:** curated company labels + a 134-pair residual gold stressing hard
  cases (conglomerates, staffing agencies, university-hospitals, gov vs
  gov-contractor, self-employed craft → industry).
- **Per-level precision/recall** reported separately (you can be right at L1, wrong
  at L4). Latest gold-companies eval: **L1 P 0.862 / R 0.862; L2 P 1.0 / R 0.828;
  L3 P 1.0 / R 0.586; L4 P 1.0 / R 0.103** — i.e. precision held at 1.0 below L1,
  recall (depth) falls off, exactly the precision-first trade.
- **Agreement-band calibration:** maps jury agreement → observed precision.
  Measured on the gold panel: **unanimous L1 0.977 (n=44), majority 0.966 (n=29)**.
- **Self-reported confidence is useless locally** and is *not* used as a gate:
  the production bulk juror's self-reported "high" ran at L1 precision **0.889
  (n=72)** regardless of correctness — the calibrated agreement band is the gate,
  and auto-accept stays human-gated until a band proves out via the Alternative
  Annotator Test.

## 2.7 The multi-host serving infrastructure

### Host pool (`llm_pool.py`) — stdlib-only scheduler

A pool of inference daemons consumed as one capacity. Knows nothing about
taxonomies or proposals — it moves JSON bodies to daemons and hands responses to
a callback under a lock.

- **Two backends, one abstraction:** `OllamaHost(api ∈ {"ollama","llamacpp"})`.
  Ollama hosts probe `/api/tags` and POST `/api/chat`; llama-server hosts probe
  `/v1/models` and POST `/v1/chat/completions` with `_openai_body` /
  `_from_openai` adapters that translate the enum schema into a strict
  `response_format`, set `cache_prompt: true`, and normalize timings (ms→ns).
- **Eligibility = where a model is pulled** (discovered, not configured).
- **Scheduling:** one queue per model; each host runs `parallel` worker threads
  with sticky model-affinity (minimise swap thrash) and work-stealing for models
  present on several hosts. `take()` skips a unit a host already failed.
- **Failure policy:** per unit, 1 same-host retry → 1 cross-host requeue → give up
  (left uncached, resumable). A host with 5 consecutive failures is marked down
  and its now-unservable queue is pruned to `failed`. All hosts down → pure cache
  read. A raising result-callback can't kill a worker slot. Every unit reaches
  `finish()` exactly once; termination is guaranteed (stress-tested 200 units ×
  20 trials with random failures + raising callbacks, no hang, no double-count).
- **Default pool:** 2 Ollama daemons + 2 batched llama-server lanes (below).

### The batched lanes (the 7-day enabler)

The decisive throughput win was replacing serial Ollama with **llama.cpp
`llama-server` continuous batching** on both machines, serving one model under a
shared alias so the pool work-steals:

| Host | Build | Model | Slots (`-np`) | Measured |
|------|-------|-------|--------------:|----------|
| Local (RTX 5080, WSL2) | native CUDA **sm_120**, llama.cpp b9592 | `qwen3-4b` Q4_K_M | 16 | ~1.5–2.1 items/s |
| Framework (Strix Halo, gfx1151) | prebuilt **Vulkan/RADV** b9592 | `qwen3-4b` Q4_K_M | 8 | ~0.5 items/s |

Key configuration facts (the non-obvious ones):

- **sm_120 build:** the distro nvcc 12.6 cannot target Blackwell; a compute_90
  PTX-JIT fallback ran ~5× slow. The working build uses a user-space **CUDA 12.8**
  toolchain (micromamba) with a matching **gcc-12** host compiler
  (`-DCMAKE_CUDA_ARCHITECTURES=120 -DCMAKE_CUDA_HOST_COMPILER=…/g++`).
- **vLLM was ruled out** (the higher-ceiling option) because WSL is 2.6.1 and
  Blackwell CUDA-graph capture needs WSL ≥ 2.7.0; eager mode carries a measured
  ~8× penalty. Per the user's constraint, no WSL restart — llama-server is the
  no-restart path with native grammar support and per-slot prompt caching.
- **ROCm on the Framework:** the daemon was silently CPU-only —
  `OLLAMA_LLM_LIBRARY=rocm` didn't match the shipped `rocm_v7_2` libdir. A
  systemd drop-in pointing at `rocm_v7_2` lit up the iGPU (gemma3:27b 3.7→
  ~8.7 tok/s, an 8.5× jump); for the batched lane, **Vulkan/RADV** beats ROCm for
  token-gen on gfx1151 (community-confirmed, re-measured: Qwen3-30B-A3B pp512
  ~1409 t/s, tg128 ~95 t/s).
- **Slot-context sizing (subtle, caught in pilot):** per-slot context = `-c` /
  `-np`, and the ~3.9k-token jury prompt overflowed 4096-token slots, truncating
  ~3% of outputs at `finish_reason: length` so they never validated. Both servers
  run **6144 tokens/slot** (`-c 98304 -np 16` local, `-c 49152 -np 8` remote),
  KV at `q8_0`.
- Each server runs under a `while true` **watchdog** (`serve-*.sh`, `setsid`)
  that relaunches on any exit — insurance against the documented gfx1151
  sustained-load wedge.

## 2.8 The big run (`run_tail.sh`)

The S1 strategy, chosen from a quantified workload study over three candidates:

- **Juror:** `qwen3-4b` Q4 via the batched lanes — the workload study's
  best-AND-fastest local single juror (gold L1 **0.893** vs llama3.1:8b's 0.760;
  also ~2× faster). Confirmed through the production path at L1 **0.889 (n=72)**.
- **Prompt unchanged (v3):** zero cache invalidation; votes land as ordinary
  `llamacpp/qwen3-4b-q4` jurors that `jury.aggregate` / `build_industry` consume.
- **Frequency-ordered:** items fired highest-row-coverage first. The freq≥2 head
  is **491,343 items = 76.2% of residual rows = 46.2% of all org rows** — so the
  bulk of analytic value lands in the first ~2.5 days; the freq-1 long tail
  (75.8% of items but 23.8% of residual rows) fills in after.
- **Chunked & resumable:** 100k-item chunks, each a preview-then-`--execute`
  pass that reads the frozen cache first and fires only the uncached remainder.
  Bounded memory, crash-safe (incremental 50-vote flushes), idempotent. Stops when
  a full pass adds < 0.1% new votes (the residue is items whose constrained output
  never validates → review-queue leftovers), then auto-runs
  `build_industry --propagate`. Status: `industry/results/tail_status.txt`; log:
  `tail_run.log`.

**Rejected levers (measured, not assumed):**
- *Embedding prefilter as an LLM short-circuit* — precision ceiling ~0.88 even at
  high cosine (exemplar-kNN on silver labels); kept only as a routing/ordering
  signal, not a call-replacement.
- *120-char rationale cap* — the rationale **is** the chain-of-thought with
  thinking off; capping it dropped qwen3:4b L1 from 0.893 → 0.720. (A softer
  240-char/30-word cap was quality-neutral but unnecessary for S1.)
- *llama3.2:3b* — L1 0.507, strictly dominated.

### Throughput accounting

```
   Serial Ollama, one model, one item ............... ~24 days   (0.99 items/s)
   ── ROCm fix on the Framework (was CPU-only) ────── 8.5× on big models
   ── llama-server continuous batching vs serial ──── ~3× pooled
   ── qwen3-4b bulk juror (better AND faster) ─────── ~2×
   ── frequency-ordered firing ─────────────────────── 76% of value in 24% of items
   ─────────────────────────────────────────────────────────────────────────────
   Sustained pooled rate ............................. ~2.3 items/s, ~99% valid
   Usable (freq≥2) coverage .......................... ~2.5 days   ✓ under 7
   Full 2.03M residual ............................... ~10 days (tail is cheap value)
```

## 2.9 Reproducibility & governance summary

- **Offline = pure cache read.** `build_industry` / `run_industry` only ever
  *read* the frozen cache; the pipeline is deterministic and runnable with no
  network and no key.
- **Propose-only.** The jury is a review-queue candidate in `llm_*` columns; it
  never overwrites the deterministic spine.
- **No PII egress.** The production run is entirely local open-weight models;
  scraped profile text never leaves the two machines (the cloud `claude-*` votes
  in the cache are gold-set calibration only).
- **Agreement, not eloquence.** The gating signal is calibrated jury agreement,
  not a model's self-reported confidence.
- **Frozen, content-hashed cache** keyed on `evidence + model + prompt + schema`,
  with a now-deterministic vocab export so keys survive re-export.

## 2.10 File map

| File | Role |
|------|------|
| `taxonomy.py` / `taxonomy.json` | 162-node 4-level schema, NAICS crosswalk, enum schema |
| `curated.py`, `name_rules.py`, `occupation_prior.py` | deterministic methods M1/M3/M4-M5 |
| `classify.py` | precedence + fusion → partial path with per-level confidence |
| `llm.py` | M6 cloud layer: prompt, evidence, cache, Batch API, `cached_panel` |
| `local_llm.py` | local jurors: panel constants, think-flags, pool-backed firing |
| `llm_pool.py` | multi-host scheduler (Ollama + llama-server), discovery, work-stealing, failure policy |
| `jury.py` | hierarchical-consensus aggregation (pure) |
| `fire_llm.py` | the firing CLI (tail / jury / head / calibrate / sample-gold) |
| `build_industry.py` | merges deterministic + propose-only jury into the company/step tables |
| `run_industry.py` | gold eval + agreement→precision calibration |
| `bench_hosts.py` | per-(host,juror) throughput benchmark with real bodies |
| `run_tail.sh` | the chunked, resumable big-run driver |
| `doctor.py` | pre-flight: deps, data, hosts, per-model placement |

*Generated 2026-06-16, mid-run (the tail run was ~54% through the residual at
~2.3 items/s when this was written).*
