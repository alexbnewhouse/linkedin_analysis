"""Approach C: semantic embeddings on GPU (CUDA). Mirrors edu_clean Approach C.

Two modes:
  * cluster  - embed every distinct value, union-find all pairs with cosine >= T
               (blocked GPU matmul). Canonical = top-freq member.
  * anchored - (company only) build one anchor name per company_id (its
               highest-frequency spelling), embed the anchors, and assign each
               no-id name to the nearest anchor's id if cosine >= T. This is the
               organization analogue of edu's anchored-to-CIP and is the only
               embedding mode that scales past the head, since #anchors << #values.

Embeddings capture meaning/format (case, '&'-and, paraphrase) but are blind to
character typos and over-rate distinct-but-related values (sibling companies,
adjacent seniorities) -- so the threshold trades precision against recall, and
the cluster mode must be capped to the frequent head (it is O(n^2)).
"""

from __future__ import annotations

import torch

from .common import Result, normalize, timer
from .occupation import load_onet

_MODEL = "all-MiniLM-L6-v2"
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(_MODEL, device="cuda")
    return _model


def embed(texts: list[str], batch_size: int = 1024) -> torch.Tensor:
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
    n = emb.shape[0]
    embT = emb.t().contiguous()
    for start in range(0, n, row_block):
        end = min(start + row_block, n)
        sims = emb[start:end] @ embT
        idx = (sims >= threshold).nonzero(as_tuple=False)
        if idx.numel() == 0:
            continue
        local_i = idx[:, 0] + start
        j = idx[:, 1]
        keep = j > local_i
        if keep.any():
            yield from zip(local_i[keep].tolist(), j[keep].tolist())


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


# ----------------------- anchored variant (company) ----------------------
def run_anchored_company(vocab: list[tuple], threshold: float = 0.80) -> Result:
    """Assign each company name to the nearest company_id anchor by cosine."""
    with timer() as t:
        # one anchor name per id: its highest-frequency spelling in the vocab
        anchor_name: dict[str, str] = {}
        anchor_freq: dict[str, int] = {}
        for value, freq, modal_id in vocab:
            if not modal_id:
                continue
            if modal_id not in anchor_freq or freq > anchor_freq[modal_id]:
                anchor_freq[modal_id] = freq
                anchor_name[modal_id] = value
        a_ids = list(anchor_name)
        a_emb = embed([anchor_name[i] for i in a_ids])

        values = [row[0] for row in vocab]
        ids = [row[2] for row in vocab]
        v_emb = embed(values)
        mapping = {}
        aT = a_emb.t().contiguous()
        block = 4096
        for start in range(0, len(values), block):
            sims = v_emb[start : start + block] @ aT
            best_sim, best_idx = sims.max(dim=1)
            for k in range(best_idx.shape[0]):
                gi = start + k
                v = values[gi]
                if ids[gi]:  # already has its own id -> trust it
                    mapping[v] = f"id:{ids[gi]}"
                elif float(best_sim[k]) >= threshold:
                    mapping[v] = f"id:{a_ids[int(best_idx[k])]}"
                else:
                    mapping[v] = f"raw:{normalize(v)}"
    del a_emb, v_emb
    torch.cuda.empty_cache()
    total = sum(f for _v, f, *_ in vocab)
    matched = sum(f for v, f, *_ in vocab if mapping[v].startswith("id:"))
    return Result(
        name=f"C_anchored@{threshold}",
        field="company",
        mapping=mapping,
        runtime_s=t.elapsed,
        extra={
            "reference_match_row_pct": round(100 * matched / total, 1),
            "clusters": len(set(mapping.values())),
        },
    )


# ----------------------- anchored variant (occupation) -------------------
def anchored_occupation_proposals(
    values: list[str], threshold: float = 0.70, chunk: int = 100_000
):
    """Yield ``(value, soc_code, anchor_title, cosine)`` for each value whose
    nearest O*NET anchor reaches ``threshold``.

    Streaming/production variant of ``run_anchored_occupation``: same anchors,
    same nearest-anchor assignment, but it keeps the cosine evidence (for the
    review queue / confidence thresholds downstream) and embeds values in
    bounded chunks so the full multi-million-value vocabulary fits on the GPU.
    PROPOSE-ONLY by contract -- callers must never merge these autonomously.
    """
    by_norm, _by_tokens, _c2t = load_onet()
    anchor_texts = list(by_norm)
    anchor_soc = [by_norm[k] for k in anchor_texts]
    aT = embed(anchor_texts).t().contiguous()
    block = 4096
    for cstart in range(0, len(values), chunk):
        cvals = values[cstart : cstart + chunk]
        v_emb = embed(cvals)
        for start in range(0, len(cvals), block):
            sims = v_emb[start : start + block] @ aT
            best_sim, best_idx = sims.max(dim=1)
            for k in range(best_idx.shape[0]):
                cos = float(best_sim[k])
                if cos >= threshold:
                    j = int(best_idx[k])
                    yield cvals[start + k], anchor_soc[j], anchor_texts[j], cos
        del v_emb
        torch.cuda.empty_cache()


def run_anchored_occupation(vocab: list[tuple], threshold: float = 0.70) -> Result:
    """Assign each title to the nearest O*NET title anchor's SOC code by cosine.

    Propose-only backstop for the review queue: it extends SOC coverage onto the
    tail the deterministic lexicon misses, but (per the encoder study) over-rates
    distinct-but-related occupations, so it is never an autonomous merger.
    """
    with timer() as t:
        by_norm, _by_tokens, _c2t = load_onet()
        anchor_texts = list(by_norm)
        anchor_soc = [by_norm[k] for k in anchor_texts]
        a_emb = embed(anchor_texts)
        values = [row[0] for row in vocab]
        v_emb = embed(values)
        mapping = {}
        aT = a_emb.t().contiguous()
        block = 4096
        for start in range(0, len(values), block):
            sims = v_emb[start : start + block] @ aT
            best_sim, best_idx = sims.max(dim=1)
            for k in range(best_idx.shape[0]):
                v = values[start + k]
                if float(best_sim[k]) >= threshold:
                    mapping[v] = f"soc:{anchor_soc[int(best_idx[k])]}"
                else:
                    mapping[v] = f"raw:{normalize(v)}"
    del a_emb, v_emb
    torch.cuda.empty_cache()
    total = sum(f for _v, f, *_ in vocab)
    matched = sum(f for v, f, *_ in vocab if mapping[v].startswith("soc:"))
    return Result(
        name=f"C_occ_anchored@{threshold}",
        field="occupation",
        mapping=mapping,
        runtime_s=t.elapsed,
        extra={
            "reference_match_row_pct": round(100 * matched / total, 1),
            "clusters": len(set(mapping.values())),
        },
    )
