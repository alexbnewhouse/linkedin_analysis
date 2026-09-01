"""Rec 3 - the functional/industry cluster axis for self-employment steps.

The ultimate goal is to *cluster* the ~459K self-employment career steps into a
small set of functional / industry groups. SOC codes (800+ of them) are too
granular and, worse, the most common self-employment titles ("Designer",
"Consultant", "Owner") are O*NET-AMBIGUOUS and therefore left uncoded by the
deterministic backbone - so SOC alone clusters < 12% of the population.

This module defines the drawable grain: the **functional cluster = SOC major
group** (the 2-digit prefix, e.g. 15 = Computer & Mathematical), which is the
standard, principled coarsening of SOC. It then composes three signal sources
into one cluster per step, precision-first:

    1. an exact/near SOC code (occupation.match)        -> major group   [conf 1.0]
    2. Rec 1 qualifier recovery (se_qualifier)          -> cluster       [conf 0.8]
    3. Rec 2 personal-brand company trade (se_personal_brand) -> cluster [conf 0.6]
    4. otherwise an HONEST terminal residue keyed by employment_type
       (business_owner_unspecified / self_employed_unspecified)         [conf 0.5]

The shared INDUSTRY keyword gazetteer (keyword -> major group) lives here and is
reused by Rec 1 (to cluster an ambiguous title qualifier) and Rec 2 (to read a
trade out of a company brand name). One taxonomy, three consumers.
"""

from __future__ import annotations

import re

from . import occupation as O
from .common import normalize

# SOC major groups -> human label. This IS the cluster taxonomy.
CLUSTER_LABELS: dict[str, str] = {
    "11": "Management",
    "13": "Business & Financial Operations",
    "15": "Computer & Mathematical",
    "17": "Architecture & Engineering",
    "19": "Life, Physical & Social Science",
    "21": "Community & Social Service",
    "23": "Legal",
    "25": "Education, Training & Library",
    "27": "Arts, Design, Entertainment, Sports & Media",
    "29": "Healthcare Practitioners & Technical",
    "31": "Healthcare Support",
    "33": "Protective Service",
    "35": "Food Preparation & Serving",
    "37": "Building & Grounds Cleaning & Maintenance",
    "39": "Personal Care & Service",
    "41": "Sales & Related",
    "43": "Office & Administrative Support",
    "45": "Farming, Fishing & Forestry",
    "47": "Construction & Extraction",
    "49": "Installation, Maintenance & Repair",
    "51": "Production",
    "53": "Transportation & Material Moving",
    "55": "Military Specific",
}

