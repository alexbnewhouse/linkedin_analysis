"""Shared constants and helpers for the career-path / transition-network spine.

The spine turns ``normalized/career_steps.parquet`` (one row per career step,
fields already entity-resolved by ``career_clean``) into two tables:

- ``paths/steps.parquet``       — Layer 3+4: every step with a typed time
                                  interval, sequence position, and concurrency
                                  flags.
- ``paths/transitions.parquet`` — Layer 5: one row per observed move between
                                  successive *primary* steps of a person, the
                                  edge list every transition-network grain
                                  (occupation / title / employer / industry /
                                  employment-type) is later aggregated from.

This module only holds configuration that the SQL builder interpolates, so the
policy decisions (snapshot anchor, primary-role rule, sanity bounds, seniority
ordering) live in one auditable place. See ``CAREER_TRANSITION_NETWORK_PLAN.md``
§3 and ``CAREER_PATHS_PLAN.md`` Layers 3-5.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAREER_STEPS = ROOT / "normalized" / "career_steps.parquet"
OUT_DIR = ROOT / "paths"
STEPS_OUT = OUT_DIR / "steps.parquet"
TRANSITIONS_OUT = OUT_DIR / "transitions.parquet"
MANIFEST_OUT = OUT_DIR / "_manifest.json"

# --- Open decision #1 (CAREER_PATHS_PLAN): the "Present" anchor -------------
# Raw snapshot files are dated 2025-02-19. Open intervals (end_date='Present')
# are closed here, NOT at "today", so ongoing roles do not silently lengthen.
SNAPSHOT_DATE = "2025-02-19"

# --- Sanity bounds (CAREER_PATHS_PLAN §7) -----------------------------------
# Profiles with absurd step counts are scrape/merge garbage, and their O(n^2)
# concurrency self-join would dominate runtime. The max observed is 715; the
# 99.9th percentile is well under 100.
MAX_STEPS_PER_PROFILE = 100
# Gap/overlap are computed at month resolution from the month-floors of the two
# boundaries (so a same-month A-ends/B-starts handoff is NOT a gap). A run of at
# least GAP_MONTHS_MIN empty months surfaces has_gap; an interval co-occurrence
# of at least OVERLAP_MONTHS_MIN months surfaces has_overlap (2 ignores the
# one-month same-month-handoff artifact and flags only genuine concurrency).
GAP_MONTHS_MIN = 1
OVERLAP_MONTHS_MIN = 2

# Date format strings for the two LinkedIn granularities (single source).
MONTH_FMT = "%b %Y"
YEAR_FMT = "%Y"

# --- Concurrency / primary-role policy (Open decision #2) -------------------
# Two steps are "concurrent" when their intervals overlap by at least this
# fraction of the shorter interval. The lower-ranked of two concurrent steps is
# flagged is_concurrent_secondary and dropped from the primary timeline that
# edges are built along. Ranking (best first): in-workforce > side, then longer
# dwell, then more senior, then earlier start, then lower row_id (stable).
CONCURRENCY_OVERLAP_FRAC = 0.5

# Employment types that count as "in the workforce" for primary ranking.
WORKFORCE_TYPES = ("employee", "business_owner", "self_employed")
# Self-employment axis: entering/leaving these is a first-class transition kind.
SELF_EMPLOYED_TYPES = ("self_employed", "business_owner")
# Terminal / out-of-workforce destinations -> classified as 'exit'.
EXIT_TYPES = ("retired", "unemployed", "homemaker")

# --- Seniority ordinal ------------------------------------------------------
# career_clean emits TWO comma-joined *sorted sets* of seniority tokens per
# step: ``seniority_level`` (the level-signature tokens that are part of the
# title canonical identity) and ``seniority_rank_token`` (a superset on a
# separate axis -- same tokens PLUS rank-only words like 'manager' and
# 'supervisor' that belong to the base-role identity and so can never enter the
# level signature). The spine reads ``seniority_rank_token`` (falling back to
# ``seniority_level`` for older career_steps builds) and collapses a step to a
# single ordinal = the rank of its most-senior NAMED token. A step with no named
# token -- the empty string (a title with no parseable seniority word) OR only
# numeric band tokens (lvl1, lvl2, ... which are company-specific and not
# globally orderable) -- gets ordinal = NULL, i.e. *unknown* seniority.
# A move is only scored up/flat/down when BOTH endpoints carry a named token;
# otherwise the direction is 'unknown'. This deliberately refuses to read
# "Senior Engineer -> Consultant" as a demotion just because "Consultant" lacks
# a marker (the prior empty-string -> base-rank default manufactured ~80% of
# all demotion/promotion labels -- see red-team H3).
SENIORITY_RANK: dict[str, int] = {
    "intern": 0,
    "trainee": 0,
    "junior": 1,
    "associate": 2,
    "staff": 4,
    "senior": 4,
    "lead": 4,
    "principal": 5,
    "supervisor": 5,  # first-line supervisor: above senior/lead, below manager
    "head": 6,
    "manager": 6,
    "director": 7,
    "vice": 8,  # VP
    "executive": 9,
    "chief": 9,  # C-suite
}


# --- Fused seniority + transition typing (SENIORITY_TRANSITIONS_PLAN) --------
# Layer C revealed per-role seniority, produced by paths/seniority.py.
SENIORITY_SCORES_PATH = OUT_DIR / "seniority_scores.parquet"
# Layer B cross-occupation status anchor (O*NET Job Zone), keyed on SOC.
SOC_STATUS_PATH = ROOT / "reference" / "soc_status.parquet"
# Fusion weights for the per-step seniority_score. Three layers, all on [0,1],
# all increasing with seniority: lexical within-role level (A), revealed
# cross-role level from SpringRank (C), Job Zone cross-occupation status (B).
W_LEXICAL = 1.0
W_REVEALED = 1.0
W_JOBZONE = 0.5  # coarse (occupation-level, constant within a SOC) -> lower weight
LEX_MAX_RANK = 9.0  # max SENIORITY_RANK value, to normalize the lexical ordinal
# A move is directional only when |Δseniority_score| exceeds the threshold AND
# the seniority confidence clears CONF_MIN; otherwise it stays neutral
# (employer_move / lateral) — never manufacture a direction without confidence.
# Calibrated by paths/tune_thresholds.py against the lexical layer as silver
# truth: the *revealed* signal recovers lexical direction ~62% of the time, with
# 'up' (~65%) far more reliable than 'down' (~50%, near chance), and accuracy
# flat across τ. So τ_down is set higher than τ_up — demotions require stronger
# evidence — and all revealed-only directional labels remain propose-only with
# the confidence attached. This is the honest ceiling of a flow-revealed signal
# compared against a (itself-noisy, cross-role) lexical truth; treat directional
# labels on no-lexical-word edges as proposals, not ground truth.
TAU_UP = 0.08
TAU_DOWN = 0.12
CONF_MIN = 0.3
SOC_MAJOR_LEN = 2  # occupation-change is judged at the SOC major-group level


def sql_in_list(values: tuple[str, ...]) -> str:
    """Render a value tuple as a SQL ``IN (...)`` body with escaped literals.

    Single source of truth for membership tests interpolated into the spine SQL;
    safe regardless of element count or apostrophes in values.
    """
    return "(" + ", ".join("'" + v.replace("'", "''") + "'" for v in values) + ")"
