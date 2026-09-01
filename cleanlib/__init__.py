"""Shared cleaning primitives (audit F4, extracted 2026-09-01).

The canonical text normalizer + token key live here; ``career_clean.common``
re-imports them (verbatim move, zero behavior change — its calibrated mappings
depend on exact normalizer semantics). ``edu_clean`` keeps its own historical
normalizer for the same reason; NEW modules (``cert_clean`` onward) build on
cleanlib. Migrate more shared machinery (Result, vocab export, jury driver,
host pool) opportunistically — never by rewriting a calibrated mapping.
"""

from cleanlib.text import SOFT_STOP, normalize, token_key

__all__ = ["SOFT_STOP", "normalize", "token_key"]
