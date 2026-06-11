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

# (name, base_url, parallel slots, api). Ollama slots mirror each daemon's
# OLLAMA_NUM_PARALLEL; llamacpp slots mirror the llama-server -np value (the
# batched bulk lane: native-sm_120 build locally, Vulkan/RADV on the framework;
# see ~/llm-serving/serve-*.sh watchdogs on each host). Down hosts are skipped.
DEFAULT_HOSTS: tuple[tuple[str, str, int, str], ...] = (
    ("local", "http://127.0.0.1:11434", 1, "ollama"),
    ("framework", "http://100.73.40.75:11434", 2, "ollama"),
    ("local-srv", "http://127.0.0.1:8090", 16, "llamacpp"),
    ("fw-srv", "http://100.73.40.75:8091", 8, "llamacpp"),
)
TAGS_TIMEOUT = 3        # seconds: the discovery probe
REQUEST_TIMEOUT = 600   # seconds: one generation (27-32B on Strix Halo is slow)
HOST_MAX_CONSECUTIVE_FAILURES = 5


@dataclass
class OllamaHost:
    name: str
    base_url: str
    parallel: int = 1
    models: frozenset[str] = frozenset()  # bare tags from discovery
    api: str = "ollama"                   # "ollama" | "llamacpp" (llama-server)


@dataclass
class WorkUnit:
    model: str            # bare daemon name, e.g. "gemma3:27b"
    body: dict            # full /api/chat body (already names the model)
    meta: object = None   # opaque caller token, handed back via on_result
    attempts: int = 0     # attempts on the current host
    requeues: int = 0     # cross-host requeues so far (max 1)
    tried: set[str] = field(default_factory=set)  # host names that failed it


def _norm_url(url: str) -> str:
    """Normalize a host url: Ollama's own convention allows a scheme-less
    ``host:port`` (e.g. ``OLLAMA_HOST=127.0.0.1:11434``); urllib does not."""
    url = url.strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


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
                    f"bad OLLAMA_HOSTS entry: {entry!r} (expected name=url|slots|api)")
            url, _, extra = rest.partition("|")
            slots, _, api = extra.partition("|")
            out.append(OllamaHost(name=name, base_url=_norm_url(url),
                                  parallel=int(slots or 1), api=api or "ollama"))
        return out
    hosts = [OllamaHost(name=n, base_url=u, parallel=p, api=a)
             for n, u, p, a in DEFAULT_HOSTS]
    single = (e.get("OLLAMA_HOST") or "").strip()
    if single:
        hosts[0] = OllamaHost(name="local", base_url=_norm_url(single),
                              parallel=hosts[0].parallel)
    return hosts


def _fetch_tags(base_url: str) -> list[str] | None:
    """Installed model tags on one Ollama daemon, or None if unreachable."""
    try:
        with urllib.request.urlopen(base_url + "/api/tags", timeout=TAGS_TIMEOUT) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", [])]
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError):
        return None


def _fetch_models_openai(base_url: str) -> list[str] | None:
    """Model ids served by an OpenAI-compatible server (llama-server /v1/models).
    llama-server serves ONE model; launch it with ``--alias <bare-name>`` so the
    id here matches the juror's bare model name."""
    try:
        with urllib.request.urlopen(base_url + "/v1/models", timeout=TAGS_TIMEOUT) as r:
            data = json.loads(r.read())
        if "data" in data:    # OpenAI shape
            return [m["id"] for m in data["data"]]
        if "models" in data:  # llama-server builds that answer in Ollama shape
            return [m.get("name") or m.get("model") for m in data["models"]]
        return None
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError):
        return None


def _openai_body(body: dict) -> dict:
    """Adapt an Ollama ``/api/chat`` body to OpenAI ``/v1/chat/completions``.

    The enum-constrained ``format`` schema becomes a strict ``json_schema``
    response_format (llama-server compiles it to a grammar); ``cache_prompt``
    keeps the shared 2.5k-token system prefix KV hot in each server slot.
    Ollama-only keys (``think``, ``keep_alive``, ``stream``) are dropped."""
    opts = body.get("options") or {}
    return {
        "model": body["model"],
        "messages": body["messages"],
        "temperature": opts.get("temperature", 0),
        "seed": opts.get("seed", 7),
        "max_tokens": 512,
        "cache_prompt": True,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "verdict", "strict": True,
                            "schema": body["format"]},
        },
    }


