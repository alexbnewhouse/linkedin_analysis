"""Land the co-major columns into education.parquet (spec P3), propose-only.

    uv run python -m edu_clean.apply_comajors                     # dry-run
    uv run python -m edu_clean.apply_comajors --execute            # append/rebuild the columns
    uv run python -m edu_clean.apply_comajors --execute --sample 100   # + stratified blind sample

Appended columns (rebuilt from scratch each run; nothing deterministic changes):

    cip_secondary        the OTHER resolved major when a major matches the row's cip2_pooled
    cip2_secondary       its 2-digit family
    nha_level_secondary  NHA level of the secondary (0 = none)
    minor_cip / minor_cip2 / nha_level_minor
    field_components_n   resolved components on the value (0 when not split)
    comajor_source       'split' | 'conflict' (pooled family matches no major) |
                         'no_primary' (row has no pooled family) | NULL (value not split)

Secondary and minor columns are populated only when comajor_source = 'split'. Runs after
the imputed-bachelor apply and before rebuild_education_person. The mapping is optional:
when it is missing the columns are appended as NULL with a warning.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from edu_clean import humanities as H

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
MAPPING = ROOT / "normalized" / "mappings" / "edu_field_components.parquet"
MANIFEST = ROOT / "normalized" / "_comajors_manifest.json"
SAMPLE = ROOT / "edu_clean" / "results" / "comajors_sample.jsonl"
ADDED = ("cip_secondary", "cip2_secondary", "nha_level_secondary", "minor_cip", "minor_cip2",
         "nha_level_minor", "field_components_n", "comajor_source")
FP = "bit_xor(hash(linkedin_id, idx, cip_code, cip2_pooled, degree_level_pooled, degree_level_source))"
SALT = "p3-comajors-2026-09-22-v3"
RUBRIC = ("pass = the field string names two distinct fields (major + major, or major + minor) AND "
          "each CIP shown is right for its component; fail = one program name that was split, or "
          "a wrong CIP on either component; unsure = cannot tell from the string")


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def _nha(code: str | None) -> int:
    return H.classify_cip(code).level if code else 0


def run(execute: bool, sample: int = 0) -> dict:
    con = duckdb.connect()
    con.execute("PRAGMA threads=16")
    con.create_function("nha_of", _nha, ["VARCHAR"], "INTEGER", null_handling="special")
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{_q(EDUCATION)}')").fetchall()]
    keep = ", ".join(f"e.{c}" for c in cols if c not in ADDED)
    if MAPPING.exists():
        con.execute(f"CREATE OR REPLACE TEMP VIEW m AS SELECT * FROM read_parquet('{_q(MAPPING)}')")
    else:
        print(f"WARNING: {MAPPING.name} missing -- co-major columns will be NULL", flush=True)
        con.execute("CREATE OR REPLACE TEMP VIEW m AS SELECT NULL::VARCHAR AS value, NULL::VARCHAR AS status, "
                    "NULL::VARCHAR AS marker_class, NULL::VARCHAR[] AS major_cips, NULL::VARCHAR AS minor_cip, "
                    "NULL::INTEGER AS n_majors, NULL::INTEGER AS n_minors, NULL::INTEGER AS n_concentrations, "
                    "NULL::INTEGER AS nha_level_minor WHERE FALSE")
    # per-row primary choice: the major whose family equals cip2_pooled
    con.execute(f"""
      CREATE OR REPLACE TEMP VIEW ep AS
      WITH j AS (
        SELECT {keep},
               m.status, m.marker_class, m.major_cips, m.minor_cip AS m_minor,
               m.n_majors, m.n_minors, m.n_concentrations, m.nha_level_minor AS m_nha_minor,
               list_filter(m.major_cips, x -> x[1:2] = e.cip2_pooled) AS matching,
               list_filter(m.major_cips, x -> x[1:2] <> e.cip2_pooled) AS others
        FROM read_parquet('{_q(EDUCATION)}') e
        LEFT JOIN m ON m.value = e.field_raw
      ),
      k AS (
        SELECT *,
          CASE WHEN status = 'split' AND cip2_pooled IS NULL THEN 'no_primary'
               -- a stoplisted one-program head carries no CIP: minor/concentration only
               WHEN status = 'split' AND len(major_cips) = 0 THEN 'split'
               WHEN status = 'split' AND len(matching) = 0 THEN 'conflict'
               WHEN status = 'split' THEN 'split' END AS comajor_source,
          CASE WHEN status = 'split' AND cip2_pooled IS NOT NULL AND len(matching) > 0 AND len(others) > 0
               THEN others[1] END AS cip_secondary
        FROM j
      )
      SELECT * EXCLUDE (status, marker_class, major_cips, m_minor, n_majors, n_minors, n_concentrations,
                        m_nha_minor, matching, others),
             cip_secondary[1:2] AS cip2_secondary,
             nha_of(cip_secondary) AS nha_level_secondary,
             CASE WHEN comajor_source = 'split' THEN m_minor END AS minor_cip,
             CASE WHEN comajor_source = 'split' THEN m_minor[1:2] END AS minor_cip2,
             CASE WHEN comajor_source = 'split' THEN coalesce(m_nha_minor, 0) ELSE 0 END AS nha_level_minor,
             CASE WHEN status = 'split' THEN coalesce(n_majors, 0) + coalesce(n_minors, 0) + coalesce(n_concentrations, 0)
                  ELSE 0 END AS field_components_n,
             marker_class AS _marker_class
      FROM k
    """)
    src = f"read_parquet('{_q(EDUCATION)}')"
    n_src = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    n_new = con.execute("SELECT count(*) FROM ep").fetchone()[0]
    assert n_src == n_new, f"row count changed {n_src} -> {n_new}"
    assert con.execute(f"SELECT {FP} FROM {src}").fetchone()[0] == \
           con.execute(f"SELECT {FP} FROM ep").fetchone()[0], "backbone / pooled columns changed"
    dist = con.execute("SELECT comajor_source, count(*) FROM ep GROUP BY 1 ORDER BY 2 DESC").fetchall()
    l1_gain = con.execute("""
      SELECT count(*) FROM (
        SELECT linkedin_id FROM ep WHERE NOT is_duplicate GROUP BY 1
        HAVING bool_or(comajor_source = 'split' AND nha_level_secondary = 1
                       AND coalesce(degree_level_pooled, degree_level) = 4)
           AND NOT bool_or(nha_level_pooled = 1 AND coalesce(degree_level_pooled, degree_level) = 4))
    """).fetchone()[0]
    pairs = con.execute("""
      SELECT cip2_pooled || '+' || cip2_secondary AS pair, count(*) c FROM ep
      WHERE comajor_source = 'split' AND cip2_secondary IS NOT NULL
        AND (nha_level_pooled = 1 OR nha_level_secondary = 1)
      GROUP BY 1 ORDER BY 2 DESC LIMIT 15""").fetchall()
    report = {"generated": date.today().isoformat(), "rows": n_new, "executed": execute,
              "by_source": [{"source": s, "rows": c} for s, c in dist],
              "l1_bachelor_persons_gained_via_secondary": l1_gain,
              "top_l1_pairs": [{"pair": p, "rows": c} for p, c in pairs], "rubric": RUBRIC}
    if execute:
        tmp = EDUCATION.with_suffix(".parquet.tmp")
        con.execute(f"COPY (SELECT * EXCLUDE (_marker_class) FROM ep) TO '{_q(tmp)}' (FORMAT parquet, COMPRESSION zstd)")
        EDUCATION.unlink()
        tmp.replace(EDUCATION)
        MANIFEST.write_text(json.dumps(report, indent=2) + "\n")
    if sample:
        half = int(sample) // 2
        rows = []
        for mc in ("plain", "marker"):
            rows += con.execute(f"""
              SELECT ep.linkedin_id, ep.idx, ep.field_raw, m.components, ep.cip2_pooled,
                     CASE WHEN len(list_filter(m.major_cips, x -> x[1:2] = ep.cip2_pooled)) > 0
                          THEN list_filter(m.major_cips, x -> x[1:2] = ep.cip2_pooled)[1] END AS primary_cip,
                     ep.cip_secondary, ep.minor_cip, '{mc}' AS marker_class
              FROM ep JOIN m ON m.value = ep.field_raw
              WHERE ep.comajor_source = 'split' AND ep._marker_class = '{mc}'
                AND (ep.cip_secondary IS NOT NULL OR ep.minor_cip IS NOT NULL)
              ORDER BY hash(ep.linkedin_id || '|' || ep.idx::VARCHAR || '|{SALT}') LIMIT {half}
            """).fetchall()
        cols = ["linkedin_id", "idx", "field_raw", "components", "cip2_pooled", "primary_cip",
                "cip_secondary", "minor_cip", "marker_class"]
        SAMPLE.parent.mkdir(parents=True, exist_ok=True)
        with SAMPLE.open("w") as fh:
            fh.write(json.dumps({"_header": True, "sample": "comajors", "n": len(rows), "salt": SALT,
                                 "rubric": RUBRIC, "labels": ["pass", "fail", "unsure"],
                                 "strata": {"plain": half, "marker": half}}) + "\n")
            for i, r in enumerate(rows):
                d = dict(zip(cols, r))
                d["secondary_cip"] = d.pop("cip_secondary")
                d["id"] = f"comajors:{SALT.rsplit('-', 1)[-1]}:{i:03d}"
                fh.write(json.dumps(d, default=str, ensure_ascii=False) + "\n")
        report["sample_path"] = str(SAMPLE.relative_to(ROOT))
    con.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--sample", type=int, default=0)
    a = ap.parse_args()
    r = run(a.execute, a.sample)
    print("by source:", ", ".join(f"{d['source']}={d['rows']:,}" for d in r["by_source"]))
    print(f"L1 bachelor's persons gained via a secondary major: {r['l1_bachelor_persons_gained_via_secondary']:,}")
    print("top L1 pairs:", ", ".join(f"{d['pair']} ({d['rows']})" for d in r["top_l1_pairs"][:10]))
    if r.get("sample_path"):
        print("sample:", r["sample_path"])
    if not r["executed"]:
        print("(dry-run)")


if __name__ == "__main__":
    main()
