"""Land the calibrated degree-LEVEL jury into education.parquet, project-wide,
WITHOUT mutating the deterministic backbone. Adds two columns:

    degree_level_pooled   coalesce(degree_level, jury level)  -- jury fills only
                          where degree_level IS NULL and the (degree,field) key
                          matches an accepted jury key
    degree_level_source   'det' | 'jury' | NULL

    uv run python -m edu_clean.apply_degree_level_pooled            # dry-run
    uv run python -m edu_clean.apply_degree_level_pooled --execute  # rewrite parquet

Run after `edu_clean.run_dlevel_jury merge`. Idempotent (rebuilds from the
deterministic columns). Preserves `degree_level` byte-for-byte (asserted).
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
JURY = ROOT / "normalized" / "mappings" / "degree_level_jury.parquet"
MANIFEST = ROOT / "normalized" / "_dlevel_pooled_manifest.json"
ADDED = ("degree_level_pooled", "degree_level_source")
KEY = "lower(trim(coalesce(e.degree_raw,''))) || '||' || lower(trim(coalesce(e.field_raw,'')))"
FP = "bit_xor(hash(linkedin_id, idx, degree_level))"


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def run(execute: bool) -> dict:
    if not JURY.exists():
        raise SystemExit(f"{JURY} missing -- run edu_clean.run_dlevel_jury merge first")
    con = duckdb.connect(); con.execute("PRAGMA threads=8")
    cols = [r[0] for r in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{_q(EDUCATION)}')").fetchall()]
    keep = ", ".join(f"e.{c}" for c in cols if c not in ADDED)
    con.execute(f"""
      CREATE OR REPLACE TEMP VIEW ep AS
      SELECT {keep},
             coalesce(e.degree_level, j.degree_level_jury) AS degree_level_pooled,
             CASE WHEN e.degree_level IS NOT NULL THEN 'det'
                  WHEN j.degree_level_jury IS NOT NULL THEN 'jury' END AS degree_level_source
      FROM read_parquet('{_q(EDUCATION)}') e
      LEFT JOIN read_parquet('{_q(JURY)}') j
        ON e.degree_level IS NULL AND j.key = {KEY}
    """)
    # small key table for cheap validation
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE vk AS
      SELECT e.linkedin_id, e.idx, e.degree_level,
             coalesce(e.degree_level, j.degree_level_jury) AS degree_level_pooled,
             CASE WHEN e.degree_level IS NOT NULL THEN 'det'
                  WHEN j.degree_level_jury IS NOT NULL THEN 'jury' END AS degree_level_source
      FROM read_parquet('{_q(EDUCATION)}') e
      LEFT JOIN read_parquet('{_q(JURY)}') j
        ON e.degree_level IS NULL AND j.key = {KEY}
    """)
    src = f"read_parquet('{_q(EDUCATION)}')"
    n_src = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    n_new = con.execute("SELECT count(*) FROM vk").fetchone()[0]
    assert n_src == n_new, f"row count changed {n_src} -> {n_new}"
    assert con.execute(f"SELECT {FP} FROM {src}").fetchone()[0] == \
           con.execute(f"SELECT {FP} FROM vk").fetchone()[0], "degree_level backbone changed!"
    bad = con.execute("SELECT count(*) FROM vk WHERE degree_level IS NOT NULL "
                      "AND degree_level_pooled IS DISTINCT FROM degree_level").fetchone()[0]
    assert bad == 0, f"{bad} rows overwrote a deterministic degree_level"
    dupguard = con.execute(f"SELECT count(*)-count(DISTINCT key) FROM read_parquet('{_q(JURY)}')").fetchone()[0]
    assert dupguard == 0, "jury key not unique -- would fan out"

    def cov(w):
        return con.execute(f"SELECT round(100.0*avg(({w})::INT),2) FROM vk").fetchone()[0]
    jury_rows = con.execute("SELECT count(*) FROM vk WHERE degree_level_source='jury'").fetchone()[0]
    report = {
        "generated": date.today().isoformat(), "rows": n_new,
        "degree_level_coverage_pct": {"deterministic": cov("degree_level IS NOT NULL"),
                                      "pooled": cov("degree_level_pooled IS NOT NULL")},
        "jury_filled_rows": jury_rows,
        "pooled_level_dist": dict(con.execute(
            "SELECT degree_level_pooled, count(*) FROM vk WHERE degree_level_source='jury' "
            "GROUP BY 1 ORDER BY 1").fetchall()),
        "executed": execute,
    }
    if execute:
        tmp = EDUCATION.with_suffix(".parquet.tmp")
        con.execute(f"COPY ep TO '{_q(tmp)}' (FORMAT parquet, COMPRESSION zstd)")
        EDUCATION.unlink(); tmp.replace(EDUCATION)
        MANIFEST.write_text(json.dumps(report, indent=2) + "\n")
    con.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--execute", action="store_true")
    r = run(ap.parse_args().execute)
    print(f"degree_level coverage: {r['degree_level_coverage_pct']['deterministic']}% -> "
          f"{r['degree_level_coverage_pct']['pooled']}% (+{r['jury_filled_rows']:,} jury rows)")
    print(f"  jury-filled level distribution: {r['pooled_level_dist']}")
    if not r["executed"]:
        print("(dry-run)")


if __name__ == "__main__":
    main()
