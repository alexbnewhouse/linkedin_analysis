"""Approach A: deterministic rules + authoritative reference data.

* field      -> match to the US Dept. of Education CIP taxonomy (reference CSV)
* degree     -> parse into a controlled (level, type) taxonomy via rules
* title      -> LinkedIn school slug as canonical key, backfilled by an
                exact-normalized name->slug crosswalk

No fuzzy matching, no ML. Transparent and fully reproducible. Values that do
not match a reference entity map to their normalized self (i.e. left distinct).
"""

from __future__ import annotations

import csv
from collections import defaultdict

from .common import ROOT, Result, normalize, timer, token_key

# ============================ FIELD: CIP =================================
_CIP_CSV = ROOT / "reference" / "cip_codes.csv"


def _load_cip() -> tuple[dict, dict]:
    """Build two indexes from CIP titles to canonical CIP code:
    exact normalized title, and soft token-set key (filler-insensitive).

    4/6-digit instructional codes are primary; the broad 2-digit family titles
    are admitted as *fallback* `cip:NN` targets only for keys no 4/6-digit
    title already claims (LinkedIn's own field dropdown uses verbatim family
    strings such as "BUSINESS, MANAGEMENT, MARKETING, AND RELATED SUPPORT
    SERVICES", so excluding families left those rows raw)."""
    norm_candidates: dict[str, list[str]] = defaultdict(list)
    token_candidates: dict[frozenset, list[str]] = defaultdict(list)
    family_norm: dict[str, str] = {}
    family_tokens: dict[frozenset, str] = {}
    with _CIP_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("CIPCode") or "").strip()
            title = (row.get("CIPTitle") or "").strip().rstrip(".")
            typ = (row.get("Type") or "").strip().lower()
            definition = (row.get("CIPDefinition") or "").lower()
            if not title:
                continue
            # The CIP 36 "Remedial" family contains hobby/non-IPEDS titles such
            # as Art, Music, Reading, and Writing. Those are poor field-of-study
            # canonicals and can otherwise win title collisions by CSV order.
            if typ == "remedial" or "not valid for ipeds reporting" in definition:
                continue
            norm = normalize(title)
            if not norm:
                continue
            if len(code) < 4:  # 2-digit family: collect separately as fallback
                family_norm.setdefault(norm, code)
                family_tokens.setdefault(token_key(title), code)
                continue
            norm_candidates[norm].append(code)
            tk = token_key(title)
            token_candidates[tk].append(code)
    by_norm = {k: v[0] for k, v in norm_candidates.items()}
    by_tokens = {k: v[0] for k, v in token_candidates.items()}
    # Family titles never displace an instructional-code match: a family is
    # admitted only when neither its exact key nor its token key is already
    # claimed (e.g. "SOCIAL SCIENCES" token-matches 45.0101 "Social Sciences,
    # General" and must keep doing so; verbose dropdown families like
    # "BUSINESS, MANAGEMENT, MARKETING, AND RELATED SUPPORT SERVICES" get in).
    for tk, code in family_tokens.items():
        if tk in by_tokens:
            continue
        by_tokens[tk] = code
        norm = next(k for k, c in family_norm.items() if c == code)
        by_norm.setdefault(norm, code)
    return by_norm, by_tokens


def canon_field(vocab: list[tuple]) -> dict:
    by_norm, by_tokens = _load_cip()
    mapping = {}
    for value, *_ in vocab:
        norm = normalize(value)
        code = by_norm.get(norm)
        if code is None:
            code = by_tokens.get(token_key(value))
        # canonical id: CIP code if matched, else the normalized string itself
        mapping[value] = f"cip:{code}" if code else f"raw:{norm}"
    return mapping


