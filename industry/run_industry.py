"""Evaluate + report the industry classifier (mirrors career_clean.run_final_compare).

    uv run python -m industry.run_industry            # gold eval (no big data needed)
    uv run python -m industry.run_industry --full     # + production coverage on the
                                                       #   full company vocab (needs normalized/)
    uv run python -m industry.run_industry --full --cap 50000

Reports, per the plan's evaluation §5:
  * per-LEVEL precision/recall on the gold set (you can be right at L1, wrong at L4),
  * coverage at each depth (% of career steps with an L1/L2/L3/L4 industry),
  * the method breakdown and the review-queue size,
  * LLM calibration (self-confidence band -> observed precision) when a frozen
    proposal cache is present.

Writes industry/results/industry_eval.json.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from . import classify, curated, name_rules
from . import taxonomy as T
from .gold import GOLD_COMPANIES, GOLD_ROWS
from .common import depth_coverage, level_scores

RESULTS = Path(__file__).resolve().parent / "results"


def _validate() -> dict:
    tax = T.validate()
    bad_curated = curated.validate()
    bad_rules = name_rules.validate()
    if bad_curated or bad_rules:
        raise SystemExit(f"INVALID CODES: curated={bad_curated} rules={bad_rules}")
    return {"taxonomy": tax, "curated_entries": len(curated.CURATED),
            "name_rules": len(name_rules._RULES)}  # noqa: SLF001


def eval_gold() -> dict:
    pred: dict[str, str | None] = {}
    gold: dict[str, str] = {}
    detail = []
    for g in GOLD_COMPANIES:
        a = classify.classify_company(
            company_id=g.company_id, display=g.display,
            modal_occ=g.modal_occ, occ_coded_frac=g.occ_coded_frac,
        )
        pred[g.key()] = a.code
        gold[g.key()] = g.expected
        ok_l1 = T.truncate(a.code, 1) == T.truncate(g.expected, 1)
        detail.append({
            "display": g.display, "expected": g.expected, "predicted": a.code,
            "method": a.method, "confidence": a.confidence, "L1_ok": ok_l1,
            "needs_review": a.needs_review, "note": g.note,
        })
    scores = level_scores(pred, gold, taxonomy=T)
    return {"per_level": scores, "n": len(GOLD_COMPANIES), "detail": detail}


def eval_rows() -> dict:
    detail, correct = [], 0
    for soc, expected in GOLD_ROWS:
        a = classify.classify_row(
            company_canonical_id="nonorg:self_employed", company_id=None,
            company_raw=None, occupation_code=soc,
        )
        ok = T.truncate(a.code, T.level_of(expected)) == expected if T.is_valid(expected) else False
        # XOT abstain matches an XOT-expected (industry-agnostic occupation)
        if expected == "XOT":
            ok = a.code == "XOT"
        correct += ok
        detail.append({"soc": soc, "expected": expected, "predicted": a.code,
                       "method": a.method, "ok": ok})
    return {"n": len(GOLD_ROWS), "correct": correct, "detail": detail}


def production_report(cap: int | None) -> dict:
    """Run the deterministic backbone on the full (or capped) company vocab and
    report coverage-by-depth, method mix, and review-queue size."""
    from .common import load_company_vocab

    vocab = load_company_vocab(cap=cap)
    assign = classify.classify_company_vocab(vocab)
    pred = {k: a.code for k, a in assign.items()}

    cov = depth_coverage(vocab, pred, taxonomy=T, weight="freq")
    total_rows = sum(r["freq"] for r in vocab) or 1
    method_rows: Counter[str] = Counter()
    review_rows = 0
    l1_rows: Counter[str] = Counter()
    for r in vocab:
        a = assign[r["key"]]
        method_rows[a.method] += r["freq"]
        if a.needs_review:
            review_rows += r["freq"]
        l1_rows[T.truncate(a.code, 1)] += r["freq"]
    return {
        "n_companies": len(vocab),
        "total_rows": total_rows,
        "coverage_by_depth_row_pct": cov,
        "method_row_pct": {k: round(100 * v / total_rows, 1)
                           for k, v in method_rows.most_common()},
        "review_queue_row_pct": round(100 * review_rows / total_rows, 1),
        "L1_distribution_row_pct": {
            f"{c} {T.label_of(c)}": round(100 * v / total_rows, 1)
            for c, v in l1_rows.most_common()
        },
    }


def _agreement_band(agreement: float, n_jurors: int) -> str:
    """Bucket a jury's depth-agreement into a calibratable band."""
    if n_jurors <= 1:
        return "single-juror"
    if agreement >= 0.99:
        return "unanimous"
    if agreement >= 0.6:
        return "majority"
    return "split"


