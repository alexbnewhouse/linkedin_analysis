"""Land frontier (Fable 5.1) adjudications of the CIP disagreement band.

    uv run python -m edu_clean.frontier_merge add CHUNK.txt   # 'idx code' lines -> jsonl
    uv run python -m edu_clean.frontier_merge merge [--execute]

Labels are keyed by field_norm in results/frontier_adjudication.jsonl
(method 'frontier_adjudication_v1'). Rule for compound strings: the FIRST-listed
field is primary ("X and Y" -> X). HS-diploma placeholders map to 53 only when
the degree line explicitly says high school/GED; other placeholders abstain (XUN).
merge appends non-XUN labels to mappings/field_cip_jury.parquet with method
'frontier_v1', n_jurors=1, unanimous=FALSE -- never overwriting existing keys.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

from edu_clean import cip_taxonomy as T

ROOT = Path(__file__).resolve().parent.parent
KEYS = Path("/tmp/claude-1000/-home-alex-linkedin-analysis/75f1b68a-4d86-43a1-ae5f-ca08d45f96d5/scratchpad/target_band_keys.json")
OUT = ROOT / "edu_clean" / "results" / "frontier_adjudication.jsonl"
JURY = ROOT / "normalized" / "mappings" / "field_cip_jury.parquet"


def cmd_add(path: str) -> None:
    keys = json.load(open(KEYS))
    have = set()
    if OUT.exists():
        have = {json.loads(l)["field_norm"] for l in OUT.read_text().splitlines() if l.strip()}
    n = 0
    with OUT.open("a") as f:
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            i, code = line.split()
            fn = keys[int(i)]
            assert code == "XUN" or T.is_valid(code), (i, code)
            if fn in have:
                continue
            f.write(json.dumps({"field_norm": fn, "cip2": code,
                                "method": "frontier_adjudication_v1"}) + "\n")
            have.add(fn); n += 1
    print(f"added {n} labels; total {len(have)} / {len(keys)} band strings")


def cmd_merge(execute: bool) -> None:
    labels = [json.loads(l) for l in OUT.read_text().splitlines() if l.strip()]
    labels = [d for d in labels if d["cip2"] != "XUN"]
    con = duckdb.connect()
    existing = {r[0] for r in con.execute(
        f"SELECT field_norm FROM read_parquet('{JURY}')").fetchall()}
    adds = [(d["field_norm"], d["cip2"]) for d in labels if d["field_norm"] not in existing]
    print(f"frontier labels: {len(labels)} non-XUN; new to jury parquet: {len(adds)}")
    if not execute:
        print("(dry-run -- pass --execute to append)"); return
    con.execute("CREATE TEMP TABLE adds (field_norm VARCHAR, cip2 VARCHAR)")
    con.executemany("INSERT INTO adds VALUES (?, ?)", adds)
    tmp = JURY.with_name(JURY.name + ".tmp")
    con.execute(f"""COPY (SELECT * FROM read_parquet('{JURY}') UNION ALL
        SELECT field_norm, cip2, 'frontier_v1', 1, FALSE FROM adds)
        TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)""")
    dup = con.execute(f"SELECT count(*)-count(DISTINCT field_norm) FROM read_parquet('{tmp}')").fetchone()[0]
    assert dup == 0, dup
    tmp.replace(JURY)
    print(f"merged -> {JURY}; now run: make normalize-education")


if __name__ == "__main__":
    if sys.argv[1] == "add":
        cmd_add(sys.argv[2])
    else:
        cmd_merge("--execute" in sys.argv)
