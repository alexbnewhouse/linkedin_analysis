"""Focused regression checks for education/career normalization.

Run with:

    uv run python normalization_regression_checks.py

These checks cover high-value edge cases that are not represented in the small
gold-pair benchmark files.
"""

from __future__ import annotations

from career_clean.approach_a_rules import (
    parse_title,
    seniority_rank_tokens,
    title_display_base,
)
from career_clean.final_hybrid import (
    canon_company_value,
    canon_employment_type_value,
    canon_functional_cluster_value,
    canon_title,
)
from career_clean.occupation import load_onet
from career_clean.occupation import canon_occupation
from edu_clean.final_hybrid import canon_field, canon_title_value, safe_norm


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_not_equal(left, right, label: str) -> None:
    if left == right:
        raise AssertionError(f"{label}: both values were {left!r}")


def check_education() -> None:
    field_values = [
        ("Music", 1),
        ("Art", 1),
        ("Biology/Biological Sciences, General", 1),
        ("Biology, General", 1),
    ]
    fields = canon_field(field_values).mapping
    assert_equal(fields["Music"], "cip:50.09", "Music should not map to remedial CIP")
    if fields["Art"].startswith("cip:36."):
        raise AssertionError(f"Art mapped to invalid remedial CIP: {fields['Art']}")
    assert_equal(
        fields["Biology/Biological Sciences, General"],
        fields["Biology, General"],
        "Biology general variants should share the chosen CIP group",
    )

    title_id, method, confidence = canon_title_value(
        "Ambiguous School",
        url="https://www.linkedin.com/school/example-school/?trk=profile",
    )
    assert_equal(title_id, "slug:example-school", "row-level school slug")
    assert_equal(method, "slug", "row-level school method")
    assert_equal(confidence, 1.0, "row-level school confidence")
    assert_equal(safe_norm("Universidade de Sao Paulo"), "universidade de sao paulo", "ASCII norm")
    assert_equal(safe_norm("Universidade de São Paulo"), "universidade de sao paulo", "accent fold")


