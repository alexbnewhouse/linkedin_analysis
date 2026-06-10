"""Assertion tests for the NHA humanities field-of-study classification.

Run with:

    uv run python -m edu_clean.humanities_tests

Plain-assert convention (cf. career_clean/se_tests.py, normalization_regression
_checks.py); no pytest dependency. Covers known cases per level, the prefix-
override resolution, and -- on EVERY valid CIP 2020 code -- the nesting invariant
L1 => L2 => L3.
"""

from __future__ import annotations

import duckdb

from .humanities import CIP_CSV, classify, classify_cip


def eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def truthy(actual, label: str) -> None:
    if not actual:
        raise AssertionError(f"{label}: expected truthy, got {actual!r}")


def falsy(actual, label: str) -> None:
    if actual:
        raise AssertionError(f"{label}: expected falsy, got {actual!r}")


# ---------------------------------------------------------- L1 humanities
def check_level1() -> None:
    for code, grp in [
        ("54.0101", "History"),               # History
        ("23.0101", "English & Literature"),  # English
        ("16.0102", "Languages & Linguistics"),
        ("38.0101", "Philosophy & Religion"),  # Philosophy
        ("38.0201", "Philosophy & Religion"),  # Religious studies (secular)
        ("39.0602", "Theology"),              # Theology / ministerial (methodology add)
        ("50.0701", "Fine & Performing Arts"),  # Fine arts (methodology add)
        ("50.0901", "Fine & Performing Arts"),  # Music
        ("05.0103", "Area & Cultural Studies"),  # Area studies
        ("24.0101", "Liberal Arts & Humanities"),
        ("30.2202", "Languages & Linguistics"),  # Classical studies (6-digit override)
        ("30.13", "Area & Cultural Studies"),    # Medieval & Renaissance studies
    ]:
        c = classify_cip(code)
        truthy(c.is_humanities, f"{code} is_humanities (L1)")
        truthy(c.is_humanistic_social_science_incl, f"{code} L2 (nested)")
        truthy(c.is_liberal_arts, f"{code} L3 (nested)")
        eq(c.field_group, grp, f"{code} field_group")


# --------------------------------------- L2 humanistic social science (not L1)
def check_level2() -> None:
    for code in ["45.1101", "45.0201", "45.0301", "45.1001", "45.0701", "45.0901"]:
        # Sociology, Anthropology, Archeology, Political Science, Geography, Intl Rel
        c = classify_cip(code)
        falsy(c.is_humanities, f"{code} NOT L1")
        truthy(c.is_humanistic_social_science_incl, f"{code} is L2")
        truthy(c.is_liberal_arts, f"{code} is L3 (nested)")
    # Communication & media (ACLS), Library & info science, museum studies, STS, peace
    for code in ["09.0101", "25.0101", "30.1401", "30.1501", "30.0501"]:
        c = classify_cip(code)
        falsy(c.is_humanities, f"{code} NOT L1")
        truthy(c.is_humanistic_social_science_incl, f"{code} is L2")
    # Environmental psychology: the one named interpretive psych branch -> L2
    c = classify_cip("42.2101")
    falsy(c.is_humanities, "42.21 env-psych NOT L1")
    truthy(c.is_humanistic_social_science_incl, "42.21 env-psych is L2")


# --------------------- L3 only: economics, general psychology, math, natural sci
def check_level3_only() -> None:
    for code in [
        "45.0601",  # Economics: quantitative social science -> L3 not L2
        "42.0101",  # Psychology, General -> liberal art (L3) not L2
        "27.0101",  # Mathematics
        "27.0501",  # Statistics
        "26.0101",  # Biology
        "40.0801",  # Physics
        "40.0501",  # Chemistry
    ]:
        c = classify_cip(code)
        falsy(c.is_humanities, f"{code} NOT L1")
        falsy(c.is_humanistic_social_science_incl, f"{code} NOT L2")
        truthy(c.is_liberal_arts, f"{code} is L3")


# ------------------------------------------------- excluded (all three false)
def check_excluded() -> None:
    for code in [
        "52.0201",  # Business administration
        "52.0301",  # Accounting
        "51.3801",  # Nursing
        "14.0801",  # Civil engineering
        "13.0101",  # Education (pedagogy)
        "11.0101",  # Computer science (applied/professional)
        "22.0101",  # Law
        "50.1001",  # Arts/entertainment management (business override within arts)
        "30.7001",  # Data Science, General (CIP 2020; applied/professional)
        "30.7102",  # Business Analytics (CIP 2020; applied/professional)
    ]:
        c = classify_cip(code)
        falsy(c.is_humanities, f"{code} NOT L1")
        falsy(c.is_humanistic_social_science_incl, f"{code} NOT L2")
        falsy(c.is_liberal_arts, f"{code} NOT L3")


# --------------------------------------------- prefix / input-form handling
def check_input_forms() -> None:
    eq(classify("cip:54.0101").is_humanities, True, "cip: prefix accepted")
    eq(classify("54.0101").is_humanities, True, "bare code accepted")
    eq(classify("  cip:54  ").field_group, "History", "whitespace + 2-digit family")
    eq(classify(None).level, 0, "None -> level 0")
    eq(classify("").level, 0, "empty -> level 0")
    eq(classify("99.9999").level, 0, "unknown family -> level 0")
    # 6-digit override beats 4-digit beats family
    eq(classify("30.1601").is_liberal_arts, False, "30.16 applied -> excluded")
    eq(classify("30.0101").is_liberal_arts, True, "30.01 natural sci -> L3")


# ----------------------------------- nesting invariant on EVERY CIP 2020 code
def check_nesting_invariant_all_codes() -> None:
    con = duckdb.connect()
    codes = con.sql(
        f"SELECT DISTINCT CIPCode FROM read_csv('{CIP_CSV}') WHERE CIPCode IS NOT NULL"
    ).fetchall()
    n = 0
    for (code,) in codes:
        c = classify_cip(code)
        # L1 => L2 => L3
        if c.is_humanities:
            truthy(c.is_humanistic_social_science_incl, f"{code} L1 implies L2")
        if c.is_humanistic_social_science_incl:
            truthy(c.is_liberal_arts, f"{code} L2 implies L3")
        # level/boolean consistency
        eq(c.is_humanities, c.level == 1, f"{code} L1 matches level")
        eq(c.is_humanistic_social_science_incl, c.level in (1, 2), f"{code} L2 matches level")
        eq(c.is_liberal_arts, c.level in (1, 2, 3), f"{code} L3 matches level")
        n += 1
    truthy(n > 2000, "iterated all CIP codes")
    print(f"  nesting invariant holds for all {n} CIP 2020 codes")


def main() -> None:
    check_level1()
    check_level2()
    check_level3_only()
    check_excluded()
    check_input_forms()
    check_nesting_invariant_all_codes()
    print("all humanities classification tests passed")


if __name__ == "__main__":
    main()
