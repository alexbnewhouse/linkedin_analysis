"""Build, run, and benchmark all three approaches on a field.

    uv run python -m edu_clean.run_eval field
    uv run python -m edu_clean.run_eval degree
    uv run python -m edu_clean.run_eval title
    uv run python -m edu_clean.run_eval all

Prints a comparison table (reduction, gold precision/recall/F1, runtime) plus
the specific false-merge / missed-merge errors each approach makes, and writes
edu_clean/results/<field>.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import approach_a_rules as A
from . import approach_b_fuzzy as B
from . import approach_c_embed as C
from .common import Result, load_vocab, pair_scores
from .gold import PAIRS

RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)


def valid_pairs(field: str, vocab_values: set) -> list[tuple]:
    pairs, dropped = [], []
    for a, b, same in PAIRS[field]:
        if a in vocab_values and b in vocab_values:
            pairs.append((a, b, same))
        else:
            dropped.append((a, b))
    if dropped:
        print(f"  [gold] dropped {len(dropped)} pair(s) not in vocab:")
        for a, b in dropped:
            miss = a if a not in vocab_values else b
            print(f"         missing: {miss!r}")
    return pairs


def error_pairs(mapping: dict, pairs: list[tuple]) -> tuple[list, list]:
    """Return (false_merges, missed_merges)."""
    fp, fn = [], []
    for a, b, same in pairs:
        pred = mapping[a] == mapping[b]
        if pred and not same:
            fp.append((a, b))
        elif same and not pred:
            fn.append((a, b))
    return fp, fn


def evaluate(field: str) -> dict:
    print(f"\n{'=' * 72}\nFIELD: {field}\n{'=' * 72}")
    vocab = load_vocab(field)
    vocab_values = {row[0] for row in vocab}
    print(f"distinct values: {len(vocab):,}  rows: {sum(r[1] for r in vocab):,}")
    pairs = valid_pairs(field, vocab_values)
    n_same = sum(1 for *_, s in pairs if s)
    print(
        f"gold pairs in vocab: {len(pairs)}  (same={n_same}, distinct={len(pairs) - n_same})"
    )

    results: list[Result] = [A.run(field, vocab), B.run(field, vocab)]
    for thr in (0.88, 0.92):
        results.append(C.run(field, vocab, threshold=thr))
    if field == "field":
        results.append(C.run_anchored_field(vocab, threshold=0.62))

    rows = []
    print(
        f"\n{'approach':18s} {'n_in':>8} {'n_out':>8} {'reduc':>6} "
        f"{'P':>5} {'R':>5} {'F1':>5} {'acc':>5} {'fp':>3} {'fn':>3} {'sec':>6}  extra"
    )
    for r in results:
        sc = pair_scores(r.mapping, pairs)
        rows.append(
            {
                "approach": r.name,
                "n_in": r.n_in(),
                "n_out": r.n_out(),
                "reduction": round(r.reduction(), 3),
                **sc,
                "runtime_s": round(r.runtime_s, 1),
                "extra": r.extra,
            }
        )
        print(
            f"{r.name:18s} {r.n_in():>8,} {r.n_out():>8,} {r.reduction():>6.2f} "
            f"{sc['precision']:>5.2f} {sc['recall']:>5.2f} {sc['f1']:>5.2f} "
            f"{sc['accuracy']:>5.2f} {sc['fp']:>3} {sc['fn']:>3} "
            f"{r.runtime_s:>6.1f}  {r.extra}"
        )

    # qualitative errors
    for r in results:
        fp, fn = error_pairs(r.mapping, pairs)
        if fp or fn:
            print(f"\n  {r.name} errors:")
            for a, b in fp:
                print(f"    FALSE-MERGE : {a!r}  <=>  {b!r}")
            for a, b in fn:
                print(f"    MISSED-MERGE: {a!r}  =/=  {b!r}")

    out = {
        "field": field,
        "n_distinct": len(vocab),
        "n_rows": sum(r[1] for r in vocab),
        "n_gold_pairs": len(pairs),
        "results": rows,
    }
    (RESULTS / f"{field}.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    targets = ["field", "degree", "title"] if which == "all" else [which]
    for f in targets:
        evaluate(f)
