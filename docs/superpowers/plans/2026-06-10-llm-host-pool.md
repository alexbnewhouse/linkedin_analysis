# Multi-host Ollama Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fire the industry LLM jury across both machines (local RTX 5080 + Framework Desktop over tailscale) concurrently, with bigger jurors, without changing the frozen-cache contract.

**Architecture:** A stdlib-only `industry/llm_pool.py` schedules `(model, request)` work units across N Ollama daemons; eligibility = "model is pulled on that host"; per-model queues with sticky workers + work stealing; retry → cross-host requeue → give-up. `local_llm.py` keeps its public API but delegates firing to the pool and upgrades the default panel (gemma3:27b + qwen3:32b on the Framework, phi4:14b local; gpt-oss:120b head curator; llama3.1:8b bulk).

**Tech Stack:** Python 3.14 stdlib only (`threading`, `queue`/`collections.deque`, `urllib`). Tests use the repo's in-house harness (`industry/tests.py`, `check()` + `main()` tuple — **not pytest**), run via `uv run python -m industry.tests`.

**Spec:** `docs/superpowers/specs/2026-06-10-llm-host-pool-design.md`

---

### Task 1: `industry/llm_pool.py` — hosts, env parsing, discovery

**Files:**
- Create: `industry/llm_pool.py`
- Test: `industry/tests.py` (new `test_llm_pool()`, registered in `main()`)

- [ ] **Step 1: Write the failing test**

Add to `industry/tests.py`, after `test_local_llm` (around line 208), the first slice of `test_llm_pool`:

```python
# ------------------------------------------------------------ llm host pool
def test_llm_pool() -> None:
    print("llm host pool")
    from . import llm_pool as P

    # OLLAMA_HOSTS env spec: "name=url|slots,..." (slots default 1, urls rstripped)
    hs = P.hosts_from_env({"OLLAMA_HOSTS": "a=http://a:1/|3, b=http://b:2"})
    check("OLLAMA_HOSTS parsed",
          [(h.name, h.base_url, h.parallel) for h in hs]
          == [("a", "http://a:1", 3), ("b", "http://b:2", 1)])
    # legacy OLLAMA_HOST replaces the local default entry only
    hs = P.hosts_from_env({"OLLAMA_HOST": "http://gpu:11434"})
    check("OLLAMA_HOST overrides local entry",
          hs[0].name == "local" and hs[0].base_url == "http://gpu:11434"
          and hs[1].name == "framework")
    # no env -> the two default hosts
    hs = P.hosts_from_env({})
    check("default hosts", [h.name for h in hs] == ["local", "framework"])

    # discovery: unreachable host (fetch_tags -> None) is dropped; models recorded
    tags = {"http://a:1": ["m1", "m2"], "http://b:2": None}
    pool = P.HostPool(
        [P.OllamaHost("a", "http://a:1", 1), P.OllamaHost("b", "http://b:2", 2)],
        fetch_tags=lambda u: tags[u], transport=lambda h, b: {})
    check("unreachable host dropped", [h.name for h in pool.hosts] == ["a"])
    check("serves() uses discovered tags",
          [h.name for h in pool.serves("m1")] == ["a"] and pool.serves("zzz") == [])
```

And register it in `main()` — change the tuple to:

