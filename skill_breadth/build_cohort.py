"""Task 1: cohort and role table.

Builds:
  results/persons.parquet     -- linkedin_id, group, bachelor_end_year, bachelor_cip
  results/roles.parquet       -- linkedin_id, group, experience_idx, position_idx,
                                  start_year, title_raw, occupation_code_pooled, role_text
  results/_cohort_manifest.json

The group-assignment and role-filter SQL is factored into functions that take
table *names* (defaulting to the real normalized/ views) rather than
hard-coded file paths, so skill_breadth_tests.py can point them at small
in-memory fixture tables registered under other names.

    uv run python -m skill_breadth.build_cohort
"""

from __future__ import annotations

import duckdb

from . import common as C


def _case_exprs(groups: dict[str, str]) -> str:
    return ",\n            ".join(
        f"CASE WHEN {cond} THEN '{name}' END" for name, cond in groups.items()
    )


def _person_groups_cte(education_tbl: str) -> str:
    """CTE SQL: linkedin_id, n_groups, sole_group -- the distinct set of
    ALL_GROUPS (headline + sanity) each person's bachelor rows match."""
    return f"""
        bach AS (
            SELECT linkedin_id, cip_code, cip2_pooled, nha_level_pooled
            FROM {education_tbl}
            WHERE degree_level_pooled = 4 AND NOT is_duplicate
        ),
        tagged AS (
            SELECT linkedin_id, cip_code,
                   list_filter(
                       [{_case_exprs(C.ALL_GROUPS)}],
                       x -> x IS NOT NULL
                   ) AS groups
            FROM bach
        ),
        exploded AS (
            SELECT linkedin_id, cip_code, unnest(groups) AS grp
            FROM tagged
            WHERE len(groups) > 0
        ),
        person_groups AS (
            SELECT linkedin_id,
                   count(DISTINCT grp) AS n_groups,
                   any_value(grp) AS sole_group
            FROM exploded
            GROUP BY linkedin_id
        )
    """


def group_assignment_relation(
    con: duckdb.DuckDBPyConnection,
    education_tbl: str = "education",
    education_person_tbl: str = "education_person",
) -> duckdb.DuckDBPyRelation:
    """linkedin_id, group, bachelor_end_year, bachelor_cip for the 4-group cohort.

    A person is included only if:
      - they have >= 1 bachelor's row (degree_level_pooled = 4, NOT is_duplicate)
      - across ALL their bachelor rows, exactly one group is matched, among the
        4 headline groups + 3 sanity groups -- a person hitting more than one
        (even a headline group plus a sanity group) is excluded
      - that one group is a headline group (humanities/humss/stem/finance)
      - their bachelor_end_year (from education_person) falls in
        [COHORT_YEAR_MIN, COHORT_YEAR_MAX]
    bachelor_cip is the smallest cip_code among that person's matching rows
    (deterministic tiebreak; usually there is exactly one such row).
    """
    headline_list = ", ".join(f"'{g}'" for g in C.HEADLINE_GROUPS)
    return con.sql(f"""
        WITH {_person_groups_cte(education_tbl)},
        single_group AS (
            SELECT linkedin_id, sole_group AS grp
            FROM person_groups
            WHERE n_groups = 1 AND sole_group IN ({headline_list})
        ),
        bachelor_cip AS (
            SELECT e.linkedin_id, MIN(e.cip_code) AS bachelor_cip
            FROM (
                SELECT linkedin_id, cip_code, cip2_pooled, nha_level_pooled
                FROM {education_tbl}
                WHERE degree_level_pooled = 4 AND NOT is_duplicate
            ) e
            JOIN single_group s ON s.linkedin_id = e.linkedin_id
            GROUP BY e.linkedin_id
        )
        SELECT s.linkedin_id, s.grp AS "group", ep.bachelor_end_year, b.bachelor_cip
        FROM single_group s
        JOIN bachelor_cip b USING (linkedin_id)
        JOIN {education_person_tbl} ep USING (linkedin_id)
        WHERE ep.bachelor_end_year BETWEEN {C.COHORT_YEAR_MIN} AND {C.COHORT_YEAR_MAX}
    """)


def excluded_multi_group_count(
    con: duckdb.DuckDBPyConnection,
    education_tbl: str = "education",
    education_person_tbl: str = "education_person",
) -> int:
    """# distinct persons, within the cohort year window, whose bachelor rows
    match more than one of the 4 headline + 3 sanity groups."""
    row = con.sql(f"""
        WITH {_person_groups_cte(education_tbl)}
        SELECT count(*) AS n
        FROM person_groups pg
        JOIN {education_person_tbl} ep USING (linkedin_id)
        WHERE pg.n_groups > 1
          AND ep.bachelor_end_year BETWEEN {C.COHORT_YEAR_MIN} AND {C.COHORT_YEAR_MAX}
    """).fetchone()
    return int(row[0])


