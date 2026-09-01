"""Targeted follow-ups: population/language, degree variant proof, and the
residual institution-matching problem for rows without a school slug."""

import duckdb

con = duckdb.connect()
EDU = "read_parquet('parsed/education/*.parquet')"
PROF = "read_parquet('parsed/profiles/*.parquet')"


def q(sql):
    return con.sql(sql).fetchall()


def show(title, rows, headers=None):
    print(f"\n### {title}")
    if headers:
        print("  " + " | ".join(str(h) for h in headers))
    for r in rows:
        print("  " + " | ".join("" if v is None else str(v) for v in r))


# 1. Population / language: is this mostly US/English (so CIP applies)?
show(
    "Profile country_code distribution (top 15)",
    q(f"""SELECT country_code, count(*) c FROM {PROF}
           GROUP BY 1 ORDER BY c DESC LIMIT 15"""),
    ["country", "count"],
)

# 2. Degree normalization proof: apostrophe + abbreviation styles of one degree
show(
    "'Bachelor of Science' spelling variants",
    q(f"""SELECT degree, count(*) c FROM {EDU}
           WHERE regexp_replace(lower(degree), '[^a-z]', '', 'g')
                 LIKE '%bachelorofscience%'
           GROUP BY 1 ORDER BY c DESC LIMIT 15"""),
    ["degree", "count"],
)

show(
    "Curly vs straight apostrophe in degree ('Bachelor_s ...')",
    q(
        r"""SELECT
             count(*) FILTER (WHERE degree LIKE '%''%') AS straight_quote,
             count(*) FILTER (WHERE degree LIKE '%’%')  AS curly_quote
           FROM """
        + EDU
        + " WHERE degree IS NOT NULL"
    ),
    ["straight '", "curly ’"],
)

# 3. Residual institution problem: rows WITHOUT a usable school slug.
show(
    "Institution coverage by school slug",
    q(f"""
        WITH s AS (
          SELECT title,
                 regexp_extract(url, 'linkedin\\.com/school/([^/?]+)', 1) AS slug
          FROM {EDU} WHERE title IS NOT NULL
        )
        SELECT
          count(*) AS rows_with_title,
          count(*) FILTER (WHERE slug <> '') AS rows_with_slug,
          count(DISTINCT title) FILTER (WHERE slug = '' OR slug IS NULL) AS distinct_titles_no_slug
        FROM s
     """),
    ["rows_with_title", "rows_with_slug", "distinct_titles_no_slug"],
)

show(
    "Most common titles that have NO slug (residual to resolve by name)",
    q(f"""
        WITH s AS (
          SELECT title,
                 regexp_extract(url, 'linkedin\\.com/school/([^/?]+)', 1) AS slug
          FROM {EDU} WHERE title IS NOT NULL
        )
        SELECT title, count(*) c FROM s
        WHERE slug = '' OR slug IS NULL
        GROUP BY 1 ORDER BY c DESC LIMIT 20
     """),
    ["title", "count"],
)

# Do no-slug titles often ALSO appear elsewhere WITH a slug? (recoverable)
show(
    "No-slug titles that DO match a known slugged title (recoverable share)",
    q(f"""
        WITH s AS (
          SELECT title,
                 regexp_extract(url, 'linkedin\\.com/school/([^/?]+)', 1) AS slug
          FROM {EDU} WHERE title IS NOT NULL
        ),
        slugged AS (SELECT DISTINCT lower(trim(title)) lt FROM s WHERE slug <> ''),
        noslug  AS (SELECT title, count(*) c FROM s
                    WHERE slug = '' OR slug IS NULL GROUP BY 1)
        SELECT
          sum(c) AS total_noslug_rows,
          sum(c) FILTER (WHERE lower(trim(title)) IN (SELECT lt FROM slugged))
            AS recoverable_by_exact_name
        FROM noslug
     """),
    ["total_noslug_rows", "recoverable_by_exact_name"],
)
