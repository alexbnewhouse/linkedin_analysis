"""Benchmark the host pool with REAL jury request bodies.

    uv run python -m industry.bench_hosts                  # all (host, juror) pairs
    uv run python -m industry.bench_hosts --items 5 --concurrency 2

For each (host, model) pair where the model is pulled: one un-timed warmup item
(loads the model and primes the system-prefix KV cache), then N timed items,
reporting wall latency per item plus Ollama's own token counters
(prompt_eval/eval counts and durations -> true tok/s). With --concurrency K the
timed items are fired K-at-a-time (matches OLLAMA_NUM_PARALLEL) to measure
EFFECTIVE per-host throughput, which is what a wall-clock projection needs.

Read-only: results go to stdout + industry/results/bench_hosts.json; the frozen
proposal cache is NOT touched (responses are parsed but never appended).
"""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from pathlib import Path

from . import llm_pool, local_llm
from .common import load_company_vocab

RESULTS = Path(__file__).resolve().parent / "results"

# what we want benchmarked, per host name (bare model tags)
WANT = {
    "local": ["phi4:14b", "llama3.1:8b"],
    "framework": ["gemma3:27b", "qwen3:32b", "llama3.1:8b", "gpt-oss:120b"],
}


def _items(n: int) -> list[dict]:
    """Real residual-shaped items: freq-sorted vocab rows that carry text."""
    vocab = load_company_vocab()
    out = [r for r in vocab if r.get("descriptions") or r.get("titles")]
    return out[: n]


def _one(host: llm_pool.OllamaHost, body: dict) -> dict:
    t0 = time.monotonic()
    resp = llm_pool._http_chat(host, body)  # noqa: SLF001
    wall = time.monotonic() - t0
    return {
        "wall_s": round(wall, 2),
        "prompt_tokens": resp.get("prompt_eval_count"),
        "out_tokens": resp.get("eval_count"),
        "eval_s": round((resp.get("eval_duration") or 0) / 1e9, 2),
        "prompt_s": round((resp.get("prompt_eval_duration") or 0) / 1e9, 2),
        "ok": bool((resp.get("message") or {}).get("content")),
    }


def bench_pair(host: llm_pool.OllamaHost, model: str, items: list[dict],
               concurrency: int) -> dict:
    full = f"ollama/{model}"
    print(f"\n[{host.name}] {model}  (warmup ...)", flush=True)
    t0 = time.monotonic()
    _one(host, local_llm.build_request(items[0], full))
    warm = time.monotonic() - t0
    print(f"[{host.name}] {model}  warmup {warm:.1f}s; timing {len(items) - 1} items "
          f"x{concurrency} concurrent ...", flush=True)

    timed: list[dict] = []
    lock = threading.Lock()
    queue = list(enumerate(items[1:], 1))

    def worker() -> None:
        while True:
            with lock:
                if not queue:
                    return
                _, it = queue.pop(0)
            r = _one(host, local_llm.build_request(it, full))
            with lock:
                timed.append(r)

    t0 = time.monotonic()
    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    span = time.monotonic() - t0

    ok = [r for r in timed if r["ok"]]
    walls = [r["wall_s"] for r in ok]
    out_tok = [r["out_tokens"] for r in ok if r["out_tokens"]]
    eval_s = [r["eval_s"] for r in ok if r["eval_s"]]
    res = {
        "host": host.name, "model": model, "concurrency": concurrency,
        "warmup_s": round(warm, 1),
        "n_ok": len(ok), "n_fail": len(timed) - len(ok),
        "item_wall_s_median": round(statistics.median(walls), 2) if walls else None,
        "effective_items_per_s": round(len(ok) / span, 3) if ok else 0.0,
        "gen_tok_per_s": round(sum(out_tok) / sum(eval_s), 1) if eval_s and sum(eval_s) else None,
        "out_tokens_median": int(statistics.median(out_tok)) if out_tok else None,
    }
    print(f"[{host.name}] {model}  median {res['item_wall_s_median']}s/item, "
          f"effective {res['effective_items_per_s']} item/s, "
          f"gen {res['gen_tok_per_s']} tok/s, out~{res['out_tokens_median']} tok",
          flush=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark pool hosts with real jury bodies.")
    ap.add_argument("--items", type=int, default=6, help="timed items per pair (+1 warmup)")
    ap.add_argument("--concurrency", type=int, default=None,
                    help="parallel streams (default: the host's slot count)")
    args = ap.parse_args()

    pool = llm_pool.HostPool()
    if not pool.hosts:
        raise SystemExit("no Ollama host reachable")
    items = _items(args.items + 1)
    results = []
    for host in pool.hosts:
        for model in WANT.get(host.name, []):
            if model not in host.models:
                print(f"[{host.name}] {model} not pulled -- skipped")
                continue
            conc = args.concurrency or host.parallel
            results.append(bench_pair(host, model, items, conc))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "bench_hosts.json"
    out.write_text(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M"), "runs": results}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
