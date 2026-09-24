"""Mixed / semi-supervised methods: the framework supplies seeds, the data
supplies the geometry.

M1  seeded k-means            k-means over role-text embeddings initialized at
                              the ten prototype paragraphs (nine + none), so
                              every cluster is born with a name and the data
                              moves the boundaries.
M1b embedding label spread    D1's confident labels (seed matches, placeholders)
                              diffused over the 15-nearest-neighbor graph of
                              role-text embeddings (Zhou et al. label spreading).
M2  mobility label spread     the same seeds diffused over the role->role
                              transition graph: an unlabeled role takes the
                              archetype of where its holders come from and go.
M3  bootstrapped classifier   logistic regression on [embedding, SOC major,
                              industry, owner share, seniority], trained on the
                              confident D1 labels, abstaining below a
                              probability floor.
M5  vote                      majority of D1, D2, M1b, M3 (ties -> abstain).
"""

from __future__ import annotations

import sys
from collections import Counter

import numpy as np
import pyarrow as pa
import scipy.sparse as sp
import torch
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import normalize

from . import common as C
from . import framework as F
from . import m_deductive as D

KEYS = list(F.KEYS) + [F.NONE_KEY]
KI = {k: i for i, k in enumerate(KEYS)}
CONFIDENT = {"seed_exact", "seed_substring", "placeholder"}


def confident_seeds(t: pa.Table) -> dict[str, str]:
    """D1 labels from its explainable layers only (no SOC guesses)."""
    seed_idx = D._seed_index()
    seeds_sorted = sorted(seed_idx, key=len, reverse=True)
    out = {}
    for rc, disp, ow in zip(t["role_canonical"].to_pylist(), t["role_display"].to_pylist(),
                            t["owner_share"].to_pylist()):
        text = D.norm(disp)
        if (ow or 0) >= 0.9 and len(text.split()) <= 2 and any(
                w in text for w in ("owner", "founder", "self", "freelance", "contractor", "entrepreneur")):
            out[rc] = F.NONE_KEY
            continue
        if text in seed_idx and len(seed_idx[text]) == 1:
            out[rc] = next(iter(seed_idx[text]))
            continue
        padded = f" {text} "
        for s in seeds_sorted:
            if " " in s and f" {s} " in padded and len(seed_idx[s]) == 1:
                out[rc] = next(iter(seed_idx[s]))
                break
    # Outside-the-framework seeds from SOC: a role whose supported SOC major is
    # a trades / production / transport / clinical / uniformed group.
    outside = {m for m, k in D.SOC_MAJOR_MAP.items() if k == F.NONE_KEY}
    for rc, sm, ss in zip(t["role_canonical"].to_pylist(), t["soc_major"].to_pylist(),
                          t["soc_major_support"].to_pylist()):
        if rc not in out and sm in outside and (ss or 0) >= 5:
            out[rc] = F.NONE_KEY
    return out


# ---------------------------------------------------------------- graphs
def knn_graph(X: np.ndarray, k: int = 15, block: int = 4096) -> sp.csr_matrix:
    """Symmetric cosine kNN graph on the GPU."""
    Xt = torch.from_numpy(X).cuda().half()
    n = X.shape[0]
    rows, cols, vals = [], [], []
    with C.Timer(f"knn k={k} n={n}"):
        for s in range(0, n, block):
            S = Xt[s:s + block] @ Xt.T
            S[torch.arange(S.shape[0]), torch.arange(s, s + S.shape[0])] = -1
            v, j = S.topk(k, dim=1)
            rows.append(np.repeat(np.arange(s, s + S.shape[0]), k))
            cols.append(j.cpu().numpy().ravel())
            vals.append(v.float().cpu().numpy().ravel().clip(0, 1))
    W = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
    return W.maximum(W.T)


def mobility_graph(roles: list[str]) -> sp.csr_matrix:
    idx = {r: i for i, r in enumerate(roles)}
    con = C.connect()
    con.register("universe", pa.table({"role_canonical": roles}))
    e = con.sql(f"""
        SELECT e.from_node, e.to_node, e.weight FROM read_parquet('{C.ROLE_EDGES}') e
        JOIN universe a ON a.role_canonical = e.from_node
        JOIN universe b ON b.role_canonical = e.to_node WHERE NOT e.is_self_loop""").arrow().read_all()
    i = np.fromiter((idx[x] for x in e["from_node"].to_pylist()), np.int64, e.num_rows)
    j = np.fromiter((idx[x] for x in e["to_node"].to_pylist()), np.int64, e.num_rows)
    w = np.log1p(np.asarray(e["weight"].to_pylist(), np.float64))
    n = len(roles)
    A = sp.csr_matrix((w, (i, j)), shape=(n, n))
    return (A + A.T).tocsr()


