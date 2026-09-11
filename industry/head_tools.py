"""Tooling for the curated-head ratchet: dump the unresolved head with evidence,
and turn a labeled JSONL back into `industry/curated_head.py`.

    uv run python -m industry.head_tools extract --top 3000 --hum-top 3700 --out head.jsonl
    uv run python -m industry.head_tools write head_labels.jsonl

`extract` lists every id-keyed company still `unresolved` after a build, ranked
by row count (`rank_all`) and by humanities-cohort rows (`rank_hum`), with the
modal titles and description snippets from the vocab cache -- the evidence a
labeler (frontier model or human) sees.  Label lines are
`{"company_id", "code", "display", "freq", ...}`; `code` = `SKIP` abstains.

`write` validates every code against the taxonomy, refuses retracted keys,
lets hand entries win silently, and rewrites the `HEAD` table with a
provenance comment per entry.  The label record itself belongs in
`results/head_labels_v<n>.jsonl`; the blind gate for the tier is
`head_gate.py`.
"""

from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path

from . import curated
from . import taxonomy as T
from .common import CACHE, ROOT

RESULTS = Path(__file__).resolve().parent / "results"
HEAD_MODULE = Path(__file__).resolve().parent / "curated_head.py"

# ------------------------------------------------------------------ extract

def extract(top: int, hum_top: int, out: Path, threads: int = 8) -> dict:
    import duckdb

    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    con.execute(f"""
      CREATE TEMP TABLE hum AS
      SELECT s.key, count(*) AS hum_steps
      FROM read_parquet('{RESULTS}/step_industry.parquet') s
      JOIN read_parquet('{ROOT}/normalized/education_person.parquet') e USING (linkedin_id)
      WHERE e.hum_l1_any AND s.method = 'unresolved' AND s.key LIKE 'id:%'
      GROUP BY 1
    """)
    con.execute(f"""
      CREATE TEMP TABLE u AS
      SELECT c.key, c.company_id, c.display, c.freq, c.n_persons,
             coalesce(h.hum_steps, 0) AS hum_steps,
             v.titles, v.descriptions,
             row_number() OVER (ORDER BY c.freq DESC, c.key) AS rank_all,
             row_number() OVER (ORDER BY coalesce(h.hum_steps, 0) DESC, c.freq DESC, c.key) AS rank_hum
      FROM read_parquet('{RESULTS}/company_industry.parquet') c
      LEFT JOIN read_parquet('{CACHE}/company_vocab.parquet') v USING (key)
      LEFT JOIN hum h USING (key)
      WHERE c.method = 'unresolved' AND c.key LIKE 'id:%'
    """)
    rows = con.execute(f"SELECT * FROM u WHERE rank_all <= {top} OR rank_hum <= {hum_top} ORDER BY rank_all").fetchall()
    cols = [d[0] for d in con.description]
    with open(out, "w") as f:
        for r in rows:
            d = dict(zip(cols, r))
            d["titles"] = (d["titles"] or [])[:6]
            d["descriptions"] = [x[:300] for x in (d["descriptions"] or [])[:2]]
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    total = con.execute("SELECT coalesce(sum(freq), 0) FROM u").fetchone()[0]
    selected = sum(r[cols.index("freq")] for r in rows)
    return {"companies": len(rows), "rows": selected, "unresolved_rows": total}


# -------------------------------------------------------------------- write

def build_entries(rows: list[dict], hand: set[str] | None = None,
                  retracted: frozenset[str] | None = None) -> tuple[OrderedDict, list[tuple[str, str, str]]]:
    """(entries, rejects): entries[company_id] = (code, display, freq).  SKIP /
    empty codes are dropped, hand keys are dropped silently (hand wins),
    invalid codes and retracted keys are rejected."""
    hand = curated._HAND.keys() if hand is None else hand  # noqa: SLF001
    retracted = curated.RETRACTED if retracted is None else retracted
    entries: OrderedDict = OrderedDict()
    bad: list[tuple[str, str, str]] = []
    for d in rows:
        cid, code = d["company_id"], d.get("code")
        if code in (None, "", "SKIP"):
            continue
        if not T.is_valid(code):
            bad.append((cid, code, "invalid code"))
            continue
        if cid in retracted:
            bad.append((cid, code, "retracted"))
            continue
        if cid in hand:
            continue
        entries[cid] = (code, d.get("display", ""), int(d.get("freq", 0)))
    return entries, bad


def render(entries: OrderedDict, header: str) -> str:
    lines = [header, "HEAD: dict[str, str] = {\n"]
    for cid, (code, disp, freq) in entries.items():
        disp = disp.replace("\\", "\\\\").replace('"', '\\"')[:60]
        lines.append(f'    "{cid}": "{code}",  # {disp} (rows={freq})\n')
    lines.append("}\n")
    return "".join(lines)


def write(labels: Path, module: Path = HEAD_MODULE) -> int:
    rows = [json.loads(line) for line in labels.read_text().splitlines() if line.strip()]
    entries, bad = build_entries(rows)
    if bad:
        for b in bad:
            print("REJECT", *b)
        raise SystemExit(f"{len(bad)} rejected labels")
    header = module.read_text().split("HEAD: dict[str, str] = {")[0]
    module.write_text(render(entries, header))
    return len(entries)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("--top", type=int, default=3000)
    ex.add_argument("--hum-top", type=int, default=3700)
    ex.add_argument("--out", type=Path, default=Path("head.jsonl"))
    wr = sub.add_parser("write")
    wr.add_argument("labels", type=Path)
    a = ap.parse_args()
    if a.cmd == "extract":
        r = extract(a.top, a.hum_top, a.out)
        print(f"{r['companies']:,} companies selected; {r['rows']:,} rows of {r['unresolved_rows']:,} unresolved id-keyed rows -> {a.out}")
    else:
        n = write(a.labels)
        print(f"wrote {n:,} head entries -> {HEAD_MODULE}")


if __name__ == "__main__":
    main()
