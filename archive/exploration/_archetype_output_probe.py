"""Throwaway: is the archetypes output actually Sankey-ready?

Probes occupancy / state_flows / job_flows for shape, diagonal dominance,
suppression compliance, and whether the entry->exit story has any signal.
"""
import duckdb

con = duckdb.connect()
con.execute("PRAGMA threads=8")
R = "archetypes/results"

print("=== occupancy: shape ===")
print(con.execute(f"""
  SELECT entry_cohort, count(DISTINCT career_year) AS n_years,
         count(DISTINCT archetype_id) AS n_arch, count(*) AS rows,
         min(n_persons) AS min_n
  FROM read_parquet('{R}/occupancy.parquet')
  GROUP BY 1 ORDER BY 1
""").fetchall())

print("\n=== occupancy: cells below the MIN_SUPPORT=10 bar the plan promises ===")
print(con.execute(f"""
  SELECT count(*) FILTER (WHERE n_persons < 10) AS below_10,
         count(*) FILTER (WHERE n_persons < 5) AS below_5,
         count(*) AS total
  FROM read_parquet('{R}/occupancy.parquet')
""").fetchall())

print("\n=== state_flows: diagonal dominance by cohort ===")
print(con.execute(f"""
  SELECT entry_cohort,
         sum(n_persons) FILTER (WHERE from_archetype = to_archetype) AS stay,
         sum(n_persons) AS total,
         round(100.0 * sum(n_persons) FILTER (WHERE from_archetype = to_archetype)
               / sum(n_persons), 1) AS pct_stay
  FROM read_parquet('{R}/state_flows.parquet')
  GROUP BY 1 ORDER BY 1
""").fetchall())

print("\n=== state_flows: diagonal by career_year (pooled) ===")
print(con.execute(f"""
  SELECT year_from,
         round(100.0 * sum(n_persons) FILTER (WHERE from_archetype = to_archetype)
               / sum(n_persons), 1) AS pct_stay,
         sum(n_persons) AS total
  FROM read_parquet('{R}/state_flows.parquet')
  GROUP BY 1 ORDER BY 1
""").fetchall())

print("\n=== state_flows: top 15 OFF-diagonal ribbons (pooled) ===")
print(con.execute(f"""
  SELECT from_archetype, to_archetype, sum(n_persons) AS n
  FROM read_parquet('{R}/state_flows.parquet')
  WHERE from_archetype <> to_archetype
  GROUP BY 1, 2 ORDER BY n DESC LIMIT 15
""").fetchall())

print("\n=== state_flows: suppression check ===")
print(con.execute(f"""
  SELECT count(*) FILTER (WHERE n_persons < 10) AS below_10, count(*) AS total
  FROM read_parquet('{R}/state_flows.parquet')
""").fetchall())

print("\n=== person_year: in_window share + assignment method mix ===")
print(con.execute(f"""
  SELECT count(*) AS person_years, count(DISTINCT linkedin_id) AS persons,
         round(100.0 * count(*) FILTER (WHERE in_window) / count(*), 1) AS pct_in_window
  FROM read_parquet('{R}/person_year_archetype.parquet')
""").fetchall())

print("\n=== person_year: OTHER share by career_year (is the residual growing?) ===")
print(con.execute(f"""
  SELECT career_year,
         round(100.0 * count(*) FILTER (WHERE archetype_id = 0) / count(*), 1) AS pct_other,
         count(*) AS n
  FROM read_parquet('{R}/person_year_archetype.parquet')
  WHERE in_window GROUP BY 1 ORDER BY 1
""").fetchall())

print("\n=== role_archetype: assign_method mix, person-weighted ===")
print(con.execute(f"""
  SELECT assign_method, count(*) AS n_roles, sum(n_persons) AS person_support,
         round(100.0 * sum(n_persons) / sum(sum(n_persons)) OVER (), 1) AS pct
  FROM read_parquet('{R}/role_archetype.parquet')
  GROUP BY 1 ORDER BY person_support DESC
""").fetchall())

print("\n=== role coverage: how few roles carry the humanities person-years? ===")
print(con.execute(f"""
  WITH py AS (
    SELECT p.role_canonical, count(*) AS n
    FROM read_parquet('cohorts/panel.parquet') p
    JOIN (SELECT DISTINCT linkedin_id FROM read_parquet('{R}/person_year_archetype.parquet')) h
      USING (linkedin_id)
    WHERE p.role_canonical IS NOT NULL
    GROUP BY 1
  ), r AS (
    SELECT role_canonical, n,
           sum(n) OVER (ORDER BY n DESC ROWS UNBOUNDED PRECEDING) AS cum,
           sum(n) OVER () AS tot,
           row_number() OVER (ORDER BY n DESC) AS rk
    FROM py
  )
  SELECT
    min(rk) FILTER (WHERE cum >= 0.50 * tot) AS roles_for_50pct,
    min(rk) FILTER (WHERE cum >= 0.80 * tot) AS roles_for_80pct,
    min(rk) FILTER (WHERE cum >= 0.90 * tot) AS roles_for_90pct,
    min(rk) FILTER (WHERE cum >= 0.95 * tot) AS roles_for_95pct,
    min(rk) FILTER (WHERE cum >= 0.99 * tot) AS roles_for_99pct,
    max(rk) AS n_roles_total
  FROM r
""").fetchall())
