"""Build the row-level employer-keyed override mapping (spec P5).

    uv run python -m career_clean.run_overrides                  # -> normalized/mappings/career_occupation_override.parquet
    uv run python -m career_clean.run_overrides --sample 50      # + per-reason blind sample (after the rebuild)

Reads career_steps + industry/results/step_industry.parquet, pre-filters candidate rows
in SQL, applies overrides.override in Python, writes one row per step key (DISTINCT
asserted: 88 step keys repeat at parse grain). Stats to
career_clean/results/overrides_stats.json. Rebuild career_steps afterwards
(`make normalize-career`) to land occupation_code_pooled / occupation_source = 'override'.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from career_clean.overrides import override

ROOT = Path(__file__).resolve().parent.parent
STEPS = ROOT / "normalized" / "career_steps.parquet"
INDUSTRY = ROOT / "industry" / "results" / "step_industry.parquet"
OUT = ROOT / "normalized" / "mappings" / "career_occupation_override.parquet"
STATS = ROOT / "career_clean" / "results" / "overrides_stats.json"
SAMPLE = ROOT / "career_clean" / "results" / "override_sample.jsonl"
SALT = "p5-override-2026-09-22"
RUBRIC = ("pass = the override occupation code is right for this title at this employer; "
          "fail = a different code is clearly right (e.g. a paralegal, a bank VP who is a loan "
          "officer, a university principal); unsure = cannot tell")
CODE_LABELS = {"11-1021": "General and Operations Managers", "11-9032": "Education Administrators, K-12",
               "23-1011": "Lawyers", "11-1011": "Chief Executives"}


def build() -> dict:
    con = duckdb.connect()
    con.execute("PRAGMA threads=16")
    rows = con.execute(f"""
        SELECT c.source_table, c.linkedin_id, c.experience_idx, c.position_idx,
               c.title_raw, c.seniority_level, c.role_canonical, i.l1, i.l2, c.occupation_code
        FROM read_parquet('{STEPS}') c
        LEFT JOIN read_parquet('{INDUSTRY}') i
          ON i.source_table = c.source_table AND i.linkedin_id = c.linkedin_id
         AND i.experience_idx = c.experience_idx AND i.position_idx IS NOT DISTINCT FROM c.position_idx
        WHERE (c.seniority_level LIKE '%vice%' AND c.role_canonical IN ('president', 'assistantpresident'))
           OR regexp_matches(lower(c.title_raw), '^\\s*((assistant|associate|vice|interim|acting|school)\\s+)?principal\\s*$')
           OR (i.l2 = 'PRO.LEGAL' AND lower(trim(c.title_raw)) IN
               ('partner', 'managing partner', 'senior partner', 'equity partner', 'junior partner',
                'name partner', 'founding partner', 'associate', 'senior associate', 'junior associate',
                'of counsel', 'counsel', 'shareholder', 'member', 'associate attorney', 'principal'))
    """).fetchall()
    seen: set[tuple] = set()
    out: list[dict] = []
    by_reason: dict[str, int] = {}
    det_changed = 0
    for st, lid, eidx, pidx, title, sen, role, l1, l2, det in rows:
        o = override(title, sen, role, l1, l2)
        if not o:
            continue
        key = (st, lid, eidx, pidx)
        if key in seen:
            continue
        seen.add(key)
        if det is not None and det[:2] != o.soc_major:
            det_changed += 1
            continue  # never change a non-NULL det major
        out.append({"source_table": st, "linkedin_id": lid, "experience_idx": eidx, "position_idx": pidx,
                    "occupation_code_override": o.occupation_code, "soc_major_override": o.soc_major,
                    "reason": o.reason, "occupation_code_before": det})
        by_reason[o.reason] = by_reason.get(o.reason, 0) + 1
    t = pa.Table.from_pylist(out, schema=pa.schema([
        ("source_table", pa.string()), ("linkedin_id", pa.string()), ("experience_idx", pa.int64()),
        ("position_idx", pa.int64()), ("occupation_code_override", pa.string()),
        ("soc_major_override", pa.string()), ("reason", pa.string()), ("occupation_code_before", pa.string())]))
    pq.write_table(t, OUT, compression="zstd")
    stats = {"generated": date.today().isoformat(), "candidates": len(rows), "rows": t.num_rows,
             "by_reason": by_reason, "skipped_det_major_conflict": det_changed, "rubric": RUBRIC}
    STATS.parent.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps(stats, indent=1) + "\n")
    print(f"wrote {OUT} ({t.num_rows:,} rows from {len(rows):,} candidates); by reason: {by_reason}; "
          f"skipped (det major conflict): {det_changed}")
    return stats


def sample(n_per_reason: int) -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    rows = []
    for reason in ("vice_president", "k12_principal", "law_firm_partner"):
        rows += con.execute(f"""
            SELECT o.reason, c.title_raw, c.company_raw, i.l1 AS industry_l1, i.l2 AS industry_l2,
                   o.occupation_code_before, o.occupation_code_override
            FROM read_parquet('{OUT}') o
            JOIN read_parquet('{STEPS}') c
              ON c.source_table = o.source_table AND c.linkedin_id = o.linkedin_id
             AND c.experience_idx = o.experience_idx AND c.position_idx IS NOT DISTINCT FROM o.position_idx
            LEFT JOIN read_parquet('{INDUSTRY}') i
              ON i.source_table = c.source_table AND i.linkedin_id = c.linkedin_id
             AND i.experience_idx = c.experience_idx AND i.position_idx IS NOT DISTINCT FROM c.position_idx
            WHERE o.reason = '{reason}'
            ORDER BY hash(o.linkedin_id || '|' || o.experience_idx::VARCHAR || '|' ||
                          coalesce(o.position_idx::VARCHAR, '') || '|{SALT}') LIMIT {int(n_per_reason)}
        """).fetchall()
    cols = ["reason", "title_raw", "company_raw", "industry_l1", "industry_l2",
            "occupation_code_before", "occupation_code_override"]
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE.open("w") as fh:
        fh.write(json.dumps({"_header": True, "sample": "overrides", "n": len(rows), "salt": SALT,
                             "rubric": RUBRIC, "labels": ["pass", "fail", "unsure"],
                             "strata": {"per_reason": n_per_reason}}) + "\n")
        for i, r in enumerate(rows):
            d = dict(zip(cols, r))
            d["occupation_label"] = CODE_LABELS.get(d["occupation_code_override"], "")
            d["id"] = f"overrides:{i:03d}"
            fh.write(json.dumps(d, default=str, ensure_ascii=False) + "\n")
    print(f"wrote {SAMPLE} ({len(rows)} rows)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    a = ap.parse_args()
    if a.sample:
        sample(a.sample)
    else:
        build()


if __name__ == "__main__":
    main()
