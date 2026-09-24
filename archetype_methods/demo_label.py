"""Fire the remaining demo labeling batches straight at the deep Ollama host.

    uv run python -m archetype_methods.demo_label [first_batch] [concurrency]

Same prompt files and JSON schema as the orchestrated calls; writes
results/llm/demo_deep_batch_<n>.json for each batch that lacks one.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import common as C

HOST = "http://100.73.40.75:11434"
MODEL = "qwen3.8:latest"
LLM = C.RESULTS / "llm"
KEYS = ["communicators", "researchers", "analysts", "advocates", "helpers", "connectors",
        "leaders", "builders", "stewards", "none"]
SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "index": {"type": "integer"}, "primary": {"type": "string", "enum": KEYS},
    "secondary": {"type": ["string", "null"], "enum": KEYS + [None]}},
    "required": ["index", "primary", "secondary"]}}
TASK = ("Read the framework and the numbered job-title lines. For EVERY line output one object "
        '{"index": <int>, "primary": "<archetype key>", "secondary": "<archetype key or null>"}. '
        "Output a JSON array with exactly one object per input line, in order, nothing else.\n\n")


def one(b: int) -> str:
    out = LLM / f"demo_deep_batch_{b}.json"
    if out.exists():
        return f"{b} cached"
    prompt = TASK + (LLM / f"demo_batch_{b}.txt").read_text()
    body = {"model": MODEL, "stream": False, "format": SCHEMA, "think": False,
            "options": {"num_ctx": 8192, "temperature": 0.0, "num_predict": 6000},
            "messages": [{"role": "user", "content": prompt}]}
    t0 = time.time()
    req = urllib.request.Request(f"{HOST}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        resp = json.loads(r.read())
    items = json.loads(resp["message"]["content"])
    exp = set(range(b * 50, min(b * 50 + 50, 2000)))
    items = [it for it in items if it["index"] in exp]
    got = {it["index"] for it in items}
    if len(got) < len(exp) - 2:
        return f"{b} BAD indices ({len(got)} items) {time.time() - t0:.0f}s"
    out.write_text(json.dumps(items))
    return f"{b} ok ({len(got)}/{len(exp)}) {time.time() - t0:.0f}s"


if __name__ == "__main__":
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    conc = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    with ThreadPoolExecutor(conc) as ex:
        for msg in ex.map(one, range(first, 40)):
            print(msg, flush=True)