```python
    for t in (test_taxonomy, test_codes_resolve, test_precedence, test_rows,
              test_occupation_prior, test_level_scores, test_llm, test_jury,
              test_local_llm, test_llm_pool, test_gold_residual):
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run python -m industry.tests`
Expected: crash with `ImportError: cannot import name 'llm_pool'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Create `industry/llm_pool.py` (hosts + discovery only; `run()` comes in Task 2)**

```python
"""Multi-host Ollama pool -- the reusable scheduling core for local LLM jobs.

A pool of Ollama daemons (this machine's GPU + any tailnet boxes) consumed as
one capacity. Work units are (model, request-body) pairs; a model is ELIGIBLE
on every host whose daemon has it pulled -- placement is controlled by
`ollama pull`, not by config. Per-model queues with sticky workers minimise
model swapping; a model pulled on several hosts gets natural work stealing
(the faster host simply takes more). Stdlib only (threading/deque/urllib) --
the same no-new-dependency contract as the rest of the industry package.

This module knows NOTHING about taxonomies, Proposals, or caches: it moves
JSON bodies to daemons and hands JSON responses to a callback (invoked under
the pool lock, so callers may append to a file directly). The jury semantics
live in local_llm.py, which is this module's first client.

Failure policy per unit: one retry on the same host -> one requeue to a
different eligible host -> give up (left uncached; a re-run resumes via the
frozen cache). A host that fails HOST_MAX_CONSECUTIVE_FAILURES units in a row
is marked down for the rest of the run and its unservable queue drains as
failures. All hosts down -> callers degrade to a pure cache read.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field

# (name, base_url, parallel slots). Slots mirror each daemon's OLLAMA_NUM_PARALLEL
# (framework runs OLLAMA_NUM_PARALLEL=2 / OLLAMA_MAX_LOADED_MODELS=4).
DEFAULT_HOSTS: tuple[tuple[str, str, int], ...] = (
    ("local", "http://127.0.0.1:11434", 1),
    ("framework", "http://100.73.40.75:11434", 2),
)
TAGS_TIMEOUT = 3        # seconds: the discovery probe
REQUEST_TIMEOUT = 600   # seconds: one generation (27-32B on Strix Halo is slow)
HOST_MAX_CONSECUTIVE_FAILURES = 5


@dataclass
class OllamaHost:
    name: str
    base_url: str
    parallel: int = 1
    models: frozenset[str] = frozenset()  # bare tags from /api/tags (discovery)


@dataclass
class WorkUnit:
    model: str            # bare daemon name, e.g. "gemma3:27b"
    body: dict            # full /api/chat body (already names the model)
    meta: object = None   # opaque caller token, handed back via on_result
    attempts: int = 0     # attempts on the current host
    requeues: int = 0     # cross-host requeues so far (max 1)
    tried: set[str] = field(default_factory=set)  # host names that failed it


def hosts_from_env(env: dict[str, str] | None = None) -> list[OllamaHost]:
    """Host set from the environment.

    OLLAMA_HOSTS="name=url|slots,name=url" wins outright; otherwise the
    DEFAULT_HOSTS pair, with the legacy single-host OLLAMA_HOST (used by the
    old serial backend) replacing the `local` entry if set."""
    e = os.environ if env is None else env
    spec = (e.get("OLLAMA_HOSTS") or "").strip()
    if spec:
        out: list[OllamaHost] = []
        for entry in spec.split(","):
            entry = entry.strip()
            if not entry:
                continue
            name, _, rest = entry.partition("=")
            if not rest:
                raise ValueError(
                    f"bad OLLAMA_HOSTS entry: {entry!r} (expected name=url|slots)")
            url, _, slots = rest.partition("|")
            out.append(OllamaHost(name=name, base_url=url.rstrip("/"),
                                  parallel=int(slots or 1)))
        return out
    hosts = [OllamaHost(name=n, base_url=u, parallel=p) for n, u, p in DEFAULT_HOSTS]
    single = (e.get("OLLAMA_HOST") or "").strip()
    if single:
        hosts[0] = OllamaHost(name="local", base_url=single.rstrip("/"),
                              parallel=hosts[0].parallel)
    return hosts


def _fetch_tags(base_url: str) -> list[str] | None:
    """Installed model tags on one daemon, or None if unreachable."""
    try:
        with urllib.request.urlopen(base_url + "/api/tags", timeout=TAGS_TIMEOUT) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", [])]
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError):
        return None


def _http_chat(host: OllamaHost, body: dict) -> dict:
    req = urllib.request.Request(
        host.base_url + "/api/chat", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        return json.loads(r.read())


def discover(hosts: list[OllamaHost], fetch_tags=_fetch_tags) -> list[OllamaHost]:
    """Probe each host once; drop unreachable ones (with a warning)."""
    live: list[OllamaHost] = []
    for h in hosts:
        tags = fetch_tags(h.base_url)
        if tags is None:
            print(f"[pool] {h.name} ({h.base_url}) unreachable -- skipping")
            continue
        live.append(OllamaHost(h.name, h.base_url, h.parallel, frozenset(tags)))
    return live


class HostPool:
    """Schedules WorkUnits across the discovered live hosts."""

    def __init__(self, hosts: list[OllamaHost] | None = None, *,
                 fetch_tags=_fetch_tags, transport=_http_chat):
        self.hosts = discover(hosts if hosts is not None else hosts_from_env(),
                              fetch_tags)
        self.transport = transport

    def serves(self, model: str) -> list[OllamaHost]:
        return [h for h in self.hosts if model in h.models]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run python -m industry.tests`
Expected: all PASS, including the five new `llm host pool` checks.

- [ ] **Step 5: Commit**

```bash
git add industry/llm_pool.py industry/tests.py
git commit -m "feat(industry): llm_pool hosts, env parsing, /api/tags discovery"
```

---

### Task 2: `HostPool.run()` — scheduling, retry/requeue, mark-down

**Files:**
- Modify: `industry/llm_pool.py` (add `run()` to `HostPool`)
- Test: `industry/tests.py` (extend `test_llm_pool`)

- [ ] **Step 1: Write the failing tests**

Append to `test_llm_pool()`:

```python
    import time as _time

    # affinity + work stealing: "big" only on b; "small" on both. Host a is
    # slowed so b provably steals "small" after draining "big".
    runs: list[tuple[str, str]] = []   # (host, model) per executed unit
    def rec(h, body):
        runs.append((h.name, body["model"]))
        _time.sleep(0.005 if h.name == "a" else 0)
        return {"message": {"content": "ok"}}
    tag2 = {"http://a": ["small"], "http://b": ["small", "big"]}
    pool = P.HostPool([P.OllamaHost("a", "http://a", 1), P.OllamaHost("b", "http://b", 1)],
                      fetch_tags=lambda u: tag2[u], transport=rec)
    got: list[object] = []
    units = [P.WorkUnit("big", {"model": "big"}, meta=i) for i in range(5)] \
          + [P.WorkUnit("small", {"model": "small"}, meta=5 + i) for i in range(40)]
    res = pool.run(units, lambda meta, r: got.append(meta), progress_every=10**9)
    check("pool: all units done", res == {"done": 45, "failed": 0, "skipped": 0}
          and sorted(got) == list(range(45)))
    check("pool: big pinned to b", {h for h, m in runs if m == "big"} == {"b"})
    check("pool: small stolen by both", {h for h, m in runs if m == "small"} == {"a", "b"})

    # unit for a model no live host serves -> skipped, not hung
    res = pool.run([P.WorkUnit("nowhere", {"model": "nowhere"})], lambda m, r: None)
    check("pool: unservable skipped", res == {"done": 0, "failed": 0, "skipped": 1})

    # same-host retry: first call raises, second succeeds
    calls = {"n": 0}
    def flaky(h, body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient")
        return {"message": {"content": "ok"}}
    pool = P.HostPool([P.OllamaHost("a", "http://a", 1)],
                      fetch_tags=lambda u: ["m"], transport=flaky)
    res = pool.run([P.WorkUnit("m", {"model": "m"})], lambda m, r: None)
    check("pool: same-host retry", res["done"] == 1 and calls["n"] == 2)

    # cross-host rescue + mark-down: a always fails, b always works. All 10
    # units must finish on b, and a must be marked down after 5 consecutive
    # failures (bounding its wasted calls to <= 2 attempts x 5 units).
    a_calls = {"n": 0}
    def ab(h, body):
        if h.name == "a":
            a_calls["n"] += 1
            raise OSError("a is broken")
        return {"message": {"content": "ok"}}
    tag3 = {"http://a": ["m"], "http://b": ["m"]}
    pool = P.HostPool([P.OllamaHost("a", "http://a", 1), P.OllamaHost("b", "http://b", 1)],
                      fetch_tags=lambda u: tag3[u], transport=ab)
    res = pool.run([P.WorkUnit("m", {"model": "m"}, meta=i) for i in range(10)],
                   lambda m, r: None)
    check("pool: failing host's work rescued", res["done"] == 10 and res["failed"] == 0)
    check("pool: host marked down bounds damage", a_calls["n"] <= 10)

    # every host fails -> all units fail, run still terminates
    def dead(h, body):
        raise OSError("all dead")
    pool = P.HostPool([P.OllamaHost("a", "http://a", 1)],
                      fetch_tags=lambda u: ["m"], transport=dead)
    res = pool.run([P.WorkUnit("m", {"model": "m"}, meta=i) for i in range(3)],
                   lambda m, r: None)
    check("pool: total failure terminates", res["done"] == 0 and res["failed"] == 3)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run python -m industry.tests`
Expected: `AttributeError: 'HostPool' object has no attribute 'run'`.

- [ ] **Step 3: Implement `run()`**

Add inside `class HostPool` (after `serves`):

```python
    def run(self, units: list[WorkUnit], on_result, *, progress_every: int = 25) -> dict:
        """Run ``units`` across the live hosts. ``on_result(meta, response)`` is
        called under the pool lock for each success (safe to append to a file).
        Returns ``{"done": n, "failed": n, "skipped": n}``; failed/skipped units
        are simply left uncached, so a re-run resumes them."""
        lock = threading.Lock()
        queues: dict[str, deque[WorkUnit]] = {}
        skipped = 0
        for u in units:
            if self.serves(u.model):
                queues.setdefault(u.model, deque()).append(u)
            else:
                skipped += 1
        if skipped:
            print(f"[pool] {skipped} unit(s) skipped -- model not pulled on any live host")
        state = {"done": 0, "failed": 0,
                 "outstanding": sum(len(q) for q in queues.values())}
        down: set[str] = set()
        fail_streak: dict[str, int] = {h.name: 0 for h in self.hosts}
        t0 = time.monotonic()

        def finish(u: WorkUnit, ok: bool) -> None:  # under lock
            state["done" if ok else "failed"] += 1
            state["outstanding"] -= 1
            if ok and state["done"] % progress_every == 0:
                rate = state["done"] / max(time.monotonic() - t0, 1e-6)
                eta = state["outstanding"] / max(rate, 1e-6)
                print(f"  [pool] {state['done']:,} done  {rate:.2f} item/s  "
                      f"~{eta / 60:.0f} min left  (failed={state['failed']})")

        def take(host: OllamaHost, current: str | None) -> WorkUnit | None:  # under lock
            order = ([current] if current in queues else []) \
                  + [m for m in queues if m != current]
            for m in order:
                if m in host.models and queues.get(m):
                    u = queues[m].popleft()
                    if not queues[m]:
                        del queues[m]
                    return u
            return None

        def prune_unservable() -> None:  # under lock, after a mark-down
            for m in list(queues):
                if not any(h.name not in down for h in self.serves(m)):
                    for u in queues.pop(m):
                        finish(u, ok=False)

        def requeue_or_fail(u: WorkUnit, host: OllamaHost) -> None:  # under lock
            u.tried.add(host.name)
            alt = [h for h in self.serves(u.model)
                   if h.name not in u.tried and h.name not in down]
            if u.requeues < 1 and alt:
                u.requeues += 1
                u.attempts = 0
                queues.setdefault(u.model, deque()).append(u)
            else:
                finish(u, ok=False)

        def worker(host: OllamaHost) -> None:
            current: str | None = None
            while True:
                with lock:
                    if state["outstanding"] == 0 or host.name in down:
                        return
                    u = take(host, current)
                if u is None:
                    time.sleep(0.25)  # another host may yet requeue work to us
                    continue
                current = u.model
                while True:
                    u.attempts += 1
                    try:
                        resp = self.transport(host, u.body)
                    except Exception:
                        resp = None
                    if resp is not None:
                        with lock:
                            fail_streak[host.name] = 0
                            on_result(u.meta, resp)
                            finish(u, ok=True)
                        break
                    if u.attempts < 2:
                        continue  # the one same-host retry
                    with lock:
                        fail_streak[host.name] += 1
                        if fail_streak[host.name] >= HOST_MAX_CONSECUTIVE_FAILURES:
                            down.add(host.name)
                            print(f"[pool] {host.name} marked down after "
                                  f"{fail_streak[host.name]} consecutive failures")
                        requeue_or_fail(u, host)
                        if host.name in down:
                            prune_unservable()
                    break

        threads = [threading.Thread(target=worker, args=(h,), daemon=True,
                                    name=f"pool-{h.name}-{i}")
                   for h in self.hosts for i in range(h.parallel)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return {"done": state["done"], "failed": state["failed"], "skipped": skipped}
```

Note one accepted simplification: a cross-host-requeued unit goes back into the shared per-model queue, so the host that failed it *may* take it again; `requeues < 1` bounds this (it then fails permanently), and the mark-down removes the pathological case. Termination is guaranteed: every unit ends in `finish()` exactly once, workers exit when `outstanding == 0`, and `prune_unservable()` fails queued units no live host can serve.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run python -m industry.tests`
Expected: all PASS (the pool section has 12 checks now). The suite must finish in seconds — if it hangs, the termination logic is wrong; kill and fix before committing.

- [ ] **Step 5: Commit**

```bash
git add industry/llm_pool.py industry/tests.py
git commit -m "feat(industry): HostPool.run -- sticky per-model scheduling, retry/requeue, host mark-down"
```

---

### Task 3: `local_llm.py` — new panel constants + think flags

**Files:**
- Modify: `industry/local_llm.py:44-73` (constants + `build_request`)
- Test: `industry/tests.py` (extend `test_local_llm`)

- [ ] **Step 1: Write the failing tests**

In `test_local_llm` (industry/tests.py:187), append:

```python
    # upgraded panel: 3 disjoint families sized to where they run
    check("jury is 3 disjoint big families",
          local_llm.LOCAL_JURY == ("ollama/gemma3:27b", "ollama/qwen3:32b",
                                   "ollama/phi4:14b"))
    check("head curator defined", local_llm.LOCAL_HEAD == "ollama/gpt-oss:120b")
    # think flags: hybrid-thinking families get think=false (clean fast JSON);
    # everything else omits the key (Ollama rejects it on non-thinking models).
    item = {"key": "id:x", "display": "Acme Corp"}
    check("qwen3 think off",
          local_llm.build_request(item, "ollama/qwen3:32b").get("think") is False)
    check("deepseek think off",
          local_llm.build_request(item, "ollama/deepseek-r1:8b").get("think") is False)
    check("gemma has no think key",
          "think" not in local_llm.build_request(item, "ollama/gemma3:27b"))
    check("gpt-oss keeps default thinking",
          "think" not in local_llm.build_request(item, "ollama/gpt-oss:120b"))
```

(`test_local_llm` already defines an `item`; reuse it if so and drop the local one — keep names consistent with the existing body.)

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run python -m industry.tests`
Expected: FAIL on "jury is 3 disjoint big families" (old panel) and "qwen3 think off".

- [ ] **Step 3: Implement**

In `industry/local_llm.py`, replace the constants block (lines 44-48):

```python
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
```

And in `build_request` (line 61), build the body in a variable and add the flag before returning:

```python
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run python -m industry.tests`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add industry/local_llm.py industry/tests.py
git commit -m "feat(industry): upgraded local jury (27b/32b/14b + gpt-oss head) and think flags"
```

---

### Task 4: `local_llm.py` — pool-backed firing

**Files:**
- Modify: `industry/local_llm.py` (replace `_generate_one`/`propose_local`/`propose_local_panel`/`is_available`; delete `list_local_models`)
- Test: `industry/tests.py` (extend `test_local_llm`)

- [ ] **Step 1: Write the failing test**

Append to `test_local_llm`:

```python
    # pool-backed firing: a fake transport proves items x models fan out across
    # hosts in ONE pool run and land in the cache via the normal Proposal path.
    from . import llm_pool as P
    import json as _json
    fired: list[tuple[str, str]] = []
    def fake_chat(h, body):
        fired.append((h.name, body["model"]))
        return {"message": {"content": _json.dumps(
            {"rationale": "test", "code": "FIN", "confidence": "low"})}}
    fake_pool = P.HostPool(
        [P.OllamaHost("a", "http://a", 1), P.OllamaHost("b", "http://b", 1)],
        fetch_tags=lambda u: (["gemma3:27b", "qwen3:32b"] if u == "http://b"
                              else ["phi4:14b"]),
        transport=fake_chat)
    items = [{"key": "id:pooltest", "display": "Pool Test Co"}]
    out = local_llm.propose_local_panel(items, models=local_llm.LOCAL_JURY,
                                        dry_run=False, pool=fake_pool)
    check("panel fans out across hosts",
          sorted(fired) == [("a", "phi4:14b"), ("b", "gemma3:27b"), ("b", "qwen3:32b")])
    check("panel returns all jurors",
          set(out.get("id:pooltest", {})) == set(local_llm.LOCAL_JURY))
    check("votes are valid Proposals",
          all(p.code == "FIN" for p in out["id:pooltest"].values()))
    # the test wrote real cache entries -- prune them so the frozen cache stays clean
    lines = [ln for ln in llm.CACHE_FILE.read_text().splitlines()
             if '"id:pooltest"' not in ln]
    llm.CACHE_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run python -m industry.tests`
Expected: `TypeError: propose_local_panel() got an unexpected keyword argument 'pool'`.

- [ ] **Step 3: Implement**

In `industry/local_llm.py`: add `from . import llm_pool` to the imports; **delete** `_generate_one` and `list_local_models` (doctor stops using it in Task 6); replace `is_available`, `propose_local`, and `propose_local_panel` with:

```python
def is_available() -> bool:
    """True if at least one pool host answers (the local analog of a credential
    check). Prints a warning line per unreachable host as a side effect."""
    return bool(llm_pool.HostPool().hosts)


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
```

Also update the module docstring's "serial on one GPU" claims (lines 1-27) to describe the pool: same cache/prompt/schema contracts, but firing now fans out across every reachable Ollama host, with placement = where a model is pulled.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run python -m industry.tests`
Expected: all PASS, including the older "offline local propose safe" check (dry-run path never constructs a pool).

- [ ] **Step 5: Verify the cache file is unchanged**

Run: `git status --short industry/llm_proposals.jsonl`
Expected: no diff (the test pruned its own entries).

- [ ] **Step 6: Commit**

```bash
git add industry/local_llm.py industry/tests.py
git commit -m "feat(industry): pool-backed local firing -- all hosts work one panel concurrently"
```

---

### Task 5: `fire_llm.py` — head curator + per-host plan in preview

**Files:**
- Modify: `industry/fire_llm.py:142-147` (`_PANELS`), `industry/fire_llm.py:190-194` (preview), docstring lines 8-15
- Modify: `industry/local_llm.py` (new `pool_plan()` helper)

- [ ] **Step 1: Add `pool_plan()` to `local_llm.py`**

```python
def pool_plan(models: tuple[str, ...]) -> None:
    """Print which live host serves which of ``models`` (preview helper)."""
    pool = llm_pool.HostPool()
    if not pool.hosts:
        print("  [pool] NO Ollama host reachable -- firing would be a no-op")
        return
    for h in pool.hosts:
        served = [m for m in models if _model_name(m) in h.models]
        print(f"  [pool] {h.name} {h.base_url} x{h.parallel}: "
              f"serves {served or 'none of this panel'}")
    for m in models:
        if not pool.serves(_model_name(m)):
            print(f"  [pool] WARNING: {m} not pulled on any live host -> "
                  f"`ollama pull {_model_name(m)}` (on the host that should run it)")
```

- [ ] **Step 2: Wire into `fire_llm.py`**

In `_PANELS` (line 142), change the local head entry:

```python
    "local": {"tail": (local_llm.LOCAL_BULK,), "jury": local_llm.LOCAL_JURY,
              "head": (local_llm.LOCAL_HEAD,), "calibrate": local_llm.LOCAL_JURY},
```

Replace the local-preview block (lines 190-193):

```python
    if local:
        local_llm.pool_plan(models)
        gens = len(items) * len(models)
        print(f"  LOCAL on the Ollama host pool: $0. ~{gens:,} generations total, "
              f"fanned out across every live host above -- use --limit for a pilot.")
```

And in the execute branch (line 212), update the message:

```python
        print(f"\ngenerating {len(items):,} items x {len(models)} local juror(s) "
              f"across the host pool...")
```

Update the module docstring's mode table (line 8-16) to note `head` uses
`gpt-oss:120b` locally, and the `--backend local` help string (line 154) to
"local=Ollama host pool (this machine + tailnet hosts), no PII egress".

- [ ] **Step 3: Run the test suite + a real preview**

Run: `uv run python -m industry.tests` — expected: all PASS.
Run: `uv run python -m industry.fire_llm jury --limit 10 --backend local`
Expected: per-juror cached counts, then a `[pool]` line per reachable host
(framework will show unreachable until Task 6 — that's correct), no firing
(no `--execute`).

- [ ] **Step 4: Commit**

```bash
git add industry/fire_llm.py industry/local_llm.py
git commit -m "feat(industry): fire_llm pool plan preview + gpt-oss head curator"
```

---

### Task 6: `doctor.py` — pool-aware checks

**Files:**
- Modify: `industry/doctor.py:69-83` (section 3b) and `industry/doctor.py:173-180` (`_full_run` local variant text)

- [ ] **Step 1: Replace section 3b**

```python
    # 3b. fully-local backend (Ollama host pool) -- no key, no PII egress --------
    from . import local_llm, llm_pool
    pool = llm_pool.HostPool()
    if pool.hosts:
        for h in pool.hosts:
            _line(_ok, f"Ollama host '{h.name}'",
                  f"{h.base_url}  x{h.parallel} parallel, {len(h.models)} models pulled")
        want = dict.fromkeys(
            local_llm._model_name(m)  # noqa: SLF001
            for m in (*local_llm.LOCAL_JURY, local_llm.LOCAL_BULK, local_llm.LOCAL_HEAD))
        for bare in want:
            on = [h.name for h in pool.serves(bare)]
            _line(_ok if on else _warn, f"  model {bare}",
                  f"on {on}" if on else "not pulled on any live host")
            if not on:
                steps.append(f"ollama pull {bare}        # on the host that should serve it")
    else:
        _line(_warn, "Ollama host pool",
              "no host reachable -> `ollama serve` locally, or bring up the framework "
              "(see SETUP.md for the tailnet bind)")
```

- [ ] **Step 2: Update `_full_run()` local variant text**

Replace the `--- FULLY LOCAL variant ---` block (doctor.py:173-180):

```python
    print("\n  --- FULLY LOCAL variant (Ollama host pool; no key, no PII egress, free) ---")
    print("""  # the pool uses every reachable Ollama daemon: this machine + the framework
  # (tailnet). Placement is automatic: a juror runs where its model is pulled.
  uv run python -m industry.fire_llm calibrate --backend local --execute
  uv run python -m industry.fire_llm jury --backend local --limit 2000 --execute
  uv run python -m industry.fire_llm tail --backend local --execute
  uv run python -m industry.build_industry --propagate   # merges local jurors too
  uv run python -m industry.run_industry                 # calibration picks them up""")
