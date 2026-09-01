"""Unit tests for archetype assignment — run with: python -m archetypes.archetype_tests

Pure-logic tests over archetype_spec.assign_role (no data files needed) plus a
couple of invariant checks. Includes regressions for the crosswalk/keyword bugs
found during the Phase-3 face-validity pass.
"""

from __future__ import annotations

from . import archetype_spec as S


def _key(soc_detail=None, soc_major=None, text="", owner=False) -> str:
    f = S.RoleFeatures(soc_detail=soc_detail, soc_major=soc_major,
                       role_text=text, employment_owner=owner)
    aid, _method, _conf = S.assign_role(f)
    return S.KEY_BY_ID[aid]


CASES = [
    # --- SOC detail routing ---
    ("teacher by SOC-25", dict(soc_detail="25-2021"), "educators"),
    ("registered nurse", dict(soc_detail="29-1141"), "healthcare"),
    ("software dev", dict(soc_detail="15-1252"), "tech"),
    ("accountant", dict(soc_detail="13-2011"), "finance"),
    ("mgmt analyst", dict(soc_detail="13-1111"), "analysts"),
    ("writer", dict(soc_detail="27-3043"), "writers"),
    ("graphic designer", dict(soc_detail="27-1024"), "creatives"),
    ("PR specialist", dict(soc_detail="27-3031"), "comms"),
    ("market research", dict(soc_detail="13-1161"), "comms"),
    ("sales rep", dict(soc_detail="41-4012"), "sales"),
    ("retail cashier -> hospitality", dict(soc_detail="41-2011"), "hospitality"),
    # REGRESSION: 11-2022 is Sales Managers, not marketing/comms
    ("sales manager (11-2022)", dict(soc_detail="11-2022", text="sales manager"), "sales"),
    ("marketing manager (11-2021)", dict(soc_detail="11-2021"), "comms"),

    # --- keyword-over-OTHER rescue (bad SOC codes) ---
    # REGRESSION: Project Manager mis-coded to construction (47) -> analysts
    ("project mgr miscoded 47", dict(soc_detail="47-1011", text="project manager"), "analysts"),
    ("systems engineer miscoded 47", dict(soc_major="47", text="system engineer"), "tech"),
    ("ops director miscoded 33", dict(soc_detail="33-1021", text="operations director of operations"), "managers"),
    # genuine trades with no rescuing keyword stay OTHER
    ("welder stays other", dict(soc_detail="51-4121", text="welder"), "other"),
    ("police officer stays other", dict(soc_detail="33-3051", text="police officer"), "other"),

    # --- SOC major + split refinement ---
    ("major 27 default creative", dict(soc_major="27", text="artist"), "creatives"),
    ("major 27 -> writer", dict(soc_major="27", text="staff writer"), "writers"),
    ("major 13 -> finance", dict(soc_major="13", text="senior accountant"), "finance"),
    ("major 11 -> comms", dict(soc_major="11", text="marketing manager"), "comms"),
    ("major 21 -> nonprofit", dict(soc_major="21", text="community organizer"), "nonprofit"),

    # --- nonprofit greedy-development regression ---
    ("biz dev is sales not nonprofit", dict(text="business development manager"), "sales"),
    ("product development not nonprofit", dict(text="product development manager"), "managers"),
    ("fundraising", dict(text="fundraising coordinator"), "nonprofit"),

    # --- keyword-only (no SOC) ---
    ("nurse keyword", dict(text="registered nurse"), "healthcare"),
    ("teacher keyword", dict(text="high school teacher"), "educators"),
    ("barista", dict(text="barista"), "hospitality"),

    # --- founders residual ---
    ("owner no trade -> founder", dict(text="owner", owner=True), "founders"),
    ("self-employed generic -> founder", dict(text="self-employed", owner=True), "founders"),
    # a self-employed photographer keeps the creative trade
    ("self-employed photographer stays creative",
     dict(soc_major="27", text="photographer", owner=True), "creatives"),

    # --- true residual ---
    ("empty -> other", dict(text=""), "other"),

    # --- red-team regressions (regex over-capture) ---
    ("supermarket cashier not comms", dict(text="supermarket cashier"), "hospitality"),
    ("capital markets analyst not comms",
     dict(soc_major="13", text="capital markets analyst"), "analysts"),
    ("farmers market vendor not comms", dict(text="farmers market vendor"), "other"),
    ("marketing manager still comms", dict(text="marketing manager"), "comms"),
    ("R&D associate not nonprofit",
     dict(text="research and development associate"), "legal"),
    ("learning & development not nonprofit",
     dict(text="learning and development manager"), "managers"),
    ("land development officer not nonprofit",
     dict(text="land development officer"), "other"),
    ("director of development still nonprofit",
     dict(text="director of development"), "nonprofit"),
    ("generic development director -> managers (ambiguous, not nonprofit)",
     dict(text="development director"), "managers"),
    ("insurance producer not creative", dict(text="insurance producer"), "sales"),
    ("film producer still creative", dict(text="film producer"), "creatives"),
    ("user researcher not legal", dict(text="user researcher"), "tech"),
    ("policy researcher still legal", dict(text="policy researcher"), "legal"),
    # self-employed tradesperson routed to OTHER by SOC -> Founders
    ("owner welder -> founders",
     dict(soc_major="47", text="welder owner", owner=True), "founders"),

    # --- math-audit regressions (fallthrough contracts) ---
    ("unknown SOC detail falls through to keyword",
     dict(soc_detail="99-9999", text="teacher"), "educators"),
    ("bare trades major no keyword -> other", dict(soc_major="51", text=""), "other"),
]


def run() -> int:
    fails = 0
    for name, kw, expected in CASES:
        got = _key(**kw)
        ok = got == expected
        if not ok:
            fails += 1
            print(f"FAIL  {name}: expected {expected!r}, got {got!r}")
    # invariants
    assert len(S.ARCHETYPES) == 16, "15 substantive + OTHER"
    assert len({a[0] for a in S.ARCHETYPES}) == 16, "unique ids"
    assert len({a[1] for a in S.ARCHETYPES}) == 16, "unique keys"
    for pre, key in S.SOC_DETAIL.items():
        assert key in S.ID_BY_KEY, f"bad SOC_DETAIL target {key}"
    for maj, key in S.SOC_MAJOR_DEFAULT.items():
        assert key in S.ID_BY_KEY, f"bad SOC_MAJOR_DEFAULT target {key}"
    print(f"\n{len(CASES)-fails}/{len(CASES)} assignment cases passed; invariants OK")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if run() else 0)
