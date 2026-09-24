"""Logic checks for skill_breadth/build_cohort.py, against an in-memory
DuckDB fixture (no parquet needed).

    uv run python -m skill_breadth.skill_breadth_tests
"""

from __future__ import annotations

from . import build_cohort as B
from . import common as C


def check(name: str, cond: bool) -> None:
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


LONG_DESC_A = "Managed cross-functional projects and coordinated with many stakeholders."
LONG_DESC_B = "Led a small team and wrote reports summarizing quarterly outcomes weekly."
SHORT_DESC = "short"
assert len(LONG_DESC_A) >= 50 and len(LONG_DESC_B) >= 50 and len(SHORT_DESC) < 50


def build_fixture(con) -> None:
    con.sql("""
        CREATE TABLE fx_education AS
        SELECT * FROM (VALUES
            -- one clean bachelor's row per headline group
            ('p1', '23.0101', '23', 1, 4, false),   -- humanities
            ('p2', '45.0601', '45', 2, 4, false),   -- humanistic_social_sciences
            ('p3', '15.0101', '15', 0, 4, false),   -- stem
            ('p4', '52.0801', '52', 0, 4, false),   -- finance
            -- p5: two bachelor rows landing in two different groups -> excluded
            ('p5', '23.0101', '23', 1, 4, false),   -- humanities
            ('p5', '11.0101', '11', 0, 4, false),   -- stem
            -- p6: one row that matches humanities AND the liberal_arts sanity
            -- group at once -> also excluded (row-level double match)
            ('p6', '24.0101', '24', 1, 4, false),
            -- p7: clean single-group match but bachelor_end_year is out of
            -- the cohort window -> not in persons, not counted as multi-group
            ('p7', '23.0101', '23', 1, 4, false),
            -- p1 also has a non-bachelor row (should be ignored) and a
            -- bachelor row marked is_duplicate (should be ignored)
            ('p1', '15.0101', '15', 0, 5, false),
            ('p1', '52.0801', '52', 0, 4, true),
            -- p8: one matching (finance) row plus one unrelated bachelor row
            -- that matches NO group at all -> bachelor_cip must come from the
            -- matching row only, not MIN() over every bachelor row (F1 bug)
            ('p8', '52.0801', '52', 0, 4, false),
            ('p8', '01.0000', '01', 0, 4, false),
            -- p9: matching row is an nha_level_pooled-imputed row with no
            -- cip_code -> bachelor_cip should come out NULL, not error
            ('p9', NULL, NULL, 1, 4, false),
            -- p10/p11/p12: sanity-group-only matches (no headline group hit)
            -- must now surface as their own group values, not be dropped
            ('p10', '24.0102', '24', 3, 4, false),   -- liberal_arts
            ('p11', '51.3801', '51', 0, 4, false),   -- nursing
            ('p12', '52.0301', '52', 0, 4, false)    -- accounting
        ) AS t(linkedin_id, cip_code, cip2_pooled, nha_level_pooled, degree_level_pooled, is_duplicate)
    """)
    con.sql("""
        CREATE TABLE fx_education_person AS
        SELECT * FROM (VALUES
            ('p1', 2005), ('p2', 2006), ('p3', 2007), ('p4', 2008),
            ('p5', 2009), ('p6', 2010), ('p7', 1999), ('p8', 2011),
            ('p9', 2012), ('p10', 2013), ('p11', 2013), ('p12', 2013)
        ) AS t(linkedin_id, bachelor_end_year)
    """)
    con.sql(f"""
        CREATE TABLE fx_career_steps AS
        SELECT * FROM (VALUES
            -- p1, window 2005-2015
            ('p1', 0, 0, 'Editor', '{LONG_DESC_A}', 2006, NULL, false),
            ('p1', 1, 0, 'Manager', '{LONG_DESC_A}', 2020, NULL, false),   -- out of window
            ('p1', 2, 0, 'Assistant', '{SHORT_DESC}', 2007, NULL, false), -- short description
            ('p1', 3, 0, 'Writer', '{LONG_DESC_A}', 2008, NULL, false),   -- duplicate role key #1
            ('p1', 3, 0, 'Writer', '{LONG_DESC_B}', 2008, NULL, false),   -- duplicate role key #2
            ('p1', 4, 0, 'Blocked', '{LONG_DESC_A}', 2009, NULL, true),   -- is_duplicate
            -- one role each for p2/p3/p4 so every headline group has roles
            ('p2', 0, 0, 'Analyst', '{LONG_DESC_A}', 2007, NULL, false),
            ('p3', 0, 0, 'Engineer', '{LONG_DESC_A}', 2008, '15-1252', false),
            ('p4', 0, 0, 'Analyst', '{LONG_DESC_B}', 2009, NULL, false),
            -- one role for a sanity-group-only person, to confirm roles flow
            -- through for the sanity groups too
            ('p10', 0, 0, 'Advisor', '{LONG_DESC_A}', 2014, NULL, false)
        ) AS t(linkedin_id, experience_idx, position_idx, title_raw, description,
               start_year, occupation_code_pooled, is_duplicate)
    """)