```

- [ ] **Step 3: Run it**

Run: `uv run python -m industry.tests && uv run python -m industry.doctor`
Expected: tests PASS; doctor shows the local host OK, the framework
unreachable-warn (until Task 7), and per-model placement lines.

- [ ] **Step 4: Commit**

```bash
git add industry/doctor.py
git commit -m "feat(industry): doctor checks the Ollama host pool + per-model placement"
```

---

### Task 7: Framework one-time setup (systemd bind) + live verification

**Files:** none in-repo (remote host state). **Requires sudo on the Framework** — if passwordless sudo is not configured, hand the command to the user instead of running it.

- [ ] **Step 1: Apply the systemd drop-in over SSH**

```bash
ssh alex@100.73.40.75 'sudo -n true' 2>&1   # probe: can we sudo non-interactively?
```

If yes:

```bash
ssh alex@100.73.40.75 'sudo mkdir -p /etc/systemd/system/ollama.service.d && \
  printf "[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0\n" | \
  sudo tee /etc/systemd/system/ollama.service.d/network.conf >/dev/null && \
  sudo systemctl daemon-reload && sudo systemctl restart ollama'
```

If sudo needs a password, STOP and ask the user to run (e.g. via `!` in their session):

```
! ssh -t alex@100.73.40.75 'sudo mkdir -p /etc/systemd/system/ollama.service.d && printf "[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0\n" | sudo tee /etc/systemd/system/ollama.service.d/network.conf && sudo systemctl daemon-reload && sudo systemctl restart ollama'
```

- [ ] **Step 2: Verify direct tailnet reachability**

```bash
curl -s --max-time 5 http://100.73.40.75:11434/api/version
```

Expected: `{"version":"0.30.4"}` (or newer). Then:

```bash
uv run python -m industry.doctor
```

Expected: BOTH hosts `[ OK ]`, with gemma3:27b / qwen3:32b / gpt-oss:120b on
`['framework']`, phi4:14b on `['local']`, llama3.1:8b on both.

- [ ] **Step 3: Live integration smoke (the real pool, 5 items)**

```bash
uv run python -m industry.fire_llm jury --limit 5 --backend local --execute
```

Expected: pool plan shows both hosts; `[pool]` progress lines; summary reports
~15 new proposals (5 items x 3 jurors; minus any prior cache hits) and a jury
depth distribution. Watch wall-clock: the framework should be generating two
streams concurrently. Then:

```bash
uv run python -m industry.build_industry --propagate && uv run python -m industry.run_industry
```

Expected: both complete; the new jurors appear in calibration output.

- [ ] **Step 4: Commit the cache delta**

```bash
git add industry/llm_proposals.jsonl
git commit -m "data(industry): pilot jury votes from the multi-host pool (5 items x 3 jurors)"
```

---

### Task 8: Docs — SETUP.md + README

**Files:**
- Modify: `industry/SETUP.md:85-110` (§3-local)
- Modify: `industry/README.md` (the local-backend mention)

- [ ] **Step 1: Rewrite SETUP.md §3-local**

Replace the section body with:

```markdown
## 3-local. Run the jury on the Ollama HOST POOL (no key, no PII egress, free)

