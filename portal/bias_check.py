"""Bias check (COVERAGE_PLAN.md Plan 2, "required, not optional"): compare
A1-only vs pooled (accepted tiers, common.ANCHOR_TIERS) on the portal's own
year-10 statistics for the five named majors + baseline -- fan top groups,
up_share, and the long-view curve at y0/y4/y10 (the curve grid has no y5
point; y4 is the nearest).

    uv run python -m portal.bias_check

Writes portal/results/bias_check.json. Flags: fan-share delta > 2 points,
up_share delta > 0.03 (the plan's stated materiality bars).
"""

from __future__ import annotations

import json

import duckdb

from portal import analyses, build, common as C

OUT = C.OUT_DIR / "bias_check.json"

FAN_SHARE_MATERIAL = 0.02   # 2 percentage points
UP_SHARE_MATERIAL = 0.03


def _snapshot(con, tiers: tuple[str, ...]) -> dict:
    build.build_membership(con, tiers=tiers)
    build.build_panel(con)
    analyses.register_occ_nodes(con)
    fan = analyses.destination_fan(con)
    mv = analyses.moves(con)
    cv = analyses.curve(con)
    out = {}
    for g in list(C.MAJORS) + [C.BASELINE_KEY]:
        top_fan = fan[g]["fan"][:5]
        curve_years = cv[g]["years"]
        med = cv[g]["median_seniority"]

        def at(y):
            return med[curve_years.index(y)] if y in curve_years else None

        out[g] = {
            "n_windowed": fan[g]["denom"],
            "unclassified_share": fan[g]["unclassified_share"],
            "top_fan": top_fan,
            "up_share": mv[g]["up_share"],
            "curve_y0": at(0), "curve_y4": at(4), "curve_y10": at(10),
        }
    return out


def run() -> dict:
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={C.DEFAULT_THREADS}")
    a1_only = _snapshot(con, ("A1",))
    pooled = _snapshot(con, C.ANCHOR_TIERS)
    con.close()

    comparison = {}
    flags = []
    for g in list(C.MAJORS) + [C.BASELINE_KEY]:
        a1 = a1_only[g]
        po = pooled[g]
        a1_top = {c["group"]: c["share"] for c in a1["top_fan"]}
        po_top = {c["group"]: c["share"] for c in po["top_fan"]}
        fan_deltas = {}
        for grp in sorted(set(a1_top) | set(po_top)):
            d = round(po_top.get(grp, 0.0) - a1_top.get(grp, 0.0), 4)
            fan_deltas[grp] = d
            if abs(d) > FAN_SHARE_MATERIAL:
                flags.append(f"{g}: fan share delta on '{grp}' = {d:+.4f} (> {FAN_SHARE_MATERIAL})")
        up_delta = (round(po["up_share"] - a1["up_share"], 4)
                    if a1["up_share"] is not None and po["up_share"] is not None else None)
        if up_delta is not None and abs(up_delta) > UP_SHARE_MATERIAL:
            flags.append(f"{g}: up_share delta = {up_delta:+.4f} (> {UP_SHARE_MATERIAL})")
        comparison[g] = {
            "n_windowed_a1_only": a1["n_windowed"],
            "n_windowed_pooled": po["n_windowed"],
            "unclassified_share_a1_only": a1["unclassified_share"],
            "unclassified_share_pooled": po["unclassified_share"],
            "fan_share_delta_by_group": fan_deltas,
            "up_share_a1_only": a1["up_share"],
            "up_share_pooled": po["up_share"],
            "up_share_delta": up_delta,
            "curve_y0_a1_only": a1["curve_y0"], "curve_y0_pooled": po["curve_y0"],
            "curve_y4_a1_only": a1["curve_y4"], "curve_y4_pooled": po["curve_y4"],
            "curve_y10_a1_only": a1["curve_y10"], "curve_y10_pooled": po["curve_y10"],
        }

    payload = {
        "note": (
            "A1-only vs pooled (ANCHOR_TIERS = "
            f"{list(C.ANCHOR_TIERS)}) comparison of year-10 fan/up_share/curve "
            "statistics. Curve grid has no y5 point; y4 is reported as the "
            "nearest available horizon."
        ),
        "materiality_bars": {
            "fan_share_delta_points": FAN_SHARE_MATERIAL,
            "up_share_delta": UP_SHARE_MATERIAL,
        },
        "comparison": comparison,
        "material_disagreements": flags,
        "verdict": (
            "NO material disagreement found -- pooling A1+A2 is defensible."
            if not flags else
            "Material disagreement(s) found -- see material_disagreements."
        ),
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