def check_career() -> None:
    title_values = [
        ("C++ Developer", 1),
        ("C# Developer", 1),
        ("C Developer", 1),
        ("R&D Engineer", 1),
        ("Research and Development Engineer", 1),
    ]
    titles = canon_title(title_values).mapping
    assert_not_equal(titles["C++ Developer"], titles["C# Developer"], "C++ vs C#")
    assert_not_equal(titles["C++ Developer"], titles["C Developer"], "C++ vs C")
    assert_not_equal(titles["C# Developer"], titles["C Developer"], "C# vs C")
    assert_equal(
        titles["R&D Engineer"],
        titles["Research and Development Engineer"],
        "R&D expansion",
    )
    assert_not_equal(parse_title("PM"), parse_title("Project Manager"), "ambiguous PM")

    cid, method, confidence = canon_company_value(
        "Self-employed", company_id="some-noisy-company-id"
    )
    assert_equal(cid, "nonorg:self_employed", "placeholder before company id")
    assert_equal(method, "placeholder", "placeholder method")
    assert_equal(confidence, 1.0, "placeholder confidence")
    cid, method, confidence = canon_company_value("KPMG", company_id="kpmg")
    assert_equal(cid, "id:kpmg", "row-level company id")
    assert_equal(method, "company_id", "row-level company method")
    assert_equal(confidence, 1.0, "row-level company confidence")

    occupation_values = [
        ("RN", 1),
        ("Registered Nurse", 1),
        ("CEO", 1),
        ("Chief Executive Officer", 1),
        ("Chief Technology Officer", 1),
    ]
    occupations, _methods = canon_occupation(occupation_values)
    assert_equal(occupations["Registered Nurse"], "soc:29-1141", "Registered Nurse")
    assert_equal(occupations["RN"], "soc:29-1141", "RN")
    assert_equal(occupations["Chief Executive Officer"], "soc:11-1011", "CEO phrase")
    assert_equal(occupations["CEO"], "soc:11-1011", "CEO")
    assert_equal(occupations["Chief Technology Officer"], "soc:11-1011", "CTO phrase")

    emp, method, confidence = canon_employment_type_value(
        company="Self-employed",
        title="Graphic Designer",
        company_id="some-noisy-company-id",
    )
    assert_equal(emp, "self_employed", "self-employed company placeholder")
    assert_equal(method, "company_placeholder", "company placeholder employment method")
    assert_equal(confidence, 1.0, "company placeholder employment confidence")
    emp, _method, _confidence = canon_employment_type_value(
        company="Self-employed",
        title="Retired",
    )
    assert_equal(emp, "retired", "retired title wins over self-employed company")
    emp, _method, _confidence = canon_employment_type_value(
        company="Deloitte",
        title="Freelance Graphic Designer",
    )
    assert_equal(emp, "self_employed", "freelance title marker")
    emp, _method, _confidence = canon_employment_type_value(
        company="Deloitte",
        title="Consultant",
    )
    assert_equal(emp, "employee", "uncorroborated consultant stays employee")
    emp, _method, _confidence = canon_employment_type_value(
        company="Deloitte",
        title="Independent Consultant",
    )
    assert_equal(emp, "self_employed", "independent consultant title marker")
    emp, _method, _confidence = canon_employment_type_value(
        company="Example LLC",
        title="Founder",
    )
    assert_equal(emp, "business_owner", "founder title marker")

    occupation_values = [
        ("Freelance Graphic Designer", 1),
        ("Private Tutor", 1),
        ("Owner", 1),
        ("Retired", 1),
    ]
    occupations, methods = canon_occupation(occupation_values)
    assert_equal(
        occupations["Freelance Graphic Designer"],
        "soc:27-1024",
        "freelance graphic designer recovered from stripped title",
    )
    assert_equal(occupations["Private Tutor"], "soc:25-3041", "private tutor raw match")
    assert_equal(occupations["Owner"], "raw:owner", "bare owner must not map to SOC")
    assert_equal(methods["Owner"], "blocked_generic_status", "bare owner guard method")
    assert_equal(occupations["Retired"], "raw:retired", "retired must not map to SOC")


def check_seniority_rank_and_display() -> None:
    """Finding 2/5: the separate seniority-rank axis and the human-readable
    role_display label -- neither may change the title canonical identity."""
    # extended rank lexicon: manager/supervisor are rank tokens here ...
    assert_equal(seniority_rank_tokens("Account Manager"), "manager", "manager rank token")
    assert_equal(seniority_rank_tokens("Shift Supervisor"), "supervisor", "supervisor rank token")
    assert_equal(
        seniority_rank_tokens("Sr. Engineering Mgr"), "manager,senior",
        "abbreviations expand before rank extraction; sorted set",
    )
    assert_equal(seniority_rank_tokens("VP of Sales"), "vice", "vp -> vice rank token")
    assert_equal(seniority_rank_tokens("Software Engineer"), "", "no rank words -> empty")
    assert_equal(seniority_rank_tokens("Software Engineer II"), "lvl2", "roman numeral band")
    assert_equal(seniority_rank_tokens(None), "", "None title -> empty")
    # 'gm'/'md' are NOT in the lexicon (md = Medical Doctor; not precision-safe)
    assert_equal(seniority_rank_tokens("MD"), "", "md is ambiguous, not a rank token")
    assert_equal(seniority_rank_tokens("GM"), "", "gm is ambiguous, not a rank token")
    # ... but they must NOT touch the level signature / base identity
    assert_equal(parse_title("Account Manager")[0], "", "manager is not a level token")
    assert_equal(parse_title("Account Manager")[1], "account manager", "manager stays in the base")
    assert_equal(parse_title("Shift Supervisor")[0], "", "supervisor is not a level token")
    # numeric-band clamp: 2-digit numbers in titles are noise, not levels
    assert_equal(parse_title("Region 12")[0], "", "two-digit number is not a level")
    assert_equal(parse_title("Engineer 3")[0], "lvl3", "single digit 1-5 is a level band")
    assert_equal(parse_title("Engineer 7")[0], "", "digits above 5 are not levels")
    assert_equal(seniority_rank_tokens("Region 12"), "", "rank axis applies the same clamp")
    # role_display: modal level-free raw spelling per base, level words stripped
    res = canon_title([
        ("Software Engineer", 100),
        ("Sr. Software Engineer", 10),
        ("software engineer", 5),
        ("Senior Software Engineer", 8),
    ])
    disp = res.aux["role_display"]
    assert_equal(disp["Sr. Software Engineer"], "Software Engineer", "display strips seniority")
    assert_equal(disp["software engineer"], "Software Engineer", "display uses the modal spelling")
    ranks = res.aux["seniority_rank_token"]
    assert_equal(ranks["Sr. Software Engineer"], "senior", "rank token carried in aux")
    assert_equal(ranks["Software Engineer"], "", "no rank token -> empty string")
    # fallback when no level-free spelling exists: ordered base, title-cased
    res = canon_title([("Senior Underwriting Strategist", 3)])
    assert_equal(
        res.aux["role_display"]["Senior Underwriting Strategist"],
        "Underwriting Strategist",
        "fallback display = original-order base, level words stripped",
    )
    assert_equal(title_display_base("VP of Sales"), "President of Sales", "display base keeps order")


