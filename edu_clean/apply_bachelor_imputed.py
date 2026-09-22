"""Land the imputed-bachelor tier into education.parquet (spec P2), propose-only.

    uv run python -m edu_clean.apply_bachelor_imputed                 # dry-run: report only
    uv run python -m edu_clean.apply_bachelor_imputed --execute       # rewrite parquet
    uv run python -m edu_clean.apply_bachelor_imputed --execute --sample 200   # + blind sample
    uv run python -m edu_clean.apply_bachelor_imputed --execute --unland       # remove the tier

Runs AFTER apply_degree_level_pooled and apply_cip_pooled (it reads cip2_pooled) and
BEFORE rebuild_education_person. Sets degree_level_pooled = 4 and
degree_level_source = 'imputed_bachelor' on rows that satisfy imputed_bachelor.predicate_sql;
touches nothing else. Idempotent: previously imputed rows are cleared before recomputing.
The deterministic degree_level and the CIP backbone are fingerprint-asserted unchanged.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from edu_clean import imputed_bachelor as IB

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
SCHOOL_IPEDS = ROOT / "normalized" / "mappings" / "school_ipeds.parquet"
INST_META = ROOT / "reference" / "institution_meta.parquet"
MANIFEST = ROOT / "normalized" / "_bachelor_imputed_manifest.json"
SAMPLE = ROOT / "edu_clean" / "results" / "imputed_bachelor_sample.jsonl"
FP_LEVEL = "bit_xor(hash(linkedin_id, idx, degree_level))"
FP_CIP = "bit_xor(hash(linkedin_id, cip_code, nha_level))"
SALT = "p2-imputed-2026-09-22"

RUBRIC = ("pass = a completed or in-progress bachelor's at a bachelor's-granting institution; "
          "fail = exchange term, minor, certificate, license, associate, master's, residency, "
          "or an institution that does not grant bachelor's; unsure = cannot tell from the row")


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def _register(con: duckdb.DuckDBPyConnection) -> None:
    con.create_function("school_excluded", IB.school_excluded, ["VARCHAR"], "BOOLEAN",
                        null_handling="special")
    con.create_function("degree_negative", IB.degree_negative, ["VARCHAR"], "BOOLEAN",
                        null_handling="special")
    con.create_function("carnegie_excluded", IB.carnegie_excluded, ["VARCHAR"], "BOOLEAN",
                        null_handling="special")


def _build_views(con: duckdb.DuckDBPyConnection, unland: bool) -> None:
    edu = f"read_parquet('{_q(EDUCATION)}')"
    # base: existing pooled columns with any prior imputation cleared (idempotence)
    con.execute(f"""
      CREATE OR REPLACE TEMP VIEW base AS
      SELECT * REPLACE (
        CASE WHEN degree_level_source = '{IB.SOURCE}' THEN NULL ELSE degree_level_pooled END
          AS degree_level_pooled,
        CASE WHEN degree_level_source = '{IB.SOURCE}' THEN NULL ELSE degree_level_source END
          AS degree_level_source)
      FROM {edu}
    """)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE lvl AS
      SELECT s.school_slug, any_value(m.iclevel_label) AS iclevel_label,
             any_value(m.carnegie_label) AS carnegie_label
      FROM read_parquet('{_q(SCHOOL_IPEDS)}') s
      JOIN read_parquet('{_q(INST_META)}') m ON m.unitid = s.unitid
      GROUP BY 1
    """)
    con.execute("""
      CREATE OR REPLACE TEMP TABLE guard AS
      SELECT linkedin_id, idx,
             bool_or(other_bach) AS bachelor_elsewhere,
             bool_or(other_grad_same) AS grad_same_school
      FROM (
        SELECT a.linkedin_id, a.idx,
               (b.idx <> a.idx AND b.degree_level_pooled = 4) AS other_bach,
               (b.idx <> a.idx AND b.degree_level_pooled >= 6
                AND lower(trim(b.school_raw)) = lower(trim(a.school_raw))) AS other_grad_same
        FROM base a JOIN base b ON a.linkedin_id = b.linkedin_id
        WHERE a.degree_level_pooled IS NULL AND a.cip2_pooled IS NOT NULL
      ) GROUP BY 1, 2
    """)
    pred = "FALSE" if unland else IB.predicate_sql("e", "lvl", "g")
    con.execute(f"""
      CREATE OR REPLACE TEMP VIEW ep AS
      SELECT e.* REPLACE (
        CASE WHEN e.degree_level_pooled IS NOT NULL THEN e.degree_level_pooled
             WHEN {pred} THEN {IB.LEVEL} END AS degree_level_pooled,
        CASE WHEN e.degree_level_source IS NOT NULL THEN e.degree_level_source
             WHEN {pred} THEN '{IB.SOURCE}' END AS degree_level_source)
      FROM base e
      LEFT JOIN lvl ON lvl.school_slug = e.school_slug
      LEFT JOIN guard g ON g.linkedin_id = e.linkedin_id AND g.idx = e.idx
    """)


