"""Phase 2+3 — assign every role_canonical to an archetype.

Rules-first (archetype_spec.assign_role), then an embedding fallback for roles
the rules leave 'unresolved' (nearest archetype descriptor by cosine, above a
threshold AND with a margin over the 2nd-best; else OTHER). Emits
role_archetype.parquet.

A modal SOC code is trusted only when it is backed by enough steps (support)
and covers enough of the role's steps — a code resting on a handful of coded
steps out of thousands (e.g. "owner" -> 29-1229 from 5 steps) is dropped so the
role falls through to keyword/founders instead of a spurious archetype.
"""

from __future__ import annotations

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import common as C
from . import archetype_spec as S

SUPPORT_FLOOR = 5           # min persons for a role to earn an embedding call
SOC_MIN_SUPPORT = 10        # min modal-code steps to trust a SOC code
# min share of the role's steps on the modal code. Kept LOW (occupation_code
# only covers ~21.5% of steps, so a well-coded role often has <25% coded) — the
# absolute support floor does the real work; the fraction only kills codes that
# rest on a trivial sliver of a huge role (e.g. owner: 5 coded of thousands).
SOC_MIN_FRAC = 0.05
EMBED_MIN_COSINE = 0.45     # below this, an embedded role stays OTHER
EMBED_MIN_MARGIN = 0.05     # best must beat 2nd-best target by this
EMBED_MODEL = "all-MiniLM-L6-v2"


def _trust(code, support, n_steps) -> bool:
    return (code is not None and support is not None
            and support >= SOC_MIN_SUPPORT
            and n_steps and support / n_steps >= SOC_MIN_FRAC)


def _rules_pass(t: pa.Table):
    n = t.num_rows
    role_text = t.column("role_text").to_pylist()
    soc_detail = t.column("soc_detail").to_pylist()
    soc_major = t.column("soc_major").to_pylist()
    owner_share = t.column("owner_share").to_pylist()
    n_steps = t.column("n_steps").to_pylist()
    d_sup = t.column("soc_detail_support").to_pylist()
    m_sup = t.column("soc_major_support").to_pylist()

    ids, methods = [], []
    for i in range(n):
        ns = n_steps[i]
        detail = soc_detail[i] if _trust(soc_detail[i], d_sup[i], ns) else None
        major = soc_major[i] if _trust(soc_major[i], m_sup[i], ns) else None
        f = S.RoleFeatures(
            soc_detail=detail,
            soc_major=major,
            role_text=role_text[i] or "",
            employment_owner=(owner_share[i] or 0.0) > 0.5,
        )
        aid, method, _conf = S.assign_role(f)
        ids.append(aid)
        methods.append(method)
    return ids, methods


def _embed_fallback(t: pa.Table, ids, methods):
    """Resolve rules-'unresolved' roles (with enough support) by nearest
    archetype descriptor cosine, requiring a margin over the runner-up."""
    import torch
    from sentence_transformers import SentenceTransformer

    n_persons = t.column("n_persons").to_pylist()
    role_text = t.column("role_text").to_pylist()
    idx = [i for i in range(len(ids))
           if methods[i] == "unresolved"
           and (n_persons[i] or 0) >= SUPPORT_FLOOR
           and role_text[i]]
    cosines = [None] * len(ids)
    if not idx:
        return ids, methods, cosines, 0

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(EMBED_MODEL, device=device)
    # Target archetypes 1..15 (OTHER=0 is the residual, never an embed target).
    targets = [(aid, key) for aid, key, _, _ in S.ARCHETYPES if aid != 0]
    tgt_ids = [a for a, _ in targets]
    tgt_desc = [S.DESCRIPTOR_BY_KEY[k] for _, k in targets]
    tgt_vec = model.encode(tgt_desc, normalize_embeddings=True,
                           convert_to_numpy=True)

    texts = [role_text[i] for i in idx]
    vec = model.encode(texts, normalize_embeddings=True, batch_size=512,
                       convert_to_numpy=True, show_progress_bar=False)
    sims = vec @ tgt_vec.T                          # (n_idx, n_targets)
    order = np.argsort(-sims, axis=1)
    best = order[:, 0]
    best_sim = sims[np.arange(len(idx)), best]
    second_sim = sims[np.arange(len(idx)), order[:, 1]]

    n_embedded = 0
    for k, i in enumerate(idx):
        if (best_sim[k] >= EMBED_MIN_COSINE
                and best_sim[k] - second_sim[k] >= EMBED_MIN_MARGIN):
            ids[i] = tgt_ids[best[k]]
            methods[i] = "embed"
            cosines[i] = float(round(best_sim[k], 3))
            n_embedded += 1
        # else: remains OTHER / unresolved
    return ids, methods, cosines, n_embedded


def build() -> dict:
    feats = C.RESULTS / "role_features.parquet"
    t = pq.read_table(feats)

    ids, methods = _rules_pass(t)
    ids, methods, cosines, n_embedded = _embed_fallback(t, ids, methods)

    # Anything still 'unresolved' -> OTHER, method 'residual_other'.
    for i in range(len(methods)):
        if methods[i] == "unresolved":
            methods[i] = "residual_other"

    labels = [S.LABEL_BY_ID[a] for a in ids]
    keys = [S.KEY_BY_ID[a] for a in ids]
    out = pa.table({
        "role_canonical": t.column("role_canonical"),
        "archetype_id": pa.array(ids, pa.int8()),
        "archetype_key": pa.array(keys),
        "archetype_label": pa.array(labels),
        "assign_method": pa.array(methods),
        "embed_cosine": pa.array(cosines, pa.float32()),
        "n_persons": t.column("n_persons"),
        "n_steps": t.column("n_steps"),
    })
    dst = C.RESULTS / "role_archetype.parquet"
    pq.write_table(out, dst)

    # Mirror into normalized/mappings for reuse across the repo.
    mirror = C.ROOT / "normalized" / "mappings" / "role_archetype.parquet"
    pq.write_table(out.select(["role_canonical", "archetype_id",
                               "archetype_key", "assign_method",
                               "embed_cosine"]), mirror)
    return {"n_roles": out.num_rows, "n_embedded": n_embedded, "path": str(dst)}
