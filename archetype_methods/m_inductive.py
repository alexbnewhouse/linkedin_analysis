"""Inductive (data-first) methods: let the archetypes emerge from the data.

I1  title-embedding clusters    k-means over bge embeddings of role text
I2  description-document clusters   same, over what people say they DID
                                (mean of up to 6 step descriptions per role)
I3  mobility blocks             spectral embedding of the role->role transition
                                matrix (in- and out-profiles), then k-means:
                                two roles are alike if people move between the
                                same places

Each returns a clustering {role_canonical: cluster_id} for several k. The
evaluation (cluster_eval) asks: how much of the gold archetype structure does
the clustering already contain (AMI, cross-validated recoverability), how pure
is it on SOC major, how stable is it across seeds, and how lumpy is it.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict

import numpy as np
import pyarrow as pa
import scipy.sparse as sp
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.metrics import adjusted_mutual_info_score, adjusted_rand_score
from sklearn.preprocessing import normalize

from . import common as C
from . import gold as G

KS = (9, 20, 40, 80)
DOC_MIN_PERSONS = 20
DOC_PER_ROLE = 6


# ---------------------------------------------------------------- features
def role_text_embeddings(t: pa.Table) -> np.ndarray:
    return C.encode([x or "" for x in t["role_text"].to_pylist()], "role_text")


def build_role_docs(t: pa.Table) -> tuple[list[str], np.ndarray]:
    """Mean description embedding per role (roles with >= DOC_MIN_PERSONS)."""
    roles = [r for r, n in zip(t["role_canonical"].to_pylist(), t["n_persons"].to_pylist())
             if n >= DOC_MIN_PERSONS]
    con = C.connect()
    con.register("universe", pa.table({"role_canonical": roles}))
    with C.Timer("pull descriptions"):
        d = con.sql(f"""
            SELECT role_canonical, substr(description, 1, 1200) AS d
            FROM (
              SELECT c.role_canonical, c.description,
                     row_number() OVER (PARTITION BY c.role_canonical ORDER BY hash(c.linkedin_id)) AS rn
              FROM read_parquet('{C.CAREER_STEPS}') c
              JOIN universe u USING (role_canonical)
              WHERE NOT c.is_duplicate AND c.description IS NOT NULL AND length(c.description) > 80)
            WHERE rn <= {DOC_PER_ROLE}
        """).arrow().read_all()
    texts = d["d"].to_pylist()
    owners = d["role_canonical"].to_pylist()
    vec = C.encode(texts, "descriptions", batch_size=256)
    idx = {r: i for i, r in enumerate(roles)}
    acc = np.zeros((len(roles), vec.shape[1]), np.float32)
    cnt = np.zeros(len(roles), np.int32)
    for o, v in zip(owners, vec):
        acc[idx[o]] += v
        cnt[idx[o]] += 1
    keep = cnt > 0
    acc = normalize(acc[keep])
    return [r for r, k in zip(roles, keep) if k], acc


def mobility_embedding(t: pa.Table, dim: int = 64) -> tuple[list[str], np.ndarray]:
    roles = t["role_canonical"].to_pylist()
    idx = {r: i for i, r in enumerate(roles)}
    con = C.connect()
    con.register("universe", pa.table({"role_canonical": roles}))
    e = con.sql(f"""
        SELECT e.from_node, e.to_node, e.weight
        FROM read_parquet('{C.ROLE_EDGES}') e
        JOIN universe a ON a.role_canonical = e.from_node
        JOIN universe b ON b.role_canonical = e.to_node
        WHERE NOT e.is_self_loop
    """).arrow().read_all()
    i = np.fromiter((idx[x] for x in e["from_node"].to_pylist()), np.int64, e.num_rows)
    j = np.fromiter((idx[x] for x in e["to_node"].to_pylist()), np.int64, e.num_rows)
    w = np.asarray(e["weight"].to_pylist(), np.float64)
    n = len(roles)
    A = sp.csr_matrix((w, (i, j)), shape=(n, n))
    X = sp.hstack([normalize(A, norm="l1"), normalize(A.T.tocsr(), norm="l1")]).tocsr()
    deg = np.asarray(A.sum(1)).ravel() + np.asarray(A.sum(0)).ravel()
    with C.Timer(f"svd mobility dim={dim}"):
        Z = TruncatedSVD(dim, random_state=0).fit_transform(X)
    Z = normalize(Z)
    keep = deg > 0
    return [r for r, k in zip(roles, keep) if k], Z[keep]


# ---------------------------------------------------------------- clustering
def kmeans(X: np.ndarray, k: int, seed: int = 0, weights=None) -> np.ndarray:
    km = KMeans(k, n_init=2, random_state=seed, max_iter=100)
    return km.fit_predict(X, sample_weight=weights)


def cluster_eval(roles: list[str], labels: np.ndarray, t: pa.Table, name: str,
                 labels_alt: np.ndarray | None = None) -> dict:
    gold = G.load()
    pos = {r: i for i, r in enumerate(roles)}
    n_persons = dict(zip(t["role_canonical"].to_pylist(), t["n_persons"].to_pylist()))
    soc = dict(zip(t["role_canonical"].to_pylist(), t["soc_major"].to_pylist()))
    k = int(labels.max()) + 1
    out = {"name": name, "k": k, "n_roles": len(roles)}
    # gold alignment
    g = [r for r in gold if r["role_canonical"] in pos]
    gl = [r["primary"] for r in g]
    cl = [int(labels[pos[r["role_canonical"]]]) for r in g]
    out["n_gold_in"] = len(g)
    out["ami_gold"] = float(adjusted_mutual_info_score(gl, cl))
    out["ari_gold"] = float(adjusted_rand_score(gl, cl))
    # recoverability: majority map cluster->archetype, 5-fold CV over gold roles
    rng = np.random.default_rng(0)
    folds = rng.integers(0, 5, len(g))
    hits = 0
    for f in range(5):
        maj = defaultdict(Counter)
        for i in range(len(g)):
            if folds[i] != f:
                maj[cl[i]][gl[i]] += 1
        for i in range(len(g)):
            if folds[i] == f:
                pred = maj[cl[i]].most_common(1)[0][0] if maj[cl[i]] else "abstain"
                hits += pred == gl[i]
    out["recoverability_cv"] = hits / len(g)
    maj = defaultdict(Counter)
    for c, gg in zip(cl, gl):
        maj[c][gg] += 1
    out["recoverability_insample"] = sum(cnt.most_common(1)[0][1] for cnt in maj.values()) / len(g)
    # SOC-major purity, person-weighted over roles with a major
    per = defaultdict(Counter)
    for r, c in zip(roles, labels):
        s = soc.get(r)
        if s:
            per[int(c)][s] += n_persons[r]
    tot = sum(sum(cnt.values()) for cnt in per.values())
    out["soc_purity_w"] = sum(cnt.most_common(1)[0][1] for cnt in per.values()) / tot
    # lumpiness
    w = np.asarray([n_persons[r] for r in roles], float)
    share = np.bincount(labels, weights=w, minlength=k) / w.sum()
    out["largest_cluster_share_w"] = float(share.max())
    out["effective_k_w"] = float(np.exp(-(share[share > 0] * np.log(share[share > 0])).sum()))
    if labels_alt is not None:
        out["stability_ari"] = float(adjusted_rand_score(labels, labels_alt))
    # cluster cards: top roles by persons
    top = defaultdict(list)
    order = np.argsort(-w)
    for i in order:
        c = int(labels[i])
        if len(top[c]) < 8:
            top[c].append(roles[i])
    out["clusters"] = {int(c): {"share_w": float(share[c]),
                               "top": top[c],
                               "gold": dict(maj.get(c, {}))} for c in range(k)}
    return out


def run(which: str = "all") -> dict:
    t = C.load_roles()
    roles_all = t["role_canonical"].to_pylist()
    w_all = np.sqrt(np.asarray(t["n_persons"].to_pylist(), float))
    results = {}
    feats = {}
    if which in ("all", "I1"):
        feats["I1_title"] = (roles_all, role_text_embeddings(t), w_all)
    n_persons = dict(zip(roles_all, t["n_persons"].to_pylist()))
    if which in ("all", "I2"):
        r, X = build_role_docs(t)
        feats["I2_description"] = (r, X, np.sqrt(np.asarray([n_persons[x] for x in r], float)))
    if which in ("all", "I3"):
        r, Z = mobility_embedding(t)
        feats["I3_mobility"] = (r, Z, np.sqrt(np.asarray([n_persons[x] for x in r], float)))
    assignments = {}
    for name, (roles, X, w) in feats.items():
        for k in KS:
            with C.Timer(f"{name} k={k}"):
                lab = kmeans(X, k, 0, w)
                alt = kmeans(X, k, 1, w) if k in (20, 80) else None
            ev = cluster_eval(roles, lab, t, f"{name}_k{k}", alt)
            results[ev["name"]] = ev
            assignments[ev["name"]] = dict(zip(roles, lab.tolist()))
            print(f"{ev['name']}: AMI={ev['ami_gold']:.3f} recov_cv={ev['recoverability_cv']:.3f} "
                  f"soc_purity={ev['soc_purity_w']:.3f} eff_k={ev['effective_k_w']:.1f}", flush=True)
    import json
    jp, ap = C.RESULTS / "inductive.json", C.RESULTS / "inductive_assignments.npy"
    prev = json.loads(jp.read_text()) if jp.exists() else {}
    prev.update(results)
    C.write_json(prev, jp)
    prev_a = np.load(ap, allow_pickle=True).item() if ap.exists() else {}
    prev_a.update(assignments)
    np.save(ap, prev_a, allow_pickle=True)
    return results


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "all")
