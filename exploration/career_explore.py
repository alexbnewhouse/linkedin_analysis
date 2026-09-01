"""Exploratory profiling of the parsed career/employment data.

Read-only. Prints findings to stdout. Mirrors exploration/explore.py (the
education profiler) but targets the `experience` + `positions` tables and the
three fields we want to clean: organization (`company`), position `title`, and
`description`.

    uv run --group dev python exploration/career_explore.py <section>

Sections: overview, model, orgkey, placeholders, titles, descriptions,
           coverage, integrity, all
"""

import sys

import duckdb

EXP = "read_parquet('parsed/experience/*.parquet')"
POS = "read_parquet('parsed/positions/*.parquet')"
PRO = "read_parquet('parsed/profiles/*.parquet')"

# Unified job-title view. KEY MODEL FACT: for multi-role experiences the
# experience.title is the *company name* (the real titles live in positions);
# for single-role experiences experience.title is the *job title*. So a clean
# job-title column = single-role experience.title UNION ALL positions.title.
JOB_TITLES = f"""(
  SELECT title FROM {EXP} t WHERE title IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM {POS} p
                    WHERE p.linkedin_id=t.linkedin_id
                      AND p.experience_idx=t.experience_idx)
  UNION ALL
  SELECT title FROM {POS} WHERE title IS NOT NULL
)"""

con = duckdb.connect()
NONASCII = "octet_length(encode({c}))>length({c})"  # byte>char => has non-ASCII


def q(sql):
    return con.sql(sql).fetchall()


def show(title, rows, headers=None):
    print(f"\n### {title}")
    if headers:
        print("  " + " | ".join(str(h) for h in headers))
    for r in rows:
        print("  " + " | ".join("" if v is None else str(v) for v in r))


def overview():
    for name, T, cols in [
        ("EXPERIENCE", EXP, ["company", "company_id", "title", "subtitle",
                             "description", "location"]),
        ("POSITIONS", POS, ["title", "subtitle", "meta", "description", "location"]),
    ]:
        n = q(f"SELECT count(*) FROM {T}")[0][0]
        print(f"\n===== {name}: {n:,} rows =====")
        for c in cols:
            nulls, empty, dist, distn = q(f"""
              SELECT count(*) FILTER (WHERE {c} IS NULL),
                     count(*) FILTER (WHERE {c}=''),
                     count(DISTINCT {c}),
                     count(DISTINCT lower(trim({c})))
              FROM {T}""")[0]
            print(f"  {c:13s} null={nulls:>9,} ({100*nulls/n:4.1f}%) "
                  f"distinct={dist:>9,} norm={distn:>9,} "
                  f"(case/space collapse {dist-distn:,})")


def model():
    """Confirm the single-role vs multi-role title model."""
    tot = q(f"SELECT count(*) FROM {EXP}")[0][0]
    with_pos = q(f"SELECT count(*) FROM "
                 f"(SELECT DISTINCT linkedin_id, experience_idx FROM {POS})")[0][0]
    print(f"experience rows: {tot:,}")
    print(f"experiences with position children (multi-role): {with_pos:,}")
    r = q(f"""
      WITH multi AS (SELECT e.* FROM {EXP} e
        WHERE EXISTS (SELECT 1 FROM {POS} p
          WHERE p.linkedin_id=e.linkedin_id AND p.experience_idx=e.experience_idx))
      SELECT count(*), count(*) FILTER (WHERE lower(trim(title))=lower(trim(company)))
      FROM multi""")[0]
    print(f"multi-role rows where title==company: {r[1]:,}/{r[0]:,} "
          f"({100*r[1]/r[0]:.1f}%) -> title is the COMPANY for multi-role")
    show("positions-per-experience", q(f"""
      WITH pc AS (SELECT linkedin_id, experience_idx, count(*) c FROM {POS} GROUP BY 1,2)
      SELECT c, count(*) n FROM pc GROUP BY 1 ORDER BY 1 LIMIT 8"""),
         ["positions", "experiences"])


