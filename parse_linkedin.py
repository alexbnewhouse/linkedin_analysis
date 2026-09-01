"""Parse raw LinkedIn profile JSONL snapshots into an analysis-ready Parquet
star schema -- all in one self-contained script.

The raw data is one JSON object per line, where each object is a LinkedIn
profile containing scalar fields, a nested ``current_company`` object, and many
one-to-many nested lists (education, experience, ...). One of those lists,
``experience``, itself contains a nested ``positions`` list.

We flatten this into a classic star schema:

* ``profiles``  - one row per profile (scalars + flattened current_company)
* child tables  - one row per element of each nested list, linked back to the
                  profile by ``linkedin_id``

Each input file is parsed by its own worker process (embarrassingly parallel),
streaming line by line so memory stays bounded regardless of input size. Every
worker writes one Parquet shard per table; because all workers share the
schemas defined below, the shards for a table read back as a single dataset
(e.g. with ``pyarrow.dataset`` or DuckDB).

Usage:
    uv run python parse_linkedin.py                 # parse ./data -> ./parsed
    uv run python parse_linkedin.py --help          # options
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import orjson
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_EVERY = 25_000

# ==========================================================================
# Schema: the single source of truth for every table and column.
# ==========================================================================

# Logical column types. We keep the vocabulary tiny on purpose: the raw data
# only ever uses strings, integers and booleans (everything else is null).
STR = "str"
INT = "int"
BOOL = "bool"

_ARROW_TYPE = {
    STR: pa.string(),
    INT: pa.int64(),
    BOOL: pa.bool_(),
}


@dataclass(frozen=True)
class Column:
    """A single output column.

    ``name`` is the output column name. ``source`` is the key to read from the
    raw record (defaults to ``name`` when omitted). ``kind`` selects coercion
    and the resulting Arrow type.
    """

    name: str
    kind: str = STR
    source: str | None = None

    @property
    def src_key(self) -> str:
        return self.source or self.name

    @property
    def arrow_field(self) -> pa.Field:
        return pa.field(self.name, _ARROW_TYPE[self.kind])


@dataclass(frozen=True)
class ListTable:
    """A child table built from a top-level list of dicts on each profile.

    ``link_columns`` are the foreign-key/index columns prepended to every row
    (e.g. ``linkedin_id`` + ``idx``); ``columns`` are pulled from each list
    element by key.
    """

    name: str
    source: str  # top-level key holding the list on each profile
    columns: list[Column]
    link_columns: list[Column] = field(
        default_factory=lambda: [
            Column("linkedin_id", STR),
            Column("idx", INT),
        ]
    )

    @property
    def arrow_schema(self) -> pa.Schema:
        cols = self.link_columns + self.columns
        return pa.schema([c.arrow_field for c in cols])


# --------------------------------------------------------------------------
# profiles: one row per profile.
#
# Scalar top-level fields plus the flattened ``current_company`` object. The
# raw data also carries pre-flattened ``current_company_name`` /
# ``current_company_company_id`` mirrors, which we keep verbatim for fidelity.
# --------------------------------------------------------------------------
PROFILE_COLUMNS: list[Column] = [
    # Identity
    Column("linkedin_id", STR),
    Column("linkedin_num_id", STR),
    Column("id", STR),
    Column("name", STR),
    Column("first_name", STR),
    Column("last_name", STR),
    # Headline / bio
    Column("about", STR),
    Column("position", STR),
    Column("educations_details", STR),
    # Location
    Column("city", STR),
    Column("location", STR),
    Column("country_code", STR),
    # Metrics
    Column("connections", INT),
    Column("followers", INT),
    Column("recommendations_count", INT),
    # Flags
    Column("influencer", BOOL),
    Column("default_avatar", BOOL),
    Column("memorialized_account", BOOL),
    # Media / links
    Column("avatar", STR),
    Column("banner_image", STR),
    Column("input_url", STR),
    Column("url", STR),
    # Pre-flattened current-company mirrors from the raw record
    Column("current_company_name", STR),
    Column("current_company_company_id", STR),
    # Flattened current_company object (cc_* prefix)
    Column("cc_name", STR, source="current_company.name"),
    Column("cc_company_id", STR, source="current_company.company_id"),
    Column("cc_title", STR, source="current_company.title"),
    Column("cc_location", STR, source="current_company.location"),
    Column("cc_industry", STR, source="current_company.industry"),
    Column("cc_link", STR, source="current_company.link"),
    # Provenance
    Column("source_file", STR),
    Column("source_row", INT),
]

PROFILE_SCHEMA: pa.Schema = pa.schema([c.arrow_field for c in PROFILE_COLUMNS])


# --------------------------------------------------------------------------
# experience + positions.
#
# ``experience`` is a list of jobs; each job may carry a nested ``positions``
# list (multiple roles at the same company). We split these into two linked
# tables so the doubly-nested structure is fully preserved and queryable.
# --------------------------------------------------------------------------
EXPERIENCE = ListTable(
    name="experience",
    source="experience",
    link_columns=[Column("linkedin_id", STR), Column("experience_idx", INT)],
    columns=[
        Column("company", STR),
        Column("company_id", STR),
        Column("company_logo_url", STR),
        Column("title", STR),
        Column("subtitle", STR),
        Column("subtitle_url", STR, source="subtitleURL"),
        Column("location", STR),
        Column("start_date", STR),
        Column("end_date", STR),
        Column("duration", STR),
        Column("duration_short", STR),
        Column("description", STR),
        Column("description_html", STR),
        Column("url", STR),
    ],
)

# Child of EXPERIENCE: linked by (linkedin_id, experience_idx, position_idx).
POSITIONS = ListTable(
    name="positions",
    source="positions",  # read from the parent experience element
    link_columns=[
        Column("linkedin_id", STR),
        Column("experience_idx", INT),
        Column("position_idx", INT),
    ],
    columns=[
        Column("title", STR),
        Column("subtitle", STR),
        Column("meta", STR),
        Column("location", STR),
        Column("start_date", STR),
        Column("end_date", STR),
        Column("duration", STR),
        Column("duration_short", STR),
        Column("description", STR),
        Column("description_html", STR),
    ],
)


# --------------------------------------------------------------------------
# Simple one-to-many child tables (top-level list of dicts).
# Each is linked to its profile by (linkedin_id, idx).
# --------------------------------------------------------------------------
LIST_TABLES: list[ListTable] = [
    ListTable(
        "education",
        "education",
        [
            Column("title", STR),
            Column("degree", STR),
            Column("field", STR),
            Column("start_year", STR),
            Column("end_year", STR),
            Column("description", STR),
            Column("description_html", STR),
            Column("institute_logo_url", STR),
            Column("url", STR),
        ],
    ),
    ListTable(
        "certifications",
        "certifications",
        [
            Column("title", STR),
            Column("subtitle", STR),
            Column("meta", STR),
            Column("credential_id", STR),
            Column("credential_url", STR),
        ],
    ),
    ListTable(
        "courses",
        "courses",
        [Column("title", STR), Column("subtitle", STR)],
    ),
    ListTable(
        "languages",
        "languages",
        [Column("title", STR), Column("subtitle", STR)],
    ),
    ListTable(
        "activity",
        "activity",
        [
            Column("title", STR),
            Column("link", STR),
            Column("img", STR),
            Column("interaction", STR),
            Column("id", STR),
        ],
    ),
    ListTable(
        "bio_links",
        "bio_links",
        [Column("title", STR), Column("link", STR)],
    ),
    ListTable(
        "honors_and_awards",
        "honors_and_awards",
        [
            Column("title", STR),
            Column("publication", STR),
            Column("date", STR),
            Column("description", STR),
        ],
    ),
    ListTable(
        "organizations",
        "organizations",
        [
            Column("title", STR),
            Column("membership_type", STR),
            Column("membership_number", STR),
            Column("start_date", STR),
            Column("end_date", STR),
            Column("description", STR),
        ],
    ),
    ListTable(
        "patents",
        "patents",
        [
            Column("title", STR),
            Column("patents_id", STR),
            Column("date_issued", STR),
            Column("description", STR),
        ],
    ),
    ListTable(
        "people_also_viewed",
        "people_also_viewed",
        [
            Column("name", STR),
            Column("location", STR),
            Column("about", STR),
            Column("profile_link", STR),
        ],
    ),
    ListTable(
        "posts",
        "posts",
        [
            Column("title", STR),
            Column("link", STR),
            Column("img", STR),
            Column("interaction", STR),
            Column("id", STR),
            Column("created_at", STR),
            Column("attribution", STR),
        ],
    ),
    ListTable(
        "projects",
        "projects",
        [
            Column("title", STR),
            Column("start_date", STR),
            Column("end_date", STR),
            Column("description", STR),
        ],
    ),
    ListTable(
        "publications",
        "publications",
        [
            Column("title", STR),
            Column("subtitle", STR),
            Column("date", STR),
            Column("description", STR),
        ],
    ),
    ListTable(
        "similar_profiles",
        "similar_profiles",
        [
            Column("name", STR),
            Column("title", STR),
            Column("url", STR),
            Column("url_text", STR),
        ],
    ),
    ListTable(
        "volunteer_experience",
        "volunteer_experience",
        [
            Column("title", STR),
            Column("subtitle", STR),
            Column("cause", STR),
            Column("info", STR),
            Column("start_date", STR),
            Column("end_date", STR),
            Column("duration", STR),
            Column("duration_short", STR),
        ],
    ),
]

# ``recommendations`` is a list of plain strings rather than dicts, so it gets
# a hand-rolled (linkedin_id, idx, text) schema.
RECOMMENDATIONS_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("linkedin_id", pa.string()),
        pa.field("idx", pa.int64()),
        pa.field("text", pa.string()),
    ]
)


def table_schemas() -> dict[str, pa.Schema]:
    """Map every output table name to its Arrow schema."""
    schemas = {
        "profiles": PROFILE_SCHEMA,
        EXPERIENCE.name: EXPERIENCE.arrow_schema,
        POSITIONS.name: POSITIONS.arrow_schema,
        "recommendations": RECOMMENDATIONS_SCHEMA,
    }
    for table in LIST_TABLES:
        schemas[table.name] = table.arrow_schema
    return schemas


# ==========================================================================
# Extraction: turn one raw record into rows for each table.
#
# Deliberately defensive: values are coerced to the column's declared type so
# a single malformed record can never abort a multi-hour run. Anything
# unexpected becomes ``None`` (or, for strings, a JSON dump) rather than
# raising.
# ==========================================================================

# A sink receives ``(table_name, row_dict)`` and is responsible for buffering
# and writing. Keeping it as a callable decouples extraction from storage.
Sink = Callable[[str, dict[str, Any]], None]


def _coerce(value: Any, kind: str) -> Any:
    """Force ``value`` into the column's declared logical type."""
    if value is None:
        return None
    if kind == STR:
        if isinstance(value, str):
            return value
        # Preserve unexpected structured values rather than dropping them.
        return json.dumps(value, ensure_ascii=False)
    if kind == INT:
        if isinstance(value, bool):  # bool is a subclass of int; reject it
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.replace(",", "").strip()
            try:
                return int(stripped)
            except ValueError:
                return None
        return None
    if kind == BOOL:
        return value if isinstance(value, bool) else None
    return None