def _from_openai(resp: dict) -> dict:
    """Adapt an OpenAI chat response to the Ollama shape callers parse
    (``message.content`` + eval counters; llama-server timings are ms -> ns)."""
    msg = (resp.get("choices") or [{}])[0].get("message") or {}
    usage = resp.get("usage") or {}
    timings = resp.get("timings") or {}
    return {
        "message": {"content": msg.get("content") or ""},
        "eval_count": usage.get("completion_tokens"),
        "prompt_eval_count": usage.get("prompt_tokens"),
        "eval_duration": int(timings.get("predicted_ms", 0) * 1e6),
        "prompt_eval_duration": int(timings.get("prompt_ms", 0) * 1e6),
    }


def _http_chat(host: OllamaHost, body: dict) -> dict:
    if host.api == "llamacpp":
        path, payload = "/v1/chat/completions", _openai_body(body)
    else:
        path, payload = "/api/chat", body
    req = urllib.request.Request(
        host.base_url + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        out = json.loads(r.read())
    return _from_openai(out) if host.api == "llamacpp" else out


def discover(hosts: list[OllamaHost], fetch_tags=_fetch_tags,
             fetch_openai=_fetch_models_openai) -> list[OllamaHost]:
    """Probe each host once (per its api); drop unreachable ones (with a warning)."""
    live: list[OllamaHost] = []
    for h in hosts:
        probe = fetch_openai if h.api == "llamacpp" else fetch_tags
        tags = probe(h.base_url)
        if tags is None:
            print(f"[pool] {h.name} ({h.base_url}) unreachable -- skipping")
            continue
        live.append(OllamaHost(h.name, h.base_url, h.parallel, frozenset(tags), h.api))
    return live


class HostPool:
    """Schedules WorkUnits across the discovered live hosts."""

    def __init__(self, hosts: list[OllamaHost] | None = None, *,
                 fetch_tags=_fetch_tags, fetch_openai=_fetch_models_openai,
                 transport=_http_chat):
        self.hosts = discover(hosts if hosts is not None else hosts_from_env(),
                              fetch_tags, fetch_openai)
        self.transport = transport

    def serves(self, model: str) -> list[OllamaHost]:
        return [h for h in self.hosts if model in h.models]

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
                q = queues.get(m)
                if m not in host.models or not q:
                    continue
                for _ in range(len(q)):
                    u = q.popleft()
                    if host.name in u.tried:   # this host already failed it -> leave
                        q.append(u)            # it for a host that hasn't
                        continue
                    if not q:
                        del queues[m]
                    return u
            return None

        def prune_unservable() -> None:  # under lock, after a mark-down
            # A queued unit is servable only by a host that is BOTH live and has
            # not already failed it (take() skips tried hosts); anything else
            # would wait forever, so fail it now.
            for m in list(queues):
                q = queues[m]
                keep = deque()
                for u in q:
                    if any(h.name not in down and h.name not in u.tried
                           for h in self.serves(m)):
                        keep.append(u)
                    else:
                        finish(u, ok=False)
                if keep:
                    queues[m] = keep
                else:
                    del queues[m]

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
                last_err: Exception | None = None
                while True:
                    # safe un-locked: a unit is exclusively owned by one worker between queue handoffs
                    u.attempts += 1
                    try:
                        resp = self.transport(host, u.body)
                    except Exception as e:
                        resp = None
                        last_err = e
                    if resp is not None:
                        with lock:
                            fail_streak[host.name] = 0
                            try:
                                on_result(u.meta, resp)
                            except Exception as e:  # a bad callback must not kill the slot
                                print(f"[pool] on_result raised {e!r} -- unit counted done")
                            finish(u, ok=True)
                        break
                    # un-locked read of `down` is a benign race: a stale miss only
                    # costs one extra same-host attempt before the locked paths see it
                    if u.attempts < 2 and host.name not in down:
                        continue  # the one same-host retry
                    with lock:
                        fail_streak[host.name] += 1
                        if fail_streak[host.name] >= HOST_MAX_CONSECUTIVE_FAILURES:
                            down.add(host.name)
                            print(f"[pool] {host.name} marked down after "
                                  f"{fail_streak[host.name]} consecutive failures "
                                  f"(last: {last_err!r})")
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
