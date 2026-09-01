"""The frozen 4-level industry/sector schema (Layer 6a, see INDUSTRY_PLAN.md §1).

This module is the **single source of truth** for the taxonomy. It defines a
custom 4-level spine crosswalked down to NAICS, exposes accessors + validation,
builds the enum used to constrain LLM structured output, and (via ``build``)
writes the committed, externally-joinable ``industry/taxonomy.json`` asset.

Design rules (from the plan):
  * Every node has a STABLE code (``L1.L2.L3.L4`` dot path, e.g. ``FIN.BNK.COM.RET``)
    plus a display label and a NAICS crosswalk. Codes drive joins; labels drive UI.
  * PARTIAL assignment is first-class: a company may be classified to any depth
    (L1 only ... L4). Every internal node is itself a legal assignment target.
  * "Unclassifiable" buckets exist at the top (``XOT`` Other/Unknown, ``XDV``
    Diversified/Conglomerate) so the long tail and the giants have an honest home.
  * Cross-cutting ``sector`` (private/public/nonprofit) is a flag derived from the
    node, not a separate branch.

The tree is authored as nested dicts (compact, reviewable); ``_flatten`` derives
the dotted codes once at import. Keep edits here, regenerate the JSON with::

    uv run python -m industry.taxonomy build
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_JSON = Path(__file__).resolve().parent / "taxonomy.json"

# Bump when the node set changes -- busts the LLM proposal cache (industry/llm.py)
# so stale proposals against an old taxonomy are never silently reused.
SCHEMA_VERSION = 1

# A node is {"label", optional "naics" (crosswalk prefixes), optional "sector",
# optional "children": {short_code -> node}}. A leaf omits "children". ``sector``
# is inherited by descendants unless they override it.
#
# L1 macro-sectors (~16 + 2 catch-all). L2 ~ NAICS subsector. L3 ~ NAICS 4-digit /
# LinkedIn industry. L4 ~ NAICS 5-6 / GICS sub-industry, authored for the
# well-populated branches (partial assignment covers the rest).
TAXONOMY: dict[str, dict] = {
    # ============================================================ TECHNOLOGY
    "TEC": {"label": "Technology", "naics": ["51", "5415"], "children": {
        "SOF": {"label": "Software & IT Services", "naics": ["5112", "5415", "5182"], "children": {
            "APP": {"label": "Application Software", "naics": ["513210"], "children": {
                "SAAS": {"label": "SaaS / B2B Software"},
                "CONS": {"label": "Consumer Software & Apps"},
                "MOBL": {"label": "Mobile / Gaming Software"},
            }},
            "INFR": {"label": "Infrastructure & Systems Software", "naics": ["513210"], "children": {
                "CLOU": {"label": "Cloud & Hosting"},
                "SEC": {"label": "Cybersecurity"},
                "DATA": {"label": "Data & Analytics Platforms"},
            }},
            "ITSV": {"label": "IT Services & Consulting", "naics": ["5415"], "children": {
                "INTG": {"label": "Systems Integration & IT Consulting"},
                "MSP": {"label": "Managed Services & IT Outsourcing"},
            }},
            "INTC": {"label": "Internet & Digital Platforms", "naics": ["5182", "519"], "children": {
                "SRCH": {"label": "Search, Social & Marketplaces"},
                "ECOM": {"label": "E-commerce Platforms"},
            }},
        }},
        "HRDW": {"label": "Hardware & Electronics", "naics": ["334"], "children": {
            "SEMI": {"label": "Semiconductors", "naics": ["3344"]},
            "COMP": {"label": "Computers & Peripherals", "naics": ["3341"]},
            "COMM": {"label": "Communications & Networking Equipment", "naics": ["3342"]},
            "EDEV": {"label": "Electronic Devices & Components", "naics": ["3343", "3346"]},
        }},
        "TELE": {"label": "Telecommunications", "naics": ["517"], "children": {
            "WIRE": {"label": "Wireless & Wireline Carriers", "naics": ["5172", "5171"]},
            "TINF": {"label": "Telecom Infrastructure"},
        }},
    }},
    # =============================================================== FINANCE
    "FIN": {"label": "Finance", "naics": ["52"], "children": {
        "BNK": {"label": "Banking", "naics": ["522"], "children": {
            "COM": {"label": "Commercial Banking", "naics": ["52211"], "children": {
                "RET": {"label": "Retail / Consumer Banking"},
                "CORP": {"label": "Corporate / Business Banking"},
            }},
            "INV": {"label": "Investment Banking & Capital Markets", "naics": ["523"], "children": {
                "MNA": {"label": "M&A / Advisory"},
                "TRAD": {"label": "Trading & Brokerage"},
            }},
            "CU": {"label": "Credit Unions & Thrifts", "naics": ["52213"]},
        }},
        "ASM": {"label": "Asset & Investment Management", "naics": ["5239"], "children": {
            "AM": {"label": "Asset Management & Mutual Funds"},
            "PE": {"label": "Private Equity & Venture Capital"},
            "HF": {"label": "Hedge Funds"},
            "WM": {"label": "Wealth Management & Advisory"},
        }},
        "INS": {"label": "Insurance", "naics": ["524"], "children": {
            "PNC": {"label": "Property & Casualty Insurance", "naics": ["524126"]},
            "LIFE": {"label": "Life & Health Insurance", "naics": ["524113"]},
            "BROK": {"label": "Insurance Brokerage & Agencies", "naics": ["52421"]},
        }},
        "FINT": {"label": "Fintech & Payments", "naics": ["522320"], "children": {
            "PAY": {"label": "Payments & Processing"},
            "LEND": {"label": "Digital Lending & Credit"},
            "CRYP": {"label": "Crypto & Digital Assets"},
        }},
    }},
    # ============================================================ HEALTHCARE
    "HLT": {"label": "Healthcare", "naics": ["62", "3254", "3391"], "children": {
        "PROV": {"label": "Healthcare Providers & Services", "naics": ["62"], "children": {
            "HOSP": {"label": "Hospitals & Health Systems", "naics": ["622"]},
            "AMB": {"label": "Ambulatory & Physician Practices", "naics": ["621"]},
            "DENT": {"label": "Dental & Vision", "naics": ["6212"]},
            "LTC": {"label": "Long-term & Residential Care", "naics": ["623"]},
            "MHSA": {"label": "Mental Health & Social Assistance", "naics": ["6242", "623220"]},
        }},
        "PHRM": {"label": "Pharmaceuticals & Biotech", "naics": ["3254", "5417"], "children": {
            "PHARMA": {"label": "Pharmaceuticals", "naics": ["325412"]},
            "BIO": {"label": "Biotechnology", "naics": ["541714"]},
        }},
        "MDEV": {"label": "Medical Devices & Equipment", "naics": ["3391"]},
        "HTECH": {"label": "Health Tech & Digital Health", "naics": ["62"]},
        "PAYR": {"label": "Health Insurance & Managed Care", "naics": ["524114"]},
    }},
    # ============================================================= EDUCATION
    "EDU": {"label": "Education", "naics": ["61"], "children": {
        "K12": {"label": "K-12 Schools", "naics": ["6111"]},
        "HED": {"label": "Higher Education", "naics": ["6113"], "children": {
            "UNIV": {"label": "Universities & Colleges"},
            "CC": {"label": "Community & Technical Colleges"},
        }},
        "EDTECH": {"label": "EdTech & Online Learning", "naics": ["611710"]},
        "TRNG": {"label": "Training, Tutoring & Vocational", "naics": ["6114", "6116"]},
    }},
    # ========================================================= PUBLIC SECTOR
    "PUB": {"label": "Public Sector", "naics": ["92"], "sector": "public", "children": {
        "GOV": {"label": "Government Administration", "naics": ["921"], "children": {
            "FED": {"label": "Federal Government"},
            "SLOC": {"label": "State & Local Government"},
            "INTL": {"label": "International / Multilateral Bodies"},
        }},
        "DEF": {"label": "Defense & Military", "naics": ["928110"], "children": {
            "AF": {"label": "Armed Forces"},
            "DCON": {"label": "Defense Contractors", "sector": "private"},
        }},
        "JUST": {"label": "Justice, Public Safety & Law Enforcement", "naics": ["922"]},
        "PADM": {"label": "Public Programs & Agencies", "naics": ["923", "924", "925", "926"]},
    }},
    # ========================================================== MANUFACTURING
    "MFG": {"label": "Manufacturing & Industrials", "naics": ["31", "32", "33", "333"], "children": {
        "IND": {"label": "Industrial & Machinery", "naics": ["333"], "children": {
            "MACH": {"label": "Industrial Machinery & Equipment"},
            "ELEC": {"label": "Electrical Equipment", "naics": ["335"]},
        }},
        "AUTO": {"label": "Automotive & Vehicles", "naics": ["3361", "3362", "3363"], "children": {
            "OEM": {"label": "Vehicle Manufacturing"},
            "PARTS": {"label": "Auto Parts & Suppliers"},
        }},
        "AERO": {"label": "Aerospace", "naics": ["3364"]},
        "CHEM": {"label": "Chemicals & Materials", "naics": ["325", "327", "331"], "children": {
            "SPCH": {"label": "Specialty & Industrial Chemicals"},
            "MATL": {"label": "Materials, Metals & Plastics"},
        }},
        "CONP": {"label": "Consumer & Durable Goods Manufacturing", "naics": ["337", "339"]},
    }},
    # =========================================================== CONSUMER/RETAIL
    "CON": {"label": "Consumer & Retail", "naics": ["44", "45", "31"], "children": {
        "RET": {"label": "Retail", "naics": ["44", "45"], "children": {
            "GEN": {"label": "General Merchandise & Department Stores", "naics": ["452"]},
            "GROC": {"label": "Grocery & Food Retail", "naics": ["445"]},
            "SPEC": {"label": "Specialty & Apparel Retail", "naics": ["448", "451"]},
            "ETAIL": {"label": "E-commerce & Direct-to-Consumer", "naics": ["4541"]},
        }},
        "CPG": {"label": "Consumer Packaged Goods", "naics": ["311", "312", "3256"], "children": {
            "FNB": {"label": "Food & Beverage", "naics": ["311", "312"]},
            "HPC": {"label": "Household & Personal Care", "naics": ["3256"]},
            "APPL": {"label": "Apparel, Footwear & Luxury", "naics": ["315", "316"]},
        }},
        "WHL": {"label": "Wholesale & Distribution", "naics": ["42"]},
    }},
    # ======================================================= ENERGY & UTILITIES
    "ENR": {"label": "Energy & Utilities", "naics": ["21", "22", "486"], "children": {
        "OILG": {"label": "Oil & Gas", "naics": ["211", "213", "486"], "children": {
            "UPST": {"label": "Exploration & Production (Upstream)"},
            "MIDS": {"label": "Midstream & Pipelines"},
            "DOWN": {"label": "Refining & Marketing (Downstream)"},
        }},
        "UTIL": {"label": "Utilities", "naics": ["221"], "children": {
            "POWR": {"label": "Electric Power & Generation", "naics": ["2211"]},
            "WGAS": {"label": "Water & Gas Utilities", "naics": ["2212", "2213"]},
        }},
        "RENW": {"label": "Renewables & Clean Energy", "naics": ["221114", "221115"]},
        "MINE": {"label": "Mining & Metals Extraction", "naics": ["212"]},
    }},
    # ==================================================== MEDIA & ENTERTAINMENT
    "MED": {"label": "Media & Entertainment", "naics": ["51", "71", "512"], "children": {
        "PUBL": {"label": "Publishing & News", "naics": ["511", "519"]},
        "BCAST": {"label": "Broadcasting & Streaming", "naics": ["515", "516", "5121"]},
        "FILM": {"label": "Film, Music & Production", "naics": ["5121", "5122", "7111"]},
        "GAME": {"label": "Gaming & Interactive Entertainment", "naics": ["713"]},
        "ADV": {"label": "Advertising, Marketing & PR", "naics": ["5418"], "children": {
            "AGY": {"label": "Advertising & Creative Agencies"},
            "MKTG": {"label": "Marketing, PR & Market Research", "naics": ["5419"]},
        }},
        "SPRT": {"label": "Sports & Recreation", "naics": ["711211", "713940"]},
    }},
    # ==================================================== PROFESSIONAL SERVICES
    "PRO": {"label": "Professional Services", "naics": ["54", "55", "56"], "children": {
        "CONSL": {"label": "Management & Strategy Consulting", "naics": ["541611"]},
        "LEGAL": {"label": "Legal Services", "naics": ["5411"]},
        "ACCT": {"label": "Accounting, Audit & Tax", "naics": ["5412"]},
        "ENGS": {"label": "Engineering & Architecture Services", "naics": ["5413"]},
        "HRST": {"label": "Staffing, Recruiting & HR Services", "naics": ["5613", "5614"]},
        "BPO": {"label": "Business Process & Support Services", "naics": ["561"]},
        "DSGN": {"label": "Design & Creative Services", "naics": ["5414"]},
    }},
    # =============================================================== REAL ESTATE
    "RE": {"label": "Real Estate & Construction", "naics": ["53", "23", "236"], "children": {
        "REST": {"label": "Real Estate", "naics": ["531"], "children": {
            "CRE": {"label": "Commercial Real Estate & REITs", "naics": ["5311", "525"]},
            "RES": {"label": "Residential Real Estate & Brokerage", "naics": ["5312"]},
            "PM": {"label": "Property Management", "naics": ["5313"]},
        }},
        "CNST": {"label": "Construction", "naics": ["23"], "children": {
            "BLDG": {"label": "Building Construction", "naics": ["236"]},
            "INFC": {"label": "Heavy & Civil Engineering Construction", "naics": ["237"]},
            "TRADE": {"label": "Specialty Trade Contractors", "naics": ["238"]},
        }},
        "ARCH": {"label": "Architecture & Building Design", "naics": ["5413"]},
    }},
    # ==================================================== TRANSPORT & LOGISTICS
    "TRN": {"label": "Transportation & Logistics", "naics": ["48", "49"], "children": {
        "LOG": {"label": "Logistics, Freight & Supply Chain", "naics": ["488", "492", "493"]},
        "TRUCK": {"label": "Trucking & Ground Freight", "naics": ["484"]},
        "AIR": {"label": "Airlines & Aviation", "naics": ["481"]},
        "MAR": {"label": "Maritime & Shipping", "naics": ["483"]},
        "RAIL": {"label": "Rail Transportation", "naics": ["482"]},
        "PSNG": {"label": "Passenger & Ride Transportation", "naics": ["485", "4853"]},
    }},
    # ===================================================== HOSPITALITY & TRAVEL
    "HOS": {"label": "Hospitality, Travel & Food Services", "naics": ["72", "71"], "children": {
        "FOOD": {"label": "Restaurants & Food Service", "naics": ["722"]},
        "LODG": {"label": "Hotels & Lodging", "naics": ["721"]},
        "TRVL": {"label": "Travel, Tourism & Leisure", "naics": ["5615", "7211"]},
        "EVNT": {"label": "Events, Catering & Venues", "naics": ["7223", "7139"]},
    }},
    # =========================================================== AGRICULTURE
    "AGR": {"label": "Agriculture & Natural Resources", "naics": ["11"], "children": {
        "FARM": {"label": "Farming & Crop Production", "naics": ["111"]},
        "LIVE": {"label": "Livestock & Animal Production", "naics": ["112"]},
        "FOR": {"label": "Forestry, Fishing & Hunting", "naics": ["113", "114"]},
        "AGSV": {"label": "Agricultural Services & Support", "naics": ["115"]},
    }},
    # ====================================================== NONPROFIT / SOCIAL
    "NPO": {"label": "Nonprofit & Social Sector", "naics": ["813", "8132", "8133"], "sector": "nonprofit", "children": {
        "PHIL": {"label": "Foundations & Philanthropy", "naics": ["813211"]},
        "SOCS": {"label": "Social Services & Community", "naics": ["624"]},
        "ADVO": {"label": "Advocacy, Civic & Membership Orgs", "naics": ["8133", "8139"]},
        "RELG": {"label": "Religious Organizations", "naics": ["8131"]},
        "INTD": {"label": "International Development & Humanitarian"},
        "RSCH": {"label": "Research Institutes & Think Tanks", "naics": ["5417"]},
    }},
    # =========================================== CATCH-ALL / UNCLASSIFIABLE (X*)
    "XDV": {"label": "Diversified / Conglomerate"},
    "XOT": {"label": "Other / Unknown"},
}

# Sector default per top-level branch; nodes may override via a node-level "sector".
_DEFAULT_SECTOR = "private"
VALID_SECTORS = ("private", "public", "nonprofit")


# ---------------------------------------------------------------------------
# Flatten the tree to dotted codes once at import.
# ---------------------------------------------------------------------------
class Node:
    __slots__ = ("code", "level", "label", "parent", "naics", "sector", "children")

    def __init__(self, code, level, label, parent, naics, sector):
        self.code = code
        self.level = level
        self.label = label
        self.parent = parent  # parent code or None
        self.naics = naics
        self.sector = sector
        self.children: list[str] = []

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "level": self.level,
            "label": self.label,
            "parent": self.parent,
            "naics": self.naics,
            "sector": self.sector,
            "children": self.children,
        }


def _flatten() -> dict[str, Node]:
    nodes: dict[str, Node] = {}

    def walk(subtree: dict, prefix: str, level: int, parent: str | None, inherited_sector: str):
        for short, body in subtree.items():
            if "." in short:
                raise ValueError(f"short code {short!r} must not contain a dot")
            code = f"{prefix}.{short}" if prefix else short
            if code in nodes:
                raise ValueError(f"duplicate code {code!r}")
            sector = body.get("sector", inherited_sector)
            node = Node(code, level, body["label"], parent, tuple(body.get("naics", ())), sector)
            nodes[code] = node
            if parent is not None:
                nodes[parent].children.append(code)
            walk(body.get("children", {}), code, level + 1, code, sector)

    walk(TAXONOMY, "", 1, None, _DEFAULT_SECTOR)
    return nodes


NODES: dict[str, Node] = _flatten()


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------
def is_valid(code: str | None) -> bool:
    return bool(code) and code in NODES


def level_of(code: str) -> int:
    return NODES[code].level


def label_of(code: str) -> str:
    return NODES[code].label


def path_labels(code: str) -> list[str]:
    """Ancestor-to-node display labels, e.g. ['Finance','Banking','Commercial Banking']."""
    out = []
    cur: str | None = code
    while cur is not None:
        out.append(NODES[cur].label)
        cur = NODES[cur].parent
    return list(reversed(out))


def ancestors(code: str) -> list[str]:
    """Codes from L1 down to (and including) ``code``."""
    out = []
    cur: str | None = code
    while cur is not None:
        out.append(cur)
        cur = NODES[cur].parent
    return list(reversed(out))


def truncate(code: str, depth: int) -> str | None:
    """Truncate a code to ``depth`` levels (1-4). Returns the ancestor code or
    None if depth < 1. Used to emit a PARTIAL path at the depth the evidence
    supports (e.g. confident L1/L2 even when L3/L4 is unknown)."""
    if not is_valid(code) or depth < 1:
        return None
    chain = ancestors(code)
    return chain[min(depth, len(chain)) - 1]


def sector_of(code: str) -> str:
    return NODES[code].sector


def naics_of(code: str) -> tuple[str, ...]:
    """NAICS crosswalk prefixes for the node, falling back to the nearest
    ancestor that carries one (so every node resolves to *some* NAICS anchor)."""
    cur: str | None = code
    while cur is not None:
        if NODES[cur].naics:
            return NODES[cur].naics
        cur = NODES[cur].parent
    return ()


def codes_at_level(level: int) -> list[str]:
    return [c for c, n in NODES.items() if n.level == level]


def all_codes() -> list[str]:
    return list(NODES.keys())


# ---------------------------------------------------------------------------
# Structured-output schema (the enum that constrains the LLM, INDUSTRY_PLAN §1)
# ---------------------------------------------------------------------------
def output_json_schema() -> dict:
    """A strict JSON schema for one classification. ``code`` is enum-constrained
    to the taxonomy so the model literally cannot emit an off-taxonomy node;
    partial assignment is allowed because every internal node is a legal code.

    REASON BEFORE VERDICT: ``rationale`` is emitted FIRST, then ``code``, then
    ``confidence``. Structured output is generated in property order, so putting
    the rationale first forces the model to articulate the evidence before it
    commits to a code -- a cheap, well-established lift (G-Eval / chain-of-thought
    grading) over the answer-first ordering, which makes the rationale a post-hoc
    justification rather than a driver. Changing this order is a prompt-semantics
    change, so industry.llm.PROMPT_VERSION is bumped in lockstep (busts the cache)."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rationale": {
                "type": "string",
                "description": "FIRST: one short sentence reasoning from the actual "
                "evidence (a name token, a job title, a description phrase) to the "
                "industry. Decide the code only after writing this.",
            },
            "code": {
                "type": "string",
                "enum": all_codes(),
                "description": "The deepest taxonomy node the rationale's evidence "
                "supports (may be L1/L2 only — do not guess deeper than the evidence).",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Evidence strength for the code, not eloquence. NOTE: "
                "self-reported confidence is weakly calibrated and is treated as "
                "advisory only downstream — jury agreement is the gating signal.",
            },
        },
        "required": ["rationale", "code", "confidence"],
    }


