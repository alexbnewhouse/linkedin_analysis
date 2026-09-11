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
from edu_clean.final_hybrid import (
    DEGREE_LEVEL_ORDINAL,
    FIELD_CIP_ALIASES,
    FIELD_CIP_OVERRIDES,
    canon_field,
    canon_title_value,
    degree_field_signal,
    parse_degree,
    raw_id,
    safe_norm,
)


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

    # --- junk / nullish extensions (audit Finding 5) ---
    for junk in ["4.0", "12", "A", "3.8 GPA", "12th", "9-12", "Junior", "Cum Laude", "Graduated"]:
        assert_equal(raw_id("field_raw", junk), "field_raw:__blank__", f"junk field {junk!r}")
    assert_not_equal(raw_id("field_raw", "A Levels"), "field_raw:__blank__", "'A Levels' is not junk")

    # --- degree taxonomy tail categories (audit Finding 5) ---
    assert_equal(parse_degree("Undergraduate")[0], "undergraduate:generic", "Undergraduate level")
    assert_equal(parse_degree("Graduate")[0], "graduate:generic", "Graduate level")
    assert_equal(parse_degree("Postgraduate Degree")[0], "postgraduate:generic", "Postgraduate level")
    assert_equal(parse_degree("Minor")[0], "minor:generic", "Minor category")
    assert_equal(parse_degree("Study Abroad")[0], "study_abroad:generic", "Study Abroad category")
    assert_equal(parse_degree("High School Graduate")[0], "high_school:generic", "HS graduate stays HS")
    assert_not_equal(parse_degree("Minority Leadership Program")[0], "minor:generic",
                     "'Minority' must not parse as minor")
    assert_equal(parse_degree("Graduated")[0], "degree_raw:__blank__", "'Graduated' is junk, not a level")
    # ordinal sanity: HS=1 ... doctorate=7; minor/study_abroad carry no level
    assert_equal(DEGREE_LEVEL_ORDINAL["high_school"], 1, "HS ordinal")
    assert_equal(DEGREE_LEVEL_ORDINAL["bachelor"], 4, "bachelor ordinal")
    assert_equal(DEGREE_LEVEL_ORDINAL["doctorate"], 7, "doctorate ordinal")
    for lvl in ("minor", "study_abroad"):
        if lvl in DEGREE_LEVEL_ORDINAL:
            raise AssertionError(f"{lvl} must not carry a level ordinal")

    # --- degree -> field cross-pass (audit Finding 2) ---
    assert_equal(degree_field_signal("Computer Science"), ("11.07", True), "degree cell is a CIP title")
    assert_equal(
        degree_field_signal("Business Administration and Management, General"),
        ("52.0201", True),
        "verbatim CIP title in degree cell",
    )
    assert_equal(
        degree_field_signal("Bachelor of Science in Computer Science"),
        ("11.07", False),
        "subject extracted from 'Bachelor of X in Y'",
    )
    assert_equal(degree_field_signal("Bachelor of Science - BS"), None, "plain degree has no field signal")
    assert_equal(degree_field_signal("MBA"), None, "abbrev degree has no field signal")
    assert_equal(parse_degree("Computer Science"),
                 ("degree_raw:computer science", "raw", 0.5),
                 "parse_degree itself leaves the swap to canon_degree")

    # --- 2-digit CIP family admission + alias expansion (audit Finding 3) ---
    fields = canon_field(
        [
            ("BUSINESS, MANAGEMENT, MARKETING, AND RELATED SUPPORT SERVICES", 1),
            ("Social Sciences", 1),
            ("Engineering", 1),
            ("English Language and Literature/Letters", 1),
            ("English Language and Literature, General", 1),
            ("Data Science", 1),
            ("Business Analytics", 1),
            ("Cybersecurity", 1),
            ("Cyber Security", 1),
            ("English", 1),
            ("Geology", 1),
            ("Theatre", 1),
            ("Theater", 1),
        ]
    ).mapping
    assert_equal(
        fields["BUSINESS, MANAGEMENT, MARKETING, AND RELATED SUPPORT SERVICES"],
        "cip:52",
        "verbatim CIP family title -> family code",
    )
    assert_equal(fields["Social Sciences"], "cip:45.01", "family must not displace token match")
    assert_equal(fields["Engineering"], "cip:14.01", "family must not displace 'Engineering, General'")
    assert_equal(
        fields["English Language and Literature/Letters"],
        fields["English Language and Literature, General"],
        "family-23 title keeps merging with the 23.01 group (gold)",
    )
    assert_equal(fields["Data Science"], "cip:30.70", "CIP 2020 Data Science")
    assert_equal(fields["Business Analytics"], "cip:30.7102", "CIP 2020 Business Analytics")
    assert_equal(fields["Cybersecurity"], fields["Cyber Security"], "cybersecurity alias variants merge")
    assert_equal(fields["English"], "cip:23.01", "English alias")
    assert_equal(fields["Geology"], "cip:40.0601", "Geology alias")
    assert_equal(fields["Theatre"], fields["Theater"], "Theatre/Theater merge")

    # every curated alias/override target must exist in the CIP reference
    import csv as _csv

    from edu_clean.humanities import CIP_CSV

    with CIP_CSV.open(newline="", encoding="utf-8") as fh:
        known = {(row.get("CIPCode") or "").strip() for row in _csv.DictReader(fh)}
    for label, code in {**FIELD_CIP_ALIASES, **FIELD_CIP_OVERRIDES}.items():
        if code not in known:
            raise AssertionError(f"alias/override target {code!r} for {label!r} not in cip_codes.csv")


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


