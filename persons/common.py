"""Shared config and pure helpers for the person summary table and metrics cube (spec P6).

Both time axes are carried, never coalesced:
  career_years_entry  LAST_COMPLETE_YEAR - entry_year (first datable primary step)
  career_years_grad   LAST_COMPLETE_YEAR - bachelor_end_year (deterministic bachelor rung)
Every reported cell is suppressed below portal.common.MIN_SUPPORT persons.
"""
from __future__ import annotations

import math
from pathlib import Path

from paths.common import LAST_COMPLETE_YEAR, SENIORITY_RANK, SNAPSHOT_DATE, SNAPSHOT_YEAR  # noqa: F401
from portal.common import MIN_SUPPORT  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
EDU_PERSON = ROOT / "normalized" / "education_person.parquet"
CAREER_STEPS = ROOT / "normalized" / "career_steps.parquet"
STEPS = ROOT / "paths" / "steps.parquet"
STEP_INDUSTRY = ROOT / "industry" / "results" / "step_industry.parquet"
CIP_HUM = ROOT / "reference" / "cip_humanities.parquet"
OUT_DIR = ROOT / "persons"
PERSON_OUT = OUT_DIR / "person.parquet"
STEPS_OUT = OUT_DIR / "person_steps.parquet"
MANIFEST = OUT_DIR / "_manifest.json"
RESULTS = OUT_DIR / "results"
METRICS_OUT = RESULTS / "metrics.json"
TABLES = RESULTS / "tables"

STAGES: list[tuple[int, int, str]] = [(0, 2, "0-2"), (3, 5, "3-5"), (6, 10, "6-10"), (11, 20, "11-20"), (21, 999, "21+")]
STAGE_ORDER = [s for _, _, s in STAGES]
HORIZONS = (1, 5, 10, 20)
MIN_GROUP_N = 300         # cip2:<code> groups need this many persons
MANAGER_RANK = SENIORITY_RANK["manager"]     # 6
DIRECTOR_RANK = SENIORITY_RANK["director"]   # 7
VP_RANK = SENIORITY_RANK["vice"]             # 8


def stage(years: int | None) -> str | None:
    if years is None or years < 0:
        return None
    for lo, hi, label in STAGES:
        if lo <= years <= hi:
            return label
    return None


def stage_sql(col: str) -> str:
    whens = " ".join(f"WHEN {col} BETWEEN {lo} AND {hi} THEN '{label}'" for lo, hi, label in STAGES)
    return f"CASE WHEN {col} IS NULL OR {col} < 0 THEN NULL {whens} END"


def attainment(seniority_level: str | None) -> dict[str, bool]:
    """From the comma-joined lexical seniority token set of ONE step."""
    ranks = [SENIORITY_RANK[t] for t in (seniority_level or "").split(",") if t in SENIORITY_RANK]
    top = max(ranks) if ranks else -1
    return {"manager_plus": top >= MANAGER_RANK, "director_plus": top >= DIRECTOR_RANK, "vp_plus": top >= VP_RANK}


def entropy(counts: list[int]) -> float:
    tot = sum(counts)
    if tot <= 0:
        return 0.0
    return -sum((c / tot) * math.log(c / tot) for c in counts if c > 0)


def cover80(counts: list[int]) -> int:
    tot = sum(counts)
    if tot <= 0:
        return 0
    cum = 0
    for k, c in enumerate(sorted(counts, reverse=True), start=1):
        cum += c
        if cum / tot >= 0.8:
            return k
    return len(counts)


def top3(counts: list[int]) -> float:
    tot = sum(counts)
    if tot <= 0:
        return 0.0
    return sum(sorted(counts, reverse=True)[:3]) / tot


def suppress(cells: list[tuple[str, int]], floor: int) -> tuple[list[tuple[str, int]], int]:
    """Primary suppression below ``floor`` plus the audit 2.11 two-cell rule: when exactly
    one cell is below the floor, the next-smallest kept cell is suppressed too, so the
    single small cell cannot be recovered by subtraction from the panel total. Returns
    (kept cells, number suppressed)."""
    kept = [(k, n) for k, n in cells if n >= floor]
    n_sup = len(cells) - len(kept)
    if n_sup == 1 and kept:
        smallest = min(kept, key=lambda kv: kv[1])
        kept = [kv for kv in kept if kv is not smallest]
        n_sup += 1
    return kept, n_sup


def suppressed_count_for_output(n_sup: int) -> int | None:
    """Only report a suppressed-cell count when at least two cells were suppressed."""
    return n_sup if n_sup >= 2 else None
