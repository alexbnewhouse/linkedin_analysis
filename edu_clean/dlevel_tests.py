"""Checks for the degree-level jury taxonomy + acceptance logic + (if built) the
merged mapping. Plain-assert style.

    uv run python -m edu_clean.dlevel_tests
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from edu_clean import dlevel_jury as J
from edu_clean import dlevel_taxonomy as T

ROOT = Path(__file__).resolve().parent.parent
MERGE = ROOT / "normalized" / "mappings" / "degree_level_jury.parquet"


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def run() -> None:
    check("taxonomy has 7 levels + abstain", len(T.all_codes()) == 8)
    check("levels 1..7 valid, XUN valid, junk invalid",
          all(T.is_valid(str(i)) for i in range(1, 8)) and T.is_valid("XUN")
          and not T.is_valid("8") and not T.is_valid(""))
    check("schema is reason-first (code enum matches all_codes)",
          T.output_json_schema()["properties"]["code"]["enum"] == T.all_codes())
    # acceptance: unanimous non-abstain accepted; disagreement/abstain rejected
    check("accept: unanimous same level", J.unanimous_accept(["4", "4"]) == "4")
    check("accept: disagreement -> None", J.unanimous_accept(["4", "6"]) is None)
    check("accept: any abstain -> None", J.unanimous_accept(["4", "XUN"]) is None)
    check("accept: incomplete panel -> None", J.unanimous_accept(["4"]) is None)
    # construction sanity (no LLM)
    g = J.gold(20)
    check("gold keys carry a true level in 1..7",
          len(g) > 0 and all(gg["gold_code"] in [str(i) for i in range(1, 8)] for gg in g))

    if MERGE.exists():
        con = duckdb.connect()
        m = f"read_parquet('{MERGE}')"
        dup = con.execute(f"SELECT count(*)-count(DISTINCT key) FROM {m}").fetchone()[0]
        check("merged mapping: unique key (no fan-out)", dup == 0)
        bad = con.execute(f"SELECT count(*) FROM {m} WHERE degree_level_jury NOT BETWEEN 1 AND 7").fetchone()[0]
        check("merged mapping: levels in 1..7", bad == 0)
        con.close()
    else:
        print("  (merge parquet not built yet -- skipping mapping checks)")
    print("\nall degree-level jury tests passed")


if __name__ == "__main__":
    run()