def check_location() -> None:
    """Finding 6: deterministic head gazetteer (country -> US state -> city/
    metro). Precision-first: anything unrecognized stays unparsed, the raw
    string is always preserved in career_steps."""
    from career_clean.location import parse_location

    # canonical 3-segment form
    assert_equal(
        parse_location("New York, New York, United States"),
        ("US", "NY", "new york", "city_state_country", 1.0),
        "city, state, country",
    )
    # 2-letter USPS code form
    assert_equal(
        parse_location("Chicago, IL"),
        ("US", "IL", "chicago", "city_state", 1.0),
        "city, 2-letter state",
    )
    # state spelled out, no country
    assert_equal(
        parse_location("Houston, Texas"),
        ("US", "TX", "houston", "city_state", 1.0),
        "city, full state name",
    )
    # '<State> Area' suffix form
    assert_equal(
        parse_location("Houston, Texas Area"),
        ("US", "TX", "houston", "city_state", 1.0),
        "city, state + Area suffix",
    )
    # state-only and country-only
    assert_equal(parse_location("California, United States"),
                 ("US", "CA", None, "state_country", 1.0), "state, country")
    assert_equal(parse_location("New Jersey"),
                 ("US", "NJ", None, "state", 1.0), "bare state")
    assert_equal(parse_location("United States"),
                 ("US", None, None, "country", 1.0), "bare country")
    assert_equal(parse_location("India"),
                 ("IN", None, None, "country", 1.0), "bare non-US country")
    # metro head gazetteer
    assert_equal(parse_location("Greater New York City Area"),
                 ("US", "NY", "new york", "metro", 0.95), "Greater X Area")
    assert_equal(parse_location("San Francisco Bay Area"),
                 ("US", "CA", "san francisco", "metro", 0.95), "Bay Area")
    assert_equal(parse_location("New York City Metropolitan Area"),
                 ("US", "NY", "new york", "metro", 0.95), "X Metropolitan Area")
    assert_equal(parse_location("Washington D.C. Metro Area"),
                 ("US", "DC", "washington", "metro", 0.95), "DC metro")
    assert_equal(parse_location("Dallas/Fort Worth Area"),
                 ("US", "TX", "dallas-fort worth", "metro", 0.95), "DFW slash form")
    assert_equal(parse_location("Dallas-Fort Worth Metroplex"),
                 ("US", "TX", "dallas-fort worth", "metro", 0.95), "DFW metroplex")
    assert_equal(parse_location("Greater Minneapolis-St. Paul Area"),
                 ("US", "MN", "minneapolis-st. paul", "metro", 0.95), "MSP metro")
    # the same place converges across spellings (the audit's New York example)
    ny = {"New York, NY", "New York, New York, United States",
          "Greater New York City Area", "New York City Metropolitan Area"}
    assert_equal(
        {parse_location(v)[:3] for v in ny},
        {("US", "NY", "new york")},
        "New York variants converge to one (country, state, city)",
    )
    # bare-city aliases (curated, unambiguous head only)
    assert_equal(parse_location("NYC"),
                 ("US", "NY", "new york", "city_alias", 0.9), "NYC alias")
    assert_equal(parse_location("Chicago"),
                 ("US", "IL", "chicago", "city_alias", 0.9), "bare Chicago")
    # non-US city, country
    assert_equal(parse_location("London, United Kingdom"),
                 ("GB", None, "london", "city_country", 1.0), "London UK")
    assert_equal(parse_location("Hyderabad, Telangana, India"),
                 ("IN", None, "hyderabad", "city_country", 1.0), "Indian 3-segment")
    # remote / empty / junk stay honest
    assert_equal(parse_location("Remote"), (None, None, None, "remote", 1.0), "Remote")
    assert_equal(parse_location(None), (None, None, None, "empty", 0.0), "None")
    assert_equal(parse_location("  "), (None, None, None, "empty", 0.0), "blank")
    assert_equal(parse_location("Somewhere Nice"),
                 (None, None, None, "unparsed", 0.0), "unknown stays unparsed")
    # precision guards: lowercase 2-letter words are NOT state codes; 'Georgia'
    # the country is shadowed by the state (US-centric corpus, accepted)
    assert_equal(parse_location("Make it, in time")[3], "unparsed",
                 "lowercase 'in' is not Indiana")


