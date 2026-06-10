# Multi-host Ollama pool for the LLM jury — design

**Date:** 2026-06-10
**Status:** approved design, pre-implementation
**Scope:** `industry/` (M6 LLM layer), reusable core for future LLM jobs in this repo

## Problem

The local-jury backend (`industry/local_llm.py`) is deliberately serial on one
16 GB GPU: one model resident at a time, one generation at a time. We have a
second machine — a Framework Desktop (AMD Strix Halo, 125 GB unified RAM, ROCm
Ollama 0.30.4, `OLLAMA_NUM_PARALLEL=2`, `OLLAMA_MAX_LOADED_MODELS=4`) reachable
over tailscale at `100.73.40.75` — that can both (a) run far bigger jurors than
the 5080 can fit (gemma3:27b, qwen3:32b, gpt-oss:120b are already pulled) and
(b) run concurrently with the local machine. Goal: use both machines for LLM
jobs — bigger jurors **and** parallel throughput — without breaking the frozen
cache / deterministic-fallback contract.

## Decisions made

1. **Approach: client-side host pool** (not shard-and-merge, not a job queue).
   One orchestrator process on this machine talks HTTP to N Ollama daemons.
2. **Connectivity: bind the Framework's Ollama to the network** via a systemd
   drop-in (`OLLAMA_HOST=0.0.0.0`), reached at `http://100.73.40.75:11434`
   inside the tailnet. No tunnels.
3. **Scope: industry-first, reusable core.** The pool lives in `industry/` but
   knows nothing about Proposals or the taxonomy — it schedules generic
   chat-request work units, so future plans can import it.
4. **Upgraded default jury: 3 big disjoint families** —
   `ollama/gemma3:27b` + `ollama/qwen3:32b` (Framework) + `ollama/phi4:14b`
   (local 5080). Bulk juror stays `ollama/llama3.1:8b` (installed on both
   hosts → work-stealing). Head curator becomes `ollama/gpt-oss:120b`
   (Framework, Opus-analog).

## Architecture

### New module: `industry/llm_pool.py` (the reusable core)

- `OllamaHost`: name, base_url, parallel slots (default: local=1, framework=2).
- `HostPool`:
  - **Discovery.** On construction, queries each host's `/api/tags`
    (3 s timeout). Unreachable hosts are dropped with a warning. The result is
    a model→hosts capability map: *a model is eligible wherever it is pulled*.
    Placement is therefore controlled by `ollama pull`, not config.
  - **Scheduling.** Work unit = `(item_index, model, request_body)`. One queue
    per model. Each host runs `parallel` worker threads; a worker pulls from
    the queue of the model it is currently serving until that queue drains,
    then moves to another eligible model's queue (minimises model-swap
    thrash; `keep_alive` keeps the weights resident). Models present on
    multiple hosts get natural work-stealing — the faster host pulls more.
  - **Failure policy.** Per work unit: 1 retry on the same host → requeue once
    to a different eligible host → give up (item left uncached; resumable).
    Host that errors repeatedly (e.g. 5 consecutive transport failures) is
    marked down and its in-flight queue items requeue. All hosts down ⇒ the
    caller degrades to a pure cache read (existing semantics preserved).
  - **Output.** Results stream to a caller-supplied callback; the callback is
    invoked under the pool's lock, so callers may append to a file directly.
  - Stdlib only (`threading`, `queue`, `urllib`) — no new dependency.

- Host set: module constant
  `DEFAULT_HOSTS = [("local", "http://127.0.0.1:11434", 1), ("framework", "http://100.73.40.75:11434", 2)]`,
  overridable with `OLLAMA_HOSTS` (comma-separated `name=url|slots` entries).
  `OLLAMA_HOST` (the existing single-host override) keeps working: if set, it
  replaces the local entry.

### Changes to `industry/local_llm.py`

