"""Shared config for cohort analysis (COHORT_ANALYSIS_PLAN.md).

Cohort analysis tracks how outcomes evolve for groups sharing a starting point
(entry-year, graduation-year, ...). The governing hazard is **selection**:
LinkedIn is a present-day snapshot of survivors, so older cohorts are observed
only if still active/online in 2025 (left-truncation / survivorship). Every knob
that bounds what a comparison can claim lives here, in one auditable place.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPS = ROOT / "paths" / "steps.parquet"
TRANSITIONS = ROOT / "paths" / "transitions.parquet"
BLS = ROOT / "reference" / "bls_unemployment.parquet"
OUT_DIR = ROOT / "cohorts"
PANEL_OUT = OUT_DIR / "panel.parquet"
PROFILES_OUT = OUT_DIR / "profiles.parquet"

# Snapshot anchor years (matches paths/common.SNAPSHOT_DATE = 2026-02-19,
# corrected 2026-08-05 from a year-slipped 2025-02-19).
# LAST_COMPLETE_YEAR is the last FULLY observed calendar year -- what every window cut
# (`LAST_COMPLETE_YEAR - COMMON_WINDOW_YEARS`) and every graduation-year bound needs;
# its value is unchanged by the correction, because 2026 is observed only through
# February. SNAPSHOT_CAL_YEAR is the calendar ceiling on observed steps and panel
# years: use it when capping a date rather than a window.
LAST_COMPLETE_YEAR = 2025  # == paths.common.LAST_COMPLETE_YEAR (audit 2026-09-02 M7 rename)
SNAPSHOT_CAL_YEAR = 2026

# --- Valid-cohort bounds ----------------------------------------------------
# Entry years outside this range are too sparse / too survivorship-biased
# (pre-1990) or too right-censored to study at the common window (post-2018).
MIN_ENTRY_YEAR = 1990
MAX_ENTRY_YEAR = 2020

# Equal-career-age comparison window. Cohorts are compared only over career ages
# observable for ALL of them (the left-truncation/right-censoring control); also
# the horizon over which recession-scarring is documented to fade (~8-10 yrs).
COMMON_WINDOW_YEARS = 8

# Half-decade entry-cohort bins for grouped reporting.
COHORT_BIN_YEARS = 5

# --- Generational boundaries (PROXIED; no birth date exists) ----------------
# Birth year proxied as entry_year - ENTRY_AGE_PROXY. Labels are approximate and
# must be reported as proxies, never as truth (COHORT_ANALYSIS_PLAN §3.5).
ENTRY_AGE_PROXY = 22
GENERATIONS = [  # (label, birth_lo, birth_hi) inclusive
    ("Boomer", 1946, 1964),
    ("Gen X", 1965, 1980),
    ("Millennial", 1981, 1996),
    ("Gen Z", 1997, 2012),
]


def generation_for_birth_year_sql(col: str) -> str:
    """SQL CASE mapping a (proxied) birth-year column to a generation label."""
    whens = " ".join(
        f"WHEN {col} BETWEEN {lo} AND {hi} THEN '{lab}'" for lab, lo, hi in GENERATIONS
    )
    return f"CASE {whens} ELSE NULL END"
