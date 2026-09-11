"""Approach A: deterministic rules + the in-data reference key.

* company -> the LinkedIn ``company_id`` is the canonical organization key
             (analogous to the school slug in education). Placeholder values
             ("Self-employed", "Freelance", "Retired", ...) are routed to a
             NON_ORG bucket FIRST -- their company_ids are noise (e.g.
             "Self-employed" -> id "conscience-vc"), so trusting the id there
             would split synonymous placeholders and merge unrelated ones.
             No-id names are backfilled via an exact-normalized name->id
             crosswalk mined from values that do carry an id.
* title   -> parse into (seniority level, base role) via a controlled
             abbreviation/seniority taxonomy. Canonical = "level|base", so
             "Sr. Software Engineer" == "Senior Software Engineer" but stays
             distinct from "Software Engineer" (level matters, exactly like
             degree level in education).

No fuzzy matching, no ML. Transparent and reproducible. Values that match no
reference key map to their normalized self (left distinct).
"""

from __future__ import annotations

import re

from .common import Result, normalize, timer

# ====================== COMPANY: id key + placeholders ===================
# Placeholder (non-organization) values -> canonical status bucket. Matched on
# the normalized string. Order matters only for the regex fallbacks below.
_PLACEHOLDER_EXACT = {
    "self employed": "self_employed",
    "selfemployed": "self_employed",
    "self": "self_employed",
    "freelance": "self_employed",
    "freelancer": "self_employed",
    "freelance self employed": "self_employed",
    "independent contractor": "self_employed",
    "independent consultant": "self_employed",
    "sole proprietor": "self_employed",
    "private practice": "self_employed",
    "self employed contractor": "self_employed",
    "consultant self employed": "self_employed",
    "autonomo": "self_employed",
    "autonoma": "self_employed",
    "independiente": "self_employed",
    "por cuenta propia": "self_employed",
    "selbstandig": "self_employed",
    "selbststandig": "self_employed",
    "travailleur autonome": "self_employed",
    "retired": "retired",
    "semi retired": "retired",
    "unemployed": "unemployed",
    "unemployed at this time": "unemployed",
    "student": "student",
    "homemaker": "homemaker",
    "stay at home parent": "homemaker",
    "n a": "none",
    "na": "none",
    "none": "none",
    "null": "none",
    "unknown": "none",
    "various": "various",
    "various companies": "various",
    "various clients": "various",
    "various organizations": "various",
    "multiple": "various",
    "confidential": "confidential",
    "private": "confidential",
    "undisclosed": "confidential",
    "stealth": "stealth",
    "stealth startup": "stealth",
    "stealth mode startup": "stealth",
    # audit 2026-09-02 (red C1/M5): bare status words that had acquired
    # LinkedIn company_ids through modal-id inheritance and became "employers"
    # ("Independent" 2,324 rows, "Home" 1,938, "Consultant" 1,742).
    "independent": "self_employed",
    "consultant": "self_employed",
    "consulting": "self_employed",
    "contractor": "self_employed",
    "contract": "self_employed",
    "myself": "self_employed",
    "me": "self_employed",
    "own business": "self_employed",
    "my own business": "self_employed",
    "entrepreneur": "self_employed",
    "home": "none",
    "tbd": "none",
}
_PLACEHOLDER_RE = [
    (re.compile(r"^self.?employ"), "self_employed"),
    (re.compile(r"^freelanc"), "self_employed"),
    (re.compile(r"^independent (?:contractor|consultant)\b"), "self_employed"),
    (re.compile(r"^sole proprietor\b"), "self_employed"),
    (re.compile(r"^private practice\b"), "self_employed"),
    (re.compile(r"^autonom[oa]\b"), "self_employed"),
    (re.compile(r"^independiente\b"), "self_employed"),
    (re.compile(r"^por cuenta propia\b"), "self_employed"),
    (re.compile(r"^selbstandig\b|^selbststandig\b"), "self_employed"),
    (re.compile(r"^retired\b"), "retired"),
    (re.compile(r"^semi retired\b"), "retired"),
    (re.compile(r"^unemployed\b"), "unemployed"),
    (re.compile(r"^stealth\b"), "stealth"),
    (re.compile(r"^various\b"), "various"),
    # -- status strings that topped the unresolved industry head (2026-09-02):
    # "Stay at Home Mom" (453 rows), "self-emplyed", "In Transition", "Private
    # Company" (841), "Profesional independiente" (312).  Anchored, and the
    # organisations sharing a prefix (Seeking Alpha, Independent Artist Group,
    # Volunteer State CC, Private Equity Partners) are pinned in company_tests.
    (re.compile(r"^stay at home(?! llc\b)"), "homemaker"),
    (re.compile(r"^sah[md]$"), "homemaker"),
    (re.compile(r"^full time (mom|dad|mother|father|parent|mum)\b"), "homemaker"),
    (re.compile(r"^house ?(wife|husband)$"), "homemaker"),
    (re.compile(r"^home ?maker( mom| dad| and .*)?$"), "homemaker"),
    (re.compile(r"^(mom|mother|dad|father|parent|mum|mommy)$"), "homemaker"),
    (re.compile(r"^self ?empl"), "self_employed"),            # emplyed, emplyoed, emploed ...
    (re.compile(r"^profesional independiente\b"), "self_employed"),
    (re.compile(r"^independent professional$"), "self_employed"),
    (re.compile(r"^independent (artist|writer|filmmaker|musician|researcher|scholar|author|producer|"
                r"designer|photographer|creator|journalist|curator|composer|illustrator)$"), "self_employed"),
    (re.compile(r"^(author|writer|poet|novelist|self published author|independent author|published author|"
                r"freelance author|artist|fine artist|visual artist|working artist|musician|singer songwriter|"
                r"photographer|filmmaker|illustrator|composer)$"), "self_employed"),
    (re.compile(r"^(my )?own (company|business|firm|practice|studio)\b"), "self_employed"),
    (re.compile(r"^myself\b"), "self_employed"),
    (re.compile(r"^solopreneur\b"), "self_employed"),
    (re.compile(r"^personal (projects?|business|work)$"), "self_employed"),
    (re.compile(r"^in transition\b"), "career_break"),
    (re.compile(r"^career break\b"), "career_break"),
    (re.compile(r"^(on )?sabbatical\b"), "career_break"),
    (re.compile(r"^(actively )?seeking (a |my )?(new|next|employment|work|jobs?|positions?|opportunit|"
                r"full time|part time|other|re employment|gainful)"), "unemployed"),
    (re.compile(r"^looking for (a |my )?(new|next|jobs?|work|employment|opportunit|opporunit|positions?|"
                r"full time|part time)"), "unemployed"),
    (re.compile(r"^open to (work|opportunities|new opportunit|a new|new roles|roles)"), "unemployed"),
    (re.compile(r"^between (jobs|positions|opportunities|roles|gigs)\b"), "unemployed"),
    (re.compile(r"^job seek(er|ing)\b"), "unemployed"),
    (re.compile(r"^not (currently )?(employed|working)\b"), "unemployed"),
    (re.compile(r"^currently (unemployed|not (working|employed)|seeking|looking|between)\b"), "unemployed"),
    (re.compile(r"^retiree$|^none retired\b"), "retired"),
    (re.compile(r"^none\b|^not applicable\b|^not available\b|^personal$"), "none"),
    (re.compile(r"^(at home|my home|home office|work from home|working from home|home based|from home)$"), "none"),
    (re.compile(r"^multiple (compan(y|ies)|organi[sz]ations|clients|locations|agencies|employers|firms|families|"
                r"schools|hospitals|businesses|positions|jobs|projects|contracts|universities|colleges|districts|"
                r"practices|restaurants|sites)\b"), "various"),
    (re.compile(r"^misc(ellaneous)?$"), "various"),
    (re.compile(r"^confidential$|^confidential (company|clients?|jobs?|family( office)?|employer|organi[sz]ation|"
                r"firm|startup|position|project|at this time|for now|until)\b"), "confidential"),
    (re.compile(r"^anonymous$"), "confidential"),
    (re.compile(r"^private (compan(y|ies)|firm|employer|business|organi[sz]ation|sector|clients?|individuals?|"
                r"investors?|consulting|owner|party|group|corporation)$"), "confidential"),
    (re.compile(r"^private (famil(y|ies)|households?|homes?|residences?|family home|family household|house|estate)$"),
     "private_household"),
    (re.compile(r"^volunteer$|^volunteer (work|positions?|activities|services?|experience|roles?)$"), "volunteer"),
]


