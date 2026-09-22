"""Logic checks for validation/ (no parquet needed).

    uv run python -m validation.validation_tests
"""
from __future__ import annotations

from validation import common as C


def check(name: str, cond: bool) -> None:
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def main() -> None:
    check("year_bucket exact", C.year_bucket(2016, [1991, 2001, 2016]) == 2016)
    check("year_bucket +-1", C.year_bucket(2015, [1991, 2001, 2016]) == 2016)
    check("year_bucket outside tolerance", C.year_bucket(2010, [1991, 2001, 2016]) is None)
    check("year_bucket nearest wins", C.year_bucket(2002, [2001, 2006]) == 2001)
    check("year_bucket None", C.year_bucket(None, [2001]) is None)
    s = C.shares([("23", 10), ("54", 5), ("52", 85)])
    check("shares sum to one", abs(sum(s.values()) - 1.0) < 1e-9)
    check("shares english", abs(s["23"] - 0.10) < 1e-9)
    check("shares empty", C.shares([]) == {})
    check("core6 members", set(C.CORE6) == {"05", "16", "23", "24", "38", "54"})
    check("l1 proxy adds 39 and 50", set(C.L1_PROXY) == set(C.CORE6) | {"39", "50"})
    y = {"total": 1000, "english": 50, "foreign_lang": 10, "liberal_arts_hum": 20, "phil_rel": 5,
         "area_ethnic": 5, "socsci_history": 100, "history": 20, "theology": 3,
         "visual_performing_arts": 40}
    h, est = C.nces_history(y, 0.143)
    check("printed history used", h == 20 and est is False)
    h, est = C.nces_history({**y, "history": None}, 0.143)
    check("estimated history flagged", abs(h - 14.3) < 1e-9 and est is True)
    check("nces core6", abs(C.nces_group_share(y, C.CORE6_LINES, 0.143) - 110 / 1000) < 1e-9)
    check("nces l1 proxy", abs(C.nces_group_share(y, C.L1_PROXY_LINES, 0.143) - 153 / 1000) < 1e-9)
    check("cohort cutoff is ten years before last complete year",
          C.ADVANCED_DEGREE_COHORT_MAX_YEAR == C.LAST_COMPLETE_YEAR - 10)
    print("validation logic tests passed")


if __name__ == "__main__":
    main()
