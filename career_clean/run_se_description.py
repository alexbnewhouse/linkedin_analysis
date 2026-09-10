"""Evaluate the description lever (Rec 4) on the self-employment RESIDUE,
row-level over the experience table (descriptions are row-level / ~unique, so the
deduped vocab used by run_self_employed cannot carry them).

    uv run python -m career_clean.run_se_description

For each self-employment experience row we compute the functional cluster WITHOUT
the description (the prior pipeline) and WITH it. We report: how much of the
title+company residue carries a description, how much of that the description
recovers, the cluster distribution of the recovered rows, and freq-light samples
(evidence keyword + snippet) for manual precision review. Writes
career_clean/results/se_description_eval.json.
"""

from __future__ import annotations

import json
from collections import Counter

import duckdb

from . import approach_a_rules as A
from . import occupation as O
from . import se_cluster as C
from . import se_description as D
from .common import EXP, ROOT, timer

OUT = ROOT / "career_clean" / "results" / "se_description_eval.json"
SELF_EMP = {"self_employed", "business_owner"}

# SQL pre-filter to the self-employment-ish population (Python resolves the truth).
_FILTER = r"""
  (company IS NOT NULL OR title IS NOT NULL)
  AND (
    regexp_matches(lower(company), '^self.?employ|^freelanc|^independent (contractor|consultant)|^sole proprietor')
    OR regexp_matches(lower(title), '\b(owner|founder|co.?founder|consultant|freelance|self.?employed|entrepreneur|proprietor|contractor|independent)\b')
  )
"""


def main() -> None:
    by_norm, by_tokens, _ = O.load_onet()
    con = duckdb.connect()
    cur = con.execute(f"""
        SELECT company, title, description, company_id
        FROM {EXP}
        WHERE {_FILTER}
    """)

    se_rows = residue = residue_with_desc = recovered = 0
    rec_clusters: Counter[str] = Counter()
    desc_method: Counter[str] = Counter()
    samples: dict[str, list] = {}

    with timer() as t:
        while True:
            batch = cur.fetchmany(50_000)
            if not batch:
                break
            for company, title, description, company_id in batch:
                emp, _m, _c = A.resolve_employment_type(company=company, title=title)
                if emp not in SELF_EMP:
                    continue
                se_rows += 1
                # cluster WITHOUT the description (prior pipeline)
                cl0, m0, _c0 = C.resolve_functional_cluster(
                    company=company, title=title, by_norm=by_norm, by_tokens=by_tokens,
                    company_id=company_id, employment_type=emp,
                )
                if m0 != "unspecified":
                    continue
                residue += 1
                if not (description and description.strip()):
                    continue
                residue_with_desc += 1
                d_cl, d_method, d_conf, ev = D.infer_cluster(description)
                desc_method[d_method] += 1
                if d_cl:
                    recovered += 1
                    rec_clusters[d_cl] += 1
                    bucket = samples.setdefault(d_cl, [])
                    if len(bucket) < 12:
                        bucket.append({
                            "company": company, "title": title, "method": d_method,
                            "evidence": ev, "snippet": " ".join(description.split())[:160],
                        })

    clustered_before = se_rows - residue
    clustered_after = clustered_before + recovered
    report = {
        "self_employment_rows_scanned": se_rows,
        "overall_functional_cluster_coverage": {
            "title_company_only_pct": round(100 * clustered_before / max(se_rows, 1), 1),
            "with_description_pct": round(100 * clustered_after / max(se_rows, 1), 1),
            "description_lift_pp": round(100 * recovered / max(se_rows, 1), 1),
        },
        "residue_rows": residue,
        "residue_with_description": residue_with_desc,
        "residue_with_description_pct": round(100 * residue_with_desc / max(residue, 1), 1),
        "recovered_by_description": recovered,
        "recovered_pct_of_residue": round(100 * recovered / max(residue, 1), 1),
        "recovered_pct_of_residue_with_desc": round(100 * recovered / max(residue_with_desc, 1), 1),
        "desc_method_breakdown": dict(desc_method.most_common()),
        "recovered_cluster_distribution": {
            (C.cluster_label(k) or k): {"code": k, "rows": v}
            for k, v in rec_clusters.most_common()
        },
        "runtime_s": round(t.elapsed, 1),
        "samples_by_cluster": {C.cluster_label(k) or k: v for k, v in samples.items()},
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    ov = report["overall_functional_cluster_coverage"]
    print(f"self-employment rows scanned : {se_rows:,}")
    print(f"OVERALL functional-cluster coverage: "
          f"{ov['title_company_only_pct']}% (title+company) -> "
          f"{ov['with_description_pct']}% (+{ov['description_lift_pp']}pp from description)")
    print(f"residue (title+company unspecified): {residue:,}")
    print(f"  with a description         : {residue_with_desc:,} "
          f"({report['residue_with_description_pct']}% of residue)")
    print(f"  recovered by description   : {recovered:,} "
          f"(+{report['recovered_pct_of_residue']}pp of all residue; "
          f"{report['recovered_pct_of_residue_with_desc']}% of described residue)")
    print(f"desc method: {report['desc_method_breakdown']}")
    print("recovered clusters:")
    for label, d in list(report["recovered_cluster_distribution"].items())[:14]:
        print(f"  {d['code']:>3s} {label:46s} {d['rows']:>7,}")
    print(f"\nruntime {report['runtime_s']}s  wrote {OUT}")


if __name__ == "__main__":
    main()
