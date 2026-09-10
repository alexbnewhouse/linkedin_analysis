# Industry classifier + LLM jury — setup (idiot-proof)

One page, copy-paste. The deterministic backbone needs **no API key and no network**;
the LLM-as-jury layer is optional and only fires when you explicitly ask it to.

## 0. One command to orient yourself

```bash
uv run python -m industry.doctor
```

The doctor checks every prerequisite (deps, data, cache, credentials) and prints
the **exact next command** for your situation. Run it first, run it whenever you're
unsure. It is read-only and never calls the API.

## 1. Things that always work (no key, no data download)

```bash
uv run python -m industry.tests          # deterministic unit tests (taxonomy, fusion, jury)
uv run python -m industry.run_industry   # gold eval (per-level P/R) + OFFLINE LLM calibration
```

> **2026-09-01: `llm_proposals.jsonl` is gone.** The frozen proposal cache was
> destroyed during the GitHub history migration (see PR #1 and
> docs/plans/2026-09-01-recovery-and-refactor-plan.md). Production outputs
> (`results/company_industry.parquet`, `curated_promoted.py`, calibration JSONs)
> are intact. Offline calibration replay and extending the jury require
> re-firing (`fire_llm`, resumable); until then the commands below that read the
> cache will report it missing.

`run_industry` reads the committed `llm_proposals.jsonl` cache directly, so it
reports LLM/jury calibration against the gold sets **without firing anything**.

## 2. Build the production company → industry table

Needs `normalized/career_steps.parquet` (the upstream normalize output).

```bash
uv run python -m industry.build_industry --propagate
```

Writes `industry/results/company_industry.parquet` (one row per company, with the
deterministic answer **and** the propose-only `llm_*` jury candidate) and the
row-level `step_industry.parquet`. The LLM never overwrites a deterministic answer.

## 3. Fire the LLM jury (optional, costs money, needs a key)

### 3a. Auth — pick one

```bash
ant auth login                                  # OAuth profile (simplest)
# or:
export ANTHROPIC_API_KEY=sk-ant-...             # API key
# or:
set -a; eval "$(ant auth print-credentials --env)"; set +a
```

### 3b. Install the SDK

```bash
uv sync --group llm
```

### 3c. Preview, then fire (every fire mode defaults to a SAFE no-API preview)

```bash
# bulk tail: a single cheap juror (Haiku) on the text-bearing residual
uv run python -m industry.fire_llm tail --limit 5000            # preview (cost, counts)
uv run python -m industry.fire_llm tail --limit 5000 --execute  # fire

# jury: the full diverse panel (Haiku+Sonnet+Opus) on the top-N residual HEAD,
#       where errors propagate to many rows and ambiguity is worth resolving
uv run python -m industry.fire_llm jury --limit 2000 --execute

# calibrate: the panel on the gold population, so calibration can map agreement
#            -> observed precision (the Alternative Annotator Test)
uv run python -m industry.fire_llm calibrate --execute
```

Then re-merge and re-check:

```bash
uv run python -m industry.build_industry --propagate     # merges the jury candidates
uv run python -m industry.run_industry                   # updated calibration
```

> **Why is `llm_candidates` 0 after a prompt change?** The cache key embeds
> `llm.PROMPT_VERSION`. The reason-before-verdict schema (v3) supersedes the older
> answer-first proposals, so they are deliberately **not** reused — re-fire to
> repopulate. This is the reproducibility contract, not a bug; the build prints a
> note when it happens.

## 3-local. Run the jury on the Ollama HOST POOL (no key, no PII egress, free)

The local backend fires across **every reachable Ollama daemon at once**: this
machine's GPU plus the Framework Desktop over tailscale (`100.73.40.75`,
128 GB unified RAM). Placement is automatic — a juror runs wherever its model
is pulled — so the big jurors (gemma3:27b, qwen3:32b, gpt-oss:120b) live on
the Framework while phi4:14b runs here, all concurrently, writing the *same*
frozen cache.

````bash
# one-time on the Framework (binds Ollama to the tailnet; needs sudo password):
ssh -t alex@100.73.40.75 'sudo mkdir -p /etc/systemd/system/ollama.service.d && \
  printf "[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0\n" | \
  sudo tee /etc/systemd/system/ollama.service.d/network.conf && \
  sudo systemctl daemon-reload && sudo systemctl restart ollama'

# (until that's done, an SSH tunnel works the same:
#    ssh -f -N -L 11435:127.0.0.1:11434 alex@100.73.40.75
#    export OLLAMA_HOSTS="local=http://127.0.0.1:11434|1,framework=http://127.0.0.1:11435|2" )

uv run python -m industry.doctor             # shows both hosts + model placement

# same modes as the cloud path, add --backend local. Preview first.
uv run python -m industry.fire_llm calibrate --backend local --execute
uv run python -m industry.fire_llm jury --backend local --limit 2000 --execute
uv run python -m industry.fire_llm tail --backend local --execute
uv run python -m industry.fire_llm head --backend local --limit 1000 --execute  # gpt-oss:120b

uv run python -m industry.build_industry --propagate
uv run python -m industry.run_industry
````

Host set: `OLLAMA_HOSTS="name=url|slots,..."` overrides; the legacy
`OLLAMA_HOST=...` still points the `local` entry somewhere else. A host that
is down is skipped (the run degrades gracefully, down to pure-cache-read if
none are up). The panel changed (bigger jurors), so re-run `calibrate` before
trusting agreement bands. If qwen3:32b is too slow on the Framework, pull the
MoE `qwen3:30b-a3b` there and swap the string in `LOCAL_JURY`.

## 4. Extend the calibration gold set (no API)

```bash
uv run python -m industry.fire_llm sample-gold --limit 150
```

Writes `industry/results/gold_worksheet.jsonl`: a stratified sample of real residual
companies with the model's suggestion and an **empty `expected` field**. Fill in the
ground-truth code for each, then paste the labeled rows into `industry/gold_residual.py`.
More gold = tighter calibration bands = a defensible auto-accept policy.

## The disciplines that keep this reproducible

- **Offline = pure cache read.** With no key, `build_industry` and `run_industry`
  only ever *read* `llm_proposals.jsonl`. The pipeline is deterministic and runnable
  with zero network.
- **Propose-only.** The jury is a review-queue candidate in `llm_*` columns; it
  never overwrites the deterministic spine (M1 curated stays precision ≈ 1.0).
- **Agreement, not eloquence.** The gating signal is jury agreement (calibratable),
  not the model's self-reported high/medium/low (near-constant, miscalibrated).
- **Frozen, content-hashed cache.** `cache_key = hash(evidence + model + prompt +
  schema)`. Any change busts the entry, so a re-run is always correct.

See `LLM_JUDGE_JURY_REPORT.md` for the research and rationale, `README.md` for the
as-built reference, and `INDUSTRY_PLAN.md` for the original design.