# Ordered (normalized phrase/token -> major group). Order is priority: multiword
# phrases and the more specific signal come first so "digital marketing" reads as
# Business (market research) rather than Computer ("digital"). Word-boundary
# matched against a normalized string. Curated and high-precision: industry words
# only -- generic shell words (owner/founder/consultant) are deliberately absent.
_KEYWORD_RULES: list[tuple[str, str]] = [
    # --- multiword phrases first ---
    ("real estate", "41"),
    ("human resources", "13"),
    ("digital marketing", "13"),
    ("market research", "13"),
    ("social media", "13"),
    ("graphic design", "27"),
    ("interior design", "27"),
    ("web design", "27"),
    ("personal training", "39"),
    ("home health", "31"),
    ("home care", "31"),
    ("mental health", "21"),
    ("pressure washing", "37"),
    ("lawn care", "37"),
    ("auto repair", "49"),
    ("pet grooming", "39"),
    # --- creative / media (27) ---
    ("photography", "27"), ("photographer", "27"), ("videography", "27"),
    ("film", "27"), ("films", "27"), ("productions", "27"), ("media", "27"),
    ("design", "27"), ("designer", "27"), ("graphic", "27"), ("graphics", "27"),
    ("creative", "27"), ("artist", "27"), ("music", "27"), ("musician", "27"),
    ("writing", "27"), ("writer", "27"), ("editor", "27"), ("editorial", "27"),
    ("illustration", "27"), ("illustrator", "27"), ("animation", "27"),
    ("publishing", "27"), ("journalism", "27"),
    # --- business / financial (13) ---
    ("accounting", "13"), ("bookkeeping", "13"), ("tax", "13"), ("taxes", "13"),
    ("financial", "13"), ("finance", "13"), ("insurance", "13"),
    ("marketing", "13"), ("advertising", "13"), ("recruiting", "13"),
    ("recruitment", "13"), ("staffing", "13"), ("hr", "13"),
    # --- management / operations (11) ---
    ("management", "11"), ("operations", "11"),
    # --- computer / tech (15) ---
    ("it", "15"), ("ict", "15"), ("software", "15"), ("web", "15"),
    ("technology", "15"), ("tech", "15"), ("computer", "15"), ("cyber", "15"),
    ("cybersecurity", "15"), ("data", "15"), ("digital", "15"),
    ("network", "15"), ("networking", "15"), ("saas", "15"), ("cloud", "15"),
    ("app", "15"),
    # --- legal (23) ---
    ("law", "23"), ("legal", "23"), ("attorney", "23"), ("lawyer", "23"),
    ("paralegal", "23"), ("litigation", "23"),
    # --- education (25) ---
    ("tutoring", "25"), ("tutor", "25"), ("teaching", "25"), ("academy", "25"),
    ("education", "25"), ("educational", "25"),
    # --- food (35) ---
    ("restaurant", "35"), ("catering", "35"), ("cafe", "35"), ("bakery", "35"),
    ("culinary", "35"), ("chef", "35"), ("brewery", "35"), ("coffee", "35"),
    # --- personal care (39) ---
    ("salon", "39"), ("spa", "39"), ("beauty", "39"), ("barber", "39"),
    ("barbershop", "39"), ("cosmetology", "39"), ("esthetics", "39"),
    ("fitness", "39"), ("yoga", "39"), ("pilates", "39"), ("wellness", "39"),
    ("massage", "39"), ("grooming", "39"),
    # --- construction (47) ---
    ("construction", "47"), ("contracting", "47"), ("builders", "47"),
    ("roofing", "47"), ("plumbing", "47"), ("electrical", "47"),
    ("landscaping", "47"), ("landscape", "47"), ("remodeling", "47"),
    ("carpentry", "47"), ("masonry", "47"), ("concrete", "47"),
    ("flooring", "47"), ("drywall", "47"), ("excavation", "47"),
    ("paving", "47"), ("fencing", "47"), ("welding", "47"),
    # --- installation / repair (49) ---
    ("hvac", "49"), ("automotive", "49"), ("mechanic", "49"),
    ("appliance", "49"),
    # --- production (51) ---
    ("manufacturing", "51"), ("fabrication", "51"), ("woodworking", "51"),
    ("machining", "51"), ("upholstery", "51"), ("tailoring", "51"),
    # --- transportation (53) ---
    ("trucking", "53"), ("transportation", "53"), ("logistics", "53"),
    ("freight", "53"), ("hauling", "53"), ("towing", "53"), ("courier", "53"),
    # --- farming (45) ---
    ("farm", "45"), ("farming", "45"), ("agriculture", "45"),
    ("agricultural", "45"), ("ranch", "45"), ("dairy", "45"),
    ("vineyard", "45"), ("orchard", "45"),
    # --- healthcare (29 practitioners / 31 support) ---
    ("dental", "29"), ("dentistry", "29"), ("chiropractic", "29"),
    ("nursing", "29"), ("pharmacy", "29"), ("veterinary", "29"),
    ("medical", "29"), ("clinic", "29"), ("orthodontic", "29"),
    ("caregiver", "31"), ("caregiving", "31"), ("homecare", "31"),
    # --- community / social (21) ---
    ("counseling", "21"), ("therapy", "21"), ("ministry", "21"),
    ("nonprofit", "21"), ("outreach", "21"),
    # --- sales / retail (41) ---
    ("realty", "41"), ("realtor", "41"), ("brokerage", "41"),
    ("retail", "41"), ("ecommerce", "41"), ("boutique", "41"),
    # --- building / grounds (37) ---
    ("cleaning", "37"), ("janitorial", "37"), ("housekeeping", "37"),
]

INDUSTRY_KEYWORDS: dict[str, str] = {k: v for k, v in _KEYWORD_RULES}

# Precompiled word-boundary patterns, in priority order.
_KEYWORD_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(rf"\b{re.escape(kw)}\b"), kw, cl) for kw, cl in _KEYWORD_RULES
]


