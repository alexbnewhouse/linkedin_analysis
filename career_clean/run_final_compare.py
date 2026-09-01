"""Run the final hybrid on the FULL vocabulary and report production numbers.

    uv run python -m career_clean.run_final_compare

Reports, per field: reduction, reference/structured coverage, gold P/R/F1, the
specific errors, the method breakdown by row %, and runtime. Also profiles the
description-normalization pass. Writes career_clean/results/final_compare.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from . import final_hybrid
from .common import EXP, load_vocab, pair_scores
from .run_eval import error_pairs, valid_pairs

RESULTS = Path(__file__).resolve().parent / "results"

SAMPLE = {
    "company": ["AT&T", "AT&T Mobility", "EY", "Ernst & Young", "Citi", "Citigroup",
                "Self-employed", "Self Employed", "Freelance", "Citizens Bank",
                "First Citizens Bank", "US Army", "United States Army"],
    "employment_type": [
        ("Self-employed", "Graphic Designer"),
        ("Self-employed", "Retired"),
        ("Deloitte", "Consultant"),
        ("Deloitte", "Independent Consultant"),
        ("Example LLC", "Founder"),
        ("Example LLC", "Product Owner"),
    ],
    "title": ["Software Engineer", "Senior Software Engineer", "Sr. Software Engineer",
              "VP", "Vice President", "VP of Sales", "CEO", "Chief Executive Officer",
              "Co-Founder", "Cofounder", "Founder", "Project Manager", "Product Manager"],
}


def _ref_cov(field: str, vocab, mapping) -> float:
    if field == "employment_type":
        return 100.0
    prefix = {"company": "id:", "title": "title:", "occupation": "soc:"}[field]
    total = sum(f for _v, f, *_ in vocab)
    matched = sum(f for v, f, *_ in vocab if mapping[v].startswith(prefix))
    return round(100 * matched / total, 1)


def _summarize(result, vocab, pairs) -> dict:
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
        "method_row_pct": result.extra.get("row_pct_by_method", {}),
    }


def _describe_descriptions() -> dict:
    """Cheap profile of the description-normalization pass on a sample."""
    con = duckdb.connect()
    n, nn = con.sql(f"""
        SELECT count(*), count(*) FILTER (WHERE description IS NOT NULL) FROM {EXP}
    """).fetchone()
    sample = con.sql(f"""
        SELECT description FROM {EXP} WHERE description IS NOT NULL LIMIT 200000
    """).fetchall()
    changed = sum(
        1 for (d,) in sample if final_hybrid.normalize_description(d) != d
    )
    return {
        "experience_rows": n,
        "with_description": nn,
        "pct_present": round(100 * nn / n, 1),
        "sample_n": len(sample),
        "sample_pct_changed_by_normalization": round(100 * changed / max(len(sample), 1), 1),
    }


def main() -> None:
    summaries = []
    samples = {}
    title_maps = {}  # for the combined 3-axis title view
    for field in ("company", "employment_type", "title", "occupation"):
        # occupation runs on the title vocabulary (a separate axis on titles)
        vocab_field = "title" if field == "occupation" else field
        print(f"\n{'=' * 60}\n{field}  (FULL {vocab_field} vocab)\n{'=' * 60}")
        vocab = load_vocab(vocab_field)  # full vocabulary, CPU
        pairs = valid_pairs(field, {row[0] for row in vocab})
        result = final_hybrid.run(field, vocab)
        s = _summarize(result, vocab, pairs)
        summaries.append(s)
        if field in SAMPLE:
            samples[field] = {
                str(v): result.mapping[v] for v in SAMPLE[field] if v in result.mapping
            }
        if field in ("title", "occupation"):
            title_maps[field] = result.mapping
        print(f"  values={s['n_in']:,} -> canon={s['n_out']:,}  reduction={s['reduction']}")
        print(f"  reference/structured coverage: {s['reference_match_row_pct']}% of rows")
        print(f"  gold  P={s['precision']} R={s['recall']} F1={s['f1']} "
              f"(fp={s['fp']} fn={s['fn']})  runtime={s['runtime_s']}s")
        print(f"  method by row %: {s['method_row_pct']}")
        for a, b in s["false_merges"]:
            print(f"    FALSE-MERGE : {a!r} <=> {b!r}")
        for a, b in s["missed_merges"]:
            print(f"    MISSED-MERGE: {a!r} =/= {b!r}")

    # combined 3-axis title view: literal canonical + occupation code
    print(f"\n{'=' * 60}\ncombined title axes (literal | occupation)\n{'=' * 60}")
    combined = {}
    for v in SAMPLE["title"]:
        if v in title_maps.get("title", {}):
            combined[v] = {
                "literal": title_maps["title"][v],
                "occupation": title_maps["occupation"].get(v, "raw:?"),
            }
    for v, axes in combined.items():
        print(f"  {v!r:30s} {axes['literal']:28s} {axes['occupation']}")
    samples["title_combined"] = combined

    desc = _describe_descriptions()
    print(f"\n{'=' * 60}\ndescription (normalization only)\n{'=' * 60}")
    print(f"  {desc}")

    out = {"summaries": summaries, "samples": samples, "description": desc}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "final_compare.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nwrote {RESULTS / 'final_compare.json'}")
    for field, smap in samples.items():
        print(f"\nSample {field} assignments:")
        for v, cid in smap.items():
            print(f"  {v!r:32s} -> {cid}")


if __name__ == "__main__":
    main()
