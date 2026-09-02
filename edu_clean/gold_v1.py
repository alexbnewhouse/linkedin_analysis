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
import math
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


def score(*, verbose: bool = True, write: bool = True) -> dict:
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
    if verbose:
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
            if verbose:
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
        if verbose:
            print(f"{tier:<12}{len(rows):>4}{len(graded):>7}{sum(strict)/len(graded):>8.3f}"
                  f"{sum(lenient)/len(graded):>8.3f}{sum(level)/len(graded):>7.3f}{roww:>9.3f}  "
                  f"{xun['abstain']:>12}/{xun['degree_line']}/{xun['string_label']}")
    if write:
        SCORE.write_text(json.dumps(out, indent=1))
        if verbose:
            print(f"\nwrote {SCORE}")
    return out



LANDED = ("det", "jury_llm", "frontier", "knn_head", "degree_type")
CALIB = ROOT / "edu_clean" / "results" / "frontier_gold_v1_calibration.json"
KNN_SWEEP = ROOT / "edu_clean" / "results" / "frontier_gold_v1_knn_sweep.json"
SHEET = ROOT / "edu_clean" / "results" / "frontier_gold_v1_double_label_sheet.txt"
AGREE = ROOT / "edu_clean" / "results" / "frontier_gold_v1_agreement.json"
REPORT = ROOT / "edu_clean" / "results" / "frontier_gold_v1_report.json"
_ITEM_COLS = ("field_norm", "n_rows", "n_persons", "top_raw_variants",
              "modal_degree_text", "n_bachelor_rows")


def _wilson(k: int, n: int, z: float = 1.96) -> tuple | None:
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def _ok(sys_code, r) -> tuple[bool, bool]:
    """(strict, lenient) for one system code against one gold row."""
    return sys_code == r["gold_cip2"], sys_code in (r["gold_cip2"], r["gold_secondary"])


