"""Audit: how much FUNCTIONAL / INDUSTRY meaning do we currently extract from
self-employment-type career steps?

The employment_type axis already classifies the *status* (self_employed,
business_owner, ...). The open question for clustering is: of those rows, how
many also get a usable functional signal (an O*NET-SOC code)? This script
measures occupation coverage *within* the self-employment sub-population and
breaks down the uncoded remainder by title shape, so we can target the gap.

    uv run python exploration/self_employed_audit.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from career_clean import approach_a_rules as A
from career_clean import occupation as O
from career_clean.common import ROOT, load_vocab, normalize

OUT = ROOT / "career_clean" / "results" / "self_employed_audit.json"

SELF_EMP_TYPES = {"self_employed", "business_owner"}


def main() -> None:
    by_norm, by_tokens, _ = O.load_onet()
    vocab = load_vocab("employment_type")  # (company, title), freq, modal_id

    # row tallies
    total_rows = 0
    emp_rows: Counter[str] = Counter()
    # within self-employment population
    se_rows = 0
    se_coded = 0
    se_method: Counter[str] = Counter()
    # uncoded self-employment titles, by head-noun shape
    uncoded_head: Counter[str] = Counter()
    uncoded_examples: dict[str, Counter] = {}

    OWNER = {"owner", "proprietor"}
    FOUNDER = {"founder", "cofounder"}

    for (company, title), freq, _modal_id in vocab:
        total_rows += freq
        emp, _m, _c = A.resolve_employment_type(company=company, title=title)
        emp_rows[emp] += freq
        if emp not in SELF_EMP_TYPES:
            continue
        se_rows += freq
        code, method = O.match(title or "", by_norm, by_tokens)
        if code:
            se_coded += freq
            se_method[method] += freq
        else:
            ntoks = set(normalize(title).split())
            if ntoks & OWNER:
                head = "owner"
            elif ntoks & FOUNDER:
                head = "founder"
            elif "consultant" in ntoks:
                head = "consultant"
            elif not ntoks:
                head = "<empty title>"
            else:
                head = "other"
            uncoded_head[head] += freq
            ex = uncoded_examples.setdefault(head, Counter())
            if title:
                ex[title] += freq

    report = {
        "total_career_step_rows": total_rows,
        "employment_type_distribution": {
            k: {"rows": v, "pct": round(100 * v / total_rows, 2)}
            for k, v in emp_rows.most_common()
        },
        "self_employment_population": {
            "rows": se_rows,
            "pct_of_all": round(100 * se_rows / total_rows, 2),
            "occupation_coded_rows": se_coded,
            "occupation_coverage_pct": round(100 * se_coded / se_rows, 2) if se_rows else 0,
            "coded_by_method": dict(se_method.most_common()),
        },
        "uncoded_self_employment_by_head": {
            head: {
                "rows": cnt,
                "pct_of_uncoded": round(100 * cnt / (se_rows - se_coded), 2),
                "top_titles": dict(uncoded_examples.get(head, Counter()).most_common(12)),
            }
            for head, cnt in uncoded_head.most_common()
        },
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    # console summary
    se = report["self_employment_population"]
    print(f"total rows: {total_rows:,}")
    print(f"self-employment pop: {se['rows']:,} ({se['pct_of_all']}%)  "
          f"occupation coverage: {se['occupation_coverage_pct']}%")
    print("uncoded self-employment by head noun:")
    for head, d in report["uncoded_self_employment_by_head"].items():
        print(f"  {head:14s} {d['rows']:>9,}  ({d['pct_of_uncoded']}% of uncoded)")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
