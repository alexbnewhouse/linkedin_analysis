"""Build reference/soc_status.parquet — a cross-occupation status anchor (Layer B).

    uv run python reference/build_soc_status.py

Joins O*NET Job Zones (per O*NET-SOC) with the Job Zone Reference SVP ranges and
collapses to the 6-digit SOC family our `occupation_code` uses. Job Zone (1-5) is
a preparation/experience ladder keyed directly on SOC — no crosswalk — so it lets
the seniority model compare *across occupations* (what Layers A/C cannot do alone).

Source files (downloaded from onetcenter.org/database, O*NET-SOC 29.1):
  reference/Job_Zones.txt           O*NET-SOC Code, Job Zone, Date, Domain Source
  reference/Job_Zone_Reference.txt  Job Zone, Name, ..., SVP Range
Output: reference/soc_status.parquet (soc_code, job_zone, svp_low, svp_high,
job_zone_norm in [0,1]). Coverage inherits O*NET's ~6-digit SOC universe.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

REF = Path(__file__).resolve().parent
# SVP range per Job Zone (1-9 SVP scale), parsed from Job_Zone_Reference.txt.
SVP = {1: (1.0, 4.0), 2: (4.0, 6.0), 3: (6.0, 7.0), 4: (7.0, 8.0), 5: (8.0, 9.0)}


def main() -> None:
    con = duckdb.connect()
    svp_values = ", ".join(f"({z}, {lo}, {hi})" for z, (lo, hi) in SVP.items())
    out = REF / "soc_status.parquet"
    con.sql(f"""
      COPY (
        WITH jz AS (
          SELECT regexp_extract(column0, '^(\\d{{2}}-\\d{{4}})', 1) AS soc_code,
                 CAST(column1 AS INT) AS job_zone,
                 (column0 LIKE '%.00') AS is_base
          FROM read_csv('{REF / "Job_Zones.txt"}', delim='\t', header=true,
                        columns={{'column0':'VARCHAR','column1':'VARCHAR',
                                  'column2':'VARCHAR','column3':'VARCHAR'}})
        ),
        -- prefer the .00 base occupation's zone; else the modal zone in the family
        fam AS (
          SELECT soc_code,
                 coalesce(arg_max(job_zone, is_base::INT), mode(job_zone)) AS job_zone
          FROM jz GROUP BY soc_code
        ),
        svp(job_zone, svp_low, svp_high) AS (VALUES {svp_values})
        SELECT f.soc_code, f.job_zone, s.svp_low, s.svp_high,
               (f.job_zone - 1) / 4.0 AS job_zone_norm
        FROM fam f JOIN svp s USING (job_zone)
        ORDER BY f.soc_code
      ) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
    """)
    n, zones = con.sql(f"SELECT count(*), count(DISTINCT job_zone) "
                       f"FROM read_parquet('{out}')").fetchone()
    print(f"wrote {out}: {n} SOC families, {zones} job zones")
    for r in con.sql(f"SELECT job_zone, count(*) FROM read_parquet('{out}') "
                     f"GROUP BY 1 ORDER BY 1").fetchall():
        print(f"  zone {r[0]}: {r[1]} occupations")
    con.close()


if __name__ == "__main__":
    main()