def _get(record: dict[str, Any], dotted_key: str) -> Any:
    """Look up a possibly dotted key (e.g. ``current_company.name``)."""
    if "." not in dotted_key:
        return record.get(dotted_key)
    current: Any = record
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _row_from_columns(item: dict[str, Any], columns: list[Column]) -> dict[str, Any]:
    return {col.name: _coerce(_get(item, col.src_key), col.kind) for col in columns}


def _emit_list_table(
    record: dict[str, Any], linkedin_id: str, table: ListTable, sink: Sink
) -> None:
    items = record.get(table.source)
    if not isinstance(items, list):
        return
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        row = {"linkedin_id": linkedin_id, "idx": idx}
        row.update(_row_from_columns(item, table.columns))
        sink(table.name, row)


def _emit_experience(record: dict[str, Any], linkedin_id: str, sink: Sink) -> None:
    """Emit experience rows plus their nested positions rows."""
    items = record.get(EXPERIENCE.source)
    if not isinstance(items, list):
        return
    for exp_idx, exp in enumerate(items):
        if not isinstance(exp, dict):
            continue
        row = {"linkedin_id": linkedin_id, "experience_idx": exp_idx}
        row.update(_row_from_columns(exp, EXPERIENCE.columns))
        sink(EXPERIENCE.name, row)

        positions = exp.get("positions")
        if not isinstance(positions, list):
            continue
        for pos_idx, pos in enumerate(positions):
            if not isinstance(pos, dict):
                continue
            pos_row = {
                "linkedin_id": linkedin_id,
                "experience_idx": exp_idx,
                "position_idx": pos_idx,
            }
            pos_row.update(_row_from_columns(pos, POSITIONS.columns))
            sink(POSITIONS.name, pos_row)


