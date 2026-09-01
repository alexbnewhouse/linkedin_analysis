"""Embedding nearest-neighbor variants for field-to-CIP anchoring.

Two approaches are implemented for evaluation:

* global: choose the nearest CIP title globally, then threshold by cosine.
* strict: choose the nearest CIP title only among lexically eligible anchors,
  where value tokens are a subset of anchor tokens.

The strict mode is the improved guarded approach: apply the lexical guard before
nearest-neighbor selection so a bad global nearest anchor does not hide a valid
second-best eligible anchor.
"""

from __future__ import annotations

import csv
import hashlib
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

from .common import CACHE, ROOT, timer, token_key
from .encoder_bench import encode
from .final_hybrid import DetailedResult, raw_id

MODE_GLOBAL = "global"
MODE_STRICT = "strict"


def load_cip_anchors() -> list[tuple[str, str]]:
    anchors: list[tuple[str, str]] = []
    with (ROOT / "reference" / "cip_codes.csv").open(
        newline="", encoding="utf-8"
    ) as fh:
        for row in csv.DictReader(fh):
            code = (row.get("CIPCode") or "").strip()
            title = (row.get("CIPTitle") or "").strip().rstrip(".")
            typ = (row.get("Type") or "").strip().lower()
            definition = (row.get("CIPDefinition") or "").lower()
            if (
                title
                and len(code) >= 4
                and typ != "remedial"
                and "not valid for ipeds reporting" not in definition
            ):
                anchors.append((code, title))
    return anchors


def _fingerprint(texts: list[str]) -> str:
    h = hashlib.sha1()
    for text in texts:
        h.update((text or "").encode("utf-8", errors="surrogatepass"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def _cache_path(model: str, kind: str, texts: list[str]) -> Path:
    safe_model = model.replace("/", "_").replace("-", "_")
    return CACHE / f"nn_{safe_model}_{kind}_{len(texts)}_{_fingerprint(texts)}.npy"


def _cached_encode(model: str, texts: list[str], kind: str) -> np.ndarray:
    path = _cache_path(model, kind, texts)
    if path.exists():
        arr = np.load(path)
        if arr.shape[0] == len(texts):
            return arr
    arr = encode(model, texts)
    np.save(path, arr)
    return arr


def _strict_eligible_indices(
    values: list[str], anchor_tokens: list[frozenset[str]]
) -> list[list[int]]:
    by_token: dict[str, set[int]] = defaultdict(set)
    for i, toks in enumerate(anchor_tokens):
        for tok in toks:
            by_token[tok].add(i)

    out: list[list[int]] = []
    for value in values:
        vtoks = token_key(value)
        candidates: set[int] = set()
        for tok in vtoks:
            candidates.update(by_token.get(tok, ()))
        out.append([i for i in candidates if vtoks <= anchor_tokens[i]])
    return out


def _rank_global(
    value_emb: np.ndarray, anchor_emb: np.ndarray, block: int
) -> tuple[np.ndarray, np.ndarray, float]:
    best_sim = np.full(value_emb.shape[0], -np.inf, dtype=np.float32)
    best_idx = np.full(value_emb.shape[0], -1, dtype=np.int32)
    t0 = time.monotonic()
    anchors = torch.tensor(anchor_emb, device="cuda")
    for start in range(0, value_emb.shape[0], block):
        end = min(start + block, value_emb.shape[0])
        values = torch.tensor(value_emb[start:end], device="cuda")
        sims = values @ anchors.t()
        bs, bi = sims.max(dim=1)
        best_sim[start:end] = bs.float().cpu().numpy()
        best_idx[start:end] = bi.int().cpu().numpy()
        del values, sims, bs, bi
    torch.cuda.empty_cache()
    return best_idx, best_sim, time.monotonic() - t0


def _rank_strict(
    values_raw: list[str],
    value_emb: np.ndarray,
    anchor_emb: np.ndarray,
    anchor_tokens: list[frozenset[str]],
    block: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    eligible = _strict_eligible_indices(values_raw, anchor_tokens)
    best_sim = np.full(value_emb.shape[0], -np.inf, dtype=np.float32)
    best_idx = np.full(value_emb.shape[0], -1, dtype=np.int32)
    t0 = time.monotonic()
    anchors = torch.tensor(anchor_emb, device="cuda")
    for start in range(0, value_emb.shape[0], block):
        end = min(start + block, value_emb.shape[0])
        values = torch.tensor(value_emb[start:end], device="cuda")
        sims = values @ anchors.t()
        mask = torch.zeros(sims.shape, dtype=torch.bool, device="cuda")
        for row, idxs in enumerate(eligible[start:end]):
            if idxs:
                mask[row, idxs] = True
        sims.masked_fill_(~mask, float("-inf"))
        bs, bi = sims.max(dim=1)
        best_sim[start:end] = bs.float().cpu().numpy()
        best_idx[start:end] = bi.int().cpu().numpy()
        del values, sims, mask, bs, bi
    torch.cuda.empty_cache()
    return best_idx, best_sim, time.monotonic() - t0


def run_field(
    vocab: list[tuple],
    *,
    mode: str,
    model: str = "bge-base",
    threshold: float = 0.75,
    block: int = 4096,
    use_cache: bool = True,
) -> DetailedResult:
    if mode not in {MODE_GLOBAL, MODE_STRICT}:
        raise ValueError(f"unknown nearest-neighbor mode: {mode}")

    with timer() as t:
        # DuckDB's frequency-only ORDER BY can return tied values in different
        # orders across processes. Sort here so embedding caches are stable and
        # value/embedding alignment is deterministic.
        vocab = sorted(vocab, key=lambda row: (-row[1], row[0]))
        anchors = load_cip_anchors()
        codes = [c for c, _title in anchors]
        titles = [title for _c, title in anchors]
        values = [row[0] for row in vocab]
        freqs = np.array([row[1] for row in vocab], dtype=np.int64)

        encode_t0 = time.monotonic()
        if use_cache:
            anchor_emb = _cached_encode(model, titles, "cip_anchors")
            value_emb = _cached_encode(model, values, "field_values")
        else:
            anchor_emb = encode(model, titles)
            value_emb = encode(model, values)
        encode_s = time.monotonic() - encode_t0

        if mode == MODE_GLOBAL:
            best_idx, best_sim, rank_s = _rank_global(value_emb, anchor_emb, block)
        else:
            anchor_tokens = [token_key(title) for title in titles]
            best_idx, best_sim, rank_s = _rank_strict(
                values, value_emb, anchor_emb, anchor_tokens, block
            )

        mapping: dict[str, str] = {}
        method: dict[str, str] = {}
        conf: dict[str, float] = {}
        matched_rows = 0
        for i, value in enumerate(values):
            if best_idx[i] >= 0 and float(best_sim[i]) >= threshold:
                mapping[value] = f"cip:{codes[int(best_idx[i])]}"
                method[value] = f"nn_{mode}"
                conf[value] = float(best_sim[i])
                matched_rows += int(freqs[i])
            else:
                mapping[value] = raw_id("field_raw", value)
                method[value] = "raw"
                conf[value] = 0.5

    total_rows = int(freqs.sum())
    return DetailedResult(
        name=f"nn_{mode}_{model}@{threshold:g}",
        field="field",
        mapping=mapping,
        runtime_s=t.elapsed,
        method=method,
        confidence=conf,
        extra={
            "model": model,
            "mode": mode,
            "threshold": threshold,
            "reference_match_row_pct": round(100 * matched_rows / total_rows, 1),
            "embed_s": round(encode_s, 1),
            "rank_s": round(rank_s, 1),
        },
    )