def check_build_bootstrap() -> None:
    """Audit 2026-09-02 (refactor s0 / H8): a fresh clone must be able to build
    career_steps BEFORE the SOC jury has ever run -- the jury mapping is an
    optional, propose-only input, not a hard dependency."""
    import tempfile
    from pathlib import Path

    import build_normalized as B

    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        (out / "mappings").mkdir()
        for name in ("edu_degree", "edu_degree_field", "edu_school", "edu_field",
                     "career_company", "career_company_id_alias", "career_title",
                     "career_occupation", "career_functional_cluster", "career_location"):
            (out / "mappings" / f"{name}.parquet").touch()
        # every required mapping present, the jury mapping absent
        paths = B.build_mappings(out, [], "all", skip=True)
        assert_equal(paths["role_soc_jury"].exists(), False, "jury mapping absent in fixture")
        rel = B._optional_mapping_relation(paths["role_soc_jury"],  # noqa: SLF001
                                           "role_canonical VARCHAR, soc_major VARCHAR")
        import duckdb
        n = duckdb.connect().execute(f"SELECT count(*) FROM {rel}").fetchone()[0]
        assert_equal(n, 0, "missing jury mapping reads as an empty relation")
        present = out / "mappings" / "career_company.parquet"
        rel2 = B._optional_mapping_relation(present, "value VARCHAR")  # noqa: SLF001
        assert_equal("read_parquet" in rel2, True, "present mapping reads the parquet")


def check_freshness_logic() -> None:
    """scripts/check_freshness.py: an output is stale when any input is newer
    than its manifest, or the manifest is missing."""
    import importlib.util
    import os
    import tempfile
    import time
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "check_freshness", Path(__file__).parent / "scripts" / "check_freshness.py")
    cf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cf)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        old, new, manifest = d / "old", d / "new", d / "manifest.json"
        old.touch(); manifest.touch(); new.touch()
        t = time.time()
        os.utime(old, (t - 100, t - 100)); os.utime(manifest, (t - 50, t - 50)); os.utime(new, (t, t))
        assert_equal(cf.stale_inputs(manifest, [old]), [], "older input is fresh")
        assert_equal(cf.stale_inputs(manifest, [old, new]), [new], "newer input is stale")
        assert_equal(cf.stale_inputs(d / "missing.json", [old]), [old], "missing manifest -> all stale")
        assert_equal(cf.stale_inputs(manifest, [d / "absent"]), [], "absent inputs are ignored")


def check_employment_sql_mirrors_buckets() -> None:
    """The SQL that derives employment_type from a company placeholder must
    apply the same bucket -> employment overrides as
    career_rules.placeholder_to_employment (none -> unknown,
    private_household -> employee, ...), or Python and the build drift."""
    import build_normalized as B
    from career_clean import approach_a_rules as A
    sql = B._EMPLOYMENT_TYPE_SQL  # noqa: SLF001
    for bucket, emp in A._BUCKET_TO_EMPLOYMENT.items():  # noqa: SLF001
        if emp != bucket:
            assert f"'nonorg:{bucket}' THEN '{emp}'" in sql, (bucket, emp)
    assert "substr(company.canonical_id, 8)" in sql
    print("employment_type SQL mirrors the placeholder bucket overrides")


def main() -> None:
    check_education()
    check_career()
    check_seniority_rank_and_display()
    check_self_employed_clusters()
    check_location()
    check_build_bootstrap()
    check_freshness_logic()
    check_employment_sql_mirrors_buckets()
    print("normalization regression checks passed")


if __name__ == "__main__":
    main()