def orgkey():
    """company_id (and the matching url slug) as a canonical organization key."""
    have = q(f"SELECT count(*) FROM {EXP} WHERE company_id IS NOT NULL")[0][0]
    tot = q(f"SELECT count(*) FROM {EXP}")[0][0]
    print(f"rows with company_id: {have:,} ({100*have/tot:.1f}%)")
    print(f"distinct company_id: {q(f'SELECT count(DISTINCT company_id) FROM {EXP}')[0][0]:,}")
    show("company_id collapsing the most name spellings (synonym capture)",
         q(f"""SELECT company_id, count(DISTINCT company) variants, count(*) c
               FROM {EXP} WHERE company_id IS NOT NULL
               GROUP BY 1 ORDER BY variants DESC LIMIT 8"""),
         ["company_id", "name_variants", "rows"])
    show("spellings merged under company_id='att' (note: absorbs acquired brands)",
         q(f"""SELECT company, count(*) c FROM {EXP}
               WHERE company_id='att' GROUP BY 1 ORDER BY c DESC LIMIT 10"""),
         ["company", "rows"])
    show("one name -> many ids (the placeholder ambiguity problem)",
         q(f"""SELECT company, count(DISTINCT company_id) ids, count(*) c
               FROM {EXP} WHERE company_id IS NOT NULL
               GROUP BY 1 ORDER BY ids DESC LIMIT 6"""),
         ["company", "distinct_ids", "rows"])


def placeholders():
    show("TOP 20 company values (head is dominated by placeholders)",
         q(f"""SELECT company, count(*) c FROM {EXP}
               WHERE company IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT 20"""),
         ["company", "rows"])
    pat = (r'(?i)(self.?employ|freelance|self.?proprietor|\bretired\b|unemploy'
           r'|independent contractor|\bvarious\b|^n/?a$|^none$|stealth'
           r'|^private$|^homemaker$|^student$)')
    show("placeholder / non-organization values (normalized)",
         q(f"""SELECT lower(trim(company)) v, count(*) c FROM {EXP}
               WHERE regexp_matches(company, '{pat}') GROUP BY 1 ORDER BY c DESC LIMIT 25"""),
         ["value", "rows"])


def titles():
    show("TOP 20 job titles (unified single-role + positions)",
         q(f"SELECT title, count(*) c FROM {JOB_TITLES} GROUP BY 1 ORDER BY c DESC LIMIT 20"),
         ["title", "rows"])
    n = q(f"SELECT count(*) FROM {JOB_TITLES}")[0][0]
    sig = q(f"""SELECT
      count(*) FILTER (WHERE {NONASCII.format(c='title')}) non_ascii,
      count(*) FILTER (WHERE title = upper(title) AND title ~ '[A-Z]') all_caps,
      count(*) FILTER (WHERE title LIKE '%|%' OR title LIKE '%•%') multi_sep,
      count(*) FILTER (WHERE length(title) >= 100) at_len_cap,
      count(*) FILTER (WHERE length(title) > 60) long
      FROM {JOB_TITLES}""")[0]
    print(f"\ntitle signals (n={n:,}): " + "  ".join(
        f"{k}={v:,}({100*v/n:.1f}%)" for k, v in
        zip(["non_ascii", "all_caps", "multi_sep", "len==100(trunc)", "len>60"], sig)))
    show("seniority/abbrev family: 'software engineer' (same-vs-distinct tension)",
         q(f"""SELECT title, count(*) c FROM {JOB_TITLES}
               WHERE lower(title) LIKE '%software engineer%'
               GROUP BY 1 ORDER BY c DESC LIMIT 12"""), ["title", "rows"])
    show("non-ASCII titles (multilingual data)",
         q(f"""SELECT title, count(*) c FROM {JOB_TITLES}
               WHERE {NONASCII.format(c='title')} GROUP BY 1 ORDER BY c DESC LIMIT 10"""),
         ["title", "rows"])


