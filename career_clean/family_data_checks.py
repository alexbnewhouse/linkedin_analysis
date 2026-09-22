"""Data-level invariants of the occupation-family tier on the built career_steps.

    uv run python -m career_clean.family_data_checks      (make test-data)
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from career_clean.families.taxonomy import NEVER_LAND
from career_clean.run_families import GATE, MANAGERIAL, OUT

ROOT = Path(__file__).resolve().parent.parent
STEPS = ROOT / "normalized" / "career_steps.parquet"


def ok(name: str) -> None:
    print(f"  ok: {name}")


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    steps = f"read_parquet('{STEPS}')"
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    if not OUT.exists():
        print("title_family mapping missing; nothing to check")
        return
    assert q(f"SELECT count(*) - count(DISTINCT value) FROM read_parquet('{OUT}')") == 0
    ok("title_family mapping unique on value")
    gate = json.loads(GATE.read_text())
    landed = {(f, st) for f, d in gate["families"].items() for st, v in d["strata"].items() if v["landable"]}
    assert not any(f in NEVER_LAND for f, _ in landed), "a NEVER_LAND family is marked landable"
    ok("no NEVER_LAND family is landable in the gate file")
    bad = q(f"""
        SELECT count(*) FROM {steps}
        WHERE occupation_source = 'family' AND (occupation_code IS NOT NULL OR functional_cluster IS NOT NULL)
    """)
    assert bad == 0, f"{bad} family rows carry a det code or a functional cluster"
    ok("family rows: no det code, no functional cluster")
    rows = con.execute(f"""
        SELECT title_family, title_seniority9, count(*) FROM {steps}
        WHERE occupation_source = 'family' GROUP BY 1, 2""").fetchall()
    off = [(f, s9, n) for f, s9, n in rows
           if (f, "managerial" if s9 in MANAGERIAL else "staff") not in landed]
    assert not off, f"family rows landed outside the gate: {off[:5]}"
    ok("every landed family row is in a landable (family, stratum)")
    bad = q(f"SELECT count(*) FROM {steps} WHERE occupation_source = 'family' AND (title_family_confidence <> 'high' OR title_seniority9 = 'intern')")
    assert bad == 0
    ok("family rows are confidence = high and never intern seniority")
    cov = con.execute(f"""
        SELECT occupation_source, count(*) FROM {steps} GROUP BY 1 ORDER BY 2 DESC""").fetchall()
    total = sum(n for _, n in cov)
    print("  occupation_source:", ", ".join(f"{s}={n:,} ({100*n/total:.1f}%)" for s, n in cov))
    print("family data checks passed")


if __name__ == "__main__":
    main()
