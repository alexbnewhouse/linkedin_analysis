"""M4/M5 -- occupation (SOC) -> industry prior (weak, propose-only).

For rows with no usable employer (self-employed / freelance, the ``nonorg:``
population) the industry must come from the OCCUPATION, not the company line: an
independent nurse -> Healthcare, a freelance petroleum engineer -> Energy. And at
the company grain, when a company is otherwise unresolved but nearly all of its
people share one strongly industry-bound occupation, that is a weak hint.

CRITICAL precision rule: most occupations are INDUSTRY-AGNOSTIC -- a Software
Engineer, Accountant, Project Manager, or Sales Rep works in every sector -- so
those major groups ABSTAIN here. We only fire for the major groups (and a few
specific SOCs) that are genuinely bound to one industry, and always at low
confidence / shallow depth (L1-L2). This is a tiebreaker, never a decider on its
own (INDUSTRY_PLAN §M5).
"""

from __future__ import annotations

# SOC major group (2-digit) -> (industry code, confidence). Only industry-BOUND
# groups appear; agnostic groups (11 Management, 13 Business, 15 Computer,
# 17 Architecture/Eng, 19 Science, 41 Sales, 43 Admin, 49 Repair) are absent =>
# abstain. Depth is deliberately shallow (L1/L2).
_MAJOR_TO_INDUSTRY: dict[str, tuple[str, float]] = {
    "21": ("NPO.SOCS", 0.3),     # Community & Social Service
    "23": ("PRO.LEGAL", 0.45),   # Legal
    "25": ("EDU", 0.5),          # Education, Training & Library
    "27": ("MED", 0.3),          # Arts/Design/Media (weak: designers span sectors)
    "29": ("HLT.PROV", 0.5),     # Healthcare Practitioners
    "31": ("HLT.PROV", 0.5),     # Healthcare Support
    "33": ("PUB.JUST", 0.3),     # Protective Service (weak: private security too)
    "35": ("HOS.FOOD", 0.5),     # Food Preparation & Serving
    "45": ("AGR", 0.5),          # Farming, Fishing & Forestry
    "47": ("RE.CNST", 0.45),     # Construction & Extraction
    "51": ("MFG", 0.4),          # Production
    "53": ("TRN", 0.4),          # Transportation & Material Moving
    "55": ("PUB.DEF.AF", 0.5),   # Military
}

# A few specific 6-digit SOCs whose industry is sharper than their major group.
_SOC_OVERRIDE: dict[str, tuple[str, float]] = {
    "29-1141": ("HLT.PROV", 0.6),   # Registered Nurses
    "25-2021": ("EDU.K12", 0.6),    # Elementary School Teachers
    "25-2031": ("EDU.K12", 0.6),    # Secondary School Teachers
    "25-1099": ("EDU.HED", 0.55),   # Postsecondary Teachers
    "19-2041": ("NPO.RSCH", 0.3),   # Environmental Scientists (weak)
}


def _major(soc: str) -> str:
    s = soc[4:] if soc.startswith("soc:") else soc
    return s[:2] if len(s) >= 2 and s[:2].isdigit() else ""


def soc_to_industry(soc_code: str | None) -> tuple[str | None, float]:
    """Industry prior for an O*NET-SOC code (e.g. '29-1141' or 'soc:29-1141').
    Returns (code, confidence) or (None, 0.0) when the occupation is
    industry-agnostic or unknown."""
    if not soc_code:
        return None, 0.0
    s = soc_code[4:] if soc_code.startswith("soc:") else soc_code
    if s in _SOC_OVERRIDE:
        return _SOC_OVERRIDE[s]
    hit = _MAJOR_TO_INDUSTRY.get(_major(s))
    return hit if hit else (None, 0.0)


# Company-grain: a weak prior only when the workforce is overwhelmingly one
# industry-bound occupation. Requires a high coded fraction so we don't infer an
# industry from a thin, unrepresentative tail of coded titles.
MIN_OCC_CODED_FRAC = 0.5


def company_occupation_prior(
    modal_occ: str | None, occ_coded_frac: float | None
) -> tuple[str | None, float]:
    if not modal_occ or (occ_coded_frac or 0.0) < MIN_OCC_CODED_FRAC:
        return None, 0.0
    code, conf = soc_to_industry(modal_occ)
    # company-grain modal occupation is a slightly weaker signal than a person's
    # own occupation -> shave the confidence.
    return (code, round(conf * 0.8, 3)) if code else (None, 0.0)
