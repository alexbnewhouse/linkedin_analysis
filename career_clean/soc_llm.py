"""LLM jury for SOC major-group coding of the uncoded role tail.

Mirrors the industry package's local-jury layer (``industry/local_llm.py`` +
the cache pattern of ``industry/llm.py``) but targets the 23 SOC 2018 major
groups (``career_clean/soc_taxonomy.py``) instead of the industry taxonomy.
The generic host pool (``industry/llm_pool.py``) is imported VERBATIM.

Honesty rules baked in here:
  * ``evidence_text`` renders ONLY fields computed by ``soc_candidates.py``
    from the string's own steps -- absent context is omitted, never invented.
  * The output schema is enum-constrained (grammar-compiled by llama-server),
    with an explicit abstention code (XUN): the rubric orders the model to
    abstain rather than guess.
  * Votes are propose-only: they land in an append-only JSONL cache keyed by
    (evidence, model, prompt/schema version); nothing downstream is touched
    until ``run_soc_jury merge``, and even that writes a NEW mappings parquet.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from career_clean import soc_taxonomy as T

CACHE_FILE = Path(__file__).resolve().parent / "results" / "soc_votes.jsonl"

# The two-juror unanimity panel: disjoint sizes/architectures on separate
# llama-server lanes. Acceptance = both emit the SAME non-XUN major group
# (industry calibration showed agreement bands are the reliable gate --
# unanimous L1 precision .977 vs .889 for verbalized self-confidence).
JURY = ("llamacpp/qwen3-4b-q4", "llamacpp/bulk-moe-q4")

# The three llamacpp lanes this pipeline may use. Passed via OLLAMA_HOSTS so
# llm_pool skips Ollama daemons entirely (the big Ollama jurors are not part
# of this panel). name=url|slots|api per llm_pool.hosts_from_env.
HOSTS_ENV = (
    "local5080=http://127.0.0.1:8090|16|llamacpp,"
    "fw4b=http://100.73.40.75:8091|8|llamacpp,"
    "fwmoe=http://100.73.40.75:8090|8|llamacpp"
)

# Hybrid-thinking families: ask for thinking off (Ollama-style key; the
# llamacpp adapter drops it, where the JSON grammar already suppresses
# thinking output -- mirrors industry/local_llm.py). bulk-moe-q4 is
# Qwen3-30B-A3B, hence listed.
_THINK_OFF_PREFIXES = ("qwen3", "bulk-moe", "deepseek-r1")

NUM_CTX = 6144  # per-slot ctx on every lane; prompt must stay well under this


def _catalog() -> str:
    return "\n".join(f"  {c} - {T.MAJOR_GROUPS[c]}" for c in sorted(T.MAJOR_GROUPS))


_SYSTEM = f"""You classify ONE job role into exactly one US SOC 2018 major group.

Valid codes:
{_catalog()}
  {T.ABSTAIN} - cannot be classified from the evidence given