# ============================ DEGREE: taxonomy ===========================
# Map an abbreviation/keyword to a canonical (level, type).
_DEGREE_LEVELS = [  # ordered; first hit wins on the level axis
    ("doctor", "doctorate"),
    ("phd", "doctorate"),
    ("ph d", "doctorate"),
    ("doctorate", "doctorate"),
    ("ed d", "doctorate"),
    ("dba", "doctorate"),
    ("juris doctor", "doctorate"),
    (" jd", "doctorate"),
    ("master", "master"),
    ("magister", "master"),
    ("bachelor", "bachelor"),
    ("baccalaureate", "bachelor"),
    ("associate", "associate"),
    ("high school", "high_school"),
    ("ged", "high_school"),
    ("secondary", "high_school"),
    ("diploma", "diploma"),
    ("certificat", "certificate"),  # certificate / certification
    ("foundation", "foundation"),
    # common level words previously left raw; substring order matters:
    # "postgraduate"/"undergraduate" must be checked before bare "graduate"
    ("postgraduate", "postgraduate"),
    ("post graduate", "postgraduate"),  # "post-graduate" normalizes with a space
    ("undergraduate", "undergraduate"),
    ("graduate", "graduate"),
    ("study abroad", "study_abroad"),
]
# Level categories matched on exact tokens (substring matching would be unsafe:
# "minor" is a substring of "minority").
_DEGREE_LEVEL_TOKENS = {
    "minor": "minor",
}
# Standalone abbreviations -> (level, type)
_ABBREV = {
    "bs": ("bachelor", "science"),
    "bsc": ("bachelor", "science"),
    "ba": ("bachelor", "arts"),
    "ab": ("bachelor", "arts"),
    "bba": ("bachelor", "business_admin"),
    "bfa": ("bachelor", "fine_arts"),
    "beng": ("bachelor", "engineering"),
    "be": ("bachelor", "engineering"),
    "bsn": ("bachelor", "nursing"),
    "bsw": ("bachelor", "social_work"),
    "basc": ("bachelor", "applied_science"),
    "bs ": ("bachelor", "science"),
    "ms": ("master", "science"),
    "msc": ("master", "science"),
    "ma": ("master", "arts"),
    "mba": ("master", "business_admin"),
    "med": ("master", "education"),
    "meng": ("master", "engineering"),
    "msn": ("master", "nursing"),
    "msw": ("master", "social_work"),
    "mph": ("master", "public_health"),
    "mfa": ("master", "fine_arts"),
    "llm": ("master", "law"),
    "phd": ("doctorate", "philosophy"),
    "edd": ("doctorate", "education"),
    "jd": ("doctorate", "law"),
    "md": ("doctorate", "medicine"),
    "dds": ("doctorate", "dental"),
    "aa": ("associate", "arts"),
    "as": ("associate", "science"),
    "aas": ("associate", "applied_science"),
}
# Subject/type keywords (checked within the full string)
_TYPE_KEYWORDS = [
    ("business administration", "business_admin"),
    ("fine arts", "fine_arts"),
    ("applied science", "applied_science"),
    ("public health", "public_health"),
    ("social work", "social_work"),
    ("of science", "science"),
    ("of arts", "arts"),
    ("of engineering", "engineering"),
    ("of education", "education"),
    ("of nursing", "nursing"),
    ("of laws", "law"),
    ("of law", "law"),
    ("of philosophy", "philosophy"),
    ("of medicine", "medicine"),
]


def _parse_degree(value: str) -> str:
    norm = normalize(value)  # e.g. "bachelor of science bs"
    toks = norm.split()
    # 1) pure abbreviation (one or two tokens)
    if len(toks) <= 2:
        joined = "".join(toks)
        if joined in _ABBREV:
            lvl, typ = _ABBREV[joined]
            return f"{lvl}:{typ}"
        for t in toks:
            if t in _ABBREV:
                lvl, typ = _ABBREV[t]
                return f"{lvl}:{typ}"
    # 2) level by keyword (then by exact token for unsafe-substring categories)
    level = None
    for kw, lvl in _DEGREE_LEVELS:
        if kw.strip() in norm:
            level = lvl
            break
    if level is None:
        for t in toks:
            if t in _DEGREE_LEVEL_TOKENS:
                level = _DEGREE_LEVEL_TOKENS[t]
                break
    # 3) type by keyword, else by embedded abbreviation token
    typ = None
    for kw, t in _TYPE_KEYWORDS:
        if kw in norm:
            typ = t
            break
    if typ is None:
        for t in toks:
            if t in _ABBREV and _ABBREV[t][0] == (level or _ABBREV[t][0]):
                typ = _ABBREV[t][1]
                break
    if level is None and typ is not None:
        # abbreviation implied the level
        for t in toks:
            if t in _ABBREV:
                level = _ABBREV[t][0]
                break
    if level is None:
        return f"raw:{norm}"
    return f"{level}:{typ or 'generic'}"


def canon_degree(vocab: list[tuple]) -> dict:
    return {value: _parse_degree(value) for value, *_ in vocab}


# ============================ TITLE: slug ================================
def canon_title(vocab: list[tuple]) -> dict:
    # crosswalk: normalized name -> slug (from values that already carry a slug)
    crosswalk: dict[str, str] = {}
    for value, _freq, slug in vocab:
        if slug:
            crosswalk.setdefault(normalize(value), slug)
    mapping = {}
    for value, _freq, slug in vocab:
        if slug:
            mapping[value] = f"slug:{slug}"
        else:
            recovered = crosswalk.get(normalize(value))
            mapping[value] = (
                f"slug:{recovered}" if recovered else f"name:{normalize(value)}"
            )
    return mapping


# ============================ entry point ================================
def run(field_name: str, vocab: list[tuple]) -> Result:
    with timer() as t:
        if field_name == "field":
            mapping = canon_field(vocab)
        elif field_name == "degree":
            mapping = canon_degree(vocab)
        elif field_name == "title":
            mapping = canon_title(vocab)
        else:
            raise ValueError(field_name)
    # reference-match coverage: share of ROWS mapped to a known reference id
    ref_prefix = {
        "field": "cip:",
        "degree": (
            "bachelor:",
            "master:",
            "associate:",
            "doctorate:",
            "high_school:",
            "diploma:",
            "certificate:",
            "foundation:",
            "undergraduate:",
            "graduate:",
            "postgraduate:",
            "minor:",
            "study_abroad:",
        ),
        "title": "slug:",
    }[field_name]
    total = sum(f for _v, f, *_ in vocab)
    matched = sum(
        f
        for v, f, *_ in vocab
        if mapping[v].startswith(
            tuple(ref_prefix) if isinstance(ref_prefix, tuple) else ref_prefix
        )
    )
    return Result(
        name="A_rules",
        field=field_name,
        mapping=mapping,
        runtime_s=t.elapsed,
        extra={"reference_match_row_pct": round(100 * matched / total, 1)},
    )
