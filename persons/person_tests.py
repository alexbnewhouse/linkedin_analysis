"""Logic checks for persons/ (no parquet needed).

    uv run python -m persons.person_tests
"""
from __future__ import annotations

from persons import common as C


def check(name: str, cond: bool) -> None:
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def main() -> None:
    check("stage 0", C.stage(0) == "0-2")
    check("stage 5", C.stage(5) == "3-5")
    check("stage 10", C.stage(10) == "6-10")
    check("stage 20", C.stage(20) == "11-20")
    check("stage 40", C.stage(40) == "21+")
    check("stage None", C.stage(None) is None)
    check("stage negative", C.stage(-1) is None)
    check("stage_sql covers the same bins", all(f"'{s}'" in C.stage_sql("x") for s in C.STAGE_ORDER))
    a = C.attainment("senior,vice")
    check("vp attainment", a == {"manager_plus": True, "director_plus": True, "vp_plus": True})
    check("manager only", C.attainment("manager") == {"manager_plus": True, "director_plus": False, "vp_plus": False})
    check("director", C.attainment("director") == {"manager_plus": True, "director_plus": True, "vp_plus": False})
    check("head counts as manager", C.attainment("head")["manager_plus"])
    check("senior is not manager", not C.attainment("senior")["manager_plus"])
    check("empty", C.attainment("") == {"manager_plus": False, "director_plus": False, "vp_plus": False})
    check("None", C.attainment(None)["manager_plus"] is False)
    check("entropy uniform", abs(C.entropy([1, 1, 1, 1]) - 1.386294) < 1e-5)
    check("entropy single", C.entropy([7]) == 0.0)
    check("entropy empty", C.entropy([]) == 0.0)
    check("cover80", C.cover80([50, 30, 10, 10]) == 2)
    check("cover80 flat", C.cover80([1, 1, 1, 1, 1]) == 4)
    check("top3", abs(C.top3([50, 30, 10, 10]) - 0.9) < 1e-9)
    kept, n_sup = C.suppress([("a", 12), ("b", 9), ("c", 10)], 10)
    check("suppress: one small cell also takes the next-smallest", kept == [("a", 12)] and n_sup == 2)
    kept, n_sup = C.suppress([("a", 12), ("b", 9), ("c", 10), ("d", 3)], 10)
    check("suppress: two small cells, no secondary", kept == [("a", 12), ("c", 10)] and n_sup == 2)
    kept, n_sup = C.suppress([("a", 12), ("c", 10)], 10)
    check("suppress: nothing small", kept == [("a", 12), ("c", 10)] and n_sup == 0)
    kept, n_sup = C.suppress([("b", 9)], 10)
    check("suppress: single small cell alone", kept == [] and n_sup == 1)
    check("count reported only when >= 2", C.suppressed_count_for_output(1) is None and C.suppressed_count_for_output(2) == 2)
    check("floor is the portal floor", C.MIN_SUPPORT == 10)
    check("snapshot constants come from paths.common", C.LAST_COMPLETE_YEAR == 2025 and C.SNAPSHOT_YEAR == 2026)
    print("persons logic tests passed")


if __name__ == "__main__":
    main()
