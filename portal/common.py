"""Shared config + policy for the Pathways portal pipeline.

Every knob that bounds what a portal number can claim lives here, in one
auditable place (mirroring `cohorts/common.py` and `paths/common.py`).

Governing rules (from the repo methodology, non-negotiable):
  * Equal observation windows: a year-N statistic includes only people whose
    graduation anchor is >= N years before the snapshot, so every subject has a
    full, comparable window. Never compare a 2019 grad's year-10 to a 2005 grad's.
  * Gaps are unknown, never inferred unemployment.
  * No wage / representativeness claims: these are cohort statistics of LinkedIn
    survivors.
  * Re-derive from the committed parquet, never trust a stale manifest.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# DuckDB thread pool. The whole pipeline is parquet scan + hash join + windowed
# aggregation -- embarrassingly parallel -- so use (nearly) all cores. Was
# hardcoded to 8 across five entry points, which idled 24 of 32 cores on this
# box. Override with PORTAL_THREADS. Leave 2 cores for the OS / other work.
DEFAULT_THREADS = int(os.environ.get("PORTAL_THREADS") or max(4, (os.cpu_count() or 8) - 2))

# --- Inputs (verified against the repo 2026-07-07) --------------------------
EDUCATION = ROOT / "normalized" / "education.parquet"
STEPS = ROOT / "paths" / "steps.parquet"
TRANSITIONS = ROOT / "paths" / "transitions.parquet"
OCC_NODES = ROOT / "transition_network" / "occupation_nodes_analyzed.parquet"
STEP_INDUSTRY = ROOT / "industry" / "results" / "step_industry.parquet"
SOC_STATUS = ROOT / "reference" / "soc_status.parquet"
CIP_HUMANITIES = ROOT / "reference" / "cip_humanities.parquet"
TAXONOMY = ROOT / "industry" / "taxonomy.json"

OUT_DIR = ROOT / "portal" / "results"
DATA_OUT = OUT_DIR / "portal_data.json"
MANIFEST_OUT = ROOT / "portal" / "_manifest.json"

# --- Snapshot anchor --------------------------------------------------------
# Matches paths/common.SNAPSHOT_DATE = 2026-02-19 (corrected 2026-08-05 from a
# year-slipped 2025-02-19; see paths/common.py for the evidence).
SNAPSHOT_DATE = "2026-02-19"
# LAST_COMPLETE_YEAR here means the last FULLY observed calendar year, which is what
# every window cut (`LAST_COMPLETE_YEAR - N`, equal-window discipline) and every
# graduation-anchor bound in this package needs. Its value is unchanged by the
# date correction: 2026 is observed only through February, so a year-N statistic
# still requires an anchor <= 2025 - N, and a 2026 end_year is still a
# graduation that has not happened.
LAST_COMPLETE_YEAR = 2025  # == paths.common.LAST_COMPLETE_YEAR; renamed 2026-09-02 (audit M7) so it can never be confused with the 2026 calendar ceiling
# The calendar ceiling on observed steps and panel years -- the other year-grain
# fact. Use this, NOT LAST_COMPLETE_YEAR, when capping a date rather than a window.
SNAPSHOT_CAL_YEAR = 2026

# --- Population policy -------------------------------------------------------
# Analysis unit is (person, qualifying degree). A person enters a major's
# population if they hold a BACHELOR'S-level degree whose CIP family is in the
# bundle. Career outcomes are computed at person grain (a person's several
# qualifying degrees in one major collapse to one anchor -> no fan-out on
# linkedin_id, per the join-integrity guardrail).
BACHELOR_LEVEL = 4  # degree_level ordinal: 1 HS .. 3 associate, 4 bachelor, 6 master, 7 doctorate
MIN_ANCHOR_YEAR = 1950  # graduation years below this are treated as junk

# --- Graduation-anchor tiers (COVERAGE_PLAN.md Plan 2) -----------------------
# anchor_year now carries anchor_method provenance in {A1, A2, A3}
# (edu_clean/anchors.py). Only A1 (observed end_year) and A2 (start_year +
# empirically-fit duration) clear the >=80%-within-+/-1yr validation gate
# (edu_clean/results/anchor_eval.json); A3 (career-onset inference) measures
# ~31% within +/-1yr and ships flagged experimental only. ANCHOR_TIERS is the
# single knob every consumer must read -- default is the accepted set.
ANCHOR_TIERS: tuple[str, ...] = ("A1", "A2")

# --- Occupation sources (SOC major-group grain) ------------------------------
# "deterministic" = the O*NET lexicon backbone (6-digit, ~21.5% of steps).
# "llm_jury"      = career_clean SOC jury (2-digit major group only): two-model
#                   unanimity panel with retrieval-anchored evidence, calibrated
#                   at 0.887 major-group agreement on held-out deterministic
#                   gold (career_clean/results/soc_calibration.json; gate 0.85,
#                   PASSED). Propose-only: a jury label is used ONLY where the
#                   deterministic backbone abstained. 6-digit consumers
#                   (breadth, distinctive) remain deterministic-only.
# POOLED AS OF 2026-07-09 (full top-50k run merged: 38,604 strings, 3.50M
# steps). The full-coverage bias check retains ONE flag -- philrel Community &
# Social Service RR 8.48 -> 5.59 -- SIGNED OFF as deterministic-selection
# correction, not jury bias: philrel's own share GREW (8.0% -> 10.5%); the RR
# fell because the baseline's share doubled on face-valid strings (case
# manager, counselor, social worker; jury 15/17 on gold 21-strings). The
# deterministic lexicon codes philrel's signature religious titles but not
# the baseline's generic social-service titles, so the det-only RR was
# inflated by asymmetric coverage. Full audit trail:
# portal/results/soc_bias_check.json + portal/FINDINGS.md 2026-07-09.
SOC_SOURCES: tuple[str, ...] = ("deterministic", "llm_jury")
ROLE_SOC_JURY = ROOT / "normalized" / "mappings" / "role_soc_jury.parquet"

# --- CIP field-coding sources (membership grain) ------------------------------
# "deterministic" = the committed field->CIP crosswalk on education.parquet.
# "llm_jury"      = edu_clean CIP2 jury (family grain): two-model unanimity
#                   with coded-neighbor anchors, calibrated 0.911 unanimous on
#                   held-out gold (gate 0.85 PASSED;
#                   edu_clean/results/cip_calibration.json -- note the
#                   documented fuzzy-surface caveat). Fills cip2 ONLY where
#                   cip_code IS NULL; admits people to major bundles and the
#                   baseline. Tier boundaries (nha_level) stay committed-
#                   crosswalk-only (the crosswalk is 6-digit-keyed).
# POOLED AS OF 2026-07-09: top-25k run merged (18,708 strings / 362,263 rows;
# unanimity 76%, abstention 12.6%). cip_bias_check verdict: NO material
# composition drift (largest up_share delta 0.0021 vs the 0.03 bar; the first
# run's english flags were a rank-boundary artifact in the CHECK -- it
# compared top-5 sets; fixed to full cell dicts and documented in FINDINGS).
# Windowed cohort growth: arts +27.5%, philrel +21.9%, commmedia +20.7%,
# english +18.9%, history +2.1%, baseline +14.5%.
CIP_SOURCES: tuple[str, ...] = ("deterministic", "llm_jury")
FIELD_CIP_JURY = ROOT / "normalized" / "mappings" / "field_cip_jury.parquet"

# --- Horizons / window ------------------------------------------------------
# Long-view curve horizons (years since graduation anchor).
CURVE_YEARS = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
# The headline "fan / sectors / KPI" horizon.
FAN_YEAR = 10

# --- Suppression / support thresholds --------------------------------------
# THE single global named-cell bar. Loosened 40 -> 10 by user directive
# (2026-07-13, PORTAL_REDESIGN_PLAN.md): every consumer -- fan cells, curve
# points, distinctive destinations, named pathway routes, launchboard fans,
# grad-track headline, named employers, choice-subset fans -- reads this knob;
# no module or test may carry its own literal bar.
MIN_SUPPORT = 10          # suppress any reported cell with person-support < MIN_SUPPORT
BREADTH_MIN_PERSONS = 5   # a node counts toward breadth only with >=5 distinct people
# --- Within-group occupation drill-down bar (the "what does Management mean?"
# composition). Historically DELIBERATELY below the (then-40) headline bar: the
# composition of the ~30% of a fan cell which carries a deterministic 6-digit
# role is a descriptive breakdown of a coded subset, not a population estimate
# -- the same footing as the breadth KPI, which reports occupation-node reach
# at >=5 distinct people. Since the 2026-07-13 loosening the two bars COINCIDE
# at 10; this stays a separate knob because its rationale (coded-subset
# composition) is independent of the headline suppression policy. Every role
# below this bar folds into `other_coded_n`, and the UI badges the drill-down
# as a coded-subset composition.
DETAIL_MIN_SUPPORT = 10
DISTINCTIVE_RR = 1.5      # RR bar for a "distinctive" destination
DISTINCTIVE_MIN = MIN_SUPPORT  # person-support bar for a distinctive destination
FAN_TOP = None            # report all soc-major fan cells clearing MIN_SUPPORT
SECTOR_TOP = 8            # top-N industry L1 sectors, rest folded into "Other"
PATH_MIN_PERSONS = MIN_SUPPORT  # emit a named route only with >= this many distinct persons
PATH_SUPPRESS_FLOOR = 2   # routes with support in [2, PATH_MIN_PERSONS) count as suppressed
# NOTE (historical, measured at the old 40 bar): at these per-major windowed
# cohort sizes (1-5k persons) with role_canonical cardinality in the tens of
# thousands, NO contiguous 3-4-step exact role chain reached 40 persons
# (measured max support = 8) -- see FINDINGS.md "Named pathways".
# 2026-07-09: minimum stages lowered 3 -> 2 after the SOC jury expansion;
# 3-4-stage chains of DISTINCT groups stayed under 40 (max suppressed support
# ~30s) while 2-stage group transitions cleared it. With the bar now at
# MIN_SUPPORT=10 (2026-07-13), longer chains can clear again; routes remain
# labeled by their stage count in the portal.
PATH_MIN_STAGES = 2
PATH_MAX_STAGES = 4
PATH_TOP = 8              # emit at most this many named routes per major

# --- The five portal majors (extensible: majors are config, not code) -------
# key -> (display name, [cip2 families], nha tier label the portal must show)
MAJORS: dict[str, tuple[str, list[str], str]] = {
    "english":   ("English & Literature",     ["23"],        "L1"),
    "history":   ("History",                  ["54"],        "L1"),
    "philrel":   ("Philosophy & Religion",    ["38", "39"],  "L1"),
    "arts":      ("Fine & Performing Arts",   ["50"],        "L1"),
    "commmedia": ("Communication & Media",    ["09"],        "L2"),
}
BASELINE_KEY = "baseline"

# Upward-typed transitions (headline direction). Down equivalents are NOT
# reported as headline numbers: the repo's own calibration found revealed "down"
# is near-chance (~50%). See METHODOLOGY HIGH-3.
UP_TYPES = ("promotion", "employer_move_up", "occupation_change_up")
# "Deliberate pivot" moves for the Direction pillar (an intentional occupation
# change, up or neutral or down -- a change of field, not a demotion claim).
PIVOT_TYPES = ("occupation_change", "occupation_change_up", "occupation_change_down")

# Industry L1 code treated as the unresolved / catch-all bucket.
INDUSTRY_UNRESOLVED_CODE = "XOT"


def q(p) -> str:
    """SQL-safe single-quoted path/string literal body."""
    return str(p).replace("'", "''")


def soc_major_case(col: str) -> str:
    """SQL CASE mapping a 6-digit SOC code column (e.g. '27-3043') to its BLS
    major-group label via the 2-digit prefix. Mirrors transition_network.SOC_MAJOR."""
    from transition_network.common import SOC_MAJOR
    whens = " ".join(
        f"WHEN substr({col}, 1, 2) = '{k}' THEN '{v}'" for k, v in SOC_MAJOR.items()
    )
    return f"CASE {whens} ELSE NULL END"


def soc_major_label_case(col: str) -> str:
    """SQL CASE mapping a bare 2-digit major-group code column (the jury's
    grain) to its label. NULL for anything off-taxonomy."""
    from transition_network.common import SOC_MAJOR
    whens = " ".join(f"WHEN {col} = '{k}' THEN '{v}'" for k, v in SOC_MAJOR.items())
    return f"CASE {whens} ELSE NULL END"


def load_industry_l1_labels() -> dict[str, str]:
    """L1 industry code -> human label, from the committed taxonomy."""
    tax = json.loads(TAXONOMY.read_text())
    return {n["code"]: n["label"] for n in tax["nodes"] if n["level"] == 1}


def major_cip_predicate(families: list[str], alias: str = "e") -> str:
    """SQL predicate selecting rows in a major's CIP2 bundle."""
    fam = ", ".join(f"'{f}'" for f in families)
    return f"{alias}.cip2 IN ({fam})"
