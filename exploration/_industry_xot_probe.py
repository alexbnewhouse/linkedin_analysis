"""Throwaway: is industry L1 really ~100% informative, or is XOT a junk bucket?"""
import duckdb

con = duckdb.connect()
con.execute("PRAGMA threads=8")
SI = "industry/results/step_industry.parquet"

print("=== L1 distribution (top 12) ===")
for r in con.execute(f"""
  SELECT l1, count(*) AS n, round(100.0*count(*)/sum(count(*)) OVER (), 2) AS pct
  FROM read_parquet('{SI}') GROUP BY 1 ORDER BY n DESC LIMIT 12
""").fetchall():
    print(f"   {str(r[0]):<8} {r[1]:>12,}  {r[2]:>6}%")

print("\n=== L1 null vs XOT vs informative ===")
print(con.execute(f"""
  SELECT
    count(*) AS total,
    count(*) FILTER (WHERE l1 IS NULL) AS l1_null,
    count(*) FILTER (WHERE l1 = 'XOT') AS l1_xot,
    round(100.0*count(*) FILTER (WHERE l1 IS NOT NULL AND l1 <> 'XOT')/count(*),2) AS pct_informative
  FROM read_parquet('{SI}')
""").fetchall())

print("\n=== is XOT co-extensive with method='unresolved'? ===")
for r in con.execute(f"""
  SELECT method, count(*) AS n,
         count(*) FILTER (WHERE l1 = 'XOT') AS xot
  FROM read_parquet('{SI}') GROUP BY 1 ORDER BY n DESC LIMIT 10
""").fetchall():
    print(f"   {str(r[0]):<24} n={r[1]:>12,}  xot={r[2]:>12,}")
