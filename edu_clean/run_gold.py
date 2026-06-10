"""Gold-pair evaluation of the production final hybrid (CPU only).

    uv run python -m edu_clean.run_gold

Unlike run_eval / run_final_compare this imports no GPU stack, so it can run
anywhere as the module's fast test harness. It scores the final hybrid's
same-vs-distinct decisions against the labeled gold pairs, reports row-level
reference coverage, and breaks the pair confusion down by the *methods* that
produced each endpoint (so the precision claim is per-method honest: a pair is
attributed to the method pair of its two endpoints).

Writes edu_clean/results/gold_final.json.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import final_hybrid
from .common import load_vocab, pair_scores
from .gold import PAIRS

RESULTS = Path(__file__).resolve().parent / "results"

REF_PREFIXES = {
    "field": ("cip:",),
    "title": ("slug:",),
    "degree": (
        "bachelor:",
        "master:",
        "associate:",
        "doctorate:",
        "high_school:",
        "diploma:",
        "certificate:",
        "foundation:",
        "undergraduate:",
        "graduate:",
        "postgraduate:",
        "minor:",
        "study_abroad:",
    ),
}


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


def ref_coverage(field: str, vocab: list[tuple], mapping: dict[str, str]) -> float:
    prefixes = REF_PREFIXES[field]
    total = sum(freq for _v, freq, *_ in vocab)
    matched = sum(freq for v, freq, *_ in vocab if mapping[v].startswith(prefixes))
    return round(100 * matched / total, 1)


def per_method_breakdown(result, pairs: list[tuple]) -> dict:
    """Confusion counts keyed by the sorted (method_a, method_b) pair."""
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "tn": 0, "fn": 0})
    for a, b, same in pairs:
        key = "+".join(sorted({result.method.get(a, "?"), result.method.get(b, "?")}))
        pred = result.mapping[a] == result.mapping[b]
        if same and pred:
            out[key]["tp"] += 1
        elif same:
            out[key]["fn"] += 1
        elif pred:
            out[key]["fp"] += 1
        else:
            out[key]["tn"] += 1
    summary = {}
    for key, c in sorted(out.items()):
        denom = c["tp"] + c["fp"]
        summary[key] = {**c, "precision": round(c["tp"] / denom, 3) if denom else None}
    return summary


def main() -> None:
    report = {}
    ok = True
    for field in ("degree", "title", "field"):
        vocab = load_vocab(field)
        pairs = valid_pairs(field, {row[0] for row in vocab})
        result = final_hybrid.run(field, vocab)
        scores = pair_scores(result.mapping, pairs)
        cov = ref_coverage(field, vocab, result.mapping)
        methods = per_method_breakdown(result, pairs)
        errors = []
        for a, b, same in pairs:
            pred = result.mapping[a] == result.mapping[b]
            if pred != same:
                kind = "FALSE-MERGE" if pred else "MISSED-MERGE"
                errors.append([kind, a, b, result.mapping[a], result.mapping[b]])
        report[field] = {
            "n_pairs": len(pairs),
            "ref_row_pct": cov,
            **scores,
            "row_pct_by_method": result.extra.get("row_pct_by_method"),
            "per_method_pairs": methods,
            "errors": errors,
        }
        print(
            f"{field:7s} pairs={len(pairs):3d} P={scores['precision']:.2f} "
            f"R={scores['recall']:.2f} F1={scores['f1']:.2f} ref%={cov:5.1f}"
        )
        for key, c in methods.items():
            prec = "-" if c["precision"] is None else f"{c['precision']:.2f}"
            print(
                f"    {key:32s} tp={c['tp']:3d} fp={c['fp']:2d} tn={c['tn']:3d} "
                f"fn={c['fn']:2d} P={prec}"
            )
        for err in errors:
            ok = False
            print(f"    {err[0]}: {err[1]!r} <-> {err[2]!r} ({err[3]} / {err[4]})")

    RESULTS.mkdir(exist_ok=True)
    out_path = RESULTS / "gold_final.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"wrote {out_path}")
    if not ok:
        raise SystemExit("gold evaluation has errors")


if __name__ == "__main__":
    main()
