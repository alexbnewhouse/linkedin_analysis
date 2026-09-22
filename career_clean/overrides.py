"""Employer-keyed occupation overrides (spec P5, rules per the 2026-09-22 pre-review).

Pure rule table; the row-level mapping is built by career_clean/run_overrides.py. Every
rule names a reason so a consumer can exclude it. Rules:

  vice_president    seniority tokens contain 'vice' (and not 'senior'/'executive') and the
                    role is 'president' / 'assistantpresident': bare, associate and
                    assistant vice presidents move from 11-1011 (Chief Executives) to
                    11-1021 (General and Operations Managers). A CONVENTION, not an O*NET
                    mapping: on LinkedIn a bare "Vice President" is mostly a rank (a fifth
                    are at banks); O*NET keeps EVP/SVP under 11-1011 and so do we. Never fires
                    on functional VP titles ("Vice President of Sales" keeps its det code).
  k12_principal     bare / assistant / vice / interim principal at an EDU.K12 employer (or
                    EDU with no L2) -> 11-9032 Education Administrators, Kindergarten
                    through Secondary.
  law_firm_partner  partner / associate / counsel / shareholder / member / principal at a
                    PRO.LEGAL employer -> 23-1011 Lawyers (95.7% of PRO.LEGAL Associates hold
                    a JD; paralegal mentions 1.7%).

Dropped from the spec after pre-review: firm_principal (heterogeneous population, would
fail the gate). Overrides never change a non-NULL det major: VP stays in 11.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from cleanlib.text import normalize


@dataclass(frozen=True)
class Override:
    occupation_code: str
    soc_major: str
    reason: str


_PRINCIPAL = re.compile(r"^(?:(?:assistant|associate|vice|interim|acting|school)\s+)?principal$")
_LAW_TITLES = frozenset({
    "partner", "managing partner", "senior partner", "equity partner", "junior partner",
    "name partner", "founding partner", "associate", "senior associate", "junior associate",
    "of counsel", "counsel", "shareholder", "member", "associate attorney", "principal",
})
_VP_EXCLUDE_TOKENS = frozenset({"senior", "executive"})


def override(title_raw, role_canonical, seniority_level, industry_l1, industry_l2) -> Override | None:
    t = normalize(title_raw)
    if not t:
        return None
    toks = {x for x in (seniority_level or "").split(",") if x}
    if "vice" in toks and role_canonical in ("president", "assistantpresident") \
            and not (toks & _VP_EXCLUDE_TOKENS):
        return Override("11-1021", "11", "vice_president")
    if _PRINCIPAL.match(t):
        if industry_l2 == "EDU.K12" or (industry_l1 == "EDU" and industry_l2 in (None, "EDU")):
            return Override("11-9032", "11", "k12_principal")
    if t in _LAW_TITLES and industry_l2 == "PRO.LEGAL":
        return Override("23-1011", "23", "law_firm_partner")
    return None