Rules:
1. Judge what the person DOES day to day, not who employs them. The employer-industry line, when present, is context only: a nurse at a bank is still Healthcare Practitioners (29).
2. Follow official SOC conventions, which the "Nearest reference titles" line demonstrates: those are real entries from the official O*NET lexicon with their true major groups. When your own reading differs from a clear convention shown by close reference titles, follow the reference convention.
3. SOC convention notes: a manager who RUNS a function or department (marketing manager, benefits manager, IT manager) is Management (11); a specialist working WITHIN a function is not (account manager -> Sales 41, project management specialist -> 13). First-line supervisors stay in their workers' group (e.g. supervisors of office staff are 43).
4. Pure status titles (owner, founder, self-employed, freelancer, retired) are {T.ABSTAIN} unless the evidence says what the person actually does.
5. If the role could belong to two or more different major groups and neither the references nor the evidence settle it, answer {T.ABSTAIN}. Never guess between plausible groups.
6. Answer in the fixed JSON schema: first a rationale of at most two short sentences, then the code, then your confidence.
"""


def evidence_text(item: dict) -> str:
    """Render ONLY provided evidence; omit absent fields entirely."""
    parts = [f"Role: {item.get('role_display') or '(unknown)'}"]
    if item.get("top_titles"):
        parts.append(f"As written on profiles: {item['top_titles']}")
    if item.get("modal_seniority"):
        parts.append(f"Typical seniority: {item['modal_seniority']}")
    if item.get("industry_l1_label"):
        parts.append(f"Most common employer industry (context only): {item['industry_l1_label']}")
    if item.get("n_steps"):
        parts.append(f"Occurrences in the dataset: {item['n_steps']} career steps.")
    if item.get("anchors"):
        parts.append("Nearest reference titles (official O*NET lexicon, exact matches excluded):\n"
                     + "\n".join(f"- {a}" for a in item["anchors"]))
    return "\n".join(parts)


def cache_key(item: dict, model: str) -> str:
    """sha256 over evidence + model + prompt/schema versions + code count --
    any change to inputs or label space busts the entry (industry pattern)."""
    payload = json.dumps(
        {
            "evidence": evidence_text(item),
            "model": model,
            "prompt_version": T.PROMPT_VERSION,
            "schema_version": T.SCHEMA_VERSION,
            "n_codes": len(T.all_codes()),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class Proposal:
    key: str            # role_canonical
    code: str           # SOC major group or XUN (validated before caching)
    confidence: str     # high | medium | low (advisory only, never a gate)
    rationale: str
    model: str
    input_hash: str

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


def load_cache() -> dict[str, Proposal]:
    """input_hash -> Proposal; torn trailing lines are skipped (re-fired later)."""
    out: dict[str, Proposal] = {}
    if not CACHE_FILE.exists():
        return out
    bad = 0
    for line in CACHE_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            p = Proposal(**json.loads(line))
        except (json.JSONDecodeError, TypeError):
            bad += 1
            continue
        out[p.input_hash] = p
    if bad:
        print(f"[soc_llm] WARNING: skipped {bad} malformed cache line(s)")
    return out


def append_cache(proposals: list[Proposal]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_FILE.open("a", encoding="utf-8") as fh:
        for p in proposals:
            fh.write(p.to_json() + "\n")


def votes_by_key(items: list[dict], jurors: tuple[str, ...] = JURY) -> dict[str, dict[str, str]]:
    """{role_canonical: {model: code}} for whatever is already cached."""
    cache = load_cache()
    out: dict[str, dict[str, str]] = {}
    for it in items:
        for m in jurors:
            p = cache.get(cache_key(it, m))
            if p is not None:
                out.setdefault(it["role_canonical"], {})[m] = p.code
    return out


def unanimous_accept(codes: list[str]) -> str | None:
    """The acceptance rule, factored pure for testing: accepted iff EVERY juror
    voted and all votes are the SAME valid non-abstain major group."""
    if len(codes) != len(JURY):
        return None
    first = codes[0]
    if first == T.ABSTAIN or not T.is_valid(first):
        return None
    return first if all(c == first for c in codes) else None


# ---------------------------------------------------------------------------
# Firing
# ---------------------------------------------------------------------------
def _model_name(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def build_request(item: dict, model: str, *, schema: dict | None = None) -> dict:
    """Ollama-style chat body (the llamacpp adapter converts it); pure."""
    bare = _model_name(model)
    body = {
        "model": bare,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": evidence_text(item)},
        ],
        "stream": False,
        "format": schema if schema is not None else T.output_json_schema(),
        "keep_alive": "10m",
        "options": {"temperature": 0, "seed": 7, "num_ctx": NUM_CTX},
    }
    if bare.startswith(_THINK_OFF_PREFIXES):
        body["think"] = False
    return body


def make_pool():
    """HostPool restricted to the three llamacpp lanes (env override)."""
    os.environ["OLLAMA_HOSTS"] = HOSTS_ENV
    from industry import llm_pool
    return llm_pool.HostPool()


def fire(items: list[dict], jurors: tuple[str, ...] = JURY, *, execute: bool = False) -> dict:
    """Fire all uncached (item x juror) pairs. Dry-run returns the plan only."""
    cache = load_cache()
    pending = [
        (it, m)
        for m in jurors
        for it in items
        if cache_key(it, m) not in cache
    ]
    avg_evidence = (
        sum(len(evidence_text(it)) for it, _ in pending) // len(pending) if pending else 0
    )
    est_tokens = (len(_SYSTEM) + avg_evidence) // 4
    plan = {
        "items": len(items), "jurors": len(jurors),
        "pending_units": len(pending), "cached_units": len(items) * len(jurors) - len(pending),
        "approx_prompt_tokens_per_unit": est_tokens,
    }
    if not execute or not pending:
        return {**plan, "done": 0, "failed": 0, "skipped": 0}

    from industry import llm_pool
    pool = make_pool()
    if not pool.hosts:
        print("[soc_llm] no llamacpp lane reachable -- nothing fired")
        return {**plan, "done": 0, "failed": 0, "skipped": len(pending)}
    print(f"[soc_llm] firing {len(pending):,} units across "
          f"{[h.name for h in pool.hosts]}")

    schema = T.output_json_schema()
    units = [
        llm_pool.WorkUnit(model=_model_name(m), body=build_request(it, m, schema=schema),
                          meta=(it, m))
        for it, m in pending
    ]
    buf: list[Proposal] = []
    parse_failures = [0]

    def on_result(meta, resp):  # runs under the pool lock
        it, m = meta
        try:
            d = json.loads((resp.get("message") or {}).get("content", ""))
        except (json.JSONDecodeError, TypeError):
            parse_failures[0] += 1
            return
        code = d.get("code")
        if not T.is_valid(code):
            parse_failures[0] += 1
            return
        buf.append(Proposal(
            key=it["role_canonical"], code=code,
            confidence=d.get("confidence", "low"),
            rationale=str(d.get("rationale", ""))[:400],
            model=m, input_hash=cache_key(it, m),
        ))
        if len(buf) >= 50:
            append_cache(buf)
            buf.clear()

    stats = pool.run(units, on_result)
    if buf:
        append_cache(buf)
    print(f"[soc_llm] pool: {stats['done']:,} ok, {stats['failed']:,} failed, "
          f"{stats['skipped']:,} skipped; parse failures {parse_failures[0]:,}")
    return {**plan, **stats, "parse_failures": parse_failures[0]}
