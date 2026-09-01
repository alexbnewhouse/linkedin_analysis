"""Retrieval anchors for the SOC jury: nearest O*NET lexicon titles.

Calibration v1 failed its gate (unanimous 0.693 vs the 0.85 bar) with a clear
confusion structure: the jury's readings were linguistically defensible but
diverged from O*NET's major-group CONVENTIONS (functional managers -> 11,
admin supervisors stay 43, ...). The fix is to put the conventions in the
evidence: for each role we retrieve the nearest titles from the official
O*NET alternate-title lexicon (reference data already in the repo) with their
true major groups, and the rubric tells the jury to follow the reference
conventions.

Transferability guard (load-bearing): gold strings are lexicon-matchable at
the DETERMINISTIC MATCHER'S surfaces -- exact-normalized, soft-stop-dropping
token_key, and de-leveled variants (occupation.py steps 2-4) -- that is why
they have labels. Retrieval therefore excludes any entry matching the item at
token_key grain (which subsumes exact-normalized and exact-token-set), so a
gold item can never see the very entry that generated its label; it sees only
neighbors, like a candidate would. The 2026-07-08 adversarial review found
the original (weaker) guard leaked the label-generating entry into 41/600
gold items via soft-stop differences ("assistant professor OF nursing" vs
"nursing assistant professor"), inflating measured unanimity to 0.8931. With
this guard the honest re-measured figure is 0.887 (n=522, coverage 0.870) --
still past the 0.85 gate.

NOTE (also from the review): deterministic coding is per RAW TITLE, so a
role_canonical string can have both coded and uncoded steps -- candidates and
gold populations OVERLAP on ~1.6k strings. Those mixed strings are excluded
from the jury merge (run_soc_jury.cmd_merge), so their evidence/anchor shape
does not matter for production pooling.
"""

from __future__ import annotations

from collections import defaultdict

from career_clean import common as CC
from career_clean import occupation as OCC
from career_clean import soc_taxonomy as T

TOP_K = 5
MIN_JACCARD = 0.34  # at least ~1/3 token overlap before an anchor is shown

_STATE: dict = {}


def _index():
    """Inverted token index over the O*NET alt-title lexicon (built once)."""
    if _STATE:
        return _STATE
    by_norm, by_tokens, code_to_title = OCC.load_onet()
    entries = []          # (display_norm, frozenset(tokens), major_group)
    inv = defaultdict(set)  # token -> entry indices
    seen = set()
    for norm, code in by_norm.items():
        toks = frozenset(norm.split())
        if not toks or (toks, code) in seen:
            continue
        seen.add((toks, code))
        idx = len(entries)
        entries.append((norm, toks, code[:2]))
        for t in toks:
            inv[t].add(idx)
    _STATE["entries"] = entries
    _STATE["inv"] = inv
    return _STATE


def anchors_for(role_display: str | None) -> list[str]:
    """Top-K nearest lexicon titles as 'title -> code label' strings.

    Exact-normalized and exact-token-set matches are EXCLUDED (see module
    docstring). Returns [] when nothing clears MIN_JACCARD -- the evidence
    line is then omitted, never invented."""
    if not role_display:
        return []
    st = _index()
    norm = CC.normalize(role_display)
    toks = frozenset(norm.split())
    if not toks:
        return []
    item_key = CC.token_key(role_display)      # soft-stop-dropping matcher grain
    cand: dict[int, int] = defaultdict(int)
    for t in toks:
        for idx in st["inv"].get(t, ()):
            cand[idx] += 1
    scored = []
    for idx, inter in cand.items():
        name, etoks, mg = st["entries"][idx]
        # transferability guard at the deterministic matcher's grain
        if name == norm or etoks == toks or CC.token_key(name) == item_key:
            continue
        j = inter / len(toks | etoks)
        if j >= MIN_JACCARD:
            scored.append((j, len(etoks), name, mg))
    scored.sort(key=lambda x: (-x[0], x[1], x[2]))
    out, seen_pairs = [], set()
    for j, _, name, mg in scored:
        if (name, mg) in seen_pairs:
            continue
        seen_pairs.add((name, mg))
        out.append(f"{name} -> {mg} {T.MAJOR_GROUPS.get(mg, '?')}")
        if len(out) >= TOP_K:
            break
    return out


def attach_anchors(items: list[dict]) -> None:
    """Compute and attach anchors in place (deterministic, reference-only)."""
    for it in items:
        it["anchors"] = anchors_for(it.get("role_display"))
