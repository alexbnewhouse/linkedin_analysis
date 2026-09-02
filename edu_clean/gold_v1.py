"""Blind, source-stratified CIP gold set (frontier-labeled), and the scorer.

    uv run python -m edu_clean.gold_v1 draw            # sample + print BLIND evidence
    uv run python -m edu_clean.gold_v1 label FILE      # 'idx code[/secondary][?]' lines
    uv run python -m edu_clean.gold_v1 score           # per-tier precision table

Why: the existing cip_gold is deterministic-coder output (easy by construction),
so every landed tier was graded on the wrong population or not at all. This set
is drawn per SOURCE TIER of `education.cip_source` (det, jury-LLM, frontier,
knn_head, degree_type) plus the uncoded residual, labeled BEFORE seeing any
system label, and HELD OUT: never merged into a mapping, never used as a seed.
The frontier stratum grades the frontier's own labels -> consistency check only.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from edu_clean import cip_taxonomy as T
from edu_clean import humanities as H

ROOT = Path(__file__).resolve().parent.parent
EDU = ROOT / "normalized" / "education.parquet"
JURY = ROOT / "normalized" / "mappings" / "field_cip_jury.parquet"
OUT = ROOT / "edu_clean" / "results" / "frontier_gold_v1.parquet"
SCORE = ROOT / "edu_clean" / "results" / "frontier_gold_v1_score.json"
PER_TIER = 60
RESIDUAL = 100
SALT = "gold1"


def draw() -> None:
    con = duckdb.connect(); con.execute("PRAGMA threads=8")
    con.execute(f"""
      CREATE TEMP TABLE strings AS
      SELECT field_raw,
             any_value(cip_source) AS cip_source,
             any_value(cip2_pooled) AS sys_cip2,
             count(*) AS n_rows,
             mode(degree_raw) AS degree_modal
      FROM read_parquet('{EDU}')
      WHERE field_raw IS NOT NULL AND trim(field_raw) <> '' AND NOT is_duplicate
      GROUP BY field_raw""")
    con.execute(f"""
      CREATE TEMP TABLE tiered AS
      SELECT s.*,
             CASE WHEN s.cip_source = 'jury' AND j.method = 'frontier_v1' THEN 'frontier'
                  WHEN s.cip_source = 'jury' THEN 'jury_llm'
                  WHEN s.cip_source IS NULL THEN 'residual'
                  ELSE s.cip_source END AS tier
      FROM strings s
      LEFT JOIN read_parquet('{JURY}') j ON j.field_norm = lower(trim(s.field_raw))""")
    parts = []
    for tier, n in (("det", PER_TIER), ("jury_llm", PER_TIER), ("frontier", PER_TIER),
                    ("knn_head", PER_TIER), ("degree_type", PER_TIER), ("residual", RESIDUAL)):
        parts.append(f"""(SELECT * FROM tiered WHERE tier = '{tier}'
                          ORDER BY hash(field_raw || '{SALT}') LIMIT {n})""")
    rows = con.execute("SELECT * FROM (" + " UNION ALL ".join(parts) + ") u"
                       f" ORDER BY hash(field_raw || '{SALT}' || 'shuffle')").fetchall()
    cols = ["field_raw", "cip_source", "sys_cip2", "n_rows", "degree_modal", "tier"]
    table = pa.table({c: [r[i] for r in rows] for i, c in enumerate(cols)})
    table = table.append_column("idx", pa.array(range(len(rows))))
    pq.write_table(table, OUT)
    print(f"drew {len(rows)} strings -> {OUT}  (tiers: "
          + ", ".join(f"{t}={sum(1 for r in rows if r[5]==t)}" for t in
                      ("det","jury_llm","frontier","knn_head","degree_type","residual")) + ")")
    print("\nBLIND EVIDENCE (idx | field | modal degree | rows):")
    for i, r in enumerate(rows):
        print(f"{i:3d}\t{(r[0] or '')[:72]}\t{(r[4] or '')[:28]}\t{r[3]}")


def label(path: str) -> None:
    t = pq.read_table(OUT).to_pydict()
    n = len(t["idx"])
    prim, sec, unsure = [None] * n, [None] * n, [False] * n
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        i, code = line.split()
        i = int(i)
        u = code.endswith("?"); code = code.rstrip("?")
        p, _, s = code.partition("/")
        assert p == "XUN" or T.is_valid(p), (i, p)
        assert not s or T.is_valid(s), (i, s)
        prim[i], sec[i], unsure[i] = p, (s or None), u
    missing = [i for i in range(n) if prim[i] is None]
    assert not missing, f"unlabeled idx: {missing[:20]}"
    tbl = pa.table({**t, "gold_cip2": prim, "gold_secondary": sec, "gold_unsure": unsure,
                    "labeled_by": ["fable-5.1-blind"] * n, "labeled": [date.today().isoformat()] * n})
    pq.write_table(tbl, OUT)
    print(f"labeled {n} strings ({sum(1 for p in prim if p=='XUN')} XUN, "
          f"{sum(1 for s in sec if s)} with secondary, {sum(unsure)} flagged unsure)")


STRING_TIERS = {"jury", "knn_head"}          # cip_source values keyed by the field string
DEGREE_TIERS = {"degree_type", "degree_level"}  # keyed by the degree line, never the field


def _live_codes(con, strings: list[str]) -> dict:
    """Current per-string system behaviour, read live from education.parquet so the
    fixed gold sample can be re-scored after every reconfiguration.

    modal   (cip_source, cip2_pooled) of the row group with the modal degree line --
            the evidence the labeler saw
    rows    [(cip_source, cip2_pooled, n)] over all rows of the string
    """
    con.execute("CREATE OR REPLACE TEMP TABLE gs (field_raw VARCHAR)")
    con.executemany("INSERT INTO gs VALUES (?)", [(f,) for f in strings])
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE gr AS
      SELECT e.field_raw, e.degree_raw, e.cip_source, e.cip2_pooled, count(*) n
      FROM read_parquet('{EDU}') e JOIN gs USING (field_raw) GROUP BY ALL""")
    out = {f: {"modal": (None, None), "rows": []} for f in strings}
    for f, src, c, n in con.execute(
            "SELECT field_raw, cip_source, cip2_pooled, sum(n) FROM gr GROUP BY ALL").fetchall():
        out[f]["rows"].append((src, c, int(n)))
    for f, src, c in con.execute("""
      SELECT field_raw, cip_source, cip2_pooled FROM (
        SELECT field_raw, degree_raw, any_value(cip_source) cip_source, any_value(cip2_pooled) cip2_pooled,
               sum(n) n, row_number() OVER (PARTITION BY field_raw ORDER BY sum(n) DESC, degree_raw) rk
        FROM gr GROUP BY field_raw, degree_raw) WHERE rk = 1""").fetchall():
        out[f]["modal"] = (src, c)
    return out


