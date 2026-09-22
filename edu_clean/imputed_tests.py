"""Logic checks for the imputed-bachelor tier.

    uv run python -m edu_clean.imputed_tests
"""
from __future__ import annotations

from edu_clean.imputed_bachelor import (LEVEL, SOURCE, carnegie_excluded, degree_negative,
                                        not_completed, predicate_sql, school_excluded)


def check(name: str, cond: bool) -> None:
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def main() -> None:
    for s in ("Lincoln High School", "Coursera", "Udemy", "General Assembly", "Harvard Law School",
              "Stanford Graduate School of Business", "Princeton Theological Seminary",
              "Johns Hopkins School of Medicine", "St. Mary's Preparatory", "Codecademy",
              "Community College of Denver", "Lone Star College-Tomball Career Center",
              "Western State College of Law", "Empire Beauty School", "Aveda Institute Cosmetology"):
        check(f"excluded: {s}", school_excluded(s))
    for s in ("University of Colorado Boulder", "Oberlin College", "Rutgers University–New Brunswick",
              "The Ohio State University", "Yale University", "School of Visual Arts",
              "Broward College"):
        check(f"kept by regex: {s}", not school_excluded(s))
    check("None school excluded", school_excluded(None))
    check("blank school excluded", school_excluded("   "))

    for d in ("None", "N/A", "Real Estate License", "Certified", "Coursework", "Study Abroad",
              "Minor", "Continuing Education", "Residency", "In Progress", "Some College",
              "A.A.S.", "MSEE", "Teaching Credential", "Semester Abroad", "Associate", "M.A.",
              "PhD", "High School Diploma", "Exchange Program"):
        check(f"negative degree token: {d}", degree_negative(d))
    for d in ("Psychology", "Business Administration and Management, General", "Computer Science",
              "Graphic Design", "Mechanical Engineering", "Political Science and Government",
              "Mathematics", "Marketing", None, ""):
        check(f"no negative token: {d!r}", not degree_negative(d))

    for c in ("bacc_associates_dominant", "bacc_associates_mixed", "assoc_high_transfer_high_trad",
              "assoc_mixed_mixed"):
        check(f"carnegie excluded: {c}", carnegie_excluded(c))
    for c in ("R1_doctoral_very_high", "masters_larger", "bacc_arts_sciences", "bacc_diverse",
              "special_focus_4yr_arts", "not_applicable", None):
        check(f"carnegie kept: {c}", not carnegie_excluded(c))

    for d in ("Did not complete degree program", "transferred out after two years", "Dropped out in 2009",
              "Withdrew to join the Army", "did not finish"):
        check(f"not completed: {d}", not_completed(d))
    for d in ("Completed 2012, Dean's List", "Activities and Societies: debate", None, ""):
        check(f"completed / neutral: {d!r}", not not_completed(d))
    check("source constant", SOURCE == "imputed_bachelor")
    check("level is bachelor's ordinal", LEVEL == 4)
    sql = predicate_sql("e", "lvl", "g")
    for frag in ("e.degree_level_pooled IS NULL", "e.cip2_pooled <> '53'",
                 "e.degree_method = 'cip_from_degree'", "degree_negative(e.degree_raw)",
                 "school_excluded(e.school_raw)", "degree_negative(e.field_raw)", "not_completed(e.description)", "lvl.iclevel_label = '4yr+'",
                 "carnegie_excluded(lvl.carnegie_label)", "g.bachelor_elsewhere", "g.grad_same_school"):
        check(f"predicate has {frag}", frag in sql)
    print("imputed-bachelor logic tests passed")


if __name__ == "__main__":
    main()
