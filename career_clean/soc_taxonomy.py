"""SOC major-group taxonomy for the LLM-jury role coder.

The label space is the 23 US SOC 2018 major groups (2-digit prefix), imported
from ``transition_network.common.SOC_MAJOR`` -- the single source of truth used
by the transition-network cross-tabs -- plus one explicit abstention code
(``XUN``). Mirrors ``industry/taxonomy.py``'s contract: SCHEMA_VERSION /
PROMPT_VERSION participate in the vote-cache key (soc_llm.cache_key), and
``output_json_schema()`` is the reason-FIRST structured-output schema that the
llama-server grammar compiler enforces (the model literally cannot emit an
off-taxonomy code).
"""

from __future__ import annotations

from transition_network.common import SOC_MAJOR

# Bump SCHEMA_VERSION when the output schema shape changes, PROMPT_VERSION when
# the rubric or evidence rendering changes -- both are hashed into the cache key
# (soc_llm.cache_key), so a bump busts stale votes instead of silently reusing
# them.
SCHEMA_VERSION = 1
# v2: retrieval anchors (nearest O*NET lexicon titles) added to the evidence +
# convention rules in the rubric, after v1 failed calibration at 0.693
# unanimous accuracy with a systematic convention-mismatch confusion structure.
PROMPT_VERSION = 2

# 2-digit SOC major group -> label. Copied by value so a mutation here can never
# leak back into the transition-network module.
MAJOR_GROUPS: dict[str, str] = dict(SOC_MAJOR)

ABSTAIN = "XUN"
_ABSTAIN_LABEL = "Unclassifiable / insufficient information"


def all_codes() -> list[str]:
    """The full enum the juror may emit: sorted major groups + the abstention."""
    return sorted(MAJOR_GROUPS) + [ABSTAIN]


def is_valid(code) -> bool:
    return isinstance(code, str) and (code in MAJOR_GROUPS or code == ABSTAIN)


def label(code: str) -> str:
    if code == ABSTAIN:
        return _ABSTAIN_LABEL
    return MAJOR_GROUPS[code]


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
