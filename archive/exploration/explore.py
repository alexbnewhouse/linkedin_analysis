"""Exploratory profiling of the parsed education data.

Read-only. Prints findings to stdout. Run specific sections via the CLI arg
so we can iterate quickly:

    uv run --group dev python exploration/explore.py <section>

Sections: overview, field, degree, institution, url, crossfield, dupes
"""

import sys

import duckdb

EDU = "read_parquet('parsed/education/*.parquet')"
con = duckdb.connect()


def q(sql):
    return con.sql(sql).fetchall()


def show(title, rows, headers=None):
    print(f"\n### {title}")
    if headers:
        print("  " + " | ".join(str(h) for h in headers))
    for r in rows:
        print("  " + " | ".join("" if v is None else str(v) for v in r))


def overview():
    n = q(f"SELECT count(*) FROM {EDU}")[0][0]
    print(f"Total education rows: {n:,}")
    for col in [
        "title",
        "degree",
        "field",
        "start_year",
        "end_year",
        "description",
        "url",
        "institute_logo_url",
    ]:
        rows = q(f"""
            SELECT
              count(*) FILTER (WHERE {col} IS NULL) AS nulls,
              count(*) FILTER (WHERE {col} = '') AS empty,
              count(*) FILTER (WHERE trim({col}) = '' AND {col} <> '') AS ws_only,
              count(DISTINCT {col}) AS distinct_vals,
              count(DISTINCT lower(trim({col}))) AS distinct_norm
            FROM {EDU}
        """)[0]
        nulls, empty, ws, dist, distn = rows
        print(f"\n{col}:")
        print(
            f"  null={nulls:,} ({100 * nulls / n:.1f}%)  empty={empty:,}  ws_only={ws}"
        )
        print(
            f"  distinct(raw)={dist:,}  distinct(lower+trim)={distn:,} "
            f"-> {dist - distn:,} collapse from case/space alone"
        )


def top_values(col, k=40):
    rows = q(f"""
        SELECT {col}, count(*) c FROM {EDU}
        WHERE {col} IS NOT NULL AND trim({col}) <> ''
        GROUP BY 1 ORDER BY c DESC LIMIT {k}
    """)
    show(f"Top {k} values of `{col}`", rows, ["value", "count"])


def length_stats(col):
    rows = q(f"""
        SELECT
          min(length({col})), max(length({col})),
          quantile_cont(length({col}), 0.5),
          quantile_cont(length({col}), 0.95),
          quantile_cont(length({col}), 0.99)
        FROM {EDU} WHERE {col} IS NOT NULL AND trim({col}) <> ''
    """)
    show(f"`{col}` length: min/max/p50/p95/p99", rows)
    long = q(f"""
        SELECT length({col}), {col} FROM {EDU}
        WHERE {col} IS NOT NULL ORDER BY length({col}) DESC LIMIT 8
    """)
    show(f"Longest `{col}` values", [(r[0], r[1][:160]) for r in long])


def field():
    top_values("field", 50)
    length_stats("field")
    show(
        "`field` containing commas/slashes (multi-value?)",
        q(f"""SELECT count(*) FILTER (WHERE field LIKE '%,%'),
                      count(*) FILTER (WHERE field LIKE '%/%'),
                      count(*) FILTER (WHERE field LIKE '% and %' OR field LIKE '% & %')
               FROM {EDU} WHERE field IS NOT NULL"""),
        ["has_comma", "has_slash", "has_and"],
    )
    show(
        "Sample multi-value `field`",
        q(f"""SELECT field, count(*) c FROM {EDU}
               WHERE field LIKE '%,%' GROUP BY 1 ORDER BY c DESC LIMIT 15"""),
        ["field", "count"],
    )


def degree():
    top_values("degree", 50)
    length_stats("degree")
    print(
        f"\nDistinct degrees: {q(f'SELECT count(DISTINCT degree) FROM {EDU}')[0][0]:,}"
    )


def institution():
    top_values("title", 40)
    length_stats("title")


