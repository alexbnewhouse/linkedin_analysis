"""Tests for the company canonicalization axis (pure + tiny DuckDB fixtures).

    uv run python -m career_clean.company_tests

Audit 2026-09-02 (red C1/M3/M5, green E1): the value-level modal company_id
must be SUPPORTED before id-less rows inherit it; placeholders must not become
employers; the fuzzy typo tier must never merge empty/non-Latin strings; and
university employers keyed by a ``linkedin.com/school/<slug>`` URL get a
stable ``id:`` key.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb

from career_clean import approach_a_rules as R
from career_clean import common as CC
from career_clean.approach_a_rules import placeholder_to_employment
from career_clean.final_hybrid import canon_company, canon_company_value


def ok(name: str) -> None:
    print(f"  ok: {name}")


def _vocab_from_rows(rows: list[tuple[str, str | None]]) -> dict[str, tuple]:
    """Run the production company-vocab SQL over an in-memory experience table
    and return {value: (freq, modal_id)}."""
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "experience.parquet"
        con = duckdb.connect()
        con.execute("CREATE TABLE e (company VARCHAR, company_id VARCHAR)")
        con.executemany("INSERT INTO e VALUES (?, ?)", rows)
        con.execute(f"COPY e TO '{src}' (FORMAT parquet)")
        out = Path(d) / "vocab.parquet"
        con.execute(CC.company_vocab_sql(f"read_parquet('{src}')", out))
        got = con.execute(
            f"SELECT value, freq, modal_id FROM read_parquet('{out}')").fetchall()
        return {v: (f, m) for v, f, m in got}


def test_modal_id_support_gate() -> None:
    rows = []
    # 5 rows, 2 with the same id: below MIN_ID_ROWS -> no inherited id
    rows += [("Weak Co", "weak")] * 2 + [("Weak Co", None)] * 3
    # 6 rows, 3 with the same id (50%): supported
    rows += [("Half Co", "half")] * 3 + [("Half Co", None)] * 3
    # 100 rows, 49 ids: below 50% share -> no inherited id
    rows += [("Minority Co", "minor")] * 49 + [("Minority Co", None)] * 51
    # the university pattern: 2,872 rows, 2 with a stray sub-page id
    rows += [("University of Michigan", "center-for-managing-chronic-disease")] * 2
    rows += [("University of Michigan", None)] * 40
    # all rows carry the id: trivially supported
    rows += [("Google", "google")] * 4
    v = _vocab_from_rows(rows)
    assert v["Weak Co"] == (5, None), v["Weak Co"]
    assert v["Half Co"] == (6, "half"), v["Half Co"]
    assert v["Minority Co"] == (100, None), v["Minority Co"]
    assert v["University of Michigan"] == (42, None), v["University of Michigan"]
    assert v["Google"] == (4, "google"), v["Google"]
    ok("modal company_id is gated on >= max(MIN_ID_ROWS, MIN_ID_SHARE) support")


def test_placeholders() -> None:
    for value, bucket in (
        ("Independent", "self_employed"), ("Consultant", "self_employed"),
        ("Consulting", "self_employed"), ("Contractor", "self_employed"),
        ("Contract", "self_employed"), ("Myself", "self_employed"),
        ("Me", "self_employed"), ("Own Business", "self_employed"),
        ("Entrepreneur", "self_employed"), ("Home", "none"),
        ("TBD", "none"), (".", "none"), ("-", "none"), ("--", "none"),
        ("_", "none"), ("N/A", "none"),
    ):
        cid, method, _ = canon_company_value(value, company_id="stray-id")
        assert cid == f"nonorg:{bucket}" and method == "placeholder", (value, cid, method)
    ok("placeholders resolve to nonorg even when a stray company_id is attached")
    # status strings that surfaced as the top "employers" of the unresolved
    # industry head on 2026-09-02 (Stay at Home Mom 453 rows, In Transition,
    # Private Company 841, self-emplyed, Profesional independiente, ...)
    for value, bucket in (
        ("Stay at Home Mom", "homemaker"), ("Stay-at-Home Dad", "homemaker"),
        ("SAHM", "homemaker"), ("Full time parent", "homemaker"), ("Housewife", "homemaker"),
        ("Home maker", "homemaker"), ("Mother", "homemaker"),
        ("self-emplyed", "self_employed"), ("Self Emplyoed", "self_employed"),
        ("Profesional independiente", "self_employed"), ("Independent Professional", "self_employed"),
        ("Independent Artist", "self_employed"), ("Independent Researcher", "self_employed"),
        ("Author", "self_employed"), ("Writer", "self_employed"), ("Poet", "self_employed"),
        ("Self Published Author", "self_employed"), ("Artist", "self_employed"),
        ("Musician", "self_employed"), ("My Own Company", "self_employed"),
        ("Myself as an independent consultant", "self_employed"), ("Solopreneur", "self_employed"),
        ("Personal Projects", "self_employed"),
        ("In Transition", "career_break"), ("Career Break", "career_break"),
        ("On Sabbatical", "career_break"), ("Sabbatical leave", "career_break"),
        ("Seeking New Opportunities", "unemployed"), ("Actively seeking employment", "unemployed"),
        ("Looking for job", "unemployed"), ("Looking for new opporunity", "unemployed"),
        ("Open to work", "unemployed"), ("Open to new opportunities", "unemployed"),
        ("Between jobs", "unemployed"), ("Job Seeker", "unemployed"),
        ("Not currently employed", "unemployed"), ("Not working", "unemployed"),
        ("Currently unemployed", "unemployed"), ("Retiree", "retired"), ("None (retired)", "retired"),
        ("None at this time", "none"), ("Not applicable", "none"), ("Not available", "none"),
        ("At home", "none"), ("Work from home", "none"), ("Home Office", "none"), ("Personal", "none"),
        ("Multiple Companies", "various"), ("Multiple clients", "various"), ("Miscellaneous", "various"),
        ("Confidential Company", "confidential"), ("Confidential family office", "confidential"),
        ("Anonymous", "confidential"), ("Private Company", "confidential"), ("Private Client", "confidential"),
        ("Private Employer", "confidential"), ("Private Investor", "confidential"),
        ("Private Family", "private_household"), ("Private Household", "private_household"),
        ("Private Residence", "private_household"), ("Private Home", "private_household"),
        ("Private families", "private_household"),
        ("Volunteer", "volunteer"), ("Volunteer work", "volunteer"),
    ):
        cid, method, _ = canon_company_value(value, company_id="stray-id")
        assert cid == f"nonorg:{bucket}" and method == "placeholder", (value, cid, method)
    ok("status strings (stay-at-home, in transition, private company, ...) are placeholders")
    # real organisations that share a prefix with the new rules must survive
    for value in (
        "Seeking Alpha", "Independent Artist Group", "Homemaker Service Inc",
        "Family Office", "Self Regional Healthcare", "Self Magazine", "Entrepreneur Media",
        "Volunteer State Community College", "Volunteer Income Tax Assistance",
        "Private Equity Partners", "Stay at Home LLC", "Caregiver Inc", "Personal Capital",
        "Multiple Sclerosis Society", "Confidential Search Partners", "Open Table",
        "Mother Jones", "Artist Management Group", "Writer's Digest", "Author Solutions",
        "Independent Bank", "Independent Film", "Looking Glass Studios",
    ):
        cid, method, _ = canon_company_value(value, company_id="real-id")
        assert cid == "id:real-id" and method == "company_id", (value, cid, method)
    ok("organisations sharing a prefix with a status rule keep their company_id")
    assert placeholder_to_employment("private_household") == "employee"
    assert placeholder_to_employment("career_break") == "career_break"
    assert placeholder_to_employment("volunteer") == "volunteer"
    ok("new buckets map onto the employment axis (household work is employment)")


def test_non_latin_and_short_values_never_fuzzy_merge() -> None:
    vocab = [
        ("Acme Corporation", 100, "acme"),
        ("Acme Corporetion", 1, None),   # a typo twin (same metaphone block) -> merges onto the id
        ("프리랜서", 5, None),             # non-Latin: normalizes to '' -> stays raw
        ("美國加州大學柏克萊分校", 2, None),
        ("Предприниматель", 2, None),
        ("AB", 3, None),                  # too short to fuzzy-match safely
    ]
    res = canon_company(vocab)
    assert res.mapping["Acme Corporetion"] == "id:acme", res.mapping["Acme Corporetion"]
    assert res.method["Acme Corporetion"] == "typo_to_id"
    for v in ("프리랜서", "美國加州大學柏克萊分校", "Предприниматель", "AB"):
        assert res.mapping[v].startswith("raw:"), (v, res.mapping[v])
        assert res.method[v] == "raw", (v, res.method[v])
    # distinct non-Latin names must keep distinct raw keys
    assert res.mapping["프리랜서"] != res.mapping["Предприниматель"]
    ok("empty/short normalizations stay raw and distinct; real typos still merge")


def test_school_slug() -> None:
    cases = {
        "https://www.linkedin.com/school/rocky-vista-university/": "rocky-vista-university",
        "https://www.linkedin.com/school/uc-berkeley/?trk=public_profile_experience-group-header": "uc-berkeley",
        "https://in.linkedin.com/school/kamla-raheja-vidyanidhi/": "kamla-raheja-vidyanidhi",
        "https://www.linkedin.com/company/google/": None,
        "": None,
        None: None,
    }
    for url, want in cases.items():
        assert R.school_slug(url) == want, (url, R.school_slug(url), want)
    # the SQL form must agree with the Python form
    con = duckdb.connect()
    for url, want in cases.items():
        if url is None:
            continue
        got = con.execute(
            f"SELECT nullif(regexp_extract(?, '{R.SCHOOL_URL_RE}', 1), '')", [url]).fetchone()[0]
        assert got == want, (url, got, want)
    ok("school slug extracted from linkedin.com/school/<slug> URLs (Python and SQL agree)")


def main() -> None:
    test_modal_id_support_gate()
    test_placeholders()
    test_non_latin_and_short_values_never_fuzzy_merge()
    test_school_slug()
    print("All company canonicalization tests passed.")


if __name__ == "__main__":
    main()
