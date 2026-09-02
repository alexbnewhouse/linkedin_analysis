"""Embedding-kNN classifier for the uncoded field-of-study tail (v3).

    uv run --group embed python -m edu_clean.knn_tail [--tau 0.90]

Seeds = every labeled distinct field string (deterministic CIP, jury-accepted,
frontier adjudication). v2 adds COMPOUND HANDLING, the dominant error in v1's
judged sample: "X and Y" / "X, Y" / "X/Y" strings are coded by their FIRST
component (the same first-listed rule the frontier adjudication uses):
  head_exact  head component is itself a labeled string -> that label
  head_knn    head component embedded (bge-base) -> nearest labeled string
  knn         no separator -> nearest labeled string on the whole string
All kNN paths require cosine >= tau (default 0.90, set from the 2026-09-01
frontier judgment of v1: strict precision 0.87 at 0.90-0.95 before the
compound fix). Propose-only: mappings/field_cip_knn.parquet + stats.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch

from edu_clean.common import ROOT
from edu_clean.nearest_neighbor import _cached_encode

VOCAB = ROOT / "edu_clean" / "cache" / "vocab_field.parquet"
EDU_FIELD = ROOT / "normalized" / "mappings" / "edu_field.parquet"
JURY = ROOT / "normalized" / "mappings" / "field_cip_jury.parquet"
FRONTIER = ROOT / "edu_clean" / "results" / "frontier_adjudication.jsonl"
OUT = ROOT / "normalized" / "mappings" / "field_cip_knn.parquet"
STATS = ROOT / "edu_clean" / "results" / "knn_tail_stats.json"
K = 5

_PAREN = re.compile(r"\([^)]*\)")
_TAIL = re.compile(r"\s+(?:with|w/|minor in|minor:|emphasis|concentration|specializ\w*)\b.*$", re.I)
_SEP = re.compile(r"\s*(?:,|;|/|\band\b|&|\+|:|\s-\s|\|)\s*", re.I)
# Components that are degree/honor/enrollment words, never a field (v3).
_NONFIELD = re.compile(
    r"^(?:associate|bachelor|master|doctor|ph\.?d|b\.?[as]\.?|a\.?[as]\.?|m\.?[as]\.?|mba|"
    r"cum laude|magna|summa|honou?rs?|major|minor|dual|double|concentration|specializ\w*|"
    r"degree|diploma|certificate|certification|graduated?|student|studies)\b", re.I)


def head_component(value: str) -> str | None:
    """First-listed field of a compound string, or None if not compound."""
    s = _PAREN.sub(" ", value or "")
    s = _TAIL.sub("", s)
    parts = [p.strip() for p in _SEP.split(s) if p and p.strip()]
    compound = len(parts) >= 2 or s.strip() != (value or "").strip()
    if not compound:
        return None
    for p in parts:                      # first component that is a real field
        if len(p) >= 3 and not _NONFIELD.match(p):
            return p
    return None


def norm(s: str | None) -> str:
    return (s or "").lower().strip()


def load():
    con = duckdb.connect()
    vocab = con.sql(f"SELECT value, freq FROM read_parquet('{VOCAB}')").fetchall()
    vocab = sorted(vocab, key=lambda r: (-r[1], r[0]))
    values = [r[0] for r in vocab]
    freqs = np.array([r[1] for r in vocab], dtype=np.int64)
    det = dict(con.sql(
        f"SELECT value, substr(canonical_id, 5, 2) FROM read_parquet('{EDU_FIELD}') "
        f"WHERE canonical_id LIKE 'cip:%'").fetchall())
    jury = dict(con.sql(f"SELECT field_norm, cip2 FROM read_parquet('{JURY}')").fetchall())
    frontier, abstain = {}, set()
    if FRONTIER.exists():
        for line in FRONTIER.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                if d.get("cip2") and d["cip2"] != "XUN":
                    frontier[d["field_norm"]] = d["cip2"]
                elif d.get("cip2") == "XUN":
                    abstain.add(d["field_norm"])   # judged non-field: never propose
    labels, by_norm = {}, {}
    for i, v in enumerate(values):
        k = norm(v)
        lab = det.get(v) or jury.get(k) or frontier.get(k)
        if lab:
            labels[i] = lab
        elif k in abstain:
            labels[i] = "XUN"                    # excluded from proposals below
    # Head-match index (v3): deterministic CIP labels always; jury/frontier
    # labels only for multi-token keys -- single words coded in a row's
    # context ('commercial' -> 53 for a high-school row) must not hijack heads.
    for v, lab in det.items():
        by_norm.setdefault(norm(v), lab)
    for k, lab in list(jury.items()) + list(frontier.items()):
        if len(k.split()) >= 2:
            by_norm.setdefault(k, lab)
    return values, freqs, labels, by_norm


def topk(q, ref, k, block=8192):
    sims, idxs = [], []
    for s in range(0, q.shape[0], block):
        v, i = (q[s:s + block] @ ref.T).topk(k, dim=1)
        sims.append(v.cpu()); idxs.append(i.cpu())
    return torch.cat(sims).numpy(), torch.cat(idxs).numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tau", type=float, default=0.95)
    args = ap.parse_args()
    t0 = time.monotonic()
    values, freqs, labels, by_norm = load()
    print(f"vocab {len(values):,}; labeled {len(labels):,}; label index {len(by_norm):,}", flush=True)

    emb = _cached_encode("bge-base", values, "field_values").astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    E = torch.from_numpy(emb).to(dev)
    lab_idx = np.array(sorted(i for i, l in labels.items() if l != "XUN"))
    ref = E[lab_idx]
    ref_labels = [labels[i] for i in lab_idx]

    unl = [i for i in range(len(values)) if i not in labels]
    rows = []   # (value, field_norm, cip2, sim, n_rows, method)
    plain, head_q, head_txt = [], [], []
    for i in unl:
        h = head_component(values[i])
        if h is None:
            plain.append(i); continue
        lab = by_norm.get(norm(h))
        if lab:
            rows.append((values[i], norm(values[i]), lab, 1.0, int(freqs[i]), "head_exact"))
        elif len(h.split()) >= 2:            # single-word heads are too ambiguous for kNN
            head_q.append(i); head_txt.append(h)
        else:
            plain.append(i)
    print(f"unlabeled {len(unl):,}: plain {len(plain):,}, head_exact {len(rows):,}, "
          f"head_knn queue {len(head_q):,}", flush=True)

    sims, idxs = topk(E[plain], ref, K)
    for r, i in enumerate(plain):
        if sims[r, 0] >= args.tau:
            rows.append((values[i], norm(values[i]), ref_labels[idxs[r, 0]], float(sims[r, 0]),
                         int(freqs[i]), "knn"))

    if head_txt:
        hemb = _cached_encode("bge-base", head_txt, "head_components").astype(np.float32)
        hemb /= np.linalg.norm(hemb, axis=1, keepdims=True) + 1e-9
        hs, hi = topk(torch.from_numpy(hemb).to(dev), ref, K)
        for r, i in enumerate(head_q):
            if hs[r, 0] >= args.tau:
                rows.append((values[i], norm(values[i]), ref_labels[hi[r, 0]], float(hs[r, 0]),
                             int(freqs[i]), "head_knn"))

    by_m = {}
    for row in rows:
        s = by_m.setdefault(row[5], [0, 0]); s[0] += 1; s[1] += row[4]
    print("proposed by method (strings, rows):", by_m)
    print(f"total proposed {len(rows):,} strings / {sum(r[4] for r in rows):,} rows "
          f"(of {len(unl):,} strings / {int(freqs[unl].sum()):,} rows)")
    pq.write_table(pa.table({
        "value": [r[0] for r in rows], "field_norm": [r[1] for r in rows],
        "cip2": [r[2] for r in rows], "sim": [r[3] for r in rows],
        "n_rows": [r[4] for r in rows], "method": [r[5] for r in rows],
    }), OUT, compression="zstd")
    STATS.write_text(json.dumps({"generated": date.today().isoformat(), "version": 2,
                                 "tau": args.tau, "k": K,
                                 "by_method": {m: {"strings": s[0], "rows": s[1]} for m, s in by_m.items()},
                                 "labeled_seeds": len(labels)}, indent=1))
    print(f"wrote {OUT} in {time.monotonic()-t0:.0f}s")


if __name__ == "__main__":
    main()
