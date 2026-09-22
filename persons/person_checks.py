"""Data-level invariants of persons/person.parquet and persons/results/metrics.json.

    uv run python -m persons.person_checks      (make test-data)
"""
from __future__ import annotations

import json

import duckdb

from persons import common as C


def ok(name: str) -> None:
    print(f"  ok: {name}")


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    P = f"read_parquet('{C.PERSON_OUT}')"
    EP = f"read_parquet('{C.EDU_PERSON}')"
    q = lambda sql: con.execute(sql).fetchone()  # noqa: E731
    n, nd = q(f"SELECT count(*), count(DISTINCT linkedin_id) FROM {P}")
    assert n == nd, f"{n} rows, {nd} persons"
    assert n == q(f"SELECT count(*) FROM {EP}")[0], "row count differs from education_person"
    ok(f"one row per person, same universe as education_person ({n:,})")
    assert q(f"SELECT count(*) FROM {P} WHERE has_bachelor AND bachelor_level_source IS NULL")[0] == 0
    ok("every bachelor row carries bachelor_level_source")
    assert q(f"SELECT count(*) FROM {P} p JOIN {EP} e USING (linkedin_id) WHERE p.hum_l1_bachelor <> e.hum_l1_bachelor_pooled_any")[0] == 0
    ok("hum_l1_bachelor is education_person.hum_l1_bachelor_pooled_any (ANY-row rule)")
    assert q(f"SELECT count(*) FROM {P} WHERE hum_l1_bachelor AND NOT hum_l2_bachelor OR hum_l2_bachelor AND NOT hum_l3_bachelor")[0] == 0
    ok("tiers nest L1 => L2 => L3")
    combos = q(f"""SELECT count(*) FILTER (WHERE career_years_entry IS NOT NULL AND career_years_grad IS NULL),
                          count(*) FILTER (WHERE career_years_entry IS NULL AND career_years_grad IS NOT NULL),
                          count(*) FILTER (WHERE career_years_entry IS NOT NULL AND career_years_grad IS NOT NULL) FROM {P}""")
    assert combos[0] > 0 and combos[2] > 0, f"axes look coalesced: {combos}"
    ok(f"the two axes are independent (entry-only {combos[0]:,}, grad-only {combos[1]:,}, both {combos[2]:,})")
    assert q(f"SELECT count(*) FROM {P} WHERE career_years_entry < 0 OR career_years_grad < 0")[0] == 0
    ok("no negative career years (in-progress degrees are NULL on the grad axis)")
    prof = C.ROOT / "cohorts" / "profiles.parquet"
    if prof.exists():
        bad = q(f"""SELECT count(*) FROM {P} p JOIN read_parquet('{prof}') c USING (linkedin_id)
                    WHERE p.entry_year IS NOT NULL AND c.entry_year IS NOT NULL AND p.entry_year <> c.entry_year""")[0]
        tot = q(f"SELECT count(*) FROM {P} p JOIN read_parquet('{prof}') c USING (linkedin_id) WHERE p.entry_year IS NOT NULL AND c.entry_year IS NOT NULL")[0]
        assert bad <= 0.001 * tot, f"entry_year disagrees with cohorts/profiles on {bad} of {tot}"
        ok(f"entry_year agrees with cohorts/profiles.entry_year ({bad} of {tot:,} differ)")
    S = f"read_parquet('{C.STEPS_OUT}')"
    assert q(f"SELECT count(*) FROM (SELECT linkedin_id, max(seniority_ordinal) >= {C.MANAGER_RANK} AS m FROM {S} GROUP BY 1) s JOIN {P} p USING (linkedin_id) WHERE coalesce(s.m, FALSE) <> p.ever_manager_plus")[0] == 0
    ok("ever_manager_plus == max(seniority_ordinal) >= 6")
    if C.METRICS_OUT.exists():
        m = json.loads(C.METRICS_OUT.read_text())
        assert m["release"].get("git") and m["release"].get("snapshot_date") and m["release"].get("schema_version")
        ok("metrics carry a release stamp (git, snapshot_date, schema_version)")
        assert m["groups"]["all"]["basic"]["n"] == q(f"SELECT count(*) FROM {P} WHERE has_bachelor")[0]
        assert isinstance(m["groups"]["all"]["basic"]["n"], int), "counts must serialize as integers"
        assert m["groups"]["tier:l1"]["basic"]["n"] == q(f"SELECT count(*) FROM {P} WHERE hum_l1_bachelor")[0]
        ok("group n for all / tier:l1 match the person table")
        low = 0
        single = 0

        def walk(node):
            nonlocal low, single
            if isinstance(node, dict):
                if "cells" in node and isinstance(node["cells"], list):
                    low += sum(1 for c in node["cells"] if c["n"] < C.MIN_SUPPORT)
                    if node.get("suppressed_cells") == 1:
                        single += 1
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(m["groups"])
        assert low == 0, f"{low} printed cells below the floor"
        assert single == 0, f"{single} panels expose a single suppressed cell"
        ok("no printed cell below the floor; no panel exposes a single suppressed cell")
    print("persons data checks passed")


if __name__ == "__main__":
    main()
