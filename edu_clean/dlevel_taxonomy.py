"""Degree-LEVEL taxonomy for the LLM-jury level coder. Label space = the degree
level ordinals the deterministic resolver produces (final_hybrid.DEGREE_LEVEL_ORDINAL)
plus an explicit abstention (XUN) for strings that name no degree.

Mirrors edu_clean/cip_taxonomy.py's contract (SCHEMA_VERSION / PROMPT_VERSION in
the cache key; reason-first output_json_schema enforced by the llama-server grammar).
"""
from __future__ import annotations

SCHEMA_VERSION = 1
PROMPT_VERSION = 1

# ordinal code -> human label. Aligned to final_hybrid.DEGREE_LEVEL_ORDINAL so a
# jury code maps straight onto degree_level. Level 5 (generic postgraduate) is a
# real resolver output but rare; kept so the jury can use it instead of guessing
# master-vs-doctorate.
LEVELS: dict[str, str] = {
    "1": "High school diploma / secondary",
    "2": "Certificate / diploma / vocational (non-degree postsecondary)",
    "3": "Associate degree (2-year)",
    "4": "Bachelor's degree (undergraduate, 4-year)",
    "5": "Graduate/postgraduate, level unclear between master's and doctorate",
    "6": "Master's degree (incl. MBA, MFA, MSW, MA, MS)",
    "7": "Doctorate or professional doctorate (PhD, JD, MD, EdD, DBA)",
}

ABSTAIN = "XUN"
_ABSTAIN_LABEL = "No degree named / cannot determine level from the evidence"


def all_codes() -> list[str]:
    return sorted(LEVELS) + [ABSTAIN]


def is_valid(code) -> bool:
    return isinstance(code, str) and (code in LEVELS or code == ABSTAIN)


def label(code: str) -> str:
    return _ABSTAIN_LABEL if code == ABSTAIN else LEVELS[code]


def output_json_schema() -> dict:
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