def run(execute: bool, sample: int = 0, unland: bool = False) -> dict:
    con = duckdb.connect()
    con.execute("PRAGMA threads=16")
    _register(con)
    _build_views(con, unland)
    src = f"read_parquet('{_q(EDUCATION)}')"
    n_src = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    n_new = con.execute("SELECT count(*) FROM ep").fetchone()[0]
    assert n_src == n_new, f"row count changed {n_src} -> {n_new}"
    for fp in (FP_LEVEL, FP_CIP):
        assert con.execute(f"SELECT {fp} FROM {src}").fetchone()[0] == \
               con.execute(f"SELECT {fp} FROM ep").fetchone()[0], f"backbone changed: {fp}"
    # det/jury rows must be byte-identical (fingerprint, not a join: 48 linkedin_ids
    # repeat at parse grain, so (linkedin_id, idx) is not a unique key)
    fp_dj = ("SELECT count(*), bit_xor(hash(linkedin_id, idx, degree_level_pooled, degree_level_source)) "
             "FROM {t} WHERE degree_level_source IN ('det', 'jury')")
    assert con.execute(fp_dj.format(t="base")).fetchone() == con.execute(fp_dj.format(t="ep")).fetchone(), \
        "det/jury pooled rows changed"

    imputed_rows = con.execute(
        f"SELECT count(*) FROM ep WHERE degree_level_source = '{IB.SOURCE}'").fetchone()[0]
    persons_first_level = con.execute(f"""
      SELECT count(*) FROM (
        SELECT linkedin_id FROM ep GROUP BY 1
        HAVING bool_or(degree_level_source = '{IB.SOURCE}')
           AND NOT bool_or(degree_level_source IN ('det', 'jury'))
      )""").fetchone()[0]
    l1_persons_gain = con.execute(f"""
      SELECT count(*) FROM (
        SELECT linkedin_id FROM ep GROUP BY 1
        HAVING bool_or(degree_level_source = '{IB.SOURCE}' AND nha_level_pooled = 1)
           AND NOT bool_or(degree_level_source IN ('det', 'jury') AND degree_level_pooled = 4
                           AND nha_level_pooled = 1)
      )""").fetchone()[0]
    top_schools = con.execute(f"""
      SELECT school_raw, count(*) c FROM ep WHERE degree_level_source = '{IB.SOURCE}'
      GROUP BY 1 ORDER BY 2 DESC LIMIT 15""").fetchall()
    by_group = con.execute(f"""
      SELECT humanities_field_group_pooled, count(*) c FROM ep
      WHERE degree_level_source = '{IB.SOURCE}' GROUP BY 1 ORDER BY 2 DESC LIMIT 12""").fetchall()
    report = {
        "generated": date.today().isoformat(), "rows": n_new, "executed": execute, "unland": unland,
        "imputed_rows": imputed_rows, "persons_gaining_first_level": persons_first_level,
        "l1_bachelor_persons_gained": l1_persons_gain,
        "top_schools": [{"school": s, "rows": c} for s, c in top_schools],
        "by_field_group": [{"group": g, "rows": c} for g, c in by_group],
        "rubric": RUBRIC,
    }
    if execute:
        tmp = EDUCATION.with_suffix(".parquet.tmp")
        con.execute(f"COPY ep TO '{_q(tmp)}' (FORMAT parquet, COMPRESSION zstd)")
        EDUCATION.unlink()
        tmp.replace(EDUCATION)
        MANIFEST.write_text(json.dumps(report, indent=2) + "\n")
    if sample and not unland:
        rows = con.execute(f"""
          SELECT linkedin_id, idx, school_raw, degree_raw, field_raw, left(description, 200) AS description,
                 start_year, end_year, cip2_pooled, humanities_field_group_pooled
          FROM ep WHERE degree_level_source = '{IB.SOURCE}'
          ORDER BY hash(linkedin_id || '|' || idx::VARCHAR || '|{SALT}') LIMIT {int(sample)}
        """).fetchall()
        cols = ["linkedin_id", "idx", "school_raw", "degree_raw", "field_raw", "description",
                "start_year", "end_year", "cip2_pooled", "field_group"]
        SAMPLE.parent.mkdir(parents=True, exist_ok=True)
        with SAMPLE.open("w") as fh:
            fh.write(json.dumps({"_header": True, "sample": "imputed_bachelor", "n": len(rows),
                                 "salt": SALT, "rubric": RUBRIC,
                                 "labels": ["pass", "fail", "unsure"]}) + "\n")
            for i, r in enumerate(rows):
                d = dict(zip(cols, r))
                d["id"] = f"imputed_bachelor:{i:03d}"
                fh.write(json.dumps(d, default=str) + "\n")
        report["sample_path"] = str(SAMPLE.relative_to(ROOT))
    con.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--unland", action="store_true")
    a = ap.parse_args()
    r = run(a.execute, a.sample, a.unland)
    print(f"imputed rows: {r['imputed_rows']:,}; persons gaining a first level: "
          f"{r['persons_gaining_first_level']:,}; L1 bachelor's persons gained: "
          f"{r['l1_bachelor_persons_gained']:,}")
    print("top schools:", ", ".join(f"{t['school']} ({t['rows']})" for t in r["top_schools"][:8]))
    print("by field group:", ", ".join(f"{t['group']} ({t['rows']})" for t in r["by_field_group"][:8]))
    if r.get("sample_path"):
        print("sample:", r["sample_path"])
    if not r["executed"]:
        print("(dry-run)")


if __name__ == "__main__":
    main()
