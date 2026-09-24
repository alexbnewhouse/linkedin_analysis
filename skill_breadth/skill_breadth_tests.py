"""Logic checks for skill_breadth/build_cohort.py, against an in-memory
DuckDB fixture (no parquet needed).

    uv run python -m skill_breadth.skill_breadth_tests
"""

from __future__ import annotations

import numpy as np

from . import build_cohort as B
from . import common as C
from . import onet_skills as O


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


def check_onet() -> None:
    check("SOC truncation: 8-digit O*NET-SOC detail code -> 6-digit SOC",
          O.truncate_soc("15-1252.00") == "15-1252")
    check("SOC truncation: already-6-digit code passes through unchanged",
          O.truncate_soc("15-1252") == "15-1252")

    fixture = np.array([
        [1.0, 10.0, 100.0],
        [2.0, 20.0, 100.0],
        [3.0, 30.0, 400.0],
        [4.0, 40.0, 400.0],
    ])
    expected_z = (fixture - fixture.mean(axis=0)) / fixture.std(axis=0, ddof=0)
    expected_unit = expected_z / np.linalg.norm(expected_z, axis=1, keepdims=True)
    actual = O.zscore_l2_normalize(fixture)
    check("z-score + L2-normalize matches the column-zscore-then-row-unit-norm formula",
          bool(np.allclose(actual, expected_unit)))
    check("z-score + L2-normalize produces unit rows",
          bool(np.allclose(np.linalg.norm(actual, axis=1), 1.0, atol=1e-6)))

    valid = {"15-1252", "29-1141", "13-2011"}
    check("a role with a known pooled SOC keeps it",
          O.pooled_soc_assignment("29-1141", valid) == ("29-1141", "pooled"))
    check("a role with a pooled SOC absent from the skills table falls back to nearest",
          O.pooled_soc_assignment("99-9999", valid) == (None, "nearest"))
    check("a role with no pooled SOC at all falls back to nearest",
          O.pooled_soc_assignment(None, valid) == (None, "nearest"))

    # insert_backfilled_socs: generalizes round 2's single-SOC
    # insert_imputed_soc to N SOCs at once. "15-1252" here stands in for the
    # real 15-1252 case (mean of two O*NET 22.0 source rows) -- same
    # scenario as round 2's test, now exercised through the general
    # multi-SOC path -- plus a second backfilled SOC ("13-2051", standing in
    # for "Financial and Investment Analysts") to confirm N>1 works. The
    # pure function's job is correct insertion + sorted-position
    # bookkeeping, not the mean itself (that's a plain duckdb avg(), grouped
    # by the crosswalk join, exercised by the real build instead).
    base_socs = ["11-1011", "14-2011"]
    base_skills = ["Writing", "Mathematics"]
    base_mat = np.array([[1.0, 2.0], [3.0, 4.0]])
    backfill = {
        "15-1252": {"Writing": 15.0, "Mathematics": 35.0},  # stand-in mean of two source rows
        "13-2051": {"Writing": 8.0, "Mathematics": 42.0},
    }
    socs2, mat2 = O.insert_backfilled_socs(base_socs, base_mat, base_skills, backfill)
    check("insert_backfilled_socs: new SOCs land in ascending sorted position",
          socs2 == ["11-1011", "13-2051", "14-2011", "15-1252"])
    check("insert_backfilled_socs: each inserted row equals its backfill values",
          bool(np.allclose(mat2[socs2.index("15-1252")], [15.0, 35.0]))
          and bool(np.allclose(mat2[socs2.index("13-2051")], [8.0, 42.0])))
    check("insert_backfilled_socs: existing rows untouched (order may shift with new insertions)",
          bool(np.allclose(mat2[socs2.index("11-1011")], base_mat[0]))
          and bool(np.allclose(mat2[socs2.index("14-2011")], base_mat[1])))
    noop_socs, noop_mat = O.insert_backfilled_socs(base_socs, base_mat, base_skills, {})
    check("insert_backfilled_socs: empty backfill is a no-op",
          noop_socs == base_socs and bool(np.array_equal(noop_mat, base_mat)))
    try:
        O.insert_backfilled_socs(base_socs, base_mat, base_skills, {"11-1011": {"Writing": 1.0, "Mathematics": 2.0}})
        check("insert_backfilled_socs: rejects a SOC already present", False)
    except ValueError:
        check("insert_backfilled_socs: rejects a SOC already present", True)
    try:
        O.insert_backfilled_socs(base_socs, base_mat, base_skills, {"15-1252": {"Writing": 1.0}})
        check("insert_backfilled_socs: rejects an incomplete skill set", False)
    except ValueError:
        check("insert_backfilled_socs: rejects an incomplete skill set", True)

    # hybrid_nearest_soc: tiny fake (unit-vector) embeddings. Two SOCs whose
    # title candidates are IDENTICAL (a tied title term, standing in for a
    # generic title like "Founder" or "Owner" matching some unrelated SOC's
    # alternate title just as well as the intended one) -- the description
    # term must be the one that picks the correct SOC.
    socs = ["11-1011", "29-1229"]  # sorted ascending
    cand_socs = ["11-1011", "29-1229"]
    cand_vecs = np.array([
        [1.0, 0.0],  # SOC 11-1011's title candidate
        [1.0, 0.0],  # SOC 29-1229's title candidate -- identical direction, ties the title term
    ], dtype=np.float32)
    title_vec = np.array([1.0, 0.0], dtype=np.float32)
    soc_desc_vecs = np.array([
        [1.0, 0.0],  # SOC 11-1011's description
        [0.0, 1.0],  # SOC 29-1229's description -- matches desc_vec below, SOC 11-1011's doesn't
    ], dtype=np.float32)
    desc_vec = np.array([0.0, 1.0], dtype=np.float32)
    soc, title_term, desc_term = O.hybrid_nearest_soc(title_vec, desc_vec, cand_vecs, cand_socs, soc_desc_vecs, socs)
    check("hybrid_nearest_soc: title term ties across two SOCs; description term picks the right one",
          soc == "29-1229" and abs(title_term - 1.0) < 1e-6 and abs(desc_term - 1.0) < 1e-6)

    # Full tie on both terms -> deterministic tie-break toward the lowest SOC code.
    tied_desc_vecs = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    soc_tied, _, _ = O.hybrid_nearest_soc(title_vec, title_vec, cand_vecs, cand_socs, tied_desc_vecs, socs)
    check("hybrid_nearest_soc: a full tie on both terms breaks toward the lowest SOC code",
          soc_tied == "11-1011")

    # drop_title_term: an EXACT title match (cosine 1.0) against the wrong
    # SOC would normally dominate the sum outright -- standing in for
    # "Owner" exactly matching Physicians All Other's alt title. With
    # drop_title_term=True (the generic-status-title path) the title term
    # must be ignored entirely, even though it's not merely tied but
    # actually the stronger signal; only the description term decides.
    generic_cand_socs = ["11-1011", "29-1229"]
    generic_cand_vecs = np.array([
        [1.0, 0.0],  # 11-1011's title candidate -- far from the query
        [0.0, 0.0],  # 29-1229's title candidate -- zero vector, cosine 0 regardless of query
    ], dtype=np.float32)
    generic_title_vec = np.array([1.0, 0.0], dtype=np.float32)  # exact match to 11-1011's candidate
    generic_desc_vecs = np.array([
        [0.0, 1.0],  # 11-1011's description -- far from desc_vec
        [1.0, 0.0],  # 29-1229's description -- matches desc_vec: the actually-correct SOC
    ], dtype=np.float32)
    generic_desc_vec = np.array([1.0, 0.0], dtype=np.float32)
    with_title, _, _ = O.hybrid_nearest_soc(
        generic_title_vec, generic_desc_vec, generic_cand_vecs, generic_cand_socs, generic_desc_vecs, socs)
    check("hybrid_nearest_soc: with the title term included, an exact-but-wrong title match wins",
          with_title == "11-1011")
    without_title, title_term_reported, desc_term_reported = O.hybrid_nearest_soc(
        generic_title_vec, generic_desc_vec, generic_cand_vecs, generic_cand_socs, generic_desc_vecs, socs,
        drop_title_term=True)
    check("hybrid_nearest_soc: drop_title_term=True ignores it, description picks the actually-correct SOC",
          without_title == "29-1229")
    check("hybrid_nearest_soc: drop_title_term=True still reports both terms for diagnostics",
          abs(title_term_reported - 0.0) < 1e-6 and abs(desc_term_reported - 1.0) < 1e-6)

    check("GENERIC_TITLES includes career_clean.occupation's set plus the local intern/volunteer union",
          {"owner", "founder", "consultant"} <= O.GENERIC_TITLES
          and {"intern", "internship", "summer intern", "volunteer"} <= O.GENERIC_TITLES)
    check("GENERIC_TITLES membership uses career_clean.occupation.normalize (case/punctuation-insensitive)",
          O.normalize("Business Owner") in O.GENERIC_TITLES and O.normalize("Software Engineer") not in O.GENERIC_TITLES)

    print("skill_breadth O*NET-mapping tests passed")


if __name__ == "__main__":
    main()
    check_onet()
