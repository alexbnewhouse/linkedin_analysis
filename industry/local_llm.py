"""Fully-LOCAL juror backend (Ollama) -- an entirely on-device LLM jury.

Same jury, no cloud: this fires the panel against local open-weight models served
by Ollama instead of the Anthropic Batch API. It is the cleanest resolution of the
governance concern in INDUSTRY_PLAN §7.9 / LLM_JUDGE_JURY_REPORT §4.2 -- **no
scraped profile text ever leaves the machine** -- and it gives a genuinely diverse
PoLL panel from *disjoint model families* (Gemma / Phi / Llama), which is exactly
what reduces intra-model bias.

It is deliberately interchangeable with the cloud layer (``llm.py``):
  * reuses the SAME system prompt (``llm._SYSTEM``), evidence renderer
    (``llm.evidence_text``), reason-first output schema
    (``taxonomy.output_json_schema``), ``Proposal`` dataclass, cache file, and
    ``cache_key`` -- so local and cloud jurors COEXIST in one frozen cache (the key
    embeds the model string) and ``jury.aggregate`` / ``build_industry`` /
    calibration consume them without caring which backend produced a vote.
  * model strings are namespaced ``ollama/<name>`` so they are self-documenting and
    never collide with the cloud model ids in the cache.

No new Python dependency: it speaks Ollama's HTTP API with the stdlib
(``urllib``). The only "infra" is the Ollama daemon, which is already running.
Offline (daemon down) it degrades to a pure cache read, exactly like the cloud
layer -- the pipeline stays deterministic and runnable.

Enum-constrained, structured output is enforced by passing the JSON schema as
Ollama's ``format`` (constrained decoding), so a local model -- like the cloud one
-- literally cannot emit an off-taxonomy code.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from . import llm
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
# think key (the daemon rejects it).
_THINK_OFF_PREFIXES = ("qwen3", "deepseek-r1")

# Local models truncate a long prompt silently if num_ctx is too small; the
# taxonomy catalog system prompt is sizeable, so pin a generous context.
NUM_CTX = 8192
REQUEST_TIMEOUT = 240  # seconds per item; a slow first load can be ~30s


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
def _post(path: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        OLLAMA_HOST + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def is_available() -> bool:
    """True if the Ollama daemon answers (the local analog of a credential check)."""
    try:
        urllib.request.urlopen(OLLAMA_HOST + "/api/tags", timeout=3).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def list_local_models() -> list[str]:
    """Names of models the daemon has pulled (bare, e.g. ``llama3.1:8b``)."""
    try:
        data = json.loads(urllib.request.urlopen(OLLAMA_HOST + "/api/tags", timeout=5).read())
        return sorted(m["name"] for m in data.get("models", []))
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError):
        return []


def _generate_one(item: dict, model: str) -> llm.Proposal | None:
    """Fire one company at one local model -> Proposal (or None on any failure)."""
    try:
        out = _post("/api/chat", build_request(item, model), REQUEST_TIMEOUT)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    text = (out.get("message") or {}).get("content", "")
    parsed = llm._parse_result_text(text)  # noqa: SLF001  validates the code vs taxonomy
    if not parsed:
        return None
    return llm.Proposal(
        key=item["key"], code=parsed["code"],
        confidence=parsed.get("confidence", "low"),
        rationale=parsed.get("rationale", ""),
        model=model, input_hash=llm.cache_key(item, model),
    )


# ---------------------------------------------------------------------------
# Orchestration (mirrors llm.propose / propose_panel, cache-compatible)
# ---------------------------------------------------------------------------
def propose_local(
    items: list[dict], *, model: str = LOCAL_BULK, dry_run: bool = True,
    progress_every: int = 25,
) -> dict[str, llm.Proposal]:
    """Resolve ``items`` against one LOCAL model, reading the frozen cache first.

    Cached items return for free. With ``dry_run`` (default) or the daemon down,
    uncached items are skipped (pure cache read -> deterministic, offline-safe).
    Otherwise the uncached remainder is generated SERIALLY (one local GPU) and
    appended to the SAME committed cache (``llm_proposals.jsonl``)."""
    cache = llm.load_cache()
    resolved: dict[str, llm.Proposal] = {}
    pending: list[dict] = []
    for it in items:
        h = llm.cache_key(it, model)
        if h in cache:
            resolved[it["key"]] = cache[h]
        else:
            pending.append(it)

    if not pending or dry_run or not is_available():
        if pending and not dry_run and not is_available():
            print(f"[local] Ollama not reachable at {OLLAMA_HOST}; "
                  f"{len(pending)} items left uncached (start it with `ollama serve`).")
        return resolved

    print(f"[local] generating {len(pending):,} items on {model} (serial, local GPU)...")
    new: list[llm.Proposal] = []
    t0 = time.monotonic()
    for i, it in enumerate(pending, 1):
        p = _generate_one(it, model)
        if p:
            new.append(p)
            resolved[p.key] = p
        if i % progress_every == 0 or i == len(pending):
            rate = i / max(time.monotonic() - t0, 1e-6)
            eta = (len(pending) - i) / max(rate, 1e-6)
            print(f"  [local] {model}: {i:,}/{len(pending):,}  "
                  f"{rate:.1f} item/s  eta {eta/60:.1f} min  (ok={len(new):,})")
        # flush incrementally so a long run is crash-safe and re-runs resume.
        if len(new) >= 200:
            llm.append_cache(new)
            new = []
    if new:
        llm.append_cache(new)
    return resolved


def propose_local_panel(
    items: list[dict], *, models: tuple[str, ...] = LOCAL_JURY, dry_run: bool = True,
) -> dict[str, dict[str, llm.Proposal]]:
    """Resolve ``items`` against a LOCAL panel -> ``{key: {model: Proposal}}``.

    Fires one model at a time (Ollama swaps the resident model), so the whole panel
    is one GPU's worth of serial work. Pair with ``jury.aggregate``."""
    out: dict[str, dict[str, llm.Proposal]] = {}
    for model in models:
        for key, p in propose_local(items, model=model, dry_run=dry_run).items():
            out.setdefault(key, {})[model] = p
    return out