def _placeholder_bucket(norm: str) -> str | None:
    if norm in _PLACEHOLDER_EXACT:
        return _PLACEHOLDER_EXACT[norm]
    for rx, bucket in _PLACEHOLDER_RE:
        if rx.search(norm):
            return bucket
    return None


# ======================== EMPLOYMENT TYPE AXIS ==========================
# Employment status is orthogonal to both the company axis and the occupation
# axis. Company placeholders are strong signals; title markers recover the cases
# where a real or raw-looking company line hides solo work.
_BUCKET_TO_EMPLOYMENT = {
    "self_employed": "self_employed",
    "retired": "retired",
    "unemployed": "unemployed",
    "student": "student",
    "homemaker": "homemaker",
    "none": "unknown",
    "various": "various",
    "confidential": "confidential",
    "stealth": "stealth",
    "private_household": "employee",   # nannies, drivers, estate staff: employed by a household (NAICS 814)
    "career_break": "career_break",
    "volunteer": "volunteer",
}
_TITLE_STATUS_EXACT = {
    "retired": "retired",
    "semi retired": "retired",
    "unemployed": "unemployed",
    "student": "student",
    "homemaker": "homemaker",
    "stay at home parent": "homemaker",
}
_TITLE_STATUS_RE = [
    (re.compile(r"^retired\b|^semi retired\b"), "retired"),
    (re.compile(r"^unemployed\b"), "unemployed"),
    (re.compile(r"^student\b"), "student"),
    (re.compile(r"^homemaker\b|^stay at home\b"), "homemaker"),
]
_SOLO_TITLE_RE = [
    re.compile(r"^freelanc(?:e|er)?\b"),
    re.compile(r"^self employed\b|^selfemployed\b"),
    re.compile(r"^independent\b"),
    re.compile(r"^contractor\b"),
    re.compile(r"^sole proprietor\b"),
    re.compile(r"^private practice\b"),
    re.compile(r"^autonom[oa]\b"),
    re.compile(r"^independiente\b"),
    re.compile(r"^por cuenta propia\b"),
    re.compile(r"^selbstandig\b|^selbststandig\b"),
]
_OWNER_FALSE_POSITIVE = {
    "product owner",
    "scrum product owner",
    "agile product owner",
    "technical product owner",
}
_OWNER_TOKENS = {"owner", "proprietor"}
_FOUNDER_TOKENS = {"founder", "cofounder"}
_STATUS_PREFIXES = (
    "independent contractor",
    "sole proprietor",
    "private practice",
    "self employed",
    "selfemployed",
    "por cuenta propia",
    "freelance",
    "freelancer",
    "independent",
    "contractor",
    "private",
    "autonomo",
    "autonoma",
    "independiente",
    "selbstandig",
    "selbststandig",
)


