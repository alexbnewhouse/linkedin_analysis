"""Materialize row-level normalized education and career production tables.

Run with:

    uv run --with numpy python build_normalized.py            # full build
    uv run --with numpy python build_normalized.py --sections career

(numpy is needed by the DuckDB python UDF that applies the canonical
description normalizer; everything else runs on the base dependency group.)

Every output file is written to a temp name and atomically renamed, so
concurrent readers of normalized/*.parquet never see a partial file.

Outputs:

    normalized/
      _manifest.json
      education.parquet
      education_person.parquet
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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from career_clean import approach_a_rules as career_rules
from career_clean import final_hybrid as career_final
from career_clean import location as career_location
from career_clean import occupation as career_occupation
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


def _replace(tmp: Path, dest: Path) -> None:
    """Atomic publish: concurrent readers see the old file or the new file,
    never a partially-written one."""
    os.replace(tmp, dest)


def _write_table(path: Path, columns: dict[str, list[Any]]) -> int:
    table = pa.table(columns)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    _replace(tmp, path)
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
    (finding 2: extended rank lexicon, separate from the canonical),
    ``role_display`` (finding 5: human-readable label per role canonical), and
    the value-level employment signals (finding 7: employment_type is a pure
    function of these + the company placeholder bucket, so it is resolved
    inline in the career_steps SQL instead of via a pair-grain mapping --
    verified bit-identical on all 9,337,517 (company, title) pairs)."""
    values = list(result.mapping)
    rank = result.aux.get("seniority_rank_token", {})
    display = result.aux.get("role_display", {})
    status, solo, owner = [], [], []
    for v in values:
        bucket = career_rules.title_status_bucket(v)
        status.append(career_rules.placeholder_to_employment(bucket) if bucket else None)
        solo.append(career_rules.title_has_solo_marker(v))
        owner.append(career_rules.title_has_owner_marker(v))
    return _write_table(
        path,
        {
            "value": values,
            "canonical_id": [result.mapping[v] for v in values],
            "method": [result.method.get(v) for v in values],
            "confidence": [result.confidence.get(v) for v in values],
            "seniority_rank_token": [rank.get(v) for v in values],
            "role_display": [display.get(v) for v in values],
            "employment_status": status,
            "employment_solo": solo,
            "employment_owner": owner,
        },
    )