def labelled_catalog() -> str:
    """A compact, indented rendering of the tree for the LLM prompt body, so the
    model sees code + label + NAICS hint without us shipping the JSON schema in
    prose. Stable ordering = cache-friendly."""
    lines: list[str] = []

    def emit(code: str) -> None:
        n = NODES[code]
        indent = "  " * (n.level - 1)
        naics = f"  [NAICS {','.join(n.naics)}]" if n.naics else ""
        lines.append(f"{indent}{code} = {n.label}{naics}")
        for child in n.children:
            emit(child)

    for code in codes_at_level(1):
        emit(code)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation + committed-asset build
# ---------------------------------------------------------------------------
def validate() -> dict:
    """Structural integrity checks. Raises on any violation; returns a summary."""
    problems: list[str] = []
    seen_labels_by_parent: dict[str | None, set[str]] = {}
    for code, n in NODES.items():
        if n.level < 1 or n.level > 4:
            problems.append(f"{code}: level {n.level} outside 1-4")
        if n.parent is not None and n.parent not in NODES:
            problems.append(f"{code}: dangling parent {n.parent}")
        if n.sector not in VALID_SECTORS:
            problems.append(f"{code}: bad sector {n.sector!r}")
        sib = seen_labels_by_parent.setdefault(n.parent, set())
        key = n.label.lower()
        if key in sib:
            problems.append(f"{code}: duplicate sibling label {n.label!r}")
        sib.add(key)
    if problems:
        raise ValueError("taxonomy validation failed:\n  " + "\n  ".join(problems))
    by_level = {lvl: len(codes_at_level(lvl)) for lvl in (1, 2, 3, 4)}
    return {"n_nodes": len(NODES), "by_level": by_level}


def to_records() -> list[dict]:
    return [NODES[c].as_dict() for c in NODES]


def build() -> None:
    summary = validate()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "description": "4-level industry/sector taxonomy crosswalked to NAICS. "
        "Codes are dotted ancestor paths; every node is a legal (partial) "
        "assignment target. See industry/taxonomy.py.",
        "summary": summary,
        "nodes": to_records(),
    }
    TAXONOMY_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"wrote {TAXONOMY_JSON}")
    print(f"  nodes={summary['n_nodes']}  by_level={summary['by_level']}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
    else:
        print(json.dumps(validate(), indent=2))
        print("\nCatalog preview:\n")
        print(labelled_catalog())