def placeholder_to_employment(bucket: str) -> str:
    return _BUCKET_TO_EMPLOYMENT.get(bucket, bucket)


def title_status_bucket(value: str | None) -> str | None:
    norm = normalize(value)
    if norm in _TITLE_STATUS_EXACT:
        return _TITLE_STATUS_EXACT[norm]
    for rx, bucket in _TITLE_STATUS_RE:
        if rx.search(norm):
            return bucket
    return None


def title_has_solo_marker(value: str | None) -> bool:
    norm = normalize(value)
    return any(rx.search(norm) for rx in _SOLO_TITLE_RE)


def title_has_owner_marker(value: str | None) -> bool:
    norm = normalize(value)
    if not norm or norm in _OWNER_FALSE_POSITIVE:
        return False
    toks = set(norm.split())
    return bool(toks & _OWNER_TOKENS or toks & _FOUNDER_TOKENS)


def strip_employment_status_prefix(value: str | None) -> str:
    norm = normalize(value)
    if not norm:
        return ""
    for prefix in _STATUS_PREFIXES:
        if norm == prefix:
            return ""
        if norm.startswith(prefix + " "):
            return norm[len(prefix) + 1 :].strip()
    return norm


def resolve_employment_type(
    *,
    company: str | None,
    title: str | None,
    company_id: str | None = None,  # retained for API symmetry with company resolution
) -> tuple[str, str, float]:
    """Return (employment_type, method, confidence) for one career row."""
    del company_id
    title_status = title_status_bucket(title)
    if title_status:
        return placeholder_to_employment(title_status), "title_status", 1.0

    company_bucket = _placeholder_bucket(normalize(company))
    if company_bucket:
        return placeholder_to_employment(company_bucket), "company_placeholder", 1.0

    if title_has_solo_marker(title):
        return "self_employed", "title_solo_marker", 0.95
    if title_has_owner_marker(title):
        return "business_owner", "title_owner_marker", 0.9
    return "employee", "default_employee", 0.8