The local backend fires across **every reachable Ollama daemon at once**: this
machine's GPU plus the Framework Desktop over tailscale (`100.73.40.75`,
128 GB unified RAM). Placement is automatic — a juror runs wherever its model
is pulled — so the big jurors (gemma3:27b, qwen3:32b, gpt-oss:120b) live on
the Framework while phi4:14b runs here, all concurrently, writing the *same*
frozen cache.

```bash
# one-time on the Framework (binds Ollama to the tailnet; needs sudo):
ssh -t alex@100.73.40.75 'sudo mkdir -p /etc/systemd/system/ollama.service.d && \
  printf "[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0\n" | \
  sudo tee /etc/systemd/system/ollama.service.d/network.conf && \
  sudo systemctl daemon-reload && sudo systemctl restart ollama'

uv run python -m industry.doctor             # shows both hosts + model placement

# same modes as the cloud path, add --backend local. Preview first.
uv run python -m industry.fire_llm calibrate --backend local --execute
uv run python -m industry.fire_llm jury --backend local --limit 2000 --execute
uv run python -m industry.fire_llm tail --backend local --execute
uv run python -m industry.fire_llm head --backend local --limit 1000 --execute  # gpt-oss:120b

uv run python -m industry.build_industry --propagate
uv run python -m industry.run_industry
```

