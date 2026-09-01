"""Driver: Phase 2+3 role->archetype assignment + coverage report.

NOTE ON WEIGHTING: the mixes below weight by sum(n_persons) over roles. Because
a person holds several roles over a career (~4.7 on average), this is
ROLE-OCCUPANCY weighting, not a count of distinct people. It answers "what share
of role-holding spells is classified", not "what share of people". The credible
person-level and cohort shares come from Phase 4 (panel person-years).
"""

from __future__ import annotations

import json
import time

from . import common as C
from . import assign


def main() -> None:
    t0 = time.time()
    con = C.connect()
    info = assign.build()
    ra = f"read_parquet('{C.RESULTS / 'role_archetype.parquet'}')"

    method_mix = con.execute(f"""
      SELECT assign_method,
             sum(n_persons) AS occ,
             round(100.0*sum(n_persons)/sum(sum(n_persons)) OVER (), 2) AS pct
      FROM {ra} GROUP BY 1 ORDER BY occ DESC
    """).fetchall()

    arch_mix = con.execute(f"""
      SELECT archetype_id, any_value(archetype_label) AS label,
             sum(n_persons) AS occ,
             round(100.0*sum(n_persons)/sum(sum(n_persons)) OVER (), 2) AS pct
      FROM {ra} GROUP BY 1 ORDER BY occ DESC
    """).fetchall()

    other_pct = next((pc for a, _l, _o, pc in arch_mix if a == 0), 0.0)

    manifest = {
        "phase": "assign",
        "n_roles": info["n_roles"],
        "n_embedded": info["n_embedded"],
        "weighting": "role_occupancy (sum n_persons over roles; ~4.7x persons)",
        "support_floor_embed": assign.SUPPORT_FLOOR,
        "soc_min_support": assign.SOC_MIN_SUPPORT,
        "soc_min_frac": assign.SOC_MIN_FRAC,
        "embed_min_cosine": assign.EMBED_MIN_COSINE,
        "embed_min_margin": assign.EMBED_MIN_MARGIN,
        "embed_model": assign.EMBED_MODEL,
        "other_pct_role_occupancy": other_pct,
        "method_mix_role_occupancy": [
            {"method": m, "occ": int(o), "pct": pc} for m, o, pc in method_mix],
        "archetype_mix_role_occupancy": [
            {"id": a, "label": lab, "occ": int(o), "pct": pc}
            for a, lab, o, pc in arch_mix],
        "elapsed_s": round(time.time() - t0, 1),
    }
    (C.RESULTS / "_assign_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: v for k, v in manifest.items()
                      if k != "archetype_mix_role_occupancy"}, indent=2))


if __name__ == "__main__":
    main()