def url():
    n = q(f"SELECT count(*) FROM {EDU}")[0][0]
    have_url = q(f"SELECT count(*) FROM {EDU} WHERE url IS NOT NULL AND url <> ''")[0][
        0
    ]
    print(f"rows with url: {have_url:,} ({100 * have_url / n:.1f}%)")
    # extract school slug from linkedin school url
    slug_rows = q(f"""
        WITH s AS (
          SELECT regexp_extract(url, 'linkedin\\.com/school/([^/?]+)', 1) AS slug,
                 title
          FROM {EDU} WHERE url IS NOT NULL
        )
        SELECT
          count(*) FILTER (WHERE slug <> '') AS with_slug,
          count(DISTINCT slug) FILTER (WHERE slug <> '') AS distinct_slug
        FROM s
    """)[0]
    print(f"rows with school slug: {slug_rows[0]:,}  distinct slugs: {slug_rows[1]:,}")
    print(
        f"distinct raw titles: {q(f'SELECT count(DISTINCT title) FROM {EDU}')[0][0]:,}"
    )
    # how many distinct titles map to one slug (synonyms captured by slug)?
    show(
        "Slugs with the most distinct title spellings (institution synonyms)",
        q(f"""
           WITH s AS (
             SELECT regexp_extract(url, 'linkedin\\.com/school/([^/?]+)', 1) AS slug,
                    title
             FROM {EDU} WHERE url IS NOT NULL AND title IS NOT NULL
           )
           SELECT slug, count(DISTINCT title) AS title_variants, count(*) c
           FROM s WHERE slug <> '' GROUP BY 1 ORDER BY title_variants DESC LIMIT 15
         """),
        ["slug", "title_variants", "rows"],
    )
    show(
        "Example: all title spellings for one busy slug",
        q(f"""
           WITH s AS (
             SELECT regexp_extract(url, 'linkedin\\.com/school/([^/?]+)', 1) AS slug,
                    title
             FROM {EDU} WHERE url IS NOT NULL AND title IS NOT NULL
           )
           SELECT title, count(*) c FROM s
           WHERE slug = (SELECT slug FROM s WHERE slug<>'' GROUP BY slug
                         ORDER BY count(DISTINCT title) DESC LIMIT 1)
           GROUP BY 1 ORDER BY c DESC LIMIT 20
         """),
        ["title", "count"],
    )


def crossfield():
    # Are degree/field swapped or polluted? Look for degree-like tokens in field
    show(
        "`field` values that look like degrees",
        q(f"""SELECT field, count(*) c FROM {EDU}
               WHERE lower(field) SIMILAR TO '%(bachelor|master|associate|ph\\.?d|b\\.?s|m\\.?s|b\\.?a|m\\.?a)%'
               GROUP BY 1 ORDER BY c DESC LIMIT 15"""),
        ["field", "count"],
    )
    show(
        "`degree` values that look like fields of study (long, no degree word)",
        q(f"""SELECT degree, count(*) c FROM {EDU}
               WHERE length(degree) > 40
                 AND lower(degree) NOT SIMILAR TO '%(bachelor|master|associate|degree|diploma|certificate)%'
               GROUP BY 1 ORDER BY c DESC LIMIT 15"""),
        ["degree", "count"],
    )
    show(
        "rows where field == degree (redundant)",
        q(f"""SELECT count(*) FROM {EDU}
               WHERE lower(trim(field)) = lower(trim(degree))
                 AND field IS NOT NULL"""),
    )


def dupes():
    # Demonstrate near-duplicate clustering need on field of study.
    print("Probing near-duplicate FIELD values around a few seeds...")
    seeds = [
        "computer science",
        "business administration",
        "psychology",
        "english",
        "mechanical engineering",
        "accounting",
    ]
    for seed in seeds:
        rows = q(f"""
            SELECT field, count(*) c FROM {EDU}
            WHERE lower(field) LIKE '%{seed}%'
            GROUP BY 1 ORDER BY c DESC LIMIT 8
        """)
        show(f"variants containing '{seed}'", rows, ["field", "count"])