def main() -> None:
    con = C.connect()
    build_fixture(con)

    persons_rel = B.group_assignment_relation(con, "fx_education", "fx_education_person")
    con.sql("CREATE TEMP TABLE fx_persons AS SELECT * FROM persons_rel")

    check("one person per headline group, correct group + bachelor_cip",
          con.sql('SELECT linkedin_id, "group", bachelor_end_year, bachelor_cip FROM fx_persons '
                  "WHERE linkedin_id IN ('p1','p2','p3','p4') ORDER BY linkedin_id").fetchall() == [
              ("p1", "humanities", 2005, "23.0101"),
              ("p2", "humanistic_social_sciences", 2006, "45.0601"),
              ("p3", "stem", 2007, "15.0101"),
              ("p4", "finance", 2008, "52.0801"),
          ])
    check("p5/p6 (multi-group) and p7 (out-of-window) excluded", con.sql(
        "SELECT count(*) FROM fx_persons WHERE linkedin_id IN ('p5','p6','p7')"
    ).fetchone()[0] == 0)
    check("bachelor_cip comes from the matching row only, not any bachelor row "
          "(p8 also has an unrelated non-matching row with a lexically-smaller cip_code)",
          con.sql('SELECT "group", bachelor_cip FROM fx_persons WHERE linkedin_id=\'p8\''
                  ).fetchone() == ("finance", "52.0801"))
    check("bachelor_cip is NULL when the only matching row is an nha-imputed row with no cip_code",
          con.sql('SELECT "group", bachelor_cip FROM fx_persons WHERE linkedin_id=\'p9\''
                  ).fetchone() == ("humanities", None))
    check("sanity groups (nursing/accounting/liberal_arts) surface as their own group values",
          con.sql('SELECT linkedin_id, "group" FROM fx_persons '
                  "WHERE linkedin_id IN ('p10','p11','p12') ORDER BY linkedin_id").fetchall() == [
              ("p10", "liberal_arts"),
              ("p11", "nursing"),
              ("p12", "accounting"),
          ])
    check("fx_persons has exactly the 9 expected persons",
          con.sql("SELECT count(*) FROM fx_persons").fetchone()[0] == 9)

    n_multi = B.excluded_multi_group_count(con, "fx_education", "fx_education_person")
    check("p5 (two groups) and p6 (row-level double match) both counted excluded",
          n_multi == 2)

    n_before = con.sql(
        f"SELECT count(*) FROM ({B._joined_roles_sql('fx_persons', 'fx_career_steps')})"
    ).fetchone()[0]
    roles_rel = B.roles_relation(con, "fx_persons", "fx_career_steps")
    con.sql("CREATE TEMP TABLE fx_roles AS SELECT * FROM roles_rel")
    n_after = con.sql("SELECT count(*) FROM fx_roles").fetchone()[0]

    check("role key unique after dedupe", con.sql(
        "SELECT count(*) FROM (SELECT linkedin_id, experience_idx, position_idx, count(*) c "
        "FROM fx_roles GROUP BY 1,2,3 HAVING c > 1)"
    ).fetchone()[0] == 0)
    check("one duplicate role key removed", n_before - n_after == 1)

    roles_by_person = dict(con.sql(
        "SELECT linkedin_id, count(*) FROM fx_roles GROUP BY 1"
    ).fetchall())
    check("p1: in-window/long-description/non-duplicate roles kept (2 of 4 candidate rows)",
          roles_by_person.get("p1") == 2)
    check("out-of-window role dropped", con.sql(
        "SELECT count(*) FROM fx_roles WHERE linkedin_id='p1' AND start_year=2020"
    ).fetchone()[0] == 0)
    check("short-description role dropped", con.sql(
        "SELECT count(*) FROM fx_roles WHERE linkedin_id='p1' AND title_raw='Assistant'"
    ).fetchone()[0] == 0)
    check("is_duplicate role dropped", con.sql(
        "SELECT count(*) FROM fx_roles WHERE linkedin_id='p1' AND title_raw='Blocked'"
    ).fetchone()[0] == 0)
    check("p2/p3/p4 each keep their one role", roles_by_person.get("p2") == 1
          and roles_by_person.get("p3") == 1 and roles_by_person.get("p4") == 1)

    check("role_text concatenates title_raw + description", con.sql(
        f"SELECT role_text FROM fx_roles WHERE linkedin_id='p3'"
    ).fetchone()[0] == f"Engineer. {LONG_DESC_A}")
    check("occupation_code_pooled passes through", con.sql(
        "SELECT occupation_code_pooled FROM fx_roles WHERE linkedin_id='p3'"
    ).fetchone()[0] == "15-1252")
    check("group carried onto roles", con.sql(
        "SELECT \"group\" FROM fx_roles WHERE linkedin_id='p3'"
    ).fetchone()[0] == "stem")
    check("sanity-group person's role carries its sanity group", con.sql(
        "SELECT \"group\" FROM fx_roles WHERE linkedin_id='p10'"
    ).fetchone()[0] == "liberal_arts")

    print("skill_breadth logic tests passed")


if __name__ == "__main__":
    main()
