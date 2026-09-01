"""Archetype definitions + the rules-first role->archetype assignment.

15 substantive role/skillset archetypes (ids 1..15) plus an honest residual
`OTHER` (id 0) for role-states no rule and no embedding can place. The pure
function `assign_role(...)` returns (archetype_id, method, confidence); the
embedding fallback for method=='unresolved' lives in assign.py.

Assignment precedence (most-specific structured signal first):
  1. SOC detailed code (6-digit) -> archetype via longest-prefix crosswalk
  2. SOC major (2-digit) default, refined by keyword for majors that split
     (27 creatives/writers/comms, 13 analysts/finance, 11 managers/comms/...)
  3. keyword rules on role text when no SOC signal exists
  4. Founders override: self-employed/owner with no resolved trade -> FOUNDERS
  5. else 'unresolved' (-> embedding fallback, else OTHER)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- The archetypes ---------------------------------------------------------
# (id, key, label, embedding descriptor)
ARCHETYPES: tuple[tuple[int, str, str, str], ...] = (
    (0, "other", "Other / Unclassified",
     "miscellaneous, skilled trades, transportation, protective service, or unclassified work"),
    (1, "educators", "Educators & Academics",
     "teacher professor instructor tutor lecturer educational curriculum school academic"),
    (2, "creatives", "Creatives & Media Makers",
     "designer artist photographer filmmaker illustrator animator musician producer creative visual media"),
    (3, "writers", "Writers, Editors & Content",
     "writer editor author copywriter journalist content editorial reporter storytelling"),
    (4, "comms", "Communications, PR & Marketing",
     "marketing communications public relations brand social media advertising growth campaign"),
    (5, "sales", "Sales & Business Development",
     "sales business development account executive representative revenue partnerships client acquisition"),
    (6, "managers", "Managers & Operations Leaders",
     "manager director operations general management executive leadership program administration"),
    (7, "analysts", "Business & Strategy Analysts / Consultants",
     "analyst consultant strategy business operations project management advisory research analytics"),
    (8, "finance", "Finance & Accounting",
     "accountant finance financial analyst auditor bookkeeper controller tax banking investment"),
    (9, "tech", "Tech & Product",
     "software engineer developer data scientist product manager designer UX IT programmer technology"),
    (10, "admin", "Administrative & Coordination",
     "administrative assistant coordinator office receptionist clerical support scheduling human resources"),
    (11, "legal", "Legal, Policy & Research",
     "lawyer attorney paralegal legal policy analyst researcher political scientist economist compliance"),
    (12, "healthcare", "Healthcare & Human Services",
     "nurse therapist counselor social worker clinician health caregiver psychologist chaplain human services"),
    (13, "nonprofit", "Nonprofit, Public Service & Advocacy",
     "nonprofit fundraising development advocacy grant philanthropy community organizer program officer mission"),
    (14, "hospitality", "Hospitality, Retail & Service",
     "server bartender barista retail hospitality restaurant customer service host chef cashier events"),
    (15, "founders", "Founders & Independent Practitioners",
     "founder owner entrepreneur self-employed freelance independent proprietor small business consultant"),
)

KEY_BY_ID = {a[0]: a[1] for a in ARCHETYPES}
ID_BY_KEY = {a[1]: a[0] for a in ARCHETYPES}
LABEL_BY_ID = {a[0]: a[2] for a in ARCHETYPES}
DESCRIPTOR_BY_KEY = {a[1]: a[3] for a in ARCHETYPES}

# --- SOC detailed-code prefix crosswalk (longest prefix wins) ---------------
# Keys are 2- to 6-char prefixes of a 6-digit SOC code ("27-3043"). Ordering
# does not matter; the matcher takes the longest matching prefix.
SOC_DETAIL: dict[str, str] = {
    # Educators
    "25": "educators", "11-9031": "educators", "11-9032": "educators",
    "11-9033": "educators",
    # Creatives (art/design, performers, media-equipment operators)
    "27-1": "creatives", "27-2": "creatives", "27-4": "creatives",
    # Writers / editors / journalists (within 27-3 media & communication)
    "27-3041": "writers", "27-3042": "writers", "27-3043": "writers",
    "27-3023": "writers",
    # Comms / PR / marketing
    "27-3031": "comms", "11-2011": "comms", "11-2021": "comms",
    "11-2022": "sales",  # 11-2022 = Sales Managers (NOT marketing)
    "11-2032": "comms", "13-1161": "comms",
    # Sales (B2B / reps / supervisors); retail+cashier split to hospitality
    "41": "sales", "41-2": "hospitality",
    # Managers & operations leaders
    "11-1": "managers", "11-3": "managers", "11-9": "managers",
    "11-3021": "tech", "11-3031": "finance", "11-3111": "admin",
    "11-3121": "managers", "11-9111": "healthcare", "11-9121": "healthcare",
    "11-9151": "nonprofit", "11-9161": "nonprofit", "11-2031": "comms",
    "11-2033": "nonprofit",
    # Analysts / consultants (13-1 business ops specialists)
    "13-1": "analysts", "13-1071": "admin", "13-1075": "admin",
    # Finance & accounting (13-2 financial specialists)
    "13-2": "finance",
    # Tech & product (computer & math; engineering folded here for volume)
    "15": "tech", "17": "tech",
    # Administrative & coordination
    "43": "admin",
    # Legal, policy & research (legal + science incl. social scientists)
    "23": "legal", "19": "legal",
    # Healthcare & human services
    "29": "healthcare", "31": "healthcare", "21": "healthcare",
    "21-1029": "nonprofit",
    # Hospitality, retail & service
    "35": "hospitality", "37": "hospitality", "39": "hospitality",
    # Other / residual majors (trades, transport, protective, farming, mil)
    "33": "other", "45": "other", "47": "other", "49": "other",
    "51": "other", "53": "other", "55": "other",
}

# SOC-major -> default archetype when only the 2-digit major is known.
SOC_MAJOR_DEFAULT: dict[str, str] = {
    "11": "managers", "13": "analysts", "15": "tech", "17": "tech",
    "19": "legal", "21": "healthcare", "23": "legal", "25": "educators",
    "27": "creatives", "29": "healthcare", "31": "healthcare",
    "33": "other", "35": "hospitality", "37": "hospitality", "39": "hospitality",
    "41": "sales", "43": "admin", "45": "other", "47": "other", "49": "other",
    "51": "other", "53": "other", "55": "other",
}

# --- Keyword rules ----------------------------------------------------------
# Ordered; first match wins. Used to (a) refine a split SOC major and (b) place
# roles with no SOC signal. Patterns match against lowercased role text.
def _rx(p: str) -> re.Pattern:
    return re.compile(p)


KEYWORD_RULES: tuple[tuple[re.Pattern, str], ...] = (
    # Nonprofit / advocacy (specific; checked before generic dev/manager).
    # "development (director|officer|associate)" is the nonprofit fundraising
    # sense — explicitly NOT business/product/software/biz development (sales
    # or tech), which the negative lookbehinds exclude. Bare "development
    # manager" is dropped (too often business development).
    # Nonprofit uses unambiguous fundraising/advancement cues. Generic
    # "development (manager|director|...)" is deliberately NOT matched: it is
    # too often business/product/R&D/L&D/land development (red-team finding 2).
    # The nonprofit-specific "director of development" / "advancement" phrasings
    # are matched instead.
    (_rx(r"fundrais|philanthrop|grant writer|grants manager|\badvocacy\b|\badvocate\b|"
         r"community organiz|program officer|major gifts|planned giving|"
         r"donor relations|annual giving|\badvancement\b|director of development|"
         r"nonprofit|non-profit|\bngo\b|humanitarian|social impact"), "nonprofit"),
    # Writers / content
    (_rx(r"\bwriter|\beditor|copywrit|author|journalis|\bcontent\b|editorial|"
         r"blogger|storytell|screenwrit|columnist"), "writers"),
    # Comms / PR / marketing. "market" is anchored to marketing/marketer/market
    # research so it does not swallow supermarket / capital markets / farmers
    # market / aftermarket (red-team finding 1).
    (_rx(r"\bmarketing\b|\bmarketer\b|market research|"
         r"\bbrand\b|communicat|public relations|\bpr\b|social media|"
         r"advertis|\bseo\b|\bgrowth\b|campaign|media relations|publicist"), "comms"),
    # Creatives. "producer" excludes the insurance/sales sense.
    (_rx(r"design|artist|photograph|filmmak|videograph|animat|illustrat|"
         r"musician|(?<!insurance )(?<!sales )(?<!licensed )\bproducer\b|"
         r"creative|\bart director|graphic|\bux\b|\bui\b|"
         r"\bactor\b|dancer|painter|sculptor|composer"), "creatives"),
    # Finance & accounting
    (_rx(r"account(ant|ing)|\bfinanc|\baudit|bookkeep|controller|\btax\b|"
         r"treasur|actuar|underwrit|\bbank(ing|er)|investment|financial analyst"), "finance"),
    # Tech & product
    (_rx(r"software|developer|engineer|programm|\bdata (scientist|analyst|engineer)|"
         r"\bml\b|machine learning|devops|\bit\b|information technology|"
         r"product manager|full.?stack|front.?end|back.?end|\bqa\b|sysadmin|"
         r"user research|ux research|user experience"), "tech"),
    # Legal / policy / research. "research" excludes UX/product/consumer/market/
    # clinical research (those belong to tech/healthcare, which follow).
    (_rx(r"lawyer|attorney|paralegal|\blegal\b|counsel\b|litigat|\bpolicy\b|"
         r"legislat|political scien|economist|compliance|"
         r"(?<!user )(?<!ux )(?<!product )(?<!consumer )(?<!market )(?<!clinical )"
         r"\bresearch(er)?\b"), "legal"),
    # Healthcare & human services
    (_rx(r"\bnurse|therap|counsel(or|ing)|social work|clinic|\bhealth|physician|"
         r"psycholog|chaplain|\bcaregiv|\bdoctor\b|medical|dental|pharmac|"
         r"speech patholog|occupational therap"), "healthcare"),
    # Educators
    (_rx(r"teacher|professor|instructor|lecturer|\btutor|educat|faculty|"
         r"\bta\b|teaching assistant|curriculum|principal \(school\)|dean\b|"
         r"adjunct|preschool|kindergarten"), "educators"),
    # Sales & BD
    (_rx(r"\bsales\b|business development|account executive|account manager|"
         r"\bbdr\b|\bsdr\b|sales rep|realtor|real estate agent|"
         r"insurance (agent|producer|broker|sales)"), "sales"),
    # Hospitality / retail / service (incl. function-qualified service
    # managers, which must beat the generic "manager" rule below)
    (_rx(r"\bserver\b|bartend|barista|\bretail\b|hospitality|restaurant|"
         r"\bchef\b|\bcook\b|\bhost(ess)?\b|cashier|waiter|waitress|"
         r"front desk|concierge|event coordinator|catering|"
         r"kitchen manager|store manager|retail manager|\bcafe\b|"
         r"food service|shift (manager|supervisor|lead)"), "hospitality"),
    # Administrative / coordination / HR / customer service
    (_rx(r"administrativ|\bassistant\b|coordinator|receptionist|\bclerk\b|"
         r"office manager|schedul|data entry|human resources|\bhr\b|recruit|"
         r"customer service|customer support|customer success|call center|"
         r"contact center|\bteller\b"), "admin"),
    # Analysts / consultants / strategy / ops / project mgmt
    (_rx(r"analyst|consult|strateg|business operations|project manager|"
         r"program manager|operations (analyst|manager|associate)|advisor"), "analysts"),
    # Managers (generic, last so specific functions win first)
    (_rx(r"manager|director|\bvp\b|vice president|\bhead of\b|\bchief\b|"
         r"\bcoo\b|\bceo\b|general manager|supervisor|operations"), "managers"),
    # Founders / independent (title-based; also reinforced by employment form)
    (_rx(r"founder|co-?founder|owner|entrepreneur|freelance|self.?employed|"
         r"proprietor|principal \(|independent (consultant|contractor)"), "founders"),
)

_FOUNDER_GENERIC = _rx(r"founder|co-?founder|owner|entrepreneur|proprietor|"
                       r"freelance|self.?employed|independent")


@dataclass
class RoleFeatures:
    soc_detail: str | None      # 6-digit SOC, e.g. "27-3043"
    soc_major: str | None       # 2-digit SOC, e.g. "27"
    role_text: str              # lowercased role_display + top titles
    employment_owner: bool      # role is predominantly self-employed/owner


def _longest_prefix(code: str) -> str | None:
    """Longest SOC_DETAIL prefix matching a 6-digit code."""
    for n in (7, 6, 5, 4, 2):  # "27-3043"=7, "27-304"=6, "27-30"=5, "27-"=4, "27"=2
        pre = code[:n]
        if pre in SOC_DETAIL:
            return SOC_DETAIL[pre]
    return None


# SOC majors that split by function -> only these keyword refinements are
# accepted (cross-cutting keywords like generic managers/founders never
# override a known functional major).
SPLIT_REFINEMENTS: dict[str, set[str]] = {
    "27": {"writers", "comms", "creatives", "educators"},
    "13": {"finance", "analysts", "comms", "admin", "sales"},
    "11": {"comms", "finance", "tech", "healthcare", "educators",
           "nonprofit", "analysts", "admin", "sales"},
    "21": {"nonprofit", "healthcare"},
}


def _keyword_key(text: str) -> str | None:
    for rx, key in KEYWORD_RULES:
        if rx.search(text):
            return key
    return None


def assign_role(f: RoleFeatures) -> tuple[int, str, float]:
    """Return (archetype_id, method, confidence)."""
    text = f.role_text or ""

    # 0. Generic self-employed term with NO functional trade in the text ->
    #    Founders, BEFORE any SOC. A bare "owner"/"founder"/"self-employed"
    #    role aggregates wildly different businesses, so its modal SOC is
    #    meaningless (an "owner" role should not become Creatives because some
    #    coded owners run studios). A trade in the text (e.g. "restaurant
    #    owner") is caught by _keyword_key and keeps its functional archetype.
    if f.employment_owner and _FOUNDER_GENERIC.search(text):
        kw = _keyword_key(text)
        if kw is None or kw == "founders":
            return ID_BY_KEY["founders"], "founder_generic", 0.7

    # 1. SOC detailed code (most specific). A detail code routing to OTHER
    #    (trades/transport/protective/military majors) is often a miscode for
    #    a clearly white-collar title (e.g. "Project Manager" coded 47-xxxx),
    #    so let a substantive keyword rescue it before trusting the code.
    if f.soc_detail:
        key = _longest_prefix(f.soc_detail)
        if key and key != "other":
            return ID_BY_KEY[key], "soc_detail", 0.95
        if key == "other":
            kw = _keyword_key(text)
            if kw and kw not in ("other", "founders"):
                return ID_BY_KEY[kw], "keyword_over_soc", 0.6
            if f.employment_owner:
                return ID_BY_KEY["founders"], "founder_residual", 0.55
            return ID_BY_KEY["other"], "soc_detail", 0.5

    # 2. SOC major default, refined by keyword only within the major's split set
    if f.soc_major and f.soc_major in SOC_MAJOR_DEFAULT:
        refinements = SPLIT_REFINEMENTS.get(f.soc_major)
        if refinements:
            kw = _keyword_key(text)
            if kw in refinements:
                return ID_BY_KEY[kw], "soc_major_kw", 0.8
        default = SOC_MAJOR_DEFAULT[f.soc_major]
        if default != "other":
            return ID_BY_KEY[default], "soc_major", 0.7
        # major routes to OTHER -> rescue with a substantive keyword first
        kw = _keyword_key(text)
        if kw and kw not in ("other", "founders"):
            return ID_BY_KEY[kw], "keyword_over_soc", 0.6
        if f.employment_owner:
            return ID_BY_KEY["founders"], "founder_residual", 0.55
        return ID_BY_KEY["other"], "soc_major", 0.5

    # 3. keyword-only (no SOC signal)
    kw = _keyword_key(text)
    if kw:
        return ID_BY_KEY[kw], "keyword", 0.6

    # 4. Founders override for self-employed/owner residual
    if f.employment_owner:
        return ID_BY_KEY["founders"], "founder_residual", 0.55

    # 5. unresolved -> embedding fallback (assign.py), else OTHER
    return ID_BY_KEY["other"], "unresolved", 0.0
