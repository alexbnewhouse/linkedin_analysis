"""Attach the primary institution's IPEDS metadata (control, Carnegie class, level,
region, metro) to `education_person.parquet`, so every downstream consumer
(cohorts, archetypes, portal) can moderate outcomes by institution TYPE with zero
extra joins. Propose-only additive columns; deterministic backbone untouched.

    uv run python -m edu_clean.apply_institution_meta            # dry-run: coverage
    uv run python -m edu_clean.apply_institution_meta --execute  # rewrite the rollup

Run after `reference.build_ipeds_crosswalk --execute` and
`edu_clean.rebuild_education_person`. Idempotent (drops any prior inst_* columns
before re-adding). The join is on `education_person.school_slug` (the person's
primary institution, chosen by the rollup) -> school_ipeds -> institution_meta.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
EP = ROOT / "normalized" / "education_person.parquet"
XWALK = ROOT / "normalized" / "mappings" / "school_ipeds.parquet"
META = ROOT / "reference" / "institution_meta.parquet"
MANIFEST = ROOT / "normalized" / "_institution_meta_manifest.json"

ADDED = ("inst_unitid", "inst_control_label", "inst_carnegie_label",
         "inst_iclevel_label", "inst_state", "inst_region", "inst_cbsa_metro")


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def _base_cols(con) -> list[str]:
    cols = [r[0] for r in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{_q(EP)}')").fetchall()]
    return [c for c in cols if c not in ADDED]


def run(execute: bool) -> dict:
    for p in (XWALK, META):
        if not p.exists():
            raise SystemExit(f"{p} missing -- run reference.build_ipeds_crosswalk --execute")
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")

    keep = ", ".join(f"ep.{c}" for c in _base_cols(con))
    con.execute(f"""
      CREATE OR REPLACE TEMP VIEW ep_aug AS
      SELECT {keep},
             m.unitid          AS inst_unitid,
             m.control_label   AS inst_control_label,
             m.carnegie_label  AS inst_carnegie_label,
             m.iclevel_label   AS inst_iclevel_label,
             m.state           AS inst_state,
             m.region          AS inst_region,
             m.cbsa_metro      AS inst_cbsa_metro
      FROM read_parquet('{_q(EP)}') ep
      LEFT JOIN read_parquet('{_q(XWALK)}') x ON x.school_slug = ep.school_slug
      LEFT JOIN read_parquet('{_q(META)}') m  ON m.unitid = x.unitid
    """)

    n_src = con.execute(f"SELECT count(*) FROM read_parquet('{_q(EP)}')").fetchone()[0]
    n_new = con.execute("SELECT count(*) FROM ep_aug").fetchone()[0]
    assert n_src == n_new, f"row count changed {n_src} -> {n_new}"

    cov = con.execute(
        "SELECT round(100.0*avg((inst_unitid IS NOT NULL)::INT),1) FROM ep_aug").fetchone()[0]
    hum_cov = con.execute(
        "SELECT round(100.0*avg((inst_unitid IS NOT NULL)::INT),1) FROM ep_aug "
        "WHERE hum_l1_any").fetchone()[0]
    control_mix = dict(con.execute(
        "SELECT inst_control_label, count(*) FROM ep_aug WHERE hum_l1_any AND "
        "inst_unitid IS NOT NULL GROUP BY 1 ORDER BY 2 DESC").fetchall())
    carnegie_mix = dict(con.execute(
        "SELECT inst_carnegie_label, count(*) FROM ep_aug WHERE hum_l1_any AND "
        "inst_unitid IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8").fetchall())

    report = {
        "generated": date.today().isoformat(), "rows": n_new,
        "institution_coverage_pct_all": cov,
        "institution_coverage_pct_hum_l1": hum_cov,
        "hum_l1_control_mix": {k: int(v) for k, v in control_mix.items()},
        "hum_l1_top_carnegie": {k: int(v) for k, v in carnegie_mix.items()},
        "executed": execute,
    }
    if execute:
        tmp = EP.with_suffix(".parquet.tmp")
        con.execute(f"COPY ep_aug TO '{_q(tmp)}' (FORMAT parquet, COMPRESSION zstd)")
        EP.unlink()
        tmp.replace(EP)
        MANIFEST.write_text(json.dumps(report, indent=2) + "\n")
    con.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    r = run(ap.parse_args().execute)
    print(f"rows: {r['rows']:,}  institution coverage: {r['institution_coverage_pct_all']}% "
          f"(all) / {r['institution_coverage_pct_hum_l1']}% (L1 humanities)")
    print(f"  L1 control mix: {r['hum_l1_control_mix']}")
    print(f"  L1 top Carnegie: {r['hum_l1_top_carnegie']}")
    if not r["executed"]:
        print("(dry-run -- pass --execute to rewrite education_person.parquet)")


if __name__ == "__main__":
    main()
