# Industry / sector classification (Layer 6a)

A **4-level hierarchical industry schema** + a **multi-method, precision-first
classifier** that *infers* industry at the distinct-company grain and propagates
to career steps. The in-data industry field is unusable (`cc_industry` populated
on 0.005% of profiles), so this is ~100% an inference problem. Design rationale
is in `../INDUSTRY_PLAN.md`; this README is the as-built reference.

## The unit of analysis: classify companies, propagate to rows

Industry is a property of the **employer**, not the person — a profile holds many
jobs across many industries, so we resolve industry once per distinct company and
join it onto every career step. The distinct-company grain is the production
`company_canonical_id` already in `normalized/career_steps.parquet` (career_clean's
`id:<company_id>` / `raw:<norm>` / `nonorg:<bucket>`), so this is consistent with
the rest of the pipeline and guarantees *the same company gets the same industry
everywhere*. Measured: **2.99M** distinct companies / **10.6M** org rows.

## The 4-level schema (`taxonomy.py` → `taxonomy.json`)

A custom spine crosswalked down to NAICS; codes are dotted ancestor paths
(`FIN.BNK.COM.RET`), every node is a legal **partial** assignment target, and
`XDV` (Diversified) / `XOT` (Other/Unknown) give the giants and the tail an honest
home. **162 nodes** (L1 17, L2 68, L3 63, L4 14). A cross-cutting `sector`
(private/public/nonprofit) is a flag derived from the node, not a branch.

```
L1 Macro-sector   FIN = Finance
L2 Sector          FIN.BNK = Banking
L3 Industry         FIN.BNK.COM = Commercial Banking
L4 Sub-industry      FIN.BNK.COM.RET = Retail / Consumer Banking
```

`taxonomy.py` is the single source of truth; regenerate the committed JSON asset
with `uv run python -m industry.taxonomy build`. `output_json_schema()` builds the
enum that **constrains the LLM's structured output to the taxonomy** (it cannot
emit an off-taxonomy code).

## The methods (precedence + fusion, `classify.py`)

Each method emits `(code, depth, confidence)`; the engine takes the highest-
precision spine and emits the **deepest node the corroborating evidence supports**
— a path truncated to the supported depth, with per-level confidence, not a
forced L4 leaf.

| method | file | grain | precision | typical depth |
|---|---|---|---|---|
| **M1** curated `company_id` → industry | `curated.py` (hand) > `curated_head.py` (frontier-labeled head) > `curated_promoted.py` (jury-promoted) | company | hand 1.0; head / promoted 0.95 (their gate precision) | L3/L4 |
| **M3** company-name lexical rules | `name_rules.py` | company (no-id tail) | high (precision-tested fixtures, audit 2026-09-02) | L2/L3 |
| **M4/M5** occupation (SOC) → industry prior | `occupation_prior.py` | row / company-modal (pooled SOC major) | weak (tiebreak) | L1/L2 |
| **M6** LLM on name+titles+description | `llm.py` | distinct value | propose-only | varies |

Precision-first guards (same discipline as the O*NET coder): M3 fires only on
unambiguous tokens — generic corporate words (group, holdings, solutions,
services, global) never classify, and the 2026-09-02 audit retired the tokens
that fired mostly on the wrong sector (electric, farm, dairy, motors, ventures,
equity, records, industries, salon, systems, bare capital; see the bottom of
`name_rules.py`). Every rule must be reachable on its own keyword and the real
misfires (PG&E, Columbia University, food banks, Goodwill, State Farm, BAE
Systems, ...) are pinned as negative fixtures in `tests.py`. M5 **abstains on
industry-agnostic occupations** (Software Engineer, Accountant, PM, Sales,
designers / PR) and only fires for the genuinely industry-bound major groups,
always shallow + low-confidence, and at the company grain only with >= 3 rows
and a modal share >= 0.6. Anything unresolved → `XOT` + `needs_review`, with
**no sector** (an XOT row is not "private").

## The LLM layer (`llm.py` + `jury.py`) — propose-only LLM-as-jury, frozen cache

