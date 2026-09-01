"""Evaluate the three self-employment meaning-extraction recs on the FULL
self-employment population, and measure the functional-cluster coverage lift.

    uv run python -m career_clean.run_self_employed

Baseline = the SOC backbone alone (occupation.match -> major group). Then we add,
cumulatively: Rec 1 (qualifier recovery), Rec 2 (company-brand trade). Reports
coverage at each stage, the method/cluster breakdown by row %, the honest
residue, and freq-ranked SAMPLE assignments per method for manual precision
review. Writes career_clean/results/self_employed_eval.json.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from . import approach_a_rules as A
from . import occupation as O
from . import se_cluster as C
from .common import ROOT, load_vocab, timer

OUT = ROOT / "career_clean" / "results" / "self_employed_eval.json"
SELF_EMP_TYPES = {"self_employed", "business_owner"}
_SAMPLE_CAP = 20


def main() -> None:
    by_norm, by_tokens, _ = O.load_onet()
    vocab = load_vocab("employment_type")  # (company, title), freq, modal_id

    se_rows = 0
    baseline_soc = 0  # SOC-only coverage (the audit's 11.9%)
    method_rows: Counter[str] = Counter()
    cluster_rows: Counter[str] = Counter()
    samples: dict[str, list] = defaultdict(list)
    sample_seen: dict[str, set] = defaultdict(set)

    with timer() as t:
        for (company, title), freq, modal_id in vocab:
            emp, _m, _c = A.resolve_employment_type(company=company, title=title)
            if emp not in SELF_EMP_TYPES:
                continue
            se_rows += freq

            # baseline: SOC backbone alone
            soc, _sm = O.match(title or "", by_norm, by_tokens)
            if C.major_group(soc):
                baseline_soc += freq

            cluster, method, conf = C.resolve_functional_cluster(
                company=company, title=title, by_norm=by_norm, by_tokens=by_tokens,
                company_id=modal_id, employment_type=emp, soc_code=soc,
            )
            method_rows[method] += freq
            cluster_rows[cluster] += freq

            # freq-ranked sample per method for manual review
            bucket = samples[method]
            key = (company, title)
            if key not in sample_seen[method]:
                bucket.append({
                    "company": company, "title": title, "freq": freq,
                    "cluster": cluster, "label": C.cluster_label(cluster),
                    "confidence": conf,
                })
                sample_seen[method].add(key)

    for m in samples:
        samples[m] = sorted(samples[m], key=lambda r: -r["freq"])[:_SAMPLE_CAP]

    real = se_rows - sum(v for k, v in cluster_rows.items() if k.endswith("unspecified"))
    report = {
        "self_employment_rows": se_rows,
        "coverage": {
            "baseline_soc_only_pct": round(100 * baseline_soc / se_rows, 2),
            "with_recs_pct": round(100 * real / se_rows, 2),
            "lift_pp": round(100 * (real - baseline_soc) / se_rows, 2),
            "real_clustered_rows": real,
        },
        "method_row_pct": {
            k: round(100 * v / se_rows, 2) for k, v in method_rows.most_common()
        },
        "cluster_distribution": {
            (C.cluster_label(k) or k): {"code": k, "rows": v,
                                        "pct": round(100 * v / se_rows, 2)}
            for k, v in cluster_rows.most_common()
        },
        "runtime_s": round(t.elapsed, 1),
        "samples_by_method": samples,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    cov = report["coverage"]
    print(f"self-employment rows: {se_rows:,}")
    print(f"functional-cluster coverage:")
    print(f"  baseline (SOC only): {cov['baseline_soc_only_pct']}%")
    print(f"  with 3 recs        : {cov['with_recs_pct']}%   (+{cov['lift_pp']}pp)")
    print(f"\nmethod by row %: {report['method_row_pct']}")
    print(f"\ntop clusters:")
    for label, d in list(report["cluster_distribution"].items())[:14]:
        print(f"  {d['code']:>3s} {label:48s} {d['rows']:>9,} ({d['pct']}%)")
    print(f"\nruntime {report['runtime_s']}s   wrote {OUT}")


if __name__ == "__main__":
    main()
