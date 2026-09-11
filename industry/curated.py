"""M1 -- the curated company_id -> industry crosswalk (precision-~1.0 backbone).

Hand-reviewed industry for the HEAD company_ids. This is the ratchet table,
analogous to ``career_clean.approach_a_rules.ENTITY_ALIASES``: it is seeded from
the highest-frequency company_ids in the data and extended as the review queue
(and the LLM bootstrap-curator, ``llm.py`` mode 1) proposes more. Because the head
is tiny and dominant (top ~50k ids -> ~54% of all id-bearing rows), a few thousand
curated entries cover a large share of career steps at precision ~= 1.0.

Keys are career_clean canonical company_ids (``company_id_canonical``). Values are
taxonomy node codes at the DEEPEST depth we are confident about (often L3/L4).
Genuinely diversified giants get ``XDV`` rather than a forced single industry --
that is the honest call, not a failure (see Amazon / CVS / GE).
"""

from __future__ import annotations

from . import taxonomy as T

# company_id_canonical -> taxonomy code. Seeded from the top company_ids by row
# frequency; depth chosen by how unambiguous the firm's primary industry is.
CURATED: dict[str, str] = {
    # --- public sector / military ---
    "us-army": "PUB.DEF.AF",
    "us-navy": "PUB.DEF.AF",
    "united-states-air-force": "PUB.DEF.AF",
    "marines": "PUB.DEF.AF",
    "department-of-veterans-affairs": "PUB.GOV.FED",
    "doscareers": "PUB.GOV.FED",
    "u-s-house-of-representatives": "PUB.GOV.FED",
    # --- defense contractors (private) ---
    "lockheed-martin": "PUB.DEF.DCON",
    "northrop-grumman-corporation": "PUB.DEF.DCON",
    # --- banking ---
    "wellsfargo": "FIN.BNK.COM.RET",
    "bank-of-america": "FIN.BNK.COM.RET",
    "us-bank": "FIN.BNK.COM.RET",
    "pnc-bank": "FIN.BNK.COM.RET",
    "capital-one": "FIN.BNK.COM.RET",
    "citi": "FIN.BNK.COM",
    "jpmorganchase": "FIN.BNK.COM",
    "goldman-sachs": "FIN.BNK.INV",
    "morgan-stanley": "FIN.BNK.INV",
    "ubs": "FIN.BNK.INV",
    "merrilllynch": "FIN.ASM.WM",
    "fidelity-investments": "FIN.ASM.AM",
    "american-express": "FIN.FINT.PAY",
    # --- insurance ---
    "state_farm": "FIN.INS.PNC",
    "allstate": "FIN.INS.PNC",
    "liberty-mutual-insurance": "FIN.INS.PNC",
    # --- technology: software / internet ---
    "microsoft": "TEC.SOF",
    "google": "TEC.SOF.INTC.SRCH",
    "meta": "TEC.SOF.INTC.SRCH",
    "oracle": "TEC.SOF.INFR.DATA",
    "amazon-web-services": "TEC.SOF.INFR.CLOU",
    # --- technology: IT services ---
    "ibm": "TEC.SOF.ITSV.INTG",
    "accenture": "TEC.SOF.ITSV.INTG",
    "cognizant": "TEC.SOF.ITSV.INTG",
    "tata-consultancy-services": "TEC.SOF.ITSV.INTG",
    # --- technology: hardware / semis ---
    "apple": "TEC.HRDW.COMP",
    "delltechnologies": "TEC.HRDW.COMP",
    "hewlett-packard-enterprise": "TEC.HRDW.COMP",
    "hp": "TEC.HRDW.COMP",
    "xerox": "TEC.HRDW.COMP",
    "intel-corporation": "TEC.HRDW.SEMI",
    "cisco": "TEC.HRDW.COMM",
    # --- telecom ---
    "att": "TEC.TELE.WIRE",
    "verizon": "TEC.TELE.WIRE",
    "t-mobile": "TEC.TELE.WIRE",
    "sprint": "TEC.TELE.WIRE",
    # --- healthcare ---
    "kaiser-permanente": "HLT.PROV.HOSP",
    "optum": "HLT.PROV",
    "unitedhealth-group": "HLT.PAYR",
    "aetna": "HLT.PAYR",
    "humana": "HLT.PAYR",
    "cignahealthcare": "HLT.PAYR",
    "medtronic": "HLT.MDEV",
    "pfizer": "HLT.PHRM.PHARMA",
    "merck": "HLT.PHRM.PHARMA",
    "gsk": "HLT.PHRM.PHARMA",
    "sanofi": "HLT.PHRM.PHARMA",
    "novartis": "HLT.PHRM.PHARMA",
    "bristol-myers-squibb": "HLT.PHRM.PHARMA",
    "abbott-": "HLT.PHRM.PHARMA",
    "johnson-&-johnson": "HLT.PHRM",
    # --- professional services ---
    "deloitte": "PRO.CONSL",
    "pwc": "PRO.ACCT",
    "ernstandyoung": "PRO.ACCT",
    "kpmg-us": "PRO.ACCT",
    "adp": "PRO.HRST",
    "robert-half-international": "PRO.HRST",
    # --- consumer & retail ---
    "walmart": "CON.RET.GEN",
    "target": "CON.RET.GEN",
    "macy": "CON.RET.GEN",
    "nordstrom": "CON.RET.SPEC",
    "best-buy": "CON.RET.SPEC",
    "the-home-depot": "CON.RET.SPEC",
    "lowe's-home-improvement": "CON.RET.SPEC",
    "walgreens": "CON.RET",
    "nike": "CON.CPG.APPL",
    "pepsico": "CON.CPG.FNB",
    # --- manufacturing / industrials ---
    "boeing": "MFG.AERO",
    "general-motors": "MFG.AUTO.OEM",
    "ford-motor-company": "MFG.AUTO.OEM",
    "honeywell": "MFG.IND",
    "ge": "MFG.IND",
    # --- media & entertainment ---
    "the-walt-disney-company": "MED.FILM",
    "nbcuniversal-inc-": "MED.BCAST",
    "comcast": "MED.BCAST",
    # --- transport & hospitality ---
    "ups": "TRN.LOG",
    "marriott-international": "HOS.LODG",
    "starbucks": "HOS.FOOD",
    "mcdonald's-corporation": "HOS.FOOD",
    # --- review-queue ratchet promotions (human spot-check of jury disagreements) ---
    "booz-allen-hamilton": "PRO.CONSL",   # jury split 3/3 PRO.CONSL vs TEC.SOF.ITSV
    "chobani": "CON.CPG.FNB",             # single tail juror only -> below the gate
    # --- honest "diversified": no single primary industry ---
    "amazon": "XDV",
    "cvshealth": "XDV",
    "berkshire-hathaway": "XDV",  # jury said RE.REST.RES at 0.714 -- evidence is
                                  # contaminated by HomeServices agents on the parent id
}