def major_group(soc: str | None) -> str:
    """'15-1252' or 'soc:15-1252' -> '15'. Empty for missing/garbage."""
    if not soc:
        return ""
    s = soc[4:] if soc.startswith("soc:") else soc
    return s[:2] if len(s) >= 2 and s[:2].isdigit() else ""


def cluster_label(code: str | None) -> str:
    return CLUSTER_LABELS.get(code or "", "")


def keyword_cluster(text: str | None) -> tuple[str | None, str | None]:
    """Scan text for the highest-priority industry keyword. Returns
    (major_group, matched_keyword) or (None, None)."""
    norm = normalize(text)
    if not norm:
        return None, None
    for pat, kw, cl in _KEYWORD_PATTERNS:
        if pat.search(norm):
            return cl, kw
    return None, None


def keyword_hits(text: str | None, *, exclude: frozenset[str] = frozenset()) -> list[tuple[str, str]]:
    """All gazetteer matches in priority order as (keyword, major_group),
    optionally skipping an ``exclude`` set of keywords. Used by description
    inference to vote across clusters."""
    norm = normalize(text)
    if not norm:
        return []
    out = []
    for pat, kw, cl in _KEYWORD_PATTERNS:
        if kw in exclude:
            continue
        if pat.search(norm):
            out.append((kw, cl))
    return out


def ordered_keyword(
    text: str | None, *, exclude: frozenset[str] = frozenset()
) -> tuple[str | None, str | None]:
    """First (highest-priority) gazetteer match, skipping ``exclude``. Returns
    (major_group, keyword)."""
    for kw, cl in keyword_hits(text, exclude=exclude):
        return cl, kw
    return None, None


def resolve_functional_cluster(
    *,
    company: str | None,
    title: str | None,
    by_norm: dict,
    by_tokens: dict,
    company_id: str | None = None,
    employment_type: str | None = None,
    soc_code: str | None = None,
    description: str | None = None,
) -> tuple[str, str, float]:
    """Compose SOC -> Rec1 qualifier -> Rec2 company brand -> honest residue.

    Returns (cluster, method, confidence). ``cluster`` is a 2-digit major group
    for a real functional signal, or a ``*_unspecified`` terminal bucket when the
    step genuinely carries none (the honest residue, not silently dropped)."""
    from . import se_description as D  # local imports avoid an import cycle
    from . import se_personal_brand as PB
    from . import se_qualifier as Q

    # 1. exact/near SOC backbone (precision 1.0). Major group 55 (Military) is a
    # noise hit on this population (no self-employed military), so it is not a
    # real cluster -- fall through.
    if soc_code is None:
        code, _m = O.match(title or "", by_norm, by_tokens)
    else:
        code = soc_code
    cl = major_group(code)
    if cl and cl != "55":
        return cl, "soc", 1.0

    # 2. Rec 1: qualifier-aware recovery from the title
    q_cl, _soc, _qm, _qc = Q.recover_cluster(title or "", by_norm, by_tokens)
    if q_cl:
        return q_cl, "qualifier", 0.8

    # 2b. bare ambiguous occupation noun (no shell marker, so Rec 1 abstains):
    # the title itself names an industry the gazetteer knows ("Artist",
    # "Photographer", "Caregiver"). Safe here because this rollup is only ever
    # called on the self-employment population.
    t_cl, _tkw = keyword_cluster(title)
    if t_cl:
        return t_cl, "title_keyword", 0.7

    # 3. Rec 2: personal-brand company-name trade. Only for the NO-ID tail: a
    # real company_id means LinkedIn recognized a genuine employer (franchise /
    # MLM like Anytime Fitness, Pampered Chef), not a personal brand -- guessing
    # a trade from its name is unsafe, and its industry belongs to a future
    # company_id->industry crosswalk (see INDUSTRY_PLAN), not this rec.
    if not company_id:
        b_cl, _trade, _bm, _bc = PB.parse_brand(company)
        if b_cl:
            return b_cl, "company_brand", 0.6

    # 3b. Rec 4: infer the trade from the free-text description (propose-only).
    if description:
        d_cl, _dm, d_conf, _ev = D.infer_cluster(description)
        if d_cl:
            return d_cl, "description", d_conf

    # 4. honest terminal residue
    et = employment_type or "self_employed"
    if et in ("business_owner", "self_employed"):
        return f"{et}_unspecified", "unspecified", 0.5
    return "unspecified", "unspecified", 0.5
