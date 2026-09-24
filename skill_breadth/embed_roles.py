"""Task 2 (part 1): embed every role_text in results/roles.parquet.

Writes, row-aligned in a fixed deterministic order (linkedin_id,
experience_idx, position_idx):
  cache/role_emb.npy      -- float32 [n_roles, 768], L2-normalized (bge-base)
  cache/role_keys.parquet -- linkedin_id, experience_idx, position_idx, group

`common.encode` already content-hash-caches the actual model call under
cache/emb_roles_*.npy; this script additionally snapshots that array (and the
key order it corresponds to) under the fixed names above so downstream tasks
don't need to recompute the content hash to find it.

    uv run python -m skill_breadth.embed_roles
"""

from __future__ import annotations

import numpy as np
import pyarrow.parquet as pq

from . import common as C


def run() -> None:
    con = C.connect()
    roles = con.sql(f"""
        SELECT linkedin_id, "group", experience_idx, position_idx, role_text
        FROM read_parquet('{C.RESULTS / "roles.parquet"}')
        ORDER BY linkedin_id, experience_idx, position_idx
    """).arrow().read_all()

    keys = roles.select(["linkedin_id", "group", "experience_idx", "position_idx"])
    texts = roles.column("role_text").to_pylist()
    print(f"embedding {len(texts)} role texts", flush=True)

    emb = C.encode(texts, name="roles")
    assert emb.shape[0] == len(texts)

    C.CACHE.mkdir(exist_ok=True)
    np.save(C.CACHE / "role_emb.npy", emb)
    pq.write_table(keys, str(C.CACHE / "role_keys.parquet"))

    print(f"wrote cache/role_emb.npy {emb.shape}, cache/role_keys.parquet {keys.num_rows} rows", flush=True)


if __name__ == "__main__":
    run()