def _write_location_mapping(path: Path, threads: int) -> int:
    """Finding 6: deterministic head gazetteer over the distinct raw location
    vocabulary (country -> US state -> city/metro; ~90% of populated rows
    parse). Value-keyed like the other mappings; the raw string stays on
    career_steps untouched."""
    con = _connect(threads)
    values = [r[0] for r in con.sql(f"""
        SELECT DISTINCT location FROM (
          SELECT location FROM {EXP}
          UNION ALL
          SELECT location FROM {POS}
        ) WHERE location IS NOT NULL AND trim(location) <> ''
    """).fetchall()]
    con.close()
    parsed = [career_location.parse_location(v) for v in values]
    return _write_table(
        path,
        {
            "value": values,
            "country": [p[0] for p in parsed],
            "us_state": [p[1] for p in parsed],
            "city": [p[2] for p in parsed],
            "method": [p[3] for p in parsed],
            "confidence": [p[4] for p in parsed],
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


def build_mappings(out: Path, timings: list[StepTiming], sections: str = "all") -> dict[str, Path]:
    mappings = out / "mappings"
    mappings.mkdir(parents=True, exist_ok=True)
    paths = {
        "edu_degree": mappings / "edu_degree.parquet",
        "edu_school": mappings / "edu_school.parquet",
        "edu_field": mappings / "edu_field.parquet",
        "career_company": mappings / "career_company.parquet",
        "career_company_alias": mappings / "career_company_id_alias.parquet",
        "career_title": mappings / "career_title.parquet",
        "career_occupation": mappings / "career_occupation.parquet",
        "career_functional_cluster": mappings / "career_functional_cluster.parquet",
        "career_location": mappings / "career_location.parquet",
    }

    if sections in ("all", "education"):
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

    if sections == "education":
        return paths

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

    # NOTE: employment_type intentionally has NO mapping step. It is a pure
    # function of value-level signals (title status/solo/owner markers, written
    # onto the title mapping below; company placeholder bucket, already on the
    # company mapping) and is resolved inline in the career_steps SQL. The
    # former (company, title) pair-grain mapping was the build's long pole
    # (558.7s of 925.3s) and its 9.34M keys were near row grain; the inline
    # resolution was verified identical on every pair (2026-06-10 audit, f.7).
    legacy_employment = mappings / "career_employment_type.parquet"
    if legacy_employment.exists():
        legacy_employment.unlink()  # superseded; the build no longer wipes the dir
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

    with StepTimer("career location mapping", timings):
        rows = _write_location_mapping(paths["career_location"], os.cpu_count() or 1)
        timings[-1].rows = rows
        timings[-1].path = str(paths["career_location"])
        gc.collect()

    return paths


def build_functional_cluster_mapping(
    mappings: dict[str, Path], threads: int, timings: list[StepTiming]
) -> None:
    """Finding 3: materialize the evaluated SE functional cluster row-level.

    The cluster axis (SOC major group + honest ``*_unspecified`` residue) is
    scoped to the self-employment population -- its title-keyword and
    company-brand recs are only safe there (see career_clean/se_cluster.py) --
    so this pass selects rows whose inline employment type resolves to
    self_employed/business_owner and runs the production entry point
    ``final_hybrid.canon_functional_cluster_value`` (SOC -> qualifier ->
    title keyword -> company brand -> description -> residue) on each.
    Descriptions are row-grain, hence a row-keyed mapping rather than a
    value-keyed one (the pattern occupation uses)."""
    dest = mappings["career_functional_cluster"]
    con = _connect(threads)
    with StepTimer("career functional cluster mapping (self-employment rows)", timings):
        cur = con.execute(f"""
            {_CAREER_STEPS_CTE}
            SELECT
              s.source_table, s.linkedin_id, s.experience_idx, s.position_idx,
              s.company, s.company_id, s.title, s.description
            FROM steps s
            LEFT JOIN read_parquet('{_quote(mappings["career_company"])}') company
              ON s.company IS NOT DISTINCT FROM company.value
            LEFT JOIN read_parquet('{_quote(mappings["career_title"])}') title
              ON s.title IS NOT DISTINCT FROM title.value
            WHERE {_EMPLOYMENT_TYPE_SQL} IN ('self_employed', 'business_owner')
        """)
        onet_index = career_occupation.load_onet()[:2]
        keys: set[tuple] = set()
        cols: dict[str, list[Any]] = {
            "source_table": [], "linkedin_id": [], "experience_idx": [],
            "position_idx": [], "functional_cluster": [],
            "functional_cluster_method": [], "functional_cluster_confidence": [],
        }
        while True:
            batch = cur.fetchmany(50_000)
            if not batch:
                break
            for src, lid, eidx, pidx, comp, cid, title, desc in batch:
                key = (src, lid, eidx, pidx)
                if key in keys:  # rare duplicate parsed keys: keep-first
                    continue
                keys.add(key)
                cluster, fc_method, fc_conf = career_final.canon_functional_cluster_value(
                    company=comp, title=title,
                    company_id=(cid.strip() if cid and cid.strip() else None),
                    description=desc, onet_index=onet_index,
                )
                cols["source_table"].append(src)
                cols["linkedin_id"].append(lid)
                cols["experience_idx"].append(eidx)
                cols["position_idx"].append(pidx)
                cols["functional_cluster"].append(cluster)
                cols["functional_cluster_method"].append(fc_method)
                cols["functional_cluster_confidence"].append(fc_conf)
        rows = _write_table(dest, cols)
        timings[-1].rows = rows
        timings[-1].path = str(dest)
    con.close()
    gc.collect()


def write_education(out: Path, mappings: dict[str, Path], threads: int, timings: list[StepTiming]) -> None:
    """Row-level education table.

    Audit findings implemented here:
      2: degree->field cross-pass -- a degree cell that is actually a field of
         study backfills `field_*` (method 'cip_from_degree') when the field
         cell itself carries no signal (NULL or nullish/junk).
      4: typed output -- SMALLINT years, `cip2`/`cip4` rollups, sortable
         `degree_level` ordinal + `degree_type`, materialized NHA flags
         (`nha_level`, `humanities_field_group`).
      5: `in_progress` (end_year beyond the data snapshot) and `is_duplicate`
         (within-profile exact repeat, keep-first) flags.
    """
    dest = out / "education.parquet"
    tmp = dest.with_name(dest.name + ".tmp")
    nha = ROOT / "reference" / "cip_humanities.parquet"
    con = _connect(threads)
    with StepTimer("normalized education table", timings):
        con.sql(f"""
            COPY (
              WITH base AS (
                SELECT
                  e.*,
                  regexp_extract(e.url, 'linkedin\\.com/school/([^/?#]+)', 1) AS row_school_slug
                FROM {EDU} e
              ),
              joined AS (
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
                  -- finding 2: backfill only when the field cell has no signal
                  (dfield.canonical_id IS NOT NULL
                    AND (field.canonical_id IS NULL
                         OR field.canonical_id = 'field_raw:__blank__')) AS field_from_degree,
                  field.canonical_id AS field_join_canonical_id,
                  field.method AS field_join_method,
                  field.confidence AS field_join_confidence,
                  dfield.canonical_id AS dfield_canonical_id,
                  TRY_CAST(b.start_year AS SMALLINT) AS start_year,
                  TRY_CAST(b.end_year AS SMALLINT) AS end_year,
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
                LEFT JOIN read_parquet('{_quote(mappings["edu_degree_field"])}') dfield
                  ON b.degree IS NOT DISTINCT FROM dfield.value
              ),
              shaped AS (
                SELECT
                  j.linkedin_id,
                  j.idx,
                  j.school_raw,
                  j.school_canonical_id,
                  j.school_slug,
                  j.school_method,
                  j.school_confidence,
                  j.degree_raw,
                  j.degree_canonical_id,
                  CAST({_DEGREE_LEVEL_CASE} AS TINYINT) AS degree_level,
                  CASE
                    WHEN j.degree_canonical_id IS NOT NULL
                     AND NOT starts_with(j.degree_canonical_id, 'degree_raw:')
                    THEN split_part(j.degree_canonical_id, ':', 2)
                  END AS degree_type,
                  j.degree_method,
                  j.degree_confidence,
                  j.field_raw,
                  CASE WHEN j.field_from_degree THEN j.dfield_canonical_id
                       ELSE j.field_join_canonical_id END AS field_canonical_id,
                  CASE WHEN j.field_from_degree THEN 'cip_from_degree'
                       ELSE j.field_join_method END AS field_method,
                  CASE WHEN j.field_from_degree THEN 0.9
                       ELSE j.field_join_confidence END AS field_confidence,
                  j.start_year,
                  j.end_year,
                  j.description,
                  j.description_html,
                  j.institute_logo_url,
                  j.url
                FROM joined j
              ),
              final AS (
                SELECT
                  s.*,
                  CASE WHEN starts_with(s.field_canonical_id, 'cip:')
                       THEN substr(s.field_canonical_id, 5) END AS cip_code
                FROM shaped s
              )
              SELECT
                f.linkedin_id,
                f.idx,
                f.school_raw,
                f.school_canonical_id,
                f.school_slug,
                f.school_method,
                f.school_confidence,
                f.degree_raw,
                f.degree_canonical_id,
                f.degree_level,
                f.degree_type,
                f.degree_method,
                f.degree_confidence,
                f.field_raw,
                f.field_canonical_id,
                f.cip_code,
                -- finding 4: granularity rollups (cip_code is mixed 2/4/6-digit)
                CASE WHEN f.cip_code IS NOT NULL
                     THEN split_part(f.cip_code, '.', 1) END AS cip2,
                CASE WHEN length(split_part(f.cip_code, '.', 2)) >= 2
                     THEN split_part(f.cip_code, '.', 1) || '.' ||
                          left(split_part(f.cip_code, '.', 2), 2) END AS cip4,
                f.field_method,
                f.field_confidence,
                CAST(nha.nha_level AS TINYINT) AS nha_level,
                nha.humanities_field_group,
                f.start_year,
                f.end_year,
                coalesce(f.end_year > {EDU_SNAPSHOT_YEAR}, FALSE) AS in_progress,
                -- finding 5: exact within-profile repeats, keep-first
                (row_number() OVER (
                   PARTITION BY f.linkedin_id, f.school_raw, f.degree_raw,
                                f.field_raw, f.start_year, f.end_year
                   ORDER BY f.idx
                 ) > 1) AS is_duplicate,
                f.description,
                f.description_html,
                f.institute_logo_url,
                f.url
              FROM final f
              LEFT JOIN read_parquet('{_quote(nha)}') nha
                ON f.cip_code = nha.cip_code
            ) TO '{_quote(tmp)}' (FORMAT parquet, COMPRESSION zstd)
        """)
        _replace(tmp, dest)
        timings[-1].path = str(dest)
        timings[-1].rows = con.sql(f"SELECT count(*) FROM read_parquet('{_quote(dest)}')").fetchone()[0]
    con.close()


def write_education_person(out: Path, threads: int, timings: list[StepTiming]) -> None:
    """Person-level education rollup (audit finding 1, HIGH).

    One row per profile with the columns every planned education-aware
    analysis needs without re-deriving them:

      highest_degree_level / highest_degree_year  -- max ordinal + the latest
          end_year among rows at that level
      bachelor_end_year  -- earliest end_year on the bachelor rung (ordinal 4:
          bachelor/undergraduate), the cohort "graduation" anchor
      any_end_year_min / any_end_year_max  -- credential-agnostic bounds
          (the old cohorts join semantics, preserved as explicit columns)
      cip_code/cip2/cip4 + nha_level/humanities_field_group  -- the *terminal*
          field of study: the CIP-coded row with the highest degree level,
          breaking ties by latest end_year
      school_slug  -- primary institution, chosen the same way among rows
          with a slug
      n_edu_rows  -- deduplicated credential rows (is_duplicate excluded
          everywhere here)
    """
    src = out / "education.parquet"
    dest = out / "education_person.parquet"
    tmp = dest.with_name(dest.name + ".tmp")
    con = _connect(threads)
    with StepTimer("normalized education_person rollup", timings):
        con.sql(f"""
            COPY (
              WITH e AS (
                SELECT * FROM read_parquet('{_quote(src)}')
                WHERE NOT is_duplicate
              ),
              agg AS (
                SELECT
                  linkedin_id,
                  count(*) AS n_edu_rows,
                  max(degree_level) AS highest_degree_level,
                  min(end_year) FILTER (WHERE degree_level = 4) AS bachelor_end_year,
                  min(end_year) AS any_end_year_min,
                  max(end_year) AS any_end_year_max
                FROM e GROUP BY 1
              ),
              highest_year AS (
                SELECT e.linkedin_id, max(e.end_year) AS highest_degree_year
                FROM e
                JOIN agg a ON e.linkedin_id = a.linkedin_id
                          AND e.degree_level = a.highest_degree_level
                GROUP BY 1
              ),
              terminal AS (
                SELECT linkedin_id, cip_code, cip2, cip4, nha_level, humanities_field_group
                FROM e WHERE cip_code IS NOT NULL
                QUALIFY row_number() OVER (
                  PARTITION BY linkedin_id
                  ORDER BY degree_level DESC NULLS LAST, end_year DESC NULLS LAST, idx
                ) = 1
              ),
              school AS (
                SELECT linkedin_id, school_slug
                FROM e WHERE school_slug IS NOT NULL
                QUALIFY row_number() OVER (
                  PARTITION BY linkedin_id
                  ORDER BY degree_level DESC NULLS LAST, end_year DESC NULLS LAST, idx
                ) = 1
              )
              SELECT
                a.linkedin_id,
                a.n_edu_rows,
                a.highest_degree_level,
                h.highest_degree_year,
                a.bachelor_end_year,
                a.any_end_year_min,
                a.any_end_year_max,
                t.cip_code,
                t.cip2,
                t.cip4,
                t.nha_level,
                t.humanities_field_group,
                s.school_slug
              FROM agg a
              LEFT JOIN highest_year h USING (linkedin_id)
              LEFT JOIN terminal t USING (linkedin_id)
              LEFT JOIN school s USING (linkedin_id)
            ) TO '{_quote(tmp)}' (FORMAT parquet, COMPRESSION zstd)
        """)
        _replace(tmp, dest)
        timings[-1].path = str(dest)
        timings[-1].rows = con.sql(f"SELECT count(*) FROM read_parquet('{_quote(dest)}')").fetchone()[0]
    con.close()


# Row-grain career-step source: single-role experiences + position children
# (the grouped-position data-model fact; see career_clean/PLAN.md §1). Shared by
# write_career_steps and the functional-cluster mapping pass.
# finding 4: description_html / company_logo_url / url / subtitle / subtitle_url
# are intentionally NOT carried (43% of the old file, zero downstream readers);
# they remain in parsed/ for re-joins on (linkedin_id, experience_idx[,
# position_idx]).
_CAREER_STEPS_CTE = f"""
              WITH exp_parent AS (
                SELECT
                  linkedin_id,
                  experience_idx,
                  any_value(company) AS company,
                  any_value(company_id) AS company_id
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
                  e.title,
                  e.location,
                  e.start_date,
                  e.end_date,
                  e.duration,
                  e.duration_short,
                  e.description
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
                  p.title,
                  p.location,
                  p.start_date,
                  p.end_date,
                  p.duration,
                  p.duration_short,
                  p.description
                FROM {POS} p
                LEFT JOIN exp_parent e
                  ON p.linkedin_id=e.linkedin_id
                 AND p.experience_idx=e.experience_idx
              )
"""

# Inline employment-type resolution (finding 7). A pure function of the
# value-level signals on the company/title mappings; precedence mirrors
# career_clean.approach_a_rules.resolve_employment_type exactly (title status ->
# company placeholder -> solo marker -> owner marker -> employee) and was
# verified bit-identical on all 9,337,517 distinct (company, title) pairs.
# Expects the join aliases `company` and `title`.
_EMPLOYMENT_TYPE_SQL = """
                CASE
                  WHEN title.employment_status IS NOT NULL THEN title.employment_status
                  WHEN company.method = 'placeholder' THEN
                    CASE WHEN company.canonical_id = 'nonorg:none' THEN 'unknown'
                         ELSE substr(company.canonical_id, 8) END
                  WHEN coalesce(title.employment_solo, FALSE) THEN 'self_employed'
                  WHEN coalesce(title.employment_owner, FALSE) THEN 'business_owner'
                  ELSE 'employee'
                END
"""


def write_career_steps(out: Path, mappings: dict[str, Path], threads: int, timings: list[StepTiming]) -> None:
    dest = out / "career_steps.parquet"
    tmp = dest.with_name(dest.name + ".tmp")
    con = _connect(threads)
    # Stored description is NFKC-normalized (finding 4) via the canonical
    # career_clean normalizer, registered as a scalar UDF so the SQL path and
    # the Python path can never diverge. (DuckDB python UDFs need numpy --
    # hence the `--with numpy` in the run command.)
    try:
        con.create_function(
            "normalize_description", career_final.normalize_description,
            ["VARCHAR"], "VARCHAR",
        )
    except Exception as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            "registering the normalize_description UDF failed -- run as "
            "`uv run --with numpy python build_normalized.py` "
            f"(DuckDB python UDFs require numpy): {exc}"
        ) from exc
    with StepTimer("normalized career_steps table", timings):
        con.sql(f"""
            COPY (
              {_CAREER_STEPS_CTE}
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
                -- employment axis: resolved inline (finding 7), see
                -- _EMPLOYMENT_TYPE_SQL.
                {_EMPLOYMENT_TYPE_SQL} AS employment_type,
                CASE
                  WHEN title.employment_status IS NOT NULL THEN 'title_status'
                  WHEN company.method = 'placeholder' THEN 'company_placeholder'
                  WHEN coalesce(title.employment_solo, FALSE) THEN 'title_solo_marker'
                  WHEN coalesce(title.employment_owner, FALSE) THEN 'title_owner_marker'
                  ELSE 'default_employee'
                END AS employment_type_method,
                CAST(CASE
                  WHEN title.employment_status IS NOT NULL THEN 1.0
                  WHEN company.method = 'placeholder' THEN 1.0
                  WHEN coalesce(title.employment_solo, FALSE) THEN 0.95
                  WHEN coalesce(title.employment_owner, FALSE) THEN 0.9
                  ELSE 0.8
                END AS DOUBLE) AS employment_type_confidence,
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
                -- finding 3: SE functional cluster (SOC major group or honest
                -- *_unspecified residue), resolved row-level for the
                -- self-employment population only; NULL elsewhere.
                fc.functional_cluster,
                fc.functional_cluster_method,
                fc.functional_cluster_confidence,
                s.location,
                -- finding 6: deterministic location gazetteer (head coverage,
                -- ~90% of populated rows); raw string above stays untouched.
                loc.country AS location_country,
                loc.us_state AS location_us_state,
                loc.city AS location_city,
                loc.method AS location_method,
                s.start_date,
                s.end_date,
                s.duration,
                s.duration_short,
                normalize_description(s.description) AS description,
                -- finding 7: identical (person, company, title, start, end)
                -- repeats (0.32% of rows) are flagged, keep-first, so spurious
                -- self-loop transitions can be filtered without dropping data.
                (row_number() OVER (
                   PARTITION BY s.linkedin_id, s.company, s.title,
                                s.start_date, s.end_date
                   ORDER BY s.source_table, s.experience_idx,
                            s.position_idx NULLS FIRST
                 ) > 1) AS is_duplicate
              FROM steps s
              LEFT JOIN read_parquet('{_quote(mappings["career_company"])}') company
                ON s.company IS NOT DISTINCT FROM company.value
              LEFT JOIN read_parquet('{_quote(mappings["career_company_alias"])}') alias
                ON s.company_id IS NOT DISTINCT FROM alias.company_id
              LEFT JOIN read_parquet('{_quote(mappings["career_title"])}') title
                ON s.title IS NOT DISTINCT FROM title.value
              LEFT JOIN read_parquet('{_quote(mappings["career_occupation"])}') occupation
                ON s.title IS NOT DISTINCT FROM occupation.value
              LEFT JOIN read_parquet('{_quote(mappings["career_functional_cluster"])}') fc
                ON s.source_table = fc.source_table
               AND s.linkedin_id = fc.linkedin_id
               AND s.experience_idx = fc.experience_idx
               AND s.position_idx IS NOT DISTINCT FROM fc.position_idx
              LEFT JOIN read_parquet('{_quote(mappings["career_location"])}') loc
                ON s.location IS NOT DISTINCT FROM loc.value
            ) TO '{_quote(tmp)}' (FORMAT parquet, COMPRESSION zstd)
        """)
        _replace(tmp, dest)
        timings[-1].path = str(dest)
        timings[-1].rows = con.sql(f"SELECT count(*) FROM read_parquet('{_quote(dest)}')").fetchone()[0]
    con.close()


def write_manifest(
    out: Path, timings: list[StepTiming], started_at: float, threads: int, sections: str = "all"
) -> None:
    manifest = {
        "created_at_epoch_s": time.time(),
        "runtime_s": round(time.monotonic() - started_at, 1),
        "threads": threads,
        "sections": sections,
        "source": {
            "parsed_manifest": str(ROOT / "parsed" / "_manifest.json"),
            "education": EDU,
            "experience": EXP,
            "positions": POS,
        },
        "outputs": {
            "education": str(out / "education.parquet"),
            "education_person": str(out / "education_person.parquet"),
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
    tmp = out / "_manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2))
    _replace(tmp, out / "_manifest.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "normalized")
    parser.add_argument(
        "--force", action="store_true",
        help="deprecated no-op: outputs are now replaced atomically in place "
             "(the directory is never wiped, so propose-only artifacts survive)",
    )
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    parser.add_argument(
        "--sections", choices=("all", "career", "education"), default="all",
        help="rebuild only one side of the output (mappings + table)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    timings: list[StepTiming] = []
    mappings = build_mappings(out, timings, args.sections)
    if args.sections in ("all", "education"):
        write_education(out, mappings, args.threads, timings)
        write_education_person(out, args.threads, timings)
    if args.sections in ("all", "career"):
        build_functional_cluster_mapping(mappings, args.threads, timings)
        write_career_steps(out, mappings, args.threads, timings)
    write_manifest(out, timings, started, args.threads, args.sections)
    print(f"[build] wrote {out}", flush=True)


if __name__ == "__main__":
    main()