def label_spread(W: sp.csr_matrix, seeds: np.ndarray, alpha: float = 0.9, iters: int = 30) -> np.ndarray:
    """seeds: int array, -1 = unlabeled. Returns (n, |KEYS|) scores."""
    n = W.shape[0]
    d = np.asarray(W.sum(1)).ravel()
    d[d == 0] = 1
    Dm = sp.diags(1 / np.sqrt(d))
    S = Dm @ W @ Dm
    Y = np.zeros((n, len(KEYS)), np.float32)
    Y[np.arange(n)[seeds >= 0], seeds[seeds >= 0]] = 1
    # class-mass normalization: every archetype injects the same total mass,
    # so a class with many seeds (none, leaders) cannot flood the graph
    Y /= np.maximum(Y.sum(0, keepdims=True), 1)
    Fm = Y.copy()
    for _ in range(iters):
        Fm = alpha * (S @ Fm) + (1 - alpha) * Y
    return Fm


def scores_to_assignment(roles, Fm, floor: float, hard=None) -> dict:
    out = {}
    tot = Fm.sum(1)
    for i, rc in enumerate(roles):
        if hard is not None and rc in hard:
            out[rc] = (hard[rc], 1.0)
            continue
        if tot[i] <= 0:
            out[rc] = ("abstain", 0.0)
            continue
        j = int(Fm[i].argmax())
        conf = float(Fm[i, j] / tot[i])
        out[rc] = (KEYS[j] if conf >= floor else "abstain", conf)
    return out


# ---------------------------------------------------------------- methods
def m1_seeded_kmeans(t, X) -> dict:
    keys, P = D.prototype_matrix()
    km = KMeans(len(keys), init=P, n_init=1, max_iter=100, random_state=0)
    w = np.sqrt(np.asarray(t["n_persons"].to_pylist(), float))
    lab = km.fit_predict(X, sample_weight=w)
    dist = km.transform(X)
    conf = 1 - dist.min(1) / dist.mean(1)
    return {rc: (keys[int(c)], float(cf)) for rc, c, cf in zip(t["role_canonical"].to_pylist(), lab, conf)}


def m1b_embedding_spread(t, X, seeds_map, floor=0.0) -> tuple[dict, np.ndarray]:
    roles = t["role_canonical"].to_pylist()
    seeds = np.array([KI.get(seeds_map.get(r), -1) for r in roles])
    W = knn_graph(X, 15)
    Fm = label_spread(W, seeds)
    return scores_to_assignment(roles, Fm, floor, hard=seeds_map), Fm


def m2_mobility_spread(t, seeds_map, floor=0.0) -> tuple[dict, np.ndarray]:
    roles = t["role_canonical"].to_pylist()
    seeds = np.array([KI.get(seeds_map.get(r), -1) for r in roles])
    W = mobility_graph(roles)
    Fm = label_spread(W, seeds, alpha=0.8)
    return scores_to_assignment(roles, Fm, floor, hard=seeds_map), Fm


def features(t, X) -> np.ndarray:
    majors = sorted(C.SOC_MAJOR_LABEL)
    inds = sorted({x for x in t["industry_l1"].to_pylist() if x})
    n = t.num_rows
    Fx = np.zeros((n, len(majors) + len(inds) + 2), np.float32)
    mi = {m: i for i, m in enumerate(majors)}
    ii = {m: len(majors) + i for i, m in enumerate(inds)}
    for r, (sm, il, ow, sen) in enumerate(zip(t["soc_major"].to_pylist(), t["industry_l1"].to_pylist(),
                                              t["owner_share"].to_pylist(), t["mean_seniority"].to_pylist())):
        if sm in mi:
            Fx[r, mi[sm]] = 1
        if il in ii:
            Fx[r, ii[il]] = 1
        Fx[r, -2] = ow or 0
        Fx[r, -1] = ((sen or 4.5) - 4.5) / 2
    return np.hstack([X, Fx])


