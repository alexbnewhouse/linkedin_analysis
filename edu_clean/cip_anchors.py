"""Retrieval anchors for the CIP jury: nearest already-coded field strings.

For each item we retrieve the nearest field strings that the deterministic
coder ALREADY mapped (the committed field->cip mapping itself, read from
``cip_gold.parquet``: field_norm -> dominant cip2 at dominance >= 0.90) with
their true families, so the rubric can tell the jury to follow the mapping's
CONVENTIONS -- the same fix that took the SOC jury past its calibration gate
(soc_anchors.py).

Transferability guard (load-bearing lesson from the SOC jury's 2026-07-08
adversarial review, which found the label-generating lexicon entry leaking
into 41/600 gold items and inflating measured unanimity): retrieval excludes
any index entry matching the item at EVERY grain the deterministic field
coder matches on. The surfaces found in ``final_hybrid.canon_field`` /
``approach_a_rules._load_cip`` are:

  * cip_override / cip_alias -- dicts keyed by ``common.normalize(value)``
    (exact-normalized grain);
  * cip_exact -- CIP-title match at exact-normalized grain AND at soft-stop
    ``common.token_key`` grain (order-independent token set with fillers like
    "general/and/of/in" dropped);
  * typo_to_cip -- ``approach_b_fuzzy`` cluster representative resolved to a
    CIP id: metaphone-blocked, equal-token-cardinality, per-token
    rapidfuzz.ratio >= 85 typo matching. This surface is FUZZY, so gold
    anchors cannot be made fully leak-proof against it and calibration may be
    slightly optimistic; mitigation: anchors with Jaccard >= 0.85 to the item
    are ALSO excluded (a per-token >= 85 typo match at equal cardinality
    implies near-identical token sets, which high Jaccard catches).

Accordingly an entry is excluded when it equals the item at exact-normalized
grain, exact-token-set grain, soft-stop token_key grain, or Jaccard >= 0.85.
A gold item therefore never sees the very entry that generated its label
(exact surfaces) and almost never a fuzzy-reachable twin; it sees only
neighbors, like a candidate would.
"""

from __future__ import annotations

from collections import defaultdict

import duckdb

from edu_clean import cip_candidates as SC
from edu_clean import cip_taxonomy as T
from edu_clean import common as CC

TOP_K = 5
MIN_JACCARD = 0.34   # at least ~1/3 token overlap before an anchor is shown
MAX_JACCARD = 0.85   # fuzzy-surface (typo_to_cip) leak mitigation; >= excluded

_STATE: dict = {}


def _index():
    """Inverted token index over the committed field->cip2 gold mapping
    (built once from cip_gold.parquet; dominance >= 0.90 already enforced)."""
    if _STATE:
        return _STATE
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT field_norm, gold_cip2 FROM read_parquet('{SC.GOLD}')").fetchall()
    con.close()
    entries = []            # (display_norm, frozenset(tokens), cip2)
    inv = defaultdict(set)  # token -> entry indices
    seen = set()
    for field_norm, cip2 in rows:
        norm = CC.normalize(field_norm)
        toks = frozenset(norm.split())
        if not toks or (toks, cip2) in seen:
            continue
        seen.add((toks, cip2))
        idx = len(entries)
        entries.append((norm, toks, cip2))
        for t in toks:
            inv[t].add(idx)
    _STATE["entries"] = entries
    _STATE["inv"] = inv
    return _STATE


def anchors_for(field_norm: str | None) -> list[str]:
    """Top-K nearest coded field strings as 'field -> code label' strings.

    Matches at any deterministic-coder grain are EXCLUDED (see module
    docstring). Returns [] when nothing clears MIN_JACCARD -- the evidence
    line is then omitted, never invented."""
    if not field_norm:
        return []
    st = _index()
    norm = CC.normalize(field_norm)
    toks = frozenset(norm.split())
    if not toks:
        return []
    item_key = CC.token_key(field_norm)    # soft-stop-dropping matcher grain
    cand: dict[int, int] = defaultdict(int)
    for t in toks:
        for idx in st["inv"].get(t, ()):
            cand[idx] += 1
    scored = []
    for idx, inter in cand.items():
        name, etoks, cip2 = st["entries"][idx]
        # transferability guard at every deterministic matcher grain
        if name == norm or etoks == toks or CC.token_key(name) == item_key:
            continue
        j = inter / len(toks | etoks)
        if j >= MAX_JACCARD:   # fuzzy (typo_to_cip) leak mitigation
            continue
        if j >= MIN_JACCARD:
            scored.append((j, len(etoks), name, cip2))
    scored.sort(key=lambda x: (-x[0], x[1], x[2]))
    out, seen_pairs = [], set()
    for j, _, name, cip2 in scored:
        if (name, cip2) in seen_pairs:
            continue
        seen_pairs.add((name, cip2))
        out.append(f"{name} -> {cip2} {T.FAMILIES.get(cip2, '?')}")
        if len(out) >= TOP_K:
            break
    return out


def attach_anchors(items: list[dict]) -> None:
    """Compute and attach anchors in place (deterministic, mapping-only)."""
    for it in items:
        it["anchors"] = anchors_for(it.get("field_norm"))
