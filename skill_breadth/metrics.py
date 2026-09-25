"""Task 3: breadth metrics -- pure functions, no duckdb/I-O.

vendi(X)            -- Vendi score of a set of L2-normalized row vectors.
bootstrap_vendi(...) -- equal-n bootstrap over vendi(), paired across bases.
within_person_spread(...) -- per-person mean pairwise cosine distance among
    a person's role vectors (text basis only, per the plan).

See docs/superpowers/plans/2026-09-24-skill-breadth.md for the exact
formulas.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

_EIG_ZERO_TOL = 1e-10


def vendi(X: np.ndarray) -> float:
    """Vendi score of n row vectors (rows need not be pre-normalized here,
    but the cosine-kernel Vendi score assumes they are unit-norm -- callers
    are responsible for that, matching the controller decision).

    The n x n Gram kernel X X^T / n and the d x d covariance X^T X / n share
    their nonzero eigenvalues (trace 1 when rows are unit-norm), so this
    eigendecomposes whichever is smaller: the Gram matrix when n < d (e.g.
    500 draws of 768-dim text embeddings), the covariance otherwise (e.g.
    35-dim skill vectors). Tiny negative eigenvalues (float error) are
    clipped to 0 and near-zeros dropped before the Shannon-entropy sum.
    """
    X = np.asarray(X, dtype=np.float64)
    n, d = X.shape
    if n == 0:
        return 0.0
    M = (X @ X.T) / n if n < d else (X.T @ X) / n
    eigs = np.linalg.eigvalsh(M)
    eigs = np.clip(eigs, 0.0, None)
    eigs = eigs[eigs > _EIG_ZERO_TOL]
    if eigs.size == 0:
        return 0.0
    p = eigs / eigs.sum()
    h = -float(np.sum(p * np.log(p)))
    return float(np.exp(h))


def bootstrap_vendi(
    person_rows: dict,
    bases: dict[str, np.ndarray],
    seed: int,
    n_people: int = 500,
    n_boot: int = 200,
) -> dict[str, np.ndarray]:
    """Equal-n bootstrap Vendi score, paired across bases.

    person_rows: {person_id: [row_idx, ...]} -- row indices into EACH array
        in `bases` refer to the same physical role (bases are row-aligned).
    bases: {basis_name: (n_rows, d) array of unit-norm role vectors}.

    Each of n_boot replicates samples n_people distinct people without
    replacement, then one role per sampled person (uniform over that
    person's roles), using the SAME sampled people and SAME sampled role
    for every basis in that replicate -- so a text-vs-skills comparison
    isn't confounded by different sampling draws. Deterministic given seed
    (person iteration order is the sorted person_id order, never dict
    iteration order).

    Returns {basis_name: np.ndarray of shape (n_boot,)} of vendi scores.
    """
    person_ids = sorted(person_rows.keys())
    n_persons = len(person_ids)
    if n_people > n_persons:
        raise ValueError(f"n_people={n_people} > {n_persons} available people")

    rng = np.random.default_rng(seed)
    out = {name: np.empty(n_boot, dtype=np.float64) for name in bases}

    for b in range(n_boot):
        sampled_idx = rng.choice(n_persons, size=n_people, replace=False)
        chosen_rows = np.empty(n_people, dtype=np.int64)
        for i, pi in enumerate(sampled_idx):
            rows = person_rows[person_ids[pi]]
            if len(rows) == 1:
                chosen_rows[i] = rows[0]
            else:
                chosen_rows[i] = rows[rng.integers(0, len(rows))]
        for name, X in bases.items():
            out[name][b] = vendi(X[chosen_rows])

    return out


def within_person_spread(
    person_rows: dict,
    X: np.ndarray,
    min_roles: int = 3,
) -> dict:
    """Mean pairwise cosine distance among each person's role vectors
    (text basis only), for people with >= min_roles described roles.

    X must be unit-norm rows (cosine similarity = dot product).
    Returns {person_id: (n_roles, mean_pairwise_cosine_distance)}.
    """
    out = {}
    for pid, rows in person_rows.items():
        k = len(rows)
        if k < min_roles:
            continue
        V = X[np.asarray(rows, dtype=np.int64)]
        sims = V @ V.T
        iu = np.triu_indices(k, k=1)
        mean_sim = float(np.mean(sims[iu]))
        out[pid] = (k, 1.0 - mean_sim)
    return out
