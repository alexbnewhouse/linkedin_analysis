"""Throwaway: face-validity spot check the FINDINGS admits was never run.

Top roles by humanities person-year support inside the problem buckets
(OTHER, Managers, Admin, Analysts), plus how much of OTHER is an unmatched
role vs a genuinely-assigned residual.
"""
import duckdb

con = duckdb.connect()
con.execute("PRAGMA threads=8")
R = "archetypes/results"

con.execute(f"""
  CREATE TEMP TABLE hum AS
  SELECT DISTINCT linkedin_id FROM read_parquet('{R}/person_year_archetype.parquet')
""")
con.execute(f"""
  CREATE TEMP TABLE py AS
  SELECT p.role_canonical, count(*) AS n
  FROM read_parquet('cohorts/panel.parquet') p JOIN hum USING (linkedin_id)
  WHERE p.valid_cohort GROUP BY 1
""")
con.execute(f"""
  CREATE TEMP TABLE ra AS
  SELECT role_canonical, archetype_id, archetype_label, assign_method
  FROM read_parquet('{R}/role_archetype.parquet')
""")

print("=== OTHER decomposition: unmatched role vs assigned-residual ===")
print(con.execute("""
  SELECT CASE WHEN py.role_canonical IS NULL THEN 'panel role NULL'
              WHEN ra.role_canonical IS NULL THEN 'role not in crosswalk'
              ELSE 'assigned OTHER: ' || ra.assign_method END AS bucket,
         sum(py.n) AS person_years
  FROM py LEFT JOIN ra USING (role_canonical)
  WHERE coalesce(ra.archetype_id, 0) = 0
  GROUP BY 1 ORDER BY person_years DESC LIMIT 10
""").fetchall())

for aid, name in [(0, "OTHER"), (6, "Managers"), (10, "Admin"), (7, "Analysts"), (11, "Legal/Policy/Research")]:
    print(f"\n=== top 20 roles in archetype {aid} ({name}) by humanities person-years ===")
    rows = con.execute(f"""
      SELECT py.role_canonical, py.n, ra.assign_method
      FROM py JOIN ra USING (role_canonical)
      WHERE ra.archetype_id = {aid}
      ORDER BY py.n DESC LIMIT 20
    """).fetchall()
    for r in rows:
        print(f"   {r[1]:>8,}  {r[0][:52]:<52} [{r[2]}]")
