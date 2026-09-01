"""CIP 2020 2-digit family taxonomy for the LLM-jury field-of-study coder.

The label space is the set of 2-digit CIP families that the committed
deterministic field coder actually PRODUCED in ``normalized/education.parquet``
(41 families), plus one explicit abstention code (``XUN``). The set was
derived from the data (probe 2026-07-09: ``SELECT DISTINCT cip2 FROM
education.parquet WHERE cip2 IS NOT NULL`` -> 41 values, all consistent with
``left(cip_code, 2)`` on every coded row) and every code is verified at import
against the 2-digit family rows of ``reference/cip_codes.csv`` -- the same
authoritative CIP 2020 file the deterministic coder matched against. Family
LABELS are the official ``CIPTitle`` strings from that CSV (never invented).

Families present in the CSV but never produced by the coder (28 Military
Science, 32-37 Basic Skills / Citizenship / Health-Related Knowledge / Interpersonal
Skills / Leisure / Personal Awareness) are deliberately NOT in the label space:
the jury cannot emit a family the committed mapping never assigns.

Mirrors ``career_clean/soc_taxonomy.py``'s contract: SCHEMA_VERSION /
PROMPT_VERSION participate in the vote-cache key (cip_llm.cache_key), and
``output_json_schema()`` is the reason-FIRST structured-output schema that the
llama-server grammar compiler enforces (the model literally cannot emit an
off-taxonomy code).
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CIP_CSV = ROOT / "reference" / "cip_codes.csv"

# Bump SCHEMA_VERSION when the output schema shape changes, PROMPT_VERSION when
# the rubric or evidence rendering changes -- both are hashed into the cache key
# (cip_llm.cache_key), so a bump busts stale votes instead of silently reusing
# them.
SCHEMA_VERSION = 1
PROMPT_VERSION = 1

# The 41 families observed in normalized/education.parquet (see module
# docstring for the probe). cip_tests re-verifies this tuple against the
# parquet, and _load_family_titles() verifies it against the reference CSV.
DATA_CIP2: tuple[str, ...] = (
    "01", "03", "04", "05", "09", "10", "11", "12", "13", "14", "15", "16",
    "19", "21", "22", "23", "24", "25", "26", "27", "29", "30", "31", "38",
    "39", "40", "41", "42", "43", "44", "45", "46", "47", "48", "49", "50",
    "51", "52", "53", "54", "60",
)


def _load_family_titles() -> dict[str, str]:
    """Official family titles for DATA_CIP2 from the CIP 2020 reference CSV
    (2-digit CIPCode rows). Raises if any observed family lacks a title --
    labels are never invented."""
    titles: dict[str, str] = {}
    with _CIP_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("CIPCode") or "").strip()
            if len(code) == 2:
                titles.setdefault(code, (row.get("CIPTitle") or "").strip().rstrip("."))
    missing = [c for c in DATA_CIP2 if not titles.get(c)]
    if missing:
        raise RuntimeError(f"CIP families without a reference title: {missing}")
    return {c: titles[c] for c in DATA_CIP2}


# 2-digit CIP family -> official CIPTitle (built once at import; copied by
# value from the CSV so nothing mutates the reference).
FAMILIES: dict[str, str] = _load_family_titles()

ABSTAIN = "XUN"
_ABSTAIN_LABEL = "Unclassifiable / insufficient information"


def all_codes() -> list[str]:
    """The full enum the juror may emit: sorted families + the abstention."""
    return sorted(FAMILIES) + [ABSTAIN]


def is_valid(code) -> bool:
    return isinstance(code, str) and (code in FAMILIES or code == ABSTAIN)


def label(code: str) -> str:
    if code == ABSTAIN:
        return _ABSTAIN_LABEL
    return FAMILIES[code]


def output_json_schema() -> dict:
    """Strict reason-first output schema. Property ORDER is load-bearing: the
    model must write the rationale BEFORE committing to a code (constrained
    decoding follows the property order), which measurably improves verdicts."""
    return {
        "type": "object",
        "properties": {
            "rationale": {"type": "string", "maxLength": 400},
            "code": {"type": "string", "enum": all_codes()},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["rationale", "code", "confidence"],
        "additionalProperties": False,
    }
