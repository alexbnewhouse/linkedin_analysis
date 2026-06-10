"""Final education-value canonicalizer.

This module keeps the older A/B/C experiments intact and implements the
production-leaning hybrid:

* degree: deterministic taxonomy with extra abbreviation cleanup
* title: LinkedIn school slug, guarded name->slug crosswalk, typo tail
* field: CIP exact/token, curated aliases, typo tail

Embeddings are deliberately not part of the canonical default. The nearest
neighbor variants live in nearest_neighbor.py and are evaluated separately.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field as dc_field

from . import approach_a_rules as A
from . import approach_b_fuzzy as B
from .common import Result, normalize, timer, token_key

_WS = re.compile(r"\s+")
_ALNUM = re.compile(r"[^a-z0-9]+")
_SCHOOL_SLUG_RE = re.compile(r"linkedin\.com/school/([^/?#]+)")

NULLISH_NORMS = {
    "",
    "n a",
    "na",
    "none",
    "null",
    "unknown",
    "not applicable",
    "school name",
    "degree",
    "field",
    # bare filler / class-standing / honors strings observed at high frequency
    # in the field column (they carry no field-of-study signal)
    "general",
    "freshman",
    "sophomore",
    "junior",
    "senior",
    "graduated",
    "cum laude",
    "magna cum laude",
    "summa cum laude",
    "honors",
    "academic",
}

# Junk patterns on the *normalized* key: pure numerics/GPA strings ("4.0" ->
# "4 0", "12", "3.8 gpa", "12th", "9-12") and bare single ASCII letters ("A").
_JUNK_NORM = re.compile(
    r"^(?:[0-9][0-9. ]*(?:gpa)?|gpa[0-9. ]*|[0-9]+ ?(?:st|nd|rd|th)|[a-z0-9])$"
)


def is_nullish(norm: str) -> bool:
    """True when a normalized value carries no usable signal (empty, a known
    placeholder, or numeric/GPA/single-letter junk)."""
    return not norm or norm in NULLISH_NORMS or bool(_JUNK_NORM.match(norm))

# Seeded, high-confidence aliases. These are intentionally conservative:
# aliases that imply policy choices around very broad labels stay out.
# 2026-06 curation sitting (audit Finding 3c): one pass over the top ~200
# distinct raw/typo values by row frequency. Only unambiguous mappings were
# admitted; genuinely ambiguous labels are listed in the trailing comment.
FIELD_CIP_ALIASES = {
    "communications": "09.0100",
    "communication": "09.0100",
    "english language literature letters": "23.01",
    "english language and literature letters": "23.01",
    "biology biological sciences": "26.01",
    "biology biological sciences general": "26.01",
    "business administration": "52.02",
    "business management": "52.02",
    "business administration management": "52.02",
    "political science": "45.10",
    "electrical engineering": "14.1001",
    "criminal justice": "43.01",
    "liberal arts": "24.0101",
    "human resources management": "52.10",
    "human resource management": "52.10",
    "human resources": "52.10",
    "public relations": "09.09",
    "art history": "50.0703",
    "communication studies": "09.01",
    "international relations": "45.0901",
    # --- business / management ---
    "business": "52",            # family-level: the right granularity for the bare label
    "management": "52.02",
    "business admin": "52.02",
    "mba": "52.02",              # field cell carrying the degree name -> the field
    "organizational management": "52.02",
    "management and leadership": "52.02",
    "general business": "52.0101",
    "commerce": "52.0101",
    "accountancy": "52.0301",
    "entrepreneurship": "52.0701",
    "business marketing": "52.14",
    "digital marketing": "52.14",
    "financial management": "52.08",
    "business finance": "52.08",
    "corporate finance": "52.08",
    "banking and finance": "52.0803",
    "business economics": "52.0601",
    "supply chain management": "52.0203",
    "operations management": "52.0205",
    "nonprofit management": "52.0206",
    "hospitality management": "52.0901",
    "hospitality and tourism management": "52.09",
    "international management": "52.11",
    "business information systems": "52.12",
    "mis": "52.1201",
    "human resource development": "52.1005",
    "office administration": "52.04",
    # --- computing / engineering ---
    "computer information systems": "11.01",
    "information science": "11.0401",
    "it": "11.0103",
    "cybersecurity": "11.1003",
    "cyber security": "11.1003",
    "cybersecurity and information assurance": "11.1003",
    "software engineering": "14.0903",
    "biomedical engineering": "14.0501",
    "bioengineering": "14.0501",
    "aerospace engineering": "14.0201",
    "environmental engineering": "14.1401",
    "electronics engineering": "14.1001",
    "electronic engineering": "14.1001",
    "electronics and communications engineering": "14.1001",
    "electronics and communication engineering": "14.1001",
    "industrial and systems engineering": "14.3501",
    "materials science and engineering": "14.1801",
    "engineering management": "15.1501",
    "industrial management": "15.1501",
    "industrial technology": "15.0612",
    "mechanical engineering technology": "15.0805",
    "electronics technology": "15.0303",
    "electronics engineering technology": "15.0303",
    "electronic engineering technology": "15.0303",
    "electrical engineering technology": "15.0303",
    "audio engineering": "10.0203",
    # --- education ---
    "elementary education": "13.1202",
    "secondary education": "13.1205",
    "special education": "13.1001",
    "early childhood education": "13.1210",
    "adult education": "13.1201",
    "educational leadership": "13.0401",
    "educational administration": "13.0401",
    "education administration": "13.0401",
    "school counseling": "13.1101",
    "instructional technology": "13.0501",
    "music education": "13.1312",
    "art education": "13.1302",
    "business education": "13.1303",
    "english education": "13.1305",
    "physical education": "13.1314",
    "teaching": "13",            # family-level: education, level unknown
    # --- health ---
    "healthcare administration": "51.0701",
    "health care administration": "51.0701",
    "health administration": "51.0701",
    "healthcare management": "51.0701",
    "health care management": "51.0701",
    "health information management": "51.0706",
    "health informatics": "51.2706",
    "health science": "51.0000",
    "health sciences": "51.0000",
    "healthcare": "51",          # family-level: health professions
    "medical technology": "51.1005",
    "medical billing and coding": "51.0713",
    "medical assistant": "51.0801",
    "medical assisting": "51.0801",
    "physical therapy": "51.2308",
    "physical therapist assistant": "51.0806",
    "occupational therapy": "51.2306",
    "dental hygiene": "51.0602",
    "dietetics": "51.3101",
    "registered nurse": "51.3801",
    "family nurse practitioner": "51.3805",
    "clinical mental health counseling": "51.1508",
    "clinical social work": "51.1503",
    # --- social science / public ---
    "government": "45.10",       # e.g. Harvard/Georgetown name for political science
    "politics": "45.10",
    "social science": "45",      # family-level, like the verbatim "Social Sciences"
    "international affairs": "45.0901",
    "international studies": "30.2001",
    "public policy": "44.0501",
    "public affairs": "44",      # family-level: public administration professions
    "urban planning": "04.0301",
    "law enforcement": "43.0107",
    "administration of justice": "43.0103",
    "criminal justice administration": "43.0103",
    "paralegal": "22.0302",
    "paralegal studies": "22.0302",
    # --- arts / humanities / media ---
    "english": "23.01",
    "humanities": "24.0103",
    "liberal studies": "24.0101",
    "interdisciplinary studies": "30",  # family-level multi/interdisciplinary
    "theology": "39.0601",
    "spanish": "16.0905",
    "french": "16.0901",
    "american studies": "05.0102",
    "theatre": "50.05",
    "theater": "50.05",
    "theatre theater": "50.05",  # normalized "Theatre/Theater"
    "theatre arts": "50.05",
    "theater arts": "50.05",
    "fine arts": "50.07",
    "fine art": "50.07",
    "studio art": "50.0702",
    "film": "50.0601",
    "film production": "50.0602",
    "fashion design": "50.0407",
    "industrial design": "50.0404",
    "communication design": "50.04",
    "visual communications": "50.0401",
    "vocal performance": "50.0908",
    "piano performance": "50.0907",
    "music business": "50.1003",
    "culinary arts": "12.0503",
    "cosmetology": "12.0401",
    "mass communications": "09.0102",
    "mass communication": "09.0102",
    "media studies": "09.0102",
    "communication arts": "09.0100",
    "speech communication": "09.0101",
    "speech communications": "09.0101",
    "strategic communication": "09.09",
    "strategic communications": "09.09",
    "integrated marketing communications": "09.09",
    # --- sciences / quantitative ---
    "math": "27.01",
    "biological sciences": "26.01",
    "zoology": "26.0701",
    "geology": "40.0601",
    "kinesiology": "31.0505",
    "exercise science": "31.0505",
    "sports and exercise": "31.05",
    "sports management": "31.0504",
    "sport management": "31.0504",
    "sports administration": "31.0504",
    "animal science": "01.0901",
    "human development": "19.0701",
    "library science": "25.0101",
    "occupational safety and health": "15.0701",
    # --- secondary-level credentials in the field column ---
    "high school": "53",
    "ged": "53.0201",
    "college prep": "53.0102",
}
# Deliberately NOT aliased (ambiguous; revisit only with a measured decision):
#   "Science", "Arts", "Design", "Medical", "Leadership", "Counseling",
#   "Electronics", "Electrical", "EE", "Information Systems" (11.04 vs 52.12),
#   "English Literature" (gold keeps it distinct from English/23.01),
#   "Telecommunications" (09.07 vs 10.03 vs engineering), "Nutrition" (19.05
#   vs 30.19 vs 51.31), "Health Education" (13.1307 vs 51.2207), "Technology
#   Management", "Computer Technology", "Computers", "Applied Science",
#   combination fields ("Finance and Marketing", "Computer Science and
#   Engineering", "History and Political Science", "Biology/Chemistry", ...).

# Exact CIP titles where the target canonical should be the stable CIP group
# rather than the 6-digit "General" member. Keep this list intentionally tiny:
# each entry is a measured granularity decision, not a generic rollup rule.
FIELD_CIP_OVERRIDES = {
    "biology biological sciences": "26.01",
    "biology biological sciences general": "26.01",
    # The verbatim CIP family-23 title is the same label people use for the
    # 23.01 group; keep it merged with "English Language and Literature,
    # General" (gold) rather than splitting family vs group.
    "english language and literature letters": "23.01",
    "english language literature letters": "23.01",
}

# Sortable ordinal for the degree *level* axis (HS=1 ... doctorate=7), so
# "highest degree" never requires string parsing downstream. Levels that share
# a rung share the ordinal. "graduate"/"postgraduate" are above bachelor but
# unresolved between master and doctorate, so they sit below "master".
# "minor" and "study_abroad" are credentials without a level -> no ordinal.
DEGREE_LEVEL_ORDINAL = {
    "high_school": 1,
    "certificate": 2,
    "diploma": 2,
    "foundation": 2,
    "associate": 3,
    "bachelor": 4,
    "undergraduate": 4,
    "graduate": 5,
    "postgraduate": 5,
    "master": 6,
    "doctorate": 7,
}

EXTRA_DEGREE_ABBREV = {
    "bsba": ("bachelor", "business_admin"),
    "bsee": ("bachelor", "engineering"),
    "bsme": ("bachelor", "engineering"),
    "bscs": ("bachelor", "computer_science"),
    "bcom": ("bachelor", "commerce"),
    "bed": ("bachelor", "education"),
    "llb": ("bachelor", "law"),
    "mba": ("master", "business_admin"),
    "mpa": ("master", "public_admin"),
    "mph": ("master", "public_health"),
    "msw": ("master", "social_work"),
    "mfa": ("master", "fine_arts"),
    "med": ("master", "education"),
    "meng": ("master", "engineering"),
    "llm": ("master", "law"),
    "phd": ("doctorate", "philosophy"),
    "edd": ("doctorate", "education"),
    "dba": ("doctorate", "business_admin"),
}


@dataclass
class DetailedResult:
    name: str
    field: str
    mapping: dict[str, str]
    runtime_s: float
    method: dict[str, str] = dc_field(default_factory=dict)
    confidence: dict[str, float] = dc_field(default_factory=dict)
    extra: dict = dc_field(default_factory=dict)

    def n_in(self) -> int:
        return len(self.mapping)

    def n_out(self) -> int:
        return len(set(self.mapping.values()))

    def reduction(self) -> float:
        return 1.0 - self.n_out() / self.n_in() if self.mapping else 0.0

    def as_result(self) -> Result:
        return Result(self.name, self.field, self.mapping, self.runtime_s, self.extra)


def safe_norm(text: str | None) -> str:
    """ASCII matching key with a Unicode-preserving fallback for raw ids.

    The older normalizer intentionally drops non-ASCII. That is fine for many
    matching indexes, but unsafe for raw canonical ids because unrelated labels
    can collapse to an empty string.
    """
    norm = normalize(text or "")
    if norm:
        return norm
    s = unicodedata.normalize("NFKC", text or "").strip().lower()
    s = _WS.sub(" ", s)
    return s


def raw_id(prefix: str, value: str | None) -> str:
    norm = safe_norm(value)
    if is_nullish(norm):
        return f"{prefix}:__blank__"
    return f"{prefix}:{norm}"


def compact_key(value: str | None) -> str:
    return _ALNUM.sub("", normalize(value or ""))


def _row_pct_by_method(vocab: list[tuple], method: dict[str, str]) -> dict[str, float]:
    rows: dict[str, int] = defaultdict(int)
    total = 0
    for value, freq, *_ in vocab:
        total += freq
        rows[method[value]] += freq
    return {k: round(100 * v / total, 1) for k, v in sorted(rows.items())}


def parse_degree(value: str) -> tuple[str, str, float]:
    # Junk/placeholder degree cells ("4.0", "Graduated", "N/A") carry no
    # degree signal; blank them before the taxonomy can mis-parse them.
    if is_nullish(safe_norm(value)):
        return "degree_raw:__blank__", "raw", 0.5

    ck = compact_key(value)
    if ck in EXTRA_DEGREE_ABBREV:
        level, typ = EXTRA_DEGREE_ABBREV[ck]
        return f"{level}:{typ}", "taxonomy_abbrev", 1.0

    parsed = A._parse_degree(value)  # noqa: SLF001 - reuse benchmarked parser.
    if not parsed.startswith("raw:"):
        return parsed, "taxonomy", 1.0

    # Dotted abbreviations such as M.B.A. normalize to "m b a"; compact them
    # before giving up.
    if ck in EXTRA_DEGREE_ABBREV:
        level, typ = EXTRA_DEGREE_ABBREV[ck]
        return f"{level}:{typ}", "taxonomy_abbrev", 1.0
    return raw_id("degree_raw", value), "raw", 0.5


# ---------------------------------------------------------------------------
# Degree -> field cross-pass ("cip_from_degree"). Two measured phenomena:
#   1. degree/field column swaps: the degree cell is verbatim a CIP title
#      ("Computer Science", "Business Administration and Management, General")
#      -> emit the CIP as a field signal and blank the degree (it isn't one).
#   2. "Bachelor of X in Y": the taxonomy keeps level/type and discards Y
#      -> if Y matches CIP, emit it as a field signal (degree stays parsed).
# ---------------------------------------------------------------------------
_CIP_INDEXES: tuple[dict, dict] | None = None


def _cip_indexes() -> tuple[dict, dict]:
    global _CIP_INDEXES
    if _CIP_INDEXES is None:
        _CIP_INDEXES = A._load_cip()  # noqa: SLF001 - reuse benchmarked loader.
    return _CIP_INDEXES


def _field_cip_lookup(text: str) -> str | None:
    """Same precedence as the field canonicalizer: override -> CIP exact ->
    CIP token -> curated alias. Returns a bare CIP code or None."""
    norm = normalize(text)
    if not norm:
        return None
    code = FIELD_CIP_OVERRIDES.get(norm)
    if code:
        return code
    by_norm, by_tokens = _cip_indexes()
    return by_norm.get(norm) or by_tokens.get(token_key(text)) or FIELD_CIP_ALIASES.get(norm)


def degree_field_signal(value: str | None) -> tuple[str, bool] | None:
    """If a degree cell carries a field of study, return (cip_code,
    degree_is_field). degree_is_field=True means the whole cell is a field
    title (column swap) and the degree should be blanked."""
    norm = safe_norm(value)
    if is_nullish(norm):
        return None
    if parse_degree(value)[1] == "raw":
        code = _field_cip_lookup(value)
        return (code, True) if code else None
    # taxonomy parsed: try the subject after the first " in "
    _, _, subject = normalize(value).partition(" in ")
    if subject:
        code = _field_cip_lookup(subject)
        if code:
            return (code, False)
    return None


def degree_field_mapping(vocab: list[tuple]) -> DetailedResult:
    """Value-level mapping: degree raw value -> 'cip:<code>' field signal
    (method 'cip_from_degree'). Only values with a signal are emitted."""
    with timer() as t:
        mapping: dict[str, str] = {}
        method: dict[str, str] = {}
        conf: dict[str, float] = {}
        for value, *_ in vocab:
            signal = degree_field_signal(value)
            if signal is None:
                continue
            code, _is_swap = signal
            mapping[value] = f"cip:{code}"
            method[value] = "cip_from_degree"
            conf[value] = 0.9
    rows = sum(freq for value, freq, *_ in vocab if value in mapping)
    return DetailedResult(
        name="final_hybrid",
        field="degree_field",
        mapping=mapping,
        runtime_s=t.elapsed,
        method=method,
        confidence=conf,
        extra={"rows_with_signal": rows},
    )


def canon_degree(vocab: list[tuple]) -> DetailedResult:
    with timer() as t:
        mapping: dict[str, str] = {}
        method: dict[str, str] = {}
        conf: dict[str, float] = {}
        for value, *_ in vocab:
            cid, m, c = parse_degree(value)
            if m == "raw" and cid != "degree_raw:__blank__":
                signal = degree_field_signal(value)
                if signal is not None and signal[1]:
                    # The cell is a field of study, not a degree: blank it
                    # (the CIP is emitted separately via degree_field_mapping).
                    cid, m, c = "degree_raw:__blank__", "cip_from_degree", 0.9
            mapping[value] = cid
            method[value] = m
            conf[value] = c
    return DetailedResult(
        name="final_hybrid",
        field="degree",
        mapping=mapping,
        runtime_s=t.elapsed,
        method=method,
        confidence=conf,
        extra={"row_pct_by_method": _row_pct_by_method(vocab, method)},
    )


def _guarded_title_crosswalk(vocab: list[tuple]) -> dict[str, str]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for value, freq, slug in vocab:
        key = normalize(value)
        if key and slug:
            counts[key][slug] += freq

    out: dict[str, str] = {}
    for key, slug_counts in counts.items():
        ranked = sorted(slug_counts.items(), key=lambda x: x[1], reverse=True)
        if len(ranked) == 1:
            out[key] = ranked[0][0]
            continue
        total = sum(c for _slug, c in ranked)
        top_slug, top_count = ranked[0]
        second_count = ranked[1][1]
        if top_count / total >= 0.98 and top_count - second_count >= 10:
            out[key] = top_slug
    return out


def school_slug_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = _SCHOOL_SLUG_RE.search(url)
    return match.group(1) if match else None


def canon_title_value(
    value: str | None,
    *,
    slug: str | None = None,
    url: str | None = None,
    name_crosswalk: dict[str, str] | None = None,
) -> tuple[str, str, float]:
    """Canonicalize one institution row, preferring the row's actual slug."""
    actual_slug = slug or school_slug_from_url(url)
    if actual_slug:
        return f"slug:{actual_slug}", "slug", 1.0
    key = normalize(value or "")
    if key and name_crosswalk and key in name_crosswalk:
        return f"slug:{name_crosswalk[key]}", "slug_crosswalk", 0.98
    return raw_id("name", value), "raw", 0.5


