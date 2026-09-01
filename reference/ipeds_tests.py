"""Integrity checks for the IPEDS institution crosswalk + metadata.

    uv run python -m reference.ipeds_tests

Plain-assert style (cf. edu_clean/tier_tests.py). Verifies the crosswalk is a
clean one-to-one-per-slug join, every matched unitid has metadata, and the
decoded labels are present for matched Title-IV institutions.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
X = f"read_parquet('{ROOT / 'normalized' / 'mappings' / 'school_ipeds.parquet'}')"
M = f"read_parquet('{ROOT / 'reference' / 'institution_meta.parquet'}')"


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def run() -> None:
    con = duckdb.connect()
    dup = con.execute(f"SELECT count(*)-count(DISTINCT school_slug) FROM {X}").fetchone()[0]
    check("crosswalk: one row per school_slug (no fan-out)", dup == 0)

    orphan = con.execute(
        f"SELECT count(*) FROM {X} x LEFT JOIN {M} m USING (unitid) "
        f"WHERE m.unitid IS NULL").fetchone()[0]
    check("every crosswalk unitid exists in institution_meta", orphan == 0)

    meta_dup = con.execute(f"SELECT count(*)-count(DISTINCT unitid) FROM {M}").fetchone()[0]
    check("institution_meta: one row per unitid", meta_dup == 0)

    conf_bad = con.execute(
        f"SELECT count(*) FROM {X} WHERE match_confidence NOT BETWEEN 0 AND 1 "
        f"OR match_method NOT IN ('exact','core','curated_flagship')").fetchone()[0]
    check("crosswalk: methods/confidence in the declared domain", conf_bad == 0)

    # matched 4yr institutions carry decoded control + carnegie labels
    nolabel = con.execute(
        f"SELECT count(*) FROM {X} x JOIN {M} m USING (unitid) "
        f"WHERE m.iclevel = '1' AND (m.control_label IS NULL OR m.carnegie_label IS NULL)"
    ).fetchone()[0]
    check("matched 4yr institutions have control + carnegie labels", nolabel == 0)
    con.close()
    print("\nall IPEDS crosswalk tests passed")


if __name__ == "__main__":
    run()
