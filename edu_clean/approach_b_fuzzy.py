"""Approach B: blocking + guarded fuzzy clustering (unsupervised, no reference).

Pipeline per field:
  1. normalize -> soft-stopped token set
  2. block by a phonetic signature (sorted Metaphone of tokens) so only
     plausibly-similar values are ever compared (keeps it near-linear)
  3. within each block, union-find merge pairs that pass a *guarded* predicate:
     equal token cardinality AND a 1-1 token matching where every token pair is
     identical or a high-similarity typo. Equal-cardinality is the guardrail
     that stops subset/superset false-merges ("Computer Science" vs
     "Computer Science and Engineering").
  4. canonical = highest-frequency member of each cluster.

This buys typo tolerance that pure normalization (Approach A) lacks, while
staying precise about distinct subfields. Institutions are matched by NAME only
here (slug deliberately ignored) to contrast with A.
"""

from __future__ import annotations

import jellyfish
from rapidfuzz import fuzz

from .common import SOFT_STOP, Result, normalize, timer

TOKEN_SIM = 85  # per-token char-similarity to count as the "same" token (typo)
MAX_BLOCK = 500  # above this, fall back to exact-token grouping (no fuzzy)


def _soft_tokens(value: str) -> list[str]:
    toks = [t for t in normalize(value).split() if t not in SOFT_STOP]
    return toks or normalize(value).split()


def _signature(tokens: list[str]) -> str:
    """Order-independent phonetic block key; typos with the same Metaphone
    collapse into the same block."""
    codes = sorted(jellyfish.metaphone(t) or t for t in tokens)
    return f"{len(tokens)}|" + " ".join(codes)


def _tokens_match(a: list[str], b: list[str]) -> bool:
    """Equal cardinality + greedy 1-1 matching with per-token typo tolerance."""
    if len(a) != len(b):
        return False
    if sorted(a) == sorted(b):
        return True
    remaining = list(b)
    for ta in a:
        best_i, best_s = -1, -1
        for i, tb in enumerate(remaining):
            if ta == tb:
                best_i, best_s = i, 100
                break
            # only treat as typo if both reasonably long
            if min(len(ta), len(tb)) >= 4:
                s = fuzz.ratio(ta, tb)
                if s > best_s:
                    best_i, best_s = i, s
        if best_i < 0 or best_s < TOKEN_SIM:
            return False
        remaining.pop(best_i)
    return True


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


def run(field_name: str, vocab: list[tuple]) -> Result:
    with timer() as t:
        values = [row[0] for row in vocab]
        freqs = [row[1] for row in vocab]
        toks = [_soft_tokens(v) for v in values]
        uf = _UF(len(values))

        # build blocks
        blocks: dict[str, list[int]] = {}
        for i in range(len(values)):
            blocks.setdefault(_signature(toks[i]), []).append(i)

        for members in blocks.values():
            if len(members) < 2:
                continue
            if len(members) > MAX_BLOCK:
                # too big to compare pairwise: merge only exact token sets
                exact: dict[tuple, int] = {}
                for i in members:
                    key = tuple(sorted(toks[i]))
                    if key in exact:
                        uf.union(i, exact[key])
                    else:
                        exact[key] = i
                continue
            for x in range(len(members)):
                for y in range(x + 1, len(members)):
                    i, j = members[x], members[y]
                    if uf.find(i) == uf.find(j):
                        continue
                    if _tokens_match(toks[i], toks[j]):
                        uf.union(i, j)

        # canonical = highest-frequency member of each component
        best: dict[int, int] = {}
        for i in range(len(values)):
            r = uf.find(i)
            if r not in best or (freqs[i], values[best[r]]) > (freqs[best[r]], values[i]):
                best[r] = i
        mapping = {values[i]: values[best[uf.find(i)]] for i in range(len(values))}

    n_clusters = len(set(mapping.values()))
    return Result(
        name="B_fuzzy",
        field=field_name,
        mapping=mapping,
        runtime_s=t.elapsed,
        extra={"n_blocks": len(blocks), "clusters": n_clusters},
    )
