"""Approach C: semantic embeddings on GPU (CUDA).

Two modes:
  * cluster  - embed every distinct value, find all pairs with cosine >= T via
               blocked GPU matmul, union-find them. Canonical = top-freq member.
  * anchored - embed a reference anchor set (CIP titles for `field`); assign
               each value to its nearest anchor if cosine >= T, else leave it
               on its own. Canonical = the anchor.

Embeddings capture meaning (PSYCHOLOGY == Psychology, & == and) but are blind to
character typos (english vs engilsh ~ 0.50) and over-rate distinct combinations
(Computer Science vs Computer Science and Engineering ~ 0.88) - so threshold
choice trades precision against recall. All heavy math runs on the GPU.
"""

from __future__ import annotations

import csv

import torch

from .common import ROOT, Result, normalize, timer

_MODEL = "all-MiniLM-L6-v2"
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(_MODEL, device="cuda")
    return _model


def embed(texts: list[str], batch_size: int = 1024) -> torch.Tensor:
    """Return L2-normalized fp16 embeddings on the GPU."""
    model = _get_model()
    emb = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=False,
        device="cuda",
    )
    return emb.half()


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _cluster_pairs(emb: torch.Tensor, threshold: float, row_block: int = 2048):
    """Yield (i, j) index pairs with cosine >= threshold, i < j, via GPU matmul."""
    n = emb.shape[0]
    embT = emb.t().contiguous()
    for start in range(0, n, row_block):
        end = min(start + row_block, n)
        sims = emb[start:end] @ embT  # [block, n] fp16
        # keep only upper triangle (global j > i) and above threshold
        idx = (sims >= threshold).nonzero(as_tuple=False)
        if idx.numel() == 0:
            continue
        local_i = idx[:, 0] + start
        j = idx[:, 1]
        keep = j > local_i
        if keep.any():
            li = local_i[keep].tolist()
            lj = j[keep].tolist()
            yield from zip(li, lj)


def run(field_name: str, vocab: list[tuple], threshold: float = 0.90) -> Result:
    with timer() as t:
        values = [row[0] for row in vocab]
        freqs = [row[1] for row in vocab]
        emb = embed(values)
        uf = _UF(len(values))
        for i, j in _cluster_pairs(emb, threshold):
            uf.union(i, j)
        best: dict[int, int] = {}
        for i in range(len(values)):
            r = uf.find(i)
            if r not in best or freqs[i] > freqs[best[r]]:
                best[r] = i
        mapping = {values[i]: values[best[uf.find(i)]] for i in range(len(values))}
    del emb
    torch.cuda.empty_cache()
    return Result(
        name=f"C_embed@{threshold}",
        field=field_name,
        mapping=mapping,
        runtime_s=t.elapsed,
        extra={"clusters": len(set(mapping.values())), "threshold": threshold},
    )


# ----------------------- anchored variant (field/CIP) --------------------
def _load_cip_titles() -> list[tuple[str, str]]:
    out = []
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
                out.append((code, title))
    return out


def run_anchored_field(vocab: list[tuple], threshold: float = 0.70) -> Result:
    """Assign each field value to its nearest CIP title by embedding cosine."""
    with timer() as t:
        anchors = _load_cip_titles()
        a_codes = [c for c, _ in anchors]
        a_emb = embed([title for _, title in anchors])
        values = [row[0] for row in vocab]
        v_emb = embed(values)
        mapping = {}
        block = 4096
        aT = a_emb.t().contiguous()
        for start in range(0, len(values), block):
            sims = v_emb[start : start + block] @ aT  # [block, n_anchor]
            best_sim, best_idx = sims.max(dim=1)
            for k in range(best_idx.shape[0]):
                v = values[start + k]
                if float(best_sim[k]) >= threshold:
                    mapping[v] = f"cip:{a_codes[int(best_idx[k])]}"
                else:
                    mapping[v] = f"raw:{normalize(v)}"
    del a_emb, v_emb
    torch.cuda.empty_cache()
    total = sum(f for _v, f, *_ in vocab)
    matched = sum(f for v, f, *_ in vocab if mapping[v].startswith("cip:"))
    return Result(
        name=f"C_anchored@{threshold}",
        field="field",
        mapping=mapping,
        runtime_s=t.elapsed,
        extra={
            "reference_match_row_pct": round(100 * matched / total, 1),
            "clusters": len(set(mapping.values())),
        },
    )
