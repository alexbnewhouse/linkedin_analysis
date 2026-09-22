"""Co-major / minor / concentration splitter over the raw field string (spec P3).

Splitting LOGIC is ported from the sibling build; resolution of each component goes
through the repo's own field->CIP lookup (final_hybrid._field_cip_lookup), so no second
taxonomy exists. Precision-first, per the 2026-09-22 pre-review:

  1. a value that the field canonicalizer already resolves to a CIP (method cip_* or
     typo_to_cip in normalized/mappings/edu_field.parquet), or whose whole string the
     lookup resolves, is ONE field ("single"); CIP titles with commas and "and" never split;
  2. otherwise split on explicit markers (minor / major / concentration / parentheses)
     and separators; every kept component must itself resolve; majors are deduped on
     their 2-digit family (concentrations and minors are kept regardless);
  3. "split" needs at least two resolved components including at least one major.

Which major is PRIMARY is decided per ROW at apply time (edu_clean/apply_comajors.py):
the major whose family equals the row's cip2_pooled; the other major is the secondary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from cleanlib.text import normalize as _norm
from edu_clean import final_hybrid as FH

_MINOR_MARK = re.compile(r"\b(?:with\s+(?:a\s+)?)?minors?\b\s*(?:\bin\b|\bof\b|:|;|-|=)?\s*", re.I)
_MAJOR_MARK = re.compile(
    r"\b(?:with\s+(?:a\s+)?)?(?:double|dual|triple|second|first|primary)?\s*majors?(?:ing)?\b\s*(?:\bin\b|\bof\b|:|;|-|=)?\s*",
    re.I)
_CONC_MARK = re.compile(
    r"\b(?:with\s+(?:a\s+)?)?(?:concentrations?|emphasis|specializations?|specialisations?|"
    r"focus(?:ed|ing)?|tracks?|options?|specialty|areas? of study|studies in)\b\s*"
    r"(?:\bin\b|\bon\b|\bof\b|:|;|-|=)?\s*", re.I)
_PAREN = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")
_SEP = re.compile(r"\s*(?:[;/|,]|\band\b|&|\+)\s*", re.I)
_MARKER_ANY = re.compile(r"\bminors?\b|\bmajors?\b|concentration|emphasis|specializ|specialis|"
                         r"\btracks?\b|\bfocus|[\(\[]", re.I)

DETERMINISTIC_METHODS = ("cip_exact", "cip_alias", "cip_override", "typo_to_cip")

# Post-review 2026-09-22: compound SINGLE-program names that the CIP lookup does not
# resolve whole and whose halves both resolve. Matched on the normalized string
# (cleanlib.text.normalize: lowercase, '&' -> 'and', punctuation -> space). Extend with
# evidence; each entry is a program name, not a pair of majors.
COMPOUND_PROGRAMS = frozenset({
    "computer science and engineering", "computer science engineering",
    "electrical engineering and computer science", "electrical and computer engineering",
    "computer engineering and computer science", "statistics and data science",
    "philosophy politics and economics", "philosophy politics economics",
    "criminology law and society", "criminology law society", "law and society",
    "criminology and criminal justice", "criminal justice and criminology",
    "economics and business administration", "applied economics and management",
    "international business and economics", "economics and business management",
    "planning public policy and management", "biostatistics and data science",
    "politics philosophy and economics",
    "public policy and management", "economics and management", "economics and business",
    "business and economics", "politics and government", "government and politics",
    "education and human development", "information science and technology",
    "information systems and technology", "business and technology", "business and information technology",
    "mechanical and aerospace engineering", "civil and environmental engineering",
    "chemical and biological engineering", "chemical and biomolecular engineering",
    "industrial and systems engineering", "materials science and engineering",
    "cell and molecular biology", "molecular and cell biology", "molecular and cellular biology",
    "ecology and evolutionary biology", "biochemistry and molecular biology",
    "supply chain and operations management", "operations and supply chain management",
    "sport and recreation management", "media and communication", "media and communications",
    "communication and media", "journalism and mass communication", "journalism and media studies",
    "radio tv film", "radio television film", "radio television and film", "film and television",
    "film and media studies", "theatre and dance", "theater and dance", "music and theatre",
    "human development and psychology", "psychology and human development",
    "business industrial management", "history and philosophy of science",
    "science technology and society", "society and environment", "environment and society",
    "peace and conflict studies", "war and peace studies", "international and global studies",
    "gender and sexuality studies", "gender and women s studies", "women s and gender studies",
    "race and ethnic studies", "ethnic and racial studies", "religion and culture",
    "language and literature", "linguistics and languages", "literature and writing",
    "rhetoric and writing", "writing and rhetoric", "english and creative writing",
    "creative writing and literature",
})


@dataclass
class Component:
    text: str
    role: str  # major | minor | concentration
    cip: str | None


@dataclass
class Split:
    status: str  # single | split | unresolved | empty
    components: list[Component] = field(default_factory=list)
    marker_class: str = "plain"  # plain | marker


def marker_class(field_raw: str | None) -> str:
    return "marker" if field_raw and _MARKER_ANY.search(field_raw) else "plain"


def _resolve(text: str) -> str | None:
    t = text.strip(" .,;:-/")
    return FH._field_cip_lookup(t) if t else None


def _one_program(text: str) -> bool:
    t = text.strip(" .,;:-/")
    return bool(t) and (bool(_resolve(t)) or _norm(t) in COMPOUND_PROGRAMS)


def _pieces(text: str) -> list[str]:
    return [p for p in (x.strip(" .,;:-") for x in _SEP.split(text)) if p]


def split_field(field_raw: str | None, method: str | None = None) -> Split:
    """``method`` is the value's edu_field canonicalization method, when known."""
    if not field_raw or not field_raw.strip():
        return Split("empty")
    mc = marker_class(field_raw)
    if method in DETERMINISTIC_METHODS:
        return Split("single", [Component(field_raw.strip(), "major", None)], mc)
    whole = _resolve(field_raw)
    if whole:
        return Split("single", [Component(field_raw.strip(), "major", whole)], mc)
    if _norm(field_raw) in COMPOUND_PROGRAMS:
        return Split("single", [Component(field_raw.strip(), "major", None)], mc)

    text = field_raw
    minors: list[str] = []
    concs: list[str] = []
    # a head that is one program followed by a parenthetical or a marker never splits
    # ("Electrical Engineering and Computer Science (EECS)", "Computer Science and
    # Engineering, Minor in Mathematics" keeps the head whole and, for a minor, the minor)
    head_m = re.search(r"[\(\[]|,\s*(?:minors?|concentrations?|emphasis|focus|tracks?|specializations?)\b", text, re.I)
    # ... but only when nothing substantive follows the parenthetical / marker phrase
    # ("Economics (Business) & Psychology" still names a second major after the track)
    tail_ok = True
    if head_m and head_m.group(0).startswith(("(", "[")):
        close = _PAREN.search(text, head_m.start())
        after = text[close.end():] if close else ""
        tail_ok = not after.strip(" .,;:-/") or bool(_MINOR_MARK.match(after.strip(" .,;:-/"))) \
            or bool(_CONC_MARK.match(after.strip(" .,;:-/")))
    if head_m and tail_ok and _one_program(text[:head_m.start()]):
        head = text[:head_m.start()].strip(" .,;:-")
        rest = text[head_m.start():]
        comps = [Component(head, "major", _resolve(head))]
        mm = _MINOR_MARK.search(rest)
        cm = _CONC_MARK.search(rest)
        if mm:
            comps += [Component(t, "minor", _resolve(t)) for t in _pieces(_MINOR_MARK.sub(" ; ", rest[mm.end():]))]
        elif cm:
            comps += [Component(t, "concentration", _resolve(t)) for t in _pieces(_CONC_MARK.sub(" ; ", rest[cm.end():]))]
        else:  # bare parenthetical after a whole program: a track
            inner = _PAREN.search(rest)
            if inner and inner.group(1).strip():
                comps.append(Component(inner.group(1).strip(), "concentration", _resolve(inner.group(1))))
        # the head is one program (it may be stoplisted and carry no CIP); a resolved
        # minor or concentration after it is still real information
        extras = [c for c in comps[1:] if c.cip]
        if extras:
            return Split("split", [comps[0]] + extras, mc)
        return Split("single", [comps[0]], mc)

    def paren(m: re.Match) -> str:
        inner = m.group(1).strip()
        if not inner:
            return " "
        if _MINOR_MARK.search(inner):
            rest = _MINOR_MARK.sub(" ", inner).strip(" ,;:-")
            if rest:
                minors.append(rest)
                return " ; "
            return " ~MINOR~ "  # "(minor)" after a component: mark, resolve below
        if _CONC_MARK.search(inner):
            rest = _CONC_MARK.sub(" ", inner).strip(" ,;:-")
            if rest:
                concs.append(rest)
            return " ; "
        # a bare parenthetical ("Chemistry (Biochemistry)") is a track, never a second major
        concs.append(inner)
        return " ; "

    text = _PAREN.sub(paren, text)
    # "X (minor)" -> X is a minor
    if "~MINOR~" in text:
        parts = [p for p in re.split(r"~MINOR~", text)]
        head = parts[0]
        segs = _pieces(head)
        if segs:
            minors.append(segs[-1])
            head = " ; ".join(segs[:-1])
        text = head + " ; " + " ; ".join(parts[1:])
    m = _MINOR_MARK.search(text)
    if m:
        head, rest = text[:m.start()], text[m.end():]
        if rest.strip(" ,;:-/"):
            minors.extend(_pieces(_MINOR_MARK.sub(" ; ", rest)))
        else:  # trailing "<x> minor": the whole head may itself be one program ("..., Minor")
            if _resolve(head) or _norm(head) in COMPOUND_PROGRAMS:
                return Split("single", [Component(field_raw.strip(), "major", _resolve(head))], mc)
            parts = _pieces(head)  # else the last segment of the head is the minor
            if parts:
                minors.append(parts[-1])
                head = " ; ".join(parts[:-1])
        text = head
    m = _CONC_MARK.search(text)
    if m:
        after = text[m.end():]
        if after.strip(" ,;:-/"):
            concs.extend(_pieces(after))
            text = text[:m.start()]
        else:  # trailing "<x> concentration": the last segment of the head is the concentration
            parts = _pieces(text[:m.start()])
            if parts:
                concs.append(parts[-1])
                text = " ; ".join(parts[:-1])
            else:
                text = ""
    text = _MAJOR_MARK.sub(" ; ", text)
    majors = _pieces(text)

    comps = [Component(t, "major", _resolve(t)) for t in majors]
    comps += [Component(t, "concentration", _resolve(t)) for t in concs]
    comps += [Component(t, "minor", _resolve(t)) for t in minors]
    kept: list[Component] = []
    seen_major_families: set[str] = set()
    for c in comps:
        if not c.cip:
            continue
        if c.role == "major":
            fam = c.cip[:2]
            if fam in seen_major_families:
                continue
            seen_major_families.add(fam)
        kept.append(c)
    if len(kept) < 2 or not any(c.role == "major" for c in kept):
        return Split("unresolved", comps, mc)
    return Split("split", kept, mc)


def majors(s: Split) -> list[str]:
    return [c.cip for c in s.components if c.role == "major" and c.cip]


def minor(s: Split) -> str | None:
    return next((c.cip for c in s.components if c.role == "minor" and c.cip), None)


def concentration(s: Split) -> str | None:
    return next((c.cip for c in s.components if c.role == "concentration" and c.cip), None)


def primary_secondary(s: Split, cip2_pooled: str | None) -> tuple[str | None, str | None, str]:
    """Row-level choice: (primary, secondary, source) where source is 'split' when a major
    matches the row's pooled family, 'no_primary' when the row has no pooled family, and
    'conflict' when the pooled family matches no major component."""
    ms = majors(s)
    if s.status != "split" or not ms:
        return None, None, "none"
    if cip2_pooled is None:
        return None, None, "no_primary"
    match = [c for c in ms if c[:2] == cip2_pooled]
    if not match:
        return None, None, "conflict"
    prim = match[0]
    others = [c for c in ms if c != prim]
    return prim, (others[0] if others else None), "split"