Host set: `OLLAMA_HOSTS="name=url|slots,..."` overrides; the legacy
`OLLAMA_HOST=...` still points the `local` entry somewhere else. A host that
is down is skipped (the run degrades gracefully, down to pure-cache-read if
none are up). The panel changed (bigger jurors), so re-run `calibrate` before
trusting agreement bands. If qwen3:32b is too slow on the Framework, pull the
MoE `qwen3:30b-a3b` there and swap the string in `LOCAL_JURY`.
```

- [ ] **Step 2: Update README.md**

Find the local-backend sentence(s) in `industry/README.md` (grep for `local_llm`
or `Ollama`) and update to mention the host pool + `llm_pool.py` in the module
inventory, one line:
`llm_pool.py — multi-host Ollama scheduling core (hosts, discovery, work-stealing queues)`.

- [ ] **Step 3: Final full check + commit**

```bash
uv run python -m industry.tests && uv run python -m industry.doctor
git add industry/SETUP.md industry/README.md
git commit -m "docs(industry): host-pool setup + module inventory"
```

---

## Self-review notes (done at plan-writing time)

- **Spec coverage:** discovery/affinity (T1), scheduling/failure table (T2), think flags + panel (T3), single-run fan-out + cache contract (T4), preview plan + head curator (T5), doctor (T6), systemd bind + smoke + calibration pointer (T7), docs (T8). Calibrate itself is a user-triggered run (hours), deliberately left as a documented next step, not a task.
- **Type consistency:** `HostPool(hosts, *, fetch_tags, transport)`; `run(units, on_result, *, progress_every)` returns `{"done","failed","skipped"}`; `WorkUnit(model, body, meta)`; `propose_local_panel(..., pool=)` — used identically across tasks.
- **Known accepted quirks:** requeued unit may be retaken by its failing host (bounded by `requeues < 1`); `is_available()`/`pool_plan()` construct a throwaway pool (a cheap /api/tags probe per host).
