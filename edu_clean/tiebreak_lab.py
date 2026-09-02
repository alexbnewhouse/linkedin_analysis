"""Tiebreak lab: test candidate acceptance rules for the CIP disagreement band
on the gold sample BEFORE committing to any juror or rule (audit R3 retry).

    uv run python -m edu_clean.tiebreak_lab rules            # zero-LLM rules on gold
    uv run python -m edu_clean.tiebreak_lab band             # dump the gold band items
    uv run python -m edu_clean.tiebreak_lab score MODEL      # score a juror's cached votes

Everything reads the append-only vote cache; nothing is fired or merged here.
"""
from __future__ import annotations

import re
import sys
from collections import Counter

from edu_clean import cip_llm as L
from edu_clean import cip_taxonomy as T
from edu_clean.run_cip_jury import _load_gold_sample
from edu_clean.run_cip_tiebreak import vote_state

CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def full_votes(items, jurors):
    """{field_norm: {model: Proposal}} incl. confidence + rationale."""
    cache = L.load_cache()
    out = {}
    for it in items:
        for m in jurors:
            p = cache.get(L.cache_key(it, m))
            if p is not None:
                out.setdefault(it["field_norm"], {})[m] = p
    return out


def anchor_families(item) -> list[str]:
    """Ordered CIP2 families of the item's nearest-anchor evidence."""
    fams = []
    for a in item.get("anchors") or []:
        m = re.search(r"-> (\d\d) ", a)
        if m:
            fams.append(m.group(1))
    return fams


def band(items, votes):
    return [it for it in items
            if vote_state({m: p.code for m, p in votes.get(it["field_norm"], {}).items()})
            in ("disagree", "partial_abstain")]


def score(name, decisions, items):
    """decisions: {field_norm: code|None}. Prints resolution + accuracy."""
    n = len(items)
    resolved = [it for it in items if decisions.get(it["field_norm"])]
    ok = sum(1 for it in resolved if decisions[it["field_norm"]] == it["gold_cip2"])
    acc = ok / len(resolved) if resolved else float("nan")
    print(f"{name:<38} resolved {len(resolved):>3}/{n}  accuracy {acc:.3f}  "
          f"(correct {ok})")
    return acc, len(resolved)


def cmd_rules():
    items = _load_gold_sample(None)
    votes = full_votes(items, L.JURY)
    b = band(items, votes)
    print(f"gold band (original panel disagree/partial): {len(b)} strings\n")

    # Rule 1: higher self-reported confidence wins (ties -> unresolved)
    d = {}
    for it in b:
        v = votes[it["field_norm"]]
        voted = [(CONF_RANK.get(p.confidence, 0), p.code) for p in v.values()
                 if p.code != T.ABSTAIN]
        if len(voted) == 1:
            d[it["field_norm"]] = voted[0][1]
        elif len(voted) == 2 and voted[0][0] != voted[1][0]:
            d[it["field_norm"]] = max(voted)[1]
    score("R1 confidence-wins", d, b)

    # Rule 1b: confidence-wins, disagree-only (no partial abstains)
    d2 = {k: c for k, c in d.items()
          if vote_state({m: p.code for m, p in votes[k].items()}) == "disagree"}
    score("R1b confidence-wins (disagree only)", d2, [it for it in b if
          vote_state({m: p.code for m, p in votes[it['field_norm']].items()}) == "disagree"])

    # Rule 2: anchor top-1 family picks between juror votes
    d = {}
    for it in b:
        fams = anchor_families(it)
        codes = {p.code for p in votes[it["field_norm"]].values() if p.code != T.ABSTAIN}
        if fams and fams[0] in codes:
            d[it["field_norm"]] = fams[0]
    score("R2 anchor-top1 picks a juror vote", d, b)

    # Rule 3: anchor majority family (over top-K) picks
    d = {}
    for it in b:
        fams = anchor_families(it)
        codes = {p.code for p in votes[it["field_norm"]].values() if p.code != T.ABSTAIN}
        if fams:
            top, cnt = Counter(fams).most_common(1)[0]
            if top in codes and cnt >= 2:
                d[it["field_norm"]] = top
    score("R3 anchor-majority(>=2) picks", d, b)

    # Rule 4: partial-abstain -> accept the lone vote if confidence == high
    d = {}
    for it in b:
        v = votes[it["field_norm"]]
        voted = [p for p in v.values() if p.code != T.ABSTAIN]
        if len(voted) == 1 and voted[0].confidence == "high":
            d[it["field_norm"]] = voted[0].code
    score("R4 lone high-conf vote (partial band)", d, b)

    # Rule 5: R1 AND R2 agree
    d = {}
    for it in b:
        v = votes[it["field_norm"]]
        voted = [(CONF_RANK.get(p.confidence, 0), p.code) for p in v.values()
                 if p.code != T.ABSTAIN]
        conf_pick = None
        if len(voted) == 2 and voted[0][0] != voted[1][0]:
            conf_pick = max(voted)[1]
        elif len(voted) == 1:
            conf_pick = voted[0][1]
        fams = anchor_families(it)
        if conf_pick and fams and fams[0] == conf_pick:
            d[it["field_norm"]] = conf_pick
    score("R5 confidence AND anchor agree", d, b)

    # Baseline for reference: what the ORIGINAL unanimity rule scores on all gold
    allv = {}
    for it in items:
        v = votes.get(it["field_norm"], {})
        codes = [p.code for p in v.values()]
        allv[it["field_norm"]] = L.unanimous_accept(codes) if len(codes) == 2 else None
    print()
    score("(ref) unanimity on full gold", allv, items)


def cmd_band():
    items = _load_gold_sample(None)
    votes = full_votes(items, L.JURY)
    for it in band(items, votes):
        v = votes[it["field_norm"]]
        vs = ", ".join(f"{m.split('/')[-1]}={p.code}/{p.confidence}" for m, p in v.items())
        print(f"{it['field_norm']!r:45} gold={it['gold_cip2']}  {vs}  "
              f"anchors={anchor_families(it)[:3]}")


def cmd_score(model):
    items = _load_gold_sample(None)
    votes = full_votes(items, L.JURY)
    b = band(items, votes)
    third = full_votes(b, (model,))
    have = [it for it in b if model in third.get(it["field_norm"], {})]
    print(f"{model}: cached votes on band {len(have)}/{len(b)}")
    # solo on band
    d = {it["field_norm"]: third[it["field_norm"]][model].code for it in have
         if third[it["field_norm"]][model].code != T.ABSTAIN}
    score("  solo on band", d, have)
    # 2-of-3
    d = {}
    for it in have:
        codes = [p.code for p in votes[it["field_norm"]].values()] + \
                [third[it["field_norm"]][model].code]
        codes = [c for c in codes if c != T.ABSTAIN and T.is_valid(c)]
        for c in set(codes):
            if codes.count(c) >= 2:
                d[it["field_norm"]] = c
    score(f"  2-of-3 with {model.split('/')[-1]}", d, have)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "rules"
    if cmd == "rules":
        cmd_rules()
    elif cmd == "band":
        cmd_band()
    elif cmd == "score":
        cmd_score(sys.argv[2])
