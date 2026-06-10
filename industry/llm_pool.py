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
            name, _, rest = entry.strip().partition("=")
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