def _joined_roles_sql(persons_tbl: str, career_steps_tbl: str) -> str:
    """Roles in each cohort person's 10-year window with a real description,
    NOT necessarily unique on (linkedin_id, experience_idx, position_idx)."""
    return f"""
        SELECT cs.linkedin_id, p."group", cs.experience_idx, cs.position_idx,
               cs.start_year, cs.title_raw, cs.occupation_code_pooled,
               COALESCE(cs.title_raw, '') || '. ' || cs.description AS role_text
        FROM {career_steps_tbl} cs
        JOIN {persons_tbl} p USING (linkedin_id)
        WHERE NOT cs.is_duplicate
          AND cs.start_year BETWEEN p.bachelor_end_year
                                 AND p.bachelor_end_year + {C.ROLE_WINDOW_YEARS}
          AND length(trim(cs.description)) >= {C.MIN_DESCRIPTION_LEN}
    """


def roles_relation(
    con: duckdb.DuckDBPyConnection,
    persons_tbl: str,
    career_steps_tbl: str = "career_steps",
) -> duckdb.DuckDBPyRelation:
    """Role table deduped to be unique on (linkedin_id, experience_idx,
    position_idx): the role key used by later tasks. career_steps' is_duplicate
    flag does not guarantee key uniqueness on its own, so this breaks ties
    deterministically (by start_year, title_raw, role_text) and keeps one row
    per key."""
    sql = _joined_roles_sql(persons_tbl, career_steps_tbl)
    return con.sql(f"""
        SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (
                PARTITION BY linkedin_id, experience_idx, position_idx
                ORDER BY start_year, title_raw, role_text
            ) AS rn
            FROM ({sql})
        )
        WHERE rn = 1
    """)


def run() -> dict:
    con = C.connect()
    con.sql(f"CREATE VIEW education AS SELECT * FROM read_parquet('{C.EDUCATION}')")
    con.sql(f"CREATE VIEW education_person AS SELECT * FROM read_parquet('{C.EDUCATION_PERSON}')")
    con.sql(f"CREATE VIEW career_steps AS SELECT * FROM read_parquet('{C.CAREER_STEPS}')")

    with C.Timer("group assignment"):
        persons_rel = group_assignment_relation(con)
        con.sql("CREATE TEMP TABLE persons AS SELECT * FROM persons_rel")
        n_excluded_multi = excluded_multi_group_count(con)

    with C.Timer("roles"):
        n_roles_before_dedupe = con.sql(
            f"SELECT count(*) FROM ({_joined_roles_sql('persons', 'career_steps')})"
        ).fetchone()[0]
        roles_rel = roles_relation(con, "persons", "career_steps")
        con.sql("CREATE TEMP TABLE roles AS SELECT * FROM roles_rel")
        n_roles_after_dedupe = con.sql("SELECT count(*) FROM roles").fetchone()[0]

    C.RESULTS.mkdir(parents=True, exist_ok=True)
    con.sql("SELECT * FROM persons ORDER BY \"group\", linkedin_id") \
        .write_parquet(str(C.RESULTS / "persons.parquet"))
    con.sql("SELECT * FROM roles ORDER BY \"group\", linkedin_id, experience_idx, position_idx") \
        .write_parquet(str(C.RESULTS / "roles.parquet"))

    persons_by_group = dict(con.sql(
        'SELECT "group", count(*) FROM persons GROUP BY 1 ORDER BY 1'
    ).fetchall())
    roles_by_group = dict(con.sql(
        'SELECT "group", count(*) FROM roles GROUP BY 1 ORDER BY 1'
    ).fetchall())
    n_persons_total = sum(persons_by_group.values())
    n_roles_total = sum(roles_by_group.values())

    for g in C.HEADLINE_GROUPS:
        persons_by_group.setdefault(g, 0)
        roles_by_group.setdefault(g, 0)

    manifest = {
        "cohort_year_min": C.COHORT_YEAR_MIN,
        "cohort_year_max": C.COHORT_YEAR_MAX,
        "role_window_years": C.ROLE_WINDOW_YEARS,
        "min_description_len": C.MIN_DESCRIPTION_LEN,
        "group_labels": C.GROUP_LABELS,
        "persons_by_group": persons_by_group,
        "roles_by_group": roles_by_group,
        "n_persons_total": n_persons_total,
        "n_roles_total": n_roles_total,
        "excluded_multi_group_persons": n_excluded_multi,
        "roles_duplicate_role_keys_removed": n_roles_before_dedupe - n_roles_after_dedupe,
        "role_key": ["linkedin_id", "experience_idx", "position_idx"],
    }
    C.write_json(manifest, C.RESULTS / "_cohort_manifest.json")
    print(f"persons_by_group={persons_by_group}", flush=True)
    print(f"roles_by_group={roles_by_group}", flush=True)
    print(f"excluded_multi_group_persons={n_excluded_multi}", flush=True)
    print(f"roles_duplicate_role_keys_removed={n_roles_before_dedupe - n_roles_after_dedupe}", flush=True)
    return manifest


if __name__ == "__main__":
    run()
