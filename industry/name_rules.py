"""M3 -- deterministic company-name lexical rules (covers the no-id tail).

Many company names *are* their industry ("First National Bank", "St. Mary's
Hospital", "Smith & Sons Plumbing"). This module resolves a large share of the
~2.1M no-id name tail that the company_id crosswalk (M1) structurally cannot
reach, typically to L2/L3.

Precision-first, exactly like the O*NET coder and the se_cluster gazetteer: fire
only on UNAMBIGUOUS tokens (drop any token that maps to multiple sectors), match
on word boundaries against the normalized name, multiword phrases first. Curated
and extensible -- new tokens enter via the review-queue ratchet, not a model.
"""

from __future__ import annotations

import re

from career_clean.common import normalize

from . import taxonomy as T

# (normalized phrase/token -> taxonomy code). ORDER IS PRIORITY: multiword and
# more-specific phrases first so "real estate" wins before "estate", "credit
# union" before "credit". Only industry-bearing tokens -- generic corporate words
# (group, holdings, inc, llc, solutions, services, global, international) are
# deliberately absent because they span every sector.
_RULES: list[tuple[str, str]] = [
    # ---- multiword phrases (highest precision) ----
    # A leading "^" anchors the phrase to the START of the normalized name
    # (audit 2026-09-02 red C2: "Columbia University in the City of New York"
    # and "Museum of the City of New York" are not municipalities).
    ("medical center", "HLT.PROV.HOSP"),
    ("health system", "HLT.PROV.HOSP"),
    ("city of hope", "HLT.PROV.HOSP"),
    ("health plan", "HLT.PAYR"),
    ("health insurance", "HLT.PAYR"),
    ("blood bank", "HLT.PROV"),
    ("nursing homes", "HLT.PROV.LTC"),
    ("nursing home", "HLT.PROV.LTC"),
    ("home health", "HLT.PROV.LTC"),
    ("home care", "HLT.PROV.LTC"),
    ("assisted living", "HLT.PROV.LTC"),
    ("dental care", "HLT.PROV.DENT"),
    ("animal hospital", "HLT.PROV"),
    # graduate / professional schools are higher education, not K-12 or clinics
    ("school of medicine", "EDU.HED"),
    ("medical school", "EDU.HED"),
    ("medical university", "EDU.HED.UNIV"),
    ("medical college", "EDU.HED"),
    ("medical campus", "EDU.HED"),
    ("business school", "EDU.HED"),
    ("school of business", "EDU.HED"),
    ("school of management", "EDU.HED"),
    ("law school", "EDU.HED"),
    ("school of law", "EDU.HED"),
    ("school of nursing", "EDU.HED"),
    ("school of public health", "EDU.HED"),
    ("school of engineering", "EDU.HED"),
    ("graduate school", "EDU.HED"),
    ("community college", "EDU.HED.CC"),
    ("naval academy", "EDU.HED"),
    ("military academy", "EDU.HED"),
    ("air force academy", "EDU.HED"),
    ("coast guard academy", "EDU.HED"),
    ("police academy", "PUB.JUST"),
    ("academy sports", "CON.RET.SPEC"),
    ("public schools", "EDU.K12"),
    ("school district", "EDU.K12"),
    ("high school", "EDU.K12"),
    ("elementary school", "EDU.K12"),
    ("middle school", "EDU.K12"),
    ("real estate", "RE.REST"),
    ("credit union", "FIN.BNK.CU"),
    ("food bank", "NPO.SOCS"),
    ("goodwill", "NPO.SOCS"),
    ("state farm", "FIN.INS"),
    ("farm bureau", "FIN.INS"),
    ("farm credit", "FIN.BNK"),
    ("capital management", "FIN.ASM"),
    ("capital partners", "FIN.ASM.PE"),
    ("capital markets", "FIN.BNK.INV"),
    ("capital group", "FIN.ASM"),
    ("capital advisors", "FIN.ASM.WM"),
    ("law firm", "PRO.LEGAL"),
    ("law offices", "PRO.LEGAL"),
    ("law office", "PRO.LEGAL"),
    ("auto repair", "TRN"),  # ambiguous between repair shop and dealer -> keep shallow
    ("auto group", "CON.RET.SPEC"),
    ("property management", "RE.REST.PM"),
    ("staffing solutions", "PRO.HRST"),
    ("staffing agency", "PRO.HRST"),
    ("digital marketing", "MED.ADV.MKTG"),
    ("marketing agency", "MED.ADV.AGY"),
    ("advertising agency", "MED.ADV.AGY"),
    ("public relations", "MED.ADV.MKTG"),
    ("interior design", "PRO.DSGN"),
    ("graphic design", "PRO.DSGN"),
    ("web design", "TEC.SOF"),
    ("software solutions", "TEC.SOF"),
    ("oil and gas", "ENR.OILG"),
    # electric utilities (audit C2: bare "electric" sent PG&E, Schneider,
    # Westinghouse and AEP to construction trades; the token is retired)
    ("electric power", "ENR.UTIL.POWR"),
    ("electric company", "ENR.UTIL.POWR"),
    ("electric cooperative", "ENR.UTIL.POWR"),
    ("electric coop", "ENR.UTIL.POWR"),
    ("electric utility", "ENR.UTIL.POWR"),
    ("gas and electric", "ENR.UTIL"),
    ("electric and gas", "ENR.UTIL"),
    ("power and light", "ENR.UTIL.POWR"),
    ("power company", "ENR.UTIL.POWR"),
    ("heating and cooling", "RE.CNST.TRADE"),
    ("lawn care", "RE.CNST.TRADE"),
    ("pest control", "PRO.BPO"),
    # government (specific before generic)
    ("department of defense", "PUB.DEF"),
    ("national science foundation", "PUB.GOV.FED"),
    ("transportation security administration", "PUB.GOV.FED"),
    ("us department", "PUB.GOV.FED"),
    ("united states army", "PUB.DEF.AF"),
    ("united states navy", "PUB.DEF.AF"),
    ("united states air force", "PUB.DEF.AF"),
    ("fire department", "PUB.JUST"),
    # ---- institution tokens that must beat generic tokens below ----
    ("hospital", "HLT.PROV.HOSP"),
    ("hospice", "HLT.PROV.LTC"),
    ("university", "EDU.HED.UNIV"),
    ("college", "EDU.HED"),
    ("^city of", "PUB.GOV.SLOC"),
    ("^county of", "PUB.GOV.SLOC"),
    ("department of", "PUB.GOV"),
    # ---- finance ----
    ("bancorp", "FIN.BNK"),
    ("bancshares", "FIN.BNK"),
    ("bank", "FIN.BNK"),
    ("savings", "FIN.BNK"),
    ("mortgage", "FIN.FINT.LEND"),
    ("securities", "FIN.BNK.INV"),
    ("financial", "FIN"),
    ("finance", "FIN"),
    ("insurance", "FIN.INS"),
    ("assurance", "FIN.INS"),
    ("payments", "FIN.FINT.PAY"),
    # ---- healthcare ----
    ("healthcare", "HLT.PROV"),
    ("health", "HLT.PROV"),
    ("clinic", "HLT.PROV.AMB"),
    ("medical", "HLT.PROV.AMB"),
    ("dental", "HLT.PROV.DENT"),
    ("dentistry", "HLT.PROV.DENT"),
    ("orthodontics", "HLT.PROV.DENT"),
    ("pharmacy", "HLT.PROV"),
    ("pharmaceutical", "HLT.PHRM.PHARMA"),
    ("pharmaceuticals", "HLT.PHRM.PHARMA"),
    ("biotech", "HLT.PHRM.BIO"),
    ("therapeutics", "HLT.PHRM.PHARMA"),
    ("veterinary", "HLT.PROV"),
    # ---- education ----
    ("academy", "EDU.K12"),
    ("schools", "EDU.K12"),
    ("school", "EDU.K12"),
    ("isd", "EDU.K12"),
    ("montessori", "EDU.K12"),
    ("daycare", "EDU"),
    ("preschool", "EDU.K12"),
    ("tutoring", "EDU.TRNG"),
    # ---- public sector ----
    ("municipality", "PUB.GOV.SLOC"),
    ("township", "PUB.GOV.SLOC"),
    ("police", "PUB.JUST"),
    ("sheriff", "PUB.JUST"),
    # ---- real estate / construction ----
    ("realty", "RE.REST.RES"),
    ("realtors", "RE.REST.RES"),
    ("properties", "RE.REST"),
    ("homes", "RE.CNST.BLDG"),
    ("construction", "RE.CNST"),
    ("builders", "RE.CNST.BLDG"),
    ("contractors", "RE.CNST.TRADE"),
    ("contracting", "RE.CNST.TRADE"),
    ("roofing", "RE.CNST.TRADE"),
    ("plumbing", "RE.CNST.TRADE"),
    ("electrical", "RE.CNST.TRADE"),
    ("hvac", "RE.CNST.TRADE"),
    ("landscaping", "RE.CNST.TRADE"),
    ("remodeling", "RE.CNST.TRADE"),
    ("excavation", "RE.CNST.INFC"),
    ("paving", "RE.CNST.INFC"),
    ("concrete", "RE.CNST.TRADE"),
    ("architects", "RE.ARCH"),
    ("architecture", "RE.ARCH"),
    # ---- professional services ----
    ("consulting", "PRO.CONSL"),
    ("consultants", "PRO.CONSL"),
    ("advisors", "FIN.ASM.WM"),
    ("attorneys", "PRO.LEGAL"),
    ("attorney", "PRO.LEGAL"),
    ("legal", "PRO.LEGAL"),
    ("accounting", "PRO.ACCT"),
    ("cpa", "PRO.ACCT"),
    ("cpas", "PRO.ACCT"),
    ("bookkeeping", "PRO.ACCT"),
    ("engineering", "PRO.ENGS"),
    ("engineers", "PRO.ENGS"),
    ("staffing", "PRO.HRST"),
    ("recruiting", "PRO.HRST"),
    ("recruitment", "PRO.HRST"),
    # ---- technology ----
    ("software", "TEC.SOF"),
    ("technologies", "TEC"),
    ("technology", "TEC"),
    ("cybersecurity", "TEC.SOF.INFR.SEC"),
    ("semiconductor", "TEC.HRDW.SEMI"),
    ("robotics", "TEC.HRDW"),
    ("telecom", "TEC.TELE"),
    ("telecommunications", "TEC.TELE"),
    ("wireless", "TEC.TELE.WIRE"),
    # ---- media / advertising ----
    ("advertising", "MED.ADV.AGY"),
    ("marketing", "MED.ADV.MKTG"),
    ("media", "MED"),
    ("studios", "MED.FILM"),
    ("productions", "MED.FILM"),
    ("publishing", "MED.PUBL"),
    ("photography", "PRO.DSGN"),
    ("films", "MED.FILM"),
    # ---- energy / utilities / resources ----
    ("petroleum", "ENR.OILG"),
    ("energy", "ENR"),
    ("solar", "ENR.RENW"),
    ("utilities", "ENR.UTIL"),
    ("mining", "ENR.MINE"),
    ("drilling", "ENR.OILG.UPST"),
    # ---- manufacturing / industrials ----
    ("manufacturing", "MFG"),
    ("steel", "MFG.CHEM.MATL"),
    ("plastics", "MFG.CHEM.MATL"),
    ("chemical", "MFG.CHEM"),
    ("chemicals", "MFG.CHEM"),
    ("aerospace", "MFG.AERO"),
    ("automotive", "MFG.AUTO"),
    ("fabrication", "MFG.IND"),
    ("machine", "MFG.IND.MACH"),
    ("machining", "MFG.IND.MACH"),
    # ---- transport / logistics ----
    ("logistics", "TRN.LOG"),
    ("freight", "TRN.LOG"),
    ("trucking", "TRN.TRUCK"),
    ("transport", "TRN"),
    ("transportation", "TRN"),
    ("airlines", "TRN.AIR"),
    ("aviation", "TRN.AIR"),
    ("shipping", "TRN.MAR"),
    ("railroad", "TRN.RAIL"),
    # ---- hospitality / food / travel ----
    ("restaurant", "HOS.FOOD"),
    ("restaurants", "HOS.FOOD"),
    ("grill", "HOS.FOOD"),
    ("cafe", "HOS.FOOD"),
    ("catering", "HOS.EVNT"),
    ("bakery", "HOS.FOOD"),
    ("brewing", "CON.CPG.FNB"),
    ("brewery", "CON.CPG.FNB"),
    ("hotel", "HOS.LODG"),
    ("hotels", "HOS.LODG"),
    ("resort", "HOS.LODG"),
    ("travel", "HOS.TRVL"),
    ("tours", "HOS.TRVL"),
    # ---- agriculture ----
    ("farms", "AGR.FARM"),
    ("agriculture", "AGR"),
    ("agricultural", "AGR"),
    ("ranch", "AGR.LIVE"),
    ("vineyards", "AGR.FARM"),
    ("orchards", "AGR.FARM"),
    ("nursery", "AGR.AGSV"),
    # ---- nonprofit / social ----
    ("foundation", "NPO.PHIL"),
    ("nonprofit", "NPO"),
    ("ministries", "NPO.RELG"),
    ("ministry", "NPO.RELG"),
    ("church", "NPO.RELG"),
    ("diocese", "NPO.RELG"),
    ("synagogue", "NPO.RELG"),
    ("charities", "NPO.SOCS"),
    ("charity", "NPO.SOCS"),
    # ---- retail / consumer ----
    ("realtor", "RE.REST.RES"),
    ("boutique", "CON.RET.SPEC"),
    ("jewelers", "CON.RET.SPEC"),
    ("dealership", "CON.RET.SPEC"),
    ("grocery", "CON.RET.GROC"),
    ("supermarket", "CON.RET.GROC"),
    ("wholesale", "CON.WHL"),
    ("distributors", "CON.WHL"),
    ("distribution", "CON.WHL"),
    ("spa", "HOS.TRVL"),
    ("fitness", "HOS.TRVL"),
    ("gym", "HOS.TRVL"),
]

