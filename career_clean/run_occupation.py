"""Benchmark the occupation (O*NET-SOC) backstop on the title vocabulary.

    uv run python -m career_clean.run_occupation            # deterministic + embed
    uv run python -m career_clean.run_occupation --no-embed  # deterministic only

Occupation operates on the same job-title vocabulary as `title`, but assigns a
SOC family code (a separate axis from seniority/role). Compares the deterministic
O*NET lexicon (Approach A) against the embedding-anchored proposer (Approach C),
scored on the occupation gold pairs. Writes results/occupation.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import occupation as O
from .common import load_vocab, pair_scores
from .gold import PAIRS
from .run_eval import error_pairs, valid_pairs

RESULTS = Path(__file__).resolve().parent / "results"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=200_000)
    ap.add_argument("--no-embed", action="store_true")
    args = ap.parse_args()

    gold_values = tuple({v for pair in PAIRS["occupation"] for v in pair[:2]})
    vocab = load_vocab("title", cap=args.cap, include=gold_values)
    pairs = valid_pairs("occupation", {row[0] for row in vocab})
    n_same = sum(1 for *_, s in pairs if s)
    print(f"\n{'=' * 72}\nFIELD: occupation (O*NET-SOC, on title vocab)\n{'=' * 72}")
    print(f"vocab (cap={args.cap:,}+gold): {len(vocab):,} values, {sum(r[1] for r in vocab):,} rows")
    print(f"gold pairs: {len(pairs)} (same={n_same}, distinct={len(pairs) - n_same})")

    results = [O.run(vocab)]
    if not args.no_embed:
        from . import approach_c_embed as C

        for thr in (0.70, 0.80):
            results.append(C.run_anchored_occupation(vocab, threshold=thr))

    rows = []
    print(
        f"\n{'approach':22s} {'n_out':>8} {'reduc':>6} {'soc%':>6} "
        f"{'P':>5} {'R':>5} {'F1':>5} {'fp':>3} {'fn':>3} {'sec':>6}"
    )
    for r in results:
        sc = pair_scores(r.mapping, pairs)
        rows.append({"approach": r.name, "n_out": r.n_out(), "reduction": round(r.reduction(), 3),
                     **sc, "runtime_s": round(r.runtime_s, 1), "extra": r.extra})
        print(
            f"{r.name:22s} {r.n_out():>8,} {r.reduction():>6.2f} "
            f"{r.extra.get('reference_match_row_pct', 0):>6.1f} "
            f"{sc['precision']:>5.2f} {sc['recall']:>5.2f} {sc['f1']:>5.2f} "
            f"{sc['fp']:>3} {sc['fn']:>3} {r.runtime_s:>6.1f}"
        )
    for r in results:
        fp, fn = error_pairs(r.mapping, pairs)
        if fp or fn:
            print(f"\n  {r.name} errors:")
            for a, b in fp:
                print(f"    FALSE-MERGE : {a!r} <=> {b!r}")
            for a, b in fn:
                print(f"    MISSED-MERGE: {a!r} =/= {b!r}")

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "occupation.json").write_text(
        json.dumps({"field": "occupation", "cap": args.cap, "n_gold_pairs": len(pairs),
                    "results": rows}, indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
