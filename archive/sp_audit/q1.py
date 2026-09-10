import duckdb
from archetypes import common as C
con = C.connect()
con.execute(f"CREATE OR REPLACE TEMP TABLE hum_cohort AS {C.humanities_cohort_sql()}")
r = con.execute("SELECT count(*) total, count(DISTINCT linkedin_id) distinct_id FROM hum_cohort").fetchone()
print("hum_cohort total rows, distinct ids:", r)
dup = con.execute("SELECT count(*) FROM (SELECT linkedin_id FROM hum_cohort GROUP BY 1 HAVING count(*)>1)").fetchone()
print("hum_cohort ids appearing >1x:", dup)
r2 = con.execute("SELECT count(*) FILTER (WHERE grad_cohort IS NULL), count(*) FROM hum_cohort").fetchone()
print("grad_cohort null vs total:", r2)
print("GRAD_COHORTS:", C.GRAD_COHORTS)
