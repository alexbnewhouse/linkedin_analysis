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
    ("real estate", "RE.REST"),
    ("credit union", "FIN.BNK.CU"),
    ("law firm", "PRO.LEGAL"),
    ("law offices", "PRO.LEGAL"),
    ("law office", "PRO.LEGAL"),
    ("public schools", "EDU.K12"),
    ("school district", "EDU.K12"),
    ("high school", "EDU.K12"),
    ("elementary school", "EDU.K12"),
    ("middle school", "EDU.K12"),
    ("community college", "EDU.HED.CC"),
    ("medical center", "HLT.PROV.HOSP"),
    ("health system", "HLT.PROV.HOSP"),
    ("home health", "HLT.PROV.LTC"),
    ("home care", "HLT.PROV.LTC"),
    ("nursing home", "HLT.PROV.LTC"),
    ("assisted living", "HLT.PROV.LTC"),
    ("dental care", "HLT.PROV.DENT"),
    ("animal hospital", "HLT.PROV"),
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
    ("oil & gas", "ENR.OILG"),
    ("heating and cooling", "RE.CNST.TRADE"),
    ("lawn care", "RE.CNST.TRADE"),
    ("pest control", "PRO.BPO"),
    ("city of", "PUB.GOV.SLOC"),
    ("county of", "PUB.GOV.SLOC"),
    ("department of", "PUB.GOV"),
    ("us department", "PUB.GOV.FED"),
    ("united states army", "PUB.DEF.AF"),
    ("united states navy", "PUB.DEF.AF"),
    ("united states air force", "PUB.DEF.AF"),
    # ---- finance ----
    ("bancorp", "FIN.BNK"),
    ("bancshares", "FIN.BNK"),
    ("bank", "FIN.BNK"),
    ("savings", "FIN.BNK"),
    ("mortgage", "FIN.FINT.LEND"),
    ("capital", "FIN.ASM"),
    ("ventures", "FIN.ASM.PE"),
    ("equity", "FIN.ASM.PE"),
    ("securities", "FIN.BNK.INV"),
    ("financial", "FIN"),
    ("finance", "FIN"),
    ("insurance", "FIN.INS"),
    ("assurance", "FIN.INS"),
    ("payments", "FIN.FINT.PAY"),
    # ---- healthcare ----
    ("hospital", "HLT.PROV.HOSP"),
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
    ("hospice", "HLT.PROV.LTC"),
    # ---- education ----
    ("university", "EDU.HED.UNIV"),
    ("college", "EDU.HED"),
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
    ("fire department", "PUB.JUST"),
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
    ("electric", "RE.CNST.TRADE"),
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
    ("systems", "TEC.SOF.ITSV"),
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
    ("records", "MED.FILM"),
    ("photography", "PRO.DSGN"),
    ("films", "MED.FILM"),
    # ---- energy / utilities / resources ----
    ("petroleum", "ENR.OILG"),
    ("energy", "ENR"),
    ("solar", "ENR.RENW"),
    ("utilities", "ENR.UTIL"),
    ("electric power", "ENR.UTIL.POWR"),
    ("mining", "ENR.MINE"),
    ("drilling", "ENR.OILG.UPST"),
    # ---- manufacturing / industrials ----
    ("manufacturing", "MFG"),
    ("industries", "MFG.IND"),
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
    ("farm", "AGR.FARM"),
    ("agriculture", "AGR"),
    ("agricultural", "AGR"),
    ("ranch", "AGR.LIVE"),
    ("dairy", "AGR.LIVE"),
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
    ("motors", "CON.RET.SPEC"),
    ("dealership", "CON.RET.SPEC"),
    ("grocery", "CON.RET.GROC"),
    ("supermarket", "CON.RET.GROC"),
    ("wholesale", "CON.WHL"),
    ("distributors", "CON.WHL"),
    ("distribution", "CON.WHL"),
    ("salon", "PRO.BPO"),  # personal-care storefront; keep cross-cutting & shallow-ish
    ("spa", "HOS.TRVL"),
    ("fitness", "HOS.TRVL"),
    ("gym", "HOS.TRVL"),
]


def validate() -> list[str]:
    """Every rule code must resolve in the taxonomy. Returns offenders."""
    return [f"{kw!r} -> {code}" for kw, code in _RULES if not T.is_valid(code)]


_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(rf"\b{re.escape(kw)}\b"), kw, code) for kw, code in _RULES
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
