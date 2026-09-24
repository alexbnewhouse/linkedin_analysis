"""Shared substrate for skill_breadth: paths, field-group definitions, encoder cache.

Compares how broad the range of jobs held is for bachelor's graduates across
four field groups -- Humanities, Humanistic social sciences, STEM, Finance --
each defined from the person's bachelor's CIP/NHA coding in
normalized/education.parquet. See
docs/superpowers/plans/2026-09-24-skill-breadth.md for the exact group
predicates, cohort window, and role filters this module implements.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import duckdb
import numpy as np

from archetype_methods.common import ENCODER

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
RESULTS = HERE / "results"

EDUCATION = ROOT / "normalized" / "education.parquet"
EDUCATION_PERSON = ROOT / "normalized" / "education_person.parquet"
CAREER_STEPS = ROOT / "normalized" / "career_steps.parquet"

# Field-group definitions: SQL boolean predicates over education row columns
# (cip_code, cip2_pooled, nha_level_pooled). Verbatim from the plan (docs/superpowers/plans/2026-09-24-skill-breadth.md).
HEADLINE_GROUPS = {
    "humanities": "nha_level_pooled = 1",
    "humanistic_social_sciences": "nha_level_pooled = 2",
    "stem": "cip2_pooled IN ('11','14','15','26','27','40','41') AND nha_level_pooled NOT IN (1, 2)",
    "finance": "cip_code LIKE '52.08%'",
}
GROUP_LABELS = {
    "humanities": "Humanities",
    "humanistic_social_sciences": "Humanistic social sciences",
    "stem": "STEM",
    "finance": "Finance",
}
# Sanity-check-only fields (not part of the headline 4-group comparison, but
# counted for the "does the group definition make sense" cross-check). A
# person whose bachelor rows match one of these AND a headline group is still
# multi-group and excluded from the cohort, same as any other overlap.
SANITY_GROUPS = {
    "nursing": "cip_code LIKE '51.38%'",
    "accounting": "cip_code LIKE '52.03%'",
    "liberal_arts": "cip_code LIKE '24.01%'",
}
SANITY_GROUP_LABELS = {
    "nursing": "Nursing",
    "accounting": "Accounting",
    "liberal_arts": "Liberal arts (general)",
}
ALL_GROUPS = {**HEADLINE_GROUPS, **SANITY_GROUPS}
ALL_GROUP_LABELS = {**GROUP_LABELS, **SANITY_GROUP_LABELS}

COHORT_YEAR_MIN = 2000
COHORT_YEAR_MAX = 2014
ROLE_WINDOW_YEARS = 10
MIN_DESCRIPTION_LEN = 50

# Task 3 bootstrap constants (see the plan, docs/superpowers/plans/2026-09-24-skill-breadth.md).
N_PEOPLE = 500
N_BOOT = 200
BOOT_SEED = 20260924


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads TO 16")
    return con


class Timer:
    def __init__(self, label: str):
        self.label = label

    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *a):
        self.secs = time.time() - self.t0
        print(f"[{self.label}] {self.secs:.1f}s", flush=True)


_model = None


def _encoder():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(ENCODER, device="cuda")
        _model.max_seq_length = 256
    return _model


def encode(texts: list[str], name: str, batch_size: int = 512) -> np.ndarray:
    """L2-normalized float32 embeddings, cached on disk by (name, content hash)."""
    CACHE.mkdir(exist_ok=True)
    h = hashlib.sha1("\x1f".join(texts).encode("utf-8")).hexdigest()[:16]
    path = CACHE / f"emb_{name}_{len(texts)}_{h}.npy"
    if path.exists():
        return np.load(path)
    with Timer(f"encode {name} n={len(texts)}"):
        vec = _encoder().encode(
            texts, batch_size=batch_size, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False)
    vec = vec.astype(np.float32)
    np.save(path, vec)
    return vec


def write_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=_default))


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))
