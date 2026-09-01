"""Phase 2 — entry-conditions ("scarring") regression: the identified design.

    uv run --group cohort python -m cohorts.scarring

The APC identity (career_age = period - entry_year) means age/period/cohort
levels are not separately identified. The escape (Oreopoulos-von Wachter-Heisz
2012) is to replace "cohort" with an EXOGENOUS cohort characteristic — the
unemployment rate at labor-market entry — and estimate its effect on later
outcomes controlling for career age and calendar-period fixed effects. Because
the entry-unemployment rate is a *nonlinear* function of entry_year, it has
within-period variation across ages and is identified despite the APC trap.

Estimator: collapse the 40M-row panel to (entry_year, career_age) cells with mean
`seniority_score` and cell size, then WLS (weight = cell n) of

    mean_seniority ~ entry_unemployment + entry_unemployment:career_age
                     + career_age + career_age^2 + C(calendar_year)

with SEs clustered by entry_year (the cohort). The signature to look for: a
NEGATIVE `entry_unemployment` coefficient (worse entry → lower early seniority)
and a POSITIVE interaction with career_age (the scar fades with experience).
Caveat: outcome is unconditional seniority (no occupation control); levels still
carry the survivorship caveat of Phase 1, but the *within-cohort* unemployment
variation is what identifies the effect.
"""

from __future__ import annotations

import json
import time

import duckdb
import numpy as np
import statsmodels.formula.api as smf

from cohorts import common as C

MAX_AGE = 15  # horizon over which to estimate the scar + its fade


def build(threads: int = 8) -> dict:
    con = duckdb.connect(); con.execute(f"PRAGMA threads={threads}")
    started = time.monotonic()
    # cells now split by humanities (hum=1 iff any L1 degree, pooled any-degree
    # flag) so the regression can carry a recession x humanities interaction:
    # does entering the labor market in a downturn scar humanities grads MORE?
    df = con.sql(f"""
      SELECT entry_year, career_age,
             CASE WHEN hum_l1_any THEN 1 ELSE 0 END AS hum,
             (entry_year + career_age) AS calendar_year,
             any_value(entry_unemployment) AS entry_unemployment,
             count(*) AS n,
             avg(seniority_score) AS mean_seniority
      FROM read_parquet('{str(C.PANEL_OUT)}')
      WHERE valid_cohort AND career_age BETWEEN 0 AND {MAX_AGE}
        AND seniority_score IS NOT NULL AND entry_unemployment IS NOT NULL
      GROUP BY 1, 2, 3
    """).df()
    con.close()
    df["age2"] = df["career_age"] ** 2
    df["period"] = df["calendar_year"].astype(str)  # string -> patsy categorical FE

    base = smf.wls("mean_seniority ~ entry_unemployment + entry_unemployment:career_age "
                   "+ career_age + age2", data=df, weights=df["n"])
    full = smf.wls("mean_seniority ~ entry_unemployment + entry_unemployment:career_age "
                   "+ career_age + age2 + period", data=df, weights=df["n"])
    # humanities-differential scar: the entry_unemployment:hum coefficient
    hum_spec = smf.wls(
        "mean_seniority ~ entry_unemployment + entry_unemployment:career_age "
        "+ entry_unemployment:hum + hum + career_age + age2", data=df, weights=df["n"])
    cl = {"groups": df["entry_year"]}
    rb = base.fit(cov_type="cluster", cov_kwds=cl)
    rf = full.fit(cov_type="cluster", cov_kwds=cl)
    rh = hum_spec.fit(cov_type="cluster", cov_kwds=cl)

    def _coef(res, name):
        return {"coef": round(float(res.params[name]), 5),
                "se": round(float(res.bse[name]), 5),
                "p": round(float(res.pvalues[name]), 4)}

    # Headline = age-controlled spec (rb). Adding full period FE (rf) OVER-controls
    # here: at the (entry_year, career_age) cell grain, period = entry+age pins the
    # cohort, so calendar FE + age polynomial absorb entry_unemployment (the APC
    # collinearity resurfacing at cell level) — reported as a robustness contrast.
    scar0 = rb.params["entry_unemployment"]
    fade = rb.params["entry_unemployment:career_age"]
    years_to_fade = round(float(-scar0 / fade), 1) if fade else None

    summary = {
        "design": "WLS on (entry_year, career_age) cells; SE clustered by entry_year",
        "cells": len(df), "max_age": MAX_AGE,
        "n_clusters": int(df["entry_year"].nunique()),
        "headline_age_controlled": {
            "entry_unemployment": _coef(rb, "entry_unemployment"),
            "entry_unemployment:career_age": _coef(rb, "entry_unemployment:career_age"),
        },
        "robustness_with_period_FE": {
            "entry_unemployment": _coef(rf, "entry_unemployment"),
            "entry_unemployment:career_age": _coef(rf, "entry_unemployment:career_age"),
            "note": "period FE over-controls at cell grain (period=entry+age pins cohort)",
        },
        "humanities_differential_scar": {
            "entry_unemployment": _coef(rh, "entry_unemployment"),
            "entry_unemployment:hum": _coef(rh, "entry_unemployment:hum"),
            "hum": _coef(rh, "hum"),
            "reads_as_humanities_scarred_more": bool(
                rh.params["entry_unemployment:hum"] < 0
                and rh.pvalues["entry_unemployment:hum"] < 0.05),
            "note": ("entry_unemployment:hum is the humanities-vs-non differential in "
                     "the entry-recession scar. NEGATIVE + significant => humanities "
                     "grads are scarred MORE by entering in a downturn; ~0 => the scar "
                     "is common to all fields. Same confound caveat as the headline; "
                     "the graduation-year instrument (cleaner but only ~15% datable, "
                     "so under-powered) is the documented alternative, not the "
                     "default -- the module uses the full-coverage entry-year axis."),
        },
        "interpretation": {
            "initial_scar_per_pct_unemployment": round(float(scar0), 5),
            "fade_per_career_year": round(float(fade), 5),
            "implied_years_until_scar_fades": years_to_fade,
            "reads_as_scarring": bool(scar0 < 0 and fade > 0),
            "note": ("Age-controlled: negative initial effect + positive fade = the "
                     "recession-scarring signature (worse entry depresses early "
                     "seniority, converging over the implied horizon)."),
            "CONFOUND_WARNING": ("This is NOT a clean causal scar. Recent cohorts have "
                     "BOTH low entry-unemployment AND better-documented early careers "
                     "(Phase-1 recency/backfill bias), so the negative coefficient "
                     "partly reflects that recent (low-unemployment) cohorts simply "
                     "record higher early seniority. Full period FE removes the effect "
                     "but over-controls. Treat the magnitude as suggestive, not "
                     "identified; a clean estimate needs within-cohort variation our "
                     "backfill-biased snapshot cannot fully provide."),
        },
        "runtime_s": round(time.monotonic() - started, 1),
    }
    return summary


def main() -> None:
    summary = build()
    (C.OUT_DIR / "_scarring_manifest.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
