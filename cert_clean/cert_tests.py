"""Logic tests for the certification domain classifier (data-independent)."""

from __future__ import annotations

from cert_clean.domains import DOMAINS, KEYWORD_RULES, classify, curated_map


def test_curated_head() -> None:
    cases = {
        "Project Management Professional (PMP)": ("pm", "curated"),
        "PMP": ("pm", "curated"),
        "Registered Nurse": ("health", "curated"),
        "CompTIA Security+": ("it_sec", "curated"),
        # ® variant normalizes onto the same curated key
        "Project Management Professional (PMP)®": ("pm", "curated"),
        # adjudicated fixes hold
        "Certified Professional Coder (CPC)": ("health", "curated"),
        "Secret Security Clearance": ("other", "curated"),
    }
    for title, (dom, method) in cases.items():
        got_dom, got_method, conf = classify(title)
        assert got_dom == dom and got_method == method, (title, got_dom, got_method)
        assert conf is not None and conf >= 0.9


def test_keyword_tail() -> None:
    cases = {
        "AWS Solutions Architect Professional": "it_cloud",
        "Advanced Scrum Master Workshop": "pm",
        "State of Texas Real Estate Salesperson License": "fin",
        "Pediatric Nurse Practitioner Cert": "health",
        "Forklift Operator": "trades",
        "TIPS Certified Bartender": "food",
        "Unarmed Security Guard License": "trades",
    }
    for title, dom in cases.items():
        got_dom, got_method, _ = classify(title)
        assert got_dom == dom, (title, got_dom)
        assert got_method in ("curated", "keyword")


def test_nulls_and_unknowns() -> None:
    assert classify(None) == (None, None, None)
    assert classify("   ") == (None, None, None)
    dom, method, conf = classify("Honored Listee")  # curated 'other'
    assert dom == "other" and method == "curated"
    dom, _, _ = classify("Zorbltak Prize")  # matches nothing
    assert dom is None


def test_taxonomy_integrity() -> None:
    assert set(curated_map().values()) <= set(DOMAINS)
    for dom, needles in KEYWORD_RULES:
        assert dom in DOMAINS
        for n in needles:
            assert n == n.lower() and n.strip(), n


def main() -> None:
    test_curated_head()
    test_keyword_tail()
    test_nulls_and_unknowns()
    test_taxonomy_integrity()
    print("cert_clean tests passed")


if __name__ == "__main__":
    main()
