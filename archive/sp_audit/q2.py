from archetypes import common as C
con = C.connect()
ra = C.RESULTS / "role_archetype.parquet"
r = con.execute(f"SELECT count(*), count(DISTINCT role_canonical) FROM read_parquet('{ra}')").fetchone()
print("role_arch rows, distinct role_canonical:", r)
dup = con.execute(f"SELECT count(*) FROM (SELECT role_canonical FROM read_parquet('{ra}') GROUP BY 1 HAVING count(*)>1)").fetchone()
print("role_canonical >1x:", dup)

# panel schema
cols = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{C.PANEL}')").fetchall()
print("panel cols:", [c[0] for c in cols])
