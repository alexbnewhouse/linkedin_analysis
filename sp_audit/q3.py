from archetypes import common as C
con = C.connect()
con.execute(f"CREATE OR REPLACE TEMP TABLE hum_cohort AS {C.humanities_cohort_sql()}")

# panel one row per (id, calendar_year)?
r = con.execute(f"""SELECT count(*) rows, count(*)-count(DISTINCT (linkedin_id, calendar_year)) dup_excess
  FROM read_parquet('{C.PANEL}') WHERE valid_cohort""").fetchone()
print("panel valid_cohort rows, dup_excess over (id,cal_year):", r)

# panel-humanities rows in career_year [1,15]  (reproduce join)
r2 = con.execute(f"""
  SELECT count(*) FROM read_parquet('{C.PANEL}') p
  JOIN hum_cohort h USING (linkedin_id)
  WHERE p.valid_cohort
    AND (p.calendar_year - h.grad_year) BETWEEN {C.MIN_YEAR} AND {C.MAX_YEAR}
    AND h.grad_cohort IS NOT NULL
""").fetchone()
print("expected person_year rows (join reproduction):", r2)

py = C.RESULTS / "person_year_archetype.parquet"
r3 = con.execute(f"SELECT count(*), count(DISTINCT linkedin_id), min(career_year), max(career_year) FROM read_parquet('{py}')").fetchone()
print("person_year parquet rows, distinct id, min/max career_year:", r3)

# dup rows per (id, career_year) in person_year output?
r4 = con.execute(f"SELECT count(*) FROM (SELECT linkedin_id, career_year FROM read_parquet('{py}') GROUP BY 1,2 HAVING count(*)>1)").fetchone()
print("person_year (id,career_year) appearing >1x:", r4)
