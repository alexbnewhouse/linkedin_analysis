"""Land the calibrated CIP2 field jury into the canonical education table,
project-wide, WITHOUT mutating the deterministic backbone.

    uv run python -m edu_clean.apply_cip_pooled            # dry-run: report only
    uv run python -m edu_clean.apply_cip_pooled --execute  # rewrite education.parquet

The deterministic columns (`cip_code`, `cip2`, `cip4`, `nha_level`,
`humanities_field_group`, and every other) are preserved **byte-for-byte** (the
`bit_xor(hash(...))` fingerprint used by `run_tier_counts` is asserted unchanged).
Four columns are APPENDED, propose-only:

    cip2_pooled                     coalesce(cip2, jury.cip2)  -- jury fills only
                                    where cip_code IS NULL and the normalized
                                    field string matches an accepted jury string
    cip_source                      'det' | 'jury' | NULL
    nha_level_pooled                nha_level where cip_code present (keeps 6-digit
                                    override precision); else classify_cip(cip2).level
    humanities_field_group_pooled   same coalescing, family-level group for jury rows

Join semantics mirror `portal/build.py:_edu_table` (the tested reference). Idempotent:
re-running detects the columns already exist and (with --execute) rebuilds from the
deterministic columns, so it never double-applies.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from edu_clean import humanities as H

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
JURY = ROOT / "normalized" / "mappings" / "field_cip_jury.parquet"
MANIFEST = ROOT / "normalized" / "_cip_pooled_manifest.json"

# The deterministic columns whose content must not change. We assert a content
# fingerprint over the three that drive every humanities count, matching
# run_tier_counts.fingerprint exactly.
FINGERPRINT_SQL = "bit_xor(hash(linkedin_id, cip_code, nha_level))"

ADDED = ("cip2_pooled", "cip_source", "nha_level_pooled",
         "humanities_field_group_pooled")


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def _family_lookup(con) -> None:
    """Materialize a small cip2 -> (level, group) table from the humanities
    classifier, covering every cip2 family present in the data. Only ~41 rows."""
    families = [r[0] for r in con.execute(
        f"SELECT DISTINCT cip2 FROM read_parquet('{_q(EDUCATION)}') "
        f"WHERE cip2 IS NOT NULL "
        f"UNION SELECT DISTINCT cip2 FROM read_parquet('{_q(JURY)}')").fetchall()]
    rows = []
    for fam in families:
        c = H.classify_cip(fam)
        rows.append((fam, int(c.level), c.field_group))
    con.execute("CREATE OR REPLACE TEMP TABLE fam_lut "
                "(cip2 VARCHAR, level TINYINT, field_group VARCHAR)")
    con.executemany("INSERT INTO fam_lut VALUES (?, ?, ?)", rows)


def _base_relation(con) -> str:
    """The deterministic education relation with any prior pooled columns dropped
    (so re-running rebuilds cleanly rather than colliding on names). A VIEW, not a
    materialized table -- streaming keeps memory bounded on the ~260MB parquet with
    its large free-text columns."""
    cols = [r[0] for r in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{_q(EDUCATION)}')").fetchall()]
    keep = [c for c in cols if c not in ADDED]
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW edu_base AS "
        f"SELECT {', '.join(keep)} FROM read_parquet('{_q(EDUCATION)}')")
    return "edu_base"


def _build_pooled(con) -> None:
    if not JURY.exists():
        raise SystemExit(f"{JURY} not built -- run edu_clean.run_cip_jury merge first")
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE field_jury AS
      SELECT field_norm, cip2 AS jury_cip2 FROM read_parquet('{_q(JURY)}')
    """)
    dup = con.execute(
        "SELECT count(*) - count(DISTINCT field_norm) FROM field_jury").fetchone()[0]
    if dup:
        raise SystemExit(f"field_cip_jury.parquet has {dup} duplicate field_norm rows")

    base = _base_relation(con)
    _family_lookup(con)

    # Two-stage so BOTH joins are pure equijoins (hash joins). Folding the
    # `cip_code IS NULL` gate into the join condition (as an earlier version did)
    # made DuckDB pick a nested-loop join -- 3.58M x 18.7k, pathological. Instead:
    # join the jury on the equality alone; the gate lives in coalesce/CASE, which
    # is correct because `cip2 IS NULL <=> cip_code IS NULL` on this table (0
    # exceptions, asserted upstream). fam_lut then joins on the computed
    # cip2_pooled, also a clean equijoin.
    def _sql(select_cols: str) -> str:
        return f"""
          WITH p AS (
            SELECT {select_cols},
                   coalesce(e.cip2, fj.jury_cip2)                     AS cip2_pooled,
                   CASE WHEN e.cip2 IS NOT NULL       THEN 'det'
                        WHEN fj.jury_cip2 IS NOT NULL THEN 'jury' END AS cip_source
            FROM {base} e
            LEFT JOIN field_jury fj ON fj.field_norm = lower(trim(e.field_raw))
          )
          SELECT p.*,
                 CASE WHEN p.cip_code IS NOT NULL THEN p.nha_level
                      ELSE lut.level END                             AS nha_level_pooled,
                 CASE WHEN p.cip_code IS NOT NULL THEN p.humanities_field_group
                      ELSE lut.field_group END                       AS humanities_field_group_pooled
          FROM p LEFT JOIN fam_lut lut ON lut.cip2 = p.cip2_pooled"""

    # Full-width view (all original columns + the 4 pooled): streamed once by COPY.
    con.execute(f"CREATE OR REPLACE TEMP VIEW edu_pooled AS {_sql('e.*')}")
    # Small materialized key table: everything validation needs, none of the heavy
    # free-text columns -- so the validation passes are cheap.
    con.execute(f"CREATE OR REPLACE TEMP TABLE edu_key AS "
                f"{_sql('e.linkedin_id, e.cip_code, e.cip2, e.nha_level, e.humanities_field_group')}")