# Curated cross-id entity equivalences: rebrands / parent reorganizations where
# LinkedIn keeps two distinct company_ids for what is one real-world company.
# Maps a company_id onto the canonical id for the family. Canonical = the
# family's dominant (highest-frequency) id. This is the curated-alias ratchet
# (see FINDINGS): extend it as equivalences are confirmed in the review queue.
# NOTE: deliberately limited to rebrands, NOT distinct product brands/
# subsidiaries (Instagram, WhatsApp, YouTube, DeepMind stay separate) — rolling
# subsidiaries up to a parent is a separate unit-of-analysis decision.
ENTITY_ALIASES = {
    "facebook": "meta",        # Facebook, Inc. renamed to Meta
    "metafacebook": "meta",
    "alphabet-inc": "google",  # Google reorganized under Alphabet
}


def canonical_company_id(cid: str) -> str:
    """Apply curated cross-id entity equivalences (Facebook->Meta, etc.)."""
    return ENTITY_ALIASES.get(cid, cid)


# LinkedIn links university EMPLOYERS to ``/school/<slug>`` pages and leaves
# ``company_id`` blank, so 454k experience rows (299k persons) had no stable
# key (audit 2026-09-02 green E1). The slug is the same namespace as
# ``company_id`` (on id-bearing rows the ``/company/<slug>`` URL equals the id
# 99.8% of the time), so it is used verbatim as ``id:<slug>``. RE2 syntax, used
# by both the Python helper and the DuckDB ``regexp_extract`` in
# build_normalized (company_tests asserts they agree).
SCHOOL_URL_RE = r"linkedin\.com/school/([^/?#]+)"
_SCHOOL_URL = re.compile(SCHOOL_URL_RE)


def school_slug(url: str | None) -> str | None:
    """``id``-namespace slug from a linkedin.com/school/<slug> URL, else None."""
    if not url:
        return None
    m = _SCHOOL_URL.search(url)
    return m.group(1).lower() if m else None


def _name_to_id_crosswalk(vocab: list[tuple]) -> dict[str, str]:
    """normalized non-placeholder name -> modal company_id (mined from rows that
    carry an id), so a no-id spelling inherits the id of its id-bearing twin."""
    out: dict[str, str] = {}
    for value, _freq, modal_id in vocab:
        if not modal_id:
            continue
        norm = normalize(value)
        if not norm or _placeholder_bucket(norm):
            continue
        out.setdefault(norm, modal_id)
    return out


