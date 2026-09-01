"""Driver: Phase 1 role feature aggregate."""

from __future__ import annotations

import json
import time

from . import common as C
from . import role_features


def main() -> None:
    t0 = time.time()
    con = C.connect()
    out = role_features.build(con)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    cov = con.execute(f"""
      SELECT
        avg(CASE WHEN soc_detail IS NOT NULL THEN 1 ELSE 0 END) AS detail,
        avg(CASE WHEN soc_major  IS NOT NULL THEN 1 ELSE 0 END) AS major,
        avg(CASE WHEN industry_l1 IS NOT NULL THEN 1 ELSE 0 END) AS ind
      FROM read_parquet('{out}')
    """).fetchone()
    manifest = {
        "phase": "role_features",
        "n_roles": n,
        "role_coverage": {"soc_detail": cov[0], "soc_major": cov[1],
                          "industry_l1": cov[2]},
        "elapsed_s": round(time.time() - t0, 1),
    }
    (C.RESULTS / "_role_features_manifest.json").write_text(
        json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
