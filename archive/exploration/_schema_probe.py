"""Throwaway: dump schemas of the substrate tables the archetypes module uses."""
import duckdb

con = duckdb.connect()
TABLES = [
    ("career_steps", "normalized/career_steps.parquet"),
    ("panel", "cohorts/panel.parquet"),
    ("transitions", "paths/transitions.parquet"),
    ("steps", "paths/steps.parquet"),
    ("step_industry", "industry/results/step_industry.parquet"),
    ("education_person", "normalized/education_person.parquet"),
    ("role_soc_jury", "normalized/mappings/role_soc_jury.parquet"),
    ("trajectory_features", "transition_network/trajectory_features.parquet"),
    ("seniority_scores", "paths/seniority_scores.parquet"),
]
for name, path in TABLES:
    try:
        cols = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{path}') LIMIT 1").fetchall()
        n = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
        print(f"=== {name} ({n:,} rows) ===")
        print("  " + ", ".join(f"{c[0]}:{c[1]}" for c in cols))
    except Exception as e:  # noqa: BLE001
        print(f"=== {name} ERR: {e}")
    print()
