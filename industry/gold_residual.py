"""Residual gold set -- the missing calibration asset (LLM_JUDGE_JURY_REPORT §5).

The 30-company ``gold.py`` set is dominated by the curated head the DETERMINISTIC
stack already nails; it says almost nothing about the population the LLM layer
actually labels. This file is a hand-labeled gold set drawn from the LLM's real
target population -- the no-id-token brands, conglomerate divisions, and
description-only companies -- so we can finally measure LLM/jury accuracy where it
operates, map self-reported confidence / jury agreement onto observed precision,
and apply the Alternative Annotator Test before any proposal auto-applies.

Construction (deliberate, to keep calibration honest):
  * Each ``key`` is the EXACT ``company_canonical_id`` that already appears in the
    frozen ``llm_proposals.jsonl`` cache, so ``run_industry.llm_calibration`` joins
    to real proposals OFFLINE -- no API call needed to get first numbers, and the
    5,000 unvalidated Haiku proposals finally get a ground-truth check.
  * ``expected`` is the ground-truth code, determined INDEPENDENTLY of what the
    model said (never copied from the cached code), at the depth I can defend.
  * It includes deliberate MODEL-ERROR cases (Stripe is payments, not e-commerce;
    Sigma-Aldrich is lab chemicals, not personal care) so calibration precision is
    not trivially 1.0 -- the whole point is to see the bands miscalibrate.

Extend this set by sampling the production residual: ``fire_llm sample-gold``
writes a stratified labeling worksheet from the real vocab (see fire_llm.py).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldResidual:
    key: str        # EXACT company_canonical_id (matches the cache + the vocab)
    display: str
    expected: str   # ground truth, hand-labeled independently of the model
    note: str = ""


# ~55 hand-labeled companies spanning every L1, keyed to real cache entries.
# "expected" is set only as deep as is genuinely unambiguous.
GOLD_RESIDUAL: list[GoldResidual] = [
    # --- deliberate L1 MISS cases (model wrong; keeps calibration honest) ---
    GoldResidual("id:stripe", "Stripe", "FIN.FINT.PAY",
                 "payments/fintech; cache says TEC e-commerce -> L1 miss"),
    GoldResidual("id:sigma-aldrich", "Sigma-Aldrich", "MFG.CHEM",
                 "lab/specialty chemicals (MilliporeSigma); cache says CON.CPG.HPC -> L1 miss"),
    # --- Technology ---
    GoldResidual("id:intuit", "Intuit", "TEC.SOF.APP.SAAS"),
    GoldResidual("id:sage-software", "Sage", "TEC.SOF.APP.SAAS"),
    GoldResidual("id:sogeti", "Sogeti", "TEC.SOF.ITSV"),
    GoldResidual("id:vonage", "Vonage", "TEC", "cloud comms; TEC at L1, TEC.SOF vs TEC.TELE arguable"),
    # --- Finance ---
    GoldResidual("id:keycorp", "KeyCorp", "FIN.BNK.COM"),
    GoldResidual("id:hancockwhitney", "Hancock Whitney", "FIN.BNK.COM"),
    GoldResidual("id:janney-montgomery-scott", "Janney Montgomery Scott", "FIN.BNK.INV"),
    GoldResidual("id:bernstein-private-wealth-management", "Bernstein Private Wealth", "FIN.ASM.WM"),
    GoldResidual("id:london-stock-exchange-group", "London Stock Exchange Group", "FIN.BNK.INV"),
    # --- Healthcare / Pharma ---
    GoldResidual("id:modernatx", "Moderna", "HLT.PHRM.BIO"),
    GoldResidual("id:seagen", "Seagen", "HLT.PHRM.BIO"),
    GoldResidual("id:astrazeneca", "AstraZeneca", "HLT.PHRM.PHARMA"),
    GoldResidual("id:merck-group", "Merck", "HLT.PHRM.PHARMA"),
    GoldResidual("id:iehp", "Inland Empire Health Plan", "HLT.PAYR"),
    GoldResidual("id:good-samaritan-sanford-health", "Good Samaritan Society", "HLT.PROV.LTC"),
    GoldResidual("id:genedx", "GeneDx", "HLT", "genetic diagnostics; L1 confident, L2 arguable"),
    # --- Education ---
    GoldResidual("id:national-heritage-academies", "National Heritage Academies", "EDU.K12"),
    GoldResidual("id:citycollegeschicago", "City Colleges of Chicago", "EDU.HED.CC"),
    GoldResidual("raw:hobart and william smith colleges", "Hobart and William Smith Colleges", "EDU.HED.UNIV"),
    # --- Public sector ---
    GoldResidual("id:state-of-new-jersey", "State of New Jersey", "PUB.GOV.SLOC"),
    GoldResidual("id:orange-county-government", "Orange County Government", "PUB.GOV.SLOC"),
    GoldResidual("id:los-angeles-superior-court", "Los Angeles Superior Court", "PUB.JUST"),
    GoldResidual("id:defense-intelligence-agency", "Defense Intelligence Agency", "PUB.DEF"),
    # --- Manufacturing / Industrials ---
    GoldResidual("id:tesla-motors", "Tesla", "MFG.AUTO.OEM"),
    GoldResidual("id:swagelok", "Swagelok", "MFG.IND"),
    GoldResidual("id:briggs-&-stratton", "Briggs & Stratton", "MFG.IND.MACH"),
    GoldResidual("id:stanley-black-decker-inc", "Stanley Black & Decker", "MFG"),
    GoldResidual("id:bridgestone", "Bridgestone Americas", "MFG", "tires; L1 confident"),
    GoldResidual("id:cleveland-cliffs", "Cleveland-Cliffs", "MFG.CHEM.MATL", "steel"),
    # --- Consumer & Retail ---
    GoldResidual("id:dollar-general", "Dollar General", "CON.RET.GEN"),
    GoldResidual("id:bed-bath-and-beyond", "Bed Bath & Beyond", "CON.RET.SPEC"),
    GoldResidual("id:vineyard-vines", "Vineyard Vines", "CON.RET.SPEC"),
    GoldResidual("id:the-disney-store", "The Disney Store", "CON.RET.SPEC"),
    GoldResidual("id:fingerhut", "Fingerhut", "CON.RET.ETAIL"),
    GoldResidual("id:edgewell-personal-care", "Edgewell Personal Care", "CON.CPG.HPC"),
    GoldResidual("id:sargento", "Sargento Foods", "CON.CPG.FNB"),
    GoldResidual("id:cocacolaenterprises", "Coca-Cola Enterprises", "CON.CPG.FNB"),
    GoldResidual("id:nestle-waters", "Nestle Waters", "CON.CPG.FNB"),
    # --- Energy ---
    GoldResidual("id:buckeye-partners", "Buckeye Partners", "ENR.OILG"),
    # --- Media & Entertainment ---
    GoldResidual("id:disney-entertainment", "Disney Entertainment (ABC TV)", "MED.BCAST"),
    GoldResidual("id:seattle-mariners", "Seattle Mariners", "MED.SPRT"),
    GoldResidual("id:the-hartford-courant", "The Hartford Courant", "MED.PUBL"),
    GoldResidual("id:crispinagency", "Crispin Porter + Bogusky", "MED.ADV.AGY"),
    # --- Professional Services ---
    GoldResidual("id:dorsey-whitney-llp", "Dorsey & Whitney LLP", "PRO.LEGAL"),
    GoldResidual("id:ey-parthenon", "EY-Parthenon", "PRO.CONSL"),
    GoldResidual("id:right-management", "Right Management", "PRO.HRST"),
    # --- Real Estate ---
    GoldResidual("id:public-storage", "Public Storage", "RE.REST"),
    GoldResidual("id:baird-warner", "Baird & Warner", "RE.REST.RES"),
    GoldResidual("id:the-keyes-company", "The Keyes Company", "RE.REST.RES"),
    # --- Transportation / Hospitality ---
    GoldResidual("id:delta-air-lines", "Delta Air Lines", "TRN.AIR"),
    GoldResidual("id:darden", "Darden Restaurants", "HOS.FOOD"),
    GoldResidual("id:in-n-out-burger", "In-N-Out Burger", "HOS.FOOD"),
    GoldResidual("id:hilton", "Hilton", "HOS.LODG"),
    GoldResidual("id:hyatt-regency", "Hyatt Regency", "HOS.LODG"),
    GoldResidual("id:jw_marriott", "JW Marriott", "HOS.LODG"),
    # --- Nonprofit ---
    GoldResidual("id:jhpiego", "Jhpiego", "NPO.INTD"),
    GoldResidual("id:the-borgen-project", "The Borgen Project", "NPO.ADVO"),
    GoldResidual("id:ymca-of-greater-seattle", "YMCA of Greater Seattle", "NPO.SOCS"),
    GoldResidual("raw:youth villages", "Youth Villages", "NPO.SOCS"),
]


def gold_labels() -> dict[str, str]:
    """``key -> expected code`` for the residual gold (used by calibration)."""
    return {g.key: g.expected for g in GOLD_RESIDUAL}
