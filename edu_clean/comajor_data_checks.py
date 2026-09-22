"""Data-level invariants of the co-major columns on the built tables.

    uv run python -m edu_clean.comajor_data_checks      (make test-data)
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from edu_clean.apply_comajors import MANIFEST

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
EDU_PERSON = ROOT / "normalized" / "education_person.parquet"
MAPPING = ROOT / "normalized" / "mappings" / "edu_field_components.parquet"


def ok(name: str) -> None:
    print(f"  ok: {name}")


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    edu = f"read_parquet('{EDUCATION}')"
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    dup = q(f"SELECT count(*) - count(DISTINCT value) FROM read_parquet('{MAPPING}')")
    assert dup == 0, f"mapping has {dup} duplicate values (would fan out)"
    ok("mapping unique on value")
    assert q(f"SELECT count(*) FROM {edu} WHERE cip_secondary IS NOT NULL AND cip2_secondary = cip2_pooled") == 0
    ok("secondary family never equals the pooled family")
    assert q(f"SELECT count(*) FROM {edu} WHERE comajor_source IS DISTINCT FROM 'split' "
             f"AND (cip_secondary IS NOT NULL OR minor_cip IS NOT NULL OR nha_level_secondary <> 0 OR nha_level_minor <> 0)") == 0
    ok("secondary/minor columns populated only on comajor_source = 'split'")
    assert q(f"SELECT count(*) FROM {edu} WHERE comajor_source = 'split' AND cip2_pooled IS NULL") == 0
    ok("'split' rows always have a pooled family (else 'no_primary')")
    assert q(f"SELECT count(*) FROM {edu} WHERE comajor_source IS NOT NULL AND field_components_n < 2") == 0
    ok("every split/conflict/no_primary row has >= 2 resolved components")
    if MANIFEST.exists():
        m = json.loads(MANIFEST.read_text())
        want = {d["source"]: d["rows"] for d in m["by_source"]}
        got = dict(con.execute(f"SELECT comajor_source, count(*) FROM {edu} GROUP BY 1").fetchall())
        assert want == got, f"manifest {want} != table {got}"
        ok("comajor_source distribution matches the manifest")
    flagged = q(f"SELECT count(*) FROM read_parquet('{EDU_PERSON}') WHERE double_major_any")
    persons = q(f"SELECT count(DISTINCT linkedin_id) FROM {edu} WHERE NOT is_duplicate AND comajor_source = 'split' "
                f"AND cip2_secondary IS NOT NULL AND coalesce(degree_level_pooled, degree_level) = 4")
    assert flagged == persons, f"double_major_any {flagged} != {persons}"
    ok(f"education_person.double_major_any matches ({flagged:,} persons)")
    print("co-major data checks passed")


if __name__ == "__main__":
    main()
