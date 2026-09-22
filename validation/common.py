"""Shared config for external-benchmark validation (spec P1).

Compares LinkedIn shares on the bachelor's rung against NCES Digest Table
322.10 (bachelor's degrees by field) and Humanities Indicators. Reporting only.
"""
from __future__ import annotations

import json
from pathlib import Path

from paths.common import LAST_COMPLETE_YEAR, SNAPSHOT_DATE  # noqa: F401  (re-exported)

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
EDU_PERSON = ROOT / "normalized" / "education_person.parquet"
NCES = ROOT / "reference" / "nces_bachelors_by_field.json"
HI = ROOT / "reference" / "humanities_indicators.json"
OUT = ROOT / "validation" / "results" / "external_benchmarks.json"

# CIP 2-digit families with a one-to-one Digest line. core6 is the strict
# NCES-comparable humanities proxy; l1_proxy adds the two lines the repo's L1
# definition adds (theology 39, visual & performing arts 50).
CORE6 = ("05", "16", "23", "24", "38", "54")
CORE6_LINES = ("area_ethnic", "foreign_lang", "english", "liberal_arts_hum", "phil_rel", "history")
L1_PROXY = CORE6 + ("39", "50")
L1_PROXY_LINES = CORE6_LINES + ("theology", "visual_performing_arts")
NAMED = {"english": "23", "history": "54", "business": "52", "cs": "11",
         "communication": "09", "psychology": "42"}
YEAR_TOLERANCE = 1
# Advanced-degree attainment is a stock among people who have had time to
# finish; compare only cohorts at least ten years past the bachelor's.
ADVANCED_DEGREE_COHORT_MAX_YEAR = LAST_COMPLETE_YEAR - 10


def year_bucket(end_year: int | None, targets: list[int]) -> int | None:
    if end_year is None:
        return None
    best = min(targets, key=lambda t: (abs(t - end_year), t))
    return best if abs(best - end_year) <= YEAR_TOLERANCE else None


def shares(rows: list[tuple[str, int]]) -> dict[str, float]:
    tot = sum(n for _, n in rows)
    return {k: (n / tot if tot else 0.0) for k, n in rows}


def nces_history(y: dict, est_share: float) -> tuple[float, bool]:
    """History count for a Digest year: printed (Table 325.92) or estimated as
    a share of the 'social sciences and history' line. Returns (count, estimated)."""
    if y.get("history") is not None:
        return float(y["history"]), False
    return y["socsci_history"] * est_share, True


def nces_group_share(y: dict, lines: tuple[str, ...], est_share: float) -> float:
    total = 0.0
    for line in lines:
        if line == "history":
            total += nces_history(y, est_share)[0]
        else:
            total += y[line]
    return total / y["total"]


def load_nces() -> dict:
    return json.loads(NCES.read_text())


def load_hi() -> dict:
    return json.loads(HI.read_text())
