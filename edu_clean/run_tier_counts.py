"""Driver: re-derive the NHA humanities boundary-tier counts from the committed
education crosswalk and write the single source of truth for every doc/prompt
that cites them.

    uv run python -m edu_clean.run_tier_counts

Writes `edu_clean/results/tier_counts.json` with the nested L1/L2/L3 record and
distinct-person counts, the CIP coverage denominator they were computed at, and
an input-content fingerprint so any drift between this file and a fresh
re-derivation is mechanically detectable (see `edu_clean.tier_tests`).

This is the *only* place that should compute these numbers from scratch;
`portal/build.py:boundary_counts` re-derives the identical query independently
(same `nha_level` column, same nesting) as a cross-check, and both must agree
with this file -- that agreement is exactly what Plan 1 (COVERAGE_PLAN.md) is
for. This module does not import from or modify `portal/`.

Fingerprint choice: file size (bytes) + row count + an order-independent
`bit_xor(hash(linkedin_id, cip_code, nha_level))` over the three columns that
determine every count in this file. XOR-of-hash is invariant to row order (a
parquet rewrite that reshuffles rows without changing content still matches),
cheap (single columnar pass, no sort), and changes if any of those columns'
values change for any row. It is not a cryptographic hash and does not cover
columns outside this file's scope (e.g. `field_raw`) -- that's fine, it exists
to catch drift in the inputs to *this* computation, not to fingerprint the
whole parquet.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
RESULTS = Path(__file__).resolve().parent / "results"
OUT = RESULTS / "tier_counts.json"

TIERS = (("l1", "= 1"), ("l2", "IN (1, 2)"), ("l3", "IN (1, 2, 3)"))


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def fingerprint(con: duckdb.DuckDBPyConnection) -> dict:
    # Covers both the deterministic backbone (cip_code, nha_level) AND the pooled
    # columns (cip2_pooled, nha_level_pooled) so drift in EITHER layer is caught.
    edu = f"read_parquet('{_q(EDUCATION)}')"
    n_rows, xor_hash = con.execute(
        f"SELECT count(*), bit_xor(hash(linkedin_id, cip_code, nha_level, "
        f"cip2_pooled, nha_level_pooled)) FROM {edu}"
    ).fetchone()
    return {
        "file": str(EDUCATION.relative_to(ROOT)),
        "file_size_bytes": EDUCATION.stat().st_size,
        "row_count": int(n_rows),
        "content_hash_method": ("bit_xor(hash(linkedin_id, cip_code, nha_level, "
                                "cip2_pooled, nha_level_pooled))"),
        "content_hash": str(xor_hash),
    }


def _tiers(con, edu: str, level_col: str) -> dict:
    tiers = {}
    for key, pred in TIERS:
        records, persons = con.execute(
            f"SELECT count(*), count(DISTINCT linkedin_id) FROM {edu} "
            f"WHERE {level_col} {pred}").fetchone()
        tiers[key] = {"records": int(records), "persons": int(persons)}
    assert tiers["l1"]["records"] <= tiers["l2"]["records"] <= tiers["l3"]["records"]
    assert tiers["l1"]["persons"] <= tiers["l2"]["persons"] <= tiers["l3"]["persons"]
    return tiers


def _coverage(con, edu: str, code_col: str) -> dict:
    total = con.execute(f"SELECT count(*) FROM {edu}").fetchone()[0]
    coded = con.execute(
        f"SELECT count(*) FROM {edu} WHERE {code_col} IS NOT NULL").fetchone()[0]
    rate = coded / total if total else None
    return {
        "total_rows": int(total),
        "coded_rows": int(coded),
        "rate": round(rate, 4) if rate is not None else None,
        "rate_pct_1dp": round(rate * 100, 1) if rate is not None else None,
    }


def derive(con: duckdb.DuckDBPyConnection) -> dict:
    edu = f"read_parquet('{_q(EDUCATION)}')"
    # Deterministic layer (unchanged keys: existing consumers + portal
    # boundary_counts cross-check read these). Pooled layer (det backbone + CIP
    # jury) is the current headline; the two coexist so any doc/consumer can cite
    # either with its provenance.
    return {
        "cip_coverage": _coverage(con, edu, "cip_code"),
        "tiers": _tiers(con, edu, "nha_level"),
        "cip_coverage_pooled": _coverage(con, edu, "cip2_pooled"),
        "tiers_pooled": _tiers(con, edu, "nha_level_pooled"),
    }


def compute() -> dict:
    """Derive the full payload (counts + fingerprint) without writing anything.
    Used by both `run()` and the drift test, so the test never has to touch
    disk to get a fresh comparison value."""
    con = duckdb.connect()
    result = derive(con)
    fp = fingerprint(con)
    con.close()
    return {
        "generated": date.today().isoformat(),
        "source": "edu_clean.run_tier_counts (re-derives from normalized/education.parquet)",
        "input_fingerprint": fp,
        **result,
    }


def run() -> dict:
    payload = compute()
    RESULTS.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def main() -> None:
    payload = run()
    for label, cov_key, t_key in (("deterministic", "cip_coverage", "tiers"),
                                  ("pooled (+CIP jury)", "cip_coverage_pooled",
                                   "tiers_pooled")):
        t, cov = payload[t_key], payload[cov_key]
        print(f"[{label}] CIP coverage: {cov['coded_rows']:,} / "
              f"{cov['total_rows']:,} ({cov['rate_pct_1dp']}%)")
        for key in ("l1", "l2", "l3"):
            print(f"  {key}: {t[key]['records']:,} records / "
                  f"{t[key]['persons']:,} persons")
    print(f"written {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
