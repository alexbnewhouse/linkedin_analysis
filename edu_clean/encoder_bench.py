"""Head-to-head encoder benchmark for the field-canonicalization task.

  uv run python -m edu_clean.encoder_bench probe            # cheap pairwise test
  uv run python -m edu_clean.encoder_bench anchored M1 M2   # full CIP-anchor eval

`probe` measures, per encoder, how well its cosine separates merge-pairs from
keep-pairs (threshold-independent ROC-AUC), broken down by phenomenon. The key
column is AUC(same_sem vs distinct-related): whether semantics beat lexical
overlap. `anchored` runs the real production use (assign each field value to its
nearest CIP title) and reports gold P/R/F1 + coverage + GPU throughput.

Encoders:
  minilm  bge-small  bge-base  gte-base  e5-base   (subword sentence transformers)
  canine                                            (character-level transformer)
  char34                                            (char 3-4gram tf-idf, no NN)
  fuzz_tokenset  fuzz_ratio                         (pure lexical baselines)
"""

from __future__ import annotations

import sys
import time

import numpy as np

from .probe_pairs import KEEP_CATS, MERGE_CATS, PROBE

ST_MODELS = {
    "minilm": "sentence-transformers/all-MiniLM-L6-v2",
    "bge-small": "BAAI/bge-small-en-v1.5",
    "bge-base": "BAAI/bge-base-en-v1.5",
    "gte-base": "thenlper/gte-base",
    "e5-base": "intfloat/e5-base-v2",
}
_st_cache: dict = {}


def _st(name: str):
    if name not in _st_cache:
        from sentence_transformers import SentenceTransformer

        _st_cache[name] = SentenceTransformer(ST_MODELS[name], device="cuda")
    return _st_cache[name]


def _prep(name: str, texts: list[str]) -> list[str]:
    # e5 expects a task prefix; use the symmetric "query:" form on both sides.
    if name == "e5-base":
        return [f"query: {t}" for t in texts]
    return texts


def encode(name: str, texts: list[str]) -> np.ndarray:
    """Return L2-normalized vectors (numpy) for a vector encoder."""
    if name in ST_MODELS:
        m = _st(name)
        v = m.encode(
            _prep(name, texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=1024,
        )
        return v
    if name == "canine":
        return _encode_canine(texts)
    if name == "char34":
        from sklearn.feature_extraction.text import TfidfVectorizer

        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4))
        m = vec.fit_transform([t.lower() for t in texts]).toarray().astype("float32")
        n = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.clip(n, 1e-9, None)
    raise ValueError(name)


_canine = None


def _encode_canine(texts: list[str]) -> np.ndarray:
    """Mean-pooled CANINE-S (character/codepoint transformer) embeddings."""
    global _canine
    import torch
    from transformers import AutoModel, AutoTokenizer

    if _canine is None:
        tok = AutoTokenizer.from_pretrained("google/canine-s")
        mdl = AutoModel.from_pretrained("google/canine-s").to("cuda").eval()
        _canine = (tok, mdl)
    tok, mdl = _canine
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), 256):
            batch = texts[i : i + 256]
            enc = tok(
                batch, padding=True, truncation=True, max_length=64, return_tensors="pt"
            ).to("cuda")
            h = mdl(**enc).last_hidden_state  # [b, t, d]
            mask = enc["attention_mask"].unsqueeze(-1).float()
            pooled = (h * mask).sum(1) / mask.sum(1).clamp(min=1)
            pooled = torch.nn.functional.normalize(pooled, dim=1)
            out.append(pooled.float().cpu().numpy())
    return np.vstack(out)


# ----------------------------- pairwise probe ----------------------------
def _all_pairs():
    rows = []  # (cat, a, b, is_merge)
    for cat, pairs in PROBE.items():
        for a, b in pairs:
            rows.append((cat, a, b, cat in MERGE_CATS))
    return rows


def _lexical_scores(name: str, rows):
    from rapidfuzz import fuzz

    fn = fuzz.token_set_ratio if name == "fuzz_tokenset" else fuzz.ratio
    return np.array([fn(a, b) / 100.0 for _c, a, b, _m in rows])


def _vector_scores(name: str, rows):
    texts = sorted({t for _c, a, b, _m in rows for t in (a, b)})
    idx = {t: i for i, t in enumerate(texts)}
    t0 = time.monotonic()
    V = encode(name, texts)
    dt = time.monotonic() - t0
    cos = np.array([float(V[idx[a]] @ V[idx[b]]) for _c, a, b, _m in rows])
    return cos, dt, V.shape[1]