def canon_company(vocab: list[tuple]) -> dict:
    crosswalk = _name_to_id_crosswalk(vocab)
    mapping: dict[str, str] = {}
    for value, _freq, modal_id in vocab:
        norm = normalize(value)
        bucket = _placeholder_bucket(norm)
        if bucket:
            mapping[value] = f"nonorg:{bucket}"
        elif modal_id:
            mapping[value] = f"id:{canonical_company_id(modal_id)}"
        else:
            recovered = crosswalk.get(norm)
            mapping[value] = (
                f"id:{canonical_company_id(recovered)}" if recovered else f"raw:{norm}"
            )
    return mapping


# ====================== TITLE: seniority/role taxonomy ===================
# Token-level abbreviation expansion (single token -> one or more tokens).
_TITLE_ABBREV = {
    "sr": "senior",
    "snr": "senior",
    "jr": "junior",
    "mgr": "manager",
    "mgmt": "management",
    "dir": "director",
    "asst": "assistant",
    "assoc": "associate",
    "admin": "administrative",
    "coord": "coordinator",
    "rep": "representative",
    "exec": "executive",
    "eng": "engineer",
    "engr": "engineer",
    "dev": "developer",
    "spec": "specialist",
    "tech": "technician",
    "acct": "account",
    "vp": "vice president",
    "svp": "senior vice president",
    "evp": "executive vice president",
    "avp": "assistant vice president",
    "ceo": "chief executive officer",
    "cfo": "chief financial officer",
    "coo": "chief operating officer",
    "cto": "chief technology officer",
    "cmo": "chief marketing officer",
    "cio": "chief information officer",
    "rn": "registered nurse",
    "lpn": "licensed practical nurse",
    "cna": "certified nursing assistant",
    "np": "nurse practitioner",
    "hr": "human resources",
    # "PM" is genuinely ambiguous (project/product/program manager), so keep it
    # literal unless surrounding tokens resolve it elsewhere.
    "qa": "quality assurance",
    "ux": "user experience",
    "ui": "user interface",
}
# Seniority / level markers pulled OUT of the base role into a sorted signature,
# so two titles match iff they share the same role AND the same level set.
_LEVEL_TOKENS = {
    "intern": "intern",
    "trainee": "intern",
    "apprentice": "intern",
    "junior": "junior",
    "associate": "associate",
    "senior": "senior",
    "lead": "lead",
    "principal": "principal",
    "staff": "staff",
    "chief": "chief",
    "head": "head",
    "director": "director",
    "vice": "vice",  # from "vice president"
    "executive": "executive",
}
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}

# Numeric level bands are only credible in the roman-numeral range (Engineer 2,
# Analyst III, ...). Larger numbers in titles are codes, not seniority ("Region
# 12", "Unit 42") -- the unclamped rule manufactured junk lvl6-lvl19 tokens on
# ~19k steps (2026-06-10 audit, finding 2).
_LEVEL_DIGITS = {"1", "2", "3", "4", "5"}


def _is_level_digit(tok: str) -> bool:
    return tok in _LEVEL_DIGITS


def parse_title(value: str) -> tuple[str, str]:
    """Return (level_signature, base_role) from a raw title."""
    norm = normalize(value)
    # expand abbreviations token-wise
    toks: list[str] = []
    for t in norm.split():
        toks.extend(_TITLE_ABBREV.get(t, t).split())
    levels: set[str] = set()
    base: list[str] = []
    for t in toks:
        if t in _LEVEL_TOKENS:
            levels.add(_LEVEL_TOKENS[t])
        elif t in _ROMAN:
            levels.add(f"lvl{_ROMAN[t]}")
        elif _is_level_digit(t):
            levels.add(f"lvl{int(t)}")
        elif t == "president":
            base.append(t)  # keep 'president' so "vice president" != "president"
        else:
            base.append(t)
    base_norm = " ".join(sorted(t for t in base if t not in {"and", "of", "the"}))
    lvl = ",".join(sorted(levels))
    return lvl, base_norm


