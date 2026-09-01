"""Hybrid canonicalizer, designed from the benchmark findings.

Findings that drive the design:
  * Reference/rule layers (CIP exact, degree taxonomy, school slug) give
    precision 1.0 -> they must be the BACKBONE and win whenever they fire.
  * Fuzzy token matching adds typo tolerance on the tail at precision 1.0, but
    cannot expand abbreviations or merge cardinality-different variants.
  * Embedding *clustering* has poor precision (it conflates siblings/levels) ->
    never used to merge autonomously. Embeddings are only used, with lexical
    guardrails, to (a) raise CIP coverage on the unmatched field tail.

Layered precedence per value (first that fires wins):
  field : CIP-exact/token  ->  typo-cluster  ->  guarded anchored-CIP  ->  raw
  degree: taxonomy parse    ->  (taxonomy already ~complete)            ->  raw
  title : slug / name->slug ->  typo-cluster                            ->  raw

Each value also gets a `method` tag + `confidence`, enabling a review queue.
"""

from __future__ import annotations

from . import approach_a_rules as A
from . import approach_b_fuzzy as B
from . import approach_c_embed as C
from .common import Result, normalize, timer, token_key

ANCHOR_COS = 0.60  # min cosine for an anchored-CIP assignment
# Guardrail: only collapse a value onto a CIP anchor when the value is NOT more
# specific than the anchor (its content tokens are a subset of the anchor's).
# This stops combined/specialized variants ("Computer Science and Engineering",
# "Mechanical Engineering Technology") from being merged onto a general anchor.
ANCHOR_GUARD = True


def _b_cluster_map(field_name: str, vocab: list[tuple]) -> dict:
    """Representative string per value from the guarded fuzzy clusterer."""
    return B.run(field_name, vocab).mapping


def _anchored_field(vocab: list[tuple], threshold: float):
    """Nearest-CIP assignment with the anchor title's tokens, for guardrailing."""
    import csv

    import torch

    from .common import ROOT

    anchors = []
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
    a_codes = [c for c, _ in anchors]
    a_tokens = [token_key(t) for _, t in anchors]
    a_emb = C.embed([t for _, t in anchors])
    values = [r[0] for r in vocab]
    v_emb = C.embed(values)
    out = {}
    aT = a_emb.t().contiguous()
    blk = 4096
    for s in range(0, len(values), blk):
        sims = v_emb[s : s + blk] @ aT
        best_sim, best_idx = sims.max(dim=1)
        for k in range(best_idx.shape[0]):
            v = values[s + k]
            ai = int(best_idx[k])
            if float(best_sim[k]) >= threshold:
                vtok = token_key(v)
                # accept only if value shares a token AND is not more specific
                # than the anchor (value tokens subset of anchor tokens)
                ok = bool(vtok & a_tokens[ai]) and vtok <= a_tokens[ai]
                if (not ANCHOR_GUARD) or ok:
                    out[v] = (f"cip:{a_codes[ai]}", float(best_sim[k]))
    del a_emb, v_emb
    torch.cuda.empty_cache()
    return out


def run(field_name: str, vocab: list[tuple]) -> Result:
    with timer() as t:
        a_map = A.run(field_name, vocab).mapping
        method = {}
        final = {}

        if field_name == "degree":
            # taxonomy is the whole story; raw -> keep normalized self
            for v, *_ in vocab:
                aid = a_map[v]
                final[v] = aid
                method[v] = "taxonomy" if not aid.startswith("raw:") else "raw"

        elif field_name == "title":
            b_map = _b_cluster_map(field_name, vocab)
            for v, *_ in vocab:
                aid = a_map[v]
                if aid.startswith("slug:"):
                    final[v], method[v] = aid, "slug"
                else:
                    # tail: adopt fuzzy-cluster representative (typo merge)
                    final[v], method[v] = f"name:{normalize(b_map[v])}", "typo"

        elif field_name == "field":
            b_map = _b_cluster_map(field_name, vocab)
            anchored = _anchored_field(vocab, ANCHOR_COS)
            for v, *_ in vocab:
                aid = a_map[v]
                if aid.startswith("cip:"):
                    final[v], method[v] = aid, "cip_exact"
                elif v in anchored:
                    final[v], method[v] = anchored[v][0], "cip_anchor"
                else:
                    final[v], method[v] = f"raw:{normalize(b_map[v])}", "typo"
        else:
            raise ValueError(field_name)

    # confidence by method
    conf = {
        "slug": 1.0,
        "taxonomy": 1.0,
        "cip_exact": 1.0,
        "typo": 0.9,
        "cip_anchor": 0.7,
        "raw": 0.5,
    }
    method_counts: dict[str, int] = {}
    row_by_method: dict[str, int] = {}
    for v, f, *_ in vocab:
        method_counts[method[v]] = method_counts.get(method[v], 0) + 1
        row_by_method[method[v]] = row_by_method.get(method[v], 0) + f
    total = sum(f for _v, f, *_ in vocab)
    row_pct = {m: round(100 * c / total, 1) for m, c in row_by_method.items()}
    return Result(
        name="HYBRID",
        field=field_name,
        mapping=final,
        runtime_s=t.elapsed,
        extra={"row_pct_by_method": row_pct, "_confidence": conf},
    )