def descriptions():
    nd = q(f"SELECT count(*) FROM {EXP} WHERE description IS NOT NULL")[0][0]
    tot = q(f"SELECT count(*) FROM {EXP}")[0][0]
    print(f"experience.description present: {nd:,}/{tot:,} ({100*nd/tot:.1f}%)")
    sig = q(f"""SELECT
      count(*) FILTER (WHERE description ~ '<[a-zA-Z/]') has_html,
      count(*) FILTER (WHERE {NONASCII.format(c='description')}) non_ascii,
      count(*) FILTER (WHERE length(description) > 2000) very_long,
      count(*) FILTER (WHERE description = description_html) eq_html
      FROM {EXP} WHERE description IS NOT NULL""")[0]
    print("description signals: " + "  ".join(
        f"{k}={v:,}({100*v/nd:.1f}%)" for k, v in
        zip(["has_html_tag", "non_ascii", "len>2000", "==description_html"], sig)))
    print("-> description is the plain-text variant; description_html keeps markup.")


def coverage():
    """Head concentration vs long tail -> how far a dictionary/reference reaches."""
    for label, expr, T, where in [
        ("company", "company", EXP, "company IS NOT NULL"),
        ("job-title", "title", JOB_TITLES, "title IS NOT NULL"),
    ]:
        tot = q(f"SELECT count(*) FROM {T} t WHERE {where}")[0][0]
        dist = q(f"SELECT count(DISTINCT {expr}) FROM {T} t WHERE {where}")[0][0]
        print(f"\n{label}: {tot:,} rows, {dist:,} distinct")
        for topn in [100, 1000, 10000, 50000]:
            cov = q(f"""WITH x AS (SELECT {expr} v, count(*) c FROM {T} t
                        WHERE {where} GROUP BY 1 ORDER BY c DESC LIMIT {topn})
                        SELECT sum(c) FROM x""")[0][0] or 0
            print(f"  top {topn:>6}: {100*cov/tot:5.1f}% of rows")
        sing = q(f"""WITH x AS (SELECT {expr} v, count(*) c FROM {T} t WHERE {where} GROUP BY 1)
                     SELECT count(*) FILTER (WHERE c=1), count(*) FILTER (WHERE c<=3) FROM x""")[0]
        print(f"  singletons: {sing[0]:,} (<=3 times: {sing[1]:,}) <- long tail")


def integrity():
    dang = q(f"""SELECT count(*) FROM {POS} p WHERE NOT EXISTS
      (SELECT 1 FROM {EXP} e WHERE e.linkedin_id=p.linkedin_id
        AND e.experience_idx=p.experience_idx)""")[0][0]
    orph = q(f"SELECT count(*) FROM {EXP} e WHERE linkedin_id NOT IN "
             f"(SELECT linkedin_id FROM {PRO})")[0][0]
    dup = q(f"""WITH d AS (SELECT linkedin_id, company, title, start_date, end_date, count(*) c
      FROM {EXP} GROUP BY 1,2,3,4,5 HAVING count(*)>1) SELECT count(*), sum(c) FROM d""")[0]
    print(f"dangling positions: {dang:,}")
    print(f"experience rows with no profile: {orph:,}")
    print(f"duplicate experience groups: {dup[0]:,} covering {dup[1] or 0:,} rows")
    show("title length near the 100-char cap (source truncation)",
         q(f"""SELECT length, count(*) c FROM
               (SELECT length(title) length FROM {JOB_TITLES}) WHERE length>=98
               GROUP BY 1 ORDER BY 1"""), ["length", "rows"])
    show("date formats (start_date) - semi-structured 'Mon YYYY' / 'YYYY'",
         q(f"""SELECT start_date, count(*) c FROM {EXP} WHERE start_date IS NOT NULL
               GROUP BY 1 ORDER BY c DESC LIMIT 6"""), ["start_date", "rows"])


SECTIONS = {
    "overview": overview, "model": model, "orgkey": orgkey,
    "placeholders": placeholders, "titles": titles, "descriptions": descriptions,
    "coverage": coverage, "integrity": integrity,
}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "overview"
    if name == "all":
        for fn in SECTIONS.values():
            print("\n" + "=" * 70)
            fn()
    else:
        SECTIONS[name]()
