"""Sanity checks for the humanities enrichment possibility-space summary.

    uv run python -m enrichment.enrichment_tests
"""
from __future__ import annotations

from enrichment import build_enrichment as B


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def run() -> None:
    r = B.build()
    h, b = r["humanities_pooled"], r["non_humanities_baseline"]
    check("humanities population non-empty", h["n_persons"] > 100_000)
    check("baseline population non-empty", b["n_persons"] > 500_000)
    pct_keys = ("volunteer_pct", "publications_pct", "honors_pct",
                "org_leadership_pct", "professional_multilingual_pct")
    for g in (h, b):
        for k in pct_keys:
            check(f"{k} in [0,100]", 0.0 <= g[k] <= 100.0)
    check("language majors more multilingual than baseline",
          r["by_subfield"]["Languages & Linguistics"]["professional_multilingual_pct"]
          > b["professional_multilingual_pct"])
    check("every reported sub-field has a population",
          all(v["n_persons"] > 0 for v in r["by_subfield"].values()))
    print("\nall enrichment checks passed")


if __name__ == "__main__":
    run()
