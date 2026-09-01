"""Rec 1 - qualifier-aware functional recovery for self-employment titles.

The audit shows the largest UNCODED self-employment buckets are owner (45.9%),
founder (22.2%), "other" freelance/contractor (25.2%), and consultant (6.7%).
The deterministic O*NET backbone leaves them uncoded for two different reasons:

  * the head noun is a generic STATUS word it (correctly) blocks - "Owner",
    "Founder", "Consultant", "Independent Contractor"; and
  * even where a real occupation noun survives, it is often O*NET-AMBIGUOUS -
    "Designer", "Editor", "Sales Representative" map to several SOCs.

For *clustering* we don't need the exact SOC, we need the functional group. So
this rec strips the generic ownership/status/exec shell off the title, leaving
the QUALIFIER, and clusters the qualifier two ways, precision-first:

  1. the qualifier hits O*NET unambiguously  -> keep the SOC, cluster = its
     major group   ("graphic designer" -> 27-1024 -> 27);
  2. else the qualifier hits the shared industry gazetteer (se_cluster) -> the
     coarse cluster, tolerating O*NET ambiguity ("designer" -> 27, "it" -> 15,
     "restaurant" -> 35).

A title with NO self-employment shell marker is not this rec's population and
returns nothing (precision guard); a title that is ALL shell ("Owner",
"Founder & CEO", "Owner/Operator") has no functional signal and returns nothing
honestly - the company name (Rec 2) is the only remaining lever for those.
"""

from __future__ import annotations

from . import occupation as O
from . import se_cluster as C
from .approach_a_rules import _LEVEL_TOKENS, _OWNER_FALSE_POSITIVE
from .common import normalize

# Presence of any of these marks the row as the self-employment population that
# this rec is allowed to act on (the precision guard).
_SHELL_MARKERS = {
    "owner", "coowner", "proprietor", "founder", "cofounder", "consultant",
    "freelance", "freelancer", "independent", "contractor", "selfemployed",
    "entrepreneur",
}
# Multiword markers checked as substrings of the normalized title.
_SHELL_MARKER_PHRASES = ("co founder", "co owner", "self employed", "sole proprietor")

# Generic shell tokens removed to expose the qualifier. Ownership/founder/exec
# scaffolding + business-size/legal words + the consulting/freelance status.
_STRIP_TOKENS = {
    # ownership / founder / exec scaffolding
    "owner", "coowner", "co", "proprietor", "founder", "cofounder", "founding",
    "ceo", "cfo", "coo", "cto", "cmo", "cio", "president", "vp", "vice",
    "operator", "principal", "managing", "partner", "chairman", "chairwoman",
    # self-employment status
    "freelance", "freelancer", "independent", "contractor", "self", "employed",
    "selfemployed", "entrepreneur", "sole", "consultant", "consulting",
    "consultancy",
    # business-size / legal / generic org words
    "business", "company", "small", "llc", "inc", "incorporated", "ltd",
    "corporation", "corp", "group", "studio", "studios", "services", "service",
    "solutions", "enterprises", "enterprise", "agency",
    # soft fillers
    "and", "of", "the", "a", "for", "at", "to", "amp",
}
# Level words are scaffolding too (Senior Consultant -> drop senior).
_STRIP_TOKENS |= set(_LEVEL_TOKENS)


def _has_shell_marker(norm: str) -> bool:
    toks = set(norm.split())
    if toks & _SHELL_MARKERS:
        return True
    return any(p in norm for p in _SHELL_MARKER_PHRASES)


def strip_status_shell(title: str | None) -> str:
    """Remove the generic ownership/status/exec scaffolding, returning the
    qualifier (possibly empty)."""
    norm = normalize(title)
    if not norm:
        return ""
    kept = [t for t in norm.split() if t not in _STRIP_TOKENS]
    return " ".join(kept)


def recover_cluster(
    title: str | None, by_norm: dict, by_tokens: dict
) -> tuple[str | None, str | None, str, float]:
    """Return (cluster, soc_or_None, method, confidence).

    cluster is a 2-digit major group, or None when the title is not the
    self-employment population / carries no functional signal."""
    norm = normalize(title)
    if not norm or norm in _OWNER_FALSE_POSITIVE:
        return None, None, "not_se_population", 0.0
    if not _has_shell_marker(norm):
        return None, None, "not_se_population", 0.0

    qualifier = strip_status_shell(title)
    if not qualifier:
        return None, None, "bare_status", 0.0

    # 1. qualifier hits O*NET unambiguously -> keep SOC, cluster = major group.
    # Major group 55 (Military) is a false hit here: a self-employed person's
    # stripped qualifier coding to a military rank ("management"/"general" ->
    # 55-1019) is noise, never a real signal -> fall through to the gazetteer.
    code, _m = O.match(qualifier, by_norm, by_tokens)
    cl = C.major_group(code)
    if cl and cl != "55":
        return cl, code, "qualifier_onet", 0.9

    # 2. qualifier hits the coarse industry gazetteer (ambiguity-tolerant)
    kw_cl, _kw = C.keyword_cluster(qualifier)
    if kw_cl:
        return kw_cl, None, "qualifier_keyword", 0.7

    return None, None, "qualifier_unmatched", 0.0
