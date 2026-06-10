"""M6 -- the LLM layer (propose-only, sequenced LAST, behind a frozen cache).

This is the only method that reads industry signal latent in unstructured text
(the description-bearing no-id tail, and self-employed rows where industry lives
only in the ``about``/description). It is used in two bounded modes (INDUSTRY_PLAN
§3.9), NEVER as an autonomous hot-path classifier:

  1. bootstrap-curator  -- propose industries for the HEAD company table (Opus),
     for human spot-check, to grow the curated M1 backbone cheaply.
  2. tail-proposer      -- propose industries for the text-bearing residual the
     deterministic stack (M1/M3/M5) abstains on (Haiku/Sonnet), as review-queue
     candidates only.

Design that keeps it consistent with the repo's deterministic, reproducible
contract:
  * Batch API (50% cost), structured output ENUM-constrained to the frozen
    taxonomy (the model cannot emit an off-taxonomy code), short prompts, the
    stable taxonomy catalog cached as the system prefix.
  * A FROZEN, committed result cache (``industry/llm_proposals.jsonl``) keyed by a
    hash of (evidence + model + prompt + schema). A pipeline re-run never re-hits
    the API unless inputs or the schema change. Offline (no API key) the layer is
    a pure cache read -> the pipeline stays deterministic and runnable without it.
  * Model split: Haiku 4.5 for the bulk tail, Opus 4.8 for the ambiguous head /
    gold -- industry-from-name is an easy task; Opus everywhere is overkill.

The ``anthropic`` SDK is imported lazily so the rest of the module (cache, request
construction, fusion in build_industry) works with no SDK installed.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import taxonomy as T

# Bump whenever the prompt OR the output-schema field order changes -- it is part
# of cache_key(), so any change busts stale proposals (correct: a reason-first
# answer must not be silently reused under an answer-first key). v3: reason-before-
# verdict output schema (taxonomy.output_json_schema) + disambiguation sub-questions.
PROMPT_VERSION = 3

# The jury panel: diverse Claude tiers (Haiku/Sonnet/Opus). Different tiers give
# genuinely different judgments -> real disagreement signal -> a calibratable,
# agreement-based confidence -- WITHOUT shipping scraped PII to another vendor
# (INDUSTRY_PLAN §7.9). See jury.py for the hierarchical-consensus aggregation.
MODEL_BULK = "claude-haiku-4-5"    # cheap juror / single-juror tail
MODEL_MID = "claude-sonnet-4-6"    # mid juror
MODEL_HEAD = "claude-opus-4-8"     # strong juror / head curator
JURY = (MODEL_BULK, MODEL_MID, MODEL_HEAD)
MAX_TOKENS = 512

CACHE_FILE = Path(__file__).resolve().parent / "llm_proposals.jsonl"

_SYSTEM = (
    "You are an expert business analyst assigning a company to ONE node in a "
    "fixed 4-level industry taxonomy. For each company, FIRST write the rationale "
    "(reason from the evidence to the industry), THEN choose the code -- the "
    "output schema enforces this order. Rules:\n"
    "1. Choose the single best-matching `code` from the taxonomy below.\n"
    "2. Assign the DEEPEST node the evidence clearly supports. If you are only "
    "confident at L1 or L2, return that shallower code -- do NOT guess a deeper "
    "level. Every code (any depth) is a valid answer.\n"
    "3. For a genuinely diversified conglomerate with no single primary industry, "
    "use XDV. If the evidence is too thin to place even an L1, use XOT.\n"
    "4. `confidence` reflects the evidence strength, not your eloquence.\n"
    "5. Base the decision on what the organization DOES, from its name and the "
    "roles/descriptions of the people who work there.\n"
    "6. Disambiguation for known-hard cases (decide by what the EMPLOYER does):\n"
    "   - Staffing / temp / PEO agency -> PRO.HRST (the agency's industry, not the "
    "client worksite).\n"
    "   - Holding company with one clear operating business -> that business; truly "
    "mixed -> XDV.\n"
    "   - University that also runs a hospital -> EDU.HED (the employer is the "
    "university) unless the evidence is overwhelmingly clinical.\n"
    "   - Actual government body -> PUB.GOV/PUB.DEF...; a PRIVATE firm selling to "
    "government (a defense/IT contractor) -> its own commercial industry "
    "(e.g. PUB.DEF.DCON).\n"
    "   - Read the name's HEAD NOUN: 'Smith Plumbing' -> RE.CNST.TRADE; "
    "'Smith Capital' -> FIN.\n\n"
    "TAXONOMY (code = label [NAICS]):\n"
    + T.labelled_catalog()
)


# ---------------------------------------------------------------------------
# Evidence + cache key
# ---------------------------------------------------------------------------
def evidence_text(item: dict) -> str:
    """Render the per-company evidence block (the volatile user turn)."""
    parts = [f"Company name: {item.get('display') or '(unknown)'}"]
    titles = item.get("titles") or []
    if titles:
        parts.append("Common job titles of employees: " + "; ".join(titles[:8]))
    descs = item.get("descriptions") or []
    if descs:
        parts.append("Sample descriptions:\n" + "\n".join(f"- {d}" for d in descs[:3]))
    return "\n".join(parts)


def cache_key(item: dict, model: str) -> str:
    """Stable hash of (evidence, model, prompt_version, taxonomy_version). Any
    change to inputs or schema busts the entry, so re-runs are correct."""
    payload = json.dumps(
        {
            "evidence": evidence_text(item),
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "schema_version": getattr(T, "SCHEMA_VERSION", 1),
            "n_codes": len(T.all_codes()),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Frozen cache I/O
# ---------------------------------------------------------------------------
@dataclass
class Proposal:
    key: str            # company_canonical_id
    code: str           # taxonomy code (validated)
    confidence: str     # high | medium | low (model self-report)
    rationale: str
    model: str
    input_hash: str

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


def load_cache() -> dict[str, Proposal]:
    """input_hash -> Proposal. The frozen, committed proposal store. A torn
    trailing line (crash mid-flush) is skipped with a warning -- that item is
    simply uncached, and the next run re-fires it."""
    out: dict[str, Proposal] = {}
    if not CACHE_FILE.exists():
        return out
    bad = 0
    for line in CACHE_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out_p = Proposal(**json.loads(line))
        except (json.JSONDecodeError, TypeError):
            bad += 1
            continue
        out[out_p.input_hash] = out_p
    if bad:
        print(f"[llm] WARNING: skipped {bad} malformed cache line(s) in {CACHE_FILE.name}")
    return out


def append_cache(proposals: list[Proposal]) -> None:
    with CACHE_FILE.open("a", encoding="utf-8") as fh:
        for p in proposals:
            fh.write(p.to_json() + "\n")


# ---------------------------------------------------------------------------
# Request construction (Batch API, structured output)
# ---------------------------------------------------------------------------
def _params(item: dict, model: str) -> dict:
    """MessageCreateParams for one company. Taxonomy catalog is the cached system
    prefix; only the per-company evidence varies (cache-friendly)."""
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [
            {"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": evidence_text(item)}],
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": T.output_json_schema(),
            }
        },
    }


def _custom_id(index: int) -> str:
    """Opaque per-request id for the Batch API. Company keys can't be used
    directly: they look like ``id:charles-schwab`` and the ``:`` violates the
    Batch ``custom_id`` pattern ``^[a-zA-Z0-9_-]{1,64}$``. The caller maps the
    id back to the item positionally, so the real key stays on ``Proposal``."""
    return f"i{index}"


def build_requests(items: list[dict], model: str) -> list:
    """Build Batch API Request objects (custom_id = positional, see _custom_id)."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    return [
        Request(
            custom_id=_custom_id(i),
            params=MessageCreateParamsNonStreaming(**_params(it, model)),
        )
        for i, it in enumerate(items)
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _has_credentials() -> bool:
    """True if the SDK has some way to authenticate: an API key, an auth token,
    or an ``ant auth login`` OAuth profile under $XDG_CONFIG_HOME/anthropic."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "anthropic"
    return cfg.exists() and any(cfg.iterdir())


def _parse_result_text(text: str) -> dict | None:
    try:
        d = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    code = d.get("code")
    if not T.is_valid(code):  # defensive: should be impossible with the enum
        return None
    return d


def propose(
    items: list[dict],
    *,
    model: str = MODEL_BULK,
    dry_run: bool = True,
    poll_seconds: int = 30,
    timeout_seconds: int = 24 * 3600,
) -> dict[str, Proposal]:
    """Resolve ``items`` to proposals, reading the frozen cache first.

    Cached items are returned for free. With ``dry_run`` (default) or no
    credential, uncached items are simply skipped -- the pipeline stays
    deterministic and offline-runnable. With ``dry_run=False`` and a credential,
    the uncached remainder is sent via the Batch API and appended to the frozen
    cache. A credential is either ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN (e.g.
    from ``eval "$(ant auth print-credentials --env)"``), or an ``ant auth login``
    profile the SDK resolves on its own.
    Returns {company key: Proposal} for everything resolved (cache + new).
    """
    cache = load_cache()
    resolved: dict[str, Proposal] = {}
    pending: list[dict] = []
    for it in items:
        h = cache_key(it, model)
        if h in cache:
            resolved[it["key"]] = cache[h]
        else:
            pending.append(it)

    if not pending or dry_run or not _has_credentials():
        if pending and not dry_run and not _has_credentials():
            print(f"[llm] no Anthropic credential found (set ANTHROPIC_API_KEY / "
                  f"ANTHROPIC_AUTH_TOKEN or run `ant auth login`); "
                  f"{len(pending)} items left uncached.")
        return resolved

    import anthropic

    client = anthropic.Anthropic()
    new: list[Proposal] = []
    # Batch API caps at 100k requests / 256MB per batch.
    for chunk_start in range(0, len(pending), 100_000):
        chunk = pending[chunk_start : chunk_start + 100_000]
        batch = client.messages.batches.create(requests=build_requests(chunk, model))
        print(f"[llm] submitted batch {batch.id} ({len(chunk)} items, model={model})")
        deadline = time.monotonic() + timeout_seconds
        while True:
            b = client.messages.batches.retrieve(batch.id)
            if b.processing_status == "ended":
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f"batch {batch.id} did not finish in time")
            time.sleep(poll_seconds)
        by_cid = {_custom_id(i): it for i, it in enumerate(chunk)}
        for result in client.messages.batches.results(batch.id):
            if result.result.type != "succeeded":
                continue
            msg = result.result.message
            text = next((blk.text for blk in msg.content if blk.type == "text"), "")
            parsed = _parse_result_text(text)
            if not parsed:
                continue
            it = by_cid[result.custom_id]
            p = Proposal(
                key=it["key"], code=parsed["code"],
                confidence=parsed.get("confidence", "low"),
                rationale=parsed.get("rationale", ""),
                model=model, input_hash=cache_key(it, model),
            )
            new.append(p)
            resolved[p.key] = p
    if new:
        append_cache(new)
        print(f"[llm] cached {len(new)} new proposals -> {CACHE_FILE.name}")
    return resolved


def propose_panel(
    items: list[dict], *, models: tuple[str, ...] = JURY, dry_run: bool = True,
) -> dict[str, dict[str, Proposal]]:
    """Resolve ``items`` against a PANEL of jurors -> ``{key: {model: Proposal}}``.

    Reads the frozen cache first for every (item, model); fires only the uncached
    remainder per model (offline/dry-run -> pure cache read). The frozen cache is
    keyed on (evidence, model, ...), so jurors coexist in one file and a re-run of
    one juror never re-hits the others. Pair with ``jury.aggregate`` to collapse
    each company's votes into a hierarchical-consensus verdict."""
    out: dict[str, dict[str, Proposal]] = {}
    for model in models:
        for key, p in propose(items, model=model, dry_run=dry_run).items():
            out.setdefault(key, {})[model] = p
    return out


