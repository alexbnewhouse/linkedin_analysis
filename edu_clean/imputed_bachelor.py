"""Pure predicate pieces for the imputed-bachelor tier (spec P2, strict variant).

A row is imputed to the bachelor's rung only when every one of these holds:

  1. no level from the deterministic parser or the level jury (degree_level_pooled NULL);
  2. a real field is coded (cip2_pooled not NULL and not 53);
  3. the degree box held a FIELD title (degree_method = 'cip_from_degree'): the person
     typed their major where the degree goes, which is the sibling build's actual signal;
  4. neither the degree text nor the field text carries a non-bachelor token (license,
     certificate, minor, study abroad, associate/master abbreviations, ...), and the
     description does not say the program was not completed;
  5. the school string is not a high school, MOOC, community college, or named
     graduate/professional school;
  6. the school resolves to IPEDS as a four-year institution whose Carnegie class is not
     associate-dominant (no default-pass for unresolved schools);
  7. the person holds no pooled bachelor's at any other row, and no graduate-level row
     at the same school.

Pre-review (2026-09-22) measured the spec's original five guards at roughly 30% precision
on 212k rows; this strict form lands about 28k rows at an estimated 0.90. The tier is
propose-only and excludable through degree_level_source = 'imputed_bachelor'.
"""
from __future__ import annotations

import re

SOURCE = "imputed_bachelor"
LEVEL = 4  # bachelor's ordinal (final_hybrid.DEGREE_LEVEL_ORDINAL)

_SCHOOL_EXCLUDE = re.compile(
    r"(high school|highschool|\bhs\b|secondary school|preparatory|prep school|\bprep\b|academy$|"
    r"coursera|udemy|udacity|\bedx\b|linkedin learning|lynda|bootcamp|general assembly|codecademy|"
    r"khan academy|pluralsight|"
    r"community college|junior college|technical college|career center|career college|"
    r"vocational|beauty|cosmetology|barber|"
    r"graduate school|school of law|law school|college of law|school of medicine|medical school|"
    r"school of business|business school|seminary|divinity school|theological|"
    r"school of public health|school of nursing|dental school|school of dentistry|"
    r"pharmacy school|veterinary)",
    re.I)

# Tokens in the DEGREE text that say "not a bachelor's" even when no level word parsed.
_DEGREE_NEGATIVE = re.compile(
    r"(\bnone\b|\bn/?a\b|no degree|non-?degree|licen[cs]|certif|coursework|continuing|"
    r"study abroad|exchange|\bminor\b|residency|in progress|some college|semester|"
    r"\ba\.?a\.?s?\.?\b|associate|\bm\.?s\.?[a-z]{0,3}\b|\bm\.?a\.?\b|\bmba\b|\bm\.?ed\.?\b|\bmsw\b|"
    r"master|\bph\.?d\b|doctor|diploma|\bged\b|audit|credential|fellowship)",
    re.I)

CARNEGIE_EXCLUDE_PREFIXES = ("bacc_associates", "assoc_")

# Post-review 2026-09-22: descriptions that say the program was not completed.
_NOT_COMPLETED = re.compile(
    r"(did not (?:complete|finish|graduate)|didn'?t (?:complete|finish|graduate)|never (?:completed|finished|graduated)|"
    r"transferred (?:out|to)|dropped out|withdrew|incomplete|not completed|no degree|left (?:before|without))",
    re.I)


def school_excluded(school_raw: str | None) -> bool:
    if not school_raw or not school_raw.strip():
        return True
    return bool(_SCHOOL_EXCLUDE.search(school_raw))


def degree_negative(degree_raw: str | None) -> bool:
    if not degree_raw:
        return False
    return bool(_DEGREE_NEGATIVE.search(degree_raw))


def not_completed(description: str | None) -> bool:
    if not description:
        return False
    return bool(_NOT_COMPLETED.search(description))


def carnegie_excluded(carnegie_label: str | None) -> bool:
    if not carnegie_label:
        return False
    return carnegie_label.startswith(CARNEGIE_EXCLUDE_PREFIXES)


def predicate_sql(e: str, lvl: str, other: str) -> str:
    """SQL boolean over education alias ``e``, the IPEDS level view ``lvl`` (columns
    iclevel_label, carnegie_label; inner-join semantics enforced by requiring the label),
    and ``other`` (per-person guard view with columns bachelor_elsewhere, grad_same_school).
    The scalar functions school_excluded / degree_negative / carnegie_excluded must be
    registered on the connection."""
    return f"""(
        {e}.degree_level_pooled IS NULL
        AND {e}.cip2_pooled IS NOT NULL AND {e}.cip2_pooled <> '53'
        AND {e}.degree_method = 'cip_from_degree'
        AND NOT degree_negative({e}.degree_raw)
        AND NOT degree_negative({e}.field_raw)
        AND NOT not_completed({e}.description)
        AND NOT school_excluded({e}.school_raw)
        AND {lvl}.iclevel_label = '4yr+'
        AND NOT carnegie_excluded({lvl}.carnegie_label)
        AND NOT coalesce({other}.bachelor_elsewhere, FALSE)
        AND NOT coalesce({other}.grad_same_school, FALSE)
    )"""