def _gold_items(con, t: list[dict]) -> list[dict]:
    """Juror items for the gold strings in the production evidence shape
    (cip_candidates: top-3 raw variants, modal degree line, counts, anchors)."""
    norms = sorted({r["field_raw"].strip().lower() for r in t})
    con.execute("CREATE OR REPLACE TEMP TABLE gn (field_norm VARCHAR)")
    con.executemany("INSERT INTO gn VALUES (?)", [(n,) for n in norms])
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE pop AS
      SELECT lower(trim(field_raw)) AS field_norm, field_raw, linkedin_id,
             nullif(trim(degree_raw), '') AS degree_text, degree_level
      FROM read_parquet('{EDU}') WHERE lower(trim(field_raw)) IN (SELECT field_norm FROM gn)""")
    rows = con.execute("""
      WITH agg AS (
        SELECT field_norm, count(*) AS n_rows, count(DISTINCT linkedin_id) AS n_persons,
               count(*) FILTER (degree_level = 4) AS n_bachelor_rows FROM pop GROUP BY 1),
      var AS (
        SELECT field_norm, string_agg(left(field_raw, 60), ' | ' ORDER BY rn) AS top_raw_variants
        FROM (SELECT field_norm, field_raw,
                     row_number() OVER (PARTITION BY field_norm ORDER BY count(*) DESC, field_raw) AS rn
              FROM pop GROUP BY 1, 2) WHERE rn <= 3 GROUP BY 1),
      deg AS (
        SELECT field_norm, degree_text
        FROM (SELECT field_norm, degree_text,
                     row_number() OVER (PARTITION BY field_norm ORDER BY count(*) DESC, degree_text) AS rn
              FROM pop WHERE degree_text IS NOT NULL GROUP BY 1, 2) WHERE rn = 1)
      SELECT a.field_norm, a.n_rows, a.n_persons, v.top_raw_variants, d.degree_text, a.n_bachelor_rows
      FROM agg a LEFT JOIN var v USING (field_norm) LEFT JOIN deg d USING (field_norm)""").fetchall()
    items = [dict(zip(_ITEM_COLS, r)) for r in rows]
    from edu_clean import cip_anchors as A
    A.attach_anchors(items)
    return items


def calibrate(model: str, hosts: str) -> dict:
    """Fire MODEL (e.g. 'ollama/gemma3:12b') on the 400 gold strings through the
    frozen vote cache and score it per tier. HOSTS is an OLLAMA_HOSTS spec
    ('name=url|slots|api'). Votes land in results/cip_votes.jsonl keyed by
    (evidence, model, prompt version) -- re-runs are free."""
    import os
    from edu_clean import cip_llm as L
    t = pq.read_table(OUT).to_pylist()
    con = duckdb.connect()
    items = _gold_items(con, t)

    def _pool():
        os.environ["OLLAMA_HOSTS"] = hosts
        from industry import llm_pool
        return llm_pool.HostPool()
    orig = L.make_pool
    L.make_pool = _pool
    try:
        stats = L.fire(items, jurors=(model,), execute=True)
    finally:
        L.make_pool = orig
    print(f"fire: {stats}")
    votes = L.votes_by_key(items, jurors=(model,))
    res = {"model": model, "hosts": hosts, "generated": date.today().isoformat(),
           "fire": stats, "tiers": {}}
    print(f"{'tier':<12}{'n':>4}{'fired':>6}{'voted':>6}{'strict':>8}{'lenient':>8}"
          f"{'level':>7}  {'XUN: abstain/coded':>18}")

    def lvl(c):
        return H.classify_cip(c).level if c and c != "XUN" else None
    for tier in LANDED + ("residual",):
        rows = [r for r in t if r["tier"] == tier]
        fired = voted = 0
        st = le = lv = []
        st, le, lv = [], [], []
        xun = {"abstain": 0, "coded": 0, "unfired": 0}
        for r in rows:
            code = votes.get(r["field_raw"].strip().lower(), {}).get(model)
            if code is None:
                if r["gold_cip2"] == "XUN":
                    xun["unfired"] += 1
                continue
            fired += 1
            if r["gold_cip2"] == "XUN":
                xun["abstain" if code == "XUN" else "coded"] += 1
                continue
            if code == "XUN":
                continue
            voted += 1
            a, b = _ok(code, r)
            st.append(a); le.append(b); lv.append(lvl(code) == lvl(r["gold_cip2"]))
        graded = sum(1 for r in rows if r["gold_cip2"] != "XUN")
        d = {"n": len(rows), "graded": graded, "fired": fired, "voted": voted,
             "vote_rate": round(voted / graded, 3) if graded else None,
             "strict": round(sum(st) / voted, 3) if voted else None,
             "lenient": round(sum(le) / voted, 3) if voted else None,
             "level": round(sum(lv) / voted, 3) if voted else None,
             "gold_xun": xun}
        res["tiers"][tier] = d
        print(f"{tier:<12}{len(rows):>4}{fired:>6}{voted:>6}"
              f"{(d['strict'] or 0):>8.3f}{(d['lenient'] or 0):>8.3f}{(d['level'] or 0):>7.3f}"
              f"  {xun['abstain']:>10}/{xun['coded']}")
    prior = json.loads(CALIB.read_text()) if CALIB.exists() else {}
    prior[model] = res
    CALIB.write_text(json.dumps(prior, indent=1))
    print(f"wrote {CALIB}")
    return res


def knn() -> dict:
    """Embedding-kNN sweep over the gold: nearest labeled string (self excluded,
    so landed tiers are leave-one-out; residual strings are the honest test)
    at tau in {0.80, 0.85, 0.90, 0.95}. Needs `uv run --group embed`."""
    import numpy as np
    import torch
    from edu_clean import knn_tail as KT
    from edu_clean.nearest_neighbor import _cached_encode
    t = pq.read_table(OUT).to_pylist()
    values, freqs, labels, by_norm = KT.load()
    emb = _cached_encode("bge-base", values, "field_values").astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    lab_idx = np.array(sorted(i for i, lab in labels.items() if lab != "XUN"))
    ref_labels = [labels[i] for i in lab_idx]
    ref_norm = [KT.norm(values[i]) for i in lab_idx]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    ref = torch.from_numpy(emb[lab_idx]).to(dev)

    qtexts, method = [], []
    for r in t:
        h = KT.head_component(r["field_raw"])
        if h and by_norm.get(KT.norm(h)) and KT.norm(h) != KT.norm(r["field_raw"]):
            method.append(("head_exact", by_norm[KT.norm(h)]))
            qtexts.append(h)
        elif h and len(h.split()) >= 2:
            method.append(("head_knn", None)); qtexts.append(h)
        else:
            method.append(("knn", None)); qtexts.append(r["field_raw"])
    q = _cached_encode("bge-base", qtexts, "gold_v1_queries").astype(np.float32)
    q /= np.linalg.norm(q, axis=1, keepdims=True) + 1e-9
    sims, idxs = KT.topk(torch.from_numpy(q).to(dev), ref, 8)

    def lvl(c):
        return H.classify_cip(c).level if c and c != "XUN" else None
    best = []   # per gold row: (method, sim, code)
    for i, r in enumerate(t):
        m, fixed = method[i]
        if fixed:
            best.append((m, 1.0, fixed)); continue
        me = KT.norm(r["field_raw"])
        pick = None
        for s_, j in zip(sims[i], idxs[i]):
            if ref_norm[j] != me:            # leave-one-out on the exact string
                pick = (m, float(s_), ref_labels[j]); break
        best.append(pick or (m, 0.0, None))
    out = {"generated": date.today().isoformat(), "taus": {}, "by_string": []}
    for r, b in zip(t, best):
        out["by_string"].append({"idx": r["idx"], "tier": r["tier"], "method": b[0],
                                 "sim": round(b[1], 4), "knn_cip2": b[2],
                                 "gold": r["gold_cip2"], "gold_secondary": r["gold_secondary"]})
    print(f"{'tau':>5} {'tier':<12}{'n':>4}{'covered':>8}{'strict':>8}{'lenient':>8}{'level':>7}{'XUN coded':>10}")
    for tau in (0.80, 0.85, 0.90, 0.95):
        out["taus"][str(tau)] = {}
        for tier in LANDED + ("residual",):
            rows = [(r, b) for r, b in zip(t, best) if r["tier"] == tier]
            cov = [(r, b) for r, b in rows if b[1] >= tau and b[2]]
            graded = [(r, b) for r, b in cov if r["gold_cip2"] != "XUN"]
            xc = sum(1 for r, b in cov if r["gold_cip2"] == "XUN")
            st = [_ok(b[2], r)[0] for r, b in graded]
            le = [_ok(b[2], r)[1] for r, b in graded]
            lv = [lvl(b[2]) == lvl(r["gold_cip2"]) for r, b in graded]
            d = {"n": len(rows), "covered": len(cov), "graded": len(graded),
                 "strict": round(sum(st) / len(graded), 3) if graded else None,
                 "lenient": round(sum(le) / len(graded), 3) if graded else None,
                 "level": round(sum(lv) / len(graded), 3) if graded else None,
                 "gold_xun_coded": xc}
            out["taus"][str(tau)][tier] = d
            print(f"{tau:>5} {tier:<12}{len(rows):>4}{len(cov):>8}"
                  f"{(d['strict'] or 0):>8.3f}{(d['lenient'] or 0):>8.3f}{(d['level'] or 0):>7.3f}{xc:>10}")
    KNN_SWEEP.write_text(json.dumps(out, indent=1))
    print(f"wrote {KNN_SWEEP}")
    return out


_SHEET_PER_TIER = {"det": 15, "jury_llm": 15, "frontier": 15, "knn_head": 15,
                   "degree_type": 15, "residual": 25}


def sheet() -> None:
    """Write the blind double-label sheet: 100 gold strings (stratified by tier,
    salted hash) with the same evidence the first labeler saw and nothing else."""
    import hashlib
    t = pq.read_table(OUT).to_pylist()
    pick = []
    for tier, k in _SHEET_PER_TIER.items():
        rows = [r for r in t if r["tier"] == tier]
        rows.sort(key=lambda r: hashlib.sha1((r["field_raw"] + SALT + "dbl").encode()).hexdigest())
        pick += rows[:k]
    pick.sort(key=lambda r: hashlib.sha1((r["field_raw"] + SALT + "dbl2").encode()).hexdigest())
    key = "\n".join(f"  {c}  {T.FAMILIES.get(c, '') if isinstance(T.FAMILIES, dict) else ''}"
                    for c in sorted(T.FAMILIES))
    lines = [
        "BLIND DOUBLE-LABEL SHEET -- CIP 2-digit family for each field-of-study string",
        "",
        "How: for each line write your code in the last column. Format per line:",
        "  <idx> <code>            e.g.  17 52",
        "  <idx> <code>/<second>   a defensible second code (lenient credit)",
        "  <idx> <code>?           you are unsure",
        "  <idx> XUN               the field string carries no field signal",
        "                          (GPA, honors, placeholder, institution name).",
        "Rules used by the first labeler (apply the same ones):",
        "  * compound strings ('X and Y', 'X, Y', 'X/Y') -> code the FIRST-listed field",
        "  * judge the field string; the degree line is context, not the answer",
        "  * a high-school diploma row with a real field ('mathematics') -> 53",
        "Score with:  uv run python -m edu_clean.gold_v1 agree YOUR_FILE.txt",
        "",
        "CODE KEY", key, "",
        f"{'idx':>4}\t{'field of study':<72}\t{'modal degree line':<28}\t{'rows':>5}\tcode",
    ]
    for r in pick:
        lines.append(f"{r['idx']:>4}\t{r['field_raw'][:72]:<72}\t{str(r['degree_modal'] or '')[:28]:<28}"
                     f"\t{r['n_rows']:>5}\t")
    SHEET.write_text("\n".join(lines) + "\n")
    print(f"wrote {SHEET} ({len(pick)} strings)")


def agree(path: str) -> dict:
    """Inter-annotator agreement between a second labeler's file (same line
    format as `label`) and the first labels: raw agreement, lenient agreement,
    Cohen's kappa on primary codes, per tier."""
    t = {r["idx"]: r for r in pq.read_table(OUT).to_pylist()}
    second = {}
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        code = parts[1].rstrip("?")
        p, _, s2 = code.partition("/")
        second[int(parts[0])] = (p, s2 or None)
    out = {"generated": date.today().isoformat(), "n": len(second), "tiers": {}}

    def kappa(pairs):
        n = len(pairs)
        if not n:
            return None
        po = sum(1 for a, b in pairs if a == b) / n
        cats = {c for ab in pairs for c in ab}
        pe = sum((sum(1 for a, _ in pairs if a == c) / n) * (sum(1 for _, b in pairs if b == c) / n)
                 for c in cats)
        return round((po - pe) / (1 - pe), 3) if pe < 1 else None
    groups = {"all": list(second)}
    for i in second:
        groups.setdefault(t[i]["tier"], []).append(i)
    print(f"{'tier':<12}{'n':>4}{'raw':>7}{'lenient':>9}{'kappa':>7}")
    for g, ids in groups.items():
        pairs = [(t[i]["gold_cip2"], second[i][0]) for i in ids]
        raw = sum(1 for a, b in pairs if a == b) / len(ids)
        len_ok = sum(1 for i in ids if second[i][0] in (t[i]["gold_cip2"], t[i]["gold_secondary"])
                     or t[i]["gold_cip2"] in second[i]) / len(ids)
        k = kappa(pairs)
        out["tiers"][g] = {"n": len(ids), "raw": round(raw, 3), "lenient": round(len_ok, 3), "kappa": k,
                           "disagreements": [(i, t[i]["field_raw"], t[i]["gold_cip2"], second[i][0])
                                             for i in ids if t[i]["gold_cip2"] != second[i][0]]}
        print(f"{g:<12}{len(ids):>4}{raw:>7.3f}{len_ok:>9.3f}{(k if k is not None else 0):>7.3f}")
    AGREE.write_text(json.dumps(out, indent=1))
    print(f"wrote {AGREE}")
    return out


