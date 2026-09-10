"""Canonical matching-key normalizer.

Moved verbatim from ``career_clean/common.py`` (audit F4). Any change here
changes join keys for every calibrated mapping built on it — treat as frozen;
extend via wrappers, not edits.
"""

from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")
# Soft fillers that rarely change the identity of a company / job title.
SOFT_STOP = {"the", "a", "an", "of", "and", "or", "for", "to", "at", "in"}


def _ascii_fold(text: str) -> str:
    """NFKC + accent fold while preserving non-Latin fallback behavior."""
    s = unicodedata.normalize("NFKC", text)
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _protect_domain_tokens(text: str) -> str:
    """Protect meaningful punctuation before the generic punctuation pass."""
    s = re.sub(r"(?<![a-z0-9])c\s*\+\s*\+(?![a-z0-9])", " cplusplus ", text)
    s = re.sub(r"(?<![a-z0-9])c\s*#(?![a-z0-9])", " csharp ", s)
    s = re.sub(r"(?<![a-z0-9])f\s*#(?![a-z0-9])", " fsharp ", s)
    s = re.sub(r"(?<![a-z0-9])r\s*&\s*d(?![a-z0-9])", " research and development ", s)
    return s


def normalize(text: str | None) -> str:
    """Aggressive-but-safe normalization for matching keys.

    NFKC fold, lowercase, unify '&'->'and', turn separators into spaces, drop
    remaining punctuation, collapse whitespace. (Drops non-ASCII; use
    ``safe_norm`` in the module's final_hybrid for raw canonical ids so
    multilingual labels don't collapse to empty.)
    """
    if text is None:
        return ""
    s = _ascii_fold(text)
    s = s.replace("’", "'").replace("‘", "'")
    s = s.lower()
    s = _protect_domain_tokens(s)
    s = s.replace("&", " and ")
    s = s.replace("/", " ").replace("-", " ").replace(".", " ")
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def token_key(text: str | None, drop_soft: bool = True) -> frozenset[str]:
    """Order-independent token set, optionally dropping soft fillers."""
    toks = normalize(text).split()
    if drop_soft:
        kept = [t for t in toks if t not in SOFT_STOP]
        toks = kept or toks
    return frozenset(toks)