def coverage():
    """How much of the data is concentrated in the 'head'? Drives how far a
    curated dictionary gets us vs. how much long-tail fuzzy/semantic work
    remains."""
    for col in ["field", "degree", "title"]:
        total = q(f"SELECT count(*) FROM {EDU} WHERE {col} IS NOT NULL")[0][0]
        distinct = q(f"SELECT count(DISTINCT {col}) FROM {EDU}")[0][0]
        print(f"\n{col}: {total:,} non-null rows, {distinct:,} distinct values")
        for topn in [100, 500, 1000, 5000]:
            covered = (
                q(f"""
                WITH t AS (
                  SELECT {col}, count(*) c FROM {EDU}
                  WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT {topn}
                )
                SELECT sum(c) FROM t
            """)[0][0]
                or 0
            )
            print(f"  top {topn:>5} values cover {100 * covered / total:5.1f}% of rows")
        singletons = q(f"""
            WITH t AS (SELECT {col}, count(*) c FROM {EDU}
                       WHERE {col} IS NOT NULL GROUP BY 1)
            SELECT count(*) FILTER (WHERE c = 1), count(*) FILTER (WHERE c <= 3)
            FROM t
        """)[0]
        print(
            f"  distinct values appearing once: {singletons[0]:,} "
            f"(<=3 times: {singletons[1]:,})  <- the long tail"
        )


def quality():
    """Data-quality signals across the three target fields."""
    for col in ["field", "degree", "title"]:
        rows = q(f"""
            SELECT
              count(*) FILTER (WHERE {col} ~ '[^\\x00-\\x7F]') AS non_ascii,
              count(*) FILTER (WHERE {col} = upper({col}) AND {col} ~ '[A-Z]') AS all_caps,
              count(*) FILTER (WHERE {col} ~ '[0-9]') AS has_digit,
              count(*) FILTER (WHERE length(trim({col})) <= 2) AS very_short,
              count(*) FILTER (WHERE {col} <> trim({col})) AS has_pad,
              count(*) FILTER (WHERE {col} ~ '[''\u2019]') AS has_apostrophe,
              count(*) FILTER (WHERE {col} ~ '  +') AS double_space
            FROM {EDU} WHERE {col} IS NOT NULL
        """)[0]
        cols = [
            "non_ascii",
            "all_caps",
            "has_digit",
            "very_short",
            "has_pad",
            "has_apostrophe",
            "double_space",
        ]
        print(f"\n{col}: " + "  ".join(f"{c}={v:,}" for c, v in zip(cols, rows)))
    show(
        "Very short `field` values (<=2 chars)",
        q(f"""SELECT field, count(*) c FROM {EDU}
                WHERE length(trim(field)) <= 2 GROUP BY 1 ORDER BY c DESC LIMIT 15"""),
        ["field", "count"],
    )
    show(
        "Non-ASCII `field` examples",
        q(f"""SELECT field, count(*) c FROM {EDU}
                WHERE field ~ '[^\\x00-\\x7F]' GROUP BY 1 ORDER BY c DESC LIMIT 15"""),
        ["field", "count"],
    )


def logo():
    """Is institute_logo_url a reliable institution key, or polluted by generic
    placeholder logos shared across unrelated schools?"""
    n = q(f"SELECT count(*) FROM {EDU}")[0][0]
    have = q(f"SELECT count(*) FROM {EDU} WHERE institute_logo_url IS NOT NULL")[0][0]
    print(
        f"rows with logo: {have:,} ({100 * have / have * 100 / 100 * have / n:.1f}% ... {100 * have / n:.1f}%)"
    )
    show(
        "Logos shared by the most distinct titles (placeholder detector)",
        q(f"""SELECT institute_logo_url, count(DISTINCT title) titles, count(*) c
                FROM {EDU} WHERE institute_logo_url IS NOT NULL
                GROUP BY 1 ORDER BY titles DESC LIMIT 10"""),
        ["logo (trunc)", "distinct_titles", "rows"],
    )


SECTIONS = {
    "overview": overview,
    "field": field,
    "degree": degree,
    "institution": institution,
    "url": url,
    "crossfield": crossfield,
    "dupes": dupes,
    "coverage": coverage,
    "quality": quality,
    "logo": logo,
}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "overview"
    SECTIONS[name]()
