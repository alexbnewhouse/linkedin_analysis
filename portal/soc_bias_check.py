"""SOC-source bias check: deterministic-only vs pooled (det + LLM jury) fans.

    uv run python -m portal.soc_bias_check

Pooling MUST grow classification (that is its purpose), so raw share growth is
not the bias signal. The signal is RELATIVE-RISK drift: RR divides a major's
share by the baseline's share under the SAME sources, so an accurate jury
moves both numerator and denominator together and RRs hold; a jury with a
convention skew (e.g. over-assigning Management) bends majors' RRs. Bars:

  * RR delta on any det-fan cell:      |rr_pooled - rr_det| > 0.5
  * RR sign-flip around 1.0 on a cell that was distinctive (rr_det >= 1.5)

Writes portal/results/soc_bias_check.json. If any flag fires, SOC_SOURCES
should be reverted to ("deterministic",) until the jury is improved -- the
knob makes that a one-line change.
"""

from __future__ import annotations

import json

import duckdb

from portal import analyses, build, common as C

OUT = C.OUT_DIR / "soc_bias_check.json"

RR_DELTA_MATERIAL = 0.5
DISTINCTIVE_RR = C.DISTINCTIVE_RR


def _fan_snapshot(con, sources: tuple[str, ...]) -> dict:
    build.build_panel(con, soc_sources=sources)
    fan = analyses.destination_fan(con)
    return {
        g: {
            "cells": {c["group"]: {"share": c["share"], "rr": c["rr"], "n": c["n"]}
                      for c in fan[g]["fan"]},
            "unclassified_share": fan[g]["unclassified_share"],
            "soc_source_mix": fan[g]["soc_source_mix"],
        }
        for g in list(C.MAJORS) + [C.BASELINE_KEY]
    }


def run() -> dict:
    if not C.ROLE_SOC_JURY.exists():
        raise SystemExit("role_soc_jury.parquet not built -- run "
                         "career_clean.run_soc_jury merge first")
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={C.DEFAULT_THREADS}")
    build.build_membership(con)
    analyses.register_occ_nodes(con)
    det = _fan_snapshot(con, ("deterministic",))
    pooled = _fan_snapshot(con, ("deterministic", "llm_jury"))
    build.build_panel(con)  # leave the default panel behind
    con.close()

    comparison, flags = {}, []
    for g in list(C.MAJORS) + [C.BASELINE_KEY]:
        d, p = det[g], pooled[g]
        cells = {}
        for grp in sorted(set(d["cells"]) | set(p["cells"])):
            dc, pc = d["cells"].get(grp), p["cells"].get(grp)
            rr_d = dc["rr"] if dc else None
            rr_p = pc["rr"] if pc else None
            delta = round(rr_p - rr_d, 3) if rr_d is not None and rr_p is not None else None
            cells[grp] = {"rr_det": rr_d, "rr_pooled": rr_p, "rr_delta": delta,
                          "share_det": dc["share"] if dc else None,
                          "share_pooled": pc["share"] if pc else None}
            if g == C.BASELINE_KEY or delta is None:
                continue
            if abs(delta) > RR_DELTA_MATERIAL:
                flags.append(f"{g}: RR delta on '{grp}' = {delta:+.3f} (> {RR_DELTA_MATERIAL})")
            if rr_d >= DISTINCTIVE_RR and rr_p < 1.0:
                flags.append(f"{g}: '{grp}' flipped from distinctive (rr {rr_d}) "
                             f"to under-represented (rr {rr_p})")
        comparison[g] = {
            "unclassified_det": d["unclassified_share"],
            "unclassified_pooled": p["unclassified_share"],
            "soc_source_mix_pooled": p["soc_source_mix"],
            "cells": cells,
        }

    payload = {
        "note": ("Deterministic-only vs pooled (det + llm_jury) year-10 fan. "
                 "Share growth is the intended effect; RR drift is the bias "
                 "signal (see module docstring). Jury acceptance = two-model "
                 "unanimity, calibrated 0.887 on held-out gold (gate 0.85, "
                 "leak-proof anchor guard)."),
        "materiality_bars": {"rr_delta": RR_DELTA_MATERIAL,
                             "distinctive_flip": f"rr_det >= {DISTINCTIVE_RR} -> rr_pooled < 1.0"},
        "comparison": comparison,
        "material_disagreements": flags,
        "verdict": ("NO material RR drift -- pooling det + llm_jury is defensible."
                    if not flags else
                    "Material RR drift found -- revert SOC_SOURCES to deterministic-only "
                    "and investigate (see material_disagreements)."),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")
    print(payload["verdict"])
    for f in flags:
        print(" ", f)
    return payload


if __name__ == "__main__":
    run()