The only method that reads industry signal latent in unstructured text (the
description-bearing no-id tail; self-employed rows). Built as an **LLM-as-jury**
(see `LLM_JUDGE_JURY_REPORT.md`): rather than trust one model's call and its
near-constant self-reported "high", a small **diverse panel of Claude jurors**
(Haiku + Sonnet + Opus tiers) votes, and `jury.py` aggregates by **walking the
taxonomy top-down and stopping at the deepest level a majority of jurors agree
on**. Juror *agreement sets the depth* (a clean fit for the depth-truncated schema,
§3.8); juror *disagreement → `XOT` → the review queue*. The per-level agreement
fraction is the **calibratable** confidence — the gating signal, replacing the
miscalibrated verbalized band. **Never** an autonomous classifier; modes:

1. **tail** (`MODEL_BULK`, Haiku) — single cheap juror on the text-bearing residual.
2. **jury** (`JURY`, full panel) — on the top-N residual *head* by frequency, where
   errors propagate to many rows and ambiguity is worth the 3× cost (triage).
3. **head curator** (`MODEL_HEAD`, Opus) — propose head-table industries to grow M1.
4. **calibrate** — the panel on the gold population, mapping agreement → observed
   precision (the *Alternative Annotator Test*) before any auto-accept.

Disciplines that keep it consistent with the repo's reproducible contract:
**reason-before-verdict** output schema (rationale emitted before the code),
**Batch API** (50% cost), **structured output enum-constrained** to the frozen
taxonomy, the stable taxonomy catalog cached as the system prefix, an **intra-vendor
panel** (Claude tiers only — no scraped PII leaves Anthropic, §7.9), and a **frozen,
committed proposal cache** (`llm_proposals.jsonl`) keyed by a hash of (evidence +
model + prompt + schema). Offline (no `ANTHROPIC_API_KEY`) the layer is a pure cache
read, so the pipeline stays deterministic and runnable without it. Jury verdicts are
merged by `build_industry` into propose-only `llm_*` columns (`llm_code`,
`llm_agreement`, `llm_n_jurors`, `llm_agrees_det`, …) and **never overwrite a
deterministic answer**.

Two interchangeable backends (a juror is just a model string):
**cloud** (Anthropic Batch API) and **local** (`local_llm.py` / `llm_pool.py`
— a multi-host Ollama pool spanning this machine and the Framework Desktop over
tailscale, no key, no PII egress; pass `--backend local`). Placement is
automatic: each juror runs on whichever host has its model pulled, so large
jurors (gemma3:27b, qwen3:32b, gpt-oss:120b) run on the Framework while
phi4:14b runs locally, all concurrently. Both backends write the same frozen
cache and **mix freely** — `build_industry`/`run_industry` consume cloud and
local votes identically.

`llm_pool.py` — multi-host Ollama scheduling core (hosts, discovery,
work-stealing queues). Default pool: local `http://127.0.0.1:11434` (1 slot) +
Framework `http://100.73.40.75:11434` (2 slots). Override with
`OLLAMA_HOSTS="name=url|slots,..."`. Down hosts are skipped; no live hosts →
pure cache read.

```bash
uv run python -m industry.doctor                     # check prereqs, get next steps
uv sync --group llm                                  # installs anthropic (cloud only)
uv run python -m industry.fire_llm jury --limit 2000 # preview a cloud panel firing (no API)
uv run python -m industry.fire_llm jury --backend local --limit 2000 --execute  # fully local
```

See `SETUP.md` for copy-paste onboarding (incl. the fully-local path).

## Run it

```bash
uv run python -m industry.doctor                     # FIRST: prereq check + tailored next steps
uv run python -m industry.tests                      # deterministic tests (no data/network)
uv run python -m industry.run_industry               # gold eval per-level P/R + offline LLM calibration
uv run python -m industry.run_industry --full        # + production coverage on the company vocab
uv run python -m industry.taxonomy build             # regenerate taxonomy.json

uv run python -m industry.build_industry             # company_industry.parquet  (~2.5 min)
uv run python -m industry.build_industry --propagate # + row-level step_industry.parquet

# LLM jury (optional; safe no-API preview by default, --execute to fire) -- see SETUP.md
uv run python -m industry.fire_llm tail --limit 5000        # single cheap juror, bulk residual
uv run python -m industry.fire_llm jury --limit 2000        # full panel on the head (triage)
uv run python -m industry.fire_llm calibrate --execute      # panel on gold -> calibration
uv run python -m industry.fire_llm sample-gold --limit 150  # labeling worksheet (no API)
```