def canon_title(vocab: list[tuple]) -> DetailedResult:
    with timer() as t:
        crosswalk = _guarded_title_crosswalk(vocab)
        base: dict[str, str] = {}
        method: dict[str, str] = {}
        conf: dict[str, float] = {}

        for value, _freq, slug in vocab:
            cid, m, c = canon_title_value(value, slug=slug, name_crosswalk=crosswalk)
            base[value] = cid
            method[value] = m
            conf[value] = c

        b_map = B.run("title", vocab).mapping
        for value, *_ in vocab:
            if method[value] != "raw":
                continue
            rep = b_map[value]
            if rep != value and rep in base and base[rep].startswith("slug:"):
                base[value] = base[rep]
                method[value] = "typo_to_slug"
                conf[value] = 0.9
            elif rep != value:
                base[value] = raw_id("name", rep)
                method[value] = "typo"
                conf[value] = 0.85

    return DetailedResult(
        name="final_hybrid",
        field="title",
        mapping=base,
        runtime_s=t.elapsed,
        method=method,
        confidence=conf,
        extra={"row_pct_by_method": _row_pct_by_method(vocab, method)},
    )


def _base_field_map(vocab: list[tuple]) -> tuple[dict[str, str], dict[str, str], dict[str, float]]:
    a_map = A.canon_field(vocab)
    mapping: dict[str, str] = {}
    method: dict[str, str] = {}
    conf: dict[str, float] = {}
    for value, *_ in vocab:
        norm = normalize(value)
        override_code = FIELD_CIP_OVERRIDES.get(norm)
        if override_code:
            mapping[value] = f"cip:{override_code}"
            method[value] = "cip_override"
            conf[value] = 0.98
            continue
        aid = a_map[value]
        if aid.startswith("cip:"):
            mapping[value] = aid
            method[value] = "cip_exact"
            conf[value] = 1.0
            continue
        alias_code = FIELD_CIP_ALIASES.get(norm)
        if alias_code:
            mapping[value] = f"cip:{alias_code}"
            method[value] = "cip_alias"
            conf[value] = 0.98
        else:
            mapping[value] = raw_id("field_raw", value)
            method[value] = "raw"
            conf[value] = 0.5
    return mapping, method, conf


def canon_field(vocab: list[tuple]) -> DetailedResult:
    with timer() as t:
        mapping, method, conf = _base_field_map(vocab)
        b_map = B.run("field", vocab).mapping

        for value, *_ in vocab:
            if method[value] != "raw":
                continue
            rep = b_map[value]
            if rep == value:
                continue
            rep_id = mapping.get(rep)
            if rep_id and rep_id.startswith("cip:"):
                mapping[value] = rep_id
                method[value] = "typo_to_cip"
                conf[value] = 0.9
            else:
                mapping[value] = raw_id("field_raw", rep)
                method[value] = "typo"
                conf[value] = 0.85

    return DetailedResult(
        name="final_hybrid",
        field="field",
        mapping=mapping,
        runtime_s=t.elapsed,
        method=method,
        confidence=conf,
        extra={"row_pct_by_method": _row_pct_by_method(vocab, method)},
    )


def run(field_name: str, vocab: list[tuple]) -> DetailedResult:
    if field_name == "degree":
        return canon_degree(vocab)
    if field_name == "title":
        return canon_title(vocab)
    if field_name == "field":
        return canon_field(vocab)
    raise ValueError(field_name)
