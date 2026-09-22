"""Build the value-level co-major mapping over every distinct field string (spec P3).

    uv run python -m edu_clean.run_comajors

Reads normalized/mappings/edu_field.parquet (value, method) and writes
normalized/mappings/edu_field_components.parquet:

    value, method, status (single|split|unresolved|empty), marker_class (plain|marker),
    components (JSON list of {text, role, cip}), n_majors, n_minors, n_concentrations,
    major_cips (VARCHAR[]), minor_cip, concentration_cip,
    nha_level_minor (NHA level of the minor's CIP, 0 = none)

Which major is primary is a per-ROW decision made by apply_comajors (it depends on the
row's cip2_pooled). Stats to edu_clean/results/comajors_stats.json.
"""
from __future__ import annotations

import json
import time
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from edu_clean import comajors as CM
from edu_clean import humanities as H

ROOT = Path(__file__).resolve().parent.parent
FIELD_MAP = ROOT / "normalized" / "mappings" / "edu_field.parquet"
EDUCATION = ROOT / "normalized" / "education.parquet"
OUT = ROOT / "normalized" / "mappings" / "edu_field_components.parquet"
STATS = ROOT / "edu_clean" / "results" / "comajors_stats.json"
CHUNK = 20_000


def _work(items: list[tuple[str, str]]) -> list[dict]:
    out = []
    for value, method in items:
        s = CM.split_field(value, method)
        comps = [{"text": c.text, "role": c.role, "cip": c.cip} for c in s.components]
        mn = CM.minor(s)
        out.append({
            "value": value, "method": method, "status": s.status, "marker_class": s.marker_class,
            "components": json.dumps(comps, ensure_ascii=False),
            "n_majors": sum(1 for c in s.components if c.role == "major" and c.cip),
            "n_minors": sum(1 for c in s.components if c.role == "minor" and c.cip),
            "n_concentrations": sum(1 for c in s.components if c.role == "concentration" and c.cip),
            "major_cips": CM.majors(s) if s.status == "split" else [],
            "minor_cip": mn if s.status == "split" else None,
            "concentration_cip": CM.concentration(s) if s.status == "split" else None,
            "nha_level_minor": H.classify_cip(mn).level if (s.status == "split" and mn) else 0,
        })
    return out


def main() -> None:
    t0 = time.time()
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    items = con.execute(f"SELECT value, method FROM read_parquet('{FIELD_MAP}')").fetchall()
    chunks = [items[i:i + CHUNK] for i in range(0, len(items), CHUNK)]
    rows: list[dict] = []
    with Pool(16) as pool:
        for part in pool.imap(_work, chunks, chunksize=1):
            rows.extend(part)
    t = pa.Table.from_pylist(rows, schema=pa.schema([
        ("value", pa.string()), ("method", pa.string()), ("status", pa.string()),
        ("marker_class", pa.string()), ("components", pa.string()), ("n_majors", pa.int32()),
        ("n_minors", pa.int32()), ("n_concentrations", pa.int32()),
        ("major_cips", pa.list_(pa.string())), ("minor_cip", pa.string()),
        ("concentration_cip", pa.string()), ("nha_level_minor", pa.int32())]))
    pq.write_table(t, OUT, compression="zstd")
    # row-weighted status distribution
    con.execute(f"CREATE VIEW m AS SELECT * FROM read_parquet('{OUT}')")
    dist = con.execute(f"""
        SELECT m.status, m.marker_class, count(*) AS rows, count(DISTINCT m.value) AS strings
        FROM read_parquet('{EDUCATION}') e JOIN m ON m.value = e.field_raw
        WHERE NOT e.is_duplicate GROUP BY 1, 2 ORDER BY 3 DESC""").fetchall()
    stats = {"generated": date.today().isoformat(), "values": t.num_rows, "runtime_s": round(time.time() - t0, 1),
             "row_weighted": [{"status": a, "marker_class": b, "rows": c, "strings": d} for a, b, c, d in dist]}
    STATS.parent.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps(stats, indent=1) + "\n")
    print(f"wrote {OUT} ({t.num_rows:,} values) in {stats['runtime_s']}s")
    for d in stats["row_weighted"]:
        print(f"  {d['status']:11s} {d['marker_class']:7s} rows={d['rows']:>9,} strings={d['strings']:>8,}")


if __name__ == "__main__":
    main()