Outputs land in `industry/results/` (parquet gitignored, JSON summaries kept).
`company_industry.parquet`: one row per company with `industry_code`,
`l1`..`l4` (truncated codes), `depth`, `method`, `confidence`, `sector`,
`needs_review`, and the propose-only `llm_*` candidate. `step_industry.parquet`:
the row-level org axis the flow diagrams are drawn on.

## Measured results

**Gold (per-level P/R, `gold.py` — 30 companies stressing conglomerates, staffing,
gov-vs-contractor, universities-with-hospitals, the curated head, the
self-describing tail, plus deliberate recall-gap cases):**

| level | precision | recall |
|---|---|---|
| L1 | 0.862 | 0.862 |
| L2 | **1.00** | 0.828 |
| L3 | **1.00** | 0.586 |
| L4 | **1.00** | 0.103 |

Precision is 1.0 at L2–L4; recall falls with depth (partial assignment). The L1
misses are the *intended* recall-gap cases (Booz Allen, Rivian, Chobani — no
industry token in the name, no `company_id`) — exactly the population the LLM
tail-proposer + curation ratchet target. Row-grain self-employed prior: 6/6,
including correctly **abstaining** on industry-agnostic occupations.

**Production, row-weighted coverage by depth (2026-09-02, after the audit
fixes and the frontier head pass):** L1 **58.3%**, L2 53.1%, L3 25.2%, L4 2.1%
of all 10.8M career steps land on a real industry.  By method: curated 27.4%
(hand + head + promoted, 6,706 companies), name rules 29.6%, occupation prior
1.4%, unresolved 41.7%.  The humanities cohort's steps sit at L1 53.9%.  Of
the unresolved 4.5M steps, 2.56M are id-keyed companies below the head
(the next curation slice: +1,000 ids -> 59.3%, +10,000 -> 63.5%, +20,000 ->
65.9%) and 1.78M are the no-id `raw:` singleton tail, which is the LLM
proposer's problem, exactly as with occupation coverage in
`career_clean/FINDINGS.md`.  Before the head pass the same build measured
L1 49.8% (the Phase 0 fixes had retired mostly-wrong name-rule coverage from
53.0%).

## The curated head and its blind gate

`curated_head.py` (method `frontier_head_v1`) is the 2026-09-02 pass over the
unresolved head: every company with no curated / name-rule / prior industry,
ranked by row count and by humanities-cohort rows, labeled from its display
name, its modal titles and its description snippets, with abstention (`SKIP`)
for ambiguous ids ("Independent Film", "Entertainment", gig platforms).  The
label record, including the abstentions, is `results/head_labels_v1.jsonl`.

The tier carries confidence 0.95, which is a claim, not a measurement, until a
second reader checks it.  `results/head_gate_blind.jsonl` is a 100-company
blind sample (50 row-weighted, 50 uniform) with the same evidence and no code;
`results/head_gate_key.jsonl` holds the head's answers.  A reviewer who has not
seen the key writes `code` per `n` into a review file, then:
```
uv run python -m industry.head_gate industry/results/head_gate_review.jsonl
```
reports L1 / L2 / exact agreement and every disagreement, and fails under
L1 agreement 0.90.  Retract the L1 disagreements into `curated.RETRACTED`
rather than lowering the bar.  The next slice of the head (rank 10k-20k, the
65% cut) goes through the same two files.

## The review-queue ratchet

`needs_review` companies (the unresolved tail, the weak-prior fallbacks, and any
M1/M3 L1-disagreements) plus the propose-only `llm_*` candidates feed the same
curation ratchet the rest of the repo uses (`curated.CURATED` ⟵ review queue,
analogous to `career_clean.approach_a_rules.ENTITY_ALIASES`). Coverage and depth
increase over time **without sacrificing precision** — a bigger model is not the
lever; curation is.
```
review queue  ──►  human / LLM-curator spot-check  ──►  curated.CURATED (M1)  ──►  re-run build
```
