"""Fully-LOCAL juror backend (Ollama) -- an entirely on-device LLM jury.

Same jury, no cloud: this fires the panel against local open-weight models served
by Ollama instead of the Anthropic Batch API. It is the cleanest resolution of the
governance concern in INDUSTRY_PLAN §7.9 / LLM_JUDGE_JURY_REPORT §4.2 -- **no
scraped profile text ever leaves the machines we own** -- and it gives a genuinely
diverse PoLL panel from *disjoint model families* (Gemma / Qwen / Phi), which is
exactly what reduces intra-model bias.

It is deliberately interchangeable with the cloud layer (``llm.py``):
  * reuses the SAME system prompt (``llm._SYSTEM``), evidence renderer
    (``llm.evidence_text``), reason-first output schema
    (``taxonomy.output_json_schema``), ``Proposal`` dataclass, cache file, and
    ``cache_key`` -- so local and cloud jurors COEXIST in one frozen cache (the key
    embeds the model string) and ``jury.aggregate`` / ``build_industry`` /
    calibration consume them without caring which backend produced a vote.
  * model strings are namespaced ``ollama/<name>`` so they are self-documenting and
    never collide with the cloud model ids in the cache.

Firing fans out across EVERY reachable Ollama host via ``llm_pool`` (this
machine's GPU plus any tailnet boxes): all uncached (item x juror) pairs go into
one pool run, and a juror executes wherever its model is pulled -- placement is
``ollama pull``, not config. No new Python dependency: it speaks Ollama's HTTP
API with the stdlib (``urllib``). The only "infra" is the Ollama daemons.
Offline (no host reachable) it degrades to a pure cache read, exactly like the
cloud layer -- the pipeline stays deterministic and runnable.

Enum-constrained, structured output is enforced by passing the JSON schema as
Ollama's ``format`` (constrained decoding), so a local model -- like the cloud one
-- literally cannot emit an off-taxonomy code.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import llm
from . import llm_pool
from . import taxonomy as T

# Where the Ollama daemon listens (override with OLLAMA_HOST in the environment).
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

# The local jury: three DISJOINT model families (the PoLL diversity that cuts
# intra-model bias), sized to where they run -- the two big jurors live on the
# Framework Desktop (128GB unified RAM; both stay resident, OLLAMA_MAX_LOADED_
# MODELS=4) and phi4 on the local 16GB GPU, so the whole panel fires in
# parallel across machines. Placement is automatic: a juror runs wherever its
# model is pulled (llm_pool discovers /api/tags). Swap freely -- a juror is
# just a string.
LOCAL_JURY = ("ollama/gemma3:27b", "ollama/qwen3:32b", "ollama/phi4:14b")
LOCAL_BULK = "ollama/llama3.1:8b"   # cheap juror for the bulk tail (on BOTH hosts)
LOCAL_HEAD = "ollama/gpt-oss:120b"  # head curator (the local Opus-analog)

# Hybrid-thinking families: disable thinking for clean, fast, schema-shaped
# JSON. Always-thinking models (gpt-oss) keep their default; we read only
# message.content, never message.thinking. Non-thinking models must NOT get a
# think key (the daemon may reject or ignore it -- omit the key to be safe).
_THINK_OFF_PREFIXES = ("qwen3", "deepseek-r1")

# Local models truncate a long prompt silently if num_ctx is too small; the
# taxonomy catalog system prompt is sizeable, so pin a generous context.
NUM_CTX = 8192


def _model_name(model: str) -> str:
    """``ollama/llama3.1:8b`` -> ``llama3.1:8b`` (the bare name the daemon wants)."""
    return model.split("/", 1)[1] if model.startswith("ollama/") else model


def build_request(item: dict, model: str) -> dict:
    """The Ollama ``/api/chat`` body for one company (pure -- unit-testable)."""
    bare = _model_name(model)
    body = {
        "model": bare,
        "messages": [
            {"role": "system", "content": llm._SYSTEM},  # noqa: SLF001  shared rubric
            {"role": "user", "content": llm.evidence_text(item)},
        ],
        "stream": False,
        "format": T.output_json_schema(),     # enum-constrained, reason-first
        "keep_alive": "10m",                  # keep the model resident across items
        "options": {"temperature": 0, "seed": 7, "num_ctx": NUM_CTX},
    }
    if bare.startswith(_THINK_OFF_PREFIXES):
        body["think"] = False
    return body


# ---------------------------------------------------------------------------
# Daemon I/O
# ---------------------------------------------------------------------------
def is_available() -> bool:
    """True if at least one pool host answers (the local analog of a credential
    check). Prints a warning line per unreachable host as a side effect."""
    return bool(llm_pool.HostPool().hosts)


def list_local_models() -> list[str]:
    """Names of models the daemon has pulled (bare, e.g. ``llama3.1:8b``)."""
    # TODO(task 6): remove once doctor uses the pool
    try:
        data = json.loads(urllib.request.urlopen(OLLAMA_HOST + "/api/tags", timeout=5).read())
        return sorted(m["name"] for m in data.get("models", []))
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------------------
# Orchestration (mirrors llm.propose / propose_panel, cache-compatible)
# ---------------------------------------------------------------------------
def _fire(pending: list[tuple[dict, str]], pool: llm_pool.HostPool) -> list[llm.Proposal]:
    """Fire (item, model) pairs across the host pool. Successes append to the
    frozen cache incrementally (crash-safe; the callback runs under the pool
    lock). Returns the new Proposals."""
    units = [
        llm_pool.WorkUnit(model=_model_name(model),
                          body=build_request(it, model), meta=(it, model))
        for it, model in pending
    ]
    new: list[llm.Proposal] = []
    buf: list[llm.Proposal] = []

    def on_result(meta: tuple[dict, str], resp: dict) -> None:  # under pool lock
        it, model = meta
        parsed = llm._parse_result_text(  # noqa: SLF001
            (resp.get("message") or {}).get("content", ""))
        if not parsed:
            return
        p = llm.Proposal(
            key=it["key"], code=parsed["code"],
            confidence=parsed.get("confidence", "low"),
            rationale=parsed.get("rationale", ""),
            model=model, input_hash=llm.cache_key(it, model),
        )
        new.append(p)
        buf.append(p)
        if len(buf) >= 50:           # incremental flush -> long runs are crash-safe
            llm.append_cache(buf)
            buf.clear()

    stats = pool.run(units, on_result)
    if buf:
        llm.append_cache(buf)
    print(f"[local] pool run: {stats['done']:,} ok, {stats['failed']:,} failed, "
          f"{stats['skipped']:,} skipped (not pulled anywhere); "
          f"{len(new):,} proposals cached")
    return new


def propose_local_panel(
    items: list[dict], *, models: tuple[str, ...] = LOCAL_JURY, dry_run: bool = True,
    pool: llm_pool.HostPool | None = None,
) -> dict[str, dict[str, llm.Proposal]]:
    """Resolve ``items`` against a LOCAL panel -> ``{key: {model: Proposal}}``.

    Reads the frozen cache first for every (item, model); with ``dry_run`` the
    uncached remainder is skipped (pure cache read -> deterministic, offline-
    safe). Otherwise ALL uncached (item, model) pairs are enqueued in ONE pool
    run, so every host works concurrently (big jurors on the framework, phi4 on
    the local GPU). Pair with ``jury.aggregate``."""
    cache = llm.load_cache()
    out: dict[str, dict[str, llm.Proposal]] = {}
    pending: list[tuple[dict, str]] = []
    for model in models:
        for it in items:
            h = llm.cache_key(it, model)
            if h in cache:
                out.setdefault(it["key"], {})[model] = cache[h]
            else:
                pending.append((it, model))
    if not pending or dry_run:
        return out
    pool = pool or llm_pool.HostPool()
    if not pool.hosts:
        print(f"[local] no Ollama host reachable; {len(pending)} votes left uncached "
              f"(start one with `ollama serve`, or bring up the framework).")
        return out
    print(f"[local] firing {len(pending):,} (item x juror) units across "
          f"{len(pool.hosts)} host(s): {[h.name for h in pool.hosts]}")
    for p in _fire(pending, pool):
        out.setdefault(p.key, {})[p.model] = p
    return out


def propose_local(
    items: list[dict], *, model: str = LOCAL_BULK, dry_run: bool = True,
    progress_every: int = 25,  # kept for API compat; the pool prints progress
    pool: llm_pool.HostPool | None = None,
) -> dict[str, llm.Proposal]:
    """Resolve ``items`` against ONE local model via the host pool (single-model
    case of propose_local_panel; same cache semantics)."""
    panel = propose_local_panel(items, models=(model,), dry_run=dry_run, pool=pool)
    return {key: votes[model] for key, votes in panel.items() if model in votes}
