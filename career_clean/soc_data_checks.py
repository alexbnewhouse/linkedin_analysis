"""Data-level invariants of the pooled SOC-major axis on the built tables.

    uv run python -m career_clean.soc_data_checks      (make test-data)

Audit 2026-09-02 red H4: PIPELINE.md promised a career-side fingerprint that
never existed. These checks pin what the landed column must satisfy after
every ``build_normalized --sections career`` or ``run_soc_jury merge``.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from career_clean.run_soc_jury import MERGE_OUT, _non_occupation

ROOT = Path(__file__).resolve().parent.parent
STEPS = ROOT / "normalized" / "career_steps.parquet"


def ok(name: str) -> None:
    print(f"  ok: {name}")


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    steps = f"read_parquet('{STEPS}')"
    jury = f"read_parquet('{MERGE_OUT}')"

    dup = con.execute(f"SELECT count(*) - count(DISTINCT role_canonical) FROM {jury}").fetchone()[0]
    assert dup == 0, f"role_soc_jury has {dup} duplicate role_canonical rows"
    ok("jury mapping unique on role_canonical")

    bad_det = con.execute(f"""
        SELECT count(*) FROM {steps}
        WHERE occupation_code IS NOT NULL
          AND (occupation_source <> 'det' OR occupation_major_pooled <> substr(occupation_code, 1, 2))
    """).fetchone()[0]
    assert bad_det == 0, f"{bad_det} det rows where pooled major != 2-digit prefix"
    ok("det rows: occupation_major_pooled == substr(occupation_code, 1, 2)")

    bad_jury = con.execute(f"""
        SELECT count(*) FROM {steps}
        WHERE occupation_source = 'jury' AND occupation_code IS NOT NULL
    """).fetchone()[0]
    assert bad_jury == 0, f"{bad_jury} jury rows carry a deterministic code"
    ok("jury rows: no deterministic code (det always wins)")

    bad_src = con.execute(f"""
        SELECT count(*) FROM {steps}
        WHERE (occupation_major_pooled IS NULL) <> (occupation_source IS NULL)
    """).fetchone()[0]
    assert bad_src == 0, f"{bad_src} rows where pooled major and source disagree on NULLness"
    ok("pooled major and source are NULL together")

    # the non-occupation filter must hold on what was merged
    rows = con.execute(f"""
        SELECT j.role_canonical, any_value(s.role_display)
        FROM {jury} j JOIN {steps} s USING (role_canonical)
        WHERE s.occupation_source = 'jury' GROUP BY 1
    """).fetchall()
    leaked = [d for _, d in rows if _non_occupation(d)]
    assert not leaked, f"non-occupation forms landed by the jury: {leaked[:10]}"
    ok(f"no non-occupation form among {len(rows):,} landed jury roles")

    det, pooled = con.execute(f"""
        SELECT avg((occupation_code IS NOT NULL)::INT), avg((occupation_major_pooled IS NOT NULL)::INT)
        FROM {steps}""").fetchone()
    assert pooled > det, "pooled coverage must exceed deterministic coverage"
    ok(f"coverage: det {det:.3%} -> pooled {pooled:.3%}")
    print("All SOC data checks passed.")


if __name__ == "__main__":
    main()
