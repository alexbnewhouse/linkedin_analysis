"""Fire the M6 LLM layer to populate the frozen proposal cache (industry/llm_proposals.jsonl).

This is the ONE step that actually calls the Anthropic API. It is deliberately
separate from ``build_industry`` (which only ever *reads* the frozen cache), so
the build stays reproducible. Defaults to a SAFE DRY-RUN preview (candidate counts
+ a cost estimate, no API call); pass ``--execute`` to submit the Batch API jobs.

Modes (triage by where a jury earns its 3x cost -- LLM_JUDGE_JURY_REPORT §4.3):
  tail       -- SINGLE cheap juror (Haiku) on the text-bearing residual the
                deterministic stack abstained on. The bulk target; cheap.
  jury       -- the FULL diverse panel (Haiku+Sonnet+Opus) on the top-N residual
                HEAD by frequency, where errors propagate to many rows and
                ambiguity is worth resolving. Hierarchical-consensus aggregation
                + agreement-based confidence happen at build time (jury.py).
  head       -- head curator (Opus / local: gpt-oss:120b) on the top-N companies,
                to grow curated M1.
  calibrate  -- the full panel on the GOLD population (companies + residual gold),
                so run_industry can map agreement/self-confidence onto observed
                precision (the Alternative Annotator Test).
  sample-gold-- NO API. Write a stratified labeling worksheet from the real
                residual so a human can extend industry/gold_residual.py.

Auth: set ANTHROPIC_API_KEY, or `eval "$(ant auth print-credentials --env)"`, or
just `ant auth login` (the SDK resolves the profile). See industry/README.md.

    uv run python -m industry.fire_llm tail --limit 5000              # preview
    uv run python -m industry.fire_llm tail --limit 5000 --execute    # fire
    uv run python -m industry.fire_llm jury --limit 2000 --execute    # panel on head
    uv run python -m industry.fire_llm calibrate --execute
    uv run python -m industry.fire_llm sample-gold --limit 150        # worksheet, no API
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from . import classify, jury, llm, local_llm
from .common import load_company_vocab
from .gold import GOLD_COMPANIES
from .gold_residual import GOLD_RESIDUAL

RESULTS = Path(__file__).resolve().parent / "results"

# Indicative Batch API rates ($/1M tokens) = list price x 0.5. Update if pricing
# moves; this is only used for the pre-flight estimate, not billing.
_BATCH_RATES = {
    llm.MODEL_HEAD: (2.50, 12.50),   # Opus 4.8
    llm.MODEL_MID: (1.50, 7.50),     # Sonnet 4.6
    llm.MODEL_BULK: (0.50, 2.50),    # Haiku 4.5
}
_EST_OUTPUT_TOKENS = 120             # small structured JSON per item
_SYSTEM_TOKENS = len(llm._SYSTEM) // 4  # noqa: SLF001  rough chars/4 heuristic


def _residual(vocab: list[dict]) -> list[dict]:
    """Companies the deterministic stack abstained on AND that carry text the LLM
    can actually read (title/description) -- the only place M6 earns its cost."""
    assign = classify.classify_company_vocab(vocab)
    return [r for r in vocab
            if assign[r["key"]].method in ("unresolved", "occupation_prior")
            and (r.get("descriptions") or r.get("titles"))]


def _gold_rows_from_vocab(vocab: list[dict]) -> list[dict]:
    """Pull the gold companies' rows FROM the vocab so their evidence matches what
    the cache was built from (-> the existing Haiku votes are reused, not re-fired,
    and the other jurors see identical evidence). Residual gold keys are real vocab
    keys by construction; synthetic gold names that aren't in the vocab are skipped."""
    want = {g.key() for g in GOLD_COMPANIES} | {g.key for g in GOLD_RESIDUAL}
    return [r for r in vocab if r["key"] in want]