def llm_calibration() -> dict | None:
    """Map the LLM layer's signals onto OBSERVED precision against a ground-truth
    gold set, so a band can eventually gate auto-accept (the Alternative Annotator
    Test, LLM_JUDGE_JURY_REPORT §5). Pure cache read -- no API call.

    Reads the frozen proposal cache directly and joins to gold by company key
    (companies + the residual gold), so it works OFFLINE against whatever has been
    fired. Reports, per LEVEL and per band:
      * per-model self-reported-confidence band precision (verbalized confidence is
        weakly calibrated -- expect a confident band to still contain errors),
      * jury agreement-band precision + per-level P/R on the consensus verdict
        (agreement is the signal we actually trust),
      * predicted-L1 prevalence over the whole cache (to catch label/prevalence bias).
    """
    from . import llm, jury, gold_residual

    cache = llm.load_cache()
    if not cache:
        return None
    # key -> {model: Proposal}
    panel: dict[str, dict[str, llm.Proposal]] = {}
    for p in cache.values():
        panel.setdefault(p.key, {})[p.model] = p

    gold = {g.key(): g.expected for g in GOLD_COMPANIES}
    gold.update(gold_residual.gold_labels())
    matched = {k: panel[k] for k in gold if k in panel}
    if not matched:
        return None

    # 1. per-model self-confidence bands (L1 precision) -------------------------
    by_model: dict[str, dict[str, list[bool]]] = {}
    for key, models in matched.items():
        exp1 = T.truncate(gold[key], 1)
        for model, p in models.items():
            ok = T.truncate(p.code, 1) == exp1
            by_model.setdefault(model, {}).setdefault(p.confidence, []).append(ok)
    model_bands = {
        m: {b: {"precision": round(sum(v) / len(v), 3), "n": len(v)}
            for b, v in bands.items()}
        for m, bands in by_model.items()
    }

    # 2. jury consensus: per-level P/R + agreement-band precision ----------------
    jury_pred: dict[str, str] = {}
    agree_bands: dict[str, list[bool]] = {}
    for key, models in matched.items():
        verdict = jury.aggregate({m: p.code for m, p in models.items()})
        jury_pred[key] = verdict.code
        ok1 = T.truncate(verdict.code, 1) == T.truncate(gold[key], 1)
        agree_bands.setdefault(_agreement_band(verdict.agreement, verdict.n_jurors), []).append(ok1)
    jury_levels = level_scores(jury_pred, {k: gold[k] for k in matched}, taxonomy=T)

    # 3. predicted-L1 prevalence over the WHOLE cache (label/prevalence bias) -----
    prevalence: Counter[str] = Counter()
    for p in cache.values():
        prevalence[T.truncate(p.code, 1)] += 1
    n_cache = sum(prevalence.values()) or 1

    return {
        "n_cache_proposals": len(cache),
        "n_gold_matched": len(matched),
        "models_in_cache": sorted({p.model for p in cache.values()}),
        "self_confidence_precision_L1_by_model": model_bands,
        "jury_per_level": jury_levels,
        "jury_agreement_precision_L1": {
            b: {"precision": round(sum(v) / len(v), 3), "n": len(v)}
            for b, v in agree_bands.items()
        },
        "predicted_l1_prevalence_pct": {
            c: round(100 * n / n_cache, 1)
            for c, n in prevalence.most_common(8)
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="also report production coverage on the company vocab")
    ap.add_argument("--cap", type=int, default=None,
                    help="limit the company vocab to the top-N by frequency")
    args = ap.parse_args()

    out: dict = {"validate": _validate()}

    print(f"{'=' * 64}\nGOLD -- company grain (per-level P/R)\n{'=' * 64}")
    g = eval_gold()
    out["gold_companies"] = g
    for lvl, s in g["per_level"].items():
        print(f"  {lvl}: P={s['precision']} R={s['recall']} F1={s['f1']} "
              f"(tp={s['tp']} fp={s['fp']} fn={s['fn']})")
    for d in g["detail"]:
        flag = "" if d["L1_ok"] else "  <-- L1 MISS"
        print(f"    {d['display']:34s} exp={d['expected']:16s} got={d['predicted']:16s} "
              f"[{d['method']}]{flag}")

    print(f"\n{'=' * 64}\nGOLD -- row grain (self-employed occupation prior)\n{'=' * 64}")
    r = eval_rows()
    out["gold_rows"] = r
    print(f"  {r['correct']}/{r['n']} correct")
    for d in r["detail"]:
        print(f"    {d['soc']}  exp={d['expected']:12s} got={d['predicted']:12s} "
              f"{'ok' if d['ok'] else 'MISS'}")

    cal = llm_calibration()
    if cal:
        out["llm_calibration"] = cal
        print(f"\n{'=' * 64}\nLLM CALIBRATION (frozen cache vs gold)\n{'=' * 64}")
        print(f"  cache proposals={cal['n_cache_proposals']:,}  "
              f"gold-matched={cal['n_gold_matched']}  models={cal['models_in_cache']}")
        for m, bands in cal["self_confidence_precision_L1_by_model"].items():
            band_s = "  ".join(f"{b}={v['precision']}(n={v['n']})" for b, v in bands.items())
            print(f"  self-confidence L1 precision [{m}]: {band_s}")
        print("  jury per-level: " + "  ".join(
            f"{lvl} P={s['precision']}/R={s['recall']}" for lvl, s in cal["jury_per_level"].items()))
        print("  jury agreement-band L1 precision: " + "  ".join(
            f"{b}={v['precision']}(n={v['n']})" for b, v in cal["jury_agreement_precision_L1"].items()))
        print(f"  predicted-L1 prevalence (cache top-8): {cal['predicted_l1_prevalence_pct']}")
    else:
        print("\nLLM calibration: no frozen proposal cache (deterministic-only run)")

    if args.full:
        print(f"\n{'=' * 64}\nPRODUCTION coverage (company vocab)\n{'=' * 64}")
        prod = production_report(args.cap)
        out["production"] = prod
        print(f"  companies={prod['n_companies']:,}  rows={prod['total_rows']:,}")
        print(f"  coverage by depth (row %): {prod['coverage_by_depth_row_pct']}")
        print(f"  method by row %: {prod['method_row_pct']}")
        print(f"  review-queue row %: {prod['review_queue_row_pct']}")
        print(f"  L1 distribution: {prod['L1_distribution_row_pct']}")

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "industry_eval.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nwrote {RESULTS / 'industry_eval.json'}")


if __name__ == "__main__":
    main()
