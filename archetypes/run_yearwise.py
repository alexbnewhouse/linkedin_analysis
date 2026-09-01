"""Driver: Phase 4 yearwise projection + summary manifest."""

from __future__ import annotations

import json
import time

from . import common as C
from . import yearwise


def main() -> None:
    t0 = time.time()
    con = C.connect()
    paths = yearwise.build_all(con)

    py = f"read_parquet('{paths['person_year']}')"
    sf = f"read_parquet('{paths['state_flows']}')"
    jf = f"read_parquet('{paths['job_flows']}')"

    n_py, n_persons = con.execute(
        f"SELECT count(*), count(DISTINCT linkedin_id) FROM {py}").fetchone()
    anchor_mix = con.execute(
        f"SELECT anchor_tier, count(DISTINCT linkedin_id) FROM {py} "
        f"GROUP BY 1 ORDER BY 2 DESC").fetchall()
    cohort_persons = con.execute(
        f"SELECT entry_cohort, count(DISTINCT linkedin_id) FROM {py} "
        f"WHERE in_window GROUP BY 1 ORDER BY 1").fetchall()
    # OTHER share among in-window person-years
    other = con.execute(
        f"SELECT round(100.0*avg(CASE WHEN archetype_id=0 THEN 1 ELSE 0 END),2) "
        f"FROM {py} WHERE in_window").fetchone()[0]
    n_state = con.execute(f"SELECT sum(n_persons) FROM {sf}").fetchone()[0]
    n_job = con.execute(f"SELECT sum(n_moves) FROM {jf}").fetchone()[0]
    stay = con.execute(
        f"SELECT round(100.0*sum(CASE WHEN from_archetype=to_archetype "
        f"THEN n_persons ELSE 0 END)/sum(n_persons),1) FROM {sf}").fetchone()[0]

    manifest = {
        "phase": "yearwise",
        "n_person_years": int(n_py),
        "n_persons": int(n_persons),
        "other_share_pct_inwindow": other,
        "anchor_tier_persons": {t: int(c) for t, c in anchor_mix},
        "cohort_persons_inwindow": {c: int(n) for c, n in cohort_persons},
        "state_flow_person_steps": int(n_state or 0),
        "state_flow_stay_pct": stay,
        "job_flow_moves": int(n_job or 0),
        "elapsed_s": round(time.time() - t0, 1),
    }
    (C.RESULTS / "_yearwise_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
