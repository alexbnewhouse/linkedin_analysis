"""Rec 2 - personal-brand company-name trade mining (propose-only).

The audit's single largest uncoded self-employment bucket is bare ownership -
"Owner", "Business Owner", "Founder" (≈275K rows) - titles that carry NO
functional signal at all. For these the *company name* is the only remaining
lever: the self-employed person's "employer" is their own personal-brand entity,
and that name very often names the trade -

    "Smith Photography", "Acme Construction LLC", "Jane Doe Law Office",
    "Johnson Plumbing & Heating", "Riverside Fitness", "Bright Idea Marketing".

This rec reads a trade keyword out of such a name (reusing the shared
se_cluster gazetteer) and proposes its functional cluster. It is name-shape
inference, not a key - so per SELF_EMPLOYED_PLAN §6 it is PROPOSE-ONLY
(low confidence, review-queue grade), never an autonomous merge. Placeholder
"employers" ("Self-employed", "Freelance") carry no brand and are skipped.
"""

from __future__ import annotations

from . import se_cluster as C
from .approach_a_rules import _placeholder_bucket  # noqa: PLC2701
from .common import normalize

_PROPOSE_CONFIDENCE = 0.6


def parse_brand(
    company: str | None, *, company_id: str | None = None
) -> tuple[str | None, str | None, str, float]:
    """Return (cluster, trade_keyword, method, confidence).

    ``company_id`` is accepted for symmetry; the caller (the rollup) only invokes
    this for the no-functional-signal residue, so a real id does not by itself
    veto a brand reading, but a placeholder employer does."""
    norm = normalize(company)
    if not norm:
        return None, None, "empty", 0.0
    if _placeholder_bucket(norm):
        return None, None, "placeholder_not_brand", 0.0
    cl, kw = C.keyword_cluster(company)
    if cl:
        return cl, kw, "company_brand_keyword", _PROPOSE_CONFIDENCE
    return None, None, "no_brand_trade", 0.0