# Retired tokens (audit 2026-09-02, red C2). Each was measured on
# company_industry.matched and fired mostly on the wrong sector; the named
# companies below are curated-tier material (they carry company_ids), not rule
# material. Do not re-add a bare token without a negative fixture in tests.py.
#   electric   -> PG&E, Schneider, Westinghouse, AEP (utilities/manufacturers)
#   farm       -> State Farm, Perdue, Pepperidge Farm, Knott's Berry Farm
#   dairy      -> Dairy Queen
#   motors     -> Lucid, Kia, Peterbilt, Tata (OEMs, not dealerships)
#   ventures   -> Red Ventures, Pepsi Bottling Ventures, "X Ventures LLC"
#   equity     -> Equity Residential (REIT), Actors' Equity (union)
#   records    -> National Archives and Records Administration
#   industries -> Goodwill (nonprofit), ABM (services), Medline (distribution)
#   systems    -> BAE Systems, GD Mission Systems (defense), Apex (staffing)
#   salon      -> mapped to business-process outsourcing (nonsense)
#   capital    -> Capital University, Capital Health, Capital One (bank)
#   oil & gas  -> unreachable: the normalizer rewrites "&" as "and"


def validate() -> list[str]:
    """Every rule code must resolve in the taxonomy. Returns offenders."""
    return [f"{kw!r} -> {code}" for kw, code in _RULES if not T.is_valid(code)]


def _compile(kw: str) -> re.Pattern:
    """Word-boundary phrase match; a leading "^" anchors to the name start."""
    if kw.startswith("^"):
        return re.compile(rf"^{re.escape(kw[1:])}\b")
    return re.compile(rf"\b{re.escape(kw)}\b")


_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (_compile(kw), kw, code) for kw, code in _RULES
]


def match(name: str | None) -> tuple[str | None, str | None]:
    """Return (taxonomy_code, matched_keyword) for the highest-priority rule that
    fires on the normalized company name, or (None, None)."""
    norm = normalize(name)
    if not norm:
        return None, None
    for pat, kw, code in _PATTERNS:
        if pat.search(norm):
            return code, kw
    return None, None