# ================= SENIORITY RANK AXIS (separate output column) ============
# Tokens that signal rank but are part of the base-role IDENTITY -- moving
# "manager"/"supervisor" into the level signature would merge e.g. "Account
# Manager" into base "account". So they are emitted ONLY on the separate
# ``seniority_rank_token`` column, never into the title canonical.
# 'gm' / 'md' were considered and rejected: 'md' is overwhelmingly Medical
# Doctor and 'gm' collides with brand/grade tokens -- not precision-safe.
_RANK_ONLY_TOKENS = {
    "manager": "manager",
    "supervisor": "supervisor",
}
_DISPLAY_LOWER = {"and", "of", "the"}


def seniority_rank_tokens(value: str | None) -> str:
    """Comma-joined sorted token set for the seniority-rank axis: every
    ``_LEVEL_TOKENS`` marker plus the rank-only lexicon (manager, supervisor)
    and the clamped numeric band. Empty string when the title carries no rank
    word. This is a SEPARATE axis: the title canonical (level signature + base
    identity) is untouched. Consumed downstream via ``paths.common.SENIORITY_RANK``."""
    norm = normalize(value)
    toks: list[str] = []
    for t in norm.split():
        toks.extend(_TITLE_ABBREV.get(t, t).split())
    ranks: set[str] = set()
    for t in toks:
        if t in _LEVEL_TOKENS:
            ranks.add(_LEVEL_TOKENS[t])
        elif t in _RANK_ONLY_TOKENS:
            ranks.add(_RANK_ONLY_TOKENS[t])
        elif t in _ROMAN:
            ranks.add(f"lvl{_ROMAN[t]}")
        elif _is_level_digit(t):
            ranks.add(f"lvl{int(t)}")
    return ",".join(sorted(ranks))


def title_display_base(value: str | None) -> str:
    """Human-readable base of a title: original token order (NOT the sorted
    signature), abbreviations expanded, level tokens stripped, title-cased.
    The fallback for ``role_display`` when no level-free raw spelling exists."""
    norm = normalize(value)
    toks: list[str] = []
    for t in norm.split():
        toks.extend(_TITLE_ABBREV.get(t, t).split())
    base = [
        t for t in toks
        if t not in _LEVEL_TOKENS and t not in _ROMAN and not _is_level_digit(t)
    ]
    return " ".join(
        t if t in _DISPLAY_LOWER else t.capitalize() for t in base
    )


def canon_title(vocab: list[tuple]) -> dict:
    mapping: dict[str, str] = {}
    for value, *_ in vocab:
        lvl, base = parse_title(value)
        if not base:
            mapping[value] = f"raw:{normalize(value)}"
        else:
            mapping[value] = f"title:{lvl}|{base}"
    return mapping


# ============================ entry point ================================
def run(field_name: str, vocab: list[tuple]) -> Result:
    with timer() as t:
        if field_name == "company":
            mapping = canon_company(vocab)
        elif field_name == "title":
            mapping = canon_title(vocab)
        else:
            raise ValueError(field_name)
    total = sum(f for _v, f, *_ in vocab)
    if field_name == "company":
        # reference coverage = rows mapped to a company_id (excludes nonorg/raw)
        matched = sum(f for v, f, *_ in vocab if mapping[v].startswith("id:"))
    else:
        # "structured" coverage = rows that parsed to a title:level|base id
        matched = sum(f for v, f, *_ in vocab if mapping[v].startswith("title:"))
    return Result(
        name="A_rules",
        field=field_name,
        mapping=mapping,
        runtime_s=t.elapsed,
        extra={"reference_match_row_pct": round(100 * matched / total, 1)},
    )
