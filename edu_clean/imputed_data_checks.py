"""Data-level invariants of the imputed-bachelor tier on the built tables.

    uv run python -m edu_clean.imputed_data_checks      (make test-data)
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from edu_clean import imputed_bachelor as IB
from edu_clean.apply_bachelor_imputed import MANIFEST, _register

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
EDU_PERSON = ROOT / "normalized" / "education_person.parquet"


def ok(name: str) -> None:
    print(f"  ok: {name}")


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    _register(con)
    edu = f"read_parquet('{EDUCATION}')"
    src = IB.SOURCE
    n = con.execute(f"SELECT count(*) FROM {edu} WHERE degree_level_source = '{src}'").fetchone()[0]
    if MANIFEST.exists():
        m = json.loads(MANIFEST.read_text())
        assert m["imputed_rows"] == n, f"manifest says {m['imputed_rows']} imputed rows, table has {n}"
        ok(f"imputed rows match the manifest ({n:,})")
    bad = con.execute(f"""
        SELECT count(*) FROM {edu} WHERE degree_level_source = '{src}' AND NOT (
          degree_level IS NULL AND degree_level_pooled = {IB.LEVEL}
          AND cip2_pooled IS NOT NULL AND cip2_pooled <> '53'
          AND degree_method = 'cip_from_degree'
          AND NOT degree_negative(degree_raw) AND NOT degree_negative(field_raw)
          AND NOT not_completed(description) AND NOT school_excluded(school_raw))
    """).fetchone()[0]
    assert bad == 0, f"{bad} imputed rows violate the row-level predicate"
    ok("every imputed row satisfies the row-level predicate")
    bad = con.execute(f"""
        SELECT count(*) FROM (
          SELECT linkedin_id FROM {edu} GROUP BY 1
          HAVING bool_or(degree_level_source = '{src}')
             AND bool_or(degree_level_source IN ('det','jury') AND degree_level_pooled = 4)
        )""").fetchone()[0]
    assert bad == 0, f"{bad} persons hold both an imputed and a det/jury bachelor's"
    ok("no person holds both an imputed and a det/jury bachelor's")
    flagged = con.execute(f"SELECT count(*) FROM read_parquet('{EDU_PERSON}') WHERE bachelor_imputed_any").fetchone()[0]
    persons = con.execute(f"SELECT count(DISTINCT linkedin_id) FROM {edu} WHERE degree_level_source = '{src}' AND NOT is_duplicate").fetchone()[0]
    assert flagged == persons, f"person flag {flagged} != persons with an imputed row {persons}"
    ok(f"education_person.bachelor_imputed_any matches ({flagged:,} persons)")
    print("imputed-bachelor data checks passed")


if __name__ == "__main__":
    main()