def load_panel(items: list[dict], *, models: tuple[str, ...] = JURY) -> dict[str, dict[str, Proposal]]:
    """Offline convenience: the cached subset of ``propose_panel`` (no firing)."""
    return propose_panel(items, models=models, dry_run=True)


def cached_panel(items: list[dict]) -> dict[str, dict[str, Proposal]]:
    """Backend-AGNOSTIC cached jury votes for ``items`` -> ``{key: {model: Proposal}}``.

    Reads the frozen cache once and returns EVERY juror that voted on each item's
    current evidence, regardless of model or backend (cloud ``claude-*`` or local
    ``ollama/*``). This is what ``build_industry`` merges, so a fully-local jury, a
    cloud jury, or a mix all flow through with no code change -- the cache key
    embeds the model, so only votes matching the current evidence/prompt/schema are
    returned (stale ones are ignored)."""
    cache = load_cache()
    by_hash_keyed: dict[str, dict[str, Proposal]] = {}
    for p in cache.values():
        by_hash_keyed.setdefault(p.key, {})[p.model] = p
    out: dict[str, dict[str, Proposal]] = {}
    for it in items:
        votes = {}
        for model, p in by_hash_keyed.get(it["key"], {}).items():
            if cache_key(it, model) == p.input_hash:  # evidence/prompt/schema still match
                votes[model] = p
        if votes:
            out[it["key"]] = votes
    return out


def head_curator(vocab: list[dict], top_n: int, *, dry_run: bool = True) -> dict[str, Proposal]:
    """Mode 1: propose industries for the top-``top_n`` companies with Opus, to
    seed/extend the curated M1 backbone (human spot-checks the output)."""
    return propose(vocab[:top_n], model=MODEL_HEAD, dry_run=dry_run)


def tail_proposer(
    items: list[dict], *, dry_run: bool = True
) -> dict[str, Proposal]:
    """Mode 2: propose industries for the (already-filtered) text-bearing residual
    the deterministic stack abstained on, with Haiku, as review-queue candidates."""
    return propose(items, model=MODEL_BULK, dry_run=dry_run)
