"""CIP-source bias check: deterministic-only vs pooled (det + LLM jury)
MEMBERSHIP, compared on the portal's own year-10 statistics.

    uv run python -m portal.cip_bias_check

CIP pooling admits NEW people to the majors and the baseline (unlike SOC
pooling, which only reclassified existing cohort members' outcomes), so the
right comparison is the anchor-tier bias check's shape: do the people the
jury admits look statistically like the people the crosswalk admits? Bars
(same as the Plan-2 anchor check):

  * fan-share delta on any top-5 cell   > 2 points
  * up_share delta                      > 0.03

Writes portal/results/cip_bias_check.json. If a bar fires, CIP_SOURCES stays
deterministic-only until the drift is explained and signed off in FINDINGS.
"""

from __future__ import annotations

import json

import duckdb

from portal import analyses, build, common as C

OUT = C.OUT_DIR / "cip_bias_check.json"

FAN_SHARE_MATERIAL = 0.02
UP_SHARE_MATERIAL = 0.03


def _snapshot(con, cip_sources: tuple[str, ...]) -> dict:
    build.build_membership(con, cip_sources=cip_sources)
    build.build_panel(con)
    analyses.register_occ_nodes(con)
    fan = analyses.destination_fan(con)
    mv = analyses.moves(con)
    funnel = build.group_funnel(con, cip_sources=cip_sources)
    out = {}
    for g in list(C.MAJORS) + [C.BASELINE_KEY]:
        out[g] = {
            "n_windowed": fan[g]["denom"],
            # FULL cell dict, not top-5: truncating at a rank boundary turns a
            # cell swapping in/out of the top 5 into a spurious full-share
            # delta (caught on the first run: english Legal/Office&Admin at
            # the rank-5 line read as +-3.2 points of fake drift).
            "top_fan": {c["group"]: c["share"] for c in fan[g]["fan"]},
            "up_share": mv[g]["up_share"],
            "cip_source_mix": funnel[g]["cip_source_mix"],
        }
    return out


def run() -> dict:
    if not C.FIELD_CIP_JURY.exists():
        raise SystemExit("field_cip_jury.parquet not built -- run "
                         "edu_clean.run_cip_jury merge first")
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={C.DEFAULT_THREADS}")
    det = _snapshot(con, ("deterministic",))
    pooled = _snapshot(con, ("deterministic", "llm_jury"))
    build.build_membership(con)  # restore default
    con.close()

    comparison, flags = {}, []
    for g in list(C.MAJORS) + [C.BASELINE_KEY]:
        d, p = det[g], pooled[g]
        fan_deltas = {}
        for grp in sorted(set(d["top_fan"]) | set(p["top_fan"])):
            delta = round(p["top_fan"].get(grp, 0.0) - d["top_fan"].get(grp, 0.0), 4)
            fan_deltas[grp] = delta
            if abs(delta) > FAN_SHARE_MATERIAL:
                flags.append(f"{g}: fan share delta on '{grp}' = {delta:+.4f} "
                             f"(> {FAN_SHARE_MATERIAL})")
        up_delta = (round(p["up_share"] - d["up_share"], 4)
                    if d["up_share"] is not None and p["up_share"] is not None else None)
        if up_delta is not None and abs(up_delta) > UP_SHARE_MATERIAL:
            flags.append(f"{g}: up_share delta = {up_delta:+.4f} (> {UP_SHARE_MATERIAL})")
        comparison[g] = {
            "n_windowed_det": d["n_windowed"], "n_windowed_pooled": p["n_windowed"],
            "growth": round(p["n_windowed"] / d["n_windowed"] - 1, 4)
                      if d["n_windowed"] else None,
            "cip_source_mix_pooled": p["cip_source_mix"],
            "fan_share_delta_by_group": fan_deltas,
            "up_share_det": d["up_share"], "up_share_pooled": p["up_share"],
            "up_share_delta": up_delta,
        }

    payload = {
        "note": ("Deterministic-only vs pooled (det + llm_jury) CIP MEMBERSHIP "
                 "compared on year-10 fan and up_share. Cohort growth is the "
                 "intended effect; composition drift past the bars is the "
                 "signal. Jury acceptance = two-model unanimity, calibrated "
                 "0.911 on held-out gold (gate 0.85; fuzzy-surface caveat "
                 "documented in edu_clean/cip_anchors.py)."),
        "materiality_bars": {"fan_share_delta_points": FAN_SHARE_MATERIAL,
                             "up_share_delta": UP_SHARE_MATERIAL},
        "comparison": comparison,
        "material_disagreements": flags,
        "verdict": ("NO material composition drift -- pooling det + llm_jury "
                    "membership is defensible."
                    if not flags else
                    "Material drift found -- CIP_SOURCES stays deterministic-only "
                    "until explained and signed off (see material_disagreements)."),
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
