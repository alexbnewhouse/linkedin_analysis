"""Hand-labeled gold set for the industry classifier + LLM calibration.

Two grains, mirroring ``career_clean.gold``:

  * GOLD_COMPANIES -- ``(company_id, display, expected_code)`` at the
    distinct-company grain. Stresses the hard cases the plan calls out (§5):
    conglomerates (Amazon), staffing agencies, holding companies, universities
    that also run hospitals, government vs. government contractor, plus the
    precision-1.0 curated head and the self-describing name tail.
  * GOLD_ROWS -- ``(occupation_code, expected_code)`` for the ``nonorg``
    self-employed population, where industry must come from the occupation.

Expected codes may be at ANY depth; ``common.level_scores`` truncates both sides
per level, so a label can assert "Finance/Banking" (L2) without committing to an
L4 leaf. Cases the deterministic stack is expected to MISS are included on
purpose -- the eval's per-level recall is where the LLM/curation lift is measured.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldCompany:
    expected: str
    display: str
    company_id: str | None = None
    modal_occ: str | None = None
    occ_coded_frac: float | None = None
    note: str = ""

    def key(self) -> str:
        return f"id:{self.company_id}" if self.company_id else f"name:{self.display}"


GOLD_COMPANIES: list[GoldCompany] = [
    # --- curated head: precision-1.0 backbone (M1) ---
    GoldCompany("FIN.BNK.COM.RET", "Wells Fargo", "wellsfargo"),
    GoldCompany("FIN.BNK.COM", "JPMorgan Chase & Co.", "jpmorganchase"),
    GoldCompany("FIN.BNK.INV", "Goldman Sachs", "goldman-sachs"),
    GoldCompany("HLT.PHRM.PHARMA", "Pfizer", "pfizer"),
    GoldCompany("TEC.HRDW.SEMI", "Intel Corporation", "intel-corporation"),
    GoldCompany("TEC.SOF.INTC.SRCH", "Google", "google"),
    GoldCompany("PUB.DEF.AF", "US Army", "us-army"),
    GoldCompany("CON.RET.GEN", "Walmart", "walmart"),
    GoldCompany("HOS.FOOD", "Starbucks", "starbucks"),
    # --- government vs. government contractor (the classic confusion) ---
    GoldCompany("PUB.DEF.DCON", "Lockheed Martin", "lockheed-martin",
                note="defense CONTRACTOR (private), not the armed forces"),
    GoldCompany("PUB.GOV.FED", "U.S. Department of Veterans Affairs",
                "department-of-veterans-affairs"),
    # --- diversified giants: XDV is the honest answer ---
    GoldCompany("XDV", "Amazon", "amazon", note="retail + cloud + media + logistics"),
    GoldCompany("TEC.SOF.INFR.CLOU", "Amazon Web Services (AWS)", "amazon-web-services",
                note="separate company_id -> the right granularity for the cloud arm"),
    # --- self-describing name tail (M3), no company_id ---
    GoldCompany("HLT.PROV.HOSP", "St. Mary's Medical Center"),
    GoldCompany("RE.CNST.TRADE", "Johnson & Sons Plumbing LLC"),
    GoldCompany("FIN.BNK", "First National Bank of Springfield"),
    GoldCompany("EDU.K12", "Springfield Public Schools"),
    GoldCompany("EDU.HED.UNIV", "University of Michigan",
                note="also runs a hospital; the parent org is Education"),
    GoldCompany("PUB.GOV.SLOC", "City of Austin"),
    GoldCompany("PRO.HRST", "Premier Staffing Solutions"),
    GoldCompany("HLT.PROV.DENT", "Bright Smile Dentistry"),
    GoldCompany("PRO.LEGAL", "Miller & Associates Law Offices"),
    GoldCompany("HOS.FOOD", "Tony's Italian Restaurant"),
    GoldCompany("RE.REST.RES", "Coldwell Banker Realty"),
    GoldCompany("ENR.OILG", "Permian Basin Oil & Gas"),
    # --- recall gaps we EXPECT the deterministic stack to miss (no id, no
    #     self-describing token) -> measures where the LLM/curation earns its keep ---
    GoldCompany("PRO.CONSL", "Booz Allen Hamilton", note="no industry token in the name"),
    GoldCompany("MFG.AUTO.OEM", "Rivian", note="brand name carries no industry token"),
    GoldCompany("CON.CPG.FNB", "Chobani", note="brand name carries no industry token"),
    # --- holding company: thin signal -> Diversified/Other is acceptable ---
    GoldCompany("XDV", "Berkshire Hathaway", "berkshire-hathaway"),
]

# Row-grain (nonorg self-employed): industry must come from the occupation.
GOLD_ROWS: list[tuple[str, str]] = [
    ("29-1141", "HLT.PROV"),   # self-employed Registered Nurse -> Healthcare
    ("25-2021", "EDU.K12"),    # private tutor coded to elementary teaching
    ("35-1011", "HOS.FOOD"),   # self-employed Chef -> Food Services
    ("47-2111", "RE.CNST"),    # self-employed Electrician -> Construction
    ("15-1252", "XOT"),        # freelance Software Developer is INDUSTRY-AGNOSTIC -> abstain
    ("13-2011", "XOT"),        # freelance Accountant is INDUSTRY-AGNOSTIC -> abstain
]
