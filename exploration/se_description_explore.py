"""Ground the description-inference lever: what do self-employment RESIDUE
descriptions actually look like, and how often does keyword-voting on them yield
a confident functional cluster?

    uv run python exploration/se_description_explore.py

Residue = a self-employment step (company placeholder OR owner/founder/consultant
title) whose title+company give NO functional cluster today. We sample those with
a description present and (a) print raw descriptions for eyeballing, (b) prototype
the keyword-vote and report the confident-cluster rate + examples.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from career_clean import approach_a_rules as A
from career_clean import occupation as O
from career_clean import se_cluster as C
from career_clean.common import EXP, normalize

# A SQL pre-filter to the self-employment-ish population so we don't scan all 9M.
_SE_FILTER = r"""
  description IS NOT NULL AND length(trim(description)) > 0
  AND (
    regexp_matches(lower(company), '^self.?employ|^freelanc|^independent (contractor|consultant)|^sole proprietor')
    OR regexp_matches(lower(title), '\b(owner|founder|co.?founder|consultant|freelance|self.?employed|entrepreneur|proprietor)\b')
  )
"""


def main() -> None:
    by_norm, by_tokens, _ = O.load_onet()
    con = duckdb.connect()
    rows = con.sql(f"""
        SELECT company, title, description
        FROM {EXP}
        WHERE {_SE_FILTER}
        LIMIT 4000
    """).fetchall()

    residue = []
    for company, title, desc in rows:
        emp, _m, _c = A.resolve_employment_type(company=company, title=title)
        if emp not in ("self_employed", "business_owner"):
            continue
        cl, method, _conf = C.resolve_functional_cluster(
            company=company, title=title, by_norm=by_norm, by_tokens=by_tokens,
            employment_type=emp,
        )
        if method == "unspecified":
            residue.append((company, title, desc))

    print(f"sampled rows: {len(rows)}  residue-with-description: {len(residue)}\n")

    # (a) raw descriptions for eyeballing
    print("=" * 70, "\nRAW RESIDUE DESCRIPTIONS (first 18)\n", "=" * 70, sep="")
    for company, title, desc in residue[:18]:
        d = " ".join(desc.split())[:240]
        print(f"\n[{company!r} | {title!r}]\n  {d}")

    # Generic business/function words that appear in almost every self-employed
    # description ("manage operations", "marketing", "software expertise") and
    # cause 11/13/15 over-firing -> too weak to DECIDE a cluster on their own.
    WEAK = {
        "management", "operations", "marketing", "advertising", "data", "digital",
        "technology", "tech", "software", "web", "media", "design", "creative",
        "recruiting", "recruitment", "staffing", "finance", "financial",
        "network", "networking",
    }

    import re as _re
    _SENT = _re.compile(r"[.•●\n\r|;]")

    def lead_window(text: str) -> str:
        # first sentence / bullet, capped, where self-descriptions name the trade
        first = _SENT.split(text.strip(), 1)[0]
        return first[:200]

    def strong_vote(text: str):
        norm = normalize(text)
        hits: Counter[str] = Counter()
        for pat, kw, cl in C._KEYWORD_PATTERNS:  # noqa: SLF001
            if kw in WEAK:
                continue
            if pat.search(norm):
                hits[cl] += 1
        return hits

    for variant in ("LEAD", "STRONG_VOTE"):
        confident = 0
        cluster_dist: Counter[str] = Counter()
        examples = []
        for company, title, desc in residue:
            if variant == "LEAD":
                cl, kw = C.keyword_cluster(lead_window(desc))
                ok, info = (cl is not None), kw
            else:
                hits = strong_vote(desc)
                cl = hits.most_common(1)[0][0] if hits else None
                n = hits.most_common(1)[0][1] if hits else 0
                second = hits.most_common(2)[1][1] if len(hits) > 1 else 0
                ok, info = (cl is not None and n >= 2 and n > second), dict(hits.most_common(3))
            if ok:
                confident += 1
                cluster_dist[cl] += 1
                if len(examples) < 14:
                    examples.append((title, C.cluster_label(cl), info,
                                     " ".join(desc.split())[:140]))
        print("\n", "=" * 70, f"\nVARIANT: {variant}\n", "=" * 70, sep="")
        print(f"confident: {confident}/{len(residue)} "
              f"({round(100*confident/max(len(residue),1),1)}%)  dist={dict(cluster_dist.most_common())}")
        for title, label, info, snippet in examples:
            print(f"  [{title[:26]!r:28}] -> {label[:26]:26} {info}\n     {snippet}")


if __name__ == "__main__":
    main()
