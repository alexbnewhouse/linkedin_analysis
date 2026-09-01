"""Why does all-MiniLM-L6-v2 give english/engilsh ~ 0.50?

Demonstrates that the culprit is *subword tokenization*: a typo pushes the word
out-of-vocabulary, so it shatters into unrelated WordPiece pieces and the pooled
embedding diverges. A character-level representation (the principle behind
fastText / byte-level transformers) does not have this problem.
"""

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer

PAIRS = [
    ("english", "engilsh"),
    ("psychology", "psycology"),
    ("accounting", "acounting"),
    ("mechanical engineering", "mechancial enginering"),
    ("university of phoenix", "university of pheonix"),
    # a control: genuinely different words
    ("biology", "chemistry"),
]

tok = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
model = SentenceTransformer("all-MiniLM-L6-v2", device="cuda")


def char_ngram_cos(a, b, n=3):
    """Cosine over character n-gram count vectors (fastText-style principle)."""

    def grams(s):
        s = f"<{s}>"
        from collections import Counter

        return Counter(s[i : i + n] for i in range(len(s) - n + 1))

    ga, gb = grams(a), grams(b)
    keys = set(ga) | set(gb)
    va = np.array([ga.get(k, 0) for k in keys], float)
    vb = np.array([gb.get(k, 0) for k in keys], float)
    return float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9))


print(f"{'pair':42s} {'MiniLM':>7} {'char3gram':>10}   tokenization")
print("-" * 100)
for a, b in PAIRS:
    emb = model.encode([a, b], normalize_embeddings=True, convert_to_numpy=True)
    cos = float(emb[0] @ emb[1])
    cg = char_ngram_cos(a, b)
    ta = tok.tokenize(a)
    tb = tok.tokenize(b)
    print(f"{a + '  /  ' + b:42s} {cos:7.2f} {cg:10.2f}   {ta}  vs  {tb}")
