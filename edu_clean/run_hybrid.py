"""Evaluate the hybrid canonicalizer on all three fields.

uv run python -m edu_clean.run_hybrid
"""

from __future__ import annotations

import json
from pathlib import Path

from . import hybrid
from .common import load_vocab, pair_scores
from .run_eval import error_pairs, valid_pairs

RESULTS = Path(__file__).resolve().parent / "results"


def main():
    summary = {}
    for field in ("field", "degree", "title"):
        print(f"\n{'=' * 72}\nHYBRID on {field}\n{'=' * 72}")
        vocab = load_vocab(field)
        vocab_values = {row[0] for row in vocab}
        pairs = valid_pairs(field, vocab_values)
        r = hybrid.run(field, vocab)
        sc = pair_scores(r.mapping, pairs)
        print(
            f"n_in={r.n_in():,}  n_out={r.n_out():,}  reduction={r.reduction():.2f}  "
            f"runtime={r.runtime_s:.1f}s"
        )
        print(
            f"gold: P={sc['precision']}  R={sc['recall']}  F1={sc['f1']}  "
            f"acc={sc['accuracy']}  (fp={sc['fp']}, fn={sc['fn']})"
        )
        print(f"row% by method: {r.extra['row_pct_by_method']}")
        fp, fn = error_pairs(r.mapping, pairs)
        for a, b in fp:
            print(f"    FALSE-MERGE : {a!r}  <=>  {b!r}")
        for a, b in fn:
            print(f"    MISSED-MERGE: {a!r}  =/=  {b!r}")
        summary[field] = {
            "n_in": r.n_in(),
            "n_out": r.n_out(),
            "reduction": round(r.reduction(), 3),
            "runtime_s": round(r.runtime_s, 1),
            **sc,
            "row_pct_by_method": r.extra["row_pct_by_method"],
        }
    (RESULTS / "hybrid.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {RESULTS / 'hybrid.json'}")


if __name__ == "__main__":
    main()
