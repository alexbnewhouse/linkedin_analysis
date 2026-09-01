"""Driver: compute every portal number and write the JSON contract.

    python -m portal.run_portal_data [--threads N]

Emits portal/results/portal_data.json (byte-reproducible) and portal/_manifest.json.
All-CPU DuckDB; the whole run is a single connection of materialized temp tables.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date

import duckdb

from portal import common as C
from portal import analyses, build, choices, launchboard, pathways, pillars


def run(threads: int | None = None) -> dict:
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads or C.DEFAULT_THREADS}")
    started = time.monotonic()

    substrate = build.load_or_build_substrate(con)
    analyses.register_occ_nodes(con)

    boundaries = build.boundary_counts(con)
    funnel = build.group_funnel(con)
    fan = analyses.destination_fan(con)
    fan_detail = analyses.destination_fan_detail(con)
    div = analyses.diversity(con, fan)
    # Attach the within-group occupation drill-down to each fan cell in place
    # (majors[*]["fan"] and baseline["fan"] alias these same lists).
    for g in list(C.MAJORS) + [C.BASELINE_KEY]:
        for cell in fan[g]["fan"]:
            cell["detail"] = fan_detail[g].get(cell["group"])
    bd = analyses.breadth_and_distinctive(con)
    mv = analyses.moves(con)
    cv = analyses.curve(con)
    sec = analyses.sectors(con)
    emp = analyses.employer_field(con)

    top5_fan = {g: [c["group"] for c in fan[g]["fan"][:5]] for g in C.MAJORS}
    paths = pathways.mine_soc(con, top5_fan)
    pil = pillars.compute(con)
    lb = launchboard.compute(con)
    ch = choices.compute(con)

    majors = {}
    for key, (name, fams, tier) in C.MAJORS.items():
        f = funnel[key]
        majors[key] = {
            "name": name,
            "cip_families": fams,
            "nha_tier": tier,
            "records": f["records"],
            "persons": f["persons"],
            "persons_anchored": f["persons_anchored"],
            "persons_anchored_a1": f["persons_anchored_a1"],
            "anchor_drop_rate": f["anchor_drop_rate"],
            "anchor_method_mix": f["anchor_method_mix"],
            "cip_source_mix": f["cip_source_mix"],
            "persons_windowed_y10": f["persons_windowed_y10"],
            "kpi": {
                "breadth": bd[key]["breadth"],
                "breadth_of": bd[key]["breadth_of"],
                "distinctive": bd[key]["distinctive"],
                "up_share": mv[key]["up_share"],
                "dwell_median_mo": mv[key]["dwell_median_mo"],
            },
            "fan": fan[key]["fan"],
            "unclassified_share": fan[key]["unclassified_share"],
            "soc_source_mix": fan[key]["soc_source_mix"],
            "sectors": sec[key]["sectors"],
            "industry_unresolved_share": sec[key]["industry_unresolved_share"],
            "curve": cv[key],
            "pillars": pil[key],
            "paths": paths[key]["paths"],
            "paths_suppressed_count": paths[key]["paths_suppressed_count"],
            "paths_grain": paths[key]["paths_grain"],
            "launchboard": lb[key],
            "employer_field": emp[key],
            "diversity": div[key],
            "choices": ch["per_group"][key],
        }

    payload = {
        "generated": date.today().isoformat(),
        "snapshot_date": C.SNAPSHOT_DATE,
        # The single global named-cell suppression bar; the front end reads
        # this to render every suppression promise dynamically.
        "min_support": C.MIN_SUPPORT,
        "window_rule": (
            "A year-N statistic includes only persons whose graduation anchor "
            f"(qualifying bachelor's end year) is <= {C.SNAPSHOT_YEAR}-N, so every "
            "subject has a fully observed N-year window."),
        "baseline_def": (
            "All persons holding any CIP-coded bachelor's degree with a usable "
            "graduation anchor, under the same window discipline; all vs-chance / "
            "RR numbers use this baseline via the same code path."),
        "boundaries": boundaries,
        "boundaries_note": (
            "Nested humanities tiers re-derived from the committed education "
            "crosswalk (L1 subset of L2 subset of L3). These supersede the stale "
            "186,018 / 341,113 / 597,144 doc figures, which predate the CIP "
            "coverage ratchet (coded rows rose 49.1% -> 58.8%)."),
        "occupation_coverage_note": (
            (
                "Major-group occupation numbers (fan, pathways) pool two "
                "sources: the deterministic O*NET backbone (6-digit, always "
                "wins) and the career_clean LLM jury (2-digit only, fills "
                "abstentions; two-model unanimity, calibrated on held-out "
                "gold -- career_clean/results/soc_calibration.json). "
                "soc_source_mix reports the blend per major. Breadth and "
                "distinctive-destination counts remain deterministic-only "
                "(6-digit grain)."
                if "llm_jury" in C.SOC_SOURCES else
                "Occupation-grain results rest on the ~21.5% of steps that "
                "carry a deterministic SOC code (the career_clean coding "
                "ceiling). An LLM-jury expansion is calibrated and gated but "
                "not pooled into these numbers (SOC_SOURCES is "
                "deterministic-only pending the full-coverage bias check -- "
                "portal/soc_bias_check.py)."
            )
            + " The unclassified bucket is reported honestly per major."),
        "fan_detail_note": (
            "Each fan cell carries a `detail` drill-down: the specific 6-digit "
            "occupations behind the major group. This describes ONLY the "
            "deterministically role-coded slice of the cell (~30%); the jury "
            "resolves the sector but no finer, so those people appear as "
            "`no_detail_n` (classified to the group only). Named roles clear a "
            f"{C.DETAIL_MIN_SUPPORT}-person bar (since the 2026-07-13 "
            f"loosening this coincides with the {C.MIN_SUPPORT}-person "
            "headline bar), on the same descriptive footing as the breadth "
            "KPI's >=5-person occupation-node reach: a composition of the "
            "role-coded subset, not a population estimate. Finer roles fold "
            "into `other_coded_n`, and the portal badges the panel as a "
            "coded-subset composition. The launchboard snapshot fans (year-1 "
            "first destinations, year-3/5 outlook) carry the same per-cell "
            "`detail` under the same contract, computed on each horizon's own "
            "windowed endpoint."),
        "majors": majors,
        "baseline": {
            "records": funnel[C.BASELINE_KEY]["records"],
            "persons": funnel[C.BASELINE_KEY]["persons"],
            "persons_anchored": funnel[C.BASELINE_KEY]["persons_anchored"],
            "persons_anchored_a1": funnel[C.BASELINE_KEY]["persons_anchored_a1"],
            "anchor_drop_rate": funnel[C.BASELINE_KEY]["anchor_drop_rate"],
            "anchor_method_mix": funnel[C.BASELINE_KEY]["anchor_method_mix"],
            "cip_source_mix": funnel[C.BASELINE_KEY]["cip_source_mix"],
            "persons_windowed_y10": funnel[C.BASELINE_KEY]["persons_windowed_y10"],
            "fan": fan[C.BASELINE_KEY]["fan"],
            "curve": cv[C.BASELINE_KEY],
            "up_share": mv[C.BASELINE_KEY]["up_share"],
            "dwell_median_mo": mv[C.BASELINE_KEY]["dwell_median_mo"],
            "pillars": pil[C.BASELINE_KEY],
            "launchboard": lb[C.BASELINE_KEY],
            "employer_field": emp[C.BASELINE_KEY],
            "diversity": div[C.BASELINE_KEY],
            "choices": ch["per_group"][C.BASELINE_KEY],
        },
        "choices_pooled": ch["pooled"],
        "choices_not_measured": ch["not_measured"],
        "choices_notes": ch["notes"],
        "diversity_note": (
            "diversity.effective_destinations (inverse Simpson, 1/sum(p^2)) and "
            "top3_classified_share are computed over the FULL classified year-10 "
            "endpoint distribution -- scalar aggregates that name no cell, so "
            "suppression does not apply; groups_reached and top_bucket_share "
            f"restate the published fan (cells clearing the {C.MIN_SUPPORT}-"
            "person bar)."),
        "launchboard_notes": launchboard.NOTES,
        "anchor_tiers_note": (
            "anchor_method_mix reports the share of a group's anchored persons "
            "produced by each tier (A1 observed / A2 start+duration / A3 "
            "career-onset). Only tiers in ANCHOR_TIERS are ever assigned; the "
            "default is ('A1', 'A2') -- the two tiers that cleared the "
            ">=80%-within-+/-1yr validation gate "
            "(edu_clean/results/anchor_eval.json; edu_clean/FINDINGS.md). A3 "
            "measured ~31% within +/-1yr and ships flagged experimental, "
            "excluded from every default consumer."
        ),
    }

    runtime = round(time.monotonic() - started, 1)
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    C.DATA_OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    manifest = {
        "generated": payload["generated"],
        "runtime_s": runtime,
        "inputs": {
            "education": str(C.EDUCATION), "steps": str(C.STEPS),
            "transitions": str(C.TRANSITIONS), "occ_nodes": str(C.OCC_NODES),
            "step_industry": str(C.STEP_INDUSTRY), "soc_status": str(C.SOC_STATUS),
            "cip_humanities": str(C.CIP_HUMANITIES), "taxonomy": str(C.TAXONOMY),
        },
        "boundaries": boundaries,
        "funnel": funnel,
        "params": {
            "bachelor_level": C.BACHELOR_LEVEL, "fan_year": C.FAN_YEAR,
            "min_support": C.MIN_SUPPORT,
            "min_support_note": (
                "Global named-cell bar loosened 40 -> 10 (user directive "
                "2026-07-13, PORTAL_REDESIGN_PLAN.md); common.MIN_SUPPORT is "
                "the single knob -- distinctive_min and path_min_persons "
                "derive from it."),
            "detail_min_support": C.DETAIL_MIN_SUPPORT,
            "breadth_min_persons": C.BREADTH_MIN_PERSONS,
            "distinctive_rr": C.DISTINCTIVE_RR, "distinctive_min": C.DISTINCTIVE_MIN,
            "path_min_persons": C.PATH_MIN_PERSONS, "curve_years": C.CURVE_YEARS,
            "anchor_tiers": list(C.ANCHOR_TIERS),
            "soc_sources": list(C.SOC_SOURCES),
            "cip_sources": list(C.CIP_SOURCES),
            "paths_grain": "soc_major_pooled",
            "choices": {
                "intern_window": list(choices.INTERN_WINDOW),
                "military_window": list(choices.MILITARY_WINDOW),
                "service_window": list(choices.SERVICE_WINDOW),
                "grad_levels": list(choices.GRAD_LEVELS),
                "grad_horizon": choices.GRAD_HORIZON,
                "se_types": list(choices.SE_TYPES),
            },
        },
        "outputs": {"portal_data": str(C.DATA_OUT)},
    }
    manifest["params"]["threads"] = threads or C.DEFAULT_THREADS
    manifest["substrate"] = substrate  # "cache" or "built"
    C.MANIFEST_OUT.write_text(json.dumps(manifest, indent=2) + "\n")
    con.close()
    return {"runtime_s": runtime, "majors": list(majors), "substrate": substrate}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=None,
                    help="DuckDB threads (default: cores-2 via common.DEFAULT_THREADS)")
    args = ap.parse_args()
    res = run(args.threads)
    print(f"portal_data.json written in {res['runtime_s']}s "
          f"(substrate: {res['substrate']}); majors: {res['majors']}")


if __name__ == "__main__":
    main()