def score() -> None:
    """Grade the fixed gold sample against the CURRENT education.parquet.

    Semantics (settled after the first pass exposed them):
    * A gold of XUN means "the field string carries no field signal". Rows of
      such strings coded by det/degree_type/degree_level were coded from the
      degree line ("GPA 3.86" + "Advertising" -> 09), which is correct
      behaviour, so they are reported as `coded_from_degree_line`, not errors.
      The same rows coded by a STRING-keyed tier (jury/knn_head) are errors --
      a string label on a placeholder ("Summa Cum Laude Graduate" -> 53).
    * Coded gold is graded on the modal-degree row (the labeler's evidence):
      strict = primary, lenient = primary or secondary, level = same
      humanities level. Row-weighted strict grades every row of the string.
    """
    t = pq.read_table(OUT).to_pylist()
    con = duckdb.connect()
    live = _live_codes(con, [r["field_raw"] for r in t])

    def lvl(c):
        return H.classify_cip(c).level if c and c != "XUN" else None
    out = {"generated": date.today().isoformat(), "n": len(t), "tiers": {}}
    hdr = (f"{'tier':<12}{'n':>4}{'graded':>7}{'strict':>8}{'lenient':>8}{'level':>7}"
           f"{'row-wtd':>9}  {'XUN: abstain/degree-line/string-label':>38}")
    print(hdr)
    for tier in ("det", "jury_llm", "frontier", "knn_head", "degree_type", "residual"):
        rows = [r for r in t if r["tier"] == tier]
        if tier == "residual":
            codeable = [r for r in rows if r["gold_cip2"] != "XUN"]
            w = sum(r["n_rows"] for r in rows)
            wc = sum(r["n_rows"] for r in codeable)
            now_coded = sum(1 for r in rows if live[r["field_raw"]]["modal"][1])
            out["tiers"][tier] = {"n": len(rows), "codeable_strings": len(codeable),
                                  "codeable_share": round(len(codeable)/len(rows), 3),
                                  "codeable_row_share": round(wc / w, 3) if w else None,
                                  "now_coded_strings": now_coded}
            print(f"{tier:<12}{len(rows):>4}   codeable {len(codeable)}/{len(rows)} strings "
                  f"({100*len(codeable)/len(rows):.0f}%), {100*wc/w:.0f}% of rows; "
                  f"{now_coded} now coded")
            continue
        graded = [r for r in rows if r["gold_cip2"] != "XUN"]
        sysc = {r["idx"]: live[r["field_raw"]]["modal"] for r in rows}
        strict = [sysc[r["idx"]][1] == r["gold_cip2"] for r in graded]
        lenient = [sysc[r["idx"]][1] in (r["gold_cip2"], r["gold_secondary"]) for r in graded]
        level = [lvl(sysc[r["idx"]][1]) == lvl(r["gold_cip2"]) for r in graded]
        # row-weighted: every row of every graded string
        w = ok = 0
        for r in graded:
            for src, c, n in live[r["field_raw"]]["rows"]:
                w += n; ok += n if c == r["gold_cip2"] else 0
        roww = ok / w if w else None
        # XUN strings: how did the system treat them?
        xun = {"abstain": 0, "degree_line": 0, "string_label": 0}
        xun_rows = {"abstain": 0, "degree_line": 0, "string_label": 0}
        bad_labels = []
        for r in rows:
            if r["gold_cip2"] != "XUN":
                continue
            src, c = sysc[r["idx"]]
            k = "abstain" if c is None else ("string_label" if src in STRING_TIERS else "degree_line")
            xun[k] += 1
            if k == "string_label":
                bad_labels.append((r["field_raw"], src, c))
            for src2, c2, n in live[r["field_raw"]]["rows"]:
                k2 = "abstain" if c2 is None else ("string_label" if src2 in STRING_TIERS else "degree_line")
                xun_rows[k2] += n
        conf = {}
        misses = []
        for r, okk in zip(graded, lenient):
            if not okk:
                k = f"{r['gold_cip2']}->{sysc[r['idx']][1]}"; conf[k] = conf.get(k, 0) + 1
                misses.append((r["field_raw"], sysc[r["idx"]][0], sysc[r["idx"]][1],
                               r["gold_cip2"], r["gold_secondary"]))
        out["tiers"][tier] = {"n": len(rows), "graded": len(graded),
                              "strict": round(sum(strict)/len(graded), 3) if graded else None,
                              "lenient": round(sum(lenient)/len(graded), 3) if graded else None,
                              "level": round(sum(level)/len(graded), 3) if graded else None,
                              "row_weighted_strict": round(roww, 3) if roww is not None else None,
                              "gold_xun_strings": xun, "gold_xun_rows": xun_rows,
                              "xun_string_label_errors": bad_labels,
                              "lenient_misses": misses,
                              "top_confusions": sorted(conf.items(), key=lambda x: -x[1])[:6]}
        print(f"{tier:<12}{len(rows):>4}{len(graded):>7}{sum(strict)/len(graded):>8.3f}"
              f"{sum(lenient)/len(graded):>8.3f}{sum(level)/len(graded):>7.3f}{roww:>9.3f}  "
              f"{xun['abstain']:>12}/{xun['degree_line']}/{xun['string_label']}")
    SCORE.write_text(json.dumps(out, indent=1))
    print(f"\nwrote {SCORE}")


if __name__ == "__main__":
    {"draw": draw, "label": lambda: label(sys.argv[2]), "score": score}[sys.argv[1]]()