def _validate(con) -> dict:
    """Hard invariants; raise on any violation before we touch the file. All
    checks run over the small `edu_key` table (cheap); the deterministic
    fingerprint is compared against a single pass of the source parquet."""
    src = f"read_parquet('{_q(EDUCATION)}')"
    n_src = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    n_new = con.execute("SELECT count(*) FROM edu_key").fetchone()[0]
    assert n_src == n_new, f"row count changed {n_src} -> {n_new}"

    fp_src = con.execute(f"SELECT {FINGERPRINT_SQL} FROM {src}").fetchone()[0]
    fp_new = con.execute(f"SELECT {FINGERPRINT_SQL} FROM edu_key").fetchone()[0]
    assert fp_src == fp_new, "deterministic fingerprint changed -- backbone mutated!"

    # cip2_pooled is a strict superset of det cip2 (never overwrites a det value)
    bad = con.execute(
        "SELECT count(*) FROM edu_key "
        "WHERE cip2 IS NOT NULL AND cip2_pooled IS DISTINCT FROM cip2").fetchone()[0]
    assert bad == 0, f"{bad} rows where cip2_pooled overwrote a deterministic cip2"

    # cip_source consistency
    bad = con.execute(
        "SELECT count(*) FROM edu_key WHERE "
        "(cip_source='det')  <> (cip2 IS NOT NULL) OR "
        "(cip_source='jury') <> (cip2 IS NULL AND cip2_pooled IS NOT NULL)"
    ).fetchone()[0]
    assert bad == 0, f"{bad} rows with inconsistent cip_source"

    # nha_level_pooled: unchanged where det, family-classified where jury, never
    # populated where cip2_pooled is null
    bad = con.execute(
        "SELECT count(*) FROM edu_key WHERE "
        "cip_code IS NOT NULL AND nha_level_pooled IS DISTINCT FROM nha_level"
    ).fetchone()[0]
    assert bad == 0, f"{bad} det rows where nha_level_pooled != nha_level"
    bad = con.execute(
        "SELECT count(*) FROM edu_key "
        "WHERE cip2_pooled IS NULL AND nha_level_pooled IS NOT NULL").fetchone()[0]
    assert bad == 0, f"{bad} uncoded rows with a non-null nha_level_pooled"

    # coverage report
    def rate(where):
        return con.execute(
            f"SELECT round(100.0*avg(({where})::INT),2) FROM edu_key").fetchone()[0]

    def tier(col, lvls):
        return con.execute(
            f"SELECT count(*), count(DISTINCT linkedin_id) FROM edu_key "
            f"WHERE {col} IN ({', '.join(map(str, lvls))})").fetchone()

    det_cov, pooled_cov = rate("cip_code IS NOT NULL"), rate("cip2_pooled IS NOT NULL")
    jury_rows = con.execute(
        "SELECT count(*) FROM edu_pooled WHERE cip_source='jury'").fetchone()[0]
    l1d, l1p = tier("nha_level", [1]), tier("nha_level_pooled", [1])
    l2d, l2p = tier("nha_level", [1, 2]), tier("nha_level_pooled", [1, 2])
    l3d, l3p = tier("nha_level", [1, 2, 3]), tier("nha_level_pooled", [1, 2, 3])
    # nesting on pooled
    assert l1p[0] <= l2p[0] <= l3p[0] and l1p[1] <= l2p[1] <= l3p[1], "pooled nesting broken"
    return {
        "rows": n_new,
        "cip_coverage_pct": {"deterministic": det_cov, "pooled": pooled_cov},
        "jury_filled_rows": jury_rows,
        "tiers_records": {
            "l1": {"det": l1d[0], "pooled": l1p[0]},
            "l2": {"det": l2d[0], "pooled": l2p[0]},
            "l3": {"det": l3d[0], "pooled": l3p[0]},
        },
        "tiers_persons": {
            "l1": {"det": l1d[1], "pooled": l1p[1]},
            "l2": {"det": l2d[1], "pooled": l2p[1]},
            "l3": {"det": l3d[1], "pooled": l3p[1]},
        },
    }


def run(execute: bool) -> dict:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    _build_pooled(con)
    report = _validate(con)
    report["generated"] = date.today().isoformat()
    report["executed"] = execute

    if execute:
        tmp = EDUCATION.with_suffix(".parquet.tmp")
        con.execute(f"COPY edu_pooled TO '{_q(tmp)}' (FORMAT parquet, COMPRESSION zstd)")
        bak = EDUCATION.with_suffix(".parquet.bak")
        if not bak.exists():
            EDUCATION.replace(bak)  # keep the very first pre-pooled original
        else:
            EDUCATION.unlink()
        tmp.replace(EDUCATION)
        MANIFEST.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    con.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="rewrite normalized/education.parquet (else dry-run)")
    report = run(ap.parse_args().execute)
    r = report
    print(f"rows: {r['rows']:,}   executed: {r['executed']}")
    print(f"CIP coverage: {r['cip_coverage_pct']['deterministic']}% (det) "
          f"-> {r['cip_coverage_pct']['pooled']}% (pooled), "
          f"+{r['jury_filled_rows']:,} jury rows")
    for t in ("l1", "l2", "l3"):
        rec, per = r["tiers_records"][t], r["tiers_persons"][t]
        print(f"  {t}: records {rec['det']:,} -> {rec['pooled']:,}   "
              f"persons {per['det']:,} -> {per['pooled']:,}")
    if not r["executed"]:
        print("(dry-run -- pass --execute to rewrite the parquet)")


if __name__ == "__main__":
    main()