def check_self_employed_clusters() -> None:
    """The three self-employment meaning-extraction recs (se_cluster/se_qualifier/
    se_personal_brand), routed through the production row-level entry point."""
    by_norm, by_tokens, _ = load_onet()
    idx = (by_norm, by_tokens)

    def fc(company, title, **kw):
        return canon_functional_cluster_value(
            company=company, title=title, onet_index=idx, **kw
        )

    # Rec 1: qualifier recovery (strip the ownership/consulting/freelance shell)
    cl, method, _c = fc("Self-employed", "IT Consultant")
    assert_equal((cl, method), ("15", "qualifier"), "IT Consultant -> Computer via qualifier")
    cl, _m, _c = fc("Self-employed", "Restaurant Owner")
    assert_equal(cl, "35", "Restaurant Owner -> Food via qualifier")
    cl, _m, _c = fc("Self-employed", "Management Consultant")
    assert_equal(cl, "11", "Management Consultant -> Management, not Military(55)")
    # Rec 2: personal-brand company trade for a bare-owner title (no company_id)
    cl, method, _c = fc("Smith Photography", "Owner")
    assert_equal((cl, method), ("27", "company_brand"), "photography brand owner -> Arts")
    # a real company_id is not a personal brand -> not keyword-guessed
    cl, method, _c = fc("Anytime Fitness", "Owner", company_id="anytime-fitness")
    assert_equal(method, "unspecified", "real-company owner is not brand-guessed")
    # title keyword for a bare ambiguous occupation noun
    cl, method, _c = fc("Self-employed", "Artist")
    assert_equal((cl, method), ("27", "title_keyword"), "Artist -> Arts via title keyword")
    # Rec 4: free-text description infers the cluster for a bare-owner residue
    cl, method, _c = fc("Self-employed", "Owner",
                        description="We provide residential plumbing and heating repair.")
    assert_equal((cl, method), ("47", "description"), "description -> Construction")
    # the "it" keyword must not fire on the pronoun "it" in prose
    cl, method, _c = fc("Self-employed", "Founder",
                        description="I help teams take ownership of it and build culture.")
    assert_equal(method, "unspecified", "pronoun 'it' must not trigger IT cluster")
    # honest residue: genuinely signal-free stays unspecified
    cl, method, _c = fc("Self-employed", "Business Owner")
    assert_equal(method, "unspecified", "bare Business Owner -> unspecified")


def main() -> None:
    check_education()
    check_career()
    check_seniority_rank_and_display()
    check_self_employed_clusters()
    print("normalization regression checks passed")


if __name__ == "__main__":
    main()
