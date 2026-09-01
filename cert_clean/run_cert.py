"""Build the certifications skills axis (audit R6).

    uv run python -m cert_clean.run_cert

Outputs (atomic replace, manifest alongside):

  normalized/mappings/cert_domain.parquet   value-keyed: raw title -> domain,
                                            method ('curated'|'keyword'), confidence
  normalized/certifications_person.parquet  person grain: n_certs, has_<domain>
                                            bools, domain list, top_domain

Purely deterministic (curated head + keyword rules); the raw title is never
altered. Coverage stats land in normalized/_cert_manifest.json.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from cert_clean.domains import DOMAINS, classify

ROOT = Path(__file__).resolve().parent.parent
CERTS = f"read_parquet('{ROOT}/parsed/certifications/*.parquet')"
MAPPING = ROOT / "normalized" / "mappings" / "cert_domain.parquet"
PERSON = ROOT / "normalized" / "certifications_person.parquet"
MANIFEST = ROOT / "normalized" / "_cert_manifest.json"


def _replace(tmp: Path, dest: Path) -> None:
    os.replace(tmp, dest)


def build_mapping(con) -> dict:
    rows = con.sql(
        f"SELECT title, count(*) c FROM {CERTS} "
        f"WHERE title IS NOT NULL AND trim(title) <> '' GROUP BY 1"
    ).fetchall()
    titles, domains, methods, confs = [], [], [], []
    covered = total = 0
    for title, c in rows:
        dom, method, conf = classify(title)
        titles.append(title)
        domains.append(dom)
        methods.append(method)
        confs.append(conf)
        total += c
        if dom is not None:
            covered += c
    table = pa.table(
        {"value": titles, "domain": domains, "method": methods, "confidence": confs}
    )
    tmp = MAPPING.with_name(MAPPING.name + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    _replace(tmp, MAPPING)
    return {
        "distinct_titles": len(titles),
        "row_coverage_pct": round(100.0 * covered / max(total, 1), 2),
        "rows_total": total,
        "rows_covered": covered,
    }


def build_person(con) -> int:
    has_cols = ",\n".join(
        f"        coalesce(bool_or(m.domain = '{d}'), FALSE) AS has_{d}"
        for d in DOMAINS
        if d != "other"
    )
    tmp = PERSON.with_name(PERSON.name + ".tmp")
    con.sql(f"""
        COPY (
          SELECT
            c.linkedin_id,
            count(*) AS n_certs,
            count(m.domain) AS n_certs_classified,
            list_distinct(list(m.domain) FILTER (WHERE m.domain IS NOT NULL))
              AS domains,
            -- modal classified domain, ties broken alphabetically
            (SELECT m2.domain FROM {CERTS} c2
              JOIN read_parquet('{MAPPING}') m2 ON c2.title = m2.value
              WHERE c2.linkedin_id = c.linkedin_id AND m2.domain IS NOT NULL
              GROUP BY m2.domain ORDER BY count(*) DESC, m2.domain LIMIT 1)
              AS top_domain,
{has_cols}
          FROM {CERTS} c
          LEFT JOIN read_parquet('{MAPPING}') m ON c.title = m.value
          WHERE c.title IS NOT NULL AND trim(c.title) <> ''
          GROUP BY c.linkedin_id
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)
    """)
    _replace(tmp, PERSON)
    return con.sql(f"SELECT count(*) FROM read_parquet('{PERSON}')").fetchone()[0]


def main() -> None:
    started = time.monotonic()
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={os.cpu_count() or 1}")
    stats = build_mapping(con)
    persons = build_person(con)
    report = {
        "generated": date.today().isoformat(),
        "runtime_s": round(time.monotonic() - started, 1),
        "mapping": stats,
        "persons": persons,
        "outputs": {"mapping": str(MAPPING), "person": str(PERSON)},
    }
    MANIFEST.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