def _estimate(items: list[dict], models: tuple[str, ...]) -> dict:
    if not items:
        return {"items": 0}
    sample = items[: min(200, len(items))]
    avg_ev = sum(len(llm.evidence_text(it)) // 4 for it in sample) / len(sample)
    n = len(items)
    total_low = total_high = 0.0
    for model in models:
        in_rate, out_rate = _BATCH_RATES[model]
        in_high = n * (_SYSTEM_TOKENS + avg_ev)
        in_low = n * (0.1 * _SYSTEM_TOKENS + avg_ev)
        out_tok = n * _EST_OUTPUT_TOKENS
        total_high += (in_high * in_rate + out_tok * out_rate) / 1_000_000
        total_low += (in_low * in_rate + out_tok * out_rate) / 1_000_000
    return {
        "items": n, "models": list(models),
        "avg_evidence_tokens": round(avg_ev),
        "system_tokens": _SYSTEM_TOKENS,
        "est_cost_usd_low": round(total_low, 2),
        "est_cost_usd_high": round(total_high, 2),
    }


def _sample_gold_worksheet(vocab: list[dict], limit: int) -> Path:
    """Write a stratified labeling worksheet from the residual (NO API call). Picks
    companies that have a cached single-juror proposal, stratified across that
    juror's proposed L1 so the worksheet spans the space, and emits the evidence +
    the model's suggestion + an empty ``expected`` for the human to fill -> paste
    promotions into industry/gold_residual.py."""
    residual = _residual(vocab)
    cache_by_key: dict[str, llm.Proposal] = {}
    for p in llm.load_cache().values():
        cache_by_key.setdefault(p.key, p)
    have_gold = {g.key() for g in GOLD_COMPANIES} | {g.key for g in GOLD_RESIDUAL}
    from . import taxonomy as T
    # bucket residual companies with a cached proposal by suggested L1, excluding
    # ones already in the gold set.
    buckets: dict[str, list[dict]] = {}
    for r in residual:
        p = cache_by_key.get(r["key"])
        if not p or r["key"] in have_gold:
            continue
        buckets.setdefault(T.truncate(p.code, 1), []).append((r, p))
    # round-robin across L1 buckets (sorted by freq within each) for a stratified draw
    for b in buckets.values():
        b.sort(key=lambda rp: -rp[0]["freq"])
    picked: list[tuple] = []
    while len(picked) < limit and any(buckets.values()):
        for l1 in sorted(buckets):
            if buckets[l1] and len(picked) < limit:
                picked.append(buckets[l1].pop(0))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "gold_worksheet.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r, p in picked:
            fh.write(json.dumps({
                "key": r["key"], "display": r["display"], "freq": r["freq"],
                "titles": (r.get("titles") or [])[:8],
                "descriptions": (r.get("descriptions") or [])[:2],
                "model_suggestion": p.code, "model_rationale": p.rationale,
                "expected": "",   # <-- HUMAN fills this with the ground-truth code
            }, ensure_ascii=False) + "\n")
    return out


# Which models each mode uses, per backend. A juror is just a model string, so the
# only difference between cloud and local is the panel and the firing function.
_PANELS = {
    "anthropic": {"tail": (llm.MODEL_BULK,), "jury": llm.JURY, "head": (llm.MODEL_HEAD,),
                  "calibrate": llm.JURY},
    "local": {"tail": (local_llm.LOCAL_BULK,), "jury": local_llm.LOCAL_JURY,
              "head": (local_llm.LOCAL_HEAD,), "calibrate": local_llm.LOCAL_JURY},
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Fire the industry M6 LLM jury (cloud Batch API or local Ollama).")
    ap.add_argument("mode", choices=("tail", "jury", "head", "calibrate", "sample-gold"))
    ap.add_argument("--backend", choices=("anthropic", "local"), default="anthropic",
                    help="anthropic=Batch API (default); local=Ollama host pool (this machine + tailnet hosts), no PII egress")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap the number of items (pilot guard / worksheet size)")
    ap.add_argument("--execute", action="store_true",
                    help="actually fire (default: safe preview only)")
    args = ap.parse_args()
    local = args.backend == "local"

    # sample-gold is offline (no API) -> handle and return early.
    if args.mode == "sample-gold":
        vocab = load_company_vocab()
        out = _sample_gold_worksheet(vocab, args.limit or 150)
        n = sum(1 for _ in out.open())
        print(f"wrote {n} rows to {out}\n"
              f"  Fill the empty `expected` field with the ground-truth code for each,\n"
              f"  then promote the labeled rows into industry/gold_residual.py.")
        return

    models = _PANELS[args.backend][args.mode]
    if args.mode == "calibrate":
        items = _gold_rows_from_vocab(load_company_vocab())
    elif args.mode == "head":
        items = load_company_vocab()
    else:  # tail / jury -> the text-bearing residual (freq-sorted desc)
        items = _residual(load_company_vocab())
    if args.limit is not None:
        items = items[: args.limit]

    print(f"mode={args.mode} backend={args.backend} models={list(models)} candidates={len(items):,}")

    # how many votes are already cached (free) vs need firing, per juror
    propose_dry = local_llm.propose_local if local else llm.propose
    for m in models:
        cached = len(propose_dry(items, model=m, dry_run=True))
        print(f"    [{m}] {cached:,}/{len(items):,} votes already cached")

    if local:
        local_llm.pool_plan(models)
        gens = len(items) * len(models)
        print(f"  LOCAL on the Ollama host pool: $0. ~{gens:,} generations total, "
              f"fanned out across every live host above -- use --limit for a pilot.")
    elif items:
        est = _estimate(items, models)
        print(f"  ~{est['avg_evidence_tokens']} evidence tokens/item, system ~{est['system_tokens']} tokens (cached)")
        print(f"  estimated one-time batch cost across the panel: "
              f"${est['est_cost_usd_low']}-${est['est_cost_usd_high']} "
              f"(low=system cached, high=uncached; cached items are free on re-run)")

    if not args.execute:
        print(f"\n[preview only] re-run with --execute to fire"
              f"{' on the local GPU' if local else ' via the Batch API'}.")
        return
    if not items:
        print("nothing to do.")
        return

    if local:
        if not local_llm.is_available():
            raise SystemExit("no Ollama host reachable (local or framework) -- start one "
                             "with `ollama serve` or check the tailnet (see SETUP.md).")
        print(f"\ngenerating {len(items):,} items x {len(models)} local juror(s) "
              f"across the host pool...")
        panel = local_llm.propose_local_panel(items, models=models, dry_run=False)
    else:
        if not llm._has_credentials():  # noqa: SLF001
            raise SystemExit(
                "no Anthropic credential found -- set ANTHROPIC_API_KEY, run "
                "`eval \"$(ant auth print-credentials --env)\"`, or `ant auth login` first."
            )
        print(f"\nsubmitting {len(items):,} items x {len(models)} juror(s) via the Batch "
              f"API (most finish <1h)...")
        panel = llm.propose_panel(items, models=models, dry_run=False)

    # quick post-fire summary: jury verdict depth/agreement distribution
    depths: Counter[int] = Counter()
    abstain = 0
    for votes in panel.values():
        v = jury.aggregate({m: p.code for m, p in votes.items()})
        depths[v.depth] += 1
        abstain += v.is_abstention
    print(f"done. {len(panel):,} companies resolved into the frozen cache "
          f"({llm.CACHE_FILE.name}).")
    print(f"  jury verdict depth distribution: {dict(sorted(depths.items()))}  "
          f"(XOT abstentions: {abstain})")
    print("next: `uv run python -m industry.build_industry --propagate` to merge them, "
          "and `uv run python -m industry.run_industry` for calibration.")


if __name__ == "__main__":
    main()