- `LOCAL_JURY = ("ollama/gemma3:27b", "ollama/qwen3:32b", "ollama/phi4:14b")`
- `LOCAL_BULK = "ollama/llama3.1:8b"` (unchanged)
- `LOCAL_HEAD = "ollama/gpt-oss:120b"` (new; used by `fire_llm head --backend local`)
- `build_request` gains a per-model **think flag** table:
  - qwen3 / deepseek-r1 (hybrid-thinking): `"think": false` → clean fast JSON.
  - gpt-oss (always-thinking): leave thinking on (low effort if supported);
    parse `message.content`, ignore `message.thinking`.
  - non-thinking models: no `think` key (Ollama errors on unsupported keys).
- `propose_local` / `propose_local_panel` keep their signatures and cache
  semantics but delegate firing to `HostPool`. A panel run enqueues
  items×models at once so all hosts work concurrently (the old code fired
  one model at a time, serially).
- Cache contract unchanged: same `llm.cache_key`, same
  `llm_proposals.jsonl`, incremental flush every ~50 completions under the
  pool lock, last-write-wins by hash on load. Old jurors' cached votes remain
  valid; new jurors simply add votes (`jury.aggregate` is panel-agnostic).

### Changes to `industry/fire_llm.py`

- `--backend local` becomes pool-aware automatically; no new flag required.
- The `_PANELS["local"]` table picks up the new jury/bulk/head strings.
- Preview mode additionally prints the per-host plan: which hosts are up,
  which jury models each can serve, and a warning for any juror no host
  serves.

### Changes to `industry/doctor.py`

- New check: enumerate pool hosts, reachability, and per-host presence of
  `LOCAL_JURY`/`LOCAL_BULK`/`LOCAL_HEAD` models, with the exact `ollama pull`
  command for anything missing.

### One-time Framework setup (over SSH)

```
sudo systemctl edit ollama   # drop-in: Environment=OLLAMA_HOST=0.0.0.0
sudo systemctl restart ollama
```

All required models are already pulled on the right machines (verified
2026-06-10): Framework has gemma3:27b, qwen3:32b, gpt-oss:120b, llama3.1:8b;
local has phi4:14b, llama3.1:8b.

## Error handling summary

| failure | behaviour |
|---|---|
| Framework unreachable at start | warn, run localhost-only |
| tailscale drops mid-run | host marked down; items requeue to local if model present there, else left uncached (resume = re-run) |
| single request error/timeout | retry same host once, then requeue elsewhere once, then skip |
| all hosts down | pure frozen-cache read (existing offline semantics) |
| juror model pulled nowhere | preview warns; run skips that juror's queue |

## Performance expectations & known risk

Dense 27–32B models on Strix Halo may generate at only ~5–15 tok/s
(~10–25 s/item/juror at ~120 output tokens). Jury mode targets the top-N
residual head (≈2k items) — hours, not days, with both big jurors running
concurrently on the Framework while phi4 runs locally. If qwen3:32b proves too
slow in the pilot, the drop-in replacement is the MoE `qwen3:30b-a3b`
(~3B active params) pulled on the Framework — a one-string change.

## Calibration discipline

The panel changed, so before trusting any agreement band:
`fire_llm calibrate --backend local --execute` (panel on the gold population),
then `run_industry` to re-map agreement → observed precision. Auto-accept
policy stays human-gated until calibration proves a band.

## Testing

- **Unit (offline, in `industry/tests.py`):** affinity map from fake
  `/api/tags` payloads; queue partitioning and work-stealing with a stubbed
  transport; retry → requeue → give-up transitions; host mark-down; think-flag
  request construction per model family; callback/flush locking.
- **Integration smoke:** `fire_llm jury --limit 5 --execute --backend local`
  (real pool, both machines), then `build_industry --propagate` +
  `run_industry` to confirm the new votes merge and calibrate.

## Out of scope

- Anthropic Batch API path (unchanged).
- Auto-accept policy changes, taxonomy/prompt changes (cache keys untouched).
- A general job-queue service; >2 hosts is config, not new design.