def _emit_recommendations(record: dict[str, Any], linkedin_id: str, sink: Sink) -> None:
    items = record.get("recommendations")
    if not isinstance(items, list):
        return
    for idx, text in enumerate(items):
        sink(
            "recommendations",
            {"linkedin_id": linkedin_id, "idx": idx, "text": _coerce(text, STR)},
        )


def extract(
    record: dict[str, Any], source_file: str, source_row: int, sink: Sink
) -> None:
    """Decompose one profile record and push every resulting row to ``sink``."""
    linkedin_id = record.get("linkedin_id") or record.get("id") or ""

    profile = _row_from_columns(record, PROFILE_COLUMNS)
    profile["source_file"] = source_file
    profile["source_row"] = source_row
    sink("profiles", profile)

    _emit_experience(record, linkedin_id, sink)
    _emit_recommendations(record, linkedin_id, sink)
    for table in LIST_TABLES:
        _emit_list_table(record, linkedin_id, table, sink)


# ==========================================================================
# Writing: buffered, batched Parquet shard writers.
#
# Rows are buffered column-wise and flushed in batches so memory stays bounded
# regardless of how large the input file is.
# ==========================================================================


class _TableBuffer:
    """Column-oriented buffer + lazily-opened Parquet writer for one table."""

    def __init__(self, path: Path, schema: pa.Schema, batch_rows: int):
        self._path = path
        self._schema = schema
        self._batch_rows = batch_rows
        self._col_names = [f.name for f in schema]
        self._cols: dict[str, list[Any]] = {name: [] for name in self._col_names}
        self._writer: pq.ParquetWriter | None = None
        self.total_rows = 0

    def emit(self, row: dict[str, Any]) -> None:
        for name in self._col_names:
            self._cols[name].append(row.get(name))
        self.total_rows += 1
        if len(self._cols[self._col_names[0]]) >= self._batch_rows:
            self._flush()

    def _flush(self) -> None:
        if not self._cols[self._col_names[0]]:
            return
        arrays = [
            pa.array(self._cols[name], type=self._schema.field(name).type)
            for name in self._col_names
        ]
        batch = pa.record_batch(arrays, schema=self._schema)
        if self._writer is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._writer = pq.ParquetWriter(
                self._path, self._schema, compression="zstd"
            )
        self._writer.write_batch(batch)
        for name in self._col_names:
            self._cols[name].clear()

    def close(self) -> None:
        self._flush()
        if self._writer is not None:
            self._writer.close()