# Audit 2026-09-02 (red C1): the 2026-07-07 promotion pass labeled some ids by a
# DISPLAY they had inherited from id-less rows (career_clean's modal-id
# inheritance, since gated). Corrections below are keyed on what the id itself
# is; retractions are ids whose own rows are too few or too vague to label.
_CORRECTIONS: dict[str, str] = {
    "ucsdhealth": "HLT.PROV.HOSP",                 # UC San Diego Health, not the university
    "uc-irvine-medical-center": "HLT.PROV.HOSP",   # a hospital, not the university
    "kpn": "TEC.TELE",                              # Dutch telecom; "Wang Laboratories" was inherited
    "kentucky-department-of-education": "PUB.GOV.SLOC",  # a state agency; "Education" was inherited
}
RETRACTED: frozenset[str] = frozenset({
    "consultant_66",      # a "Consultant" placeholder that acquired an id
    "thebeach2",          # labeled from an inherited "Volunteer" display
    "integris-for-banks",  # labeled from inherited "Caltech" rows
    "berkeley-rha",       # labeled from inherited "UC Berkeley" rows
})
CURATED.update(_CORRECTIONS)

# Agreement-gated LLM-curator promotions (see curated_promoted.py for the gate and
# provenance) and the frontier-labeled head (curated_head.py). Precedence on a
# key conflict: hand-curated entries above > HEAD > PROMOTED.
from .curated_head import HEAD  # noqa: E402
from .curated_promoted import PROMOTED  # noqa: E402

_HAND = frozenset(CURATED)
_HEAD = frozenset(HEAD) - _HAND
CURATED = {k: v for k, v in {**PROMOTED, **HEAD, **CURATED}.items() if k not in RETRACTED}

# Per-tier confidence for the deterministic spine: hand entries are reviewed
# one by one; the two machine/frontier tiers carry their measured gate
# precision (promotion: unanimous 1.0 n=24 / majority 0.941 n=34; head: the
# blind second-pass gate), not 1.0.
_TIER_CONFIDENCE = {"hand": 1.0, "head": 0.95, "promoted": 0.95}


def provenance(company_id: str | None) -> str | None:
    """Which tier a landed company_id comes from: 'hand' | 'head' | 'promoted',
    or None when the id is not curated (or retracted)."""
    if not company_id or company_id in RETRACTED:
        return None
    if company_id in _HAND:
        return "hand"
    if company_id in _HEAD:
        return "head"
    if company_id in PROMOTED:
        return "promoted"
    return None


def confidence_of(company_id: str | None) -> float:
    return _TIER_CONFIDENCE.get(provenance(company_id) or "", 0.0)


def is_promoted(company_id: str | None) -> bool:
    """True when the entry comes from the machine-promotion pass rather than a
    hand-curated line."""
    return provenance(company_id) == "promoted"


def validate() -> list[str]:
    """Every curated code must resolve in the frozen taxonomy. Returns offenders."""
    return [f"{cid} -> {code}" for cid, code in CURATED.items() if not T.is_valid(code)]


def lookup(company_id: str | None) -> str | None:
    """Curated industry code for a company_id, or None."""
    if not company_id:
        return None
    return CURATED.get(company_id)
