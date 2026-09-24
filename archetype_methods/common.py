"""Shared substrate: the role universe, the encoder cache, paths, metrics.

Unit of classification: `role_canonical` (the normalized title string), as in
every other layer of the repo. The universe for the benchmarks is the HEAD of
that vocabulary (roles held by >= MIN_PERSONS distinct people), which is 110k
roles carrying 72% of all career steps. Everything is person-weighted when a
population number is reported.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
RESULTS = HERE / "results"
GOLD = HERE / "gold"

ROLE_FEATURES = ROOT / "archetypes" / "results" / "role_features.parquet"
CAREER_STEPS = ROOT / "normalized" / "career_steps.parquet"
ROLE_EDGES = ROOT / "transition_network" / "role_edges.parquet"
ONET_OCC = ROOT / "reference" / "onet_occupation_data.txt"
ONET_ALT = ROOT / "reference" / "onet_alternate_titles.txt"

MIN_PERSONS = 5
ENCODER = "BAAI/bge-base-en-v1.5"

SOC_MAJOR_LABEL = {
    "11": "Management", "13": "Business and Financial Operations",
    "15": "Computer and Mathematical", "17": "Architecture and Engineering",
    "19": "Life, Physical, and Social Science", "21": "Community and Social Service",
    "23": "Legal", "25": "Educational Instruction and Library",
    "27": "Arts, Design, Entertainment, Sports, and Media",
    "29": "Healthcare Practitioners and Technical", "31": "Healthcare Support",
    "33": "Protective Service", "35": "Food Preparation and Serving",
    "37": "Building and Grounds Cleaning and Maintenance",
    "39": "Personal Care and Service", "41": "Sales and Related",
    "43": "Office and Administrative Support", "45": "Farming, Fishing, and Forestry",
    "47": "Construction and Extraction", "49": "Installation, Maintenance, and Repair",
    "51": "Production", "53": "Transportation and Material Moving",
    "55": "Military Specific",
}


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads TO 16")
    return con


def load_roles(min_persons: int = MIN_PERSONS):
    """The role universe as a pyarrow Table, sorted by n_persons desc."""
    con = connect()
    return con.sql(f"""
        SELECT role_canonical, role_display, role_text, n_persons, n_steps,
               soc_detail, soc_detail_support, soc_major, soc_major_support,
               industry_l1, owner_share, mean_seniority
        FROM read_parquet('{ROLE_FEATURES}')
        WHERE n_persons >= {min_persons}
        ORDER BY n_persons DESC, role_canonical
    """).arrow().read_all()


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
