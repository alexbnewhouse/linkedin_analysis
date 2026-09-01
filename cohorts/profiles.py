"""Phase 1 — career-age outcome profiles, compared at equal age.

    uv run python -m cohorts.profiles

Mean outcomes (fused `seniority_score`, occupation status `job_zone_norm`) as a
function of career age, one curve per entry-cohort, clipped to a window
observable for ALL cohorts (`COMMON_WINDOW_YEARS`). Comparing cohorts only at
equal career age is the basic control the generational-mobility literature
requires (else age/period masquerade as cohort).

This phase is run FIRST on purpose: the cross-cohort gap at equal age is where
**survivorship bias** shows up most plainly (older cohorts are observed only via
members still active on LinkedIn in 2025), so it calibrates how much to trust the
later phases. Outputs `cohorts/age_profiles.parquet` + `_profiles_manifest.json`.
"""

from __future__ import annotations

import json
import time

import duckdb

from cohorts import common as C


def build(threads: int = 8) -> dict:
    con = duckdb.connect(); con.execute(f"PRAGMA threads={threads}")
    p = f"read_parquet('{str(C.PANEL_OUT)}')"
    started = time.monotonic()

    # mean outcomes by (humanities group, cohort bin, career age) within the
    # common window. `hum_group` is the added dimension: 'humanities' = any L1
    # degree (pooled, any-degree flag), 'non_humanities' = everyone else. This
    # turns the module's whole-population profile into the humanities-vs-non
    # comparison it was missing.
    hg = "CASE WHEN hum_l1_any THEN 'humanities' ELSE 'non_humanities' END"
    con.sql(f"""
      COPY (
        SELECT {hg} AS hum_group, entry_cohort_bin, career_age,
               count(DISTINCT linkedin_id) AS n_profiles,
               round(avg(seniority_score), 4) AS mean_seniority,
               round(avg(job_zone_norm), 4) AS mean_jobzone,
               round(avg(seniority_confidence), 4) AS mean_confidence
        FROM {p}
        WHERE valid_cohort AND career_age <= {C.COMMON_WINDOW_YEARS}
        GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
      ) TO '{str(C.OUT_DIR / "age_profiles.parquet")}' (FORMAT parquet, COMPRESSION zstd)
    """)

    # humanities-vs-non seniority gap at equal career age (pooled over cohorts,
    # equal-age so age/period don't masquerade as a field effect)
    def _hum_gap(age):
        rows = con.sql(f"""
          SELECT {hg} AS g, round(avg(seniority_score), 4) s,
                 count(DISTINCT linkedin_id) n
          FROM {p} WHERE valid_cohort AND career_age = {age} GROUP BY 1""").fetchall()
        d = {g: {"mean_seniority": s, "n": n} for g, s, n in rows}
        h, nh = d.get("humanities", {}), d.get("non_humanities", {})
        gap = (round(h["mean_seniority"] - nh["mean_seniority"], 4)
               if h.get("mean_seniority") is not None
               and nh.get("mean_seniority") is not None else None)
        return {"humanities": h, "non_humanities": nh, "gap": gap}

    # cross-cohort cross-sections at fixed career ages: the survivorship lens
    def _at_age(age):
        rows = con.sql(f"""
          SELECT entry_cohort_bin, round(avg(seniority_score), 4) AS s,
                 count(DISTINCT linkedin_id) AS n
          FROM {p} WHERE valid_cohort AND career_age = {age}
          GROUP BY 1 ORDER BY 1""").fetchall()
        return {int(b): {"mean_seniority": s, "n": n} for b, s, n in rows}

    at0, at5, at8 = _at_age(0), _at_age(5), _at_age(C.COMMON_WINDOW_YEARS)
    # entry-level seniority should be ~flat across cohorts if no survivorship;
    # a monotone gap by older cohort at equal age is the survivorship signature.
    entry_means = {b: v["mean_seniority"] for b, v in at0.items()}
    spread0 = (max(entry_means.values()) - min(entry_means.values())) if entry_means else None

    hum_gaps = {f"age_{a}": _hum_gap(a) for a in (0, 5, C.COMMON_WINDOW_YEARS)}
    con.close()

    return {
        "common_window_years": C.COMMON_WINDOW_YEARS,
        "seniority_at_entry_by_cohort": at0,
        "seniority_at_age_5_by_cohort": at5,
        f"seniority_at_age_{C.COMMON_WINDOW_YEARS}_by_cohort": at8,
        "entry_seniority_spread_across_cohorts": round(spread0, 4) if spread0 else None,
        "humanities_vs_non_seniority": hum_gaps,
        "humanities_note": (
            "hum_group='humanities' = any L1-humanities degree (pooled any-degree "
            "flag). Gap = humanities mean seniority - non-humanities, at equal "
            "career age (pooled over cohorts). Survivorship caveat applies equally "
            "to both groups, so the GAP is more trustworthy than either level."),
        "survivorship_note": (
            "At equal career age, older cohorts are observed only through members "
            "still active on LinkedIn in 2025 (survivors). A monotone seniority "
            "gap favouring older cohorts at the SAME age is therefore survivorship, "
            "not necessarily a cohort effect — interpret cross-cohort levels with "
            "this in mind; prefer the within-cohort scarring design (Phase 2)."),
        "runtime_s": round(time.monotonic() - started, 1),
        "output": str(C.OUT_DIR / "age_profiles.parquet"),
    }


def main() -> None:
    summary = build()
    (C.OUT_DIR / "_profiles_manifest.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