class ShardWriter:
    """Owns one ``_TableBuffer`` per table for a single input shard."""

    def __init__(self, output_root: Path, shard_name: str, batch_rows: int = 50_000):
        self._buffers = {
            table: _TableBuffer(
                output_root / table / f"{shard_name}.parquet", schema, batch_rows
            )
            for table, schema in table_schemas().items()
        }

    def emit(self, table: str, row: dict[str, Any]) -> None:
        self._buffers[table].emit(row)

    def close(self) -> dict[str, int]:
        """Flush and close all writers; return per-table row counts."""
        counts = {}
        for name, buf in self._buffers.items():
            buf.close()
            counts[name] = buf.total_rows
        return counts


# ==========================================================================
# Pipeline: parallel orchestration (one worker process per input file).
# ==========================================================================


@dataclass
class FileResult:
    file: str
    profiles: int = 0
    json_errors: int = 0
    elapsed_s: float = 0.0
    table_counts: dict[str, int] = field(default_factory=dict)


def parse_file(input_path: Path, output_root: Path, batch_rows: int) -> FileResult:
    """Parse one JSONL file into Parquet shards. Runs inside a worker process."""
    started = time.monotonic()
    shard_name = input_path.stem  # e.g. snap_mlsi9jwqziij1k8zq.1
    writer = ShardWriter(output_root, shard_name, batch_rows=batch_rows)
    file_label = input_path.name

    profiles = 0
    json_errors = 0
    with input_path.open("rb") as fh:  # bytes: orjson parses bytes directly
        for row_no, line in enumerate(fh):
            if not line.strip():
                continue
            try:
                record = orjson.loads(line)
            except orjson.JSONDecodeError:
                json_errors += 1
                continue
            if not isinstance(record, dict):
                json_errors += 1
                continue
            extract(record, file_label, row_no, writer.emit)
            profiles += 1
            if profiles % LOG_EVERY == 0:
                print(
                    f"[{file_label}] {profiles:,} profiles", file=sys.stderr, flush=True
                )

    table_counts = writer.close()
    return FileResult(
        file=file_label,
        profiles=profiles,
        json_errors=json_errors,
        elapsed_s=time.monotonic() - started,
        table_counts=table_counts,
    )


