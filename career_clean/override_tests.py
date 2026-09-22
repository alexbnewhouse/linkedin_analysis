"""Logic checks for the employer-keyed overrides.

    uv run python -m career_clean.override_tests

Argument order follows the spec: override(title_raw, role_canonical, seniority_level, industry_l1, industry_l2).
"""
from __future__ import annotations

from career_clean.overrides import override


def check(name: str, cond: bool) -> None:
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def main() -> None:
    o = override("Vice President", "president", "vice", "FIN", "FIN.BNK")
    check("bare VP -> 11-1021", o and o.occupation_code == "11-1021" and o.reason == "vice_president")
    o = override("VP", "president", "vice", None, None)
    check("VP with no industry still fires (token rule)", o and o.occupation_code == "11-1021")
    o = override("Assistant Vice President", "president", "assistant,vice", "FIN", "FIN.BNK")
    check("assistant VP fires", o and o.occupation_code == "11-1021")
    check("Senior Vice President stays 11-1011 (O*NET)",
          override("Senior Vice President", "president", "senior,vice", "TEC", None) is None)
    check("Executive Vice President stays",
          override("Executive Vice President", "president", "executive,vice", "TEC", None) is None)
    check("functional VP never fires", override("Vice President of Sales", "president sales", "vice", "TEC", None) is None)
    check("Vice President, Marketing never fires",
          override("Senior Vice President, Marketing", "marketing president", "senior,vice", "TEC", None) is None)
    check("President untouched", override("President", "president", "", "FIN", None) is None)

    o = override("Principal", None, None, "EDU", "EDU.K12")
    check("K-12 principal", o and o.occupation_code == "11-9032" and o.reason == "k12_principal")
    o = override("Assistant Principal", "assistant", "principal", "EDU", "EDU.K12")
    check("assistant principal", o and o.occupation_code == "11-9032")
    o = override("Principal", None, None, "EDU", None)
    check("principal at EDU with no L2 fires", o and o.occupation_code == "11-9032")
    check("principal at higher ed untouched", override("Principal", None, None, "EDU", "EDU.HED") is None)
    check("principal at consulting untouched (firm_principal dropped)",
          override("Principal", None, None, "PRO", "PRO.CONSL") is None)
    check("Principal Software Engineer untouched",
          override("Principal Software Engineer", "engineer software", "principal", "TEC", None) is None)

    o = override("Partner", "partner", "", "PRO", "PRO.LEGAL")
    check("law partner", o and o.occupation_code == "23-1011" and o.reason == "law_firm_partner")
    o = override("Associate", None, None, "PRO", "PRO.LEGAL")
    check("law associate", o and o.occupation_code == "23-1011")
    o = override("Principal", None, None, "PRO", "PRO.LEGAL")
    check("law-firm principal is a lawyer", o and o.occupation_code == "23-1011")
    o = override("Partner.", "partner", "", "PRO", "PRO.LEGAL")
    check("trailing punctuation normalized", o and o.occupation_code == "23-1011")
    check("Associate at a bank untouched", override("Associate", None, None, "FIN", "FIN.BNK") is None)
    check("Partner at consulting untouched", override("Partner", "partner", "", "PRO", "PRO.CONSL") is None)
    check("Paralegal at a law firm untouched", override("Paralegal", "paralegal", "", "PRO", "PRO.LEGAL") is None)
    check("empty title", override("", "", "", "PRO", "PRO.LEGAL") is None)
    print("override tests passed")


if __name__ == "__main__":
    main()
