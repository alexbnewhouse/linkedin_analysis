"""Materialize row-level normalized education and career production tables.

Run with:

    uv run python build_normalized.py

Outputs:

    normalized/
      _manifest.json
      education.parquet
      career_steps.parquet
      mappings/*.parquet

The cleaner modules operate primarily as value canonicalizers: distinct raw
values -> canonical ids, methods, and confidences. This script turns those
canonicalizers into production row-level Parquet by writing mapping tables and
joining them back onto the parsed LinkedIn star schema.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from career_clean import approach_a_rules as career_rules
from career_clean import final_hybrid as career_final
from career_clean.common import EXP, POS, ROOT, load_vocab as load_career_vocab
from edu_clean import final_hybrid as edu_final
from edu_clean.common import EDU, load_vocab as load_edu_vocab


@dataclass
class StepTiming:
    name: str
    runtime_s: float
    rows: int | None = None
    path: str | None = None


class StepTimer:
    def __init__(self, name: str, timings: list[StepTiming]):
        self.name = name
        self.timings = timings
        self.start = 0.0
        self.record: StepTiming | None = None

    def __enter__(self):
        print(f"[build] {self.name} ...", flush=True)
        self.start = time.monotonic()
        self.record = StepTiming(self.name, 0.0)
        self.timings.append(self.record)
        return self

    def __exit__(self, *_args):
        elapsed = time.monotonic() - self.start
        if self.record is not None:
            self.record.runtime_s = elapsed
        print(f"[build] {self.name} done in {elapsed:.1f}s", flush=True)


def _write_table(path: Path, columns: dict[str, list[Any]]) -> int:
    table = pa.table(columns)
    pq.write_table(table, path, compression="zstd")
    return table.num_rows


def _write_value_mapping(path: Path, result) -> int:
    values = list(result.mapping)
    return _write_table(
        path,
        {
            "value": values,
            "canonical_id": [result.mapping[v] for v in values],
            "method": [result.method.get(v) for v in values],
            "confidence": [result.confidence.get(v) for v in values],
        },
    )


def _write_title_mapping(path: Path, result) -> int:
    """Value mapping plus the title-only aux axes: ``seniority_rank_token``
    (finding 2: extended rank lexicon, separate from the canonical) and
    ``role_display`` (finding 5: human-readable label per role canonical)."""
    values = list(result.mapping)
    rank = result.aux.get("seniority_rank_token", {})
    display = result.aux.get("role_display", {})
    return _write_table(
        path,
        {
            "value": values,
            "canonical_id": [result.mapping[v] for v in values],
            "method": [result.method.get(v) for v in values],
            "confidence": [result.confidence.get(v) for v in values],
            "seniority_rank_token": [rank.get(v) for v in values],
            "role_display": [display.get(v) for v in values],
        },
    )


def _write_employment_mapping(path: Path, result) -> int:
    keys = list(result.mapping)
    return _write_table(
        path,
        {
            "company": [k[0] for k in keys],
            "title": [k[1] for k in keys],
            "employment_type": [result.mapping[k] for k in keys],
            "method": [result.method.get(k) for k in keys],
            "confidence": [result.confidence.get(k) for k in keys],
        },
    )


def _write_company_aliases(path: Path) -> int:
    rows = sorted(career_rules.ENTITY_ALIASES.items())
    return _write_table(
        path,
        {
            "company_id": [r[0] for r in rows],
            "canonical_company_id": [r[1] for r in rows],
        },
    )


def _quote(path: Path) -> str:
    return str(path).replace("'", "''")


def _connect(threads: int) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    return con


def build_mappings(out: Path, timings: list[StepTiming]) -> dict[str, Path]:
    mappings = out / "mappings"
    mappings.mkdir(parents=True, exist_ok=True)
    paths = {
        "edu_degree": mappings / "edu_degree.parquet",
        "edu_school": mappings / "edu_school.parquet",
        "edu_field": mappings / "edu_field.parquet",
        "career_company": mappings / "career_company.parquet",
        "career_company_alias": mappings / "career_company_id_alias.parquet",
        "career_employment_type": mappings / "career_employment_type.parquet",
        "career_title": mappings / "career_title.parquet",
        "career_occupation": mappings / "career_occupation.parquet",
    }

    with StepTimer("education degree mapping", timings):
        result = edu_final.run("degree", load_edu_vocab("degree"))
        rows = _write_value_mapping(paths["edu_degree"], result)
        timings[-1].rows = rows
        timings[-1].path = str(paths["edu_degree"])
        del result
        gc.collect()

    with StepTimer("education school mapping", timings):
        result = edu_final.run("title", load_edu_vocab("title"))
        rows = _write_value_mapping(paths["edu_school"], result)
        timings[-1].rows = rows
        timings[-1].path = str(paths["edu_school"])
        del result
        gc.collect()

    with StepTimer("education field mapping", timings):
        result = edu_final.run("field", load_edu_vocab("field"))
        rows = _write_value_mapping(paths["edu_field"], result)
        timings[-1].rows = rows
        timings[-1].path = str(paths["edu_field"])
        del result
        gc.collect()

    with StepTimer("career company mapping", timings):
        result = career_final.run("company", load_career_vocab("company"))
        rows = _write_value_mapping(paths["career_company"], result)
        timings[-1].rows = rows
        timings[-1].path = str(paths["career_company"])
        del result
        gc.collect()

    with StepTimer("career company id alias mapping", timings):
        rows = _write_company_aliases(paths["career_company_alias"])
        timings[-1].rows = rows
        timings[-1].path = str(paths["career_company_alias"])

    with StepTimer("career employment_type mapping", timings):
        result = career_final.run("employment_type", load_career_vocab("employment_type"))
        rows = _write_employment_mapping(paths["career_employment_type"], result)
        timings[-1].rows = rows
        timings[-1].path = str(paths["career_employment_type"])
        del result
        gc.collect()

    with StepTimer("career title mapping", timings):
        result = career_final.run("title", load_career_vocab("title"))
        rows = _write_title_mapping(paths["career_title"], result)
        timings[-1].rows = rows
        timings[-1].path = str(paths["career_title"])
        del result
        gc.collect()

    with StepTimer("career occupation mapping", timings):
        result = career_final.run("occupation", load_career_vocab("title"))
        rows = _write_value_mapping(paths["career_occupation"], result)
        timings[-1].rows = rows
        timings[-1].path = str(paths["career_occupation"])
        del result
        gc.collect()

    return paths


def write_education(out: Path, mappings: dict[str, Path], threads: int, timings: list[StepTiming]) -> None:
    dest = out / "education.parquet"
    con = _connect(threads)
    with StepTimer("normalized education table", timings):
        con.sql(f"""
            COPY (
              WITH base AS (
                SELECT
                  e.*,
                  regexp_extract(e.url, 'linkedin\\.com/school/([^/?#]+)', 1) AS row_school_slug
                FROM {EDU} e
              )
              SELECT
                b.linkedin_id,
                b.idx,
                b.title AS school_raw,
                CASE
                  WHEN b.row_school_slug <> '' THEN 'slug:' || b.row_school_slug
                  ELSE school.canonical_id
                END AS school_canonical_id,
                CASE
                  WHEN b.row_school_slug <> '' THEN b.row_school_slug
                  WHEN starts_with(school.canonical_id, 'slug:') THEN substr(school.canonical_id, 6)
                  ELSE NULL
                END AS school_slug,
                CASE WHEN b.row_school_slug <> '' THEN 'slug' ELSE school.method END AS school_method,
                CASE WHEN b.row_school_slug <> '' THEN 1.0 ELSE school.confidence END AS school_confidence,
                b.degree AS degree_raw,
                degree.canonical_id AS degree_canonical_id,
                degree.method AS degree_method,
                degree.confidence AS degree_confidence,
                b.field AS field_raw,
                field.canonical_id AS field_canonical_id,
                CASE WHEN starts_with(field.canonical_id, 'cip:') THEN substr(field.canonical_id, 5) ELSE NULL END AS cip_code,
                field.method AS field_method,
                field.confidence AS field_confidence,
                b.start_year,
                b.end_year,
                b.description,
                b.description_html,
                b.institute_logo_url,
                b.url
              FROM base b
              LEFT JOIN read_parquet('{_quote(mappings["edu_school"])}') school
                ON b.title IS NOT DISTINCT FROM school.value
              LEFT JOIN read_parquet('{_quote(mappings["edu_degree"])}') degree
                ON b.degree IS NOT DISTINCT FROM degree.value
              LEFT JOIN read_parquet('{_quote(mappings["edu_field"])}') field
                ON b.field IS NOT DISTINCT FROM field.value
            ) TO '{_quote(dest)}' (FORMAT parquet, COMPRESSION zstd)
        """)
        timings[-1].path = str(dest)
        timings[-1].rows = con.sql(f"SELECT count(*) FROM read_parquet('{_quote(dest)}')").fetchone()[0]
    con.close()


def write_career_steps(out: Path, mappings: dict[str, Path], threads: int, timings: list[StepTiming]) -> None:
    dest = out / "career_steps.parquet"
    con = _connect(threads)
    with StepTimer("normalized career_steps table", timings):
        con.sql(f"""
            COPY (
              WITH exp_parent AS (
                SELECT
                  linkedin_id,
                  experience_idx,
                  any_value(company) AS company,
                  any_value(company_id) AS company_id,
                  any_value(company_logo_url) AS company_logo_url,
                  any_value(url) AS url
                FROM {EXP}
                GROUP BY 1, 2
              ),
              steps AS (
                SELECT
                  'experience' AS source_table,
                  e.linkedin_id,
                  e.experience_idx,
                  CAST(NULL AS BIGINT) AS position_idx,
                  e.company,
                  e.company_id,
                  e.company_logo_url,
                  e.title,
                  e.subtitle,
                  e.subtitle_url,
                  e.location,
                  e.start_date,
                  e.end_date,
                  e.duration,
                  e.duration_short,
                  e.description,
                  e.description_html,
                  e.url
                FROM {EXP} e
                WHERE NOT EXISTS (
                  SELECT 1 FROM {POS} p
                  WHERE p.linkedin_id=e.linkedin_id
                    AND p.experience_idx=e.experience_idx
                )
                UNION ALL
                SELECT
                  'position' AS source_table,
                  e.linkedin_id,
                  e.experience_idx,
                  p.position_idx,
                  e.company,
                  e.company_id,
                  e.company_logo_url,
                  p.title,
                  p.subtitle,
                  CAST(NULL AS VARCHAR) AS subtitle_url,
                  p.location,
                  p.start_date,
                  p.end_date,
                  p.duration,
                  p.duration_short,
                  p.description,
                  p.description_html,
                  e.url
                FROM {POS} p
                LEFT JOIN exp_parent e
                  ON p.linkedin_id=e.linkedin_id
                 AND p.experience_idx=e.experience_idx
              )
              SELECT
                s.source_table,
                s.linkedin_id,
                s.experience_idx,
                s.position_idx,
                s.company AS company_raw,
                s.company_id AS company_id_raw,
                CASE
                  WHEN company.method = 'placeholder' THEN company.canonical_id
                  WHEN NULLIF(trim(s.company_id), '') IS NOT NULL
                    THEN 'id:' || coalesce(alias.canonical_company_id, s.company_id)
                  ELSE company.canonical_id
                END AS company_canonical_id,
                CASE
                  WHEN company.method = 'placeholder' THEN NULL
                  WHEN NULLIF(trim(s.company_id), '') IS NOT NULL
                    THEN coalesce(alias.canonical_company_id, s.company_id)
                  WHEN starts_with(company.canonical_id, 'id:') THEN substr(company.canonical_id, 4)
                  ELSE NULL
                END AS company_id_canonical,
                CASE
                  WHEN company.method = 'placeholder' THEN 'placeholder'
                  WHEN NULLIF(trim(s.company_id), '') IS NOT NULL THEN 'company_id'
                  ELSE company.method
                END AS company_method,
                CASE
                  WHEN company.method = 'placeholder' THEN 1.0
                  WHEN NULLIF(trim(s.company_id), '') IS NOT NULL THEN 1.0
                  ELSE company.confidence
                END AS company_confidence,
                employment.employment_type,
                employment.method AS employment_type_method,
                employment.confidence AS employment_type_confidence,
                s.title AS title_raw,
                title.canonical_id AS title_canonical_id,
                CASE WHEN starts_with(title.canonical_id, 'title:')
                  THEN regexp_extract(title.canonical_id, '^title:([^|]*)\\|', 1)
                  ELSE NULL
                END AS seniority_level,
                CASE WHEN starts_with(title.canonical_id, 'title:')
                  THEN regexp_extract(title.canonical_id, '^title:[^|]*\\|(.*)$', 1)
                  ELSE NULL
                END AS role_canonical,
                title.role_display,
                title.seniority_rank_token,
                title.method AS title_method,
                title.confidence AS title_confidence,
                occupation.canonical_id AS occupation_canonical_id,
                CASE WHEN starts_with(occupation.canonical_id, 'soc:') THEN substr(occupation.canonical_id, 5) ELSE NULL END AS occupation_code,
                occupation.method AS occupation_method,
                occupation.confidence AS occupation_confidence,
                s.subtitle,
                s.subtitle_url,
                s.location,
                s.start_date,
                s.end_date,
                s.duration,
                s.duration_short,
                s.description,
                s.description_html,
                s.company_logo_url,
                s.url
              FROM steps s
              LEFT JOIN read_parquet('{_quote(mappings["career_company"])}') company
                ON s.company IS NOT DISTINCT FROM company.value
              LEFT JOIN read_parquet('{_quote(mappings["career_company_alias"])}') alias
                ON s.company_id IS NOT DISTINCT FROM alias.company_id
              LEFT JOIN read_parquet('{_quote(mappings["career_employment_type"])}') employment
                ON s.company IS NOT DISTINCT FROM employment.company
               AND s.title IS NOT DISTINCT FROM employment.title
              LEFT JOIN read_parquet('{_quote(mappings["career_title"])}') title
                ON s.title IS NOT DISTINCT FROM title.value
              LEFT JOIN read_parquet('{_quote(mappings["career_occupation"])}') occupation
                ON s.title IS NOT DISTINCT FROM occupation.value
            ) TO '{_quote(dest)}' (FORMAT parquet, COMPRESSION zstd)
        """)
        timings[-1].path = str(dest)
        timings[-1].rows = con.sql(f"SELECT count(*) FROM read_parquet('{_quote(dest)}')").fetchone()[0]
    con.close()


def write_manifest(out: Path, timings: list[StepTiming], started_at: float, threads: int) -> None:
    manifest = {
        "created_at_epoch_s": time.time(),
        "runtime_s": round(time.monotonic() - started_at, 1),
        "threads": threads,
        "source": {
            "parsed_manifest": str(ROOT / "parsed" / "_manifest.json"),
            "education": EDU,
            "experience": EXP,
            "positions": POS,
        },
        "outputs": {
            "education": str(out / "education.parquet"),
            "career_steps": str(out / "career_steps.parquet"),
            "mappings": str(out / "mappings"),
        },
        "steps": [
            {
                "name": t.name,
                "runtime_s": round(t.runtime_s, 1),
                "rows": t.rows,
                "path": t.path,
            }
            for t in timings
        ],
    }
    (out / "_manifest.json").write_text(json.dumps(manifest, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "normalized")
    parser.add_argument("--force", action="store_true", help="replace an existing output directory")
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = args.out.resolve()
    if out.exists():
        if not args.force:
            raise SystemExit(f"{out} already exists; rerun with --force to replace it")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    started = time.monotonic()
    timings: list[StepTiming] = []
    mappings = build_mappings(out, timings)
    write_education(out, mappings, args.threads, timings)
    write_career_steps(out, mappings, args.threads, timings)
    write_manifest(out, timings, started, args.threads)
    print(f"[build] wrote {out}", flush=True)


if __name__ == "__main__":
    main()
