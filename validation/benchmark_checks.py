"""Data-level tripwires on the committed external-benchmark results.

    uv run python -m validation.benchmark_checks      (make test-data)

These are tripwires for a broken CIP or degree-level apply, not targets: a ratio far
outside the band means a tier changed shape, not that LinkedIn "should" match NCES.
"""
from __future__ import annotations

import json

from validation import common as C

MIN_ROWS_PER_YEAR = 1_000
RATIO_BAND = (0.5, 1.5)
MIN_ADVANCED_N = 10_000


def ok(name: str) -> None:
    print(f"  ok: {name}")


def main() -> None:
    r = json.loads(C.OUT.read_text())
    assert r["release"].get("git"), "release stamp missing git sha"
    ok("release stamp present")
    for y, e in r["years"].items():
        assert e["linkedin_n"] >= MIN_ROWS_PER_YEAR, f"{y}: only {e['linkedin_n']} rows"
        for grp in ("core6", "l1_proxy"):
            ratio = e[grp]["ratio"]
            assert ratio is not None and RATIO_BAND[0] <= ratio <= RATIO_BAND[1], \
                f"{y} {grp} ratio {ratio} outside {RATIO_BAND}"
    ok(f"every Digest year has >= {MIN_ROWS_PER_YEAR:,} rows and core6/l1_proxy ratios in {RATIO_BAND}")
    a = r["advanced_degree_rate"]
    assert a["n_cohort"] >= MIN_ADVANCED_N, f"advanced-degree cohort n={a['n_cohort']}"
    assert 0.0 < a["linkedin_hum_l1_bachelor_cohort"] < 1.0
    ok("advanced-degree comparison has a cohort of >= 10,000 persons")
    print("benchmark checks passed")


if __name__ == "__main__":
    main()