def report() -> dict:
    """Numbers for the methods section: per-tier precision with Wilson 95%
    intervals, row shares per tier, row-weighted overall precision, the
    lenient-minus-strict gap (taxonomy ambiguity), the ambiguity pairs, and the
    recall bound implied by the residual sample."""
    sc = score(verbose=False, write=False)
    t = pq.read_table(OUT).to_pylist()
    con = duckdb.connect()
    src = dict(con.execute(f"""
      SELECT CASE WHEN e.cip_source = 'jury' AND j.method LIKE 'frontier%' THEN 'frontier'
                  WHEN e.cip_source = 'jury' THEN 'jury_llm' ELSE e.cip_source END AS tier, count(*)
      FROM read_parquet('{EDU}') e
      LEFT JOIN read_parquet('{ROOT / "normalized" / "mappings" / "field_cip_jury.parquet"}') j
        ON e.cip_source = 'jury' AND j.field_norm = lower(trim(e.field_raw))
      GROUP BY 1""").fetchall())
    total = sum(src.values())
    uncoded = src.get(None, 0)
    text_resid = con.execute(f"""SELECT count(*) FROM read_parquet('{EDU}')
      WHERE cip2_pooled IS NULL AND field_raw IS NOT NULL AND trim(field_raw) <> ''""").fetchone()[0]
    tiers = {}
    for tier in LANDED:
        d = sc["tiers"][tier]
        g = d["graded"]
        tiers[tier] = {
            "rows": src.get(tier, 0), "row_share_of_coded": round(src.get(tier, 0) / (total - uncoded), 4),
            "graded": g,
            "strict": d["strict"], "strict_ci95": _wilson(round(d["strict"] * g), g),
            "lenient": d["lenient"], "lenient_ci95": _wilson(round(d["lenient"] * g), g),
            "level": d["level"], "level_ci95": _wilson(round(d["level"] * g), g),
            "ambiguity_gap": round(d["lenient"] - d["strict"], 3),
        }
    tiers["degree_level"] = {"rows": src.get("degree_level", 0),
                             "row_share_of_coded": round(src.get("degree_level", 0) / (total - uncoded), 4),
                             "note": "by construction: uncoded high-school rows -> 53; not sampled"}
    measured = sum(tiers[x]["rows"] for x in LANDED)
    overall = {k: round(sum(tiers[x]["rows"] * tiers[x][k] for x in LANDED) / measured, 4)
               for k in ("strict", "lenient", "level")}
    # ambiguity pairs: gold primary vs system code accepted only under lenient
    pairs = {}
    for tier in LANDED:
        for f, srcx, sysc, g, g2 in sc["tiers"][tier]["lenient_misses"]:
            pass
    live = _live_codes(con, [r["field_raw"] for r in t])
    for r in t:
        if r["tier"] == "residual" or r["gold_cip2"] == "XUN":
            continue
        sysc = live[r["field_raw"]]["modal"][1]
        if sysc and sysc != r["gold_cip2"] and sysc == r["gold_secondary"]:
            k = f"{r['gold_cip2']}~{sysc}"
            pairs[k] = pairs.get(k, 0) + 1
    resid = sc["tiers"]["residual"]
    out = {
        "generated": date.today().isoformat(),
        "rows_total": total, "rows_coded": total - uncoded,
        "coverage_pct": round(100 * (total - uncoded) / total, 2),
        "tiers": tiers,
        "overall_row_weighted_over_measured_tiers": overall,
        "measured_rows": measured,
        "ambiguity_pairs": sorted(pairs.items(), key=lambda x: -x[1]),
        "recall_bound": {
            "uncoded_rows": uncoded, "uncoded_with_field_text": text_resid,
            "residual_codeable_share": resid["codeable_share"],
            "recoverable_rows_upper_bound": int(text_resid * resid["codeable_row_share"]),
            "recoverable_share_of_all_rows_pct": round(100 * text_resid * resid["codeable_row_share"] / total, 2),
        },
        "labeling": {"annotators": 1, "strings": len(t), "secondary_labels": sum(1 for r in t if r["gold_secondary"]),
                     "unsure": sum(1 for r in t if r["gold_unsure"]),
                     "double_label_sheet": str(SHEET.relative_to(ROOT))},
    }
    REPORT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "tiers"}, indent=1))
    for tier, d in tiers.items():
        print(tier, json.dumps(d))
    print(f"wrote {REPORT}")
    return out


if __name__ == "__main__":
    {"draw": draw, "label": lambda: label(sys.argv[2]), "score": score,
     "calibrate": lambda: calibrate(sys.argv[2], sys.argv[3]), "knn": knn,
     "sheet": sheet, "agree": lambda: agree(sys.argv[2]), "report": report}[sys.argv[1]]()
