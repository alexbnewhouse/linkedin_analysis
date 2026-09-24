"""Scoring an assignment against the gold set.

An assignment is {role_canonical: (label, score)} where label is one of the
nine archetype keys, 'none' (an explicit 'outside the framework' verdict) or
'abstain' (no decision). Every metric is reported plain and person-weighted.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from . import framework as F
from . import gold as G

LABELS = list(F.KEYS) + [F.NONE_KEY]


def _acc(pairs, weights):
    if not pairs:
        return float("nan")
    w = np.asarray(weights, float)
    hit = np.asarray([p == g for p, g in pairs], float)
    return float((hit * w).sum() / w.sum())


def score(assignment: dict, gold=None, name: str = "") -> dict:
    gold = gold or G.load()
    rows = []
    for r in gold:
        lab, sc = assignment.get(r["role_canonical"], ("abstain", 0.0))
        rows.append((r, lab, sc))
    n = len(rows)
    ones = [1.0] * n
    wts = [r["n_persons"] for r, _, _ in rows]

    strict = [(lab, r["primary"]) for r, lab, _ in rows]
    lenient = [(lab, lab if lab in (r["primary"], r["secondary"]) and lab != "abstain"
                else r["primary"]) for r, lab, _ in rows]
    assigned = [i for i, (_, lab, _) in enumerate(rows) if lab != "abstain"]
    out = {
        "name": name,
        "n_gold": n,
        "coverage": len(assigned) / n,
        "coverage_w": float(sum(wts[i] for i in assigned) / sum(wts)),
        "acc_strict": _acc(strict, ones),
        "acc_lenient": _acc(lenient, ones),
        "acc_strict_w": _acc(strict, wts),
        "acc_lenient_w": _acc(lenient, wts),
        "acc_strict_assigned": _acc([strict[i] for i in assigned], [1.0] * len(assigned)),
        "acc_lenient_assigned": _acc([lenient[i] for i in assigned], [1.0] * len(assigned)),
    }
    # by fit stratum and by band (strict, unweighted)
    for key in ("fit", "band"):
        groups = defaultdict(list)
        for i, (r, lab, _) in enumerate(rows):
            groups[r[key]].append(i)
        out[f"acc_by_{key}"] = {g: _acc([strict[i] for i in idx], [1.0] * len(idx))
                                for g, idx in sorted(groups.items())}
        out[f"n_by_{key}"] = {g: len(idx) for g, idx in sorted(groups.items())}
    # macro-F1 over the ten labels; abstain counts as a miss for recall
    f1s = {}
    for L in LABELS:
        tp = sum(1 for p, g in strict if p == L and g == L)
        fp = sum(1 for p, g in strict if p == L and g != L)
        fn = sum(1 for p, g in strict if g == L and p != L)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s[L] = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    out["f1_by_label"] = f1s
    out["macro_f1"] = float(np.mean([f1s[L] for L in LABELS]))
    out["macro_f1_nine"] = float(np.mean([f1s[L] for L in F.KEYS]))
    # confusion (gold -> predicted), for the report
    conf = Counter((g, p) for p, g in strict)
    out["confusion"] = {f"{g}->{p}": c for (g, p), c in conf.most_common() if g != p}
    return out


def agreement(a: dict, b: dict, universe: list[str], weights=None) -> dict:
    """Pairwise agreement of two assignments over a universe (Cohen's kappa)."""
    pa, pb = [], []
    w = []
    for i, rc in enumerate(universe):
        la = a.get(rc, ("abstain", 0))[0]
        lb = b.get(rc, ("abstain", 0))[0]
        if la == "abstain" or lb == "abstain":
            continue
        pa.append(la); pb.append(lb); w.append(1.0 if weights is None else weights[i])
    if not pa:
        return {"n": 0}
    w = np.asarray(w)
    po = float((np.asarray([x == y for x, y in zip(pa, pb)], float) * w).sum() / w.sum())
    ca, cb = Counter(), Counter()
    for x, y, ww in zip(pa, pb, w):
        ca[x] += ww; cb[y] += ww
    pe = sum(ca[L] * cb[L] for L in set(ca) | set(cb)) / (w.sum() ** 2)
    return {"n": len(pa), "agree": po, "kappa": (po - pe) / (1 - pe) if pe < 1 else 1.0}


def summary_row(s: dict) -> str:
    return (f"| {s['name']} | {s['coverage']:.2f} | {s['acc_strict']:.3f} | {s['acc_lenient']:.3f} | "
            f"{s['acc_strict_w']:.3f} | {s['acc_strict_assigned']:.3f} | {s['macro_f1']:.3f} | "
            f"{s['acc_by_fit'].get('strong', float('nan')):.2f} / "
            f"{s['acc_by_fit'].get('weak', float('nan')):.2f} / "
            f"{s['acc_by_fit'].get('none', float('nan')):.2f} |")