def find_input_files(data_dir: Path) -> list[Path]:
    """All ``*.jsonl`` files, ignoring Windows ``Zone.Identifier`` sidecars."""
    files = [
        p
        for p in data_dir.glob("*.jsonl")
        if p.is_file() and not p.name.endswith(":Zone.Identifier")
    ]
    return sorted(files)


def run(
    data_dir: Path,
    output_root: Path,
    workers: int | None = None,
    batch_rows: int = 50_000,
) -> dict[str, Any]:
    """Parse every input file in parallel and write a run manifest."""
    files = find_input_files(data_dir)
    if not files:
        raise SystemExit(f"No .jsonl files found in {data_dir}")

    workers = workers or min(len(files), 8)
    output_root.mkdir(parents=True, exist_ok=True)
    print(
        f"Parsing {len(files)} file(s) with {workers} worker(s) -> {output_root}",
        file=sys.stderr,
        flush=True,
    )

    started = time.monotonic()
    results: list[FileResult] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(parse_file, f, output_root, batch_rows): f for f in files
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                f"[done] {result.file}: {result.profiles:,} profiles "
                f"in {result.elapsed_s:.0f}s ({result.json_errors} json errors)",
                file=sys.stderr,
                flush=True,
            )

    totals: dict[str, int] = {}
    for result in results:
        for table, count in result.table_counts.items():
            totals[table] = totals.get(table, 0) + count

    manifest = {
        "data_dir": str(data_dir),
        "output_root": str(output_root),
        "workers": workers,
        "batch_rows": batch_rows,
        "elapsed_s": round(time.monotonic() - started, 1),
        "files": [
            {
                "file": r.file,
                "profiles": r.profiles,
                "json_errors": r.json_errors,
                "elapsed_s": round(r.elapsed_s, 1),
            }
            for r in sorted(results, key=lambda r: r.file)
        ],
        "total_profiles": sum(r.profiles for r in results),
        "total_json_errors": sum(r.json_errors for r in results),
        "table_row_counts": dict(sorted(totals.items())),
    }
    (output_root / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


# ==========================================================================
# CLI
# ==========================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse raw LinkedIn JSONL snapshots into a Parquet star schema."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data",
        help="Directory containing the *.jsonl input files (default: ./data).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "parsed",
        help="Directory to write Parquet tables into (default: ./parsed).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes (default: min(#files, 8)).",
    )
    parser.add_argument(
        "--batch-rows",
        type=int,
        default=50_000,
        help="Rows buffered per table before flushing a Parquet row group.",
    )
    args = parser.parse_args(argv)

    manifest = run(
        data_dir=args.data_dir,
        output_root=args.output_root,
        workers=args.workers,
        batch_rows=args.batch_rows,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
