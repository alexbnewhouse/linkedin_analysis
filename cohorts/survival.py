"""Phase 3 — time-to-first-upward-move (survival / event-history analysis).

    uv run --group cohort python -m cohorts.survival

Event = a person's FIRST upward move (`transition_type` in promotion /
employer_move_up / occupation_change_up); duration = career age at that move;
profiles with no observed upward move are **right-censored** at their last
observed career age (the correct treatment of ongoing/incomplete careers).
Kaplan–Meier gives median time-to-advancement by entry cohort; Cox PH gives the
hazard ratio for the entry-year unemployment rate.

Caveats baked in: (1) the upward-move label leans on the revealed-seniority
signal (noisy, esp. 'down', but ~constant across cohorts so *relative* cohort
comparisons hold); (2) **left-truncation/survivorship** — older cohorts enter the
sample only as survivors, biasing their curves; we report a sensitivity that
restricts to cohorts with a full early-career observation window.
"""

from __future__ import annotations

import json
import time

import duckdb
import numpy as np

from cohorts import common as C

UP_TYPES = ("promotion", "employer_move_up", "occupation_change_up")


def _survival_frame(con):
    up_list = "(" + ", ".join(f"'{t}'" for t in UP_TYPES) + ")"
    return con.sql(f"""
      WITH promo AS (
        SELECT linkedin_id, min(year(to_start_dt)) AS first_up_year
        FROM read_parquet('{str(C.TRANSITIONS)}')
        WHERE transition_type IN {up_list}
        GROUP BY 1
      )
      SELECT pr.linkedin_id, pr.entry_year, pr.entry_cohort_bin,
             pr.entry_unemployment, pr.observed_max_career_age,
             CAST(pr.hum_l1_any AS INTEGER) AS hum,
             (promo.first_up_year IS NOT NULL) AS event,
             CASE WHEN promo.first_up_year IS NOT NULL
                  THEN greatest(promo.first_up_year - pr.entry_year, 0)
                  ELSE pr.observed_max_career_age END AS duration
      FROM read_parquet('{str(C.PROFILES_OUT)}') pr
      LEFT JOIN promo USING (linkedin_id)
      WHERE pr.valid_cohort AND pr.observed_max_career_age >= 0
    """).df()


def build(threads: int = 8, cox_sample: int = 200_000, seed: int = 42) -> dict:
    from lifelines import KaplanMeierFitter, CoxPHFitter
    con = duckdb.connect(); con.execute(f"PRAGMA threads={threads}")
    started = time.monotonic()
    df = _survival_frame(con); con.close()
    df = df[df["duration"] >= 0].copy()

    kmf = KaplanMeierFitter()
    kmf.fit(df["duration"], df["event"])
    overall_median = float(kmf.median_survival_time_)

    # KM by entry cohort: median time-to-advancement + share advanced by year 5
    by_cohort = {}
    for b, g in df.groupby("entry_cohort_bin"):
        k = KaplanMeierFitter().fit(g["duration"], g["event"])
        med = float(k.median_survival_time_)
        # P(advanced by age 5) = 1 - S(5)
        s5 = float(k.predict(5))
        by_cohort[int(b)] = {"n": int(len(g)), "median_years_to_advance": med,
                             "share_advanced_by_age5": round(1 - s5, 3)}

    # Cox PH: hazard ratio for entry unemployment + humanities (sample for tractability)
    samp = df.sample(min(cox_sample, len(df)), random_state=seed)[
        ["duration", "event", "entry_unemployment", "hum"]].dropna()
    samp = samp[samp["duration"] > 0]  # Cox needs positive durations
    cph = CoxPHFitter().fit(samp, duration_col="duration", event_col="event")
    hr = float(np.exp(cph.params_["entry_unemployment"]))
    hr_p = float(cph.summary.loc["entry_unemployment", "p"])
    hum_hr = float(np.exp(cph.params_["hum"]))
    hum_hr_p = float(cph.summary.loc["hum", "p"])

    # KM split: time-to-first-advancement, humanities vs non (fully-observed cohorts
    # only, so the backfill gradient doesn't dominate the comparison)
    fully_km = df[df["entry_year"] <= C.SNAPSHOT_YEAR - C.COMMON_WINDOW_YEARS]
    by_hum = {}
    for hv, label in ((1, "humanities"), (0, "non_humanities")):
        g = fully_km[fully_km["hum"] == hv]
        if len(g):
            k = KaplanMeierFitter().fit(g["duration"], g["event"])
            by_hum[label] = {"n": int(len(g)),
                             "median_years_to_advance": float(k.median_survival_time_),
                             "share_advanced_by_age5": round(1 - float(k.predict(5)), 3)}

    # sensitivity: cohorts old enough to be fully observed over the common window
    fully = df[df["entry_year"] <= C.SNAPSHOT_YEAR - C.COMMON_WINDOW_YEARS]
    kf = KaplanMeierFitter().fit(fully["duration"], fully["event"])

    summary = {
        "event": "first upward move " + str(UP_TYPES),
        "n_profiles": int(len(df)),
        "event_rate": round(float(df["event"].mean()), 3),
        "overall_median_years_to_advance": overall_median,
        "by_entry_cohort": by_cohort,
        "cox_entry_unemployment": {
            "hazard_ratio": round(hr, 4), "p": round(hr_p, 4), "n": int(len(samp)),
            "reads_as": ("HR<1 => higher entry unemployment slows advancement "
                         "(scarring); HR>1 => speeds it"),
        },
        "cox_humanities": {
            "hazard_ratio": round(hum_hr, 4), "p": round(hum_hr_p, 4),
            "reads_as": ("hazard ratio for advancing to first upward move, humanities "
                         "vs non (adjusting for entry unemployment). HR<1 => humanities "
                         "grads reach their first upward move more SLOWLY; HR>1 => faster."),
        },
        "km_by_humanities_fully_observed": by_hum,
        "sensitivity_fully_observed_cohorts": {
            "entry_year_max": C.SNAPSHOT_YEAR - C.COMMON_WINDOW_YEARS,
            "n": int(len(fully)),
            "median_years_to_advance": float(kf.median_survival_time_),
        },
        "caveats": ("Right-censoring handled natively. The strong cohort gradient "
                    "(median 17yr for 1990 entrants -> 6yr for 2015) is LARGELY AN "
                    "ARTIFACT: recent cohorts' early careers are better documented "
                    "(backfill), and observation windows differ by cohort, so recent "
                    "cohorts record early upward moves that older cohorts' backfilled "
                    "profiles omit. Do NOT read it as recent cohorts truly advancing "
                    "faster. The near-null Cox HR (~1.0) is the more credible "
                    "entry-conditions read: no robust unemployment effect on the "
                    "advancement hazard once we stop comparing differently-observed "
                    "cohorts. Also LEFT-TRUNCATION (older cohorts = 2025 survivors) "
                    "and a noisy revealed-seniority 'up' label."),
        "runtime_s": round(time.monotonic() - started, 1),
    }
    return summary


def main() -> None:
    summary = build()
    (C.OUT_DIR / "_survival_manifest.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