def m3_classifier(t, X, seeds_map, floor=0.0) -> tuple[dict, np.ndarray]:
    roles = t["role_canonical"].to_pylist()
    Fx = features(t, X)
    y = np.array([KI.get(seeds_map.get(r), -1) for r in roles])
    m = y >= 0
    with C.Timer(f"logreg on {m.sum()} weak labels"):
        clf = LogisticRegression(max_iter=300, C=1.0, class_weight="balanced")
        clf.fit(Fx[m], y[m])
    P = clf.predict_proba(Fx)
    full = np.zeros((len(roles), len(KEYS)), np.float32)
    full[:, clf.classes_] = P
    return scores_to_assignment(roles, full, floor), full


def vote(assignments: list[dict], roles) -> dict:
    out = {}
    for rc in roles:
        c = Counter(a[rc][0] for a in assignments if a.get(rc, ("abstain",))[0] != "abstain")
        if not c:
            out[rc] = ("abstain", 0.0)
            continue
        (lab, n), *rest = c.most_common(2)
        if rest and rest[0][1] == n:
            out[rc] = ("abstain", 0.0)
        else:
            out[rc] = (lab, n / len(assignments))
    return out


def run():
    from . import metrics as M
    t = C.load_roles()
    roles = t["role_canonical"].to_pylist()
    X = C.encode([x or "" for x in t["role_text"].to_pylist()], "role_text")
    seeds_map = confident_seeds(t)
    print("confident seeds:", len(seeds_map), Counter(seeds_map.values()).most_common())
    results, assignments = {}, {}

    a = m1_seeded_kmeans(t, X)
    results["M1_seeded_kmeans"] = M.score(a, name="M1_seeded_kmeans"); assignments["M1_seeded_kmeans"] = a
    a, Fm = m1b_embedding_spread(t, X, seeds_map)
    results["M1b_embed_spread"] = M.score(a, name="M1b_embed_spread"); assignments["M1b_embed_spread"] = a
    a2 = scores_to_assignment(roles, Fm, 0.5, hard=seeds_map)
    results["M1b_embed_spread_f0.50"] = M.score(a2, name="M1b_embed_spread_f0.50"); assignments["M1b_embed_spread_f0.50"] = a2
    a, Fm2 = m2_mobility_spread(t, seeds_map)
    results["M2_mobility_spread"] = M.score(a, name="M2_mobility_spread"); assignments["M2_mobility_spread"] = a
    a2 = scores_to_assignment(roles, Fm2, 0.5, hard=seeds_map)
    results["M2_mobility_spread_f0.50"] = M.score(a2, name="M2_mobility_spread_f0.50"); assignments["M2_mobility_spread_f0.50"] = a2
    a, P = m3_classifier(t, X, seeds_map)
    results["M3_classifier"] = M.score(a, name="M3_classifier"); assignments["M3_classifier"] = a
    for fl in (0.5, 0.7):
        a2 = scores_to_assignment(roles, P, fl)
        nm = f"M3_classifier_f{fl:.2f}"
        results[nm] = M.score(a2, name=nm); assignments[nm] = a2
    # M2+M1b product: geometry and mobility must agree
    comb = Fm / np.maximum(Fm.sum(1, keepdims=True), 1e-9) * (Fm2 / np.maximum(Fm2.sum(1, keepdims=True), 1e-9) + 0.05)
    a = scores_to_assignment(roles, comb, 0.0, hard=seeds_map)
    results["M2x_embed_times_mobility"] = M.score(a, name="M2x_embed_times_mobility"); assignments["M2x_embed_times_mobility"] = a

    ded = np.load(C.RESULTS / "deductive_assignments.npy", allow_pickle=True).item()
    v = vote([ded["D1_lexicon_soc"], ded["D2_seed_knn_f0.00"], assignments["M1b_embed_spread"],
              assignments["M3_classifier"]], roles)
    results["M5_vote_D1_D2_M1b_M3"] = M.score(v, name="M5_vote_D1_D2_M1b_M3"); assignments["M5_vote_D1_D2_M1b_M3"] = v

    for nm, s in results.items():
        print(f"{nm}: cov={s['coverage']:.2f} strict={s['acc_strict']:.3f} lenient={s['acc_lenient']:.3f} "
              f"assigned={s['acc_strict_assigned']:.3f} F1={s['macro_f1']:.3f} fit={ {k: round(v, 2) for k, v in s['acc_by_fit'].items()} }", flush=True)
    C.write_json(results, C.RESULTS / "mixed.json")
    np.save(C.RESULTS / "mixed_assignments.npy", assignments, allow_pickle=True)


if __name__ == "__main__":
    run()
