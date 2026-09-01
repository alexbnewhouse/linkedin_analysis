"""Occupation backstop: map a job title to an O*NET-SOC occupation code.

This is the title analogue of education's CIP field-of-study reference. It is a
SEPARATE axis from the seniority/role canonical produced by approach_a /
final_hybrid: the SOC code groups *semantic* job families ("Software Engineer" ==
"Software Developer" == 15-1252) that the literal role parser cannot, while the
seniority level stays on its own axis. So a cleaned title carries three things:
seniority_level, role_canonical (literal), and occupation_code (this module).

Reference: O*NET-SOC 29.1 (reference/onet_alternate_titles.txt, ~55k real-world
title strings -> SOC code; reference/onet_occupation_data.txt, the 1k occupation
titles + descriptions). The alt-title lexicon is exactly the asset that gave CIP
its precision-1.0 exact-match backbone in education.

Matching is deterministic and precision-first:
  1. exact normalized title in the lexicon
  2. order-independent token-set match
  3. de-leveled fallback (strip seniority/abbrev via approach_a.parse_title) for
     1 and 2, so "Senior Software Engineer" finds "Software Engineer"
Titles whose lexicon entry is AMBIGUOUS (maps to >1 SOC) are left uncoded -- the
generic cross-cutting titles ("Manager", "Project Manager", "Consultant") that
genuinely span occupations. The embedding-anchored variant (propose-only, for the
review queue) lives in approach_c_embed.run_anchored_occupation.
"""

from __future__ import annotations

import csv
import re

from . import approach_a_rules as A
from .common import ROOT, Result, normalize, timer, token_key

_ALT = ROOT / "reference" / "onet_alternate_titles.txt"
_OCC = ROOT / "reference" / "onet_occupation_data.txt"
_PARENS = re.compile(r"\(([^)]*)\)")
_GENERIC_STATUS_TITLES = {
    "business owner",
    "co founder",
    "cofounder",
    "consultant",
    "contractor",
    "founder",
    "freelance consultant",
    "independent consultant",
    "owner",
    "proprietor",
    "self employed",
    "selfemployed",
    "sole proprietor",
}


def _soc(code: str) -> str:
    """O*NET-SOC '15-1252.00' -> SOC family '15-1252'."""
    return code.split(".")[0]


def _singular_last_word(title: str) -> str | None:
    words = title.strip().split()
    if not words:
        return None
    last = words[-1]
    lower = last.lower()
    if len(last) <= 3 or lower.endswith("ss") or not lower.endswith("s"):
        return None
    words[-1] = last[:-1]
    singular = " ".join(words)
    return singular if singular != title else None


def _title_variants(title: str) -> list[str]:
    """Reference-title variants that preserve precision.

    O*NET alternates often encode phrases as "Chief Technology Officer (CTO)"
    or "CEO (Chief Executive Officer)"; index both the outside text and the
    parenthetical content. Singularizing only the final word recovers common
    profile labels such as "Registered Nurse" from "Registered Nurses".
    """
    out: list[str] = []

    def add_variant(v: str | None) -> None:
        if not v:
            return
        v = v.strip()
        if v and v.lower() != "n/a" and v not in out:
            out.append(v)
        singular = _singular_last_word(v)
        if singular and singular not in out:
            out.append(singular)

    add_variant(title)
    add_variant(_PARENS.sub("", title))
    for inner in _PARENS.findall(title):
        add_variant(inner)
    return out


def load_onet() -> tuple[dict[str, str], dict[frozenset, str], dict[str, str]]:
    """Build (by_norm, by_tokens, code_to_title). Ambiguous keys (>1 SOC) are
    dropped to keep exact matching at precision ~1.0."""
    code_to_title: dict[str, str] = {}
    with _OCC.open(encoding="utf-8", newline="") as fh:
        r = csv.reader(fh, delimiter="\t")
        next(r, None)
        for row in r:
            if len(row) < 2:
                continue
            code_to_title.setdefault(_soc(row[0]), row[1])

    norm_codes: dict[str, set[str]] = {}
    tok_codes: dict[frozenset, set[str]] = {}

    def add(title: str, code: str) -> None:
        n = normalize(title)
        if n:
            norm_codes.setdefault(n, set()).add(code)
            tok_codes.setdefault(token_key(title), set()).add(code)

    # occupation titles themselves
    for code, title in code_to_title.items():
        for variant in _title_variants(title):
            add(variant, code)
    # the ~55k alternate / reported titles
    with _ALT.open(encoding="utf-8", newline="") as fh:
        r = csv.reader(fh, delimiter="\t")
        next(r, None)
        for row in r:
            if len(row) < 2:
                continue
            for variant in _title_variants(row[1]):
                add(variant, _soc(row[0]))
            if len(row) >= 3 and row[2] and row[2].lower() != "n/a":
                for variant in _title_variants(row[2]):
                    add(variant, _soc(row[0]))

    by_norm = {k: next(iter(v)) for k, v in norm_codes.items() if len(v) == 1}
    by_tokens = {k: next(iter(v)) for k, v in tok_codes.items() if len(v) == 1}
    return by_norm, by_tokens, code_to_title


def _deleveled(value: str) -> str:
    """Role text with seniority/abbreviation handled, via the title parser."""
    _lvl, base = A.parse_title(value)
    return base


def _generic_status_title(value: str | None) -> bool:
    return normalize(value) in _GENERIC_STATUS_TITLES


def _match_surface(value: str, by_norm: dict, by_tokens: dict) -> tuple[str | None, str]:
    n = normalize(value)
    if _generic_status_title(n):
        return None, "blocked_generic_status"
    if n in by_norm:
        return by_norm[n], "onet_exact"
    tk = token_key(value)
    if tk in by_tokens:
        return by_tokens[tk], "onet_token"
    base = _deleveled(value)
    if base:
        if _generic_status_title(base):
            return None, "blocked_generic_status"
        if base in by_norm:
            return by_norm[base], "onet_deleveled"
        btk = token_key(base)
        if btk in by_tokens:
            return by_tokens[btk], "onet_deleveled_token"
    return None, "unmatched"


def match(value: str, by_norm: dict, by_tokens: dict) -> tuple[str | None, str]:
    if A.title_status_bucket(value):
        return None, "blocked_status"

    code, method = _match_surface(value, by_norm, by_tokens)
    if code or method.startswith("blocked"):
        return code, method

    stripped = A.strip_employment_status_prefix(value)
    if stripped and stripped != normalize(value):
        code, stripped_method = _match_surface(stripped, by_norm, by_tokens)
        if code:
            return code, f"{stripped_method}_status_stripped"
        if stripped_method.startswith("blocked"):
            return None, stripped_method

    return None, "unmatched"


def canon_occupation(vocab: list[tuple]) -> tuple[dict, dict]:
    by_norm, by_tokens, _ = load_onet()
    mapping: dict[str, str] = {}
    method: dict[str, str] = {}
    for value, *_ in vocab:
        code, m = match(value, by_norm, by_tokens)
        mapping[value] = f"soc:{code}" if code else f"raw:{normalize(value)}"
        method[value] = m
    return mapping, method


def run(vocab: list[tuple]) -> Result:
    with timer() as t:
        mapping, method = canon_occupation(vocab)
    total = sum(f for _v, f, *_ in vocab)
    matched = sum(f for v, f, *_ in vocab if mapping[v].startswith("soc:"))
    return Result(
        name="A_onet",
        field="occupation",
        mapping=mapping,
        runtime_s=t.elapsed,
        extra={"reference_match_row_pct": round(100 * matched / total, 1)},
    )
