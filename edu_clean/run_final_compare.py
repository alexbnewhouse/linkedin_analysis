"""Run the final hybrid and nearest-neighbor comparisons.

Examples:
    uv run python -m edu_clean.run_final_compare
    uv run python -m edu_clean.run_final_compare --model minilm
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import final_hybrid
from .common import load_vocab, pair_scores
from .gold import PAIRS
from .nearest_neighbor import MODE_GLOBAL, MODE_STRICT, load_cip_anchors, run_field
from .run_eval import error_pairs, valid_pairs

RESULTS = Path(__file__).resolve().parent / "results"

SAMPLE_VALUES = [
    "Business",
    "Business Administration",
    "Communications",
    "Management",
    "Science",
    "4.0",
    "General",
    "Computer Information Systems",
    "Data Science",
    "Cybersecurity",
]


def _ref_cov(field: str, vocab: list[tuple], mapping: dict[str, str]) -> float:
    if field == "field":
        prefixes = ("cip:",)
    elif field == "title":
        prefixes = ("slug:",)
    elif field == "degree":
        prefixes = (
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
        )
    else:
        raise ValueError(field)
    total = sum(freq for _value, freq, *_ in vocab)
    matched = sum(
        freq for value, freq, *_ in vocab if mapping[value].startswith(prefixes)
    )
    return round(100 * matched / total, 1)


def _summarize(result, vocab: list[tuple], pairs: list[tuple]) -> dict:
    scores = pair_scores(result.mapping, pairs)
    fp, fn = error_pairs(result.mapping, pairs)
    return {
        "approach": result.name,
        "field": result.field,
        "n_in": result.n_in(),
        "n_out": result.n_out(),
        "reduction": round(result.reduction(), 3),
        "runtime_s": round(result.runtime_s, 1),
        "reference_match_row_pct": _ref_cov(result.field, vocab, result.mapping),
        **scores,
        "false_merges": fp,
        "missed_merges": fn,
        "extra": result.extra,
    }


def _sample_assignments(results: list, values: list[str]) -> dict:
    code_to_title = {f"cip:{code}": title for code, title in load_cip_anchors()}
    out: dict[str, dict[str, str]] = {}
    for value in values:
        row = {}
        for result in results:
            if value not in result.mapping:
                continue
            cid = result.mapping[value]
            label = code_to_title.get(cid, "")
            row[result.name] = f"{cid}" + (f" | {label}" if label else "")
        if row:
            out[value] = row
    return out


def print_summary(rows: list[dict]) -> None:
    print(
        f"{'approach':24s} {'field':>7} {'reduc':>6} {'ref%':>6} "
        f"{'P':>5} {'R':>5} {'F1':>5} {'fp':>3} {'fn':>3} {'sec':>7}"
    )
    print("-" * 90)
    for row in rows:
        print(
            f"{row['approach'][:24]:24s} {row['field']:>7s} "
            f"{row['reduction']:6.3f} {row['reference_match_row_pct']:6.1f} "
            f"{row['precision']:5.2f} {row['recall']:5.2f} {row['f1']:5.2f} "
            f"{row['fp']:3d} {row['fn']:3d} {row['runtime_s']:7.1f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="bge-base", help="encoder_bench model key")
    parser.add_argument("--global-threshold", type=float, default=0.75)
    parser.add_argument("--strict-threshold", type=float, default=0.55)
    parser.add_argument("--global-high-threshold", type=float, default=0.85)
    parser.add_argument("--strict-high-threshold", type=float, default=0.80)
    parser.add_argument(
        "--single-threshold",
        action="store_true",
        help="Only run the primary global/strict thresholds.",
    )
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    summaries: list[dict] = []
    field_results = []

    # Full recommended hybrid on all three fields.
    for field in ("degree", "title", "field"):
        vocab = load_vocab(field)
        pairs = valid_pairs(field, {row[0] for row in vocab})
        result = final_hybrid.run(field, vocab)
        summaries.append(_summarize(result, vocab, pairs))
        if field == "field":
            field_results.append(result)

    # Two field-only nearest-neighbor approaches.
    field_vocab = load_vocab("field")
    field_pairs = valid_pairs("field", {row[0] for row in field_vocab})
    nn_specs = [
        (MODE_GLOBAL, args.global_threshold),
        (MODE_STRICT, args.strict_threshold),
    ]
    if not args.single_threshold:
        nn_specs.extend(
            [
                (MODE_GLOBAL, args.global_high_threshold),
                (MODE_STRICT, args.strict_high_threshold),
            ]
        )

    for mode, threshold in nn_specs:
        result = run_field(
            field_vocab,
            mode=mode,
            model=args.model,
            threshold=threshold,
            use_cache=not args.no_cache,
        )
        summaries.append(_summarize(result, field_vocab, field_pairs))
        field_results.append(result)

    samples = _sample_assignments(field_results, SAMPLE_VALUES)
    out = {
        "model": args.model,
        "global_threshold": args.global_threshold,
        "strict_threshold": args.strict_threshold,
        "global_high_threshold": None
        if args.single_threshold
        else args.global_high_threshold,
        "strict_high_threshold": None
        if args.single_threshold
        else args.strict_high_threshold,
        "summaries": summaries,
        "sample_assignments": samples,
    }
    RESULTS.mkdir(exist_ok=True)
    out_path = RESULTS / "final_compare.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print_summary(summaries)
    print(f"\nwrote {out_path}")
    print("\nSample field assignments:")
    for value, row in samples.items():
        print(f"  {value!r}")
        for name, assignment in row.items():
            print(f"    {name}: {assignment}")


if __name__ == "__main__":
    main()
