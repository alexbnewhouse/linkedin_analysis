"""Deterministic degree-LEVEL rescue for the ~726k rows where `degree_level` is
NULL because the raw `degree` box held a FIELD string (or the field box holds the
degree). We re-run the existing benchmarked degree parser
(`final_hybrid.parse_degree`) on `field_raw` (and, as a fallback, re-parse
`degree_raw`), and keep only rows where it lands on a real degree level.

    uv run python -m edu_clean.degree_level_rescue            # dry-run: gold + coverage
    uv run python -m edu_clean.degree_level_rescue --execute  # write the mapping parquet

Propose-only: writes `normalized/mappings/degree_level_rescue.parquet`
(linkedin_id, idx -> degree_level_rescued, rescue_method); never mutates
education.parquet. The canonical landing of `degree_level_pooled` is separate.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from edu_clean import final_hybrid as FH

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
OUT = ROOT / "normalized" / "mappings" / "degree_level_rescue.parquet"
STATS = Path(__file__).resolve().parent / "results" / "degree_level_rescue.json"

GATE = 0.90  # precision floor (repo standard) before a rescue rule ships


def level_from_text(text: str | None) -> int | None:
    """Degree level (1..7) if the parser lands the string on a real degree via
    the taxonomy / abbreviation path; None for field-names, junk, or raw misses."""
    if not text:
        return None
    canon, method, _conf = FH.parse_degree(text)
    if method not in ("taxonomy", "taxonomy_abbrev"):
        return None
    level_word = canon.split(":", 1)[0]
    return FH.DEGREE_LEVEL_ORDINAL.get(level_word)


def _distinct_pairs(con, where: str):
    return con.execute(
        f"SELECT DISTINCT field_raw, degree_raw FROM read_parquet('{EDUCATION}') "
        f"WHERE {where}").fetchall()


def _rescue_map(pairs) -> dict[tuple, tuple[int, str]]:
    """(field_raw, degree_raw) -> (level, method). Field box first (that's where
    the misplaced degree usually is), then a degree_raw re-parse fallback."""
    out = {}
    for field_raw, degree_raw in pairs:
        lvl = level_from_text(field_raw)
        if lvl is not None:
            out[(field_raw, degree_raw)] = (lvl, "field_rescue")
            continue
        lvl = level_from_text(degree_raw)
        if lvl is not None:
            out[(field_raw, degree_raw)] = (lvl, "degree_reparse")
    return out


def gold(con) -> dict:
    """Honest, NON-circular precision for the rescue rule. The rescue reads the
    LEVEL out of the FIELD box; so measure: among rows with a KNOWN degree_level
    whose FIELD box also parses to a degree level, how often does the field-box
    level equal the true degree_level? (Re-parsing degree_raw would be circular --
    that is how degree_level was assigned in the first place.)"""
    rows = con.execute(
        f"SELECT field_raw, degree_level FROM read_parquet('{EDUCATION}') "
        f"WHERE degree_level IS NOT NULL AND NOT is_duplicate "
        f"AND field_raw IS NOT NULL").fetchall()
    seen, n, ok, fired = {}, 0, 0, 0
    for fraw, lvl in rows:
        if fraw in seen:
            pred = seen[fraw]
        else:
            pred = level_from_text(fraw)
            seen[fraw] = pred
        n += 1
        if pred is not None:            # field box parses to a degree level
            fired += 1
            ok += int(pred == lvl)
    return {"gold_rows_with_field": n, "field_parses_to_level": fired,
            "fire_rate": round(fired / n, 4) if n else None,
            "precision": round(ok / fired, 4) if fired else None,
            "note": ("precision = P(field-box level == true degree_level | field "
                     "box parses to a degree). Non-circular: uses field_raw, not "
                     "the degree_raw that produced degree_level.")}


def run(execute: bool) -> dict:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    g = gold(con)

    where = "degree_level IS NULL AND NOT is_duplicate"
    pairs = _distinct_pairs(con, where)
    rmap = _rescue_map(pairs)

    # materialize a lookup and join to get row-level rescues
    con.execute("CREATE TEMP TABLE rmap (field_raw VARCHAR, degree_raw VARCHAR, "
                "degree_level_rescued TINYINT, rescue_method VARCHAR)")
    con.executemany("INSERT INTO rmap VALUES (?, ?, ?, ?)",
                    [(f, d, lv, m) for (f, d), (lv, m) in rmap.items()])
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE rescue AS
      SELECT e.linkedin_id, e.idx, r.degree_level_rescued, r.rescue_method
      FROM read_parquet('{EDUCATION}') e
      JOIN rmap r ON e.field_raw IS NOT DISTINCT FROM r.field_raw
                 AND e.degree_raw IS NOT DISTINCT FROM r.degree_raw
      WHERE e.degree_level IS NULL AND NOT e.is_duplicate
    """)
    n_null = con.execute(f"SELECT count(*) FROM read_parquet('{EDUCATION}') "
                         f"WHERE degree_level IS NULL AND NOT is_duplicate").fetchone()[0]
    n_rescued = con.execute("SELECT count(*) FROM rescue").fetchone()[0]
    dup = con.execute("SELECT count(*) - count(DISTINCT (linkedin_id, idx)) "
                      "FROM rescue").fetchone()[0]
    assert dup == 0, f"{dup} duplicate (linkedin_id, idx) in rescue -- would fan out"
    by_level = dict(con.execute(
        "SELECT degree_level_rescued, count(*) FROM rescue GROUP BY 1 ORDER BY 1").fetchall())
    by_method = dict(con.execute(
        "SELECT rescue_method, count(*) FROM rescue GROUP BY 1").fetchall())
    hum_gain = con.execute(f"""
      SELECT count(*) FROM rescue rs
      JOIN read_parquet('{EDUCATION}') e USING (linkedin_id, idx)
      WHERE e.nha_level_pooled = 1""").fetchone()[0]

    report = {
        "generated": date.today().isoformat(), "gate": GATE, "gold": g,
        "passes_gate": (g["precision"] is not None and g["precision"] >= GATE),
        "null_level_rows": n_null, "rescued_rows": n_rescued,
        "rescued_pct_of_null": round(100.0 * n_rescued / n_null, 1) if n_null else None,
        "rescued_by_level": {int(k): int(v) for k, v in by_level.items()},
        "rescued_by_method": {k: int(v) for k, v in by_method.items()},
        "humanities_l1_rescued_rows": hum_gain,
        "executed": execute,
    }
    # Always record the result (incl. a gate FAIL) for provenance -- a measured
    # negative is a finding worth keeping, like the repo's A3-anchor rejection.
    STATS.parent.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps(report, indent=2) + "\n")
    if execute:
        if not report["passes_gate"]:
            raise SystemExit(
                f"gold precision {g['precision']} < gate {GATE}; NOT shipping the "
                f"rescue mapping. The degree parser mis-fires on field names with "
                f"degree-like substrings ('diplomacy'->diploma, 'secondary "
                f"education'->high_school). The reliable lever is the context LLM "
                f"jury (edu_clean.run_dlevel_jury), blocked on the serving stack.")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY (SELECT * FROM rescue ORDER BY linkedin_id, idx) "
                    f"TO '{OUT}' (FORMAT parquet, COMPRESSION zstd)")
    con.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    r = run(ap.parse_args().execute)
    print(f"gold: precision={r['gold']['precision']} "
          f"(field_parses_to_level={r['gold']['field_parses_to_level']:,}) "
          f"gate={r['gate']} -> {'PASS' if r['passes_gate'] else 'FAIL'}")
    print(f"rescued {r['rescued_rows']:,} / {r['null_level_rows']:,} null-level rows "
          f"({r['rescued_pct_of_null']}%)")
    print(f"  by level: {r['rescued_by_level']}")
    print(f"  by method: {r['rescued_by_method']}")
    print(f"  humanities-L1 (pooled) rows rescued: {r['humanities_l1_rescued_rows']:,}")
    if not r["executed"]:
        print("(dry-run -- pass --execute to write the mapping)")


if __name__ == "__main__":
    main()