def probe():
    from sklearn.metrics import roc_auc_score

    rows = _all_pairs()
    cats = list(PROBE.keys())
    labels = np.array([1 if m else 0 for _c, _a, _b, m in rows])
    sem_mask = np.array([c == "same_sem" for c, *_ in rows])
    keep_mask = np.array([c in KEEP_CATS for c, *_ in rows])

    encoders = list(ST_MODELS) + ["canine", "char34", "fuzz_tokenset", "fuzz_ratio"]
    print(
        f"\n{'encoder':14s} "
        + " ".join(f"{c[:9]:>9}" for c in cats)
        + f" {'AUCall':>7} {'AUCsem':>7} {'bestF1':>7} {'dim':>5}"
    )
    print("-" * 130)
    results = {}
    for name in encoders:
        try:
            if name.startswith("fuzz"):
                cos = _lexical_scores(name, rows)
                dim = "-"
            else:
                cos, _dt, dim = _vector_scores(name, rows)
        except Exception as e:  # noqa: BLE001
            print(f"{name:14s} FAILED: {str(e)[:80]}")
            continue
        cat_med = {
            c: np.median([cos[i] for i, r in enumerate(rows) if r[0] == c])
            for c in cats
        }
        auc_all = roc_auc_score(labels, cos)
        # semantic-merge vs distinct-related (the decisive separation)
        sub = sem_mask | keep_mask
        auc_sem = roc_auc_score(labels[sub], cos[sub]) if sub.sum() else float("nan")
        # best F1 over thresholds
        best_f1 = 0.0
        for thr in np.unique(cos):
            pred = (cos >= thr).astype(int)
            tp = int(((pred == 1) & (labels == 1)).sum())
            fp = int(((pred == 1) & (labels == 0)).sum())
            fn = int(((pred == 0) & (labels == 1)).sum())
            p = tp / (tp + fp) if tp + fp else 0
            r = tp / (tp + fn) if tp + fn else 0
            f1 = 2 * p * r / (p + r) if p + r else 0
            best_f1 = max(best_f1, f1)
        print(
            f"{name:14s} "
            + " ".join(f"{cat_med[c]:9.2f}" for c in cats)
            + f" {auc_all:7.3f} {auc_sem:7.3f} {best_f1:7.3f} {str(dim):>5}"
        )
        results[name] = {"auc_all": auc_all, "auc_sem": auc_sem, "best_f1": best_f1}
    print(
        "\nLegend: AUCall=merge-vs-keep, AUCsem=same_sem-vs-distinct-related (1.0=perfect, 0.5=chance)"
    )
    return results


# --------------------------- anchored-CIP eval ---------------------------
def anchored(models: list[str]):
    import csv

    import torch

    from .common import ROOT, load_vocab, normalize, pair_scores, token_key
    from .gold import PAIRS

    anchors = []
    with (ROOT / "reference" / "cip_codes.csv").open(
        newline="", encoding="utf-8"
    ) as fh:
        for row in csv.DictReader(fh):
            code = (row.get("CIPCode") or "").strip()
            title = (row.get("CIPTitle") or "").strip().rstrip(".")
            typ = (row.get("Type") or "").strip().lower()
            definition = (row.get("CIPDefinition") or "").lower()
            if (
                title
                and len(code) >= 4
                and typ != "remedial"
                and "not valid for ipeds reporting" not in definition
            ):
                anchors.append((code, title))
    a_codes = [c for c, _ in anchors]
    a_titles = [t for _, t in anchors]
    a_tokens = [token_key(t) for t in a_titles]

    vocab = load_vocab("field")
    values = [r[0] for r in vocab]
    vocab_values = {v for v in values}
    pairs = [
        (a, b, s)
        for a, b, s in PAIRS["field"]
        if a in vocab_values and b in vocab_values
    ]
    total = sum(f for _v, f, *_ in vocab)

    print(
        f"\n{'encoder':12s} {'thr':>5} {'P':>5} {'R':>5} {'F1':>5} "
        f"{'cov%':>6} {'reduc':>6} {'embed_s':>8} {'str/s':>9}"
    )
    print("-" * 80)
    for name in models:
        try:
            t0 = time.monotonic()
            A = encode(name, a_titles)
            V = encode(name, values)
            embed_s = time.monotonic() - t0
            A = torch.tensor(A, device="cuda")
            for thr in (0.55, 0.60, 0.70, 0.80):
                mapping = {}
                blk = 8192
                for s in range(0, len(values), blk):
                    Vb = torch.tensor(V[s : s + blk], device="cuda")
                    sims = Vb @ A.t()
                    bs, bi = sims.max(dim=1)
                    for k in range(bi.shape[0]):
                        v = values[s + k]
                        ai = int(bi[k])
                        if (
                            float(bs[k]) >= thr
                            and (token_key(v) & a_tokens[ai])
                            and token_key(v) <= a_tokens[ai]
                        ):
                            mapping[v] = f"cip:{a_codes[ai]}"
                        else:
                            mapping[v] = f"raw:{normalize(v)}"
                sc = pair_scores(mapping, pairs)
                matched = sum(f for v, f, *_ in vocab if mapping[v].startswith("cip:"))
                reduc = 1 - len(set(mapping.values())) / len(mapping)
                print(
                    f"{name:12s} {thr:5.2f} {sc['precision']:5.2f} "
                    f"{sc['recall']:5.2f} {sc['f1']:5.2f} "
                    f"{100 * matched / total:6.1f} {reduc:6.2f} "
                    f"{embed_s:8.1f} {len(values) / embed_s:9,.0f}"
                )
            del A
            torch.cuda.empty_cache()
        except Exception as e:  # noqa: BLE001
            print(f"{name:12s} FAILED: {str(e)[:80]}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "probe":
        probe()
    elif cmd == "anchored":
        models = sys.argv[2:] or ["minilm", "bge-base", "e5-base"]
        anchored(models)
